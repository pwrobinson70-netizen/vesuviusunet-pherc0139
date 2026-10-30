#!/usr/bin/env python3
"""
Run a trained 3D U-Net checkpoint over a whole fragment and stitch the
per-tile predictions into one full-resolution ink-probability map + PNG
visualisation, plus a final F0.5/precision/recall/AUC readout on the
held-out (validation) region for direct comparison with training logs.

Example:
    python -m vesuvius_unet.infer --data_dir data --checkpoint runs/frag1/best.pt \\
        --output prediction.png
"""
from __future__ import annotations

import argparse

import numpy as np
import torch
from PIL import Image

from .dataset import _load_volume_and_mask
from .metrics import binary_metrics
from .model import UNet3D


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data_dir", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--output", default="prediction.png")
    p.add_argument("--patch_size", type=int, default=256)
    p.add_argument("--depth", type=int, default=64)
    p.add_argument("--stride", type=int, default=None, help="Defaults to patch_size/2 for overlap-averaged stitching")
    p.add_argument("--val_fraction", type=float, default=0.2,
                    help="Same value used at training time, to report a held-out score")
    p.add_argument("--batch_size", type=int, default=4)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    return p.parse_args()


def stitch_predict(model, volume, patch_size, depth, stride, device, batch_size=4):
    D, H, W = volume.shape
    prob_sum = np.zeros((H, W), dtype=np.float32)
    weight = np.zeros((H, W), dtype=np.float32)

    coords = [(y0, x0) for y0 in range(0, H - patch_size + 1, stride)
              for x0 in range(0, W - patch_size + 1, stride)]

    model.eval()
    with torch.no_grad():
        for i in range(0, len(coords), batch_size):
            batch_coords = coords[i:i + batch_size]
            patches = np.stack([
                volume[:, y0:y0 + patch_size, x0:x0 + patch_size].astype(np.float32) / 65535.0
                for y0, x0 in batch_coords
            ])
            x = torch.from_numpy(patches).unsqueeze(1).to(device)  # (B, 1, D, p, p)
            logits_2d = model.ink_logits_2d(x)
            probs = torch.sigmoid(logits_2d).squeeze(1).cpu().numpy()  # (B, p, p)
            for (y0, x0), prob in zip(batch_coords, probs):
                prob_sum[y0:y0 + patch_size, x0:x0 + patch_size] += prob
                weight[y0:y0 + patch_size, x0:x0 + patch_size] += 1.0

    weight[weight == 0] = 1.0  # avoid div-by-zero at the untiled border
    return prob_sum / weight


def main():
    args = parse_args()
    stride = args.stride or args.patch_size // 2

    print(f"Loading fragment from {args.data_dir} ...")
    volume, mask = _load_volume_and_mask(args.data_dir, args.depth)

    ckpt = torch.load(args.checkpoint, map_location=args.device)
    train_args = ckpt.get("args", {})
    base_channels = train_args.get("base_channels", 16)
    # Pull the ACTUAL patch_size/val_fraction used at training time from the
    # checkpoint rather than trusting args defaults, so the held-out region
    # computed below exactly matches what the model was validated against.
    train_patch_size = train_args.get("patch_size", args.patch_size)
    train_val_fraction = train_args.get("val_fraction", args.val_fraction)
    model = UNet3D(in_channels=1, base_channels=base_channels,
                   aggregation=train_args.get("aggregation", "max"),
                   topk=train_args.get("topk")).to(args.device)
    model.load_state_dict(ckpt["model"])
    print(f"Loaded checkpoint from epoch {ckpt.get('epoch')} (best_f05={ckpt.get('best_f05'):.3f})")

    print("Running tiled inference over the full fragment (this can take a while on CPU)...")
    prob_map = stitch_predict(model, volume, args.patch_size, args.depth, stride, args.device, args.batch_size)

    Image.fromarray((prob_map * 255).astype(np.uint8)).save(args.output)
    print(f"Saved probability map to {args.output}")

    # Score on the SAME held-out region training validated against: interleaved
    # patch_size-wide column blocks, every Nth one held out (see
    # VesuviusPatchDataset in dataset.py). NOT a single left/right column cut --
    # that degenerates to a meaningless 0.0/NaN whenever the writing isn't
    # evenly spread across the fragment's width (confirmed to happen on
    # Fragment 1, whose rightmost 20% is 100% blank papyrus).
    val_every = max(1, round(1 / train_val_fraction)) if train_val_fraction > 0 else 0
    W = prob_map.shape[1]
    if val_every > 0:
        col_block = np.arange(W) // train_patch_size
        val_col_mask = (col_block % val_every) == (val_every - 1)
    else:
        val_col_mask = np.zeros(W, dtype=bool)

    val_probs = prob_map[:, val_col_mask].ravel()
    val_targets = mask[:, val_col_mask].ravel()
    metrics = binary_metrics(val_probs, val_targets)
    print(f"Held-out region (interleaved strips, matches training split): "
          f"precision={metrics['precision']:.3f} recall={metrics['recall']:.3f} "
          f"F0.5={metrics['f05']:.3f} AUC={metrics['auc']:.3f}")

    # Also report the whole-fragment score for context. This is optimistic --
    # most of the fragment WAS used for training -- but useful as an upper bound.
    all_metrics = binary_metrics(prob_map.ravel(), mask.ravel())
    print(f"Whole fragment (includes training region, optimistic upper bound): "
          f"precision={all_metrics['precision']:.3f} recall={all_metrics['recall']:.3f} "
          f"F0.5={all_metrics['f05']:.3f} AUC={all_metrics['auc']:.3f}")


if __name__ == "__main__":
    main()
