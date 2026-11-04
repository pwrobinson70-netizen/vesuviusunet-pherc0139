"""Deep geometry inspection for tifxyz patches (optional, needs scipy).

These checks target the mesh-defect families named in the Vesuvius
Challenge 2026 Open Problems post ("mergers, holes, sheet switches"):

- interior holes: invalid regions fully enclosed by valid cells
- grid-spacing distortion: adjacent-vertex distances vs the expected
  1/scale voxels (stretch or compression concentrations)
- self-proximity: vertex pairs far apart in grid (UV) space but close in
  3D, the signature of a sheet switch or a merger folding a mesh
  onto a neighboring wrap
- normal flips: adjacent quads whose normals point in opposite directions

All metrics are conservative *detectors*: they flag places a human (or a
downstream repair tool) should look at, they do not modify anything.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from .core import Patch


def _expected_spacing(patch: Patch) -> Optional[float]:
    meta = patch.meta or {}
    scale = meta.get("scale")
    try:
        s = float(scale[0])
        if s > 0:
            return 1.0 / s
    except (TypeError, ValueError, IndexError):
        pass
    return None


def inspect_patch(
    patch: Patch, *, proximity_factor: float = 0.5, uv_min_dist: int = 10, collect_cells: bool = False
) -> dict[str, Any]:
    """Compute deep geometry metrics. Returns a JSON-serializable dict.

    With ``collect_cells=True`` the result additionally carries a
    ``defect_cells`` key: ``{defect_type: [[row, col], ...]}`` grid cells
    pinpointing each finding (used by the VC3D pointset export below).
    """
    from scipy import ndimage
    from scipy.spatial import cKDTree

    if patch.x.size == 0:
        return {"error": "empty grid"}

    P = patch.points().astype(np.float64)
    V = patch.valid & np.isfinite(P).all(axis=-1)
    H, W = V.shape
    result: dict[str, Any] = {"grid": [H, W], "valid_fraction": float(V.mean())}
    defect_cells: dict[str, np.ndarray] = {}

    if not V.any():
        result["error"] = "no valid vertices"
        return result

    # --- interior holes -------------------------------------------------
    inv = ~V
    lbl, n = ndimage.label(inv)
    border = np.zeros_like(inv)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    border_labels = set(np.unique(lbl[border & inv]).tolist())
    hole_ids = [i for i in range(1, n + 1) if i not in border_labels]
    hole_sizes = ndimage.sum_labels(inv, lbl, hole_ids).astype(int).tolist() if hole_ids else []
    result["holes"] = {"count": len(hole_ids), "cells": int(sum(hole_sizes)), "largest": max(hole_sizes, default=0)}
    if collect_cells:
        # Hole cells themselves have no 3D position; export the valid
        # cells ringing each interior hole instead.
        hole_mask = np.isin(lbl, hole_ids)
        defect_cells["hole_boundary"] = np.argwhere(ndimage.binary_dilation(hole_mask) & V)

    # --- spacing distortion --------------------------------------------
    du = np.linalg.norm(np.diff(P, axis=1), axis=2)
    dv = np.linalg.norm(np.diff(P, axis=0), axis=2)
    mu = V[:, 1:] & V[:, :-1]
    mv = V[1:, :] & V[:-1, :]
    edges = np.concatenate([du[mu], dv[mv]])
    spacing: dict[str, Any] = {}
    if edges.size:
        spacing["median"] = float(np.median(edges))
        spacing["p01"] = float(np.percentile(edges, 1))
        spacing["p99"] = float(np.percentile(edges, 99))
        expected = _expected_spacing(patch)
        if expected:
            spacing["expected"] = expected
            spacing["stretch_frac"] = float((edges > 1.5 * expected).mean())
            spacing["compress_frac"] = float((edges < 0.5 * expected).mean())
            if collect_cells:
                # Cells touching an edge over the stretch threshold, worst
                # (longest edge) first, deduplicated.
                su = mu & (du > 1.5 * expected)
                sv = mv & (dv > 1.5 * expected)
                ru, cu = np.nonzero(su)
                rv, cv = np.nonzero(sv)
                cells = np.concatenate([
                    np.stack([ru, cu], axis=1), np.stack([ru, cu + 1], axis=1),
                    np.stack([rv, cv], axis=1), np.stack([rv + 1, cv], axis=1),
                ])
                lengths = np.concatenate([du[su], du[su], dv[sv], dv[sv]])
                if cells.size:
                    order = np.argsort(-lengths)
                    cells, lengths = cells[order], lengths[order]
                    _, first = np.unique(cells, axis=0, return_index=True)
                    cells = cells[first[np.argsort(-lengths[first])]]
                defect_cells["stretch"] = cells
    result["spacing"] = spacing

    # --- self-proximity (sheet-switch / merger suspects) ----------------
    expected = _expected_spacing(patch) or (spacing.get("median") or 1.0)
    idx = np.argwhere(V)
    pts = P[V]
    # Subsample very large grids to keep the KD-tree pass fast.
    max_pts = 400_000
    if pts.shape[0] > max_pts:
        stride = int(np.ceil(pts.shape[0] / max_pts))
        pts, idx = pts[::stride], idx[::stride]
    tree = cKDTree(pts)
    pairs = tree.query_pairs(r=expected * proximity_factor, output_type="ndarray")
    if pairs.size:
        uv_dist = np.abs(idx[pairs[:, 0]] - idx[pairs[:, 1]]).max(axis=1)
        suspects = pairs[uv_dist > uv_min_dist]
    else:
        suspects = np.empty((0, 2), dtype=int)
    sus_cells = np.unique(idx[suspects.ravel()], axis=0) if suspects.size else np.empty((0, 2), dtype=int)
    result["self_proximity"] = {
        "pairs": int(len(suspects)),
        "cells": int(len(sus_cells)),
        "radius_voxels": float(expected * proximity_factor),
        "note": "grid-distant vertex pairs closer than radius in 3D (sheet-switch/merger suspects)",
    }
    if collect_cells:
        defect_cells["self_proximity"] = sus_cells

    # --- normal flips ---------------------------------------------------
    dpu = np.gradient(P, axis=1)
    dpv = np.gradient(P, axis=0)
    nrm = np.cross(dpv, dpu)
    length = np.linalg.norm(nrm, axis=2, keepdims=True)
    length[length == 0] = 1.0
    nrm /= length
    dot_u = (nrm[:, 1:] * nrm[:, :-1]).sum(axis=2)[mu]
    dot_v = (nrm[1:, :] * nrm[:-1, :]).sum(axis=2)[mv]
    dots = np.concatenate([dot_u, dot_v])
    if dots.size:
        result["normals"] = {
            "median_adjacent_dot": float(np.median(dots)),
            "flip_fraction": float((dots < 0).mean()),
        }

    if collect_cells:
        result["defect_cells"] = {k: np.asarray(v).tolist() for k, v in defect_cells.items()}

    return result


# --- VC3D point-collection export --------------------------------------
#
# Target schema: the point-collection JSON that VC3D and vc_calc_surface_metrics
# load via PointCollections::loadFromJSON. Source of truth is C++, in
# villa/volume-cartographer (all line numbers refer to that repo):
#
#   {
#     "vc_pointcollections_json_version": "1",   # REQUIRED; must be the
#                                                #   *string* "1", loadFromJSON
#                                                #   calls get_string() and
#                                                #   rejects the file otherwise
#                                                #   (core/src/PointCollections.cpp:590)
#     "collections": {                           # REQUIRED object; keys are
#                                                #   stringified uint64 ids,
#                                                #   parsed with stoull
#                                                #   (PointCollections.cpp:598-604)
#       "<collection-id>": {
#         "name": "...",                         # REQUIRED (PointCollections.cpp:147)
#         "points": {                            # REQUIRED (PointCollections.cpp:149);
#           "<point-id>": {                      #   keys are stringified uint64 ids
#                                                #   (PointCollections.cpp:152); keep them
#                                                #   unique across ALL collections, the
#                                                #   loader rebuilds a flat id->point map
#                                                #   (PointCollections.cpp:633-639)
#             "p": [x, y, z],                    # REQUIRED (PointCollections.cpp:59);
#                                                #   3 floats, world coordinates in
#                                                #   volume voxels, (x, y, z) order:
#                                                #   index 0/1/2 -> Vec3f x/y/z
#                                                #   (PointCollections.cpp:20-22), and
#                                                #   the tifxyz x/y/z.tif grids load
#                                                #   into channels 0/1/2
#                                                #   (core/src/QuadSurface.cpp:2333-2335);
#                                                #   vc_calc_surface_metrics z-filters
#                                                #   on p[2] (core/src/surface_metrics.cpp:132)
#             "wind_a": null,                    # optional winding annotation; float or
#                                                #   null; missing/null -> NaN = "none"
#                                                #   (PointCollections.cpp:60-64)
#             "creation_time": <int>             # optional; ms since epoch; missing -> 0
#                                                #   (PointCollections.cpp:65-69)
#           }, ...                               # optional per point: "links" (array of
#                                                #   point ids) and "fiber_dir" ("h"/"v")
#                                                #   (PointCollections.cpp:71-85)
#         },
#         "metadata": {                          # REQUIRED object (PointCollections.cpp:160)
#           "winding_is_absolute": false         # optional bool, default true when absent
#                                                #   (PointCollections.cpp:94-100); we write
#                                                #   false since our wind_a are all null -
#                                                #   these are defect markers, not absolute
#                                                #   winding-number annotations
#         },
#         "color": [r, g, b]                     # REQUIRED (PointCollections.cpp:161);
#                                                #   3 floats in 0..1 (VC3D multiplies by
#                                                #   255 for display,
#                                                #   apps/VC3D/CPointCollectionWidget.cpp:288)
#       }, ...                                   # optional per collection: "anchor2d",
#                                                #   "autoFillMode"/"autoFillConstant",
#                                                #   "tags", "windings_linked"
#                                                #   (PointCollections.cpp:163-196)
#     }
#   }                                            # any extra top-level keys are preserved
#                                                #   as opaque file metadata
#                                                #   (PointCollections.cpp:594-596)
#
# defect type -> (collection-name label, display color)
_DEFECT_STYLES = {
    "self_proximity": ("switch", (1.0, 0.0, 0.0)),
    "hole_boundary": ("hole", (1.0, 0.55, 0.0)),
    "stretch": ("stretch", (1.0, 1.0, 0.0)),
}


def defect_points(patch: Patch, metrics: dict[str, Any]) -> dict[str, list[list[float]]]:
    """Map ``defect_cells`` grid cells (from ``inspect_patch(...,
    collect_cells=True)``) to 3D ``[x, y, z]`` points in volume voxels."""
    P = patch.points().astype(np.float64)
    out: dict[str, list[list[float]]] = {}
    for key, cells in (metrics.get("defect_cells") or {}).items():
        cells = np.asarray(cells, dtype=int)
        if cells.size:
            out[key] = [[float(v) for v in P[r, c]] for r, c in cells]
    return out


def build_pointset(
    items: Iterable[tuple[str, dict[str, list[list[float]]]]], *, max_points: int = 2000
) -> dict[str, Any]:
    """Assemble a VC3D point-collection dict (schema above) from
    ``(patch_name, defect_points(...))`` pairs. One collection per defect
    type per patch, named ``defect_<type>_<patch_name>``; collections over
    ``max_points`` are thinned (stretch cells arrive worst-first, so
    truncation keeps the worst; the others are subsampled evenly)."""
    now_ms = int(time.time() * 1000)
    collections: dict[str, Any] = {}
    col_id = pt_id = 1
    for patch_name, points_by_type in items:
        for key, (label, color) in _DEFECT_STYLES.items():
            pts = points_by_type.get(key) or []
            if not pts:
                continue
            if len(pts) > max_points:
                if key == "stretch":
                    pts = pts[:max_points]
                else:
                    pts = pts[:: int(np.ceil(len(pts) / max_points))]
            points_obj = {}
            for p in pts:
                points_obj[str(pt_id)] = {"p": p, "wind_a": None, "creation_time": now_ms}
                pt_id += 1
            collections[str(col_id)] = {
                "name": f"defect_{label}_{patch_name}",
                "points": points_obj,
                "metadata": {"winding_is_absolute": False},
                "color": list(color),
            }
            col_id += 1
    return {"vc_pointcollections_json_version": "1", "collections": collections}


def export_pointset(
    items: Iterable[tuple[str, dict[str, list[list[float]]]]], out_json: Path, *, max_points: int = 2000
) -> dict[str, Any]:
    """Write the point-collection JSON to ``out_json``; returns the dict."""
    data = build_pointset(items, max_points=max_points)
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
    return data


def render_defect_map(patch: Patch, metrics: dict[str, Any], out_png: Path) -> None:
    """Write a quick-look PNG: validity, spacing distortion, and z-height."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    P = patch.points().astype(np.float64)
    V = patch.valid & np.isfinite(P).all(axis=-1)
    du = np.linalg.norm(np.diff(P, axis=1), axis=2)
    spacing_img = np.full(V.shape, np.nan)
    spacing_img[:, 1:] = np.where(V[:, 1:] & V[:, :-1], du, np.nan)
    z_img = np.where(V, P[..., 2], np.nan)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    axes[0].imshow(V, cmap="gray", interpolation="nearest")
    axes[0].set_title(f"validity ({metrics.get('valid_fraction', 0):.1%} valid, "
                      f"{metrics.get('holes', {}).get('count', 0)} interior holes)")
    im1 = axes[1].imshow(spacing_img, cmap="magma", interpolation="nearest")
    axes[1].set_title("adjacent-vertex spacing (voxels)")
    fig.colorbar(im1, ax=axes[1], fraction=0.046)
    im2 = axes[2].imshow(z_img, cmap="viridis", interpolation="nearest")
    axes[2].set_title("z height (voxels)")
    fig.colorbar(im2, ax=axes[2], fraction=0.046)
    for ax in axes:
        ax.set_xlabel("grid col")
        ax.set_ylabel("grid row")
    fig.suptitle(str(patch.path.name))
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
