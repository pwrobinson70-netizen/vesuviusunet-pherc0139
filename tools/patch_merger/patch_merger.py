#!/usr/bin/env python3
"""patch_merger: merge tifxyz patches of one volume, but only where the overlap passes a same-sheet gate.  (MIT)

    python patch_merger.py PATCH [PATCH ...] --out-dir DIR [--zarr VOL.zarr | --npy VOL.npy] [--umbilicus FILE]
                           [--pitch-vox P] [--scale S]

PATCH is a tifxyz directory, or a directory of them (e.g. winding_sweep's patches/). Method, in order:

1. CUTS.  A patch that switches sheet is cut where it switches: a grid line along which most neighbour steps are
   longer than --max-edge-stretch x the median step, and (with a centre line) a radius jump found by
   trace_auditor's winding-jump detector. --cut-margin cells either side of a cut are dropped. What is left is split
   into SEGMENTS (4-connected pieces); a segment is the unit that is merged or refused.
2. OVERLAPS.  For every pair of segments of different patches whose bounding boxes (grown by --candidate-pitch x
   pitch) meet: candidate points are those within --candidate-pitch x pitch of the other segment (not counting points
   whose nearest neighbour is within --edge-cells cells of the other segment's border: that is the same sheet running
   on past the edge, not an overlap). Candidates are grouped into connected clusters on the grid; a cluster is SAME
   when at least --min-same-fraction of its points are within --overlap-pitch x pitch of the other segment.
3. THE GATE (trace_auditor's pair logic).  An overlap is accepted only if ALL hold:
   shared sheet: SAME clusters hold at least --min-overlap-points points and no cluster is mixed;
   on-sheet: >= --on-sheet-fraction of the overlap points of BOTH segments sit on a CT intensity peak along the
             surface normal (|offset| <= --on-sheet-pitch x pitch); needs a volume;
   winding:  at --winding-heights heights the overlap of B lies within --winding-tol pitches of A's sheet at the
             same angle about the centre line (whole-sheet offset 0); needs a centre line;
   charts:   an affine map of B's grid into A's grid can be fitted to the overlap (residual <= --max-register-residual cells).
   A check that cannot be run is NOT JUDGED and refuses the overlap unless --allow-unjudged.
4. MERGE.  Accepted overlaps join segments into connected components. Each component is resampled onto one regular
   grid with spacing 1/--scale voxels (default: the finest input scale): every node takes the distance-weighted mean
   of the member surfaces that cover it (weight = grid distance to the member's own border). Nodes covered by no
   member are invalid (-1,-1,-1); holes narrower than --max-gap-pitch x pitch inside a component's footprint are
   bridged, wider ones never. Segments that no accepted overlap anchors, cut off from an anchored part of the same
   patch (the far side of a switch), are dropped and reported.
5. REPORT.  seam_report.json / seam_report.txt list every overlap and every cut with the reason; overlay.png.

Every threshold is a flag (--help). Deterministic. CPU only. Exit code: 0 done, 2 bad input.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import sys
import uuid as _uuid
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy import ndimage as ndi
from scipy.ndimage import gaussian_filter1d, map_coordinates
from scipy.spatial import cKDTree

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _d in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor"):
    _p = os.path.join(_TOOLS, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import sheet_spacing_check as ssc  # noqa: E402
import sheet_switch_finder as ssf  # noqa: E402
import trace_auditor as ta  # noqa: E402
import uf_io  # noqa: E402
from ssc_io import ArrayVolume, InputError, Mesh, ZarrVolume, load_mesh  # noqa: E402

__version__ = "0.1.0"
ACCEPTED, REFUSED = "accepted", "refused"
PASS, FAIL, NJ = "PASS", "FAIL", "NOT JUDGED"
MISMATCH = "shared-sheet mismatch"


def _h(text):
    return dict(metadata={"help": text})


@dataclass
class Params:
    # --- pitch
    pitch_vox: float | None = field(default=None, **_h("CT sheet pitch in voxels; default: measured per patch from the volume"))
    n_pitch_heights: int = field(default=3, **_h("heights per patch at which the pitch is measured (median)"))
    # --- cuts
    max_edge_stretch: float = field(default=2.5, **_h("a neighbour step longer than this x the median step is a break"))
    cut_fraction: float = field(default=0.5, **_h("a grid line is a cut if this fraction of its neighbour steps are breaks"))
    cut_margin: int = field(default=3, **_h("grid cells dropped on each side of a cut (>= 1; covers a ramp switch)"))
    min_segment_points: int = field(default=20, **_h("segments with fewer valid points are dropped"))
    # --- overlap
    overlap_pitch: float = field(default=0.5, **_h("same sheet = nearest point of the other segment closer than this x pitch"))
    candidate_pitch: float = field(default=1.5, **_h("points within this x pitch of the other segment are overlap candidates (finds adjacent sheets)"))
    edge_cells: float = field(default=2.0, **_h("candidates whose nearest neighbour is within this many cells of the other segment's border are ignored"))
    min_overlap_points: int = field(default=20, **_h("least candidate points (both sides) for an overlap to be judged at all"))
    min_same_fraction: float = field(default=0.8, **_h("a cluster is SAME if this fraction of its points is within --overlap-pitch"))
    # --- gate: on-sheet
    on_sheet_pitch: float = field(default=0.25, **_h("on-sheet: CT peak along the normal within this x pitch of the point"))
    on_sheet_halfwidth_pitch: float = field(default=0.6, **_h("... profile half length, x pitch"))
    on_sheet_contrast: float = field(default=0.25, **_h("... peak must exceed the profile median by this fraction of the sampled intensity range (p0.5..p99.5)"))
    on_sheet_fraction: float = field(default=0.8, **_h("fraction of overlap points that must be on-sheet, for each segment"))
    max_check_points: int = field(default=1500, **_h("at most this many overlap points per segment are sampled in the CT"))
    # --- gate: winding
    winding_heights: int = field(default=3, **_h("heights at which the winding offset is checked"))
    winding_tol: float = field(default=0.5, **_h("winding: B within this x pitch of A's sheet at the same angle (whole-sheet offset 0)"))
    winding_fraction: float = field(default=0.8, **_h("fraction of B overlap points that must pass the winding check"))
    allow_unjudged: bool = field(default=False, **_h("do not refuse an overlap because the volume or centre line is missing (NOT JUDGED checks pass)"))
    max_register_residual: float = field(default=1.0, **_h("median chart-registration residual allowed, grid cells"))
    # --- output
    scale: float | None = field(default=None, **_h("output grid cells per voxel (tifxyz meta scale); default: the finest input scale"))
    max_gap_pitch: float = field(default=0.5, **_h("holes inside a component's footprint up to this x pitch wide are bridged; wider never (0 = never)"))
    max_grid_cells: int = field(default=25_000_000, **_h("refuse to build an output grid larger than this"))
    voxel_um: float | None = field(default=None, **_h("voxel size (um); only used to add area_cm2 to meta.json"))


# ------------------------------------------------------------------------------------- grid helpers
def _fd(P, axis):
    """Finite-difference tangent of a (H, W, 3) NaN-padded grid along axis 0/1: central where both
    neighbours exist, else one-sided; NaN where the cell is isolated."""
    P = np.moveaxis(P, axis, 0)
    fwd = np.full_like(P, np.nan)
    fwd[:-1] = P[1:] - P[:-1]
    bwd = np.full_like(P, np.nan)
    bwd[1:] = P[1:] - P[:-1]
    ok_f, ok_b = np.isfinite(fwd).all(-1), np.isfinite(bwd).all(-1)
    out = np.where((ok_f & ok_b)[..., None], 0.5 * (fwd + bwd), np.where(ok_f[..., None], fwd, bwd))
    return np.moveaxis(out, 0, axis)


def _mesh_from_P(name, P, valid, scale=None):
    return Mesh(name, P[..., 0].copy(), P[..., 1].copy(), P[..., 2].copy(), valid.copy(), scale=scale)


def area_vx2(xyz):
    """Area of a (H, W, 3) grid with NaN or -1 at invalid points: two triangles per fully valid quad."""
    xyz = np.asarray(xyz, np.float64)
    ok = np.isfinite(xyz).all(-1) & ~(xyz == -1).any(-1)
    q = ok[:-1, :-1] & ok[1:, :-1] & ok[:-1, 1:] & ok[1:, 1:]
    a, b, c, d = xyz[:-1, :-1], xyz[1:, :-1], xyz[:-1, 1:], xyz[1:, 1:]
    with np.errstate(all="ignore"):
        ar = 0.5 * (np.linalg.norm(np.cross(b - a, c - a), axis=-1) + np.linalg.norm(np.cross(d - b, d - c), axis=-1))
    return float(ar[q].sum())


# ------------------------------------------------------------------------------------- patches and segments
@dataclass
class Patch:
    name: str
    path: str
    P: np.ndarray                  # (H, W, 3) NaN where invalid
    valid: np.ndarray
    scale: tuple                   # (sx, sy) cells per voxel
    pitch: float | None = None
    cuts: list = field(default_factory=list)
    notes: list = field(default_factory=list)


class Seg:
    """A connected, cut-free piece of a patch: the unit that is merged or refused."""

    def __init__(self, patch, pi, k, mask):
        self.patch, self.pi, self.k, self.mask = patch, pi, k, mask
        self.name = f"{patch.name}#{k}" if k is not None else patch.name
        self.P = np.where(mask[..., None], patch.P, np.nan)
        self.rc = np.argwhere(mask)                       # (n, 2) grid rows, cols of the valid cells
        self.pts = self.P[mask]                           # (n, 3)
        self.n = len(self.pts)
        self.pitch = patch.pitch
        self.edt = ndi.distance_transform_edt(np.pad(mask, 1))[1:-1, 1:-1]     # cells from the border / holes
        self._tree = None
        self._tan = None
        self.status, self.reason = "kept", ""

    @property
    def tree(self):
        if self._tree is None:
            self._tree = cKDTree(self.pts)
        return self._tree

    def tangents(self):
        if self._tan is None:
            self._tan = (_fd(self.P, 0), _fd(self.P, 1))
        return self._tan

    def normals(self):
        tr, tc = self.tangents()
        n = np.cross(tr, tc)
        with np.errstate(all="ignore"):
            n = n / np.linalg.norm(n, axis=-1, keepdims=True)
        return n[self.mask]

    def bbox(self):
        return self.pts.min(0), self.pts.max(0)


def load_patches(paths, invalid_value=-1.0):
    """Expand directories-of-patches, load, return list[Patch] in a stable order (sorted by name)."""
    dirs = []
    for p in paths:
        p = str(p)
        if not os.path.isdir(p):
            raise InputError(f"patch path is not a directory: {p}")
        if os.path.isfile(os.path.join(p, "x.tif")):
            dirs.append(p)
        else:
            sub = sorted(os.path.join(p, d) for d in os.listdir(p) if os.path.isfile(os.path.join(p, d, "x.tif")))
            if not sub:
                raise InputError(f"no tifxyz patch (x.tif) in {p} or its sub-directories")
            dirs += sub
    out, seen = [], set()
    for d in sorted(dirs, key=lambda s: os.path.normpath(s)):
        m = load_mesh(d, invalid_value)
        parts = os.path.normpath(os.path.abspath(d)).split(os.sep)
        name, up = parts[-1], 1
        while name in seen and up < len(parts) - 1:          # same basename elsewhere: prefix parent folders until unique
            up += 1
            name = "_".join(parts[-up:])
        seen.add(name)
        if m.scale is None:
            raise InputError(f"{d}: meta.json has no usable 'scale' (VC3D requires it)")
        P = np.stack([m.x, m.y, m.z], -1)
        P[~m.valid] = np.nan
        out.append(Patch(name, os.path.normpath(d), P, m.valid.copy(), m.scale))
    if not out:
        raise InputError("no patches given")
    return out


def patch_from_xyz(name, xyz, scale):
    """In-memory Patch from a (H, W, 3) array (-1 or NaN = invalid)."""
    xyz = np.asarray(xyz, np.float64).copy()
    ok = np.isfinite(xyz).all(-1) & ~(xyz == -1).any(-1)
    xyz[~ok] = np.nan
    return Patch(name, name, xyz, ok, (float(scale[0]), float(scale[1])))


# ------------------------------------------------------------------------------------- volume / centre / pitch
def open_volume(zarr_path=None, npy_path=None, level=0):
    """-> (ssc volume, uf volume, description) or (None, None, 'none')."""
    if npy_path:
        if not os.path.isfile(npy_path):
            raise InputError(f"npy volume not found: {npy_path}")
        a = np.load(npy_path, mmap_mode="r")
        return ArrayVolume(a), uf_io.ArrayVolume(a), npy_path
    if zarr_path:
        return ZarrVolume(zarr_path, level), uf_io.open_volume(zarr_path, "zarr", level), f"{zarr_path} level {level}"
    return None, None, "none"


def measure_pitch(patch, vol, p: Params, ssf_p):
    """Median CT pitch of a patch (voxels): trace_auditor.local_pitch on cut lines at evenly spaced heights."""
    if p.pitch_vox:
        return float(p.pitch_vox)
    if vol is None:
        raise InputError("pitch unknown: give --pitch-vox, or a volume (--zarr / --npy) to measure it")
    z = patch.P[..., 2][patch.valid]
    if not z.size:
        raise InputError(f"patch {patch.name} has no valid points")
    lo, hi = float(z.min()), float(z.max())
    hs = np.linspace(lo + 0.2 * (hi - lo), hi - 0.2 * (hi - lo), max(1, p.n_pitch_heights)) if hi > lo else [lo]
    sp = ssc.Params(max_gap_vox=float("inf"), invalid_value=ssf_p.invalid_value)
    m = _mesh_from_P(patch.name, patch.P, patch.valid)
    vals = []
    for h in hs:
        line = ssc.cut_line(m, float(h), sp)
        pp = ta.local_pitch(vol, line, float(h), ssf_p) if line.n else None
        if pp is not None:
            vals.append(float(np.median(pp)))
    if not vals:
        raise InputError(f"cannot measure the CT pitch for {patch.name}; give --pitch-vox")
    return float(np.median(vals))


# ------------------------------------------------------------------------------------- cuts and segments
def find_cuts(patch, p: Params, centre, ta_p):
    """List of cuts: dict(kind, axis 'col'|'row', index = first cell after the cut, detail)."""
    P, valid = patch.P, patch.valid
    cuts = []
    for axis, label in ((1, "col"), (0, "row")):
        a, b = (P[:, :-1], P[:, 1:]) if axis == 1 else (P[:-1], P[1:])
        va, vb = (valid[:, :-1], valid[:, 1:]) if axis == 1 else (valid[:-1], valid[1:])
        both = va & vb
        if both.sum() < 3:
            continue
        L = np.where(both, np.linalg.norm(b - a, axis=-1), np.nan)
        med = float(np.nanmedian(L))
        if not med > 0:
            continue
        broken = both & (L > p.max_edge_stretch * med)
        other = 0 if axis == 1 else 1
        nb, nbr = both.sum(axis=other), broken.sum(axis=other)
        for i in np.flatnonzero((nb >= 3) & (nbr >= p.cut_fraction * np.maximum(nb, 1)) & (nbr > 0)):
            cuts.append(dict(kind="edge-stretch", axis=label, index=int(i) + 1,
                             detail=f"{int(nbr[i])} of {int(nb[i])} neighbour steps across this {label} boundary are "
                                    f"> {p.max_edge_stretch:g} x the median step ({med:.2f} vox)"))
    if centre is not None and patch.pitch:
        z = P[..., 2][valid]
        lo, hi = float(z.min()), float(z.max())
        hs = np.linspace(lo + 0.1 * (hi - lo), hi - 0.1 * (hi - lo), 5) if hi > lo else [lo]
        sp = ssc.Params(max_gap_vox=float("inf"))
        m = _mesh_from_P(patch.name, P, valid)
        found = {}
        for h in hs:
            c = centre.at(float(h))
            if c is None:
                continue
            line = ssc.cut_line(m, float(h), sp)
            if line.n == 0:
                continue
            w = ta.winding_check_height(line, c, np.full(line.n, patch.pitch), ta_p)
            for j in w["jumps"]:
                found.setdefault(int(j["col"]), []).append((float(h), j["step_pitches"]))
        # nearby columns (a ramp seen at slightly different columns at different heights) are one cut
        for col in sorted(found):
            if cuts and cuts[-1]["kind"] == "winding-jump" and cuts[-1]["axis"] == "col" and col - cuts[-1]["_last"] <= 2:
                cuts[-1]["_last"] = col
                continue
            hs_, st = zip(*found[col])
            cuts.append(dict(kind="winding-jump", axis="col", index=col, _last=col,
                             detail=f"radius about the centre line jumps {st[0]:+.2f} pitch at z={hs_[0]:g} (and {len(hs_) - 1} more heights)"))
        for c in cuts:
            c.pop("_last", None)
    # de-duplicate (same axis and index)
    seen, out = set(), []
    for c in sorted(cuts, key=lambda c: (c["axis"], c["index"], c["kind"])):
        k = (c["axis"], c["index"])
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def make_segments(patch, pi, p: Params):
    """Apply the cuts (with margin) and split into segments. Fills patch.cuts[*]['dropped_cells']."""
    keep = patch.valid.copy()
    m = max(1, int(p.cut_margin))
    for c in patch.cuts:
        before = int(keep.sum())
        i = c["index"]
        if c["axis"] == "col":
            keep[:, max(0, i - m):i + m] = False
        else:
            keep[max(0, i - m):i + m, :] = False
        c["dropped_cells"] = before - int(keep.sum())
    lab, n = ndi.label(keep)                           # 4-connected
    segs = []
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    order = [k for k in np.argsort(-sizes[1:], kind="stable") + 1]
    dropped = []
    for k in order:
        if sizes[k] < p.min_segment_points:
            dropped.append(dict(patch=patch.name, n_points=int(sizes[k]),
                                reason=f"fragment of {int(sizes[k])} points (< --min-segment-points {p.min_segment_points})"))
            continue
        segs.append(Seg(patch, pi, len(segs) if (len(patch.cuts) or n > 1) else None, lab == k))
    return segs, dropped


# ------------------------------------------------------------------------------------- pair checks
def _clusters(seg, idx_mask):
    """Connected clusters (8-neighbour) of the selected points of seg on its grid: -> label per point (0 = not selected)."""
    g = np.zeros(seg.mask.shape, bool)
    g[seg.rc[idx_mask, 0], seg.rc[idx_mask, 1]] = True
    lab, _ = ndi.label(g, structure=np.ones((3, 3), int))
    return lab[seg.rc[:, 0], seg.rc[:, 1]]


def _candidates(S, T, d_cand, d_same, p: Params):
    """Points of S that are overlap candidates against T. -> (cand mask, d, nearest index in T, same mask over cand clusters)."""
    d, j = T.tree.query(S.pts, distance_upper_bound=d_cand)
    ok = np.isfinite(d)
    jj = np.where(ok, j, 0)
    ok &= T.edt[T.rc[jj, 0], T.rc[jj, 1]] >= p.edge_cells
    return ok, d, jj


def _cluster_verdict(S, cand, d, d_same, min_frac):
    """Per-point 'in a SAME cluster' and per-cluster stats."""
    lab = _clusters(S, cand)
    same_pt = cand & (d < d_same)
    out = np.zeros(S.n, bool)
    stats = []
    for k in np.unique(lab[lab > 0]):
        m = lab == k
        f = float(same_pt[m].mean())
        stats.append(dict(n=int(m.sum()), same_fraction=f))
        if f >= min_frac:
            out |= m
    return out, stats


def on_sheet_fraction(S, idx, vol, pitch, p: Params):
    """Fraction of the points S.pts[idx] (sampled) with a CT peak along the surface normal within --on-sheet-pitch x pitch."""
    nrm = S.normals()
    idx = idx[np.isfinite(nrm[idx]).all(-1)]
    if len(idx) == 0:
        return None, 0
    if len(idx) > p.max_check_points:
        idx = idx[np.linspace(0, len(idx) - 1, p.max_check_points).astype(int)]
    sc = vol.ct_scale
    hw = p.on_sheet_halfwidth_pitch * pitch
    step = 0.5
    s = np.arange(-hw, hw + 1e-9, step)
    prof = np.full((len(idx), len(s)), np.nan)
    pts, nr = S.pts[idx], nrm[idx]
    shape = vol.data.shape
    for i in range(len(idx)):
        q = (pts[i][None, :] + s[:, None] * nr[i][None, :] - (sc - 1) / 2) / sc          # (n, 3) x, y, z in pixel units
        lo = np.floor(q.min(0)).astype(int) - 1
        hi = np.ceil(q.max(0)).astype(int) + 2
        lo = np.maximum(lo, 0)
        hi = np.minimum(hi, [shape[2], shape[1], shape[0]])
        if (hi <= lo).any():
            continue
        crop = np.asarray(vol.data[lo[2]:hi[2], lo[1]:hi[1], lo[0]:hi[0]], dtype=np.float32)
        prof[i] = map_coordinates(crop, [q[:, 2] - lo[2], q[:, 1] - lo[1], q[:, 0] - lo[0]], order=1, mode="nearest")
    good = np.isfinite(prof).all(1)
    if not good.any():
        return None, 0
    prof = gaussian_filter1d(prof[good], 1.0 / step, axis=1)
    lo_i, hi_i = np.percentile(prof, 0.5), np.percentile(prof, 99.5)
    rng = max(hi_i - lo_i, 1e-9)
    k = prof.argmax(1)
    off = np.abs(s[k])
    prom = prof.max(1) - np.median(prof, axis=1)
    on = (off <= p.on_sheet_pitch * pitch) & (prom >= p.on_sheet_contrast * rng)
    return float(on.mean()), int(good.sum())


def winding_offsets(A, B, ia, ib, centre, pitch, p: Params):
    """trace_auditor pair logic restricted to the overlap: at a few heights, offset of B's overlap from A's overlap at the
    same angle about the centre line, in pitches. -> (list of per-height dicts, fraction ok or None)."""
    if len(ia) == 0 or len(ib) == 0:
        return [], None
    za = A.pts[ia][:, 2]
    zb = B.pts[ib][:, 2]
    lo, hi = max(za.min(), zb.min()), min(za.max(), zb.max())
    if hi < lo:
        return [], None
    hs = np.linspace(lo + 0.1 * (hi - lo), hi - 0.1 * (hi - lo), max(1, p.winding_heights)) if hi > lo else [lo]
    ma = np.zeros(A.mask.shape, bool)
    ma[A.rc[ia, 0], A.rc[ia, 1]] = True
    mb = np.zeros(B.mask.shape, bool)
    mb[B.rc[ib, 0], B.rc[ib, 1]] = True
    meshA = _mesh_from_P(A.name, np.where(ma[..., None], A.P, np.nan), ma)
    meshB = _mesh_from_P(B.name, np.where(mb[..., None], B.P, np.nan), mb)
    sp = ssc.Params(max_gap_vox=float("inf"))
    rows, oks = [], []
    for h in hs:
        c = centre.at(float(h)) if centre else None
        if c is None:
            rows.append(dict(z=float(h), status=NJ, reason="no centre here"))
            continue
        la, lb = ssc.cut_line(meshA, float(h), sp), ssc.cut_line(meshB, float(h), sp)
        if la.n == 0 or lb.n == 0:
            rows.append(dict(z=float(h), status=NJ, reason="no cut line of the overlap at this height"))
            continue
        ra = ta.cut_polar(la, c, np.full(la.n, pitch))
        rb = ta.cut_polar(lb, c, np.full(lb.n, pitch))
        d = ta.pair_offsets(ra, rb) / pitch
        d = d[np.isfinite(d)]
        if d.size == 0:
            rows.append(dict(z=float(h), status=NJ, reason="A has no sheet at the angles of B"))
            continue
        ok = np.abs(d) < p.winding_tol
        oks.append(ok)
        rows.append(dict(z=float(h), status=PASS if ok.mean() >= p.winding_fraction else FAIL, n=int(d.size),
                         ok_fraction=float(ok.mean()), median_offset_pitches=float(np.median(d)),
                         integer_offset=int(round(float(np.median(d))))))
    return rows, (float(np.concatenate(oks).mean()) if oks else None)


def register(A, B, ib, nearest_in_A, ia_of, p: Params):
    """Affine map of B's grid (r, c) into A's grid from the overlap points ib of B and their nearest A points.
    Each correspondence is refined within the cell by projecting the offset onto A's local tangents.
    -> (3x3 homogeneous matrix mapping B (r, c, 1) -> A (r, c, 1), residual in cells) or (None, reason)."""
    tr, tc = A.tangents()
    nb = nearest_in_A[ib]
    rA, cA = A.rc[nb, 0], A.rc[nb, 1]
    t1, t2 = tr[rA, cA], tc[rA, cA]
    v = B.pts[ib] - A.pts[nb]
    g11, g12, g22 = (t1 * t1).sum(1), (t1 * t2).sum(1), (t2 * t2).sum(1)
    b1, b2 = (t1 * v).sum(1), (t2 * v).sum(1)
    det = g11 * g22 - g12 * g12
    with np.errstate(all="ignore"):
        dr, dc = (g22 * b1 - g12 * b2) / det, (-g12 * b1 + g11 * b2) / det
    ok = np.isfinite(dr) & np.isfinite(dc) & (np.abs(dr) < 3) & (np.abs(dc) < 3)
    if ok.sum() < max(6, p.min_overlap_points // 2):
        return None, "too few usable correspondences to register the grids"
    src = np.column_stack([B.rc[ib][ok].astype(float), np.ones(ok.sum())])
    dst = np.column_stack([rA[ok] + dr[ok], cA[ok] + dc[ok]])
    s = np.linalg.svd(src - src.mean(0) * np.array([1, 1, 0]), compute_uv=False)
    if s[-2] < 1.0 or s[0] / max(s[-2], 1e-9) > 1e3:
        return None, "the overlap is too thin or too short to register the grids (degenerate)"
    M, *_ = np.linalg.lstsq(src, dst, rcond=None)         # (3, 2)
    res = np.linalg.norm(src @ M - dst, axis=1)
    resid = float(np.median(res))
    T = np.eye(3)
    T[:2, :] = M.T
    if abs(np.linalg.det(T[:2, :2])) < 1e-6:
        return None, "registration map is singular"
    if resid > p.max_register_residual:
        return None, f"chart registration residual {resid:.2f} cells > --max-register-residual {p.max_register_residual:g}"
    return T, resid


def evaluate_pair(A, B, vol, centre, p: Params):
    """One record per overlapping pair of segments (None if they do not overlap at all)."""
    pitch = 0.5 * ((A.pitch or 0.0) + (B.pitch or 0.0))
    d_cand, d_same = p.candidate_pitch * pitch, p.overlap_pitch * pitch
    a0, a1 = A.bbox()
    b0, b1 = B.bbox()
    if (a0 > b1 + d_cand).any() or (b0 > a1 + d_cand).any():
        return None
    cB, dB, jB = _candidates(B, A, d_cand, d_same, p)          # B points near A (nearest A index jB)
    cA, dA, jA = _candidates(A, B, d_cand, d_same, p)
    n_cand = int(cB.sum() + cA.sum())
    if n_cand < p.min_overlap_points:
        return None
    sB, stB = _cluster_verdict(B, cB, dB, d_same, p.min_same_fraction)
    sA, stA = _cluster_verdict(A, cA, dA, d_same, p.min_same_fraction)
    n_same = int(sA.sum() + sB.sum())
    rec = dict(a=A.name, b=B.name, pitch_vox=pitch, n_candidates=n_cand, n_same=n_same,
               same_fraction=float((cB & (dB < d_same)).sum() + (cA & (dA < d_same)).sum()) / n_cand,
               median_distance_pitch=float(np.median(np.concatenate([dB[cB], dA[cA]])) / pitch),
               clusters=dict(a=stA, b=stB))
    ctr = np.concatenate([B.pts[cB], A.pts[cA]]).mean(0)
    rec["centroid_xyz"] = [float(v) for v in ctr]
    rec["checks"] = {}
    reasons = []
    if n_same < p.min_overlap_points:
        rec["checks"]["shared_sheet"] = dict(status=FAIL)
        rec["status"] = REFUSED
        rec["reason"] = (f"{MISMATCH}: {n_cand} points lie within {p.candidate_pitch:g} pitch of the other patch but only "
                         f"{n_same} in clusters that are within {p.overlap_pitch:g} pitch (median distance "
                         f"{rec['median_distance_pitch']:.2f} pitch)")
        return rec
    if not (sA.any() and sB.any()):
        rec["checks"]["shared_sheet"] = dict(status=FAIL)
        rec["status"] = REFUSED
        rec["reason"] = (f"{MISMATCH}: the overlap is only seen from one patch ({int(sA.sum())} points of A, {int(sB.sum())} of B are in "
                         f"clusters within {p.overlap_pitch:g} pitch of the other)")
        return rec
    rec["checks"]["shared_sheet"] = dict(status=PASS)
    # ---- on-sheet
    if vol is None:
        rec["checks"]["on_sheet"] = dict(status=NJ, reason="no volume given")
    else:
        fa, na = on_sheet_fraction(A, np.flatnonzero(sA), vol, pitch, p)
        fb, nb_ = on_sheet_fraction(B, np.flatnonzero(sB), vol, pitch, p)
        if fa is None or fb is None:
            rec["checks"]["on_sheet"] = dict(status=NJ, reason="could not sample the CT at the overlap")
        else:
            st = PASS if min(fa, fb) >= p.on_sheet_fraction else FAIL
            rec["checks"]["on_sheet"] = dict(status=st, a=fa, b=fb, n_a=na, n_b=nb_)
            if st == FAIL:
                reasons.append(f"off-sheet: only {100 * fa:.0f}% (A) / {100 * fb:.0f}% (B) of the overlap points sit on a CT peak "
                               f"(need {100 * p.on_sheet_fraction:.0f}%)")
    # ---- winding
    if centre is None:
        rec["checks"]["winding"] = dict(status=NJ, reason="no centre line")
    else:
        rows, fr = winding_offsets(A, B, np.flatnonzero(sA), np.flatnonzero(sB), centre, pitch, p)
        if fr is None:
            rec["checks"]["winding"] = dict(status=NJ, reason="; ".join(r.get("reason", "") for r in rows) or "no height judged", heights=rows)
        else:
            bad = [r for r in rows if r["status"] == FAIL]
            st = FAIL if bad else PASS
            rec["checks"]["winding"] = dict(status=st, ok_fraction=fr, heights=rows)
            if bad:
                reasons.append(f"{MISMATCH}: winding offset about the centre line is {bad[0]['integer_offset']:+d} sheet "
                               f"({bad[0]['median_offset_pitches']:+.2f} pitch) at z={bad[0]['z']:g}")
    unj = [k for k, v in rec["checks"].items() if v["status"] == NJ]
    if unj and not p.allow_unjudged:
        reasons.append("not judged: " + "; ".join(f"{k} ({rec['checks'][k]['reason']})" for k in unj) + " (--allow-unjudged to accept)")
    # ---- chart registration
    reg = None
    if not reasons:
        ib = np.flatnonzero(sB)
        reg, info = register(A, B, ib, jB, None, p)
        if reg is None:
            reasons.append(f"registration: {info}")
        else:
            rec["registration"] = dict(residual_cells=info, matrix_b_to_a=[[float(v) for v in r] for r in reg])
    if reasons:
        rec["status"], rec["reason"] = REFUSED, "; ".join(reasons)
        return rec
    rec["status"] = ACCEPTED
    rec["reason"] = (f"{n_same} overlap points, {100 * rec['same_fraction']:.0f}% of the {n_cand} candidates within "
                     f"{p.overlap_pitch:g} pitch; " + ", ".join(f"{k} {v['status']}" for k, v in rec["checks"].items()))
    rec["_T_b_to_a"] = reg
    return rec


# ------------------------------------------------------------------------------------- resampling
def _bilinear(arr, r, c):
    r0, c0 = np.floor(r).astype(int), np.floor(c).astype(int)
    fr, fc = (r - r0)[..., None] if arr.ndim == 3 else (r - r0), (c - c0)[..., None] if arr.ndim == 3 else (c - c0)
    return ((1 - fr) * (1 - fc) * arr[r0, c0] + (1 - fr) * fc * arr[r0, c0 + 1]
            + fr * (1 - fc) * arr[r0 + 1, c0] + fr * fc * arr[r0 + 1, c0 + 1])


def bridge_gaps(P, valid, gap_nodes):
    """Fill invalid nodes of P (H, W, 3) that lie inside holes at most gap_nodes wide, with the normalised mean of
    the valid nodes within the gap. Wider holes are left alone. -> (P, valid, n_filled)."""
    k = int(math.floor(gap_nodes / 2.0))
    if k < 1 or valid.all():
        return P, valid, 0
    pad = np.pad(valid, k + 1)
    closed = ndi.binary_closing(pad, structure=np.ones((3, 3), bool), iterations=k)[k + 1:-(k + 1), k + 1:-(k + 1)]
    fill = closed & ~valid
    if not fill.any():
        return P, valid, 0
    size = 2 * k + 1
    w = ndi.uniform_filter(valid.astype(float), size=size, mode="constant")
    out = P.copy()
    for ax in range(3):
        num = ndi.uniform_filter(np.where(valid, P[..., ax], 0.0), size=size, mode="constant")
        with np.errstate(all="ignore"):
            out[..., ax] = np.where(fill & (w > 0), num / w, P[..., ax])
    newv = valid | (fill & (w > 0))
    return out, newv, int((newv & ~valid).sum())


def resample_component(segs, Ts, p: Params, out_scale, pitch):
    """Segments with their 3x3 maps into the root chart -> (H, W, 3) NaN-padded grid, valid, info.
    Root chart: grid (r, c) of segs[0]. Output node (i, j) is at chart (rmin + i*dr, cmin + j*dc)."""
    root = segs[0]
    sx, sy = root.patch.scale
    ox, oy = out_scale
    dc, dr = sx / ox, sy / oy                                 # chart units per output node (cols, rows)
    lo = np.full(2, np.inf)
    hi = np.full(2, -np.inf)
    for s, T in zip(segs, Ts):
        q = (T @ np.column_stack([s.rc.astype(float), np.ones(s.n)]).T)[:2].T
        lo, hi = np.minimum(lo, q.min(0)), np.maximum(hi, q.max(0))
    H, W = int(math.floor((hi[0] - lo[0]) / dr)) + 1, int(math.floor((hi[1] - lo[1]) / dc)) + 1
    if H * W > p.max_grid_cells:
        raise InputError(f"merged grid {H} x {W} exceeds --max-grid-cells {p.max_grid_cells}")
    num = np.zeros((H, W, 3))
    den = np.zeros((H, W))
    for s, T in zip(segs, Ts):
        Tinv = np.linalg.inv(T)
        q = (T @ np.column_stack([s.rc.astype(float), np.ones(s.n)]).T)[:2].T
        i0, i1 = max(0, int(math.floor((q[:, 0].min() - lo[0]) / dr)) - 1), min(H, int(math.ceil((q[:, 0].max() - lo[0]) / dr)) + 2)
        j0, j1 = max(0, int(math.floor((q[:, 1].min() - lo[1]) / dc)) - 1), min(W, int(math.ceil((q[:, 1].max() - lo[1]) / dc)) + 2)
        ii, jj = np.meshgrid(np.arange(i0, i1), np.arange(j0, j1), indexing="ij")
        R, C = lo[0] + ii * dr, lo[1] + jj * dc
        r = Tinv[0, 0] * R + Tinv[0, 1] * C + Tinv[0, 2]
        c = Tinv[1, 0] * R + Tinv[1, 1] * C + Tinv[1, 2]
        h, w = s.mask.shape
        inb = (r >= 0) & (c >= 0) & (r <= h - 1 - 1e-9) & (c <= w - 1 - 1e-9)
        r, c = np.where(inb, r, 0.0), np.where(inb, c, 0.0)
        r0, c0 = np.minimum(np.floor(r).astype(int), h - 2), np.minimum(np.floor(c).astype(int), w - 2)
        r0, c0 = np.maximum(r0, 0), np.maximum(c0, 0)
        ok = inb & s.mask[r0, c0] & s.mask[r0 + 1, c0] & s.mask[r0, c0 + 1] & s.mask[r0 + 1, c0 + 1] if min(h, w) >= 2 else np.zeros_like(inb)
        if not ok.any():
            continue
        r, c = np.where(ok, r, 0.0), np.where(ok, c, 0.0)
        Pf = np.where(s.mask[..., None], s.P, 0.0)
        pos = _bilinear(Pf, r, c)
        wgt = _bilinear(s.edt, r, c)
        wgt = np.where(ok, np.maximum(wgt, 1e-6), 0.0)
        num[i0:i1, j0:j1] += np.where(ok[..., None], pos, 0.0) * wgt[..., None]
        den[i0:i1, j0:j1] += wgt
    valid = den > 0
    P = np.full((H, W, 3), np.nan)
    P[valid] = num[valid] / den[valid][:, None]
    gap_nodes = p.max_gap_pitch * pitch * min(ox, oy)
    P, valid2, n_br = bridge_gaps(P, valid, gap_nodes)
    return P, valid2, dict(n_bridged=n_br, grid=[H, W])


def write_tifxyz(path, P, valid, scale, extra=None):
    import tifffile
    os.makedirs(path, exist_ok=True)
    xyz = np.where(valid[..., None], P, -1.0).astype(np.float32)
    for k, ax in enumerate("xyz"):
        tifffile.imwrite(os.path.join(path, f"{ax}.tif"), np.ascontiguousarray(xyz[..., k]))
    ok = xyz[..., 0] != -1
    bbox = [xyz[ok].min(axis=0).tolist(), xyz[ok].max(axis=0).tolist()] if ok.any() else [[-1.0] * 3, [-1.0] * 3]
    meta = {"bbox": bbox, "format": "tifxyz", "scale": [float(scale[0]), float(scale[1])], "type": "seg",
            "uuid": str(_uuid.uuid5(_uuid.NAMESPACE_URL, "patch_merger/" + os.path.basename(os.path.normpath(path)) + "/"
                                    + hashlib.sha1(xyz.tobytes()).hexdigest())),
            "area_vx2": area_vx2(xyz), "source": "patch_merger"}
    meta.update(extra or {})
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=4)


# ------------------------------------------------------------------------------------- the merge
class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def merge(patches, vol, centre, p: Params, ssf_p=None, ta_p=None, out_dir=None, log=None):
    """Run the whole pipeline on loaded patches. Writes into out_dir if given. -> report dict (+ 'components_data')."""
    log = log or (lambda m: None)
    if p.cut_margin < 1:
        raise InputError("--cut-margin must be >= 1")
    ssf_p = ssf_p or ssf.Params(vertical=1)
    ta_p = ta_p or ta.Params()
    for pa in patches:
        pa.pitch = measure_pitch(pa, vol, p, ssf_p)
    # ---- cuts and segments
    segs, dropped = [], []
    for i, pa in enumerate(patches):
        pa.cuts = find_cuts(pa, p, centre, ta_p)
        s, d = make_segments(pa, i, p)
        segs += s
        dropped += d
        log(f"{pa.name}: pitch {pa.pitch:.2f}, {len(pa.cuts)} cut(s), {len(s)} segment(s)")
    # ---- pairs
    seams = []
    for a in range(len(segs)):
        for b in range(a + 1, len(segs)):
            A, B = segs[a], segs[b]
            if A.pi == B.pi:
                continue
            rec = evaluate_pair(A, B, vol, centre, p)
            if rec is not None:
                rec["_ia"], rec["_ib"] = a, b
                seams.append(rec)
    for k, s in enumerate(seams):
        s["id"] = k
    # ---- anchoring: a cut-off segment no accepted overlap anchors is dropped if its patch has an anchored segment
    anchored = {s["_ia"] for s in seams if s["status"] == ACCEPTED} | {s["_ib"] for s in seams if s["status"] == ACCEPTED}
    by_patch = {}
    for i, s in enumerate(segs):
        by_patch.setdefault(s.pi, []).append(i)
    alive = set(range(len(segs)))
    for pi, ids in by_patch.items():
        if len(ids) > 1 and any(i in anchored for i in ids):
            for i in ids:
                if i not in anchored:
                    cuts = "; ".join(f"{c['kind']} at {c['axis']} {c['index']}" for c in patches[pi].cuts) or "a break in the grid"
                    segs[i].status = "dropped"
                    segs[i].reason = (f"far side of {cuts}: not anchored by any accepted overlap while another part of "
                                      f"{patches[pi].name} is")
                    alive.discard(i)
        elif len(ids) > 1:
            for i in ids:
                segs[i].reason = "patch was cut but no part of it overlaps another patch: kept as a separate component"
    # ---- components
    uf = _UF(len(segs))
    acc = [s for s in seams if s["status"] == ACCEPTED and s["_ia"] in alive and s["_ib"] in alive]
    for s in acc:
        uf.union(s["_ia"], s["_ib"])
    groups = {}
    for i in sorted(alive):
        groups.setdefault(uf.find(i), []).append(i)
    comps = []
    out_scale_default = None
    if p.scale:
        out_scale_default = (p.scale, p.scale)
    else:
        sx = max(pa.scale[0] for pa in patches)
        sy = max(pa.scale[1] for pa in patches)
        out_scale_default = (sx, sy)
    for ci, (root_id, ids) in enumerate(sorted(groups.items(), key=lambda kv: min(kv[1]))):
        ids = sorted(ids, key=lambda i: (-segs[i].n, i))
        root = ids[0]
        T = {root: np.eye(3)}
        edges = sorted([s for s in acc if s["_ia"] in ids], key=lambda s: (-s["n_same"], s["id"]))
        changed = True
        while changed:
            changed = False
            for s in edges:
                a, b = s["_ia"], s["_ib"]
                if a in T and b not in T:
                    T[b] = T[a] @ s["_T_b_to_a"]
                    changed = True
                elif b in T and a not in T:
                    T[a] = T[b] @ np.linalg.inv(s["_T_b_to_a"])
                    changed = True
        members = [i for i in ids if i in T]
        P, valid, info = resample_component([segs[i] for i in members], [T[i] for i in members], p, out_scale_default,
                                            float(np.mean([segs[i].pitch for i in members])))
        name = f"component_{ci:03d}"
        comps.append(dict(name=name, segments=[segs[i].name for i in members], patches=sorted({segs[i].patch.name for i in members}),
                          P=P, valid=valid, scale=out_scale_default, area_vx2=area_vx2(np.where(valid[..., None], P, -1.0)),
                          n_points=int(valid.sum()), n_bridged=info["n_bridged"], grid=info["grid"],
                          n_seams=sum(1 for s in acc if s["_ia"] in members)))
    # ---- report
    report = dict(tool_version=__version__, params=asdict(p),
                  patches=[dict(patch=pa.name, shape=list(pa.valid.shape), scale=list(pa.scale), pitch_vox=pa.pitch,
                                n_valid=int(pa.valid.sum()), cuts=pa.cuts,
                                segments=[dict(segment=s.name, n_points=s.n, status=s.status, reason=s.reason) for s in segs if s.pi == i])
                           for i, pa in enumerate(patches)],
                  dropped_fragments=dropped,
                  seams=[{k: v for k, v in s.items() if not k.startswith("_")} for s in seams],
                  components=[{k: v for k, v in c.items() if k not in ("P", "valid")} for c in comps])
    refused = [s for s in seams if s["status"] == REFUSED]
    reasons = {}
    for s in refused:
        key = MISMATCH if MISMATCH in s["reason"] else ("off-sheet" if "off-sheet" in s["reason"] else
                                                       ("not judged" if "not judged" in s["reason"] else "registration"))
        reasons[key] = reasons.get(key, 0) + 1
    report["summary"] = dict(n_patches=len(patches), n_segments=len(segs), n_components=len(comps),
                             seams_accepted=len(seams) - len(refused), seams_refused=len(refused), refused_by_reason=reasons,
                             segments_dropped=sum(1 for s in segs if s.status == "dropped"),
                             total_area_vx2=float(sum(c["area_vx2"] for c in comps)))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for c in comps:
            extra = dict(source_patches=c["patches"], source_segments=c["segments"], n_bridged_nodes=c["n_bridged"])
            if p.voxel_um:
                extra["area_cm2"] = c["area_vx2"] * (p.voxel_um * 1e-4) ** 2
            write_tifxyz(os.path.join(out_dir, c["name"] + ".tifxyz"), c["P"], c["valid"], c["scale"], extra)
        with open(os.path.join(out_dir, "seam_report.json"), "w") as f:
            json.dump(report, f, indent=2, default=float)
        with open(os.path.join(out_dir, "seam_report.txt"), "w") as f:
            f.write(text_report(report))
        write_overlay(os.path.join(out_dir, "overlay.png"), patches, segs, seams, comps)
    report["components_data"] = comps
    return report


# ------------------------------------------------------------------------------------- output
def text_report(rep):
    s = rep["summary"]
    out = [f"patch_merger {rep['tool_version']}", "",
           f"{s['n_patches']} patches -> {s['n_segments']} segments -> {s['n_components']} merged components; "
           f"{s['seams_accepted']} overlaps accepted, {s['seams_refused']} refused "
           f"({', '.join(f'{k}: {v}' for k, v in s['refused_by_reason'].items()) or 'none'}); "
           f"{s['segments_dropped']} segments dropped; area {s['total_area_vx2']:.0f} vox^2", ""]
    out.append("CUTS")
    n = 0
    for pa in rep["patches"]:
        for c in pa["cuts"]:
            n += 1
            out.append(f"  {pa['patch']}: {c['kind']} at {c['axis']} {c['index']} ({c.get('dropped_cells', 0)} cells dropped): {c['detail']}")
    out += ["  none"] if not n else []
    out.append("")
    out.append("DROPPED")
    n = 0
    for pa in rep["patches"]:
        for sg in pa["segments"]:
            if sg["status"] == "dropped":
                n += 1
                out.append(f"  {sg['segment']} ({sg['n_points']} points): {sg['reason']}")
    for d in rep["dropped_fragments"]:
        n += 1
        out.append(f"  {d['patch']}: {d['reason']}")
    out += ["  none"] if not n else []
    out.append("")
    out.append("OVERLAPS")
    for sm in rep["seams"]:
        out.append(f"  #{sm['id']:<3d} {sm['status'].upper():8s} {sm['a']}  x  {sm['b']}: {sm['reason']}")
    out += ["  none"] if not rep["seams"] else []
    out.append("")
    out.append("COMPONENTS")
    for c in rep["components"]:
        out.append(f"  {c['name']}: {c['n_points']} points, area {c['area_vx2']:.0f} vox^2, grid {c['grid'][0]}x{c['grid'][1]}, "
                   f"{c['n_seams']} accepted overlaps, {c['n_bridged']} bridged nodes; segments: {', '.join(c['segments'])}")
    return "\n".join(out) + "\n"


_PALETTE = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189), (140, 86, 75),
            (227, 119, 194), (127, 127, 127), (188, 189, 34), (23, 190, 207)]


def write_overlay(path, patches, segs, seams, comps, size=620):
    """PNG: left = input segments (x, y projection, colour per patch), right = merged components; seams drawn on both:
    green = accepted, red = refused, with the overlap number."""
    from PIL import Image, ImageDraw
    allp = np.concatenate([s.pts for s in segs]) if segs else np.zeros((1, 3))
    lo, hi = allp[:, :2].min(0), allp[:, :2].max(0)
    span = float(max((hi - lo).max(), 1e-6))
    sc = (size - 40) / span
    img = Image.new("RGB", (2 * size, size + 22), (20, 20, 24))
    d = ImageDraw.Draw(img)

    def px(xy, off):
        return int(20 + (xy[0] - lo[0]) * sc + off), int(20 + (xy[1] - lo[1]) * sc)

    def draw_pts(pts, col, off, k=30000):
        if len(pts) > k:
            pts = pts[np.linspace(0, len(pts) - 1, k).astype(int)]
        for q in pts:
            x, y = px(q, off)
            d.rectangle((x, y, x + 1, y + 1), fill=col)

    for s in segs:
        draw_pts(s.pts, _PALETTE[s.pi % len(_PALETTE)], 0)
    for c in comps:
        pts = c["P"][c["valid"]]
        draw_pts(pts, _PALETTE[int(c["name"][-3:]) % len(_PALETTE)], size)
    for sm in seams:
        col = (60, 255, 60) if sm["status"] == ACCEPTED else (255, 60, 60)
        for off in (0, size):
            x, y = px(sm["centroid_xyz"], off)
            d.ellipse((x - 5, y - 5, x + 5, y + 5), outline=col, width=2)
            d.text((x + 7, y - 5), str(sm["id"]), fill=col)
    d.text((6, size + 6), f"inputs ({len(patches)} patches, colour = patch)   |   merged ({len(comps)} components)   "
                          f"green = accepted overlap, red = refused", fill=(220, 220, 220))
    img.save(path)


# ------------------------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patches", nargs="+", help="tifxyz directories, or directories holding tifxyz directories")
    ap.add_argument("--out-dir", required=True)
    g = ap.add_argument_group("volume and centre line")
    g.add_argument("--zarr", help="OME-Zarr volume (level-0 voxel coordinates)")
    g.add_argument("--zarr-level", type=int, default=0)
    g.add_argument("--npy", help="volume as .npy (z, y, x)")
    g.add_argument("--umbilicus", help="centre line file (trace_auditor formats); default: estimated from the volume")
    g.add_argument("--umbilicus-format", default="auto")
    g.add_argument("--umbilicus-scale", type=float, default=1.0)
    g.add_argument("--no-centre", action="store_true", help="do not look for a centre line (winding check NOT JUDGED, no winding cuts)")
    g.add_argument("--invalid-value", type=float, default=-1.0)
    for f in dataclasses.fields(Params):
        flag = "--" + f.name.replace("_", "-")
        h = f.metadata.get("help", "")
        if f.type == "bool" or isinstance(f.default, bool):
            ap.add_argument(flag, dest=f.name, action="store_true", default=f.default, help=f"{h}")
        else:
            t = float if f.default is None or isinstance(f.default, float) else int
            ap.add_argument(flag, dest=f.name, type=t, default=f.default, help=f"{h} (default {f.default})")
    ta._sub_flags(ap, "audit", ta.Params, skip=[x.name for x in dataclasses.fields(ta.Params) if not x.name.startswith("wn_")])
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    try:
        for name in ("overlap_pitch", "candidate_pitch", "min_same_fraction", "on_sheet_fraction", "winding_fraction"):
            if getattr(p, name) <= 0:
                raise InputError(f"--{name.replace('_', '-')} must be > 0")
        if p.candidate_pitch < p.overlap_pitch:
            raise InputError("--candidate-pitch must be >= --overlap-pitch")
        ta_p = ta._sub_params(a, "audit", ta.Params)
        patches = load_patches(a.patches, a.invalid_value)
        vol, uvol, desc = open_volume(a.zarr, a.npy, a.zarr_level)
        centre, csrc = None, "none"
        if a.umbilicus:
            z, y, x = ta.read_umbilicus(a.umbilicus, a.umbilicus_format, a.umbilicus_scale)
            centre, csrc = ta.Centre(z, y, x, a.umbilicus, np.inf), f"file {a.umbilicus}"
        elif uvol is not None and not a.no_centre:
            zs = [float(pa.P[..., 2][pa.valid].min()) for pa in patches] + [float(pa.P[..., 2][pa.valid].max()) for pa in patches]
            cen, info = ta.estimate_centre(uvol, min(zs) - 32.0, max(zs) + 32.0, ta.Params(), ta.uf.Params())
            if cen is None:
                csrc = f"umbilicus_finder: only {info['n_ok']} OK slices of {info['n_slices']}"
                log("no centre line: the winding check is NOT JUDGED (give --umbilicus)")
            else:
                centre, csrc = ta.Centre(*cen, "umbilicus_finder", 1.5 * 32.0), "umbilicus_finder"
        ssf_p = ssf.Params(vertical=1)
        rep = merge(patches, vol, centre, p, ssf_p, ta_p, a.out_dir, log)
    except (InputError, uf_io.InputError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    rep.pop("components_data")
    print(text_report(rep), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
