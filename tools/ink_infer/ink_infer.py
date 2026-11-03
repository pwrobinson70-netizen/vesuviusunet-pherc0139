#!/usr/bin/env python3
"""ink_infer: run a trained VesuviusUNET 3-D U-Net checkpoint over a traced segment (MIT).

    tifxyz mesh + CT volume (OME-Zarr) -> surface volume at the training pitch
    -> tiled 3-D U-Net inference -> stitched ink-probability map (.npy, .png).

The output is a PICTURE, not a score: no labels are used. Read README.md for the limits.
Resumable: with --work-dir the accumulators are saved atomically, so an overnight run that is
interrupted continues where it stopped (--resume).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))      # repo root: vesuvius_unet
from surface import (CTVolume, InputError, extract_patch, layer_offsets, load_mesh,  # noqa: E402
                     pad_surface, resample_mesh)

__version__ = "0.1.0"
TRAIN_PITCH_UM = 3.24      # voxel pitch the frozen checkpoints were trained at (scripts/ converter)


# ------------------------------------------------------------------ checkpoint
def sha256_file(path, n=16):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]


def load_checkpoint(path, device="cpu", trust=False):
    """Load a checkpoint. weights_only=True first (no pickled code); --trust-checkpoint opts out."""
    import torch
    if not os.path.isfile(str(path)):
        raise InputError(f"checkpoint not found: {path}")
    try:
        return torch.load(path, map_location=device, weights_only=True)
    except Exception as e:  # noqa: BLE001
        if not trust:
            raise InputError(f"cannot load {path} with weights_only=True ({type(e).__name__}); if you "
                             "trust the file, rerun with --trust-checkpoint") from e
        return torch.load(path, map_location=device, weights_only=False)


def build_model(ckpt, device="cpu"):
    """Rebuild the model exactly as trained: from the checkpoint's own args/contract, never defaults."""
    from vesuvius_unet.model import UNet3D
    args = dict(ckpt.get("args") or {})
    con = dict(ckpt.get("contract") or {})
    model = UNet3D(in_channels=1, base_channels=args.get("base_channels", 16),
                   aggregation=con.get("aggregation", args.get("aggregation", "max")),
                   topk=con.get("topk", args.get("topk"))).to(device)
    if "model" not in ckpt:
        raise InputError("checkpoint has no 'model' state_dict")
    sd = {k.removeprefix("module."): v for k, v in ckpt["model"].items()}      # DataParallel
    model.load_state_dict(sd)
    model.eval()
    return model, args, con


# --------------------------------------------------------------------- stitching
def patch_grid(n, size, stride):
    """Start offsets covering [0, n) including the last partial step (no untiled border)."""
    if n <= size:
        return [0]
    s = list(range(0, n - size + 1, stride))
    if s[-1] != n - size:
        s.append(n - size)
    return s


def blend_window(size, kind):
    if kind == "mean":
        return np.ones((size, size), np.float32)
    r = np.minimum(np.arange(size) + 1, size - np.arange(size)).astype(np.float32)
    r = np.clip(r / (size / 2), 0.05, 1.0)
    return np.outer(r, r).astype(np.float32)


def intensity_rule(sample, ref_p1, ref_p99):
    """The converter's mechanical rule: rescale iff p99 is outside [0.5, 2.0] x reference p99.
    Returns (scale, offset, note); linear map sample p1/p99 -> reference p1/p99."""
    if ref_p99 is None or sample.size == 0:
        return 1.0, 0.0, "no intensity rule"
    p1, p99 = np.percentile(sample, [1, 99])
    if 0.5 * ref_p99 <= p99 <= 2.0 * ref_p99:
        return 1.0, 0.0, f"p99 {p99:.4f} inside [0.5,2]x ref {ref_p99:.4f}: unchanged"
    a = (ref_p99 - (ref_p1 or 0.0)) / max(p99 - p1, 1e-9)
    return float(a), float((ref_p1 or 0.0) - a * p1), f"p99 {p99:.4f} outside rule: rescaled"


def run_inference(model, vol, surf, *, depth, patch, stride, layer_step_vox, device="cpu",
                  batch_size=4, amp=False, tta=False, workers=2, blend="hann", min_valid_frac=0.05,
                  work_dir=None, resume=False, save_every=50, scale=1.0, offset=0.0,
                  log=print, config=None):
    """Tiled inference. Returns (prob float32 (H,W) -- 0 where invalid, weight, stats dict)."""
    import torch
    surf = pad_surface(surf, patch)
    H, W = surf.shape
    ys, xs = patch_grid(H, patch, stride), patch_grid(W, patch, stride)
    coords = [(y, x) for y in ys for x in xs
              if surf.valid[y:y + patch, x:x + patch].mean() >= min_valid_frac]
    offs = layer_offsets(depth, layer_step_vox)
    win = blend_window(patch, blend)
    psum, wsum, done = np.zeros((H, W), np.float32), np.zeros((H, W), np.float32), 0

    state = os.path.join(work_dir, "state.npz") if work_dir else None
    cfg = json.dumps(config or {}, sort_keys=True, default=str)
    if state and resume and os.path.isfile(state):
        z = np.load(state, allow_pickle=False)
        if str(z["cfg"]) != cfg:
            raise InputError("--resume: the work-dir state was made with different settings; "
                             "use a fresh --work-dir (or delete state.npz)")
        psum, wsum, done = z["psum"], z["wsum"], int(z["done"])
        log(f"resumed: {done}/{len(coords)} patches already done")

    def save_state(n):
        if not state:
            return
        os.makedirs(work_dir, exist_ok=True)
        tmp = state + ".tmp.npz"
        np.savez(tmp, psum=psum, wsum=wsum, done=n, cfg=cfg)
        os.replace(tmp, state)

    def make(c):
        p, v = extract_patch(vol, surf, c[0], c[1], patch, offs)
        return np.clip(p * scale + offset, 0.0, 1.0).astype(np.float32), v

    t0, done0 = time.time(), done
    use_amp = amp and str(device).startswith("cuda")
    batches = [coords[i:i + batch_size] for i in range(done, len(coords), batch_size)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex, torch.no_grad():
        futs = [ex.submit(lambda b=b: [make(c) for c in b]) for b in batches[:workers + 1]]
        nxt = len(futs)
        for bi, b in enumerate(batches):
            res = futs[bi].result()
            futs[bi] = None
            if nxt < len(batches):
                futs.append(ex.submit(lambda b=batches[nxt]: [make(c) for c in b]))
                nxt += 1
            x = torch.from_numpy(np.stack([r[0] for r in res])).unsqueeze(1).to(device)
            with torch.autocast("cuda", enabled=use_amp):
                lg = model.ink_logits_2d(x)
                if tta:
                    lg = (lg + model.ink_logits_2d(x.flip(-1)).flip(-1)
                          + model.ink_logits_2d(x.flip(-2)).flip(-2)) / 3.0
            pr = torch.sigmoid(lg.float()).squeeze(1).cpu().numpy()
            for (y, x0), p, (_, v) in zip(b, pr, res):
                w = win * v
                psum[y:y + patch, x0:x0 + patch] += p * w
                wsum[y:y + patch, x0:x0 + patch] += w
            done += len(b)
            if (bi + 1) % save_every == 0:
                save_state(done)
                el = time.time() - t0
                n_now = done - done0                      # patches done in THIS session (resume-safe)
                log(f"{done}/{len(coords)} patches  {el / 60:.1f} min  eta {(len(coords) - done) * el / max(1, n_now) / 60:.1f} min")
    save_state(done)
    prob = np.where(wsum > 0, psum / np.maximum(wsum, 1e-9), 0.0).astype(np.float32)
    prob[~surf.valid] = 0.0
    return prob, surf, dict(patches=len(coords), seconds=time.time() - t0, shape=[H, W])


# -------------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mesh", help="tifxyz folder (x.tif y.tif z.tif meta.json)")
    ap.add_argument("--zarr", required=True, help="OME-Zarr CT volume")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--trust-checkpoint", action="store_true", help="allow pickled (weights_only=False) load")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--work-dir", help="resumable state (default: <out-dir>/work)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--scan-voxel-um", type=float, help="CT voxel size (default: mesh meta.json)")
    ap.add_argument("--out-pitch-um", type=float, default=TRAIN_PITCH_UM,
                    help="pitch of the output grid AND of the layers; must equal the training pitch")
    ap.add_argument("--mesh-scale", type=float, nargs=2, metavar=("SX", "SY"), help="override meta.json scale")
    ap.add_argument("--depth", type=int, help="layers (default: checkpoint contract/args)")
    ap.add_argument("--patch", type=int, help="patch size (default: checkpoint contract/args, else 256)")
    ap.add_argument("--stride", type=int, help="default patch/2")
    ap.add_argument("--flip-normal", action="store_true", help="reverse the layer order (run both, compare by eye)")
    ap.add_argument("--norm-max", type=float, help="intensity divisor (default: dtype max, i.e. uint8 -> /255)")
    ap.add_argument("--ref-p1", type=float, help="reference 1st percentile (0..1) for the intensity rule")
    ap.add_argument("--ref-p99", type=float, help="reference 99th percentile (0..1); enables the intensity rule")
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2, help="patch-extraction threads")
    ap.add_argument("--amp", action="store_true", help="CUDA mixed precision")
    ap.add_argument("--tta", action="store_true", help="average with H/W flips (3x slower)")
    ap.add_argument("--blend", choices=("hann", "mean"), default="hann")
    ap.add_argument("--min-valid-frac", type=float, default=0.05)
    ap.add_argument("--save-every", type=int, default=50, help="batches between state saves")
    ap.add_argument("--threshold", type=float, help="also write a binary PNG at this probability")
    ap.add_argument("--device", default=None)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    import torch
    device = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    try:
        mesh = load_mesh(a.mesh)
        vox = a.scan_voxel_um or mesh.voxel_um
        if not vox:
            raise InputError("scan voxel size unknown: add it to meta.json or pass --scan-voxel-um")
        ckpt = load_checkpoint(a.checkpoint, "cpu", a.trust_checkpoint)
        model, targs, con = build_model(ckpt, device)
        depth = a.depth or con.get("depth") or targs.get("depth") or 64
        patch = a.patch or con.get("patch_size") or targs.get("patch_size") or 256
        for k, v in (("depth", depth), ("patch_size", patch)):
            if con.get(k) not in (None, v):
                print(f"WARNING: --{k} {v} differs from the checkpoint contract ({con[k]})", file=sys.stderr)
        if abs(a.out_pitch_um - TRAIN_PITCH_UM) > 1e-6:
            print(f"WARNING: out pitch {a.out_pitch_um} um != training pitch {TRAIN_PITCH_UM} um; the "
                  "model has not seen this scale", file=sys.stderr)
        step = a.out_pitch_um / vox                       # voxels per output pixel and per layer
        vol = CTVolume.open_zarr(a.zarr, a.zarr_level, a.norm_max)
        surf = resample_mesh(mesh, step, a.flip_normal, tuple(a.mesh_scale) if a.mesh_scale else None)
        if not surf.valid.any():
            raise InputError("no valid surface pixels after resampling")
        scale, offset, note = 1.0, 0.0, "no intensity rule"
        if a.ref_p99 is not None:
            ys, xs = np.nonzero(surf.valid)
            pick = np.random.default_rng(0).choice(len(ys), min(20000, len(ys)), replace=False)
            c = surf.P[ys[pick], xs[pick]]
            scale, offset, note = intensity_rule(vol.sample(c).ravel(), a.ref_p1, a.ref_p99)
        os.makedirs(a.out_dir, exist_ok=True)
        cfg = dict(version=__version__, mesh=a.mesh, zarr=a.zarr, level=a.zarr_level, ckpt=sha256_file(a.checkpoint),
                   depth=depth, patch=patch, step=step, flip=a.flip_normal, scale=scale, offset=offset,
                   blend=a.blend, tta=a.tta, stride=a.stride or patch // 2, pitch=a.out_pitch_um,
                   vox=vox, mesh_scale=a.mesh_scale or mesh.scale, norm_max=vol.norm_max,
                   min_valid_frac=a.min_valid_frac)       # anything that changes the patch list or pixels
        prob, surf2, st = run_inference(
            model, vol, surf, depth=depth, patch=patch, stride=a.stride or patch // 2, layer_step_vox=step,
            device=device, batch_size=a.batch_size, amp=a.amp, tta=a.tta, workers=a.workers, blend=a.blend,
            min_valid_frac=a.min_valid_frac, work_dir=a.work_dir or os.path.join(a.out_dir, "work"),
            resume=a.resume, save_every=a.save_every, scale=scale, offset=offset, config=cfg)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    from PIL import Image
    np.save(os.path.join(a.out_dir, "ink_prob.npy"), prob.astype(np.float16))
    Image.fromarray((prob * 255).astype(np.uint8)).save(os.path.join(a.out_dir, "ink_prob.png"))
    Image.fromarray((surf2.valid * 255).astype(np.uint8)).save(os.path.join(a.out_dir, "valid_mask.png"))
    if a.threshold is not None:
        Image.fromarray(((prob >= a.threshold) * 255).astype(np.uint8)).save(os.path.join(a.out_dir, "ink_binary.png"))
    prov = dict(config=cfg, intensity=note, device=str(device), stats=st, contract=con,
                notes=["picture, not a score: no labels were used", "checkpoint trained at "
                       f"{TRAIN_PITCH_UM} um on PHerc0139 data; transfer to other scans is unvalidated"])
    json.dump(prov, open(os.path.join(a.out_dir, "run.json"), "w"), indent=2, default=str)
    print(f"done: {st['patches']} patches in {st['seconds'] / 60:.1f} min -> {a.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
