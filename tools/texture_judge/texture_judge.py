#!/usr/bin/env python3
"""texture_judge: does the papyrus fibre texture on the rendered surface stay continuous? (MIT)

Every other judge in this repository (spacing, switch finder, auditor, winding, crush map) starts from bright-peak detection along
the surface normal. This one looks at a DIFFERENT signal, the one a person checks by eye in a VC3D surface render: the fibre texture.

  render      the CT volume sampled on the tifxyz surface and at +/- k voxels along the local normal, one flat image per layer in grid
              coordinates (rows x cols), NaN where the surface is invalid or leaves the volume;
  direction   structure tensor of the surface layer at a Gaussian scale -> fibre orientation + coherence;
  continuity  per window: orientation jump to the neighbouring windows, texture presence (coherence, contrast), layer agreement;
  verdict     ON-SHEET-TEXTURED / BREAK / BLURRED / NOT JUDGED per window and per cut line.

Two render modes. `surface` needs a real 3-D volume (OME-Zarr, or a dense stack of slice PNGs) and renders the whole grid.
`section` is the fallback for SPARSE volumes (a few slice PNGs, like the real test samples): only the cut line at each slice height can
be rendered, as a straightened cross-section (offset across the sheet x arc length along the cut line). A fibre direction relative to the
sheet frame is not available there (see README, "Limits").

Exit code 0 = no BREAK and not mostly BLURRED, 1 = a BREAK or too many BLURRED windows, 2 = bad input, 4 = too little could be judged.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
from dataclasses import dataclass

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_TOOLS, "sheet_spacing_check"))
import sheet_spacing_check as ssc  # noqa: E402
from ssc_io import InputError, PngVolume, ZarrVolume, load_mesh, slice_index_for, to_px  # noqa: E402

__version__ = "0.1.0"
ON, BRK, BLR, NJ = "ON-SHEET-TEXTURED", "BREAK", "BLURRED", "NOT JUDGED"
CODE = {ON: 0, BRK: 1, BLR: 2, NJ: 3}
NAMES = {v: k for k, v in CODE.items()}
COLOUR = {ON: (60, 190, 90), BRK: (235, 40, 40), BLR: (240, 160, 30), NJ: (130, 130, 130)}


@dataclass
class Params:
    k: float = 2.0                       # layers rendered at 0, +k, -k voxels along the normal
    pixel_vox: float = 1.0               # render pixel size (voxels per pixel); must resolve the fibre period (>= 2 px per period)
    grad_sigma: float = 1.0              # Gaussian derivative scale of the structure tensor (pixels)
    symmetry: int = 2                    # 2 = classic structure tensor (orientation mod 180, differences 0-90 deg); 4 = two balanced perpendicular families (mod 90, differences 0-45)
    window: int = 32                     # window edge (render pixels)
    min_valid_fraction: float = 0.7      # a window needs this fraction of its pixels valid, else NOT JUDGED
    min_coherence: float = 0.30          # textured needs coherence >= this ...
    min_contrast: float = 0.04           # ... and contrast (std of the smoothed render, volume scaled to 0..1) >= this; BLURRED needs BOTH below
    min_agreement: float = 0.50          # textured needs correlation with the +/-k layers >= this, else BLURRED (edge of the sheet / gap)
    max_jump_deg: float = 25.0           # orientation jump (neighbouring windows, wrapped) above this counts as a break ...
    break_run: int = 2                   # ... if it is held over this many textured windows on each side
    break_gap: int = 1                   # ... allowing up to this many non-textured windows between the two sides (the window that straddles the jump)
    section_halfwidth: float = 12.0      # section mode: half height of the straightened cross-section (voxels)
    min_slices: int = 8                  # auto mode: fewer slices than this in the surface's z range -> section mode
    max_pixels: float = 80e6             # refuse to render more than this many pixels per layer
    max_block_mb: float = 3000.0         # refuse to load a bigger volume block
    max_blurred_fraction: float = 0.25   # exit code 1 if more of the judged windows than this are BLURRED
    min_judged_fraction: float = 0.30    # exit code 4 if fewer windows than this could be judged
    invalid_value: float = -1.0          # tifxyz no-data marker
    intensity_max: float = 0.0           # volume value that maps to 1.0 (0 = auto: 255 for 8-bit data, else 65535)

    def validate(self):
        if self.symmetry not in (2, 4):
            raise InputError("--symmetry must be 2 or 4")
        for n in ("k", "pixel_vox", "grad_sigma", "window", "min_valid_fraction", "section_halfwidth"):
            if not getattr(self, n) > 0:
                raise InputError(f"--{n.replace('_', '-')} must be > 0")
        if self.window < 4 or self.break_run < 1 or not 0 < self.min_valid_fraction <= 1:
            raise InputError("need --window >= 4, --break-run >= 1 and 0 < --min-valid-fraction <= 1")
        if not 0 < self.max_jump_deg < 90:
            raise InputError("--max-jump-deg must be in (0, 90)")


# --------------------------------------------------------------------------------------------------------------- volume access
def open_volume(zarr=None, zarr_level=0, png_dir=None, png_pixel_um=None, voxel_um=None, png_pattern="{z:05d}.png"):
    if zarr:
        return ZarrVolume(zarr, zarr_level)
    if png_dir:
        return PngVolume(png_dir, png_pixel_um, voxel_um, png_pattern)
    raise InputError("need --zarr or --png-dir")


def present_slices(vol, z_lo, z_hi):
    """Slice indices (volume pixels) that exist in the level-0 z range [z_lo, z_hi]."""
    sc = vol.ct_scale
    lo, hi = slice_index_for(z_lo, sc), slice_index_for(z_hi, sc)
    if hasattr(vol, "pattern"):
        return [i for i in range(max(lo, 0), hi + 1) if os.path.isfile(os.path.join(vol.dir, vol.pattern.format(z=i)))]
    n = vol.data.shape[0]
    return list(range(max(lo, 0), min(hi, n - 1) + 1))


def _slice(vol, zi):
    """One slice as float32 (y, x), by CT slice index."""
    return vol.tile(zi * vol.ct_scale, 0, 0, 10 ** 7, 10 ** 7)


class Sampler:
    """Trilinear sampling of the CT at level-0 voxel coordinates (x, y, z). NaN outside the volume or where a slice file is missing."""

    def __init__(self, vol, pts_xyz, p: Params):
        from scipy.ndimage import map_coordinates
        self._mc = map_coordinates
        self.vol, sc = vol, vol.ct_scale
        ok = np.isfinite(pts_xyz).all(axis=-1)
        if not ok.any():
            raise InputError("no valid surface points to sample")
        q = pts_xyz[ok]
        pad = 2 * max(p.k, 1.0) + 2
        z0 = max(0, int(math.floor((q[:, 2].min() - pad - (sc - 1) / 2) / sc)))
        z1 = int(math.ceil((q[:, 2].max() + pad - (sc - 1) / 2) / sc))
        have = set(present_slices(vol, z0 * sc, z1 * sc))
        if not have:
            raise InputError("the CT volume has no slice inside the surface's z range")
        z0, z1 = max(z0, min(have)), min(z1, max(have))
        first = _slice(vol, min(have))
        self.vmax = p.intensity_max or (255.0 if first.max() <= 255 else 65535.0)
        H, W = first.shape
        px = to_px(q[:, :2], sc)
        x0, x1 = max(0, int(math.floor(px[:, 0].min() - pad / sc)) - 1), min(W, int(math.ceil(px[:, 0].max() + pad / sc)) + 2)
        y0, y1 = max(0, int(math.floor(px[:, 1].min() - pad / sc)) - 1), min(H, int(math.ceil(px[:, 1].max() + pad / sc)) + 2)
        if x1 <= x0 or y1 <= y0:
            raise InputError("the surface lies outside the CT slices")
        mb = (z1 - z0 + 1) * (y1 - y0) * (x1 - x0) * 4 / 1e6
        if mb > p.max_block_mb:
            raise InputError(f"the volume block needed is {mb:.0f} MB (> --max-block-mb {p.max_block_mb:g}); render a smaller piece")
        blk = np.full((z1 - z0 + 1, y1 - y0, x1 - x0), np.nan, np.float32)
        for zi in sorted(have):
            if z0 <= zi <= z1:
                blk[zi - z0] = _slice(vol, zi)[y0:y1, x0:x1] / self.vmax
        self.blk, self.o, self.sc = blk, (z0, y0, x0), sc

    def __call__(self, pts_xyz):
        z0, y0, x0 = self.o
        sc = self.sc
        out = np.full(pts_xyz.shape[:-1], np.nan, np.float32)
        ok = np.isfinite(pts_xyz).all(axis=-1)
        if not ok.any():
            return out
        q = pts_xyz[ok]
        idx = np.stack([(q[:, 2] - (sc - 1) / 2) / sc - z0, (q[:, 1] - (sc - 1) / 2) / sc - y0, (q[:, 0] - (sc - 1) / 2) / sc - x0])
        out[ok] = self._mc(self.blk, idx, order=1, mode="constant", cval=np.nan, prefilter=False)
        return out


# --------------------------------------------------------------------------------------------------------------- the surface render
def _mesh_steps(mesh):
    """Median 3-D distance between neighbouring valid grid points along rows / along columns (voxels)."""
    P = np.stack([mesh.x, mesh.y, mesh.z], -1)
    dr = np.linalg.norm(P[1:] - P[:-1], axis=-1)
    dc = np.linalg.norm(P[:, 1:] - P[:, :-1], axis=-1)
    dr, dc = dr[np.isfinite(dr)], dc[np.isfinite(dc)]
    if dr.size == 0 or dc.size == 0:
        raise InputError(f"{mesh.name}: no two neighbouring valid grid points")
    return float(np.median(dr)), float(np.median(dc))


def _bilinear(A, rf, cf):
    """A (H, W) with NaN; sample at fractional grid coordinates rf (n,), cf (m,) -> (n, m). NaN if any of the 4 corners is NaN."""
    H, W = A.shape
    r0 = np.clip(np.floor(rf).astype(int), 0, max(H - 2, 0)); c0 = np.clip(np.floor(cf).astype(int), 0, max(W - 2, 0))
    tr = (rf - r0)[:, None]; tc = (cf - c0)[None, :]
    r1, c1 = np.minimum(r0 + 1, H - 1), np.minimum(c0 + 1, W - 1)
    a = A[np.ix_(r0, c0)]; b = A[np.ix_(r0, c1)]; c = A[np.ix_(r1, c0)]; d = A[np.ix_(r1, c1)]
    return (a * (1 - tr) * (1 - tc) + b * (1 - tr) * tc + c * tr * (1 - tc) + d * tr * tc)


def render_surface(mesh, vol, p: Params, log=None):
    """Layers {0: img, +k: img, -k: img} (NaN where invalid) plus the geometry of the pixel grid. Pixels are pixel_vox voxels apart."""
    log = log or (lambda m: None)
    sr_vox, sc_vox = _mesh_steps(mesh)
    H, W = mesh.shape
    step_r, step_c = p.pixel_vox / sr_vox, p.pixel_vox / sc_vox           # pixel size in grid units
    rf, cf = np.arange(0, H - 1 + 1e-9, step_r), np.arange(0, W - 1 + 1e-9, step_c)
    if len(rf) * len(cf) > p.max_pixels:
        raise InputError(f"the render would be {len(rf)} x {len(cf)} pixels (> --max-pixels); raise --pixel-vox")
    xyz = np.stack([_bilinear(a, rf, cf) for a in (mesh.x, mesh.y, mesh.z)], -1)
    tr = np.gradient(xyz, axis=0); tc = np.gradient(xyz, axis=1)
    nrm = np.cross(tr, tc)
    ln = np.linalg.norm(nrm, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        nrm = np.where(ln > 1e-9, nrm / ln, np.nan)
    smp = Sampler(vol, xyz, p)
    layers = {}
    for d in (0.0, float(p.k), -float(p.k)):
        log(f"sampling layer {d:+g}")
        layers[d] = smp(xyz + d * nrm)
    return dict(layers=layers, xyz=xyz, rf=rf, cf=cf, step=(step_r, step_c), voxel_step=(sr_vox, sc_vox), vmax=smp.vmax)


def cut_points(mesh, z0):
    """Where the grid crosses height z0: column, fractional row, x, y (one entry per crossing, ordered by column)."""
    z = mesh.z
    ok = mesh.valid[:-1] & mesh.valid[1:]
    with np.errstate(invalid="ignore"):
        d = z - z0
        cross = ok & ((d[:-1] <= 0) != (d[1:] <= 0))
    c, r = np.nonzero(cross.T)
    if len(c) == 0:
        return np.zeros(0, int), np.zeros(0), np.zeros((0, 2))
    t = d[r, c] / (d[r, c] - d[r + 1, c])
    xy = np.stack([mesh.x[r, c] + t * (mesh.x[r + 1, c] - mesh.x[r, c]), mesh.y[r, c] + t * (mesh.y[r + 1, c] - mesh.y[r, c])], 1)
    return c, r + t, xy


def render_sections(mesh, vol, heights, p: Params, log=None):
    """Sparse volume: one straightened cross-section per height. Returns a list of dicts with layers (NaN-padded), grid columns of each
    section column and the xy of the cut line. The section is the slice sampled at offsets -h..+h along the in-plane normal."""
    log = log or (lambda m: None)
    from scipy.ndimage import gaussian_filter1d, map_coordinates
    out = []
    sp = ssc.Params(max_gap_vox=float("inf"), invalid_value=p.invalid_value)
    for z0 in heights:
        line = ssc.cut_line(mesh, float(z0), sp)
        sec = dict(z=float(z0), layers=None, col=np.zeros(0), xy=np.zeros((0, 2)), runs=0, note=None)
        if line.n < 2:
            sec["note"] = "no cut line at this height"
            out.append(sec); continue
        zi = slice_index_for(z0, vol.ct_scale)
        try:
            if hasattr(vol, "pattern"):
                if zi not in present_slices(vol, z0, z0):
                    raise InputError(f"no slice at z={z0:g}")
            img = _slice(vol, zi)
        except InputError as e:
            sec["note"] = str(e)
            out.append(sec); continue
        vmax = p.intensity_max or (255.0 if img.max() <= 255 else 65535.0)
        img = img / vmax
        offs = np.arange(-p.section_halfwidth, p.section_halfwidth + 1e-9, p.pixel_vox)
        cols_img, cols_grid, cols_xy = [], [], []
        for run in np.unique(line.run):
            m = line.run == run
            if m.sum() < 2:
                continue
            xy, cg = line.xy[m], line.col[m].astype(float)
            seg = np.hypot(*np.diff(xy, axis=0).T)
            s = np.concatenate([[0], np.cumsum(seg)])
            if s[-1] < p.pixel_vox:
                continue
            ss = np.arange(0, s[-1] + 1e-9, p.pixel_vox)
            xs, ys, cc = (np.interp(ss, s, v) for v in (xy[:, 0], xy[:, 1], cg))
            sm = max(2.0, 0.5 * float(np.median(seg)) / p.pixel_vox)
            tx, ty = np.gradient(gaussian_filter1d(xs, sm, mode="nearest")), np.gradient(gaussian_filter1d(ys, sm, mode="nearest"))
            nn = np.hypot(tx, ty); nn[nn == 0] = 1
            nx_, ny_ = -ty / nn, tx / nn
            X = xs[None, :] + offs[:, None] * nx_[None, :]; Y = ys[None, :] + offs[:, None] * ny_[None, :]
            sc = vol.ct_scale
            sec_img = map_coordinates(img, [(Y - (sc - 1) / 2) / sc, (X - (sc - 1) / 2) / sc], order=1, mode="constant", cval=np.nan)
            cols_img.append(sec_img); cols_grid.append(cc); cols_xy.append(np.stack([xs, ys], 1))
            gap = np.full((len(offs), int(p.window)), np.nan)          # NaN gap between runs so no window straddles two pieces
            cols_img.append(gap); cols_grid.append(np.full(gap.shape[1], np.nan)); cols_xy.append(np.full((gap.shape[1], 2), np.nan))
        if not cols_img:
            sec["note"] = "cut line too short"
            out.append(sec); continue
        base = np.concatenate(cols_img, axis=1)
        sh = int(round(p.k / p.pixel_vox))
        layers = {0.0: base}
        for d, s_ in ((float(p.k), -sh), (-float(p.k), sh)):
            L = np.full_like(base, np.nan)
            if s_ > 0:
                L[s_:] = base[:-s_]
            elif s_ < 0:
                L[:s_] = base[-s_:]
            else:
                L = base.copy()
            layers[d] = L
        sec.update(layers=layers, col=np.concatenate(cols_grid), xy=np.concatenate(cols_xy), runs=len(cols_img) // 2, vmax=vmax)
        out.append(sec)
    return out


# --------------------------------------------------------------------------------------------------------------- fibre field + windows
def fibre_field(img, p: Params):
    """Per-pixel complex orientation field V (|V| = gradient energy, arg V = m * orientation) and the energy w, plus the valid mask and the
    Gaussian-smoothed image. m = p.symmetry. m = 2 is the classic structure tensor (Jxx - Jyy + 2i Jxy)."""
    from scipy.ndimage import binary_erosion, gaussian_filter
    valid = np.isfinite(img)
    if not valid.any():
        z = np.zeros(img.shape)
        return z.astype(complex), z, valid, z
    fill = np.where(valid, img, float(np.nanmean(img)))
    s = p.grad_sigma
    gy = gaussian_filter(fill, s, order=(1, 0), mode="nearest")
    gx = gaussian_filter(fill, s, order=(0, 1), mode="nearest")
    sm = gaussian_filter(fill, s, mode="nearest")
    r = max(1, int(math.ceil(3 * s)))
    good = binary_erosion(valid, structure=np.ones((2 * r + 1, 2 * r + 1), bool), border_value=1)
    z = gx + 1j * gy
    w = np.abs(z) ** 2
    m = p.symmetry
    V = z ** m / np.maximum(w, 1e-30) ** ((m - 2) / 2.0)           # |V| = w, arg V = m * gradient angle
    V = np.where(good, V, 0)
    return V, np.where(good, w, 0.0), good, np.where(good, sm, np.nan)


def angdiff_deg(a_rad, b_rad, m):
    """Difference of two m-fold orientations (radians of the *orientation*, i.e. arg V / m), wrapped to 0 .. 180/m degrees."""
    d = np.angle(np.exp(1j * m * (np.asarray(a_rad) - np.asarray(b_rad)))) / m
    return np.abs(np.degrees(d))


def window_stats(layers, p: Params):
    """Tile the render into window x window tiles and measure each. Returns dict of 2-D arrays."""
    img = layers[0.0]
    R, C = img.shape
    wr = min(p.window, R)
    wc = p.window
    nr, nc = -(-R // wr), -(-C // wc)
    V, w, good, sm = fibre_field(img, p)
    sm_l = {d: fibre_field(L, p)[3] for d, L in layers.items() if d != 0.0}
    st = {n: np.full((nr, nc), np.nan) for n in ("valid", "coherence", "orientation", "contrast", "agreement")}
    for i in range(nr):
        for j in range(nc):
            sl = (slice(i * wr, min((i + 1) * wr, R)), slice(j * wc, min((j + 1) * wc, C)))
            g = good[sl]
            st["valid"][i, j] = g.sum() / float(g.size)
            if g.sum() < 8:
                continue
            ew = w[sl].sum()
            sV = V[sl].sum()
            st["coherence"][i, j] = abs(sV) / max(ew, 1e-30)
            st["orientation"][i, j] = np.angle(sV) / p.symmetry
            a = sm[sl][g]
            st["contrast"][i, j] = float(a.std())
            cs = []
            for d, L in sm_l.items():
                b = L[sl]
                ok = g & np.isfinite(b)
                if ok.sum() >= 8:
                    x, y = sm[sl][ok], b[ok]
                    if x.std() > 1e-9 and y.std() > 1e-9:
                        cs.append(float(np.corrcoef(x, y)[0, 1]))
                    else:
                        cs.append(0.0)
            if cs:
                st["agreement"][i, j] = min(cs)
    st["wr"], st["wc"] = wr, wc
    return st


def base_verdicts(st, p: Params):
    """ON / BLURRED / NOT JUDGED per window, with a short reason (BREAK is added by find_breaks)."""
    nr, nc = st["valid"].shape
    v = np.full((nr, nc), CODE[NJ], int)
    why = np.empty((nr, nc), object)
    for i in range(nr):
        for j in range(nc):
            if st["valid"][i, j] < p.min_valid_fraction or not np.isfinite(st["coherence"][i, j]):
                why[i, j] = "too few valid pixels"
                continue
            lc, lk = st["coherence"][i, j] < p.min_coherence, st["contrast"][i, j] < p.min_contrast
            ag = st["agreement"][i, j]
            if lc and lk:
                v[i, j], why[i, j] = CODE[BLR], "low coherence and low contrast"
            elif lc or lk:
                why[i, j] = "mixed: " + ("coherence" if lc else "contrast") + " low, the other not"
            elif np.isfinite(ag) and ag < p.min_agreement:
                v[i, j], why[i, j] = CODE[BLR], f"layer agreement {ag:.2f} < {p.min_agreement:g}"
            else:
                v[i, j], why[i, j] = CODE[ON], "textured"
    return v, why


def _seq_breaks(theta, ok, p: Params):
    """Held orientation jumps along one sequence of windows. Looks at consecutive textured windows u -> u' separated by at most
    p.break_gap non-textured windows; the jump is between the mean orientation of the break_run textured windows ending at u and the
    break_run beginning at u' (each group must be contiguous). Returns [(u, u', jump_deg)], the largest jump of each flagged stretch."""
    m, N = p.symmetry, p.break_run
    idx = np.flatnonzero(ok)
    jump = []
    for t in range(len(idx) - 1):
        u, v = idx[t], idx[t + 1]
        if v - u - 1 > p.break_gap or t - N + 1 < 0 or t + N >= len(idx):
            jump.append(np.nan); continue
        L, R = idx[t - N + 1:t + 1], idx[t + 1:t + 1 + N]
        if (np.diff(L) != 1).any() or (np.diff(R) != 1).any():
            jump.append(np.nan); continue
        mean = lambda ts: np.angle(np.exp(1j * m * theta[ts]).mean()) / m           # noqa: E731
        jump.append(float(angdiff_deg(mean(L), mean(R), m)))
    jump = np.array(jump)
    flag = np.isfinite(jump) & (jump > p.max_jump_deg)
    out, t = [], 0
    while t < len(flag):
        if flag[t]:
            e = t
            while e + 1 < len(flag) and flag[e + 1]:
                e += 1
            b = t + int(np.argmax(jump[t:e + 1]))
            out.append((int(idx[b]), int(idx[b + 1]), float(jump[b])))
            t = e + 1
        else:
            t += 1
    return out


def find_breaks(st, v, p: Params):
    """Mark the BREAK windows and return the break list. A held jump between two textured windows that are neighbours marks both of them;
    when non-textured windows lie between the two sides (the window that straddles the jump) only those in-between windows are marked."""
    ok = (v == CODE[ON])
    th = st["orientation"]
    nr, nc = v.shape
    brk = []
    for i in range(nr):                                    # along columns
        for u, w_, jd in _seq_breaks(np.nan_to_num(th[i]), ok[i], p):
            brk.append(dict(axis="cols", ti=i, tj=u, tj2=w_, jump_deg=jd))
    for j in range(nc):                                    # along rows
        for u, w_, jd in _seq_breaks(np.nan_to_num(th[:, j]), ok[:, j], p):
            brk.append(dict(axis="rows", ti=u, ti2=w_, tj=j, jump_deg=jd))
    v = v.copy()
    for e in brk:
        if e["axis"] == "cols":
            lo, hi = (e["tj"] + 1, e["tj2"]) if e["tj2"] - e["tj"] > 1 else (e["tj"], e["tj2"] + 1)
            v[e["ti"], lo:hi] = CODE[BRK]
        else:
            lo, hi = (e["ti"] + 1, e["ti2"]) if e["ti2"] - e["ti"] > 1 else (e["ti"], e["ti2"] + 1)
            v[lo:hi, e["tj"]] = CODE[BRK]
    return v, brk


# --------------------------------------------------------------------------------------------------------------- driver
def _frac(v):
    n = v.size
    d = {NAMES[c]: int((v == c).sum()) for c in NAMES}
    judged = n - d[NJ]
    return dict(n_windows=int(n), counts=d, judged_fraction=judged / n if n else 0.0,
                fractions_of_judged={k: (d[k] / judged if judged else None) for k in (ON, BRK, BLR)})


def judge_surface(mesh, vol, p: Params, heights=(), log=None):
    log = log or (lambda m: None)
    R = render_surface(mesh, vol, p, log)
    st = window_stats(R["layers"], p)
    v0, why = base_verdicts(st, p)
    v, brk = find_breaks(st, v0, p)
    sr, sc_ = R["step"]
    wr, wc = st["wr"], st["wc"]
    breaks = []
    for e in brk:
        if e["axis"] == "cols":
            py, px = (e["ti"] + 0.5) * wr, (e["tj"] + 1 + e["tj2"]) / 2.0 * wc
        else:
            py, px = (e["ti"] + 1 + e["ti2"]) / 2.0 * wr, (e["tj"] + 0.5) * wc
        py, px = int(min(py, R["xyz"].shape[0] - 1)), int(min(px, R["xyz"].shape[1] - 1))
        q = R["xyz"][py, px]
        breaks.append(dict(axis=e["axis"], grid_row=float(R["rf"][py]), grid_col=float(R["cf"][px]), jump_deg=e["jump_deg"],
                           window=[int(e["ti"]), int(e["tj"])], window_end=[int(e.get("ti2", e["ti"])), int(e.get("tj2", e["tj"]))], xyz=[None if not np.isfinite(t) else float(t) for t in q]))
    cuts = []
    for z0 in heights:
        c, rowf, xy = cut_points(mesh, float(z0))
        ti = np.minimum((rowf / sr / wr).astype(int), v.shape[0] - 1)
        tj = np.minimum((c / sc_ / wc).astype(int), v.shape[1] - 1)
        codes = v[ti, tj] if len(c) else np.zeros(0, int)
        here = []                                           # breaks whose window the cut line passes through (centre column of each)
        for e, b in zip(brk, breaks):
            if e["axis"] == "cols":
                hit = (ti == e["ti"]) & (tj >= (e["tj"] + 1 if e["tj2"] - e["tj"] > 1 else e["tj"])) & (tj <= (e["tj2"] - 1 if e["tj2"] - e["tj"] > 1 else e["tj2"]))
            else:
                hit = (tj == e["tj"]) & (ti >= (e["ti"] + 1 if e["ti2"] - e["ti"] > 1 else e["ti"])) & (ti <= (e["ti2"] - 1 if e["ti2"] - e["ti"] > 1 else e["ti2"]))
            if len(c) and hit.any():
                here.append(dict(grid_col=b["grid_col"], jump_deg=b["jump_deg"]))
        cuts.append(dict(z=float(z0), n_points=int(len(c)), col=[int(t) for t in c], row=[float(t) for t in rowf],
                         verdict=[NAMES[int(t)] for t in codes], breaks=here,
                         counts={NAMES[k]: int((codes == k).sum()) for k in NAMES}))
    rep = dict(mode="surface", grid=dict(shape=list(mesh.shape), pixel_vox=p.pixel_vox, voxel_step_row_col=list(R["voxel_step"]),
                                         render_shape=list(R["layers"][0.0].shape), window_px=[wr, wc],
                                         window_grid_rows_cols=[wr * sr, wc * sc_]),
               windows=_frac(v), breaks=breaks, cut_lines=cuts)
    rep["_internal"] = dict(R=R, st=st, v=v, v0=v0, why=why)
    return rep


def judge_sections(mesh, vol, heights, p: Params, log=None):
    secs = render_sections(mesh, vol, heights, p, log)
    allv, outs, breaks, cuts = [], [], [], []
    for s in secs:
        if s["layers"] is None:
            cuts.append(dict(z=s["z"], n_points=0, col=[], verdict=[], breaks=[], counts={k: 0 for k in CODE}, note=s["note"]))
            outs.append(None)
            continue
        st = window_stats(s["layers"], p)
        v0, why = base_verdicts(st, p)
        v, brk = find_breaks(st, v0, p)
        allv.append(v)
        wc = st["wc"]
        for e in brk:
            px = int(min((e["tj"] + 1 + e["tj2"]) / 2.0 * wc, len(s["col"]) - 1)) if e["axis"] == "cols" else int(min((e["tj"] + 0.5) * wc, len(s["col"]) - 1))
            if np.isfinite(s["col"][px]):
                breaks.append(dict(axis=e["axis"], z=s["z"], grid_col=float(s["col"][px]), jump_deg=e["jump_deg"],
                                   xyz=[float(s["xy"][px, 0]), float(s["xy"][px, 1]), s["z"]]))
        # cut-line verdicts: one per grid column that has a section column
        col_verdict = {}
        for px, g in enumerate(s["col"]):
            if np.isfinite(g):
                j = min(px // wc, v.shape[1] - 1)
                col_verdict.setdefault(int(round(g)), NAMES[int(v[min(v.shape[0] - 1, 0), j])])
        cols = sorted(col_verdict)
        codes = np.array([CODE[col_verdict[c]] for c in cols], int)
        cuts.append(dict(z=s["z"], n_points=len(cols), col=cols, verdict=[col_verdict[c] for c in cols],
                         breaks=[dict(grid_col=b["grid_col"], jump_deg=b["jump_deg"]) for b in breaks if b["z"] == s["z"]],
                         counts={NAMES[k]: int((codes == k).sum()) for k in NAMES}, runs=s["runs"]))
        outs.append(dict(sec=s, st=st, v=v, why=why))
    V = np.concatenate([a.ravel() for a in allv]) if allv else np.zeros(0, int)
    rep = dict(mode="section", windows=_frac(V) if V.size else dict(n_windows=0, counts={k: 0 for k in CODE}, judged_fraction=0.0,
                                                                    fractions_of_judged={k: None for k in (ON, BRK, BLR)}),
               breaks=breaks, cut_lines=cuts)
    rep["_internal"] = dict(outs=outs)
    return rep


def choose_mode(mesh, vol, p: Params, mode):
    if mode != "auto":
        return mode
    n = len(present_slices(vol, float(np.nanmin(mesh.z[mesh.valid])), float(np.nanmax(mesh.z[mesh.valid]))))
    return "surface" if n >= p.min_slices else "section"


def run(mesh, vol, p: Params, heights=(), mode="auto", log=None):
    p.validate()
    m = choose_mode(mesh, vol, p, mode)
    if m == "section":
        if not heights:
            raise InputError("this volume is sparse (too few slices for a surface render): section mode needs --heights")
        rep = judge_sections(mesh, vol, list(heights), p, log)
    else:
        rep = judge_surface(mesh, vol, p, list(heights), log)
    w = rep["windows"]
    fo = w["fractions_of_judged"]
    if w["judged_fraction"] < p.min_judged_fraction:
        rep["exit_code"], rep["verdict"] = 4, NJ
    elif w["counts"][BRK] > 0 or (fo[BLR] or 0) > p.max_blurred_fraction:
        rep["exit_code"], rep["verdict"] = 1, "FAIL"
    else:
        rep["exit_code"], rep["verdict"] = 0, "PASS"
    return rep


# --------------------------------------------------------------------------------------------------------------- pictures
def _to_u8(img, lo=None, hi=None):
    a = np.asarray(img, float)
    ok = np.isfinite(a)
    if not ok.any():
        return np.zeros(a.shape, np.uint8)
    lo = np.percentile(a[ok], 1) if lo is None else lo
    hi = np.percentile(a[ok], 99) if hi is None else hi
    u = np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1) * 255
    return np.where(ok, u, 0).astype(np.uint8)


def _save(arr, path, max_px=2048):
    from PIL import Image
    im = Image.fromarray(arr)
    if max(im.size) > max_px:
        f = max_px / max(im.size)
        im = im.resize((max(1, int(im.size[0] * f)), max(1, int(im.size[1] * f))), Image.BILINEAR)
    im.save(path, optimize=True)


def overlay_image(img, v, st, breaks_px, cut_px=(), lo=None, hi=None):
    """Grey render with a window grid coloured by verdict, BREAKs as thick red lines, cut lines in cyan. Returns RGB uint8."""
    g = _to_u8(img, lo, hi)
    rgb = np.stack([g, g, g], -1).astype(np.float32)
    wr, wc = st["wr"], st["wc"]
    R, C = g.shape
    for i in range(v.shape[0]):
        for j in range(v.shape[1]):
            y0, y1, x0, x1 = i * wr, min((i + 1) * wr, R), j * wc, min((j + 1) * wc, C)
            col = np.array(COLOUR[NAMES[int(v[i, j])]], np.float32)
            rgb[y0:y1, x0:x1] = 0.8 * rgb[y0:y1, x0:x1] + 0.2 * col
            rgb[y0:y1, x0:x0 + 1] = col; rgb[y0:y0 + 1, x0:x1] = col
    for (y, x, ax) in breaks_px:
        y, x = int(y), int(x)
        if ax == "cols":
            rgb[max(0, y - wr // 2):min(R, y + wr // 2), max(0, x - 1):x + 2] = COLOUR[BRK]
        else:
            rgb[max(0, y - 1):y + 2, max(0, x - wc // 2):min(C, x + wc // 2)] = COLOUR[BRK]
    for (y, x) in cut_px:
        if 0 <= y < R and 0 <= x < C:
            rgb[int(y), int(x)] = (0, 255, 255)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def orientation_image(img, p: Params):
    """Hue = fibre orientation, brightness = coherence (per pixel, smoothed at 3 x grad_sigma)."""
    from scipy.ndimage import gaussian_filter
    import colorsys
    V, w, good, _ = fibre_field(img, p)
    s = 3 * p.grad_sigma
    Vs = gaussian_filter(V.real, s) + 1j * gaussian_filter(V.imag, s)
    ws = gaussian_filter(w, s)
    coh = np.where(good, np.abs(Vs) / np.maximum(ws, 1e-30), 0)
    hue = (np.angle(Vs) / (2 * np.pi)) % 1.0
    lut = np.array([colorsys.hsv_to_rgb(h, 1, 1) for h in np.linspace(0, 1, 256)])
    rgb = lut[np.minimum((hue * 256).astype(int), 255)] * np.clip(coh, 0, 1)[..., None]
    return (rgb * 255).astype(np.uint8)


def write_pictures(rep, p: Params, out_dir, heights):
    os.makedirs(out_dir, exist_ok=True)
    files = []
    I = rep["_internal"]
    if rep["mode"] == "surface":
        R, st, v = I["R"], I["st"], I["v"]
        base = R["layers"][0.0]
        ok = np.isfinite(base)
        lo, hi = (np.percentile(base[ok], 1), np.percentile(base[ok], 99)) if ok.any() else (0, 1)
        for d, L in R["layers"].items():
            f = os.path.join(out_dir, f"surface_{'k' if d else ''}{d:+g}.png" if d else "surface_k+0.png")
            _save(_to_u8(L, lo, hi), f); files.append(f)
        f = os.path.join(out_dir, "fibre_orientation.png"); _save(orientation_image(base, p), f); files.append(f)
        sr, sc_ = R["step"]
        bpx = [(b["grid_row"] / sr, b["grid_col"] / sc_, b["axis"]) for b in rep["breaks"]]
        cpx = [(r / sr, c / sc_) for cl in rep["cut_lines"] for r, c in zip(cl["row"], cl["col"])]
        f = os.path.join(out_dir, "overlay.png"); _save(overlay_image(base, v, st, bpx, cpx, lo, hi), f); files.append(f)
    else:
        for o in I["outs"]:
            if o is None:
                continue
            s, st, v = o["sec"], o["st"], o["v"]
            z = int(s["z"])
            base = s["layers"][0.0]
            f = os.path.join(out_dir, f"section_z{z}.png"); _save(_to_u8(base), f, 8192); files.append(f)
            f = os.path.join(out_dir, f"section_z{z}_overlay.png")
            wc = st["wc"]
            bpx = []
            for b in rep["breaks"]:
                if b["z"] == s["z"]:
                    px = int(np.nanargmin(np.abs(s["col"] - b["grid_col"])))
                    bpx.append((base.shape[0] / 2, px, "cols"))
            _save(overlay_image(base, v, st, bpx), f, 8192); files.append(f)
    return files


# --------------------------------------------------------------------------------------------------------------- CLI
def text_report(rep, inputs):
    w = rep["windows"]
    L = [f"texture_judge {__version__}   mesh: {inputs['mesh']}   CT: {inputs['ct']}   mode: {rep['mode']}",
         f"verdict: {rep['verdict']}   windows: {w['n_windows']}   judged {100 * w['judged_fraction']:.0f}%"]
    for k in (ON, BRK, BLR, NJ):
        n = w["counts"][k]
        L.append(f"  {k:<18} {n:>6}  ({100 * n / w['n_windows']:.0f}% of all)" if w["n_windows"] else f"  {k:<18} {n:>6}")
    for b in rep["breaks"]:
        loc = f"row {b['grid_row']:.1f}, col {b['grid_col']:.1f}" if "grid_row" in b else f"z={b['z']:g}, col {b['grid_col']:.1f}"
        L.append(f"  BREAK ({b['axis']}) at grid {loc}, voxel xyz {b['xyz']}: orientation jump {b['jump_deg']:.0f} deg")
    for c in rep["cut_lines"]:
        cn = c["counts"]
        L.append(f"  cut line z={c['z']:g}: {c['n_points']} pts   " + "  ".join(f"{k} {cn[k]}" for k in (ON, BRK, BLR, NJ)) + (f"   ({c['note']})" if c.get("note") else ""))
    return "\n".join(L) + "\n"


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("mesh", help="tifxyz folder of the trace")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr", help="OME-Zarr volume"); g.add_argument("--png-dir", help="directory of slice PNGs")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--png-pixel-um", type=float); ap.add_argument("--png-pattern", default="{z:05d}.png")
    ap.add_argument("--voxel-size-um", type=float, help="mesh voxel size (PNG input)")
    ap.add_argument("--heights", help="comma-separated cut-line heights (voxels); required for a sparse volume")
    ap.add_argument("--mode", choices=["auto", "surface", "section"], default="auto",
                    help="surface = render the whole grid (dense volume); section = straightened cross-section per height (sparse volume)")
    ap.add_argument("--transpose", action="store_true", help="grids have z varying along columns")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--json", help="report path (default <out-dir>/texture_judge.json)")
    d = Params()
    for f in dataclasses.fields(Params):
        ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, type=type(getattr(d, f.name)), default=getattr(d, f.name))
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        p.validate()
        mesh = load_mesh(a.mesh, p.invalid_value, a.transpose)
        vox = a.voxel_size_um or mesh.voxel_um
        vol = open_volume(a.zarr, a.zarr_level, a.png_dir, a.png_pixel_um, vox, a.png_pattern)
        try:
            heights = [float(h) for h in a.heights.split(",") if h.strip()] if a.heights else []
        except ValueError as e:
            raise InputError(f"--heights must be comma-separated numbers: {e}") from e
        rep = run(mesh, vol, p, heights, a.mode, log=lambda m: print(m, file=sys.stderr))
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    os.makedirs(a.out_dir, exist_ok=True)
    files = [] if a.no_png else write_pictures(rep, p, a.out_dir, heights)
    rep.pop("_internal")
    inputs = dict(mesh=a.mesh, ct=a.zarr or a.png_dir, heights=heights)
    rep.update(tool_version=__version__, inputs=inputs, params=dataclasses.asdict(p), files=[os.path.relpath(f, a.out_dir) for f in files])
    with open(a.json or os.path.join(a.out_dir, "texture_judge.json"), "w") as fh:
        json.dump(rep, fh, indent=1, default=float)
    txt = text_report(rep, inputs)
    with open(os.path.join(a.out_dir, "texture_judge.txt"), "w") as fh:
        fh.write(txt)
    print(txt, end="")
    return rep["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
