"""Validation checks for tifxyz patches.

Each check returns zero or more findings. A finding is a dict:
``{"check": str, "severity": "error"|"warning"|"info", "message": str, **data}``.

Severity meaning:
- error:   the patch will misbehave in downstream tools (data loss, crashes)
- warning: suspicious, worth a look, may degrade results
- info:    notable but harmless
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .core import Patch, compute_bbox, parse_meta_bbox

# Findings with matching drift above this tolerance (in voxels) count as
# stale. villa issue #1272 used 1e-3; the observed real-world drift is up
# to hundreds of voxels, so the exact value is not sensitive.
BBOX_TOLERANCE = 1e-3

Finding = dict[str, Any]


def _f(check: str, severity: str, message: str, **data: Any) -> Finding:
    return {"check": check, "severity": severity, "message": message, **data}


def check_files(patch: Patch) -> list[Finding]:
    out = []
    for fname, err in patch.read_errors.items():
        out.append(_f("tif-read", "error", f"{fname} unreadable: {err}", file=fname))
    if patch.meta_error is not None:
        out.append(_f("meta-parse", "error", f"meta.json problem: {patch.meta_error}"))
    return out


def check_grid_consistency(patch: Patch) -> list[Finding]:
    out = []
    shapes = {"x.tif": patch.x.shape, "y.tif": patch.y.shape, "z.tif": patch.z.shape}
    if len(set(shapes.values())) > 1:
        out.append(
            _f(
                "grid-shape",
                "error",
                f"coordinate grids have mismatched shapes: {shapes}",
                shapes={k: list(v) for k, v in shapes.items()},
            )
        )
        return out  # downstream vertex checks assume equal shapes
    if patch.x.size == 0:
        if not patch.read_errors:
            out.append(_f("grid-empty", "error", "coordinate grids are empty"))
        return out
    for name, arr in (("x.tif", patch.x), ("y.tif", patch.y), ("z.tif", patch.z)):
        if arr.dtype != np.float32:
            out.append(
                _f(
                    "grid-dtype",
                    "warning",
                    f"{name} dtype is {arr.dtype}, expected float32 (VC3D writes float32)",
                    file=name,
                    dtype=str(arr.dtype),
                )
            )
    if patch.mask is not None and patch.mask.shape != patch.x.shape:
        out.append(
            _f(
                "mask-shape",
                "warning",
                f"mask.tif shape {patch.mask.shape} != grid shape {patch.x.shape}",
            )
        )
    return out


def check_vertices(patch: Patch) -> list[Finding]:
    if patch.x.size == 0 or patch.x.shape != patch.y.shape or patch.x.shape != patch.z.shape:
        return []
    out = []
    valid = patch.valid
    n = valid.size
    n_valid = int(valid.sum())
    if n_valid == 0:
        out.append(
            _f(
                "no-valid-vertices",
                "error",
                "patch has no valid vertices under the loader's rules "
                "(x == -1, z <= 0, or masked out)",
            )
        )
        return out

    pts = patch.points()
    nonfinite = ~np.isfinite(pts).all(axis=-1) & valid
    n_nan = int(nonfinite.sum())
    if n_nan:
        out.append(
            _f(
                "nan-vertices",
                "warning",
                f"{n_nan} valid-flagged vertices contain NaN/Inf coordinates",
                count=n_nan,
            )
        )

    # Inconsistent sentinel: y == -1 on a vertex the loader still considers
    # valid (x != -1, z > 0, mask retained). z == -1 needs no check since
    # the loader's z<=0 rule already invalidates it, but a lone y sentinel
    # survives into meshes and bboxes as a coordinate on the -1 plane.
    partial = valid & (patch.y == -1)
    n_partial = int(partial.sum())
    if n_partial:
        out.append(
            _f(
                "partial-sentinel",
                "warning",
                f"{n_partial} vertices have y == -1 but remain valid under the "
                f"loader's rules (x != -1, z > 0, mask retained), so likely corrupt",
                count=n_partial,
            )
        )

    out.append(
        _f(
            "valid-fraction",
            "info",
            f"{n_valid}/{n} vertices valid ({n_valid / n:.1%})",
            valid=n_valid,
            total=n,
        )
    )
    return out


def check_meta_fields(patch: Patch) -> list[Finding]:
    if patch.meta is None:
        return []
    out = []
    meta = patch.meta
    fmt = meta.get("format")
    if fmt != "tifxyz":
        out.append(_f("meta-format", "warning", f'format is {fmt!r}, expected "tifxyz"'))
    scale = meta.get("scale")
    if (
        not isinstance(scale, (list, tuple))
        or len(scale) != 2
        or not all(isinstance(s, (int, float)) and s > 0 for s in scale)
    ):
        out.append(
            _f(
                "meta-scale",
                "error",
                f"scale is {scale!r}, expected two positive numbers "
                f"(downstream area/size math divides by it)",
                scale=scale,
            )
        )
    # The #1226 failure family: zero/negative physical sizes silently
    # nullify area computations and discard segments downstream.
    for key in ("voxelsize", "voxelsize_um", "voxel_size"):
        if key in meta:
            v = meta[key]
            if not isinstance(v, (int, float)) or v <= 0:
                out.append(
                    _f(
                        "meta-voxelsize",
                        "error",
                        f"{key} is {v!r}. A zero or invalid voxel size silently discards "
                        f"segments downstream (villa #1226 failure class)",
                        key=key,
                        value=v,
                    )
                )
    return out


def check_bbox(patch: Patch) -> list[Finding]:
    """The villa #1272 check: recompute the bbox from the coordinate grids
    and diff it against meta.json."""
    if (
        patch.meta is None
        or patch.x.size == 0
        or patch.x.shape != patch.y.shape
        or patch.x.shape != patch.z.shape
    ):
        return []
    out = []
    stored = parse_meta_bbox(patch.meta)
    if stored is None:
        if "bbox" in patch.meta:
            out.append(_f("bbox-malformed", "error", f"bbox field is malformed: {patch.meta['bbox']!r}"))
        else:
            # Legitimate: vc_tifxyz_trim erases bbox; VC3D recomputes lazily.
            out.append(_f("bbox-missing", "info", "meta.json has no bbox (recomputed lazily by VC3D)"))
        return out

    true = compute_bbox(patch)
    if true is None:
        return out  # no-valid-vertices already reported
    t_low, t_high = true
    s_low, s_high = stored
    drift = [abs(a - b) for a, b in zip(t_low + t_high, s_low + s_high)]
    max_drift = max(drift)
    if max_drift > BBOX_TOLERANCE:
        # How many valid vertices lie outside the stored box? This is the
        # fraction that bbox-based filters (e.g. bbox_intersects_z) can
        # silently drop or misattribute.
        valid = patch.valid
        pts = patch.points()[valid]
        finite = np.isfinite(pts).all(axis=-1)
        pts = pts[finite]
        lo = np.array(s_low, dtype=np.float64)
        hi = np.array(s_high, dtype=np.float64)
        outside = ((pts < lo - BBOX_TOLERANCE) | (pts > hi + BBOX_TOLERANCE)).any(axis=-1)
        frac = float(outside.mean()) if pts.size else 0.0
        out.append(
            _f(
                "bbox-stale",
                "error",
                f"stored bbox is stale: max drift {max_drift:.1f} voxels, "
                f"{frac:.1%} of valid vertices outside the stored box (villa #1272)",
                max_drift=max_drift,
                per_axis_drift=drift,
                stored=[s_low, s_high],
                recomputed=[t_low, t_high],
                frac_outside=frac,
            )
        )
    return out


ALL_CHECKS = [check_files, check_grid_consistency, check_vertices, check_meta_fields, check_bbox]


def validate_patch(patch: Patch) -> list[Finding]:
    findings: list[Finding] = []
    for chk in ALL_CHECKS:
        findings.extend(chk(patch))
    return findings


def worst_severity(findings: list[Finding]) -> str:
    sevs = {f["severity"] for f in findings}
    for s in ("error", "warning", "info"):
        if s in sevs:
            return s
    return "ok"
