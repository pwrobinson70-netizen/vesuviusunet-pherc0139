"""
3D U-Net for Vesuvius Challenge ink detection.

Architecture idea (matches the shape of the reference approach used by top
Vesuvius Challenge / Kaggle "Ink Detection" solutions, e.g. `vesuvius_unet` in
https://github.com/ScrollPrize/villa): take a stack of CT slices around the
papyrus surface as a 3D patch (depth x height x width), run it through a 3D
U-Net, and collapse the resulting 3D logits volume down to a single 2D
ink-probability map by taking the max activation along the depth axis at
every (h, w) location. Max-projection lets the network "pick" whichever
z-slice shows the strongest ink evidence for that pixel, rather than forcing
one fixed slice to carry the signal.

This is an original, deliberately simplified re-implementation of that idea
for learning/experimentation on a single workstation (1-2 consumer GPUs) —
not a copy of any specific repo's code. See the real ScrollPrize/villa repo
for the production-grade version with far more training tricks.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvBlock3D(nn.Module):
    """Two 3x3x3 conv layers, each followed by InstanceNorm3d + LeakyReLU.

    InstanceNorm is used instead of BatchNorm because 3D patches make for
    small batch sizes (2-4 is typical on a single consumer GPU), where batch
    statistics get noisy.
    """

    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv3d(in_ch, out_ch, kernel_size=3, padding=1, bias=False),
            nn.InstanceNorm3d(out_ch, affine=True),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Conv3d(out_ch, out_ch, kernel_size=3, padding=1, bias=False),
            nn.InstanceNorm3d(out_ch, affine=True),
            nn.LeakyReLU(0.1, inplace=True),
        )

    def forward(self, x):
        return self.block(x)


class Down3D(nn.Module):
    """2x2x2 max-pool then a ConvBlock3D."""

    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.pool = nn.MaxPool3d(kernel_size=2)
        self.conv = ConvBlock3D(in_ch, out_ch)

    def forward(self, x):
        return self.conv(self.pool(x))


class Up3D(nn.Module):
    """Trilinear upsample + 1x1x1 conv to halve channels, concat skip, ConvBlock3D."""

    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.reduce = nn.Conv3d(in_ch, out_ch, kernel_size=1)
        self.conv = ConvBlock3D(out_ch * 2, out_ch)

    def forward(self, x, skip):
        x = F.interpolate(x, size=skip.shape[2:], mode="trilinear", align_corners=False)
        x = self.reduce(x)
        x = torch.cat([x, skip], dim=1)
        return self.conv(x)



class UNet3D(nn.Module):
    """A 4-level 3D U-Net that preserves the input's (D, H, W) shape.

    Input:  (B, in_channels, D, H, W)  -- a stack of D consecutive CT slices,
            cropped to an (H, W) spatial patch, intensities normalised to
            [0, 1].
    Output: (B, 1, D, H, W) raw logits -- call `.project()` (or use
            `ink_logits_2d()` below) to collapse to a 2D ink-logit map.

    Depth aggregation (fix #18, STAGED rev1):
      aggregation="max"        -- torch.amax over depth (the original behaviour, default).
      aggregation="topk_mean"  -- mean of the `topk` largest logits over depth at each (h, w).
    Why: the max of D noisy draws is biased upward -- with D=64 slices of pure noise the
    max sits ~2.4 sigma above the mean, so every blank pixel arrives at the sigmoid already
    looking a little like ink. Averaging the top k keeps "pick the slices where the ink is"
    but pulls the noise floor down and the per-pixel variance with it. topk=1 is exactly
    max; topk=D is a plain mean over depth. The choice is part of the training contract
    and must be identical at scoring time: build the model from the checkpoint's stored
    args (aggregation, topk), never from defaults.

    Backward compatible: default construction is byte-identical in behaviour and in
    state_dict keys to the previous model.py, so every existing checkpoint still loads.

    Memory note: 3D convolutions at e.g. depth=64, 256x256 are the memory
    bottleneck. `base_channels=16` (default) needs roughly 8-10GB of GPU
    memory at batch_size=2 with mixed precision on a 64x256x256 patch; halve
    `base_channels` or the patch size for smaller cards (see README).
    """

    AGGREGATIONS = ("max", "topk_mean")

    def __init__(self, in_channels: int = 1, base_channels: int = 16,
                 aggregation: str = "max", topk: int | None = None):
        super().__init__()
        if aggregation not in self.AGGREGATIONS:
            raise ValueError(f"aggregation must be one of {self.AGGREGATIONS}, got {aggregation!r}")
        if aggregation == "topk_mean" and (topk is None or int(topk) < 1):
            raise ValueError("aggregation='topk_mean' needs topk >= 1")
        if aggregation == "max" and topk not in (None, 1):
            raise ValueError(f"aggregation='max' ignores topk; got topk={topk}. Pass topk=None "
                             "(or use aggregation='topk_mean') so the contract says what the model does.")
        self.aggregation = aggregation
        self.topk = int(topk) if topk is not None else None

        c = base_channels
        self.enc0 = ConvBlock3D(in_channels, c)
        self.down1 = Down3D(c, c * 2)
        self.down2 = Down3D(c * 2, c * 4)
        self.down3 = Down3D(c * 4, c * 8)
        self.bottleneck = Down3D(c * 8, c * 16)

        self.up3 = Up3D(c * 16, c * 8)
        self.up2 = Up3D(c * 8, c * 4)
        self.up1 = Up3D(c * 4, c * 2)
        self.up0 = Up3D(c * 2, c)

        self.out_conv = nn.Conv3d(c, 1, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e0 = self.enc0(x)          # (B, c,    D,    H,    W)
        e1 = self.down1(e0)        # (B, 2c,   D/2,  H/2,  W/2)
        e2 = self.down2(e1)        # (B, 4c,   D/4,  H/4,  W/4)
        e3 = self.down3(e2)        # (B, 8c,   D/8,  H/8,  W/8)
        b = self.bottleneck(e3)    # (B, 16c,  D/16, H/16, W/16)

        d3 = self.up3(b, e3)       # (B, 8c,   D/8,  H/8,  W/8)
        d2 = self.up2(d3, e2)      # (B, 4c,   D/4,  H/4,  W/4)
        d1 = self.up1(d2, e1)      # (B, 2c,   D/2,  H/2,  W/2)
        d0 = self.up0(d1, e0)      # (B, c,    D,    H,    W)

        return self.out_conv(d0)   # (B, 1, D, H, W) raw logits

    @staticmethod
    def max_project(logits_3d: torch.Tensor) -> torch.Tensor:
        """Collapse (B, 1, D, H, W) logits to (B, 1, H, W) via max over depth.
        Kept for backward compatibility; new code should call `project()`."""
        return torch.amax(logits_3d, dim=2)

    @staticmethod
    def topk_mean_project(logits_3d: torch.Tensor, k: int) -> torch.Tensor:
        """Collapse (B, 1, D, H, W) to (B, 1, H, W): mean of the k largest logits over depth.
        k is clamped to D. k=1 reproduces max_project exactly."""
        D = logits_3d.shape[2]
        k = max(1, min(int(k), D))
        return logits_3d.topk(k, dim=2).values.mean(dim=2)

    def project(self, logits_3d: torch.Tensor) -> torch.Tensor:
        """Depth aggregation according to THIS model's contract. train.py, infer.py,
        tune_threshold.py and cross_infer.py must all go through this (not max_project)
        so training and scoring agree."""
        if self.aggregation == "max":
            return self.max_project(logits_3d)
        return self.topk_mean_project(logits_3d, self.topk)

    def contract_fields(self) -> dict:
        """The two fields build_contract() needs from the model."""
        return {"aggregation": self.aggregation, "topk": self.topk}

    def ink_logits_2d(self, x: torch.Tensor) -> torch.Tensor:
        """Full forward pass -> 2D ink logits (B, 1, H, W). Apply sigmoid for probability."""
        return self.project(self.forward(x))


def count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


__revision__ = "staged-rev1"   # model.py rev1 = original (16/09); staged-rev1 adds topk_mean aggregation (#18)


if __name__ == "__main__":
    # Self-test. Runs with the plain interpreter: python -m vesuvius_unet.model
    torch.manual_seed(0)
    B, D, H, W = 2, 16, 32, 32   # bottleneck is (D/16, H/16, W/16); InstanceNorm needs > 1 element there
    z = torch.randn(B, 1, D, H, W)

    # 1. topk=1 is EXACTLY max; topk=D is exactly the mean; top-k mean never exceeds max
    assert torch.equal(UNet3D.topk_mean_project(z, 1), UNet3D.max_project(z))
    assert torch.allclose(UNet3D.topk_mean_project(z, D), z.mean(dim=2), atol=1e-6)
    assert torch.allclose(UNet3D.topk_mean_project(z, 999), z.mean(dim=2), atol=1e-6)   # k clamped to D
    assert (UNet3D.topk_mean_project(z, 4) <= UNet3D.max_project(z) + 1e-7).all()
    print("[ok] topk_mean: k=1 == max exactly, k>=D == mean, always <= max")

    # 2. the noise-bias claim in the docstring, measured: pure noise, 64 slices
    n = torch.randn(4000, 1, 64, 1, 1)
    m_max, m_k16, m_k4 = (UNet3D.max_project(n).mean().item(), UNet3D.topk_mean_project(n, 16).mean().item(),
                         UNet3D.topk_mean_project(n, 4).mean().item())
    s_max, s_k16 = UNet3D.max_project(n).std().item(), UNet3D.topk_mean_project(n, 16).std().item()
    assert 2.2 < m_max < 2.6 and m_k16 < m_max and s_k16 < s_max
    print(f"[ok] pure-noise floor over 64 slices: max = +{m_max:.2f} sigma (std {s_max:.2f}); "
          f"top-16 mean = +{m_k16:.2f} sigma (std {s_k16:.2f}); top-4 mean = +{m_k4:.2f} sigma")

    # 3. dispatch + gradient flow through topk; contract fields honest
    mk = UNet3D(1, 4, aggregation="topk_mean", topk=4)
    x = torch.rand(1, 1, D, H, W, requires_grad=True)
    out = mk.ink_logits_2d(x); assert out.shape == (1, 1, H, W)
    out.sum().backward(); assert x.grad is not None and torch.isfinite(x.grad).all()
    assert mk.contract_fields() == {"aggregation": "topk_mean", "topk": 4}
    assert UNet3D(1, 4).contract_fields() == {"aggregation": "max", "topk": None}
    for bad in (dict(aggregation="topk_mean"), dict(aggregation="topk_mean", topk=0),
                dict(aggregation="max", topk=16), dict(aggregation="median")):
        try:
            UNet3D(1, 4, **bad); raise SystemExit(f"accepted invalid {bad}")
        except ValueError:
            pass
    print("[ok] project() dispatches, gradients flow through topk, invalid combos refused")

    # 4. backward compatibility: default model == old behaviour, same state_dict keys, same param count
    m0 = UNet3D(1, 4)
    assert torch.equal(m0.project(z), UNet3D.max_project(z))
    assert count_params(m0) == 334541, count_params(m0)
    sd_keys = set(m0.state_dict().keys())
    mk_keys = set(mk.state_dict().keys())
    assert sd_keys == mk_keys, "aggregation must not add state_dict entries (old checkpoints must load)"
    assert not any(k.startswith(("aggregation", "topk")) for k in sd_keys)
    print(f"[ok] default model: max aggregation, 334,541 params at base_channels=4, "
          f"{len(sd_keys)} state_dict keys, none added by the aggregation option")
    print("[ok] model.py staged-rev1 self-test passed")
