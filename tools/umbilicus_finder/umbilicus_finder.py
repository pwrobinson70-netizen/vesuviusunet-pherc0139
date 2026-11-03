"""umbilicus_finder: estimate a scroll's centre line (umbilicus) from CT slices, with confidence.

MIT licence (see repository LICENSE). CPU only. Dependencies: numpy, scipy, pillow (+ zarr for OME-Zarr).

Per slice: mask the scroll -> structure tensor (sheet normals) -> closed-form least-squares point
closest to all normal lines -> robust re-weighting -> confidence. Along z: confidence-weighted
running median + smoothing spline. See README.md. Every constant is a field of Params and a CLI flag.
"""
import argparse
import dataclasses
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from scipy.interpolate import UnivariateSpline

import uf_io
from uf_io import InputError

__version__ = "0.2.0"


@dataclass
class Params:
    # --- slice preparation / mask
    target_px: int = field(default=1000, metadata=dict(help="downsample (block mean) so the longer side is about this many px"))
    otsu_classes: int = field(default=2, metadata=dict(help="2 = Otsu; 3 = 3-class Otsu using its lowest threshold (for a case much denser than papyrus; untested on real data)"))
    mask_sigma: float = field(default=2.0, metadata=dict(help="Gaussian sigma (ds px) before thresholding"))
    close_radius: int = field(default=2, metadata=dict(help="binary closing radius (ds px) before fill-holes; 0 = off"))
    # --- structure tensor / votes
    sigma_grad: float = field(default=1.5, metadata=dict(help="gradient Gaussian sigma (ds px)"))
    sigma_int: float = field(default=4.0, metadata=dict(help="tensor integration Gaussian sigma (ds px)"))
    coherence_min: float = field(default=0.4, metadata=dict(help="keep pixels with structure-tensor coherence >= this"))
    energy_min_frac: float = field(default=0.1, metadata=dict(help="keep pixels with gradient energy >= this fraction of the in-mask 95th percentile"))
    energy_cap: float = field(default=3.0, metadata=dict(help="vote weight = coherence * min(energy / median energy, cap)"))
    widen_low_coherence: bool = field(default=False, metadata=dict(help="where the coherence is below --coherence-min, re-compute the structure tensor with a wider integration window (--sigma-int x --widen-factor^k, k = 1..--widen-steps) and keep a wider scale only where it raises the coherence (PR #17 finding 2: real slices have long flat wraps and weak sheets, every slice LOW)"))
    widen_factor: float = field(default=2.0, metadata=dict(help="integration sigma multiplier per widening step"))
    widen_steps: int = field(default=2, metadata=dict(help="number of widening steps"))
    # --- robust centre
    robust: str = field(default="tukey", metadata=dict(help="re-weighting: tukey or huber", choices=["tukey", "huber"]))
    robust_iters: int = field(default=8, metadata=dict(help="re-weighting iterations"))
    tukey_c: float = field(default=4.685, metadata=dict(help="Tukey cutoff in robust scales"))
    huber_k: float = field(default=1.345, metadata=dict(help="Huber knee in robust scales"))
    min_scale_px: float = field(default=0.25, metadata=dict(help="floor for the robust residual scale (ds px)"))
    inlier_weight: float = field(default=0.5, metadata=dict(help="a vote is an inlier if its robust weight >= this"))
    # --- confidence / flags
    min_votes: int = field(default=300, metadata=dict(help="LOW if fewer inlier votes than this"))
    votes_full: int = field(default=3000, metadata=dict(help="inlier votes at which the votes factor reaches 1"))
    min_coverage_deg: float = field(default=180.0, metadata=dict(help="LOW if angular coverage of inlier votes is below this (deg)"))
    coverage_full_deg: float = field(default=300.0, metadata=dict(help="coverage at which the coverage factor reaches 1 (deg)"))
    coverage_bin_deg: float = field(default=10.0, metadata=dict(help="azimuth bin width for coverage (deg)"))
    coverage_bin_min_frac: float = field(default=0.005, metadata=dict(help="a bin counts as covered with >= this fraction of inlier votes (and >= 3)"))
    max_residual_pitch: float = field(default=1.0, metadata=dict(help="LOW if median perpendicular residual exceeds this many pitches; factor is 0.5 at this value"))
    min_confidence: float = field(default=0.3, metadata=dict(help="LOW if confidence is below this"))
    # --- pitch (sheet spacing), used only to express the residual in pitches
    pitch_vox: float = field(default=0.0, metadata=dict(help="sheet pitch in level-0 voxels; 0 = estimate from the data"))
    pitch_search_px: float = field(default=40.0, metadata=dict(help="half-length of the normal-direction profiles used to estimate pitch (ds px)"))
    pitch_samples: int = field(default=1500, metadata=dict(help="votes sampled for the pitch estimate"))
    pitch_min_peak: float = field(default=0.1, metadata=dict(help="minimum autocorrelation peak accepted as the pitch"))
    # --- along z
    median_window: int = field(default=5, metadata=dict(help="weighted running-median window (samples, odd)"))
    spline_sigma_vox: float = field(default=3.0, metadata=dict(help="assumed per-slice centre noise (level-0 voxels) for the smoothing spline"))
    spline_degree: int = field(default=3, metadata=dict(help="smoothing spline degree (1-5)"))
    min_weight: float = field(default=0.02, metadata=dict(help="floor on the confidence used as spline / median weight"))
    departure_vox: float = field(default=10.0, metadata=dict(help="report z ranges where the smoothed line is further than this from the raw estimate (level-0 voxels)"))
    seed: int = field(default=0, metadata=dict(help="random seed (vote sub-sampling)"))


# --------------------------------------------------------------------------- slice helpers
def downsample(img, target_px):
    """Block-mean downsample by an integer factor so max(h, w) is about target_px."""
    img = np.asarray(img, dtype=np.float32)
    f = max(1, int(round(max(img.shape) / float(target_px))))
    if f == 1:
        return img, 1
    h, w = (img.shape[0] // f) * f, (img.shape[1] // f) * f
    return img[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3)), f


def otsu_lower_threshold(img, classes=3, bins=128):
    """Lowest threshold of (multi-)Otsu on a clipped histogram. None if the image is flat."""
    lo, hi = np.percentile(img, [0.5, 99.9])
    if not np.isfinite(lo) or hi - lo < 1e-6:
        return None
    hist, edges = np.histogram(np.clip(img, lo, hi), bins=bins, range=(lo, hi))
    p = hist / hist.sum()
    centres = 0.5 * (edges[:-1] + edges[1:])
    om, mu = np.cumsum(p), np.cumsum(p * centres)
    mt = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        if classes == 2:
            sb = (mt * om - mu) ** 2 / (om * (1 - om))
            sb[~np.isfinite(sb)] = -1
            return float(edges[int(np.argmax(sb)) + 1])
        t1, t2 = np.triu_indices(bins - 1, k=1)
        w0, w1, w2 = om[t1], om[t2] - om[t1], 1 - om[t2]
        m0, m1, m2 = mu[t1] / w0, (mu[t2] - mu[t1]) / w1, (mt - mu[t2]) / w2
        var = w0 * (m0 - mt) ** 2 + w1 * (m1 - mt) ** 2 + w2 * (m2 - mt) ** 2
    var[~np.isfinite(var)] = -1
    return float(edges[int(t1[int(np.argmax(var))]) + 1])


def scroll_mask(img, p):
    """Otsu -> largest component by papyrus pixel count -> closing -> fill holes. None if no scroll.

    The component with most foreground pixels (counted before hole filling) is taken, so a thin
    case ring that encloses the scroll cannot win by its filled area.
    """
    sm = ndi.gaussian_filter(img, p.mask_sigma) if p.mask_sigma > 0 else img
    t = otsu_lower_threshold(sm, p.otsu_classes)
    if t is None:
        return None
    fg = sm > t
    lab, n = ndi.label(fg, structure=np.ones((3, 3)))
    if n == 0:
        return None
    sizes = ndi.sum(fg, lab, index=np.arange(1, n + 1))
    comp = lab == (1 + int(np.argmax(sizes)))
    if p.close_radius > 0:
        r = int(p.close_radius)
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        comp = ndi.binary_closing(comp, structure=(xx ** 2 + yy ** 2) <= r * r, border_value=0)
    return ndi.binary_fill_holes(comp)


def structure_tensor(img, sigma_grad, sigma_int):
    """Return (nx, ny, coherence, energy): unit dominant-gradient (sheet normal) in (x, y)."""
    gy = ndi.gaussian_filter(img, sigma_grad, order=(1, 0))
    gx = ndi.gaussian_filter(img, sigma_grad, order=(0, 1))
    jxx = ndi.gaussian_filter(gx * gx, sigma_int)
    jyy = ndi.gaussian_filter(gy * gy, sigma_int)
    jxy = ndi.gaussian_filter(gx * gy, sigma_int)
    theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy)
    tr = jxx + jyy
    disc = np.sqrt(((jxx - jyy) / 2) ** 2 + jxy ** 2)
    coh = np.where(tr > 1e-12, 2 * disc / np.maximum(tr, 1e-12), 0.0)
    return np.cos(theta), np.sin(theta), coh, tr


def structure_tensor_adaptive(img, sigma_grad, sigma_int, coherence_min, factor=2.0, steps=2):
    """Structure tensor whose integration window is widened (sigma_int * factor^k) wherever the coherence is below
    `coherence_min`. A pixel below the threshold adopts a wider scale only if that scale gives it a HIGHER coherence (wide windows
    average towards isotropy in noise and mix orientations on curved sheets, so the widest scale is not always the best), so the
    coherence never drops and pixels already at or above `coherence_min` are untouched."""
    nx, ny, coh, en = structure_tensor(img, sigma_grad, sigma_int)
    s = sigma_int
    for _ in range(max(0, int(steps))):
        low = coh < coherence_min
        if not low.any():
            break
        s *= factor
        nx2, ny2, coh2, en2 = structure_tensor(img, sigma_grad, s)
        take = low & (coh2 > coh)
        nx, ny, coh, en = (np.where(take, b, a) for a, b in ((nx, nx2), (ny, ny2), (coh, coh2), (en, en2)))
    return nx, ny, coh, en


def solve_centre(px, py, nx, ny, w):
    """argmin_c sum w_i |P_i (c - p_i)|^2, P_i = I - n_i n_i^T (closed form 2x2). None if degenerate."""
    a11 = np.sum(w * (1 - nx * nx))
    a22 = np.sum(w * (1 - ny * ny))
    a12 = np.sum(w * (-nx * ny))
    # b = sum w P p
    b1 = np.sum(w * ((1 - nx * nx) * px - nx * ny * py))
    b2 = np.sum(w * (-nx * ny * px + (1 - ny * ny) * py))
    det = a11 * a22 - a12 * a12
    if not np.isfinite(det) or det <= 1e-9 * (a11 + a22) ** 2:
        return None
    return np.array([(a22 * b1 - a12 * b2) / det, (a11 * b2 - a12 * b1) / det])  # (x, y)


def perp_dist(c, px, py, nx, ny):
    return np.abs((c[0] - px) * ny - (c[1] - py) * nx)


def robust_weights(d, p):
    s = max(1.4826 * float(np.median(d)), p.min_scale_px)
    if p.robust == "tukey":
        u = d / (p.tukey_c * s)
        return np.where(u < 1, (1 - u * u) ** 2, 0.0)
    return np.minimum(1.0, p.huber_k * s / np.maximum(d, 1e-12))


def coverage_deg(az, p):
    """Angular coverage (deg, 0-360): bins with enough votes x bin width."""
    nb = max(1, int(round(360.0 / p.coverage_bin_deg)))
    h, _ = np.histogram(np.mod(az, 2 * np.pi), bins=nb, range=(0, 2 * np.pi))
    thr = max(3.0, p.coverage_bin_min_frac * len(az))
    return float(np.sum(h >= thr) * 360.0 / nb)


def estimate_pitch_px(img, px, py, nx, ny, p, rng):
    """Sheet pitch (ds px) from the mean autocorrelation of intensity profiles along vote normals."""
    if len(px) < 50:
        return None
    idx = rng.choice(len(px), size=min(p.pitch_samples, len(px)), replace=False)
    half = float(p.pitch_search_px)
    t = np.arange(-half, half + 1e-9, 0.5)
    ys = py[idx, None] + t[None, :] * ny[idx, None]
    xs = px[idx, None] + t[None, :] * nx[idx, None]
    prof = ndi.map_coordinates(img, [ys.ravel(), xs.ravel()], order=1, mode="nearest").reshape(ys.shape)
    prof = prof - prof.mean(axis=1, keepdims=True)
    n = prof.shape[1]
    f = np.fft.rfft(prof, n=2 * n, axis=1)
    acf = np.fft.irfft(f * np.conj(f), axis=1)[:, :n].mean(axis=0)
    if acf[0] <= 0:
        return None
    acf = acf / acf[0] * (n / (n - np.arange(n)))  # unbiased
    acf[0] = 1.0
    maxlag = n // 2
    neg = np.nonzero(acf[:maxlag] < 0)[0]
    if len(neg) == 0:
        return None
    seg = acf[neg[0]:maxlag]
    k = int(np.argmax(seg))
    if k == 0 or k == len(seg) - 1 or seg[k] < p.pitch_min_peak:
        return None
    return float((neg[0] + k) * 0.5)


# --------------------------------------------------------------------------- one slice
@dataclass
class SliceResult:
    ok: bool = False                # a centre was produced
    cy: float = np.nan              # level-0 voxels (centre convention)
    cx: float = np.nan
    n_votes: int = 0
    n_inliers: int = 0
    coverage_deg: float = 0.0
    residual_vox: float = np.nan    # median perpendicular distance over all votes
    pitch_vox: float = np.nan       # local pitch estimate, nan if none
    reasons: list = field(default_factory=list)
    confidence: float = 0.0
    flag: str = "LOW"
    residual_pitch: float = np.nan
    debug: dict = field(default_factory=dict)


def analyse_slice(img2d, p, scale_xy=1.0, keep_debug=False, rng=None):
    """Estimate the centre of one 2-D slice. Never raises on bad content: returns ok=False."""
    rng = rng if rng is not None else np.random.default_rng(p.seed)
    r = SliceResult()
    img, f = downsample(img2d, p.target_px)
    unit = f * scale_xy  # ds px -> level-0 voxels
    if keep_debug:
        r.debug.update(img=img, f=f)
    if not np.all(np.isfinite(img)):
        img = np.nan_to_num(img)
    mask = scroll_mask(img, p) if img.size and img.max() > img.min() else None
    if mask is None or mask.sum() < 100:
        r.reasons.append("no_scroll")
        return r
    if p.widen_low_coherence:
        nx, ny, coh, en = structure_tensor_adaptive(img, p.sigma_grad, p.sigma_int, p.coherence_min, p.widen_factor, p.widen_steps)
    else:
        nx, ny, coh, en = structure_tensor(img, p.sigma_grad, p.sigma_int)
    e_ref = np.percentile(en[mask], 95)
    keep = mask & (coh >= p.coherence_min) & (en >= p.energy_min_frac * e_ref) & (en > 0)
    yy, xx = np.nonzero(keep)
    r.n_votes = int(len(yy))
    if len(yy) < 10:
        r.reasons.append("few_votes")
        return r
    px, py = xx.astype(float), yy.astype(float)
    vnx, vny = nx[keep], ny[keep]
    w0 = coh[keep] * np.minimum(en[keep] / np.median(en[keep]), p.energy_cap)

    c = solve_centre(px, py, vnx, vny, w0)
    if c is None:
        r.reasons.append("degenerate")
        return r
    wr = np.ones_like(w0)
    for _ in range(max(0, p.robust_iters)):
        wr_new = robust_weights(perp_dist(c, px, py, vnx, vny), p)
        if np.count_nonzero(w0 * wr_new) < 10:
            break
        c_new = solve_centre(px, py, vnx, vny, w0 * wr_new)
        if c_new is None:
            break
        wr, c = wr_new, c_new
    d = perp_dist(c, px, py, vnx, vny)
    inl = wr >= p.inlier_weight
    r.n_inliers = int(inl.sum())
    az = np.arctan2(py[inl] - c[1], px[inl] - c[0])
    r.coverage_deg = coverage_deg(az, p) if r.n_inliers else 0.0
    r.residual_vox = float(np.median(d) * unit)
    pp = estimate_pitch_px(img, px, py, vnx, vny, p, rng)
    r.pitch_vox = float(pp * unit) if pp else np.nan
    r.cx = float(centre_to_level0_scalar(c[0], f, scale_xy))
    r.cy = float(centre_to_level0_scalar(c[1], f, scale_xy))
    r.ok = True
    if keep_debug:
        r.debug.update(centre_xy=(float(c[0]), float(c[1])), votes_xy=np.stack([px, py], 1),
                       normals_xy=np.stack([vnx, vny], 1), inlier=inl)
    return r


def centre_to_level0_scalar(c_ds, f, scale_xy):
    """ds-pixel coordinate -> level-0 voxel coordinate (block mean of f px, then level scale)."""
    c_level = (c_ds + 0.5) * f - 0.5
    return uf_io.centre_to_level0(c_level, scale_xy)


def finalize(r, pitch_vox, p):
    """Fill residual_pitch / confidence / flag / reasons given the (global) pitch."""
    if not r.ok:
        r.flag, r.confidence = "LOW", 0.0
        return r
    reasons = list(r.reasons)
    if not (pitch_vox and np.isfinite(pitch_vox) and pitch_vox > 0):
        reasons.append("no_pitch")
        r.residual_pitch = np.nan
        res_f = 0.0
    else:
        r.residual_pitch = r.residual_vox / pitch_vox
        res_f = 1.0 / (1.0 + (r.residual_pitch / p.max_residual_pitch) ** 2)
        if r.residual_pitch > p.max_residual_pitch:
            reasons.append("high_residual")
    if r.n_inliers < p.min_votes:
        reasons.append("few_votes")
    if r.coverage_deg < p.min_coverage_deg:
        reasons.append("low_coverage")
    votes_f = min(1.0, r.n_inliers / max(p.votes_full, 1))
    cov_f = min(1.0, r.coverage_deg / max(p.coverage_full_deg, 1e-9))
    r.confidence = float(votes_f * cov_f * res_f)
    if r.confidence < p.min_confidence and not reasons:
        reasons.append("low_confidence")
    r.reasons = reasons
    r.flag = "LOW" if reasons else "OK"
    return r


# --------------------------------------------------------------------------- along z
def weighted_running_median(v, w, window):
    """Weighted median over a centred window, ignoring NaN. Returns array like v.

    Ends are padded by odd reflection about the end sample (v[-k] = 2 v[0] - v[k]) so a linear
    trend is not pulled inward by a truncated window.
    """
    n = len(v)
    h = min(max(0, window // 2), max(n - 1, 0))
    out = np.full(n, np.nan)
    if n == 0:
        return out
    k = np.arange(1, h + 1)
    vp = np.concatenate([2 * v[0] - v[k][::-1], v, 2 * v[-1] - v[n - 1 - k]])
    wp = np.concatenate([w[k][::-1], w, w[n - 1 - k]])
    for i in range(n):
        vv, ww = vp[i:i + 2 * h + 1], wp[i:i + 2 * h + 1]
        ok = np.isfinite(vv)
        if not ok.any():
            continue
        vv, ww = vv[ok], ww[ok]
        o = np.argsort(vv)
        cw = np.cumsum(ww[o])
        out[i] = vv[o][int(np.searchsorted(cw, 0.5 * cw[-1]))]
    return out


def smooth_line(z, y, x, conf, p):
    """Confidence-weighted running median, then weighted smoothing spline. Returns (ys, xs)."""
    z, conf = np.asarray(z, float), np.asarray(conf, float)
    w = np.maximum(conf, p.min_weight)
    out = []
    for v in (np.asarray(y, float), np.asarray(x, float)):
        med = weighted_running_median(v, w, p.median_window)
        ok = np.isfinite(med)
        n = int(ok.sum())
        if n == 0:
            out.append(np.full(len(z), np.nan))
        elif n == 1:
            out.append(np.full(len(z), med[ok][0]))
        else:
            k = int(min(max(p.spline_degree, 1), 5, n - 1))
            sp = UnivariateSpline(z[ok], med[ok], w=np.sqrt(w[ok]) / max(p.spline_sigma_vox, 1e-9),
                                  k=k, s=float(n), ext=3)
            out.append(sp(z))
    return out[0], out[1]


def runs(z, mask):
    """Contiguous True runs of mask -> list of (z_first, z_last, start_idx, end_idx)."""
    res, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            res.append((float(z[i]), float(z[j]), i, j))
            i = j + 1
        else:
            i += 1
    return res


# --------------------------------------------------------------------------- volume driver
def plan_slices(vol, z_start, z_stop, z_step):
    """Unique level slice indices for level-0 z in [z_start, z_stop) every z_step. Strict range check."""
    extent = vol.shape[0] * vol.scale_z
    if z_step <= 0:
        raise InputError("z step must be > 0")
    if z_start is None:
        z_start = 0.0
    if z_stop is None:
        z_stop = extent
    if z_stop <= z_start:
        raise InputError(f"z range is empty: start {z_start} >= stop {z_stop}")
    if z_start < 0 or z_stop > extent + 1e-6:
        raise InputError(f"z range [{z_start}, {z_stop}) is outside the volume, level-0 z extent is [0, {extent:g})")
    zs = np.arange(z_start, z_stop, z_step)
    idx = [uf_io.level0_to_slice_index(z, vol.scale_z) for z in zs]
    idx = sorted({min(max(i, 0), vol.shape[0] - 1) for i in idx})
    return idx


def run(vol, p, z_start=None, z_stop=None, z_step=64.0, overlay_dir=None, log=None):
    """Full pipeline. Returns (rows, summary). rows: dicts keyed by uf_io.CSV_COLUMNS."""
    idx = plan_slices(vol, z_start, z_stop, z_step)
    rng = np.random.default_rng(p.seed)
    results, imgs = [], []
    for k, zi in enumerate(idx):
        if log:
            log(f"slice {k + 1}/{len(idx)} (level index {zi})")
        res = analyse_slice(vol.read_slice(zi), p, vol.scale_xy, keep_debug=overlay_dir is not None, rng=rng)
        results.append(res)

    pitches = [r.pitch_vox for r in results if r.ok and np.isfinite(r.pitch_vox)]
    pitch = float(p.pitch_vox) if p.pitch_vox > 0 else (float(np.median(pitches)) if pitches else np.nan)
    for r in results:
        finalize(r, pitch, p)

    z = np.array([float(uf_io.centre_to_level0(i, vol.scale_z)) for i in idx])
    ry = np.array([r.cy for r in results])
    rx = np.array([r.cx for r in results])
    conf = np.array([r.confidence for r in results])
    sy, sx = smooth_line(z, ry, rx, conf, p)
    dep = np.hypot(sy - ry, sx - rx)

    rows = []
    for i, r in enumerate(results):
        rows.append(dict(z=z[i], y=sy[i], x=sx[i], confidence=r.confidence, flag=r.flag,
                         raw_y=ry[i], raw_x=rx[i], departure_vox=dep[i], n_votes=r.n_votes,
                         n_inliers=r.n_inliers, coverage_deg=r.coverage_deg,
                         residual_pitch=r.residual_pitch, reason=";".join(r.reasons)))

    if overlay_dir is not None:
        odir = Path(overlay_dir)
        odir.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(results):
            d = r.debug
            uf_io.write_overlay(odir / f"overlay_z{z[i]:08.1f}.png", d["img"], d.get("centre_xy"),
                                d.get("votes_xy"), d.get("normals_xy"), d.get("inlier"),
                                f"z={z[i]:.0f} {r.flag} conf={r.confidence:.2f}")

    valid = np.isfinite(dep)
    summary = dict(
        tool="umbilicus_finder", version=__version__, units="level-0 voxels (z, y, x)",
        volume_shape_level=list(vol.shape), scale_z=vol.scale_z, scale_xy=vol.scale_xy,
        n_slices=len(rows), n_ok=sum(r["flag"] == "OK" for r in rows),
        n_low=sum(r["flag"] == "LOW" for r in rows), pitch_vox=pitch,
        pitch_source="flag" if p.pitch_vox > 0 else ("estimated (median of slices)" if pitches else "unknown"),
        departure_vox=dict(median=float(np.median(dep[valid])) if valid.any() else None,
                           max=float(np.max(dep[valid])) if valid.any() else None,
                           threshold=p.departure_vox,
                           ranges=[dict(z_first=a, z_last=b, max_vox=float(np.nanmax(dep[s:e + 1])))
                                   for a, b, s, e in runs(z, valid & (dep > p.departure_vox))]),
        low_confidence_ranges=[dict(z_first=a, z_last=b,
                                    reasons=sorted({q for r in rows[s:e + 1] for q in r["reason"].split(";") if q}))
                               for a, b, s, e in runs(z, np.array([r["flag"] == "LOW" for r in rows]))],
        params=dataclasses.asdict(p))
    return rows, summary


# --------------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("input", help="OME-Zarr (group or 3-D array) or a directory of slice PNGs")
    ap.add_argument("--out-dir", required=True, help="output directory (created)")
    ap.add_argument("--input-type", choices=["auto", "zarr", "png"], default="auto")
    ap.add_argument("--level", type=int, default=0, help="OME-Zarr level to read")
    ap.add_argument("--xy-scale", type=float, default=None, help="level-0 voxels per in-plane voxel/pixel (overrides OME metadata; PNG default 1)")
    ap.add_argument("--z-scale", type=float, default=None, help="level-0 voxels per z step (default: same as xy)")
    ap.add_argument("--pixel-um", type=float, default=None, help="PNG pixel size (um); with --voxel-um sets --xy-scale = pixel/voxel")
    ap.add_argument("--voxel-um", type=float, default=None, help="level-0 voxel size (um)")
    ap.add_argument("--png-glob", default="*.png")
    ap.add_argument("--z-start", type=float, default=None, help="first level-0 z (default 0)")
    ap.add_argument("--z-stop", type=float, default=None, help="level-0 z, exclusive (default volume end)")
    ap.add_argument("--z-step", type=float, default=64.0, help="level-0 z step")
    ap.add_argument("--overlays", action="store_true", help="write overlay PNGs to <out-dir>/overlays")
    ap.add_argument("--export-all", action="store_true", help="villa export includes LOW points (default: OK only)")
    for f in dataclasses.fields(Params):
        kw = dict(default=f.default, help=f.metadata.get("help", ""))
        if isinstance(f.default, bool):
            ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, action="store_true", help=kw["help"] + " (off by default)")
            continue
        if "choices" in f.metadata:
            kw["choices"] = f.metadata["choices"]
        ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, type=type(f.default), **kw)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        xy = a.xy_scale
        if xy is None and a.pixel_um and a.voxel_um:
            xy = a.pixel_um / a.voxel_um
        vol = uf_io.open_volume(a.input, a.input_type, a.level, a.z_scale, xy, a.png_glob)
        out = Path(a.out_dir)
        rows, summary = run(vol, p, a.z_start, a.z_stop, a.z_step,
                            overlay_dir=out / "overlays" if a.overlays else None,
                            log=lambda m: print(m, file=sys.stderr))
        out.mkdir(parents=True, exist_ok=True)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    uf_io.write_csv(out / "umbilicus.csv", rows)
    summary["villa_points_exported"] = uf_io.write_villa_json(out / "umbilicus_villa.json", rows, a.export_all)
    uf_io.write_json(out / "umbilicus_summary.json", summary)
    if summary["villa_points_exported"] == 0:
        print("warning: no OK slice, so umbilicus_villa.json holds no control points (see 'reason' in "
              "umbilicus.csv; --export-all writes the LOW ones)", file=sys.stderr)
    print(f"{summary['n_ok']} OK / {summary['n_low']} LOW of {summary['n_slices']} slices; "
          f"pitch {summary['pitch_vox']:.1f} vox ({summary['pitch_source']}); outputs in {out}")
    if all(not np.isfinite(r["y"]) for r in rows):
        print("error: no slice produced a centre", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
