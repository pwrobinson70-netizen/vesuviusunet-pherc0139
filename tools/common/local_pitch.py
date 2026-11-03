"""local_pitch: sheet spacing at EVERY point of a trace, along the local normal, with a confidence per point (MIT).

Shared by sheet_spacing_check, sheet_switch_finder, trace_auditor and crush_map. Pure numpy/scipy, no I/O.

Method (every constant is a field of `PitchParams` and a CLI flag of the tools that use it):
  1. Sample the CT along the local normal at every trace point (+-`half_len_vox`), smooth, remove the slow trend.
  2. Pass 1 (whole profile): peaks (prominence `prominence_frac` x the robust range of the profile, min distance
     `min_distance_px`), gaps between neighbouring peaks, median gap g0.
  3. Pass 2 (LOCAL): only the peaks within +-`window_pitches` x g0 of the trace point, median of THEIR gaps = the local
     pitch at this point. A crushed scroll whose spacing changes by 2x along the normal is then measured where the point is,
     not as the average over 120 voxels.
  4. Confidence in [0, 1] = (peaks) x (regularity) x (contrast): `min(1, n_gaps / full_gaps)`; `max(0, 1 - cv / cv_max)` where
     cv is the robust scatter of the local gaps (1.4826 MAD / median); and `clip(ac / ac_full, 0, 1)` where ac is the
     (unbiased, mean-removed) autocorrelation of the local window at the estimated pitch (smoothed white noise has evenly
     spaced maxima too, but its autocorrelation at that lag is ~0; on real scan data the second lobe is below 0.1). Fewer than `min_peaks` local peaks: confidence 0
     (the pitch then falls back to the pass-1 value so that callers that insist on a number still get one).
  5. Optionally a running median of the pitch along each run of the line (`smooth_points`) and of the confidence.

The OLD behaviour (per-point median peak gap at prominence 0.25 over the whole +-60 voxel profile, falling back to one median
per height) stays in each tool behind `--global-pitch`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates, median_filter
from scipy.signal import find_peaks

__all__ = ["PitchParams", "LocalPitch", "sample_profiles", "estimate_profiles", "local_pitch", "run_median"]


@dataclass
class PitchParams:
    half_len_vox: float = 60.0        # normal profile half-length (voxels)
    step_px: float = 0.5              # profile sample step (CT pixels)
    sigma_px: float = 1.0             # Gaussian smoothing of the profile (CT pixels)
    prominence_frac: float = 0.10     # min peak prominence / robust profile range (old default 0.25: see PR #17 F3)
    min_distance_px: float = 3.0      # min spacing between peaks (CT pixels)
    min_peaks: int = 3                # local peaks needed for a pitch
    window_pitches: float = 3.0       # pass 2 uses peaks within this many pass-1 pitches of the point
    full_gaps: int = 4                # confidence 1 on the peak count from this many local gaps
    cv_max: float = 0.5               # confidence 0 on regularity at this robust scatter of the local gaps
    ac_full: float = 0.5              # confidence 1 on periodicity at this autocorrelation of the local window at the pitch
    trend_sigma_vox: float = 30.0     # slow-trend removal (voxels); 0 = off
    smooth_points: int = 1            # running median of pitch / confidence along each run (odd; 1 = off)
    method: str = "peaks"             # "peaks" (peak gaps) or "acorr" (first autocorrelation peak of the local window)

    def validate(self):
        if self.method not in ("peaks", "acorr"):
            raise ValueError("method must be 'peaks' or 'acorr'")
        if self.smooth_points % 2 != 1:
            raise ValueError("smooth_points must be odd")
        if not (self.half_len_vox > 0 and self.step_px > 0 and self.window_pitches > 0 and self.cv_max > 0
                and self.full_gaps >= 1 and self.min_peaks >= 2 and 0 <= self.prominence_frac < 1):
            raise ValueError("invalid PitchParams")
        return self


@dataclass
class LocalPitch:
    pitch: np.ndarray        # (n,) voxels; NaN where nothing could be measured
    confidence: np.ndarray   # (n,) 0..1
    n_peaks: np.ndarray      # (n,) local peaks used (0 when none)
    cv: np.ndarray           # (n,) robust scatter of the local gaps (NaN when < 2 gaps)

    @property
    def n(self):
        return len(self.pitch)


def run_median(x, run, size):
    """Running median of x over each run (nan-aware: only finite neighbours count; NaN stays NaN)."""
    if size <= 1 or len(x) == 0:
        return np.asarray(x, float).copy()
    out = np.asarray(x, float).copy()
    h = size // 2
    starts = np.flatnonzero(np.r_[True, np.diff(run) != 0])
    ends = np.r_[starts[1:], len(run)]
    for s, e in zip(starts, ends):
        seg = np.asarray(x[s:e], float)
        for i in range(e - s):
            w = seg[max(0, i - h): i + h + 1]
            w = w[np.isfinite(w)]
            if len(w) and np.isfinite(seg[i]):
                out[s + i] = np.median(w)
    return out


def sample_profiles(tile, origin, xy_px, nrm, ct_scale, p: PitchParams):
    """Profiles along the normals. xy_px = trace points in CT pixels (x, y) of the full slice, origin = tile corner (x0, y0).
    Returns (s_vox (m,), prof (n, m)); rows with an undefined normal are NaN."""
    half_px = p.half_len_vox / ct_scale
    s_px = np.arange(-half_px, half_px + 1e-9, p.step_px)
    pts = np.asarray(xy_px, float) - np.asarray(origin, float)
    n = len(pts)
    ok = np.isfinite(nrm[:, 0])
    xs = pts[:, 0:1] + np.where(ok, nrm[:, 0], 0.0)[:, None] * s_px[None, :]
    ys = pts[:, 1:2] + np.where(ok, nrm[:, 1], 0.0)[:, None] * s_px[None, :]
    prof = map_coordinates(np.asarray(tile, float), [ys.ravel(), xs.ravel()], order=1, mode="nearest").reshape(n, -1)
    prof = gaussian_filter1d(prof, p.sigma_px / p.step_px, axis=1)
    prof[~ok] = np.nan
    return s_px * ct_scale, prof


def _detrend(pr, step_vox, p: PitchParams):
    if p.trend_sigma_vox > 0:
        return pr - gaussian_filter1d(pr, p.trend_sigma_vox / step_vox, mode="nearest")
    return pr


def _peaks(pr, p: PitchParams):
    """Peak indices of the profile (prominence >= prominence_frac x max-min of the smoothed, detrended profile, as in the old
    estimator: a percentile range collapses to the noise level when the sheets cover under 5 % of the profile)."""
    rng = float(pr.max() - pr.min())
    if not rng > 0:
        return np.zeros(0, int)
    mind = max(1, int(round(p.min_distance_px / p.step_px)))
    pk, _ = find_peaks(pr, prominence=p.prominence_frac * rng, distance=mind)
    return pk


def _acorr_at(w, lag):
    """Unbiased mean-removed autocorrelation of w at `lag` samples (max over lag +-1), 0 if undefined."""
    w = np.asarray(w, float) - np.mean(w)
    v = float(np.mean(w * w))
    if len(w) < 6 or not v > 0:
        return 0.0
    best = 0.0
    for L in (lag - 1, lag, lag + 1):
        if 1 <= L < len(w) - 2:
            best = max(best, float(np.mean(w[:-L] * w[L:])) / v)
    return max(0.0, best)


def _acorr_pitch(pr, centre, halfwin, step_vox, lo_vox, hi_vox):
    """First autocorrelation peak (voxels) of the window pr[centre-halfwin: centre+halfwin]; (pitch, peak height) or (nan, 0)."""
    a, b = max(0, centre - halfwin), min(len(pr), centre + halfwin + 1)
    w = pr[a:b] - np.mean(pr[a:b])
    if len(w) < 8 or not np.std(w) > 0:
        return np.nan, 0.0
    ac = np.correlate(w, w, "full")[len(w) - 1:]
    ac = ac / np.maximum(np.arange(len(w), 0, -1), 1)           # unbiased
    ac = ac / ac[0]
    lo, hi = max(2, int(lo_vox / step_vox)), min(len(ac) - 2, int(hi_vox / step_vox))
    if hi <= lo:
        return np.nan, 0.0
    pk, _ = find_peaks(ac[: hi + 2])
    pk = [k for k in pk if lo <= k <= hi]
    if not pk:
        return np.nan, 0.0
    k = pk[0]
    return k * step_vox, float(ac[k])


def estimate_profiles(s_vox, prof, p: PitchParams) -> LocalPitch:
    """Local pitch and confidence from profiles (n, m) sampled at s_vox (the trace point is at s = 0)."""
    p.validate()
    n = len(prof)
    step_vox = float(s_vox[1] - s_vox[0])
    centre = int(np.argmin(np.abs(s_vox)))
    pitch, conf = np.full(n, np.nan), np.zeros(n)
    npk, cv = np.zeros(n, int), np.full(n, np.nan)
    for i in range(n):
        pr = prof[i]
        if not np.all(np.isfinite(pr)):
            continue
        pr = _detrend(pr, step_vox, p)
        pk = _peaks(pr, p)
        if len(pk) < 2:
            continue
        pos = s_vox[pk]
        g0 = float(np.median(np.diff(pos)))
        if not g0 > 0:
            continue
        pitch[i] = g0                                            # pass-1 fallback, confidence stays 0
        near = pos[np.abs(pos) <= p.window_pitches * g0]
        if p.method == "acorr":
            hw = int(round(p.window_pitches * g0 / step_vox))
            ap, h = _acorr_pitch(pr, centre, hw, step_vox, 0.4 * g0, 2.2 * g0)
            if np.isfinite(ap):
                pitch[i] = ap
                npk[i] = len(near)
                gaps = np.diff(near) if len(near) >= 2 else np.zeros(0)
                cv[i] = 1.4826 * np.median(np.abs(gaps - np.median(gaps))) / np.median(gaps) if len(gaps) >= 2 else np.nan
                conf[i] = max(0.0, min(1.0, h)) * min(1.0, max(0, len(near) - 1) / p.full_gaps)
            continue
        npk[i] = len(near)
        if len(near) < p.min_peaks:
            continue
        gaps = np.diff(near)
        m = float(np.median(gaps))
        pitch[i] = m
        c = 1.4826 * float(np.median(np.abs(gaps - m))) / m if len(gaps) >= 2 else float("nan")
        cv[i] = c
        c_reg = 1.0 if not np.isfinite(c) else max(0.0, 1.0 - c / p.cv_max)
        hw = int(round(p.window_pitches * g0 / step_vox))
        ac = _acorr_at(pr[max(0, centre - hw): centre + hw + 1], int(round(m / step_vox)))
        conf[i] = min(1.0, len(gaps) / p.full_gaps) * c_reg * min(1.0, ac / p.ac_full)
    return LocalPitch(pitch, conf, npk, cv)


def local_pitch(tile, origin, xy_px, nrm, ct_scale, run, p: PitchParams) -> LocalPitch:
    """Local pitch + confidence at every trace point. `run` = run id per point (smoothing never crosses runs)."""
    p.validate()
    s_vox, prof = sample_profiles(tile, origin, xy_px, nrm, ct_scale, p)
    lp = estimate_profiles(s_vox, prof, p)
    if p.smooth_points > 1:
        lp = LocalPitch(run_median(lp.pitch, run, p.smooth_points), run_median(lp.confidence, run, p.smooth_points),
                        lp.n_peaks, lp.cv)
    return lp
