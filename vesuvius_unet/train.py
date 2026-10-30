#!/usr/bin/env python3
"""
Train a 3D U-Net ink-detection model on a Vesuvius Challenge fragment.

Designed for a workstation with 1-2 NVIDIA GPUs (falls back to CPU, but CPU
training at this patch size is impractically slow -- only useful for a
correctness smoke-test with tiny --patch_size/--depth/--epochs values).

Example:
    python -m vesuvius_unet.train \\
        --data_dir data \\
        --output_dir runs/frag1 \\
        --patch_size 256 --depth 64 --batch_size 4 --epochs 30

See README.md for hardware sizing guidance (patch size / batch size / base
channels for different GPU memory budgets) and multi-GPU usage.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from .dataset import make_train_val_datasets
from .losses import build_loss
from .metrics import binary_metrics
from .model import UNet3D, count_params
from .run_hygiene_v2 import (assert_contract_matches, atomic_write_json, build_contract,
                             print_run_banner, save_epoch_checkpoint)


MIN_DIVISOR = 16  # 4 pooling stages in UNet3D, each halving D/H/W

# Source files hashed into the run banner, so the log proves which code ran.
BANNER_SOURCES = ("dataset.py", "model.py", "losses.py", "train.py", "infer.py",
                  "metrics.py", "run_hygiene_v2.py")

# Args that change what the model IS. A resume that changes any of them is a
# different experiment, so it is refused (checked even for pre-contract
# checkpoints, via the args dict they carry).
RESUME_MUST_MATCH = ("patch_size", "depth", "stride", "val_fraction", "base_channels")


def training_contract(args) -> dict:
    """The training contract of THIS code, as run_hygiene_v2.build_contract wants it.
    Every value describes what the code actually does - none of them are settings:
      aggregation   model.project(), which dispatches on --aggregation/--topk (#18)
      loss          --loss: bce_dice (BCEDiceLoss) or bce_tversky (BCETverskyLoss, #19)
      depth window  the first `depth` slices (dataset._load_volume_and_mask)
      normalisation fixed linear /65535 (VesuviusPatchDataset.__getitem__)
      split         every Nth tile-column goes to val (VesuviusPatchDataset.__init__);
                    n uses the same formula as the dataset, and main() checks the
                    real tiles against it after loading.
    If any of those change in the code, change this function in the same edit."""
    stride = args.stride or args.patch_size
    n = max(1, round(1 / args.val_fraction)) if args.val_fraction > 0 else 0
    return build_contract(
        aggregation=args.aggregation, topk=args.topk, loss=args.loss,
        alpha=args.alpha, beta=args.beta,
        depth_start=0, depth=args.depth, patch_size=args.patch_size,
        split={"kind": "every_nth_column", "n": n, "stride": stride},
        normalisation="linear_div_65535", val_fraction=args.val_fraction)


def check_split_matches_contract(train_ds, val_ds, contract: dict) -> None:
    """Enforce the contract's split against the tiles the dataset really built,
    rather than trusting that two copies of the formula agree."""
    n, stride = contract["split"]["n"], contract["split"]["stride"]
    if n <= 0:
        return
    val_cols = {t.x0 // stride for t in val_ds.tiles}
    train_cols = {t.x0 // stride for t in train_ds.tiles}
    bad_val = sorted(c for c in val_cols if c % n != n - 1)
    bad_train = sorted(c for c in train_cols if c % n == n - 1)
    if bad_val or bad_train:
        raise RuntimeError(f"split does not match contract {contract['split']}: "
                           f"val tile-columns {bad_val[:10]} / train tile-columns {bad_train[:10]} "
                           f"are on the wrong side")
    print(f"Split check: OK ({len(val_cols)} val tile-columns, {len(train_cols)} train "
          f"tile-columns, every {n}th column is val)")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data_dir", required=True, help="Folder with NN.tif slices + inklabels.png")
    p.add_argument("--output_dir", default="runs/exp1", help="Where to write checkpoints + logs")
    p.add_argument("--patch_size", type=int, default=256, help="Spatial patch size (H=W)")
    p.add_argument("--depth", type=int, default=64, help="Number of z-slices per patch")
    p.add_argument("--stride", type=int, default=None, help="Tile stride; defaults to patch_size (no overlap)")
    p.add_argument("--val_fraction", type=float, default=0.2, help="Fraction of fragment width held out for validation")
    p.add_argument("--base_channels", type=int, default=16, help="U-Net width; lower for smaller GPUs")
    p.add_argument("--batch_size", type=int, default=4)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight_decay", type=float, default=1e-4)
    p.add_argument("--num_workers", type=int, default=4)
    p.add_argument("--negative_keep_prob", type=float, default=0.15,
                    help="Fraction of ink-free tiles to keep (avoids background-only dataset domination)")
    p.add_argument("--aggregation", choices=["max", "topk_mean"], default="max",
                    help="Depth aggregation of the 3D logits (#18). Part of the training contract.")
    p.add_argument("--topk", type=int, default=None,
                    help="k for --aggregation topk_mean (e.g. 16). Must be None for 'max'.")
    p.add_argument("--loss", choices=["bce_dice", "bce_tversky"], default="bce_dice",
                    help="Objective (#19). bce_tversky disables pos_weight - see losses.py docstring.")
    p.add_argument("--alpha", type=float, default=None,
                    help="Tversky weight on FALSE POSITIVES (default 0.7). Only with --loss bce_tversky.")
    p.add_argument("--beta", type=float, default=None,
                    help="Tversky weight on FALSE NEGATIVES (default 0.3). Only with --loss bce_tversky.")
    p.add_argument("--amp", action="store_true", default=True, help="Use mixed precision (default on for CUDA)")
    p.add_argument("--no_amp", dest="amp", action="store_false")
    p.add_argument("--gpus", type=str, default="all",
                    help="'all' (use every visible GPU via DataParallel), 'cpu', or comma-separated device ids e.g. '0,1'")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--resume", type=str, default=None, help="Path to a checkpoint to resume from")
    p.add_argument("--log_every", type=int, default=20, help="Print training loss every N steps")
    args = p.parse_args()

    if args.aggregation == "topk_mean" and (args.topk is None or args.topk < 1):
        p.error("--aggregation topk_mean requires --topk >= 1")
    if args.aggregation == "max" and args.topk not in (None, 1):
        p.error(f"--aggregation max ignores --topk (got {args.topk}); drop it, or use --aggregation topk_mean")
    if args.loss == "bce_dice" and (args.alpha is not None or args.beta is not None):
        p.error("--alpha/--beta apply only to --loss bce_tversky")
    if args.loss == "bce_tversky":
        # Resolve the defaults HERE, so vars(args), the contract and the checkpoint all
        # record the values actually used rather than None.
        args.alpha = 0.7 if args.alpha is None else args.alpha
        args.beta = 0.3 if args.beta is None else args.beta

    for name in ("patch_size", "depth"):
        val = getattr(args, name)
        if val % MIN_DIVISOR != 0:
            p.error(f"--{name}={val} must be a multiple of {MIN_DIVISOR} "
                     f"(UNet3D has 4 pooling stages, each halving D/H/W)")
    return args


def pick_device_and_ids(gpus: str):
    if gpus == "cpu" or not torch.cuda.is_available():
        return torch.device("cpu"), []
    if gpus == "all":
        ids = list(range(torch.cuda.device_count()))
    else:
        ids = [int(x) for x in gpus.split(",") if x != ""]
    if not ids:
        return torch.device("cpu"), []
    return torch.device(f"cuda:{ids[0]}"), ids


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device, amp: bool) -> dict:
    model.eval()
    all_probs, all_targets = [], []
    with torch.no_grad():
        for vol, lbl in loader:
            vol = vol.to(device, non_blocking=True)
            with torch.autocast(device_type=device.type, enabled=amp and device.type == "cuda"):
                logits_3d = model(vol)
                logits_2d = (model.module if isinstance(model, nn.DataParallel) else model).project(logits_3d)
            probs = torch.sigmoid(logits_2d).float().cpu().numpy().ravel()
            all_probs.append(probs)
            all_targets.append(lbl.numpy().ravel())
    probs = np.concatenate(all_probs)
    targets = np.concatenate(all_targets)
    print(f"[DEBUG] targets: n={len(targets)}  unique={np.unique(targets)}  ink_frac={(targets==1).mean():.6f}")
    print(f"[DEBUG] probs: min={probs.min():.4f}  max={probs.max():.4f}  nan_in_probs={np.isnan(probs).sum()}")
    return binary_metrics(probs, targets)


def main():
    args = parse_args()

    # Run banner FIRST, before anything that can fail, so even a crashed launch
    # leaves a record of exactly which code and settings it ran with.
    here = Path(__file__).resolve().parent
    sources = [here / name for name in BANNER_SOURCES]
    contract = training_contract(args)
    banner = print_run_banner(sources, args=args, seed=args.seed, extra={"contract": contract})
    missing = [p.name for p in sources if not p.exists()]
    if missing:
        print(f"WARNING: banner could not hash {missing} - this log does NOT prove "
              f"which version of those files ran.", flush=True)
    banner["missing_sources"] = missing
    # Plain-types copy (e.g. torch's version object -> str) so checkpoints stay
    # loadable by torch.load's default weights_only unpickler.
    banner = json.loads(json.dumps(banner, default=str))

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)
    # The watchdog does not capture stdout, so keep the banner on disk too:
    # one file per launch, next to the checkpoints it describes.
    banner_path = os.path.join(args.output_dir, f"run_banner_{time.strftime('%Y%m%d-%H%M%S')}.json")
    atomic_write_json(banner_path, banner)
    print(f"Run banner saved to {banner_path}")

    device, gpu_ids = pick_device_and_ids(args.gpus)
    print(f"Device: {device}  |  GPU ids: {gpu_ids or 'none (CPU)'}")

    print("Loading fragment and building tile index (this reads the whole fragment into RAM once)...")
    t0 = time.time()
    train_ds, val_ds = make_train_val_datasets(
        args.data_dir,
        patch_size=args.patch_size,
        depth=args.depth,
        stride=args.stride,
        val_fraction=args.val_fraction,
        negative_keep_prob=args.negative_keep_prob,
        seed=args.seed,
    )
    print(f"  train tiles: {len(train_ds)}  |  val tiles: {len(val_ds)}  |  loaded in {time.time() - t0:.1f}s")
    check_split_matches_contract(train_ds, val_ds, contract)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                               num_workers=args.num_workers, pin_memory=(device.type == "cuda"),
                               persistent_workers=(args.num_workers > 0), drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=max(1, args.batch_size), shuffle=False,
                             num_workers=args.num_workers, pin_memory=(device.type == "cuda"),
                             persistent_workers=(args.num_workers > 0))

    model = UNet3D(in_channels=1, base_channels=args.base_channels,
                   aggregation=args.aggregation, topk=args.topk).to(device)
    print(f"Model params: {count_params(model):,}")
    if len(gpu_ids) > 1:
        print(f"Using nn.DataParallel across GPUs {gpu_ids}")
        model = nn.DataParallel(model, device_ids=gpu_ids)

    # pos_weight balances the (usually minority) ink class in the BCE term
    ink_frac = max(train_ds.ink_fraction, 1e-4)
    if args.loss == "bce_dice":
        pos_weight = (1 - ink_frac) / ink_frac
        print(f"Train ink fraction ~{ink_frac:.3f} (ENRICHED by negative_keep_prob; see #16) "
              f"-> BCE pos_weight ~{pos_weight:.2f}")
    else:
        # pos_weight (>1) pushes recall; Tversky alpha>beta pushes precision. Using both
        # is fighting yourself, so build_loss refuses the combination outright.
        pos_weight = None
        print(f"Train ink fraction ~{ink_frac:.3f}; --loss {args.loss}: pos_weight NOT used "
              f"(alpha={args.alpha} on false positives, beta={args.beta} on false negatives)")
    criterion = build_loss(args.loss, pos_weight=pos_weight,
                           alpha=args.alpha, beta=args.beta).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    scaler = torch.amp.GradScaler(device.type, enabled=args.amp and device.type == "cuda")

    start_epoch = 0
    best_f05 = -1.0
    if args.resume and os.path.exists(args.resume):
        ckpt = torch.load(args.resume, map_location=device)
        # Refuse to resume into a different experiment.
        old_args = ckpt.get("args") or {}
        changed = {k: (old_args[k], getattr(args, k)) for k in RESUME_MUST_MATCH
                   if k in old_args and old_args[k] != getattr(args, k)}
        if changed:
            raise RuntimeError(f"refusing to resume {args.resume}: settings changed since it was saved "
                               f"(checkpoint vs now): {changed}")
        if isinstance(ckpt.get("contract"), dict):
            assert_contract_matches(ckpt["contract"], contract)
            print("Resume contract check: OK (checkpoint and this run have the same training contract)")
        else:
            print("NOTE: resuming from a checkpoint saved before run contracts existed - nothing to "
                  "check it against. This run's contract is stored from the next checkpoint on.")
        (model.module if isinstance(model, nn.DataParallel) else model).load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_epoch = ckpt["epoch"] + 1
        best_f05 = ckpt.get("best_f05", -1.0)
        print(f"Resumed from {args.resume} at epoch {start_epoch}")

    # Carry forward any history from previous runs. Without this, resuming
    # silently overwrites history.json with ONLY the epochs from this run,
    # destroying the earlier training curve (this bit us: epochs 0-11 of
    # frag1 were lost this way before the fix). Entries at or after
    # start_epoch are dropped so a re-run of the same epochs replaces rather
    # than duplicates them.
    history = []
    history_path = os.path.join(args.output_dir, "history.json")
    if start_epoch > 0 and os.path.exists(history_path):
        try:
            with open(history_path) as f:
                prior = json.load(f)
            history = [h for h in prior if h.get("epoch", -1) < start_epoch]
            if history:
                print(f"Carried forward {len(history)} earlier epoch(s) of history "
                      f"(epochs {history[0]['epoch']}-{history[-1]['epoch']})")
        except (json.JSONDecodeError, OSError) as exc:
            # Never let a damaged history file stop training - just warn loudly.
            print(f"WARNING: could not read existing {history_path} ({exc}); "
                  f"starting a fresh history. Previous epoch metrics will not be preserved.")
            history = []

    for epoch in range(start_epoch, args.epochs):
        model.train()
        epoch_loss = 0.0
        t_epoch = time.time()
        for step, (vol, lbl) in enumerate(train_loader):
            vol = vol.to(device, non_blocking=True)
            lbl = lbl.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=args.amp and device.type == "cuda"):
                logits_3d = model(vol)
                logits_2d = (model.module if isinstance(model, nn.DataParallel) else model).project(logits_3d)
                loss = criterion(logits_2d, lbl)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            epoch_loss += loss.item()
            if (step + 1) % args.log_every == 0:
                print(f"  epoch {epoch} step {step + 1}/{len(train_loader)} "
                      f"loss={loss.item():.4f}")

        scheduler.step()
        avg_loss = epoch_loss / max(1, len(train_loader))
        val_metrics = evaluate(model, val_loader, device, args.amp)
        dt = time.time() - t_epoch
        print(f"Epoch {epoch}: train_loss={avg_loss:.4f}  "
              f"val_precision={val_metrics['precision']:.3f} val_recall={val_metrics['recall']:.3f} "
              f"val_F0.5={val_metrics['f05']:.3f} val_AUC={val_metrics['auc']:.3f}  ({dt:.1f}s)")
        history.append({"epoch": epoch, "train_loss": avg_loss, **val_metrics})

        ckpt = {
            "epoch": epoch,
            "model": (model.module if isinstance(model, nn.DataParallel) else model).state_dict(),
            "optimizer": optimizer.state_dict(),
            "best_f05": best_f05,
            "args": vars(args),
            "contract": contract,
            "run_banner": banner,
        }
        # epochNNN.pt (kept for every epoch) + last.pt, both written atomically.
        save_epoch_checkpoint(args.output_dir, epoch, ckpt)
        if val_metrics["f05"] > best_f05:
            best_f05 = val_metrics["f05"]
            ckpt["best_f05"] = best_f05
            torch.save(ckpt, os.path.join(args.output_dir, "best.pt"))
            print(f"  -> new best F0.5={best_f05:.3f}, saved to {args.output_dir}/best.pt")

        atomic_write_json(history_path, history)

    print(f"Done. Best val F0.5={best_f05:.3f}. Checkpoints + history.json in {args.output_dir}")


if __name__ == "__main__":
    main()
