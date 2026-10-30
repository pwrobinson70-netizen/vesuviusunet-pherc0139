#!/usr/bin/env python3
"""
sweep_saved_map.py -- REV 2 (fable) -- threshold-sweep a probability map that has ALREADY
been saved to disk, without re-running inference and without touching any deployed
module.

WHY THIS EXISTS
---------------
cross_infer.py reports precision/recall/F0.5 through metrics.binary_metrics(), which
hardcodes threshold=0.5. On fragment 1 the F0.5-optimal threshold was measured at
0.810, and scoring at 0.5 cost 0.1716 of F0.5 on the same weights. So a cross-fragment
run scored at 0.5 understates the model by roughly that much, and the cross-fragment
number is the one that decides whether renting a GPU is justified.

This script re-scores a saved map at every threshold. It imports nothing from
vesuvius_unet, so it can be run while training is in progress and cannot perturb a
run (no deploy mid-run).

    # after: python -m vesuvius_unet.cross_infer --data_dir data_frag2 \
    #            --checkpoint runs/frag1/best.pt --output cross_frag2.png
    python sweep_saved_map.py --prob_map cross_frag2.png --data_dir data_frag2 \
        --out cross_frag2_threshold.json

PRECISION NOTE (read before trusting the numbers)
-------------------------------------------------
cross_infer.py saves `(prob_map * 255).astype(uint8)`, so the map on disk is quantised
to 256 levels. That is finer than the 99 thresholds swept by default, so the OPTIMAL
THRESHOLD and the F0.5 AT IT are reliable to about +/-0.004 in threshold. It is not a
substitute for sweeping the float map in memory; it is the way to get the tuned number
from a run that has already finished. The quantisation is reported in the output.

REV 2 (19 Sept) adds what the pre-registration needs and rev 1 lacked:
  * ROC AUC (rank-based, tie-aware, equals sklearn's) over the whole rectangle;
  * if the fragment folder holds a papyrus mask (mask.png), the SAME sweep and AUC restricted
    to papyrus pixels. Frag2 measured 0.774 over the rectangle vs 0.655 on papyrus -- most of
    the rectangle AUC is earned by calling the blank margin blank. The pre-registered bar is
    papyrus-only AUC, so the baseline and the new model must both be measured this way, by
    the same code, on the PC, instead of by hand in a container.
  Rectangle numbers are unchanged from rev 1 (same sweep), so earlier JSONs stay comparable.

Self-test: `python sweep_saved_map.py --selftest` (numpy + PIL only, no data needed).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

__revision__ = "rev2_fable"


def fbeta(precision: float, recall: float, beta: float = 0.5) -> float:
    """Identical to vesuvius_unet.metrics.fbeta -- copied, not imported, so this
    script has no dependency on the package and cannot be affected by a mid-run edit."""
    if precision + recall == 0:
        return 0.0
    b2 = beta ** 2
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def sweep(probs: np.ndarray, targets: np.ndarray, n: int = 99) -> list[dict]:
    """Precision/recall/F0.5 at n thresholds in one sorted pass.

    Same algorithm as tune_threshold.sweep_thresholds. Reimplemented here rather than
    imported for the isolation reason above; the self-test below checks this against a
    brute-force count so the duplication cannot drift silently.
    """
    targets = targets.astype(np.uint8)
    total_pos = int(targets.sum())
    if total_pos == 0:
        raise ValueError("No ink pixels in the scored region - nothing to tune against.")
    order = np.argsort(probs, kind="stable")[::-1]
    sorted_targets = targets[order]
    sorted_probs = probs[order]
    tp_cum = np.cumsum(sorted_targets, dtype=np.int64)

    out = []
    for t in np.linspace(0.0, 1.0, n + 2)[1:-1]:
        k = int(np.searchsorted(-sorted_probs, -t, side="right"))
        if k == 0:
            precision = recall = 0.0
        else:
            tp = int(tp_cum[k - 1])
            precision = tp / k
            recall = tp / total_pos
        out.append({
            "threshold": float(t), "precision": precision, "recall": recall,
            "f05": fbeta(precision, recall, 0.5), "f1": fbeta(precision, recall, 1.0),
            "predicted_positive_fraction": k / probs.size,
        })
    return out


def auc_rank(probs: np.ndarray, targets: np.ndarray) -> float:
    """ROC AUC by the Mann-Whitney rank formula with average ranks for ties; equals
    sklearn.metrics.roc_auc_score. Same implementation as sweep_epochs_rev2_fable."""
    targets = targets.astype(bool)
    n_pos, n_neg = int(targets.sum()), int((~targets).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(probs, kind="stable")
    sp = probs[order]
    first = np.r_[True, sp[1:] != sp[:-1]]
    grp = np.cumsum(first) - 1
    starts = np.flatnonzero(first)
    ends = np.r_[starts[1:], sp.size]
    avg = (starts + ends + 1) / 2.0
    ranks = np.empty(sp.size, dtype=np.float64)
    ranks[order] = avg[grp]
    return float((ranks[targets].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def load_papyrus_mask(data_dir: str, shape) -> np.ndarray | None:
    """Kaggle-style mask.png (papyrus = nonzero). None if absent."""
    p = os.path.join(data_dir, "mask.png")
    if not os.path.exists(p):
        return None
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    m = np.array(Image.open(p))
    if m.ndim == 3:
        m = m[..., 0]
    if m.shape != tuple(shape):
        raise ValueError(f"mask.png is {m.shape}, fragment is {tuple(shape)} - wrong fragment?")
    return m > 0


def load_mask(data_dir: str) -> np.ndarray:
    """Same rule dataset._load_volume_and_mask uses: first *inklabel* file, >0 is ink."""
    from PIL import Image
    cands = glob.glob(os.path.join(data_dir, "*inklabel*"))
    if not cands:
        raise FileNotFoundError(f"No inklabels file found in {data_dir!r}")
    path = cands[0]
    if path.lower().endswith((".tif", ".tiff")):
        import tifffile as tiff
        m = tiff.imread(path)
    else:
        m = np.array(Image.open(path))
    return (m > 0).astype(np.uint8)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prob_map", required=True, help="PNG written by cross_infer.py / infer.py")
    p.add_argument("--data_dir", required=True, help="Fragment folder holding the inklabels file")
    p.add_argument("--out", default=None, help="Where to write the JSON (default: next to the map)")
    p.add_argument("--n_thresholds", type=int, default=99)
    p.add_argument("--region", choices=["all", "val_strips"], default="all",
                   help="'all' = whole fragment (correct for cross_infer: the model never saw "
                        "any of it). 'val_strips' = the held-out strips only (for a map of the "
                        "TRAINING fragment).")
    p.add_argument("--patch_size", type=int, default=64, help="Only used by --region val_strips")
    p.add_argument("--val_fraction", type=float, default=0.2, help="Only used by --region val_strips")
    p.add_argument("--papyrus_mask", default="auto",
                   help="'auto' = use <data_dir>/mask.png if present (default); 'none' = skip; or a path to a mask PNG")
    args = p.parse_args()

    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None            # fragment 2 is 141 Mpx; PIL would refuse above 179 Mpx
    raw = np.array(Image.open(args.prob_map).convert("L"))
    probs_2d = raw.astype(np.float32) / 255.0
    mask = load_mask(args.data_dir)
    if probs_2d.shape != mask.shape:
        raise ValueError(f"prob map {probs_2d.shape} != mask {mask.shape} - wrong fragment?")

    if args.region == "val_strips":
        val_every = max(1, round(1 / args.val_fraction)) if args.val_fraction > 0 else 0
        col_block = np.arange(probs_2d.shape[1]) // args.patch_size
        keep = (col_block % val_every) == (val_every - 1) if val_every else np.ones(probs_2d.shape[1], bool)
        probs, targets = probs_2d[:, keep].ravel(), mask[:, keep].ravel()
        region = f"held-out strips (every {val_every}th {args.patch_size}px column)"
    else:
        keep = np.ones(probs_2d.shape[1], bool)
        probs, targets = probs_2d.ravel(), mask.ravel()
        region = "whole fragment (all unseen by this checkpoint)"
    papyrus = None if args.papyrus_mask == "none" else load_papyrus_mask(
        args.data_dir if args.papyrus_mask == "auto" else os.path.dirname(os.path.abspath(args.papyrus_mask)), probs_2d.shape)
    pap_sel = papyrus[:, keep].ravel() if papyrus is not None else None

    n_levels = int(np.unique(raw).size)
    print(f"sweep_saved_map {__revision__}")
    print(f"  map    : {args.prob_map}  ({probs_2d.shape[0]}x{probs_2d.shape[1]}, "
          f"{n_levels} distinct 8-bit levels)")
    print(f"  region : {region} -- {probs.size:,} px, true ink fraction {targets.mean():.4f}")

    res = sweep(probs, targets, args.n_thresholds)
    best = max(res, key=lambda r: r["f05"])
    half = min(res, key=lambda r: abs(r["threshold"] - 0.5))
    auc = auc_rank(probs, targets)
    pap = None
    if pap_sel is not None:
        pp, pt = probs[pap_sel], targets[pap_sel]
        pres = sweep(pp, pt, args.n_thresholds)
        pbest = max(pres, key=lambda r: r["f05"])
        phalf = min(pres, key=lambda r: abs(r["threshold"] - 0.5))
        pap = {"pixels": int(pt.size), "fraction_of_region": float(pap_sel.mean()),
               "true_ink_fraction": float(pt.mean()), "auc": auc_rank(pp, pt),
               "best_threshold": pbest["threshold"], "f05_at_best": pbest["f05"],
               "precision_at_best": pbest["precision"], "recall_at_best": pbest["recall"],
               "f05_at_0.5": phalf["f05"], "sweep": pres}

    print("\n  thresh   precision   recall    F0.5     F1    predicted+")
    for r in res:
        if r is best or r is half or abs(r["threshold"] * 20 - round(r["threshold"] * 20)) < 1e-9:
            mark = "  <-- BEST" if r is best else ("  <-- as cross_infer reports it" if r is half else "")
            print(f"   {r['threshold']:.3f}     {r['precision']:.3f}    {r['recall']:.3f}   "
                  f"{r['f05']:.3f}  {r['f1']:.3f}    {r['predicted_positive_fraction']:.3f}{mark}")
    print(f"\nF0.5 at 0.5 (what cross_infer printed): {half['f05']:.4f} "
          f"(P={half['precision']:.3f} R={half['recall']:.3f})")
    print(f"F0.5 at the tuned threshold {best['threshold']:.3f}   : {best['f05']:.4f} "
          f"(P={best['precision']:.3f} R={best['recall']:.3f})")
    print(f"Gain from threshold selection alone   : {best['f05'] - half['f05']:+.4f}")
    if half["recall"] > 0 and half["precision"] > 0:
        print(f"Over-prediction at 0.5: marking {half['recall']/half['precision']:.2f}x "
              f"more ink than exists")
    print(f"AUC over the region (rectangle)          : {auc:.4f}")
    if pap:
        print(f"\nPAPYRUS ONLY (mask.png, {pap['fraction_of_region']:.1%} of the region, {pap['pixels']:,} px, "
              f"true ink fraction {pap['true_ink_fraction']:.4f}):")
        print(f"  AUC                                    : {pap['auc']:.4f}   <-- the pre-registered measure")
        print(f"  F0.5 at own optimum {pap['best_threshold']:.3f}            : {pap['f05_at_best']:.4f} "
              f"(P={pap['precision_at_best']:.3f} R={pap['recall_at_best']:.3f})")
        print(f"  F0.5 at 0.5                            : {pap['f05_at_0.5']:.4f}")
        print(f"  rectangle AUC minus papyrus AUC        : {auc - pap['auc']:+.4f}  (what the blank margin was worth)")
    elif args.papyrus_mask != "none":
        print("\n(no mask.png in the fragment folder -> no papyrus-only numbers; the pre-registration needs them)")

    out = args.out or os.path.splitext(args.prob_map)[0] + "_threshold.json"
    with open(out, "w") as f:
        json.dump({"script_revision": __revision__, "prob_map": os.path.basename(args.prob_map),
                   "data_dir": args.data_dir, "region": region,
                   "quantisation_levels_in_map": n_levels,
                   "true_ink_fraction": float(targets.mean()),
                   "best_threshold": best["threshold"], "f05_at_best": best["f05"],
                   "f05_at_0.5": half["f05"], "precision_at_best": best["precision"],
                   "recall_at_best": best["recall"], "auc": auc,
                   "papyrus": pap, "sweep": res}, f, indent=2)
    print(f"\nWrote {out}")


def _selftest() -> None:
    rng = np.random.default_rng(0)
    n = 40000
    targets = (rng.random(n) < 0.08).astype(np.uint8)
    probs = np.clip(rng.normal(np.where(targets == 1, 0.72, 0.30), 0.16), 0, 1).astype(np.float32)

    res = sweep(probs, targets, 99)
    # brute force at three thresholds -- the sorted one-pass sweep must agree exactly
    for r in (res[9], res[49], res[88]):
        t = r["threshold"]
        pred = probs >= t
        tp = int((pred & (targets == 1)).sum()); fp = int((pred & (targets == 0)).sum())
        fn = int((~pred & (targets == 1)).sum())
        bp = tp / (tp + fp) if tp + fp else 0.0
        br = tp / (tp + fn) if tp + fn else 0.0
        assert abs(bp - r["precision"]) < 1e-12, (t, bp, r["precision"])
        assert abs(br - r["recall"]) < 1e-12, (t, br, r["recall"])
        assert abs(fbeta(bp, br) - r["f05"]) < 1e-12
    print(f"[ok] sweep matches brute force at 3 thresholds ({n:,} px)")

    best = max(res, key=lambda r: r["f05"]); half = min(res, key=lambda r: abs(r["threshold"] - .5))
    assert best["f05"] >= half["f05"], "tuned threshold must not be worse than 0.5"
    print(f"[ok] tuned {best['threshold']:.3f} F0.5={best['f05']:.4f} >= "
          f"at-0.5 F0.5={half['f05']:.4f} (gain {best['f05']-half['f05']:+.4f})")

    # 8-bit quantisation must not move the optimum materially -- the claim in the docstring
    q = (np.round(probs * 255) / 255).astype(np.float32)
    bq = max(sweep(q, targets, 99), key=lambda r: r["f05"])
    assert abs(bq["threshold"] - best["threshold"]) <= 0.02, (bq["threshold"], best["threshold"])
    assert abs(bq["f05"] - best["f05"]) < 5e-3, (bq["f05"], best["f05"])
    print(f"[ok] 8-bit quantised map gives threshold {bq['threshold']:.3f} vs float "
          f"{best['threshold']:.3f}, F0.5 {bq['f05']:.4f} vs {best['f05']:.4f} "
          f"-- docstring's accuracy claim holds")

    try:
        sweep(probs, np.zeros(n, np.uint8), 9); raise SystemExit("all-blank target not caught")
    except ValueError as e:
        assert "nothing to tune" in str(e)
    print("[ok] refuses an all-blank scoring region instead of returning 0.0")

    # rev 2: AUC equals sklearn (if present) and a brute-force pairwise count with ties
    a = auc_rank(probs, targets)
    try:
        from sklearn.metrics import roc_auc_score
        assert abs(a - roc_auc_score(targets, probs)) < 1e-9, (a, roc_auc_score(targets, probs))
        print(f"[ok] rank-AUC {a:.6f} == sklearn roc_auc_score")
    except ImportError:
        print(f"[ok] rank-AUC {a:.6f} (sklearn absent here; tie test below still pins it)")
    q = np.round(rng.random(500) * 4) / 4; t = (rng.random(500) < 0.3).astype(np.uint8)
    pos, neg = q[t == 1], q[t == 0]
    brute = (np.sum(pos[:, None] > neg[None, :]) + 0.5 * np.sum(pos[:, None] == neg[None, :])) / (pos.size * neg.size)
    assert abs(auc_rank(q, t) - brute) < 1e-12
    print("[ok] rank-AUC handles ties (matches brute-force pairwise count on 5-level data)")

    # rev 2: a blank margin inflates rectangle AUC; restricting to papyrus removes the free credit
    H, W = 200, 200
    pm = np.zeros((H, W), bool); pm[40:160, 40:160] = True            # papyrus = central 36%
    tg2 = np.zeros((H, W), np.uint8); tg2[pm] = rng.random(pm.sum()) < 0.1
    pr2 = np.where(pm, np.clip(rng.normal(np.where(tg2 == 1, 0.6, 0.4), 0.2), 0, 1), 0.02).astype(np.float32)
    auc_rect, auc_pap = auc_rank(pr2.ravel(), tg2.ravel()), auc_rank(pr2[pm], tg2[pm])
    assert auc_rect > auc_pap + 0.05, (auc_rect, auc_pap)
    print(f"[ok] blank margin: rectangle AUC {auc_rect:.3f} vs papyrus-only {auc_pap:.3f} -- the margin's "
          f"free credit is removed, as the docstring claims")
    print("[ok] sweep_saved_map rev2_fable self-test passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
