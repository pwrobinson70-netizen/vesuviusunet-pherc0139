#!/usr/bin/env python3
"""sheet_switch_finder: where does a traced surface jump onto a neighbouring papyrus sheet?  (MIT)

See README.md for the method. Every constant is a field of `Params` and a CLI flag.
Mesh / CT readers, the cut line, normals, CT pitch and the on-sheet test are imported from
tools/sheet_spacing_check (not copied, not modified).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates, maximum_filter, median_filter
from scipy.signal import find_peaks

_SSC_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "sheet_spacing_check"))
if _SSC_DIR not in sys.path:
    sys.path.insert(0, _SSC_DIR)
import sheet_spacing_check as ssc  # noqa: E402
from ssc_io import (InputError, PngVolume, ZarrVolume, load_mesh, to_px)  # noqa: E402

__version__ = "0.2.0"

_D = ssc.Params()      # defaults shared with sheet_spacing_check stay in sync


@dataclass
class Params:
    # --- switch test (method steps 2, 3, 5)
    sample_pitches: float = 3.0         # step 2: sample the normal +/- this many CT pitches
    step_min: float = 0.6               # step 5: single switch if |step| >= this (pitches) ...
    step_max: float = 1.4               #         ... and <= this
    multi_step_max: float = 3.5         # step 5: larger steps up to this are reported as multi-sheet
    k_points: int = 5                   # step 5: points that must stay on each side
    median_window: int = _D.median_window   # step 5/7: running median (odd, points)
    # --- tracking (step 3)
    track_max_jump_pitch: float = 0.5   # nearest peak must lie within this (pitches) of the track
    max_lost_points: int = 10           # restart tracking after this many points without a peak
    max_offsheet_bridge: int = 10       # restart tracking after this many consecutive off-sheet points
    max_gap_pitches: float = 3.5        # cut line is split into runs at gaps above this (pitches)
    normal_break_factor: float = 4.0    # normals are not taken across a point-to-point step this many
                                        # times the median step (a hard jump), 0 = never break
    max_tilt_deg: float = 25.0          # normals tilted more than this from the local median normal are
                                        # not used (the mesh is crossing sheets there); 0 = keep all
    tilt_window: int = 31               # points of the running median that defines the local normal
    # --- orientation / pitch
    orientation: str = "radial"         # 'radial' = + is away from the centre; 'grid' = raw normal
    centre_x: float | None = None       # scroll axis x for 'radial' (default: centroid of the cut line)
    centre_y: float | None = None
    pitch_vox: float | None = None      # override the measured CT pitch (voxels)
    global_pitch: bool = False          # OLD behaviour: one CT pitch per height; steps in units of it (PR #17 finding 5: 17 vox vs 9.5 measured)
    pitch_prominence_frac: float = _D.pitch_prominence_frac   # local pitch (tools/common/local_pitch.py), same defaults as sheet_spacing_check
    pitch_window_pitches: float = _D.pitch_window_pitches
    pitch_cv_max: float = _D.pitch_cv_max
    pitch_ac_full: float = _D.pitch_ac_full
    pitch_smooth_points: int = 9        # running median of the local pitch along the line: beside a switch the normal profile straddles two sheets and reads about 2x
    min_pitch_confidence: float = _D.min_pitch_confidence
    # --- vertical test (step 6)
    vertical: int = 1                   # 1 = run the vertical test, 0 = skip it
    # --- confidence
    conf_int_tol: float = 0.4           # |step| this far (pitches) from a whole number -> 0 confidence
    conf_flat_tol: float = 0.3          # mean abs deviation on the two sides (pitches) -> 0 confidence
    # --- CT sampling / on-sheet, shared with sheet_spacing_check (same defaults)
    onsheet_radius_px: float = _D.onsheet_radius_px
    otsu_bins: int = _D.otsu_bins
    profile_halflen_vox: float = _D.profile_halflen_vox   # only for measuring the CT pitch
    profile_step_px: float = _D.profile_step_px
    profile_sigma_px: float = _D.profile_sigma_px
    peak_prominence_frac: float = _D.peak_prominence_frac
    peak_min_distance_px: float = _D.peak_min_distance_px
    min_peaks: int = _D.min_peaks
    tangent_halfwidth: int = _D.tangent_halfwidth
    tile_pad_px: int = _D.tile_pad_px
    invalid_value: float = _D.invalid_value
    overlay_zoom: int = 3               # overlay PNG magnification

    def validate(self):
        if self.median_window < 1 or self.median_window % 2 == 0:
            raise InputError(f"--median-window must be odd and >= 1, got {self.median_window}")
        if self.k_points < 1:
            raise InputError(f"--k-points must be >= 1, got {self.k_points}")
        if not (0 < self.step_min < self.step_max < self.multi_step_max):
            raise InputError("need 0 < --step-min < --step-max < --multi-step-max")
        if self.sample_pitches <= 0 or self.max_gap_pitches <= 0 or self.track_max_jump_pitch <= 0:
            raise InputError("--sample-pitches, --max-gap-pitches and --track-max-jump-pitch must be > 0")
        if self.orientation not in ("radial", "grid"):
            raise InputError(f"--orientation must be 'radial' or 'grid', got {self.orientation!r}")
        if (self.centre_x is None) != (self.centre_y is None):
            raise InputError("give both --centre-x and --centre-y, or neither")
        if self.pitch_vox is not None and not self.pitch_vox > 0:
            raise InputError("--pitch-vox must be > 0")
        if self.overlay_zoom < 1:
            raise InputError("--overlay-zoom must be >= 1")

    def ssc(self, max_gap_vox):
        return ssc.Params(
            median_window=self.median_window, onsheet_radius_px=self.onsheet_radius_px,
            otsu_bins=self.otsu_bins, profile_halflen_vox=self.profile_halflen_vox,
            profile_step_px=self.profile_step_px, profile_sigma_px=self.profile_sigma_px,
            peak_prominence_frac=self.peak_prominence_frac,
            peak_min_distance_px=self.peak_min_distance_px, min_peaks=self.min_peaks,
            tangent_halfwidth=self.tangent_halfwidth, tile_pad_px=self.tile_pad_px,
            invalid_value=self.invalid_value, max_gap_vox=max_gap_vox, global_pitch=self.global_pitch,
            pitch_prominence_frac=self.pitch_prominence_frac, pitch_window_pitches=self.pitch_window_pitches,
            pitch_cv_max=self.pitch_cv_max, pitch_ac_full=self.pitch_ac_full,
            pitch_smooth_points=self.pitch_smooth_points, min_pitch_confidence=self.min_pitch_confidence)


OK, OFF, LOST = 0, 1, 2     # per-point status: tracked on-sheet / off the papyrus / on-sheet but track lost


# ------------------------------------------------------------- step 1: cut line
def cut_rows(mesh, z0):
    """Fractional grid row of every cut point, in the same order as ssc.cut_line (by column, row)."""
    z = mesh.z
    ok = mesh.valid[:-1] & mesh.valid[1:]
    with np.errstate(invalid="ignore"):
        d = z - z0
        cross = ok & ((d[:-1] <= 0) != (d[1:] <= 0))
    c, r = np.nonzero(cross.T)
    if len(c) == 0:
        return np.zeros(0)
    d1, d2 = d[r, c], d[r + 1, c]
    return r + d1 / (d1 - d2)


def resplit(line, gap_vox):
    """New run ids: split at non-consecutive columns or xy gaps above gap_vox."""
    if line.n < 2:
        return ssc.Line(line.xy, line.col, np.zeros(line.n, int), line.nz2)
    step = np.hypot(*np.diff(line.xy, axis=0).T)
    brk = (np.diff(line.col) != 1) | (step > gap_vox)
    return ssc.Line(line.xy, line.col, np.concatenate([[0], np.cumsum(brk)]), line.nz2)


def normal_runs(line, factor):
    """Finer run ids for the tangents: also split at jumps much larger than the usual point
    spacing, so that the normals beside a hard jump stay clean (the track is still continuous)."""
    if factor <= 0 or line.n < 3:
        return line
    step = np.hypot(*np.diff(line.xy, axis=0).T)
    typ = np.median(step[step > 0]) if (step > 0).any() else 0.0
    brk = (np.diff(line.run) != 0) | (step > factor * typ if typ > 0 else False)
    return ssc.Line(line.xy, line.col, np.concatenate([[0], np.cumsum(brk)]), line.nz2)


def tilt_filter(nrm, fine_line, p: Params):
    """(normals with the tilted ones NaN'd, running-median normals).

    A ramp between sheets tilts the line's normal; sampling along it inflates the offset by
    1/cos(tilt) and displaces the hit sideways. Normals more than max_tilt_deg away from the
    running-median normal angle are dropped (the point becomes 'lost'). The median normal is
    also used as the sheet-normal direction for the continuity test of the tracker."""
    med = nrm.copy()
    out = nrm.copy()
    for s, e in ssc._run_bounds(fine_line.run):
        ok = np.isfinite(nrm[s:e, 0])
        if ok.sum() < 3:
            continue
        ang = np.unwrap(np.arctan2(nrm[s:e, 1][ok], nrm[s:e, 0][ok]))
        filled = np.interp(np.arange(e - s), np.flatnonzero(ok), ang)
        w = max(1, min(p.tilt_window, (e - s) // 2 * 2 - 1))
        ref = median_filter(filled, size=w, mode="nearest")
        med[s:e] = np.stack([np.cos(ref), np.sin(ref)], axis=1)
        if p.max_tilt_deg > 0:
            out[s:e][np.abs(filled - ref) > math.radians(p.max_tilt_deg)] = np.nan
    return out, med


def orient(nrm, line, p: Params):
    """Flip the normal of whole runs so that + points away from the centre (outward)."""
    nrm = nrm.copy()
    if p.orientation == "grid":
        return nrm
    c = (np.array([p.centre_x, p.centre_y], float) if p.centre_x is not None
         else line.xy.mean(axis=0))
    for s, e in ssc._run_bounds(line.run):
        dots = np.nansum(np.einsum("ij,ij->i", nrm[s:e], line.xy[s:e] - c))
        if dots < 0:
            nrm[s:e] *= -1
    return nrm


# ---------------------------------------------------------- step 2: peaks on the normal
def sample_profiles(tile, origin, line, nrm, ct_scale, half_vox, p: Params):
    """Smoothed CT profiles along the normals: (s in voxels, (n, m) profiles)."""
    half_px = half_vox / ct_scale
    s_px = np.arange(-half_px, half_px + 1e-9, p.profile_step_px)
    pts = to_px(line.xy, ct_scale) - np.asarray(origin, float)
    nx = np.where(np.isfinite(nrm[:, 0]), nrm[:, 0], 0.0)[:, None]
    ny = np.where(np.isfinite(nrm[:, 1]), nrm[:, 1], 0.0)[:, None]
    xs, ys = pts[:, 0:1] + nx * s_px[None, :], pts[:, 1:2] + ny * s_px[None, :]
    prof = map_coordinates(tile, [ys.ravel(), xs.ravel()], order=1, mode="nearest").reshape(xs.shape)
    prof = gaussian_filter1d(prof, p.profile_sigma_px / p.profile_step_px, axis=1)
    return s_px * ct_scale, prof


def find_sheet_peaks(pr, s_vox, p: Params):
    """Positions (voxels along the normal, parabola-refined) of the bright-sheet peaks."""
    rng = pr.max() - pr.min()
    if not rng > 0:
        return np.zeros(0)
    mind = max(1, int(round(p.peak_min_distance_px / p.profile_step_px)))
    pk, _ = find_peaks(pr, prominence=p.peak_prominence_frac * rng, distance=mind)
    if len(pk) == 0:
        return np.zeros(0)
    ds = s_vox[1] - s_vox[0]
    y0, y1, y2 = pr[pk - 1], pr[pk], pr[pk + 1]
    den = y0 - 2 * y1 + y2
    with np.errstate(divide="ignore", invalid="ignore"):
        delta = np.where(den < 0, 0.5 * (y0 - y2) / den, 0.0)
    return s_vox[pk] + np.clip(delta, -1, 1) * ds


# ------------------------------------------------------------ step 3 + 4: tracking
def track_run(xy, nrm, mnrm, peaks, on, pitch, p: Params):
    """Track ONE CT sheet along one run. Returns (offset in pitches, segment id)."""
    n = len(xy)
    pitch = np.broadcast_to(np.asarray(pitch, float), (n,))      # v0.2: local pitch per point (a scalar still works)
    off = np.full(n, np.nan)
    seg = np.full(n, -1)
    ref, lost, off_run, seg_id = None, 0, 0, -1
    for i in range(n):
        if not on[i]:
            off_run += 1
            if ref is not None and off_run > p.max_offsheet_bridge:
                ref = None
        else:
            off_run = 0
        if not np.isfinite(nrm[i, 0]):
            lost += 1
            if ref is not None and lost > p.max_lost_points:
                ref = None
            continue
        pk = peaks[i]
        if ref is None:
            if not on[i] or len(pk) == 0:
                continue
            k = int(np.argmin(np.abs(pk)))              # the peak nearest the mesh
            seg_id += 1
            lost = 0
        else:
            # continuity: the candidate sheet point nearest the tracked one, measured ACROSS the
            # sheet (along the median normal), so sliding along the line costs nothing.
            k = -1
            if len(pk):
                d = np.abs((xy[i] + nrm[i] * pk[:, None] - ref) @ mnrm[i])
                k = int(np.argmin(d))
            gate = p.track_max_jump_pitch * pitch[i]
            if k < 0 or d[k] > gate:
                lost += 1
                if lost > p.max_lost_points:
                    ref = None
                continue
            lost = 0
        ref = xy[i] + nrm[i] * pk[k]
        off[i] = -pk[k] / pitch[i]                       # (mesh - sheet) / LOCAL pitch, mesh at 0
        seg[i] = seg_id
    return off, seg


# ---------------------------------------------------------------- step 5: step test
def _mad(a, centre):
    return float(np.mean(np.abs(a - centre)))


def confidence(step, mad_sum, p: Params):
    n = max(1, round(abs(step)))
    a = 1.0 - min(1.0, abs(abs(step) - n) / p.conf_int_tol)
    b = 1.0 - min(1.0, mad_sum / p.conf_flat_tol)
    return float(a * b)


def classify(step):
    """Direction, whole-sheet count; 'double' when the step is too big for one sheet."""
    return "outward" if step > 0 else "inward"


def sheets_for(step, p: Params):
    a = abs(step)
    return 1 if a <= p.step_max else max(2, int(math.floor(a + 0.5)))


def detect_steps(x, p: Params):
    """Steps of ~1 pitch (or more) in the sequence x that persist >= K points on both sides.

    Returns dicts with i (first point after the step, index into x), step, mad_before/after.
    """
    K, n = p.k_points, len(x)
    if n < 2 * K:
        return []
    xs = median_filter(np.asarray(x, float), size=p.median_window, mode="nearest")
    cand = []
    for i in range(K, n - K + 1):
        b, a = xs[i - K:i], xs[i:i + K]
        mb, ma = float(np.median(b)), float(np.median(a))
        st = ma - mb
        if not p.step_min <= abs(st) <= p.multi_step_max:
            continue
        mid = (ma + mb) / 2
        stays = (np.all(b <= mid) and np.all(a >= mid)) if st > 0 else (np.all(b >= mid) and np.all(a <= mid))
        if stays:
            cand.append(dict(i=i, step=st, mad_before=_mad(b, mb), mad_after=_mad(a, ma)))
    out = []
    for c in cand:          # chains of near-by candidates of one sign are one event: keep the largest
        if out and c["i"] - out[-1]["i"] < K and (c["step"] > 0) == (out[-1]["step"] > 0):
            if abs(c["step"]) > abs(out[-1]["step"]) + 1e-12:
                out[-1] = c
            continue
        out.append(c)
    return out


def detect_stretches(step, p: Params):
    """Vertical test: stretches of >= K consecutive columns whose (median-smoothed) height-to-height
    offset change is one sign and in [step_min, multi_step_max]. Returns (j0, j1_exclusive, value)."""
    n = len(step)
    if n < p.k_points:
        return []
    sm = median_filter(np.asarray(step, float), size=p.median_window, mode="nearest")
    good = (np.abs(sm) >= p.step_min) & (np.abs(sm) <= p.multi_step_max)
    out, j = [], 0
    while j < n:
        if not good[j]:
            j += 1
            continue
        e = j
        while e + 1 < n and good[e + 1] and (sm[e + 1] > 0) == (sm[j] > 0):
            e += 1
        if e - j + 1 >= p.k_points:
            out.append((j, e + 1, float(np.median(sm[j:e + 1]))))
        j = e + 1
    return out


# --------------------------------------------------------------- one height
def _tile_for(vol, line, half_vox, p: Params, z0):
    sc = vol.ct_scale
    H, W = vol.probe_shape(z0)
    allp = to_px(line.xy, sc)
    pad = int(math.ceil(half_vox / sc + p.onsheet_radius_px + 2)) + p.tile_pad_px
    x0, y0 = max(0, int(math.floor(allp[:, 0].min())) - pad), max(0, int(math.floor(allp[:, 1].min())) - pad)
    x1, y1 = min(W, int(math.ceil(allp[:, 0].max())) + pad + 1), min(H, int(math.ceil(allp[:, 1].max())) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        raise InputError(f"mesh cut line at z={z0} falls outside the CT slice ({W}x{H} px)")
    return vol.tile(z0, x0, y0, x1, y1), (x0, y0)


def _empty_height(z, n, note):
    return dict(z=float(z), n_points=int(n), ct_pitch_vox=None, fraction_tracked=0.0,
                fraction_off_sheet=0.0, fraction_lost=0.0, n_switches=0, n_runs=0, note=note)


def analyse_height(mesh, vol, z0, p: Params):
    """Horizontal analysis at one height. Returns (record, switches, state)."""
    sp = p.ssc(max_gap_vox=float("inf"))
    line = ssc.cut_line(mesh, z0, sp)
    if line.n == 0:
        return _empty_height(z0, 0, "height outside the z range of the mesh"), [], None
    rows = cut_rows(mesh, z0)
    assert len(rows) == line.n, "internal: cut_rows out of step with cut_line"
    sc = vol.ct_scale

    tile, origin = _tile_for(vol, line, p.profile_halflen_vox, p, z0)
    pitch = p.pitch_vox
    lpc = None
    if pitch is None:
        if p.global_pitch:
            pp = ssc.ct_pitches(tile, origin, line, sc, sp)
        else:
            lpc = ssc.ct_local_pitch(tile, origin, line, sc, sp)
            pp = lpc.pitch
        pitch = float(np.nanmedian(pp)) if np.isfinite(pp).any() else float("nan")
    if not (np.isfinite(pitch) and pitch > 0):
        return _empty_height(z0, line.n, "no CT pitch could be measured (fewer than "
                                         f"{p.min_peaks} peaks anywhere on the line)"), [], None
    # per-point pitch: the LOCAL pitch (nearest valid one along the run where none was measured); the height value for
    # --global-pitch or --pitch-vox
    pitch_pp = np.full(line.n, pitch) if lpc is None else ssc._fill_along_run(pp, line.run, pitch)
    half = p.sample_pitches * float(np.max(pitch_pp))
    if half > p.profile_halflen_vox:        # the tile must cover the sampling profile
        tile, origin = _tile_for(vol, line, half, p, z0)

    line = resplit(line, p.max_gap_pitches * pitch)
    thr = ssc.otsu_threshold(tile, p.otsu_bins)
    onmask = maximum_filter(tile, footprint=ssc._disk(p.onsheet_radius_px), mode="nearest") > thr
    on_raw = ssc._lookup(onmask, to_px(line.xy, sc), origin)
    on = np.zeros(line.n, bool)                              # on-sheet, smoothed as in sheet_spacing_check
    for s, e in ssc._run_bounds(line.run):
        on[s:e] = median_filter(on_raw[s:e].astype(np.uint8), size=p.median_window, mode="nearest") >= 1

    fine = normal_runs(line, p.normal_break_factor)
    nrm, mnrm = tilt_filter(orient(ssc.normals(fine, sp), line, p), fine, p)
    if lpc is not None:       # v0.2: re-measure the local pitch with the tilt-filtered normals (beside a hop the tangent normal is tilted and reads ~2x)
        lpc = ssc.ct_local_pitch(tile, origin, line, sc, sp, nrm=nrm)
        pitch_pp = ssc._fill_along_run(lpc.pitch, line.run, pitch)
        pp = lpc.pitch
    s_vox, prof = sample_profiles(tile, origin, line, nrm, sc, half, p)
    peaks = [find_sheet_peaks(prof[i], s_vox, p) if np.isfinite(nrm[i, 0]) else np.zeros(0)
             for i in range(line.n)]

    offset = np.full(line.n, np.nan)
    seg = np.full(line.n, -1)
    seg_base = 0
    for s, e in ssc._run_bounds(line.run):
        o, sg = track_run(line.xy[s:e], nrm[s:e], mnrm[s:e], peaks[s:e], on[s:e], pitch_pp[s:e], p)
        offset[s:e] = o
        seg[s:e] = np.where(sg >= 0, sg + seg_base, -1)
        seg_base += int(sg.max()) + 1 if (sg >= 0).any() else 0

    status = np.where(~on, OFF, np.where(np.isfinite(offset), OK, LOST))
    usable = (status == OK)

    switches = []
    for s, e in ssc._run_bounds(line.run):
        for sid in np.unique(seg[s:e][usable[s:e]]):
            idx = np.flatnonzero(usable & (seg == sid))
            idx = idx[(idx >= s) & (idx < e)]
            for d in detect_steps(offset[idx], p):
                i = d["i"]
                li = int((idx[i - 1] + idx[i] + 1) // 2)          # middle of the gap between the sides
                switches.append(_switch_record(
                    "horizontal", z0, z0, line, rows, li, d["step"],
                    d["mad_before"] + d["mad_after"], p, line_index=li,
                    index_before=int(idx[i - 1]), index_after=int(idx[i]),
                    persist_before=p.k_points, persist_after=p.k_points))
    switches.sort(key=lambda r: r["line_index"])
    rec = dict(z=float(z0), n_points=int(line.n), ct_pitch_vox=pitch,
               pitch_mode="local" if lpc is not None else ("override" if p.pitch_vox is not None else "global"),
               pitch_confidence_mean=float(np.mean(lpc.confidence)) if lpc is not None else None,
               pitch_local_p10=float(np.nanpercentile(pp, 10)) if lpc is not None and np.isfinite(pp).any() else None,
               pitch_local_p90=float(np.nanpercentile(pp, 90)) if lpc is not None and np.isfinite(pp).any() else None,
               fraction_tracked=float(np.mean(status == OK)),
               fraction_off_sheet=float(np.mean(status == OFF)),
               fraction_lost=float(np.mean(status == LOST)),
               n_switches=len(switches), n_runs=int(line.run.max()) + 1, note="")
    state = dict(line=line, rows=rows, offset=offset, status=status, usable=usable, pitch=pitch, pitch_pp=pitch_pp,
                 pitch_conf=(lpc.confidence if lpc is not None else None))
    return rec, switches, state


def _switch_record(kind, z_from, z_to, line, rows, li, step, mad_sum, p, **extra):
    n_sheets = sheets_for(step, p)
    return dict(kind=kind, height=float(z_to), height_from=float(z_from), height_to=float(z_to),
                row=float(rows[li]), col=int(line.col[li]),
                x=float(line.xy[li, 0]), y=float(line.xy[li, 1]), z=float(z_to),
                direction=classify(step), step=float(step), n_sheets=n_sheets,
                double_switch=bool(n_sheets >= 2), confidence=confidence(step, mad_sum, p), **extra)


# ---------------------------------------------------------------- vertical test
def vertical_switches(heights, states, p: Params):
    out = []
    for h0, h1 in zip(heights[:-1], heights[1:]):
        s0, s1 = states.get(h0), states.get(h1)
        if s0 is None or s1 is None:
            continue

        def per_col(st):     # first tracked on-sheet cut point of each grid column
            d = {}
            for i in np.flatnonzero(st["usable"]):
                d.setdefault(int(st["line"].col[i]), i)
            return d
        a, b = per_col(s0), per_col(s1)
        cols = sorted(set(a) & set(b))
        if not cols:
            continue
        brk = np.flatnonzero(np.diff(cols) != 1) + 1
        for chunk in np.split(np.asarray(cols), brk):
            step = np.array([s1["offset"][b[c]] - s0["offset"][a[c]] for c in chunk])
            for j0, j1, val in detect_stretches(step, p):
                seg = step[j0:j1]
                mid = (j0 + j1 - 1) // 2
                li = b[int(chunk[mid])]
                out.append(_switch_record(
                    "vertical", h0, h1, s1["line"], s1["rows"], li, val,
                    _mad(seg, float(np.median(seg))), p, line_index=int(li),
                    col_start=int(chunk[j0]), col_end=int(chunk[j1 - 1]), n_columns=int(j1 - j0)))
    return out


# ------------------------------------------------------------------- the run
def run_finder(mesh, vol, heights, p: Params, overlay_cb=None, want_states=False):
    p.validate()
    hs = sorted({float(h) for h in heights})
    if not hs or not all(math.isfinite(h) for h in hs):
        raise InputError("need at least one finite height")
    recs, switches, states, warns = [], [], {}, []
    for h in hs:
        rec, sw, st = analyse_height(mesh, vol, h, p)
        recs.append(rec)
        switches += sw
        if st is not None:
            states[h] = st
        if rec["note"]:
            warns.append(f"z={h:g}: {rec['note']}")
    if p.vertical and len(hs) > 1:
        switches += vertical_switches(hs, states, p)
    for r in recs:
        r["n_vertical_switches"] = sum(1 for s in switches if s["kind"] == "vertical" and s["height_to"] == r["z"])
    if mesh.n_invalid:
        warns.append(f"{mesh.n_invalid} grid cells have no data")
    switches.sort(key=lambda s: (s["height"], s["kind"] != "horizontal", s["line_index"]))
    n_pts = sum(r["n_points"] for r in recs)
    tot = lambda k: (sum(r[k] * r["n_points"] for r in recs) / n_pts) if n_pts else None  # noqa: E731
    summary = dict(n_heights=len(hs), n_points=n_pts, n_switches=len(switches),
                   n_horizontal=sum(s["kind"] == "horizontal" for s in switches),
                   n_vertical=sum(s["kind"] == "vertical" for s in switches),
                   n_double=sum(s["double_switch"] for s in switches),
                   fraction_tracked=tot("fraction_tracked"), fraction_off_sheet=tot("fraction_off_sheet"),
                   fraction_lost=tot("fraction_lost"))
    result = dict(heights=recs, switches=switches, summary=summary, warnings=warns)
    if want_states:                  # per-height internals (line, per-point local pitch + confidence); not JSON-serialisable
        result["states"] = states
    if overlay_cb:
        for r in recs:
            st = states.get(r["z"])
            if st is not None:
                marks = [s for s in switches if s["height"] == r["z"]]
                overlay_cb(r, st, marks, vol)
    return result


# --------------------------------------------------------------------- output
def _pc(v):
    return "n/a" if v is None else f"{100 * v:.1f}%"


def text_summary(report):
    res, out = report["result"], []
    s = res["summary"]
    out.append("sheet_switch_finder " + report["tool_version"])
    out.append(f"mesh: {report['inputs']['mesh']}   CT: {report['inputs']['ct']}")
    out.append(f"heights: {s['n_heights']}   cut-line points: {s['n_points']}")
    out.append(f"SWITCHES: {s['n_switches']} (horizontal {s['n_horizontal']}, vertical {s['n_vertical']}, "
               f"double/multi-sheet {s['n_double']})")
    out.append(f"line tracked: {_pc(s['fraction_tracked'])}   off-sheet: {_pc(s['fraction_off_sheet'])}   "
               f"lost track: {_pc(s['fraction_lost'])}")
    out.append("")
    out.append("per height:")
    for r in res["heights"]:
        pit = "n/a" if r["ct_pitch_vox"] is None else f"{r['ct_pitch_vox']:.2f}"
        out.append(f"  z={r['z']:g}: points {r['n_points']}, pitch {pit} vox, tracked "
                   f"{_pc(r['fraction_tracked'])}, off-sheet {_pc(r['fraction_off_sheet'])}, lost "
                   f"{_pc(r['fraction_lost'])}, switches {r['n_switches']} horizontal + "
                   f"{r.get('n_vertical_switches', 0)} vertical" + (f"  [{r['note']}]" if r["note"] else ""))
    if res["switches"]:
        out.append("")
        out.append("switches (human: check these spots):")
        for w in res["switches"]:
            where = f"z={w['height']:g}" if w["kind"] == "horizontal" else \
                f"z={w['height_from']:g}->{w['height_to']:g}, cols {w['col_start']}-{w['col_end']}"
            out.append(f"  {w['kind']:<10} {where}  row {w['row']:.1f} col {w['col']}  "
                       f"xyz ({w['x']:.1f}, {w['y']:.1f}, {w['z']:g})  {w['direction']}  step {w['step']:+.2f}"
                       f"{'  DOUBLE (' + str(w['n_sheets']) + ' sheets)' if w['double_switch'] else ''}"
                       f"  confidence {w['confidence']:.2f}")
    for w in res["warnings"]:
        out.append(f"warning: {w}")
    return "\n".join(out) + "\n"


def _offset_colours(off, status):
    t = np.clip(np.nan_to_num(off) / 1.5, -1, 1)[:, None]
    base = np.array([40, 200, 60.0])
    hot, cold = np.array([240, 50, 40.0]), np.array([50, 90, 255.0])
    col = np.where(t >= 0, base + t * (hot - base), base + (-t) * (cold - base))
    col[status == OFF] = (255, 255, 255)
    col[status == LOST] = (255, 220, 0)
    return col.astype(np.uint8)


def write_overlay(path, state, marks, tile, origin, ct_scale, zoom):
    """Tile in grey; cut line coloured by offset (green 0, red + / outward, blue - / inward,
    white off-sheet, yellow lost); rings mark switches (cyan horizontal, magenta vertical)."""
    from PIL import Image, ImageDraw
    lo, hi = np.percentile(tile, [1, 99])
    g = np.clip((tile - lo) / max(hi - lo, 1e-9), 0, 1)
    img = np.repeat((g * 255).astype(np.uint8)[..., None], 3, axis=2)
    line = state["line"]
    px = np.rint(to_px(line.xy, ct_scale) - np.asarray(origin)).astype(int)
    col = _offset_colours(state["offset"], state["status"])
    m = (px[:, 0] >= 0) & (px[:, 1] >= 0) & (px[:, 0] < img.shape[1]) & (px[:, 1] < img.shape[0])
    img[px[m, 1], px[m, 0]] = col[m]
    im = Image.fromarray(img).resize((img.shape[1] * zoom, img.shape[0] * zoom), Image.NEAREST)
    dr = ImageDraw.Draw(im)
    for w in marks:
        c = (to_px(np.array([[w["x"], w["y"]]]), ct_scale)[0] - np.asarray(origin) + 0.5) * zoom
        rad = 5 * zoom
        dr.ellipse([c[0] - rad, c[1] - rad, c[0] + rad, c[1] + rad],
                   outline=(0, 255, 255) if w["kind"] == "horizontal" else (255, 0, 255), width=max(1, zoom // 2))
    im.save(path)


# ----------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("mesh", help="tifxyz folder of the traced surface")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr", help="OME-Zarr volume")
    g.add_argument("--png-dir", help="directory of 2-D slice PNGs")
    ap.add_argument("--zarr-level", type=int, default=0, help="OME-Zarr level (coords are level-0 voxels)")
    ap.add_argument("--png-pixel-um", type=float, help="PNG pixel size in um (PNG input)")
    ap.add_argument("--png-pattern", default="{z:05d}.png", help="PNG name; {z} = slice index")
    ap.add_argument("--voxel-size-um", type=float, help="mesh voxel size; overrides meta.json (PNG input)")
    ap.add_argument("--heights", required=True, help="comma-separated z heights (volume voxels)")
    ap.add_argument("--transpose", action="store_true", help="grids have z varying along columns")
    ap.add_argument("--out-json"), ap.add_argument("--out-txt")
    ap.add_argument("--overlay-dir", help="write one overlay PNG per height here")
    for f, v in asdict(Params()).items():
        flag = "--" + f.replace("_", "-")
        if isinstance(v, bool):
            ap.add_argument(flag, action="store_true", help="(off by default)")
        else:
            ap.add_argument(flag, type=(float if v is None else type(v)), default=v)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f: getattr(a, f) for f in asdict(Params())})
    try:
        p.validate()
        try:
            heights = [float(h) for h in a.heights.split(",") if h.strip()]
        except ValueError as e:
            raise InputError(f"--heights must be comma-separated numbers: {e}") from e
        mesh = load_mesh(a.mesh, p.invalid_value, a.transpose)
        if a.zarr:
            vol, ct = ZarrVolume(a.zarr, a.zarr_level), f"{a.zarr} level {a.zarr_level}"
        else:
            vox = a.voxel_size_um or mesh.voxel_um
            vol, ct = PngVolume(a.png_dir, a.png_pixel_um, vox, a.png_pattern), a.png_dir
        cb = None
        if a.overlay_dir:
            os.makedirs(a.overlay_dir, exist_ok=True)

            def cb(rec, st, marks, vol_):      # noqa: E306 - tile is re-read, so memory stays small
                line = st["line"]
                tile, origin = _tile_for(vol_, line, p.sample_pitches * st["pitch"] + 1, p, rec["z"])
                write_overlay(os.path.join(a.overlay_dir, f"overlay_z{int(rec['z']):06d}.png"),
                              st, marks, tile, origin, vol_.ct_scale, p.overlay_zoom)
        result = run_finder(mesh, vol, heights, p, cb)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    report = dict(tool_version=__version__, inputs=dict(mesh=a.mesh, ct=ct, heights=heights),
                  params=asdict(p), result=result)
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
