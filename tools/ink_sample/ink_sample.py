#!/usr/bin/env python3
"""ink_sample: read a published 3-D ink volume onto one traced surface (MIT).

    tifxyz trace + 3-D ink zarr (OME level L) -> samples along the trace normal at offsets
    lo..hi (voxels AT LEVEL L) -> 2-D max and mean projections on the trace grid
    (float32 TIFF + a small PNG thumbnail + meta.json).

No model is run and nothing is learned: this only resamples someone else's 3-D ink prediction
onto our trace, so the two can be compared. Only the zarr chunks under each output tile are read.
The thumbnail is capped at --thumb-max pixels on its long side (default 512) on purpose.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "..", "ink_infer"), HERE):
    _p = os.path.abspath(_p)
    if _p not in sys.path:
        sys.path.insert(0, _p)
from surface import CTVolume, InputError, _check_ome_scale, load_mesh, resample_mesh  # noqa: E402

__version__ = "0.1.0"


def normal_offsets(lo, hi, level, step=1.0):
    """Offsets along the normal in LEVEL-0 voxels for lo..hi (inclusive) given in level-L voxels."""
    if hi < lo:
        raise InputError(f"offset range is empty: lo={lo} > hi={hi}")
    if step <= 0:
        raise InputError(f"--offset-step must be > 0, got {step}")
    n = int(np.floor((hi - lo) / step + 1e-9)) + 1
    return (lo + np.arange(n) * step) * float(2 ** level)


def open_ink(path, level, norm_max=None):
    """CTVolume over a local OME-Zarr or an http(s) URL (read chunk by chunk, nothing stored)."""
    if str(path).startswith(("http://", "https://")):
        from http_zarr import HttpZarrError, open_level
        try:
            arr, datasets = open_level(str(path), level)
        except HttpZarrError as e:
            raise InputError(f"{path}: {e}") from e
        if datasets:
            _check_ome_scale(type("N", (), {"attrs": {"multiscales": [{"datasets": datasets}]}})(), level, path)
        return CTVolume(arr, level, norm_max)
    return CTVolume.open_zarr(path, level, norm_max=norm_max)


def transform_mesh(mesh, offset=None, scale=1.0):
    """Trace coordinates -> ink-zarr level-0 voxels: (P + offset) * scale. The grid spacing scales with it."""
    if offset is None and scale == 1.0:
        return mesh
    if scale <= 0:
        raise InputError(f"--trace-scale must be > 0, got {scale}")
    off = np.zeros(3) if offset is None else np.asarray(offset, np.float64)
    mesh.P = (mesh.P + off) * float(scale)
    if mesh.scale is not None:
        mesh.scale = (mesh.scale[0] / scale, mesh.scale[1] / scale)
    return mesh


MAX_BLOCK_VOX = 64_000_000   # largest bounding block read at once (a scrambled trace can otherwise span the whole volume)


def sample_capped(vol: CTVolume, pts, max_vox=MAX_BLOCK_VOX):
    """vol.sample(pts) for (..., 3) level-0 xyz points, splitting the points (sorted by z) so that no single read's
    bounding block exceeds max_vox voxels at the volume's level. Same values as vol.sample; bounded memory."""
    shp = pts.shape[:-1]
    flat = pts.reshape(-1, 3)
    out = np.zeros(len(flat), np.float32)
    ok = np.isfinite(flat).all(axis=1)
    idx = np.nonzero(ok)[0]
    if len(idx) == 0:
        return out.reshape(shp)
    idx = idx[np.argsort(flat[idx, 2], kind="stable")]

    def vox(sel):
        q = vol.to_px(flat[sel])
        ext = np.ceil(q.max(axis=0)) - np.floor(q.min(axis=0)) + 3
        return float(np.prod(ext))

    stack = [idx]
    while stack:
        sel = stack.pop()
        if len(sel) > 1 and vox(sel) > max_vox:
            h = len(sel) // 2
            stack += [sel[:h], sel[h:]]
            continue
        out[sel] = vol.sample(flat[sel])
    return out.reshape(shp)


def sample_projections(vol: CTVolume, surf, offsets, tile=128, log=None, profile=None):
    """(max, mean) float32 images on the surface grid; NaN where the surface is invalid.

    Works tile by tile so each zarr read covers only the bounding box of that tile's sample points.
    `profile` (optional array of offsets): also returns the mean value over all valid pixels at each of those
    offsets, a 1-D check of where along the normal the ink sits.
    """
    H, W = surf.shape
    mx = np.full((H, W), np.nan, np.float32)
    mn = np.full((H, W), np.nan, np.float32)
    n_t = ((H + tile - 1) // tile) * ((W + tile - 1) // tile)
    psum = None if profile is None else np.zeros(len(profile))
    pn = 0
    done = 0
    t0 = time.time()
    for y0 in range(0, H, tile):
        for x0 in range(0, W, tile):
            v = surf.valid[y0:y0 + tile, x0:x0 + tile]
            done += 1
            if not v.any():
                continue
            P = surf.P[y0:y0 + tile, x0:x0 + tile][v]               # (n, 3)
            N = surf.N[y0:y0 + tile, x0:x0 + tile][v]
            pts = P[None] + offsets[:, None, None] * N[None]          # (D, n, 3)
            s = sample_capped(vol, pts)                                # (D, n)
            bm = mx[y0:y0 + tile, x0:x0 + tile]
            ba = mn[y0:y0 + tile, x0:x0 + tile]
            bm[v] = s.max(axis=0)
            ba[v] = s.mean(axis=0)
            if profile is not None:
                psum += sample_capped(vol, P[None] + profile[:, None, None] * N[None]).sum(axis=1)
                pn += len(P)
            if log and (done % 50 == 0 or done == n_t):
                log(f"tile {done}/{n_t}  {time.time() - t0:.0f}s")
    if profile is None:
        return mx, mn
    return mx, mn, (psum / max(pn, 1))


def thumbnail(img, max_side=512):
    """uint8 PNG array, long side <= max_side, invalid -> 0, scaled 0..1 -> 0..255 (no stretching)."""
    from PIL import Image
    a = np.nan_to_num(img, nan=0.0)
    a = np.clip(a, 0.0, 1.0)
    im = Image.fromarray(np.rint(a * 255).astype(np.uint8))
    H, W = a.shape
    f = max(H, W) / float(max_side)
    if f > 1:
        im = im.resize((max(1, int(round(W / f))), max(1, int(round(H / f)))), Image.BILINEAR)
    return im


def run(a, log=print):
    mesh = load_mesh(a.trace)
    off = list(a.trace_offset) if a.trace_offset else None
    if a.window_offset:
        w = mesh.meta.get("window")
        if not isinstance(w, dict) or "x0" not in w or "y0" not in w:
            raise InputError(f"{a.trace}: --window-offset needs meta.json 'window' with x0 and y0")
        off = [float(w["x0"]), float(w["y0"]), 0.0]
    mesh = transform_mesh(mesh, off, a.trace_scale)
    sc = tuple(a.mesh_scale) if a.mesh_scale else None
    step = a.step if a.step is not None else float(2 ** a.level)
    surf = resample_mesh(mesh, step, flip_normal=a.flip_normal, scale=sc)
    vol = open_ink(a.ink_zarr, a.level, norm_max=a.norm_max)
    offs = normal_offsets(a.lo, a.hi, a.level, a.offset_step)
    log(f"surface {surf.shape[0]}x{surf.shape[1]} at {step:g} vox/pixel, {surf.valid.mean():.1%} valid; "
        f"zarr level {a.level} shape {tuple(vol.data.shape)}; {len(offs)} offsets "
        f"{offs[0]:g}..{offs[-1]:g} level-0 vox")
    prof_offs = None
    if a.profile is not None:
        prof_offs = normal_offsets(-a.profile, a.profile, a.level)
    res = sample_projections(vol, surf, offs, tile=a.tile, log=log, profile=prof_offs)
    mx, mn = res[0], res[1]
    os.makedirs(a.out, exist_ok=True)
    import tifffile
    tifffile.imwrite(os.path.join(a.out, "ink_max.tif"), mx)
    tifffile.imwrite(os.path.join(a.out, "ink_mean.tif"), mn)
    thumbnail(mx, a.thumb_max).save(os.path.join(a.out, "ink_max_thumb.png"))
    if prof_offs is not None:
        with open(os.path.join(a.out, "profile.csv"), "w", newline="\n") as f:
            f.write("offset_level,offset_level0,mean_ink\n")
            for o, v in zip(prof_offs, res[2]):
                f.write(f"{o / 2 ** a.level:g},{o:g},{v:.6f}\n")
    ok = surf.valid
    stats = dict(max_mean=float(np.nanmean(mx[ok])) if ok.any() else None,
                 max_frac_above_0p5=float((np.nan_to_num(mx[ok]) > 0.5).mean()) if ok.any() else None,
                 mean_mean=float(np.nanmean(mn[ok])) if ok.any() else None)
    meta = dict(tool="ink_sample", version=__version__, trace=os.path.abspath(a.trace),
                ink_zarr=a.ink_zarr if str(a.ink_zarr).startswith(("http://", "https://")) else os.path.abspath(a.ink_zarr), level=a.level, step_vox=step,
                offsets_level=[a.lo, a.hi, a.offset_step], offsets_level0=[float(offs[0]), float(offs[-1]), len(offs)],
                flip_normal=bool(a.flip_normal), norm_max=vol.norm_max, shape=list(surf.shape),
                valid_fraction=float(surf.valid.mean()), trace_offset=off, trace_scale=a.trace_scale, stats=stats,
                note="max/mean over the normal offsets of the ink volume, scaled to 0..1 by norm_max; NaN = no trace")
    with open(os.path.join(a.out, "meta.json"), "w", newline="\n") as f:
        json.dump(meta, f, indent=2)
    log(f"wrote {a.out}: ink_max.tif ink_mean.tif ink_max_thumb.png meta.json")
    if prof_offs is not None:
        meta["profile"] = [[float(o / 2 ** a.level), float(v)] for o, v in zip(prof_offs, res[2])]
        with open(os.path.join(a.out, "meta.json"), "w", newline="\n") as f:
            json.dump(meta, f, indent=2)
    return mx, mn, surf


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--trace", required=True, help="tifxyz folder (x.tif y.tif z.tif meta.json), level-0 voxels")
    ap.add_argument("--ink-zarr", required=True, help="OME-Zarr of a 3-D ink prediction (group with levels 0, 1, ...): "
                    "a local folder or an http(s) URL (only the chunks needed are fetched; nothing is stored)")
    ap.add_argument("--trace-offset", type=float, nargs=3, metavar=("DX", "DY", "DZ"),
                    help="added to the trace xyz before --trace-scale (e.g. a crop origin)")
    ap.add_argument("--window-offset", action="store_true",
                    help="take --trace-offset from meta.json 'window' (x0, y0, 0), as in testdata/pherc_paris4_groundtruth")
    ap.add_argument("--trace-scale", type=float, default=1.0,
                    help="multiplies (trace xyz + offset) to give level-0 voxels of the ink zarr (e.g. 2 for a 9.6 um "
                    "trace on a 4.8 um zarr)")
    ap.add_argument("--profile", type=float, default=None, metavar="R",
                    help="also write profile.csv: mean ink over the trace at each offset -R..R (voxels at --level)")
    ap.add_argument("--level", type=int, default=0, help="zarr level to read (level L = 2**L coarser)")
    ap.add_argument("--lo", type=float, default=-4.0, help="first normal offset, in voxels at --level")
    ap.add_argument("--hi", type=float, default=4.0, help="last normal offset, in voxels at --level")
    ap.add_argument("--offset-step", type=float, default=1.0, help="offset step, in voxels at --level")
    ap.add_argument("--step", type=float, default=None, help="output pixel spacing along the surface, level-0 voxels "
                    "(default 2**level, i.e. one output pixel per zarr voxel)")
    ap.add_argument("--flip-normal", action="store_true", help="reverse the trace normal")
    ap.add_argument("--mesh-scale", type=float, nargs=2, metavar=("SX", "SY"), help="override meta.json scale")
    ap.add_argument("--norm-max", type=float, default=None, help="value that means 1.0 (default: dtype max, 1.0 for floats)")
    ap.add_argument("--tile", type=int, default=128, help="output tile side for chunked reads")
    ap.add_argument("--thumb-max", type=int, default=512, help="long side of the PNG thumbnail")
    ap.add_argument("--out", required=True, help="output folder")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        run(a)
    except InputError as e:
        print(f"ink_sample: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
