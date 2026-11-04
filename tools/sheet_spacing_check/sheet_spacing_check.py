#!/usr/bin/env python3
"""sheet_spacing_check: do two traced surfaces stay ~one papyrus sheet apart?  (MIT)

See README.md for the method. Every constant is a field of `Params` and a CLI flag.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, asdict

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates, maximum_filter, median_filter
from scipy.signal import find_peaks
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_COMMON = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)
import local_pitch as lpm  # noqa: E402  (tools/common/local_pitch.py: shared local sheet spacing + confidence)
from ssc_io import (ArrayVolume, InputError, PngVolume, ZarrVolume, load_mesh,  # noqa: E402
                    mesh_voxel_um, to_px)

__version__ = "0.2.0"


@dataclass
class Params:
    ratio_min: float = 0.5          # step 4: clean needs distance/pitch >= this
    ratio_max: float = 1.5          #         ... and <= this
    onsheet_radius_px: float = 2.0  # step 4: CT max radius (CT pixels)
    otsu_bins: int = 256            # step 4: histogram bins for Otsu
    median_window: int = 5          # step 5: running median (odd, points)
    pitch_flag_frac: float = 0.25   # step 6: CT vs mesh pitch mismatch flag
    profile_halflen_vox: float = 60.0   # step 3: normal profile half-length (mesh voxels)
    profile_step_px: float = 0.5        # step 3: profile sample step (CT pixels)
    profile_sigma_px: float = 1.0       # step 3: Gaussian smoothing of profile (CT pixels)
    peak_prominence_frac: float = 0.25  # step 3: min peak prominence / profile range
    peak_min_distance_px: float = 3.0   # step 3: min spacing between peaks (CT pixels)
    min_peaks: int = 3                  # step 3: peaks needed for a pitch
    tangent_halfwidth: int = 3          # step 3: points each side for the local tangent
    max_gap_vox: float = 20.0           # line is split into runs at gaps above this
    densify_step_vox: float = 0.5       # step 2: B line resampling for nearest distance
    b_missing_cols: int = 5             # step 2: A point is 'uncovered' if B has no cut point within
                                        #         this many grid columns
    tile_pad_px: int = 32               # extra margin around the lines for the Otsu tile
    invalid_value: float = -1.0         # tifxyz "no data" marker
    min_clean_heights: int | None = None  # area rule N (default ceil(M/2))
    band_height_vox: float | None = None  # area band thickness (default: height spacing)
    area_min_cos: float = 0.1           # clamp on sqrt(1 - nz^2) in the area band factor
    # --- v0.2 local pitch (tools/common/local_pitch.py)
    global_pitch: bool = False          # OLD behaviour: peak gaps at --peak-prominence-frac over the whole profile, height median as fallback
    pitch_prominence_frac: float = 0.05 # local pitch: min peak prominence / profile range (PR #17: 0.25 gave 14-17 vox on real data, independent 9-10.5)
    pitch_window_pitches: float = 3.0   # local pitch: use the peaks within this many pitches of the point
    pitch_cv_max: float = 0.5           # local pitch: confidence 0 at this robust scatter of the local gaps
    pitch_ac_full: float = 0.5          # local pitch: confidence 1 at this autocorrelation at the pitch
    pitch_smooth_points: int = 1        # local pitch: running median over this many points along each run (odd; 1 = off)
    min_pitch_confidence: float = 0.0   # points whose local-pitch confidence is below this have no pitch (counted 'no pitch', not clean)


# ----------------------------------------------------------- step 1: cut line
@dataclass
class Line:
    xy: np.ndarray      # (n, 2) voxel coords
    col: np.ndarray     # (n,) grid column
    run: np.ndarray     # (n,) run id (contiguous piece of line)
    nz2: np.ndarray     # (n,) squared z-component of the surface unit normal

    @property
    def n(self):
        return len(self.col)


def _nz2_grid(mesh):
    P = np.stack([mesh.x, mesh.y, mesh.z], axis=-1)
    with np.errstate(all="ignore"):
        dr = np.gradient(P, axis=0) if P.shape[0] > 1 else np.full_like(P, np.nan)
        dc = np.gradient(P, axis=1) if P.shape[1] > 1 else np.full_like(P, np.nan)
        n = np.cross(dr, dc)
        return n[..., 2] ** 2 / np.sum(n ** 2, axis=-1)


def cut_line(mesh, z0, p: Params) -> Line:
    """Points where the mesh grid crosses z0, interpolated along grid columns."""
    z = mesh.z
    ok = mesh.valid[:-1] & mesh.valid[1:]
    with np.errstate(invalid="ignore"):
        d = z - z0
        cross = ok & ((d[:-1] <= 0) != (d[1:] <= 0))
    c, r = np.nonzero(cross.T)                    # ordered by column, then row
    if len(c) == 0:
        e = np.zeros(0)
        return Line(np.zeros((0, 2)), e.astype(int), e.astype(int), e)
    d1, d2 = d[r, c], d[r + 1, c]
    t = d1 / (d1 - d2)
    xy = np.stack([mesh.x[r, c] + t * (mesh.x[r + 1, c] - mesh.x[r, c]),
                   mesh.y[r, c] + t * (mesh.y[r + 1, c] - mesh.y[r, c])], axis=1)
    g = _nz2_grid(mesh)
    nz2 = g[r, c] + t * (g[r + 1, c] - g[r, c])
    step = np.hypot(*np.diff(xy, axis=0).T) if len(c) > 1 else np.zeros(0)
    # max_gap_vox is a floor: on a coarse grid (VC3D scale 0.05 = 20 vox per cell) the usual
    # point-to-point step already exceeds it, which used to cut every point into its own run.
    consecutive = np.diff(c) == 1
    typical = float(np.median(step[consecutive])) if consecutive.any() else 0.0
    brk = ~consecutive | (step > max(p.max_gap_vox, 3.0 * typical))
    run = np.concatenate([[0], np.cumsum(brk)])
    return Line(xy, c, run, nz2)


def _run_bounds(run):
    starts = np.flatnonzero(np.r_[True, np.diff(run) != 0])
    ends = np.r_[starts[1:], len(run)]
    return list(zip(starts, ends))


# ------------------------------------------------------------ otsu / on-sheet
def otsu_threshold(img, bins=256):
    v = np.asarray(img, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0 or v.min() == v.max():
        return float(v.max()) if v.size else float("nan")
    hist, edges = np.histogram(v, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    with np.errstate(divide="ignore", invalid="ignore"):
        mu0 = m0 / w0
        mu1 = (m0[-1] - m0) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
    between[~np.isfinite(between)] = -1
    return float(centers[int(np.argmax(between))])


def _disk(radius):
    r = int(math.ceil(radius))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (yy ** 2 + xx ** 2) <= radius ** 2


def _lookup(mask, pts_px, origin):
    """mask value at CT-pixel coords (x, y); False outside the tile."""
    ix = np.rint(pts_px[:, 0] - origin[0]).astype(int)
    iy = np.rint(pts_px[:, 1] - origin[1]).astype(int)
    inside = (ix >= 0) & (iy >= 0) & (ix < mask.shape[1]) & (iy < mask.shape[0])
    out = np.zeros(len(ix), bool)
    out[inside] = mask[iy[inside], ix[inside]]
    return out


# ------------------------------------------------------------ step 3: CT pitch
def normals(line: Line, p: Params):
    """Unit in-plane normals from a local tangent within each run (NaN if undefined)."""
    nrm = np.full((line.n, 2), np.nan)
    k = p.tangent_halfwidth
    for s, e in _run_bounds(line.run):
        if e - s < 2:
            continue
        idx = np.arange(s, e)
        lo, hi = np.clip(idx - k, s, e - 1), np.clip(idx + k, s, e - 1)
        t = line.xy[hi] - line.xy[lo]
        L = np.hypot(t[:, 0], t[:, 1])
        with np.errstate(invalid="ignore", divide="ignore"):
            t = t / L[:, None]
        t[L == 0] = np.nan
        nrm[s:e] = np.stack([-t[:, 1], t[:, 0]], axis=1)
    return nrm


def pitch_params(p: Params) -> "lpm.PitchParams":
    return lpm.PitchParams(half_len_vox=p.profile_halflen_vox, step_px=p.profile_step_px, sigma_px=p.profile_sigma_px,
                           prominence_frac=p.pitch_prominence_frac, min_distance_px=p.peak_min_distance_px,
                           min_peaks=p.min_peaks, window_pitches=p.pitch_window_pitches, cv_max=p.pitch_cv_max,
                           ac_full=p.pitch_ac_full, smooth_points=p.pitch_smooth_points).validate()


def ct_local_pitch(tile, origin, line: Line, ct_scale, p: Params, nrm=None) -> "lpm.LocalPitch":
    """Local pitch (mesh voxels) and confidence at every cut-line point (tools/common/local_pitch.py). `nrm` = unit in-plane
    normals (default: the tangent-based ones; callers that filter out tilted normals pass theirs, NaN = no pitch there)."""
    if line.n == 0:
        z = np.zeros(0)
        return lpm.LocalPitch(z, z, z.astype(int), z)
    lp = lpm.local_pitch(tile, origin, to_px(line.xy, ct_scale), normals(line, p) if nrm is None else nrm, ct_scale,
                         line.run, pitch_params(p))
    if p.min_pitch_confidence > 0:
        lp.pitch[lp.confidence < p.min_pitch_confidence] = np.nan
    return lp


def ct_pitches(tile, origin, line: Line, ct_scale, p: Params):
    """Per-point bright-sheet spacing (mesh voxels) along the local normal: the LOCAL estimator, or with p.global_pitch the
    old per-point median peak gap over the whole profile."""
    if not p.global_pitch:
        return ct_local_pitch(tile, origin, line, ct_scale, p).pitch
    out = np.full(line.n, np.nan)
    if line.n == 0:
        return out
    nrm = normals(line, p)
    half_px = p.profile_halflen_vox / ct_scale
    s = np.arange(-half_px, half_px + 1e-9, p.profile_step_px)
    pts = to_px(line.xy, ct_scale) - np.asarray(origin, float)  # tile pixel coords (x, y)
    xs = pts[:, 0:1] + nrm[:, 0:1] * s[None, :]
    ys = pts[:, 1:2] + nrm[:, 1:2] * s[None, :]
    prof = map_coordinates(tile, [ys.ravel(), xs.ravel()], order=1, mode="nearest")
    prof = prof.reshape(xs.shape)
    prof = gaussian_filter1d(prof, p.profile_sigma_px / p.profile_step_px, axis=1)
    mind = max(1, int(round(p.peak_min_distance_px / p.profile_step_px)))
    for i in range(line.n):
        if not np.isfinite(nrm[i, 0]):
            continue
        pr = prof[i]
        rng = pr.max() - pr.min()
        if rng <= 0:
            continue
        pk, _ = find_peaks(pr, prominence=p.peak_prominence_frac * rng, distance=mind)
        if len(pk) >= p.min_peaks:
            out[i] = np.median(np.diff(pk)) * p.profile_step_px * ct_scale
    return out


# ------------------------------------------------------ step 2: pair distance
def densify(line: Line, step):
    pts = []
    for s, e in _run_bounds(line.run):
        seg = line.xy[s:e]
        pts.append(seg)
        for a, b in zip(seg[:-1], seg[1:]):
            m = int(math.ceil(np.hypot(*(b - a)) / step))
            if m > 1:
                f = (np.arange(1, m) / m)[:, None]
                pts.append(a + f * (b - a))
    return np.concatenate(pts) if pts else np.zeros((0, 2))


def _fill_along_run(pitch, run, fallback):
    """NaN pitches take the value of the nearest finite one on the same run (by point index); `fallback` if the run has none."""
    out = np.asarray(pitch, float).copy()
    for s, e in _run_bounds(run):
        seg = out[s:e]
        fin = np.isfinite(seg)
        if fin.all():
            continue
        if not fin.any():
            out[s:e] = fallback
            continue
        idx = np.arange(e - s)
        near = np.abs(idx[:, None] - idx[fin][None, :]).argmin(axis=1)
        out[s:e] = np.where(fin, seg, seg[fin][near])
    return out


def _no_nearby_col(cols, ref_cols, w):
    """True where no entry of the sorted `ref_cols` lies within +/- w of `cols`."""
    lo = np.searchsorted(ref_cols, cols - w, side="left")
    hi = np.searchsorted(ref_cols, cols + w, side="right")
    return hi <= lo


def _arc_weights(line: Line):
    """Per-point arc length (half of each adjacent segment) within runs, voxels."""
    w = np.zeros(line.n)
    for s, e in _run_bounds(line.run):
        if e - s < 2:
            continue
        seg = np.hypot(*np.diff(line.xy[s:e], axis=0).T)
        w[s:e - 1] += seg / 2
        w[s + 1:e] += seg / 2
    return w


# ------------------------------------------------------ steps 1-6 for a height
def _empty_result(z, na, nb, reason):
    return dict(z=float(z), n_points_a=na, n_points_b=nb, uncovered_a=na == 0,
                uncovered_b=nb == 0, uncovered_fraction=1.0, clean_fraction=0.0,
                shared_fraction=0.0, skipped_fraction=0.0, no_pitch_fraction=0.0,
                median_ratio=None, ct_pitch_vox=None, mesh_pitch_vox=None,
                pitch_mismatch_flag=True, onsheet_fraction_a=0.0, onsheet_fraction_b=0.0,
                otsu_threshold=None, pitch_fallback_fraction=0.0, note=reason,
                pitch_mode=None, pitch_confidence_mean=0.0, pitch_local_p10=None, pitch_local_p90=None)


def _num(v):
    return None if v is None or not np.isfinite(v) else float(v)


def analyse_height(A, B, vol, z0, p: Params, want_overlay=False):
    la, lb = cut_line(A, z0, p), cut_line(B, z0, p)
    pts = dict(col=la.xy[:0, 0].astype(int), clean=np.zeros(0, bool), area=np.zeros(0),
               nz2=np.zeros(0))
    if la.n == 0 or lb.n == 0:
        who = [n for n, l in (("A", la), ("B", lb)) if l.n == 0]
        res = _empty_result(z0, la.n, lb.n, f"height outside z range of mesh {' and '.join(who)}")
        if la.n:     # A points exist: they count as not clean, area still sampled
            pts = dict(col=la.col, clean=np.zeros(la.n, bool), area=_arc_weights(la), nz2=la.nz2)
        return res, pts, None

    sc = vol.ct_scale
    H, W = vol.probe_shape(z0)
    allp = to_px(np.concatenate([la.xy, lb.xy]), sc)
    pad = int(math.ceil(p.profile_halflen_vox / sc + p.onsheet_radius_px + 2)) + p.tile_pad_px
    x0, y0 = max(0, int(math.floor(allp[:, 0].min())) - pad), max(0, int(math.floor(allp[:, 1].min())) - pad)
    x1, y1 = min(W, int(math.ceil(allp[:, 0].max())) + pad + 1), min(H, int(math.ceil(allp[:, 1].max())) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        raise InputError(f"mesh cut lines at z={z0} fall outside the CT slice ({W}x{H} px)")
    tile = vol.tile(z0, x0, y0, x1, y1)
    origin = (x0, y0)

    thr = otsu_threshold(tile, p.otsu_bins)
    onmask = maximum_filter(tile, footprint=_disk(p.onsheet_radius_px), mode="nearest") > thr

    if p.global_pitch:
        pa, pb = ct_pitches(tile, origin, la, sc, p), ct_pitches(tile, origin, lb, sc, p)
        conf_a = np.where(np.isfinite(pa), 1.0, 0.0)
    else:
        lpa, lpb = ct_local_pitch(tile, origin, la, sc, p), ct_local_pitch(tile, origin, lb, sc, p)
        pa, pb, conf_a = lpa.pitch, lpb.pitch, lpa.confidence
    both = np.concatenate([pa, pb])
    ct_pitch = float(np.nanmedian(both)) if np.isfinite(both).any() else float("nan")
    pa_used = np.where(np.isfinite(pa), pa, ct_pitch)          # old / last resort: fall back to the height median
    if not p.global_pitch:
        pa_used = _fill_along_run(pa, la.run, ct_pitch)        # v0.2: the nearest local pitch on the same run first
    fallback = float(np.mean(~np.isfinite(pa) & np.isfinite(ct_pitch)))

    dense = densify(lb, p.densify_step_vox)
    d, idx = cKDTree(dense).query(la.xy)
    # A points with no B data nearby (hole / B ends early) are 'uncovered', not 'skipped'
    bmiss = _no_nearby_col(la.col, lb.col, p.b_missing_cols)
    on_a = _lookup(onmask, to_px(la.xy, sc), origin)
    on_b = _lookup(onmask, to_px(dense[idx], sc), origin)

    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(bmiss, np.nan, d / pa_used)
    nopitch = ~bmiss & ~np.isfinite(ratio)
    shared = ~nopitch & (ratio < p.ratio_min)
    skipped = ~nopitch & (ratio > p.ratio_max)
    inrange = ~bmiss & ~nopitch & ~shared & ~skipped
    raw = inrange & on_a & on_b

    clean = np.zeros(la.n, bool)                               # step 5, per run
    for s, e in _run_bounds(la.run):
        clean[s:e] = median_filter(raw[s:e].astype(np.uint8), size=p.median_window,
                                   mode="nearest") >= 1

    mesh_pitch = float(np.median(d[~bmiss])) if (~bmiss).any() else float("nan")
    mism = (not np.isfinite(ct_pitch)) or (not np.isfinite(mesh_pitch)) or abs(ct_pitch - mesh_pitch) / ct_pitch > p.pitch_flag_frac
    res = dict(z=float(z0), n_points_a=la.n, n_points_b=lb.n, uncovered_a=False,
               uncovered_b=False, uncovered_fraction=float(bmiss.mean()), clean_fraction=float(clean.mean()),
               shared_fraction=float(shared.mean()), skipped_fraction=float(skipped.mean()),
               no_pitch_fraction=float(nopitch.mean()), median_ratio=_num(np.nanmedian(ratio)) if np.isfinite(ratio).any() else None,
               ct_pitch_vox=_num(ct_pitch), mesh_pitch_vox=_num(mesh_pitch),
               pitch_mismatch_flag=bool(mism), onsheet_fraction_a=float(on_a.mean()),
               onsheet_fraction_b=float(on_b.mean()), otsu_threshold=_num(thr),
               pitch_fallback_fraction=fallback, note="",
               pitch_mode="global" if p.global_pitch else "local",
               pitch_confidence_mean=float(np.mean(conf_a)) if len(conf_a) else 0.0,
               pitch_local_p10=_num(np.nanpercentile(pa, 10)) if np.isfinite(pa).any() else None,
               pitch_local_p90=_num(np.nanpercentile(pa, 90)) if np.isfinite(pa).any() else None)
    pts = dict(col=la.col, clean=clean, area=_arc_weights(la), nz2=la.nz2)
    ov = (tile, origin, la, lb, clean) if want_overlay else None
    return res, pts, ov


def heights_bands(heights, p: Params):
    hs = np.asarray(heights, float)
    if p.band_height_vox:
        return np.full(len(hs), float(p.band_height_vox))
    if len(hs) < 2:
        raise InputError("a single height needs --band-height-vox (area band thickness)")
    order = np.argsort(hs)
    s = hs[order]
    gaps = np.diff(s)
    b = np.empty(len(s))
    b[0], b[-1] = gaps[0], gaps[-1]
    b[1:-1] = (gaps[:-1] + gaps[1:]) / 2
    out = np.empty(len(hs))
    out[order] = b
    return out


def run_check(A, B, vol, heights, p: Params, voxel_um=None, overlay_cb=None):
    if A.shape != B.shape:
        raise InputError(f"grid shapes differ: {A.name} {A.shape} vs {B.name} {B.shape}; "
                         "the meshes must be traced on the same grid")
    if p.median_window % 2 != 1:
        raise InputError("--median-window must be odd")
    if not len(heights):
        raise InputError("no heights given")
    M = len(heights)
    N = p.min_clean_heights if p.min_clean_heights is not None else math.ceil(M / 2)
    if not 1 <= N <= M:
        raise InputError(f"--min-clean-heights must be in 1..{M}, got {N}")
    bands = heights_bands(heights, p)

    W = A.shape[1]
    clean_count = np.zeros(W, int)
    area_col = np.zeros(W)                                     # voxel^2, sampled area per column
    rows = []
    excl_pts, excl_arc = 0, 0.0
    for k, z0 in enumerate(heights):
        res, pts, ov = analyse_height(A, B, vol, z0, p, want_overlay=overlay_cb is not None)
        rows.append(res)
        if len(pts["col"]):
            # Undefined normals (NaN, next to holes) are NOT treated as vertical: such points are
            # excluded from the area and cannot make a column clean; they are counted instead.
            fin = np.isfinite(pts["nz2"])
            flag = np.zeros(W, bool)
            flag[pts["col"][pts["clean"] & fin]] = True
            clean_count += flag
            fac = 1.0 / np.maximum(np.sqrt(np.clip(1 - pts["nz2"][fin], 0, 1)), p.area_min_cos)
            np.add.at(area_col, pts["col"][fin], pts["area"][fin] * bands[k] * fac)
            excl_pts += int((~fin).sum())
            excl_arc += float(pts["area"][~fin].sum())
        if ov is not None:
            overlay_cb(res, *ov)

    qual = clean_count >= N
    vox = voxel_um
    to_cm2 = (vox * 1e-4) ** 2 if vox else None
    area = dict(min_clean_heights=N, n_heights=M, voxel_um=vox,
                clean_columns=int(qual.sum()), columns_with_data=int((area_col > 0).sum()),
                clean_area_vox2=float(area_col[qual].sum()),
                sampled_area_vox2=float(area_col.sum()),
                excluded_nan_normal_points=excl_pts, excluded_nan_normal_arc_vox=excl_arc,
                clean_area_cm2=float(area_col[qual].sum() * to_cm2) if to_cm2 else None,
                sampled_area_cm2=float(area_col.sum() * to_cm2) if to_cm2 else None)
    warnings = []
    for m in (A, B):
        if m.n_invalid:
            warnings.append(f"mesh {m.name}: {m.n_invalid} of {m.valid.size} grid cells have no valid "
                            f"data (a coordinate equals {p.invalid_value:g} or is non-finite); "
                            "cut lines skip them")
    unmeasured = [r["z"] for r in rows if r["no_pitch_fraction"] > 0.5 and not r["note"]]
    if unmeasured:
        warnings.append(f"no CT sheet pitch could be measured at z = {', '.join(f'{z:g}' for z in unmeasured)} "
                        f"(fewer than {p.min_peaks} peaks within +/-{p.profile_halflen_vox:g} vox of the cut line, or "
                        "runs too short for a tangent): those points count as not clean. If the sheets are more than "
                        "about a third of --profile-halflen-vox apart, raise --profile-halflen-vox")
    if excl_pts:
        warnings.append(f"{excl_pts} cut points (arc {excl_arc:.1f} vox) have an undefined surface "
                        "normal next to holes; they are excluded from the area and count as not clean")
    if A.scale:
        # cross-check meta.json scale (grid steps per voxel) against measured column spacing
        dx = np.hypot(np.diff(A.x, axis=1), np.diff(A.y, axis=1))
        med = float(np.nanmedian(dx)) if np.isfinite(dx).any() else float("nan")
        if np.isfinite(med) and abs(med * A.scale[0] - 1) > 0.25:
            warnings.append(f"meta.json scale {A.scale} implies {1 / A.scale[0]:.2f} vox column "
                            f"spacing but the grid measures {med:.2f}; area uses measured geometry")
    return dict(heights=rows, area=area, warnings=warnings)


# ----------------------------------------------------------------- reporting
def _pc(v):
    return "  n/a" if v is None else f"{100 * v:5.1f}"


def text_summary(report):
    inp, rows, area = report["inputs"], report["result"]["heights"], report["result"]["area"]
    out = [f"sheet_spacing_check {report['tool_version']}",
           f"A: {inp['mesh_a']}   B: {inp['mesh_b']}   CT: {inp['ct']}", "",
           "     z  nA   clean% shared% skipped% uncov%  med.ratio  CTpitch  meshpitch  flag"]
    for r in rows:
        f = lambda v, fmt: "   n/a" if v is None else fmt % v  # noqa: E731
        out.append(f"{r['z']:6.0f} {r['n_points_a']:4d}  {_pc(r['clean_fraction'])}  "
                   f"{_pc(r['shared_fraction'])}  {_pc(r['skipped_fraction'])}   "
                   f"{_pc(r['uncovered_fraction'])}  {f(r['median_ratio'], '%8.2f')}  "
                   f"{f(r['ct_pitch_vox'], '%7.2f')}  {f(r['mesh_pitch_vox'], '%9.2f')}  "
                   f"{'PITCH-MISMATCH' if r['pitch_mismatch_flag'] else ''}"
                   f"{' UNCOVERED' if r['uncovered_a'] or r['uncovered_b'] else ''}")
    out.append("")
    cm = f"{area['clean_area_cm2']:.4g} cm^2 of {area['sampled_area_cm2']:.4g} cm^2 sampled" \
        if area["clean_area_cm2"] is not None else \
        f"{area['clean_area_vox2']:.4g} vox^2 of {area['sampled_area_vox2']:.4g} vox^2 sampled (no voxel size)"
    out.append(f"Area clean at >= {area['min_clean_heights']} of {area['n_heights']} heights: {cm}")
    out += [f"WARNING: {w}" for w in report["result"]["warnings"]]
    return "\n".join(out) + "\n"


def write_overlay(path, res, tile, origin, la, lb, clean, ct_scale):
    from PIL import Image
    lo, hi = np.percentile(tile, [1, 99])
    g = np.clip((tile - lo) / max(hi - lo, 1e-9), 0, 1)
    img = np.repeat((g * 255).astype(np.uint8)[..., None], 3, axis=2)

    def dot(xy, col):
        px = np.rint(to_px(xy, ct_scale) - np.asarray(origin)).astype(int)
        for dx in (0, 1):
            for dy in (0, 1):
                ix, iy = px[:, 0] + dx, px[:, 1] + dy
                m = (ix >= 0) & (iy >= 0) & (ix < img.shape[1]) & (iy < img.shape[0])
                if np.ndim(col) == 1:
                    img[iy[m], ix[m]] = col
                else:
                    img[iy[m], ix[m]] = col[m]

    dot(lb.xy, np.array([60, 140, 255]))                       # mesh B line: blue
    colours = np.where(clean[:, None], [40, 220, 60], [240, 40, 40]).astype(np.uint8)
    dot(la.xy, colours)                                        # mesh A: green clean / red not
    Image.fromarray(img).save(path)


# ----------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("mesh_a", help="tifxyz folder of the reference mesh A")
    ap.add_argument("mesh_b", help="tifxyz folder of the mesh B (the proposed neighbour)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr", help="OME-Zarr volume")
    g.add_argument("--png-dir", help="directory of 2-D slice PNGs")
    ap.add_argument("--zarr-level", type=int, default=0, help="OME-Zarr level (coords are level-0 voxels)")
    ap.add_argument("--png-pixel-um", type=float, help="PNG pixel size in um (PNG input)")
    ap.add_argument("--png-pattern", default="{z:05d}.png", help="PNG name; {z} = slice index")
    ap.add_argument("--voxel-size-um", type=float, help="mesh voxel size; overrides meta.json")
    ap.add_argument("--heights", required=True, help="comma-separated z heights (volume voxels)")
    ap.add_argument("--transpose", action="store_true", help="grids have z varying along columns")
    ap.add_argument("--out-json"), ap.add_argument("--out-txt")
    ap.add_argument("--overlay-dir", help="write one overlay PNG per height here")
    d = Params()
    for f, v in asdict(d).items():
        flag = "--" + f.replace("_", "-")
        if v is None:
            ap.add_argument(flag, type=float if f == "band_height_vox" else int, default=None)
        elif isinstance(v, bool):
            ap.add_argument(flag, action="store_true", help="(off by default)")
        else:
            ap.add_argument(flag, type=type(v), default=v)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f: getattr(a, f) for f in asdict(Params())})
    try:
        heights = [float(h) for h in a.heights.split(",") if h.strip()]
        A = load_mesh(a.mesh_a, p.invalid_value, a.transpose)
        B = load_mesh(a.mesh_b, p.invalid_value, a.transpose)
        vox = mesh_voxel_um(A, B, a.voxel_size_um)
        if a.zarr:
            vol, ct = ZarrVolume(a.zarr, a.zarr_level), f"{a.zarr} level {a.zarr_level}"
        else:
            vol, ct = PngVolume(a.png_dir, a.png_pixel_um, vox, a.png_pattern), a.png_dir
        cb = None
        if a.overlay_dir:
            os.makedirs(a.overlay_dir, exist_ok=True)
            cb = lambda res, *ov: write_overlay(  # noqa: E731
                os.path.join(a.overlay_dir, f"overlay_z{int(res['z']):06d}.png"),
                res, *ov, vol.ct_scale)
        result = run_check(A, B, vol, heights, p, vox, cb)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    report = dict(tool_version=__version__, inputs=dict(mesh_a=a.mesh_a, mesh_b=a.mesh_b, ct=ct,
                  heights=heights, voxel_um=vox), params=asdict(p), result=result)
    txt = text_summary(report)
    if a.out_json:
        with open(a.out_json, "w") as fh:
            json.dump(report, fh, indent=2)
    if a.out_txt:
        with open(a.out_txt, "w") as fh:
            fh.write(txt)
    print(txt, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
