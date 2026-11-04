"""vun-densify: bilinear densification of a tifxyz grid.  (MIT)

    vun-densify SRC.tifxyz OUT.tifxyz [--spacing 1.0]

A tifxyz patch stores x, y, z on a grid whose cell spacing is 1/scale voxels (meta.json "scale", e.g. 0.05 = one cell per 20 voxels).
The verified PHerc. Paris 4 patches are that coarse. The checking tools sample a trace once per grid cell, so a coarse grid gives them
18-21 cut-line points per height. This tool resamples the grid to a finer cell spacing (default 1 voxel):

* x, y, z are interpolated bilinearly between the four corner cells of the coarse cell that holds each new node;
* it NEVER interpolates across invalid cells: a new node is valid only if every coarse corner that has a non-zero weight at that node is valid
  (so the hole boundaries stay where they were, and no node bridges a gap);
* the factor per axis is an integer (round((1/scale)/spacing)); it is never below 1, so the tool never makes a grid coarser;
* the output has (H-1)*fy+1 x (W-1)*fx+1 nodes (every coarse node is kept exactly), x/y/z float32 with -1 in invalid nodes, mask.tif 255/0,
  meta.json with "scale" multiplied by the factor and a "densify_note" recording what was done.

Interpolation is geometry-preserving only up to the curvature of the surface between coarse nodes (a chord of a circle of radius R over a span
s is off by s^2/(8R) voxels); it adds no information. Exit code 0 on success, 2 on bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

__version__ = "0.1.0"


def _axis_weights(n_coarse, f):
    """New-node positions along one axis -> (i0, i1, w1, w0) with node k = i0 + w1 in coarse units (i1 = i0 + 1, clipped)."""
    n_new = (n_coarse - 1) * f + 1
    k = np.arange(n_new)
    i0 = np.minimum(k // f, n_coarse - 2) if n_coarse > 1 else np.zeros(n_new, int)
    w1 = (k - i0 * f) / float(f) if n_coarse > 1 else np.zeros(n_new)
    i1 = np.minimum(i0 + 1, n_coarse - 1)
    return i0, i1, w1, 1.0 - w1


def densify_arrays(x, y, z, valid, fy, fx):
    """Bilinear densification of (H, W) grids by integer factors (fy rows, fx columns).

    Returns (x2, y2, z2, valid2); invalid nodes are NaN. A node is valid only if all coarse corners with non-zero weight are valid.
    """
    x, y, z = (np.asarray(a, float) for a in (x, y, z))
    valid = np.asarray(valid, bool) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    H, W = valid.shape
    if H < 2 or W < 2:
        raise ValueError("need a grid of at least 2 x 2 cells")
    if int(fy) < 1 or int(fx) < 1:
        raise ValueError("factors must be integers >= 1")
    ri0, ri1, rw1, rw0 = _axis_weights(H, int(fy))
    ci0, ci1, cw1, cw0 = _axis_weights(W, int(fx))
    out_valid = np.ones((len(ri0), len(ci0)), bool)
    outs = [np.zeros((len(ri0), len(ci0))) for _ in range(3)]
    for (ri, rw) in ((ri0, rw0), (ri1, rw1)):
        for (ci, cw) in ((ci0, cw0), (ci1, cw1)):
            w = rw[:, None] * cw[None, :]
            used = w > 1e-12
            cv = valid[ri][:, ci]
            out_valid &= (cv | ~used)
            for o, g in zip(outs, (x, y, z)):
                o += np.where(used, w * np.where(cv, g[ri][:, ci], 0.0), 0.0)
    for o in outs:
        o[~out_valid] = np.nan
    return outs[0], outs[1], outs[2], out_valid


def factors_for(scale, spacing):
    """Integer factors (fy, fx) so that the new cell spacing is <= `spacing` voxels (cell spacing = 1/scale voxels; scale = (sx, sy))."""
    sx, sy = float(scale[0]), float(scale[1])
    if not (sx > 0 and sy > 0 and spacing > 0):
        raise ValueError("scale and spacing must be > 0")
    return max(1, int(round((1.0 / sy) / spacing))), max(1, int(round((1.0 / sx) / spacing)))


def densify_dir(src, dst, spacing=1.0, note_extra=None):
    """Densify the tifxyz folder `src` into `dst` (created). Returns the densify_note dict."""
    import tifffile
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(os.path.dirname(here), "tools", "sheet_spacing_check"), os.path.join(here, "_tools", "sheet_spacing_check")):
        if os.path.isdir(c) and c not in sys.path:
            sys.path.insert(0, c)
    from ssc_io import load_mesh
    m = load_mesh(src, -1.0, False)
    with open(os.path.join(src, "meta.json")) as fh:
        meta = json.load(fh)
    sc = meta.get("scale")
    if not (isinstance(sc, (list, tuple)) and len(sc) >= 2 and all(isinstance(s, (int, float)) and s > 0 for s in sc[:2])):
        raise ValueError(f"{src}: meta.json has no usable 'scale'")
    fy, fx = factors_for(sc, spacing)
    x2, y2, z2, v2 = densify_arrays(m.x, m.y, m.z, m.valid, fy, fx)
    os.makedirs(dst, exist_ok=True)
    for a, g in zip("xyz", (x2, y2, z2)):
        tifffile.imwrite(os.path.join(dst, f"{a}.tif"), np.where(v2, g, -1.0).astype(np.float32), compression="zlib")
    tifffile.imwrite(os.path.join(dst, "mask.tif"), (v2 * 255).astype(np.uint8), compression="zlib")
    note = dict(tool="vun-densify", version=__version__, method="bilinear, never across invalid cells",
                source_scale=[float(sc[0]), float(sc[1])], target_spacing_vox=float(spacing), factor_rows=fy, factor_cols=fx,
                source_shape_hw=[int(m.shape[0]), int(m.shape[1])], shape_hw=[int(v2.shape[0]), int(v2.shape[1])],
                valid_nodes=int(v2.sum()), source_valid_nodes=int(m.valid.sum()))
    if note_extra:
        note.update(note_extra)
    meta = dict(meta)
    meta["scale"] = [float(sc[0]) * fx, float(sc[1]) * fy]
    meta["densify_note"] = note
    with open(os.path.join(dst, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    return note


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", help="input tifxyz folder")
    ap.add_argument("dst", help="output tifxyz folder (created)")
    ap.add_argument("--spacing", type=float, default=1.0, help="target cell spacing in voxels (default 1)")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.src) or a.spacing <= 0:
        print("error: SRC must be a tifxyz folder and --spacing > 0", file=sys.stderr)
        return 2
    if os.path.abspath(a.src) == os.path.abspath(a.dst):
        print("error: refusing to overwrite the input", file=sys.stderr)
        return 2
    try:
        note = densify_dir(a.src, a.dst, a.spacing)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
