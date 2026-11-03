#!/usr/bin/env python3
"""geometric_repair: geometric repair of tifxyz surfaces, built on tifxyz-repair (MIT, Nieuwlaar).  (MIT)

OUR code, a separate module.  The vendored upstream package ``tifxyz_repair/`` is unmodified; we use its loader
(``core.load_patch``, VC3D validity semantics) and its bbox rule (``core.compute_bbox``).  See ATTRIBUTION.md.

    python geometric_repair.py PATCH_DIR --out OUT_DIR [--max-rings 3 ...]
    python geometric_repair.py PATCH_DIR --dry-run          # report only

What it does (upstream only repairs the stale ``bbox`` field; it never touches vertices, scale or mask):
  1. INFILL  invalid vertices (the (-1,-1,-1) marker, mask 0, z<=0, non-finite) are re-estimated from their valid
             neighbours: a least-squares plane  P(dr, dc) = a + b*dr + c*dc  fitted in grid coordinates to the ORIGINAL valid
             vertices in a window, evaluated at the invalid cell.  Only cells within --max-rings grid steps of a valid
             vertex are filled, the window grows with that distance, the fit needs --min-neighbours points of rank 3, and
             is rejected if its RMS residual exceeds --max-residual-frac x the median grid spacing.  Cells that fail stay
             invalid.  Edge cells are EXTRAPOLATED, i.e. this invents surface: the infilled cells are flagged in infilled.tif
             and counted in meta.json["repair"], and --max-rings 0 turns infill off.
  2. SCALE   meta.json "scale" ([cells/voxel along columns, along rows]) is re-measured from the median spacing of
             valid neighbouring vertices; it is rewritten only if it differs from the stored one by more than
             --scale-tolerance (relative), and only with --fix-scale (otherwise it is reported).
  3. BBOX    recomputed over the valid vertices after infill (upstream rule, XYZ order).
  4. MASK    mask.tif is (re)generated: uint8, 255 = valid, 0 = invalid (VC3D reads >= 255 as valid), same shape as the grid.
Invalid vertices are normalised to (-1,-1,-1) in x/y/z.  Output goes to --out (a new directory) unless --in-place, which
keeps *.bak copies.  Exit code 0 ok, 2 bad input.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
from dataclasses import dataclass

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import tifffile  # noqa: E402
from tifxyz_repair.core import Patch, compute_bbox, load_patch  # noqa: E402  (vendored upstream, unmodified)

__version__ = "0.1.0"


@dataclass
class Params:
    max_rings: int = 3               # infill only cells within this many grid steps (Chebyshev) of a valid vertex; 0 = no infill
    fit_radius: int = 2              # fit window half-width (cells) for a cell next to the valid region; grows by 1 per extra ring
    min_neighbours: int = 6          # a fit needs at least this many valid vertices in the window (the plane has 3 unknowns per axis)
    max_residual_frac: float = 0.5   # reject a fit whose RMS residual is above this x the median grid spacing (a fold or a crease)
    fix_scale: bool = False          # rewrite meta.json scale when it disagrees with the measured spacing
    scale_tolerance: float = 0.02    # relative difference between stored and measured scale that counts as a disagreement
    mask_threshold: int = 255        # value written for valid vertices in mask.tif (VC3D keeps >= 255)


# ----------------------------------------------------------------------------------------------- validity
def valid_vertices(patch: Patch) -> np.ndarray:
    """Upstream (VC3D loader) validity, plus the FORMATS.md rule: any component == -1 or non-finite is invalid."""
    P = patch.points()
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(P).all(axis=-1) & ~(P == -1.0).any(axis=-1)
    return patch.valid & ok


def grid_spacing(P: np.ndarray, valid: np.ndarray):
    """Median Euclidean distance (voxels) between valid neighbours along columns and along rows, plus pair counts."""
    out = []
    for axis in (1, 0):
        a, b = (P[:, 1:], P[:, :-1]) if axis == 1 else (P[1:], P[:-1])
        va, vb = (valid[:, 1:], valid[:, :-1]) if axis == 1 else (valid[1:], valid[:-1])
        both = va & vb
        d = np.linalg.norm(a[both] - b[both], axis=-1)
        out.append((float(np.median(d)) if d.size else float("nan"), int(d.size)))
    return out[0], out[1]          # (columns), (rows)


# ----------------------------------------------------------------------------------------------- infill
def _chebyshev_distance(valid: np.ndarray) -> np.ndarray:
    from scipy.ndimage import distance_transform_cdt
    return distance_transform_cdt(~valid, metric="chessboard")   # 0 on valid cells, k at k steps from the nearest valid cell


def infill(P: np.ndarray, valid: np.ndarray, p: Params, spacing: float | None = None):
    """Return (P_new, valid_new, filled).  P is (H, W, 3); all inputs untouched.  Fits use only the ORIGINAL valid vertices,
    so errors do not compound from one ring to the next."""
    P2 = P.copy()
    filled = np.zeros(valid.shape, bool)
    if p.max_rings <= 0 or not valid.any():
        return P2, valid.copy(), filled
    if spacing is None or not np.isfinite(spacing):
        (sc, _), (sr, _) = grid_spacing(P, valid)
        spacing = np.nanmean([sc, sr])
    dist = _chebyshev_distance(valid)
    H, W = valid.shape
    for r, c in zip(*np.nonzero((dist >= 1) & (dist <= p.max_rings))):
        R = p.fit_radius + int(dist[r, c]) - 1
        r0, r1, c0, c1 = max(r - R, 0), min(r + R + 1, H), max(c - R, 0), min(c + R + 1, W)
        m = valid[r0:r1, c0:c1]
        if m.sum() < p.min_neighbours:
            continue
        rr, cc = np.nonzero(m)
        A = np.column_stack([np.ones(rr.size), rr + r0 - r, cc + c0 - c]).astype(np.float64)
        if np.linalg.matrix_rank(A) < 3:
            continue
        Y = P[r0:r1, c0:c1][m].astype(np.float64)
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        resid = np.sqrt(np.mean(np.sum((A @ coef - Y) ** 2, axis=1)))
        if resid > p.max_residual_frac * spacing:
            continue
        P2[r, c] = coef[0]
        filled[r, c] = True
    return P2, valid | filled, filled


# ----------------------------------------------------------------------------------------------- the repair
def repair(patch: Patch, p: Params):
    """Pure computation.  Returns (P_out (H,W,3) float32, valid_out, filled, meta_out, report)."""
    P = patch.points().astype(np.float32)
    valid = valid_vertices(patch)
    H, W = valid.shape
    (sc, nc), (sr, nr) = grid_spacing(P, valid)
    spacing = float(np.nanmean([sc, sr]))
    P2, valid2, filled = infill(P, valid, p, spacing)
    P2[~valid2] = -1.0

    meta = dict(patch.meta or {})
    stored = meta.get("scale")
    measured = [1.0 / sc if sc and np.isfinite(sc) else None, 1.0 / sr if sr and np.isfinite(sr) else None]
    scale_note = "no stored scale" if not (isinstance(stored, (list, tuple)) and len(stored) >= 2) else "stored scale agrees"
    scale_changed = False
    if measured[0] and measured[1]:
        if not (isinstance(stored, (list, tuple)) and len(stored) >= 2):
            scale_note = "stored scale missing or malformed (VC3D refuses to load such a file)"
            if p.fix_scale:
                meta["scale"] = measured
                scale_changed = True
        else:
            rel = max(abs(measured[0] - float(stored[0])) / float(stored[0]),
                      abs(measured[1] - float(stored[1])) / float(stored[1]))
            if rel > p.scale_tolerance:
                scale_note = f"stored scale differs from measured by {100 * rel:.1f}%"
                if p.fix_scale:
                    meta["scale"] = measured
                    scale_changed = True
            else:
                scale_note = f"stored scale agrees with measured (within {100 * p.scale_tolerance:.1f}%)"

    tmp = dataclasses.replace(patch, x=P2[..., 0], y=P2[..., 1], z=P2[..., 2], mask=valid2.astype(np.uint8) * 255)
    bb = compute_bbox(tmp)
    old_bb = patch.meta.get("bbox") if patch.meta else None
    if bb is not None:
        meta["bbox"] = [list(bb[0]), list(bb[1])]
    meta["repair"] = {"tool": "tifxyz_repair geometric_repair", "version": __version__,
                      "infilled_vertices": int(filled.sum()), "invalid_before": int((~valid).sum()),
                      "invalid_after": int((~valid2).sum()), "params": dataclasses.asdict(p)}
    report = {
        "shape_hw": [H, W], "vertices": H * W,
        "invalid_before": int((~valid).sum()), "invalid_after": int((~valid2).sum()),
        "invalid_fraction_before": float((~valid).mean()), "invalid_fraction_after": float((~valid2).mean()),
        "infilled": int(filled.sum()),
        "spacing_voxels": {"columns": sc, "rows": sr, "pairs": [nc, nr]},
        "scale": {"stored": stored, "measured": measured, "note": scale_note, "rewritten": scale_changed},
        "bbox": {"old": old_bb, "new": meta.get("bbox")},
        "had_mask_tif": patch.mask is not None,
    }
    return P2, valid2, filled, meta, report


def write_patch(out_dir, P, valid, filled, meta, p: Params):
    os.makedirs(out_dir, exist_ok=True)
    for i, name in enumerate("xyz"):
        tifffile.imwrite(os.path.join(out_dir, f"{name}.tif"), np.ascontiguousarray(P[..., i], dtype=np.float32))
    tifffile.imwrite(os.path.join(out_dir, "mask.tif"), np.where(valid, p.mask_threshold, 0).astype(np.uint8))
    tifffile.imwrite(os.path.join(out_dir, "infilled.tif"), (filled * 255).astype(np.uint8))
    tmp = os.path.join(out_dir, "meta.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, indent=4) + "\n")
    os.replace(tmp, os.path.join(out_dir, "meta.json"))


# ----------------------------------------------------------------------------------------------- hold-out benchmark
def holdout(P: np.ndarray, valid: np.ndarray, depth: int, p: Params):
    """Hide the `depth` outermost rings of the valid region (chessboard erosion), infill, compare with the truth.
    Returns dict with RMS / max error in voxels for ours and for the naive baseline 'copy the nearest valid vertex'."""
    from scipy.ndimage import distance_transform_cdt, distance_transform_edt
    inside = distance_transform_cdt(np.pad(valid, 1), metric="chessboard")[1:-1, 1:-1]   # 1 on the outermost valid ring; the array border counts as outside
    hidden = valid & (inside <= depth)
    keep = valid & ~hidden
    P2, v2, filled = infill(np.where(keep[..., None], P, -1.0), keep, p)
    got = filled & hidden
    # baseline: nearest kept vertex
    _, idx = distance_transform_edt(~keep, return_indices=True)
    base = P[idx[0], idx[1]]
    out = {"depth": depth, "hidden": int(hidden.sum()), "filled": int(got.sum()), "fill_rate": float(got.sum() / max(hidden.sum(), 1))}
    for name, est in (("ours", P2), ("nearest_copy", base)):
        sel = got
        d = np.linalg.norm(est[sel] - P[sel], axis=-1) if sel.any() else np.array([np.nan])
        out[name] = {"rms": float(np.sqrt(np.mean(d ** 2))), "median": float(np.median(d)), "max": float(np.max(d))}
    return out


# ----------------------------------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patch", help="tifxyz directory (x.tif y.tif z.tif meta.json [mask.tif])")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--out", help="write the repaired surface into this NEW directory")
    g.add_argument("--in-place", action="store_true", help="overwrite the input; originals kept as *.bak")
    ap.add_argument("--dry-run", action="store_true", help="compute and print the report, write nothing")
    ap.add_argument("--report", help="also write the report JSON here")
    d = Params()
    ap.add_argument("--max-rings", type=int, default=d.max_rings, help="infill cells up to this many grid steps from a valid vertex; 0 = no infill (default %(default)s)")
    ap.add_argument("--fit-radius", type=int, default=d.fit_radius, help="fit window half-width in cells (default %(default)s)")
    ap.add_argument("--min-neighbours", type=int, default=d.min_neighbours, help="valid vertices needed in the window (default %(default)s)")
    ap.add_argument("--max-residual-frac", type=float, default=d.max_residual_frac, help="reject a fit with RMS residual above this x grid spacing (default %(default)s)")
    ap.add_argument("--fix-scale", action="store_true", help="rewrite meta.json scale when it disagrees with the measured spacing")
    ap.add_argument("--scale-tolerance", type=float, default=d.scale_tolerance, help="relative scale disagreement that counts (default %(default)s)")
    ap.add_argument("--mask-threshold", type=int, default=d.mask_threshold, help="mask.tif value of valid vertices; VC3D needs >= 255 (default %(default)s)")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if not a.dry_run and not a.out and not a.in_place:
        print("error: give --out DIR, --in-place or --dry-run", file=sys.stderr)
        return 2
    if not os.path.isdir(a.patch) or not all(os.path.isfile(os.path.join(a.patch, f)) for f in ("x.tif", "y.tif", "z.tif")):
        print(f"error: {a.patch} is not a tifxyz directory", file=sys.stderr)
        return 2
    p = Params(a.max_rings, a.fit_radius, a.min_neighbours, a.max_residual_frac, a.fix_scale, a.scale_tolerance, a.mask_threshold)
    patch = load_patch(a.patch)
    if patch.read_errors:
        print(f"error: unreadable files: {patch.read_errors}", file=sys.stderr)
        return 2
    P, valid, filled, meta, rep = repair(patch, p)
    if not a.dry_run:
        if a.in_place:
            for f in ("x.tif", "y.tif", "z.tif", "meta.json", "mask.tif"):
                src = os.path.join(a.patch, f)
                if os.path.isfile(src) and not os.path.exists(src + ".bak"):
                    shutil.copy2(src, src + ".bak")
            write_patch(a.patch, P, valid, filled, meta, p)
        else:
            if os.path.exists(a.out) and os.listdir(a.out):
                print(f"error: {a.out} exists and is not empty", file=sys.stderr)
                return 2
            write_patch(a.out, P, valid, filled, meta, p)
    text = json.dumps(rep, indent=2)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
