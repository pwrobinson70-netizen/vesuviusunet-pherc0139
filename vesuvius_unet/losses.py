"""Loss functions for ink-detection training.

Combines BCEWithLogits (stable, handles class imbalance via pos_weight) with
a soft Dice loss (directly optimises pixel overlap, which correlates with
the F-beta metrics used to evaluate this task).

STAGED rev1 adds fix #19: a soft Tversky loss and a BCE+Tversky combination.

CONVENTION -- read this before touching alpha/beta:
    Tversky index = TP / (TP + alpha*FP + beta*FN)
    alpha multiplies FALSE POSITIVES, beta multiplies FALSE NEGATIVES.
    alpha = beta = 0.5 is exactly Dice. alpha > beta punishes invented ink harder than
    missed ink, which is what a precision-weighted metric (F0.5) wants and what a model
    measured at 3x over-prediction needs. The project setting is alpha=0.7, beta=0.3.
    (The medical-segmentation literature usually runs it the other way round, alpha=0.3,
    to favour recall -- do not copy those numbers.) The self-test pins this direction.

pos_weight and Tversky are BOTH asymmetry knobs. pos_weight > 1 pushes toward recall (more
predicted ink); Tversky alpha > beta pushes toward precision. Using both means fighting
yourself, and the current pos_weight (~1.87) is derived from the ENRICHED training ink
fraction, not the real one. When --loss bce_tversky is selected, train.py must pass
pos_weight=None. build_loss() enforces that.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

__revision__ = "staged-rev1"   # rev1 = original (16/09); staged-rev1 adds Tversky (#19) + build_loss


def soft_dice_loss(logits: torch.Tensor, targets: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    probs = torch.sigmoid(logits)
    probs = probs.flatten(1)
    targets = targets.flatten(1)
    intersection = (probs * targets).sum(dim=1)
    union = probs.sum(dim=1) + targets.sum(dim=1)
    dice = (2 * intersection + eps) / (union + eps)
    return 1 - dice.mean()


def soft_tversky_loss(logits: torch.Tensor, targets: torch.Tensor, alpha: float = 0.7,
                      beta: float = 0.3, eps: float = 1e-6) -> torch.Tensor:
    """1 - TP / (TP + alpha*FP + beta*FN), soft (probabilities), per sample then averaged.
    alpha weights FALSE POSITIVES, beta weights FALSE NEGATIVES. alpha=beta=0.5 == Dice."""
    probs = torch.sigmoid(logits).flatten(1)
    targets = targets.flatten(1)
    tp = (probs * targets).sum(dim=1)
    fp = (probs * (1 - targets)).sum(dim=1)
    fn = ((1 - probs) * targets).sum(dim=1)
    tversky = (tp + eps) / (tp + alpha * fp + beta * fn + eps)
    return 1 - tversky.mean()


class BCEDiceLoss(nn.Module):
    def __init__(self, pos_weight: float | None = None, dice_weight: float = 1.0, bce_weight: float = 1.0):
        super().__init__()
        pw = torch.tensor(pos_weight) if pos_weight is not None else None
        self.register_buffer("pos_weight", pw if pw is not None else torch.tensor(1.0))
        self.dice_weight = dice_weight
        self.bce_weight = bce_weight

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        bce = F.binary_cross_entropy_with_logits(logits, targets, pos_weight=self.pos_weight)
        dice = soft_dice_loss(logits, targets)
        return self.bce_weight * bce + self.dice_weight * dice


class BCETverskyLoss(nn.Module):
    """BCE (unweighted by default) + soft Tversky. alpha on FP, beta on FN -- see module docstring."""

    def __init__(self, alpha: float = 0.7, beta: float = 0.3, pos_weight: float | None = None,
                 tversky_weight: float = 1.0, bce_weight: float = 1.0):
        super().__init__()
        if not (0.0 <= alpha <= 1.0 and 0.0 <= beta <= 1.0):
            raise ValueError(f"alpha/beta must be in [0, 1]; got {alpha}, {beta}")
        self.alpha, self.beta = float(alpha), float(beta)
        pw = torch.tensor(pos_weight) if pos_weight is not None else torch.tensor(1.0)
        self.register_buffer("pos_weight", pw)
        self.tversky_weight = tversky_weight
        self.bce_weight = bce_weight

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        bce = F.binary_cross_entropy_with_logits(logits, targets, pos_weight=self.pos_weight)
        tv = soft_tversky_loss(logits, targets, self.alpha, self.beta)
        return self.bce_weight * bce + self.tversky_weight * tv


def build_loss(name: str, pos_weight: float | None = None, alpha: float | None = None,
               beta: float | None = None) -> nn.Module:
    """The one place train.py should construct its criterion from flags.
    'bce_dice'    -> BCEDiceLoss(pos_weight)             (the original objective; alpha/beta must be None)
    'bce_tversky' -> BCETverskyLoss(alpha, beta), pos_weight FORBIDDEN (see module docstring)."""
    if name == "bce_dice":
        if alpha is not None or beta is not None:
            raise ValueError("alpha/beta only apply to --loss bce_tversky")
        return BCEDiceLoss(pos_weight=pos_weight)
    if name == "bce_tversky":
        if pos_weight not in (None, 1.0):
            raise ValueError(f"--loss bce_tversky must not be combined with pos_weight ({pos_weight}); "
                             "both are asymmetry knobs and they pull in opposite directions")
        return BCETverskyLoss(alpha=0.7 if alpha is None else alpha, beta=0.3 if beta is None else beta)
    raise ValueError(f"unknown loss {name!r}; expected 'bce_dice' or 'bce_tversky'")


if __name__ == "__main__":
    torch.manual_seed(0)
    t = (torch.rand(3, 1, 32, 32) < 0.15).float()                  # ~15% ink
    z = torch.randn(3, 1, 32, 32) * 2

    # 1. alpha = beta = 0.5 is Dice (they differ only in how eps enters; tolerance covers that)
    d, tv = soft_dice_loss(z, t).item(), soft_tversky_loss(z, t, 0.5, 0.5).item()
    assert abs(d - tv) < 1e-5, (d, tv)
    print(f"[ok] Tversky(0.5, 0.5) == Dice: {tv:.6f} vs {d:.6f}")

    # 2. THE CONVENTION, pinned. Build a prediction that is FP-heavy (predicts ink where there is none,
    #    finds all the real ink) and one that is FN-heavy (misses half the ink, invents none).
    big = 6.0
    fp_heavy = torch.where(t > 0, big, torch.where(torch.rand_like(t) < 0.3, big, -big))   # 30% of blanks -> ink
    fn_heavy = torch.where((t > 0) & (torch.rand_like(t) < 0.5), big, -big)                # half the ink -> missed
    l_fp_a7 = soft_tversky_loss(fp_heavy, t, 0.7, 0.3).item(); l_fp_a3 = soft_tversky_loss(fp_heavy, t, 0.3, 0.7).item()
    l_fn_a7 = soft_tversky_loss(fn_heavy, t, 0.7, 0.3).item(); l_fn_a3 = soft_tversky_loss(fn_heavy, t, 0.3, 0.7).item()
    assert l_fp_a7 > l_fp_a3, "alpha=0.7 must punish the FP-heavy prediction MORE than alpha=0.3"
    assert l_fn_a7 < l_fn_a3, "alpha=0.7 must punish the FN-heavy prediction LESS than alpha=0.3"
    print(f"[ok] convention: alpha weights FP. FP-heavy pred: loss {l_fp_a7:.3f} (a=.7) > {l_fp_a3:.3f} (a=.3); "
          f"FN-heavy pred: {l_fn_a7:.3f} (a=.7) < {l_fn_a3:.3f} (a=.3)")

    # 3. combined loss: finite, differentiable, equals BCE+Dice at 0.5/0.5 with matching pos_weight
    zz = z.clone().requires_grad_(True)
    crit = BCETverskyLoss(0.7, 0.3)
    loss = crit(zz, t); loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(zz.grad).all()
    a, b = BCETverskyLoss(0.5, 0.5, pos_weight=1.87)(z, t).item(), BCEDiceLoss(pos_weight=1.87)(z, t).item()
    assert abs(a - b) < 1e-5, (a, b)
    print(f"[ok] BCETverskyLoss finite + differentiable; at (0.5, 0.5, pw=1.87) equals BCEDiceLoss: {a:.6f} vs {b:.6f}")

    # 4. build_loss guards: tversky + pos_weight refused; alpha/beta on dice refused; defaults right
    assert isinstance(build_loss("bce_dice", pos_weight=1.87), BCEDiceLoss)
    tvl = build_loss("bce_tversky"); assert (tvl.alpha, tvl.beta) == (0.7, 0.3) and tvl.pos_weight.item() == 1.0
    for bad in (dict(name="bce_tversky", pos_weight=1.87), dict(name="bce_dice", alpha=0.7), dict(name="focal")):
        try:
            build_loss(**bad); raise SystemExit(f"accepted {bad}")
        except ValueError:
            pass
    print("[ok] build_loss: tversky refuses pos_weight, dice refuses alpha/beta, defaults 0.7/0.3")

    # 5. what pos_weight was doing: on the same prediction, BCE with pw=1.87 vs 1.0 -- shows the recall push
    bce_pw = F.binary_cross_entropy_with_logits(fn_heavy, t, pos_weight=torch.tensor(1.87)).item()
    bce_1 = F.binary_cross_entropy_with_logits(fn_heavy, t).item()
    assert bce_pw > bce_1
    print(f"[ok] context: pos_weight 1.87 raises the FN-heavy prediction's BCE from {bce_1:.3f} to {bce_pw:.3f} "
          f"-- it was a recall push; Tversky a=.7 is a precision push; combining them is incoherent")
    print("[ok] losses.py staged-rev1 self-test passed")
