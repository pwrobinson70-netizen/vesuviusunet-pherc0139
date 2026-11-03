#!/usr/bin/env python3
"""phantom_e2e: train a TINY ink model on phantom scrolls and score ink_infer against the known letters (MIT).

Everything is synthetic (tools/phantom_scroll with --ink). Nothing here says anything about real scans.

    # 1. phantoms with different seeds and different letters (see README, "End to end on phantoms")
    # 2. train on patches sampled ON THE TRUE SURFACE of the ink turn, label = ink mask
    python tools/ink_infer/phantom_e2e.py train --train PH/train1 PH/train2 --val PH/val \
        --out tools/ink_infer/phantom_ckpt/tiny.pt
    # 3. run the ink_infer pipeline on val, on the test true surface and on the test BAD trace; score
    python tools/ink_infer/phantom_e2e.py score --ckpt tools/ink_infer/phantom_ckpt/tiny.pt \
        --val PH/val --test PH/test --work W --json result.json --png-dir docs/ink_e2e

Scores: ROC AUC and F0.5 against the letter mask of the ink turn, resampled (nearest cell) to the ink_infer
output grid. The F0.5 threshold is the best one on the VAL phantom, applied unchanged to the test phantom
(the test-best value is also printed, for reference only).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
from surface import CTVolume, extract_patch, layer_offsets, load_mesh, resample_mesh  # noqa: E402


# ----------------------------------------------------------------------------- data
def load_phantom(root, step=1.0):
    """(volume, surface of the ink turn, ink label on the surface grid (H, W) uint8)."""
    from PIL import Image
    from scipy.ndimage import map_coordinates
    truth = json.load(open(os.path.join(root, "truth.json")))
    turn = truth["ink"]["turn"]
    mesh = load_mesh(os.path.join(root, "surfaces", f"turn_{turn:02d}"))
    surf = resample_mesh(mesh, step)
    m = np.asarray(Image.open(os.path.join(root, truth["ink"]["mask"]))) > 0
    sx, sy = mesh.scale
    H, W = surf.shape
    # pixel (i, j) sits at grid cell (i*step*sy, j*step*sx): the rule surface.resample_mesh uses
    rr, cc = np.meshgrid(np.arange(H) * step * sy, np.arange(W) * step * sx, indexing="ij")
    lab = (map_coordinates(m.astype(np.float32), [rr, cc], order=0, mode="nearest") > 0.5).astype(np.uint8)
    return CTVolume.open_zarr(os.path.join(root, "volume.zarr"), 0), surf, lab


# ----------------------------------------------------------------------------- train
def train(a):
    import torch
    import torch.nn.functional as F
    from vesuvius_unet.model import UNet3D, count_params
    torch.set_num_threads(a.threads)
    rng = np.random.default_rng(a.seed)
    torch.manual_seed(a.seed)
    offs = layer_offsets(a.depth, 1.0)

    def prep(roots):
        out = []
        for r in roots:
            vol, surf, lab = load_phantom(r)
            ok = np.argwhere(surf.valid[:-a.patch, :-a.patch])
            out.append((vol, surf, lab, ok))
        return out

    tr, va = prep(a.train), prep(a.val)

    def sample(sets, n):
        X, Y, V = [], [], []
        while len(X) < n:
            vol, surf, lab, ok = sets[rng.integers(len(sets))]
            y, x = ok[rng.integers(len(ok))]
            lb = lab[y:y + a.patch, x:x + a.patch]
            if rng.random() < a.ink_frac and lb.sum() == 0:       # force ink-containing patches a fraction of the time
                continue
            p, v = extract_patch(vol, surf, y, x, a.patch, offs)
            if v.mean() < a.min_valid:
                continue
            X.append(p); Y.append(lb); V.append(v)
        t = lambda z: torch.from_numpy(np.stack(z).astype(np.float32))
        return t(X).unsqueeze(1), t(Y), t(V)

    model = UNet3D(1, a.base_channels)
    n_par = count_params(model)
    print(f"params {n_par}", flush=True)
    if n_par >= a.max_params:
        raise SystemExit(f"{n_par} params >= --max-params {a.max_params}")
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    vx, vy, vv = sample(va, a.val_patches)                         # fixed validation batch
    t0, step, best = time.time(), 0, (1e9, None)
    while (time.time() - t0) / 60 < a.minutes and step < a.max_steps:
        model.train()
        x, y, v = sample(tr, a.batch)
        lg = model.ink_logits_2d(x).squeeze(1)
        loss = (F.binary_cross_entropy_with_logits(lg, y, reduction="none") * v).sum() / v.sum().clamp(min=1)
        opt.zero_grad(); loss.backward(); opt.step(); step += 1
        if step % a.eval_every == 0:
            model.eval()
            with torch.no_grad():
                lg = model.ink_logits_2d(vx).squeeze(1)
                vl = ((F.binary_cross_entropy_with_logits(lg, vy, reduction="none") * vv).sum() / vv.sum()).item()
            if vl < best[0]:
                best = (vl, {k: t.detach().clone() for k, t in model.state_dict().items()})
            print(f"step {step} train {loss.item():.4f} val {vl:.4f} best {best[0]:.4f} "
                  f"{(time.time() - t0) / 60:.1f} min", flush=True)
    sd = best[1] or model.state_dict()
    con = dict(aggregation="max", topk=None, depth=a.depth, patch_size=a.patch)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    torch.save({"model": sd, "args": dict(base_channels=a.base_channels, aggregation="max", topk=None,
                                          depth=a.depth, patch_size=a.patch), "contract": con}, a.out)
    size = os.path.getsize(a.out)
    print(f"saved {a.out}  {size / 1e6:.2f} MB  params {n_par}  steps {step}  best val loss {best[0]:.4f}")
    if size >= a.max_mb * 1e6:
        os.remove(a.out)
        print(f"checkpoint >= {a.max_mb} MB: deleted (do not commit it)")
        return 1
    return 0


# ----------------------------------------------------------------------------- score
def f_beta(tp, n_pred, n_pos, beta=0.5):
    prec = tp / n_pred if n_pred else 0.0
    rec = tp / n_pos if n_pos else 0.0
    b2 = beta * beta
    return (1 + b2) * prec * rec / (b2 * prec + rec) if prec + rec > 0 else 0.0


def f05_at(prob, lab, valid, thr):
    p, l = prob[valid], lab[valid] > 0
    pr = p >= thr
    return f_beta(float((pr & l).sum()), float(pr.sum()), float(l.sum()))


def best_f05(prob, lab, valid, n=101):
    ths = np.linspace(0, 1, n)
    f = [f05_at(prob, lab, valid, t) for t in ths]
    i = int(np.argmax(f))
    return float(ths[i]), float(f[i])


def auc(prob, lab, valid):
    from sklearn.metrics import roc_auc_score
    l = lab[valid] > 0
    return float(roc_auc_score(l, prob[valid])) if 0 < l.sum() < l.size else float("nan")


def run_ink_infer(mesh_dir, zarr, ckpt, out):
    """The real CLI entry (ink_infer.main), not a re-implementation."""
    from PIL import Image
    import ink_infer
    rc = ink_infer.main([mesh_dir, "--zarr", zarr, "--checkpoint", ckpt, "--out-dir", out,
                         "--scan-voxel-um", "3.24", "--out-pitch-um", "3.24", "--batch-size", "8"])
    if rc:
        raise SystemExit(f"ink_infer failed ({rc}) on {mesh_dir}")
    return (np.load(os.path.join(out, "ink_prob.npy")).astype(np.float32),
            np.asarray(Image.open(os.path.join(out, "valid_mask.png"))) > 0)


def score(a):
    from PIL import Image
    vt = json.load(open(os.path.join(a.val, "truth.json")))
    tt = json.load(open(os.path.join(a.test, "truth.json")))
    turn = vt["ink"]["turn"]
    res = {}
    # ---- val: choose the threshold
    vmesh = os.path.join(a.val, "surfaces", f"turn_{turn:02d}")
    vp, vvalid = run_ink_infer(vmesh, os.path.join(a.val, "volume.zarr"), a.ckpt, os.path.join(a.work, "val"))
    vlab = load_phantom(a.val)[2]
    thr, vf = best_f05(vp, vlab, vvalid)
    res["val"] = dict(text=vt["ink"]["text"], auc=auc(vp, vlab, vvalid), best_threshold=thr, f05=vf,
                      ink_fraction=float(vlab[vvalid].mean()))
    # ---- test, true surface
    tmesh = os.path.join(a.test, "surfaces", f"turn_{turn:02d}")
    tp, tvalid = run_ink_infer(tmesh, os.path.join(a.test, "volume.zarr"), a.ckpt, os.path.join(a.work, "test_true"))
    tlab = load_phantom(a.test)[2]
    frac = float(tlab[tvalid].mean())
    res["test_true_surface"] = dict(
        text=tt["ink"]["text"], auc=auc(tp, tlab, tvalid), threshold_from_val=thr,
        f05_at_val_threshold=f05_at(tp, tlab, tvalid, thr),
        f05_best_on_test_reference_only=best_f05(tp, tlab, tvalid)[1],
        ink_fraction=frac, f05_predict_all_ink_baseline=f_beta(frac * tvalid.sum(), tvalid.sum(), frac * tvalid.sum()))
    # ---- test, bad trace (planted switch)
    sw = tt["switches"][0]
    bp, bvalid = run_ink_infer(os.path.join(a.test, sw["trace"]), os.path.join(a.test, "volume.zarr"), a.ckpt,
                               os.path.join(a.work, "test_bad"))
    assert bp.shape == tp.shape, (bp.shape, tp.shape)
    scale_x = json.load(open(os.path.join(tmesh, "meta.json")))["scale"][0]
    col_px = int(round(sw["col"] / scale_x))                       # grid col -> output px (1 vox per px)
    cols = np.broadcast_to(np.arange(tp.shape[1])[None, :], tp.shape)
    both = tvalid & bvalid
    bad = dict(text=tt["ink"]["text"], switch_col_px=col_px, switch_direction=sw["direction"],
               margin_px=a.margin_px, f05_at_val_threshold_whole_map=f05_at(bp, tlab, both, thr))
    for name, z in (("before_switch", cols < col_px - a.margin_px), ("after_switch", cols > col_px + a.margin_px)):
        m = z & both
        for lbl, p in (("true_trace", tp), ("bad_trace", bp)):
            bad[f"{name}.{lbl}.auc"] = auc(p, tlab, m)
            bad[f"{name}.{lbl}.mean_prob_on_ink"] = float(p[m & (tlab > 0)].mean())
            bad[f"{name}.{lbl}.mean_prob_off_ink"] = float(p[m & (tlab == 0)].mean())
            bad[f"{name}.{lbl}.f05_at_val_threshold"] = f05_at(p, tlab, m, thr)
    res["test_bad_trace"] = bad
    print(json.dumps(res, indent=2))
    if a.json:
        json.dump(res, open(a.json, "w"), indent=2)
    if a.png_dir:
        os.makedirs(a.png_dir, exist_ok=True)
        g8 = lambda p: (np.clip(p, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(g8(tp)).save(os.path.join(a.png_dir, "ink_map_true_surface.png"))
        Image.fromarray(g8(bp)).save(os.path.join(a.png_dir, "ink_map_bad_trace.png"))
        Image.fromarray(g8(tlab.astype(np.float32))).save(os.path.join(a.png_dir, "truth_letter_mask.png"))
        H, W = tp.shape       # panel: truth | true-surface map | bad-trace map (red line = switch column)
        pan = np.full((H, 3 * W + 8, 3), 90, np.uint8)
        for k, p in enumerate((tlab.astype(np.float32), tp, bp)):
            pan[:, k * (W + 4):k * (W + 4) + W] = g8(p)[..., None]
        pan[:, 2 * (W + 4) + col_px] = (255, 0, 0)
        Image.fromarray(pan).save(os.path.join(a.png_dir, "panel_truth_true_bad.png"))
    return 0


# ----------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="train the tiny model on phantom patches")
    t.add_argument("--train", nargs="+", required=True, help="phantom dirs (made with --ink)")
    t.add_argument("--val", nargs="+", required=True, help="phantom dirs, different seed AND letters")
    t.add_argument("--out", required=True)
    t.add_argument("--base-channels", type=int, default=3)
    t.add_argument("--depth", type=int, default=16, help="layers along the normal (1 vox apart)")
    t.add_argument("--patch", type=int, default=32, help="patch edge (px); multiple of 16")
    t.add_argument("--batch", type=int, default=8)
    t.add_argument("--lr", type=float, default=3e-3)
    t.add_argument("--minutes", type=float, default=12.0, help="wall-clock training budget")
    t.add_argument("--max-steps", type=int, default=10 ** 9)
    t.add_argument("--eval-every", type=int, default=25)
    t.add_argument("--val-patches", type=int, default=64)
    t.add_argument("--ink-frac", type=float, default=0.5, help="fraction of training patches forced to contain ink")
    t.add_argument("--min-valid", type=float, default=0.9, help="min valid-pixel fraction of a training patch")
    t.add_argument("--max-params", type=int, default=200_000)
    t.add_argument("--max-mb", type=float, default=5.0, help="delete the checkpoint if it is this big (MB) or bigger")
    t.add_argument("--threads", type=int, default=4)
    t.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("score", help="ink_infer on val / test / bad trace, scored against the letter mask")
    s.add_argument("--ckpt", required=True)
    s.add_argument("--val", required=True, help="one phantom dir")
    s.add_argument("--test", required=True, help="one phantom dir made with --bad-switch")
    s.add_argument("--work", required=True)
    s.add_argument("--json")
    s.add_argument("--png-dir")
    s.add_argument("--margin-px", type=int, default=16,
                   help="columns around the switch left out of the before/after zones")
    a = ap.parse_args(argv)
    return train(a) if a.cmd == "train" else score(a)


if __name__ == "__main__":
    sys.exit(main())
