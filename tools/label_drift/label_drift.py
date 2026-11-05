#!/usr/bin/env python3
"""label_drift: how far do labels drawn on a flattened surface sit from the true papyrus?  (MIT)

Given a tifxyz surface, a CT volume and a 2-D label image in the surface grid (an ink mask, or any label), measure at
every labelled pixel (= grid node): (1) the signed distance from the surface point to the nearest bright-sheet peak along
the local normal, in voxels and in local pitches; (2) whether the point is on-sheet (the same test as sheet_spacing_check);
(3) the local sheet thickness. See README.md for the method. Every constant is a field of `Params` and a CLI flag.

Reused, not copied: tools/common/local_pitch.py (profile sampling, detrending, peak finding, local pitch) and
tools/sheet_spacing_check (mesh / volume readers, Otsu threshold, on-sheet mask, cut line, parameter defaults).
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import shutil
import sys
from dataclasses import dataclass, asdict

import numpy as np
from scipy import ndimage as ndi
from scipy.ndimage import maximum_filter
from scipy.signal import peak_widths

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (os.path.join(_HERE, "..", "sheet_spacing_check"), os.path.join(_HERE, "..", "common")):
    _d = os.path.normpath(_d)
    if _d not in sys.path:
        sys.path.insert(0, _d)
import local_pitch as lpm  # noqa: E402  tools/common/local_pitch.py
import sheet_spacing_check as ssc  # noqa: E402
from ssc_io import (InputError, PngVolume, ZarrVolume, load_mesh, mesh_voxel_um,  # noqa: E402
                    slice_index_for, to_px)

__version__ = "0.1.0"

VERDICTS = ("OK", "SHIFTED", "OFF-SHEET", "MIXED", "NO-DATA")
FWHM_PER_SIGMA = 2.3548200450309493
_SSC_DEFAULTS = ssc.Params()


@dataclass
class Params:
    # ---- which pixels
    label_min_value: float = 0.0        # a pixel is labelled if its value is > this
    connectivity: int = 8               # components: 4 or 8 connected
    min_component_px: int = 1           # components with fewer labelled pixels are ignored (counted in the report)
    # ---- geometry
    max_nz2: float = 0.5                # a node whose unit normal has nz^2 above this is not measured (in-plane normals need a steep surface)
    z_snap_vox: float = 0.0             # use the nearest slice up to this far (z, voxels) from the node when its own slice is missing
    invalid_value: float = _SSC_DEFAULTS.invalid_value   # tifxyz "no data" marker
    # ---- profile / peaks (defaults = sheet_spacing_check's)
    profile_halflen_vox: float = _SSC_DEFAULTS.profile_halflen_vox   # normal profile half-length (voxels): the peak search range
    profile_step_px: float = _SSC_DEFAULTS.profile_step_px
    profile_sigma_px: float = _SSC_DEFAULTS.profile_sigma_px
    peak_prominence_frac: float = _SSC_DEFAULTS.peak_prominence_frac  # sheet peaks: min prominence / profile range
    peak_min_distance_px: float = _SSC_DEFAULTS.peak_min_distance_px
    thickness_raw: bool = False         # report the FWHM of the smoothed profile as is (default: remove the profile smoothing in quadrature)
    # ---- local pitch (tools/common/local_pitch.py, defaults = sheet_spacing_check's)
    min_peaks: int = _SSC_DEFAULTS.min_peaks
    pitch_prominence_frac: float = _SSC_DEFAULTS.pitch_prominence_frac
    pitch_window_pitches: float = _SSC_DEFAULTS.pitch_window_pitches
    pitch_cv_max: float = _SSC_DEFAULTS.pitch_cv_max
    pitch_ac_full: float = _SSC_DEFAULTS.pitch_ac_full
    min_pitch_confidence: float = 0.0   # nodes below this confidence use the component's median pitch
    # ---- on-sheet (same test as sheet_spacing_check)
    onsheet_radius_px: float = _SSC_DEFAULTS.onsheet_radius_px
    otsu_bins: int = _SSC_DEFAULTS.otsu_bins
    tile_pad_px: int = _SSC_DEFAULTS.tile_pad_px
    # ---- verdicts (all in local pitches unless noted)
    ok_pitch: float = 0.10              # |median drift| up to this = centred
    consistent_spread_pitch: float = 0.15   # robust sigma (1.4826 MAD) of the drift up to this = a consistent offset
    max_shift_pitch: float = 0.40       # a consistent offset up to this is SHIFTED; beyond it the label sits in the gap
    mixed_off_frac: float = 0.20        # OK needs an off-sheet fraction up to this
    off_sheet_frac: float = 0.50        # OFF-SHEET from this off-sheet fraction
    min_measured: int = 5               # fewer measured nodes in a component = NO-DATA
    # ---- corrected surface / picture
    correct_max_pitch: float = 0.50     # --write-corrected leaves nodes alone whose |drift| exceeds this many pitches
    png_range_pitch: float = 0.50       # drift map PNG: colour scale +-this many pitches
    png_scale: int = 1                  # drift map PNG: integer magnification

    def validate(self):
        pos = ("profile_halflen_vox", "profile_step_px", "profile_sigma_px", "peak_min_distance_px", "pitch_window_pitches",
               "pitch_cv_max", "pitch_ac_full", "onsheet_radius_px", "png_range_pitch", "consistent_spread_pitch",
               "correct_max_pitch")
        for k in pos:
            if not getattr(self, k) > 0:
                raise InputError(f"--{k.replace('_', '-')} must be > 0")
        if self.connectivity not in (4, 8):
            raise InputError("--connectivity must be 4 or 8")
        if not 0 <= self.peak_prominence_frac < 1 or not 0 <= self.pitch_prominence_frac < 1:
            raise InputError("prominence fractions must be in [0, 1)")
        if self.ok_pitch < 0 or self.max_shift_pitch < self.ok_pitch:
            raise InputError("need 0 <= --ok-pitch <= --max-shift-pitch")
        if not (0 <= self.mixed_off_frac <= 1 and 0 <= self.off_sheet_frac <= 1):
            raise InputError("off-sheet fractions must be in [0, 1]")
        if self.min_measured < 1 or self.min_component_px < 1 or self.png_scale < 1 or self.min_peaks < 2:
            raise InputError("--min-measured, --min-component-px, --png-scale must be >= 1 and --min-peaks >= 2")
        if self.z_snap_vox < 0 or not 0 <= self.min_pitch_confidence <= 1 or self.max_nz2 <= 0 or self.max_nz2 > 1:
            raise InputError("--z-snap-vox must be >= 0, --min-pitch-confidence in [0, 1], --max-nz2 in (0, 1]")
        return self


def ssc_params(p: Params) -> "ssc.Params":
    """The sheet_spacing_check Params carrying this tool's profile / pitch / on-sheet settings."""
    keys = ("profile_halflen_vox", "profile_step_px", "profile_sigma_px", "peak_min_distance_px", "min_peaks",
            "pitch_prominence_frac", "pitch_window_pitches", "pitch_cv_max", "pitch_ac_full", "onsheet_radius_px",
            "otsu_bins", "tile_pad_px", "invalid_value")
    return dataclasses.replace(_SSC_DEFAULTS, **{k: getattr(p, k) for k in keys})


# ------------------------------------------------------------------ inputs
def load_label(path):
    """Label image -> 2-D float array (NaN where undefined). PNG / TIFF / NPY."""
    path = str(path)
    if not os.path.isfile(path):
        raise InputError(f"label file does not exist: {path}")
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".npy":
            a = np.load(path, allow_pickle=False)
        elif ext in (".tif", ".tiff"):
            import tifffile
            a = tifffile.imread(path)
        else:
            from PIL import Image
            a = np.asarray(Image.open(path))
    except Exception as e:  # noqa: BLE001
        raise InputError(f"cannot read label {path}: {e}") from e
    a = np.asarray(a)
    if a.ndim == 3 and a.shape[-1] in (2, 3, 4):
        a = a[..., :3].max(axis=-1) if a.shape[-1] >= 3 else a[..., 0]
    if a.ndim != 2:
        raise InputError(f"label must be a 2-D image, got shape {a.shape}")
    if a.dtype.kind not in "biuf":
        raise InputError(f"label has unsupported dtype {a.dtype}")
    return a.astype(np.float64)


def surface_normals(mesh):
    """Unit normals (H, W, 3) = d/drow x d/dcol of the grid (central differences, one-sided at holes and edges; NaN where
    undefined). The sign convention of the whole tool: positive drift = the peak lies along +normal."""
    P = np.stack([mesh.x, mesh.y, mesh.z], axis=-1)

    def diff(axis):
        P0 = np.moveaxis(P, axis, 0)
        fwd = np.full_like(P0, np.nan)
        bwd = np.full_like(P0, np.nan)
        fwd[:-1] = P0[1:] - P0[:-1]
        bwd[1:] = P0[1:] - P0[:-1]
        both = np.isfinite(fwd) & np.isfinite(bwd)
        d = np.where(both, 0.5 * (fwd + bwd), np.where(np.isfinite(fwd), fwd, bwd))
        return np.moveaxis(d, 0, axis)

    with np.errstate(all="ignore"):
        n = np.cross(diff(0), diff(1))
        n = n / np.linalg.norm(n, axis=-1, keepdims=True)
    return n


# ------------------------------------------------------------------ measurement
def _refine(pr, k, step):
    """Sub-sample peak offset (voxels) by a 3-point parabola."""
    if 0 < k < len(pr) - 1:
        a, b, c = pr[k - 1], pr[k], pr[k + 1]
        den = a - 2 * b + c
        if den < 0:
            return float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) * step
    return 0.0


def measure_profiles(s_vox, prof, p: Params, ct_scale):
    """Per profile: drift (signed distance to the nearest peak, NaN if none), thickness (FWHM of that peak), local pitch,
    pitch confidence. The trace point is at s = 0, the positive direction is the normal."""
    n = len(prof)
    step = float(s_vox[1] - s_vox[0])
    pp = ssc.pitch_params(ssc_params(p))
    pk_par = dataclasses.replace(pp, prominence_frac=p.peak_prominence_frac)
    lp = lpm.estimate_profiles(s_vox, prof, pp)
    drift, thick = np.full(n, np.nan), np.full(n, np.nan)
    blur = FWHM_PER_SIGMA * p.profile_sigma_px * ct_scale
    for i in range(n):
        pr = prof[i]
        if not np.all(np.isfinite(pr)):
            continue
        pr = lpm._detrend(pr, step, pp)
        pk = lpm._peaks(pr, pk_par)
        if len(pk) == 0:
            continue
        pos = s_vox[pk]
        j = int(np.argmin(np.abs(pos)))
        drift[i] = pos[j] + _refine(pr, int(pk[j]), step)
        w = float(peak_widths(pr, [int(pk[j])], rel_height=0.5)[0][0]) * step
        thick[i] = w if p.thickness_raw else float(np.sqrt(max(w * w - blur * blur, 0.0)))
    return drift, thick, lp.pitch, lp.confidence


def _tile_for(vol, mesh, z_rep, pts_vox, p: Params, sp: "ssc.Params"):
    """CT tile of one slice around the mesh cut line and the labelled points of that slice (so that the Otsu threshold
    is taken over the same kind of region as in sheet_spacing_check)."""
    sc = vol.ct_scale
    H, W = vol.probe_shape(z_rep)
    line = ssc.cut_line(mesh, z_rep + 0.5 * (sc - 1), sp)
    allp = to_px(np.concatenate([pts_vox, line.xy]) if line.n else pts_vox, sc)
    pad = int(np.ceil(p.profile_halflen_vox / sc + p.onsheet_radius_px + 2)) + p.tile_pad_px
    x0, y0 = max(0, int(np.floor(allp[:, 0].min())) - pad), max(0, int(np.floor(allp[:, 1].min())) - pad)
    x1, y1 = min(W, int(np.ceil(allp[:, 0].max())) + pad + 1), min(H, int(np.ceil(allp[:, 1].max())) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        raise InputError(f"labelled points at z={z_rep} fall outside the CT slice ({W}x{H} px)")
    return vol.tile(z_rep, x0, y0, x1, y1), (x0, y0)


def analyse(mesh, label, vol, p: Params):
    """Measure every labelled node. Returns a dict of (H, W) arrays and the component table."""
    p.validate()
    if label.shape != mesh.shape:
        raise InputError(f"label shape {label.shape} != surface grid shape {mesh.shape} (rows, cols); "
                         f"the label must be drawn in the grid of this surface (try --transpose if the grid has z along columns)")
    lab = np.nan_to_num(label, nan=-np.inf) > p.label_min_value
    if not lab.any():
        raise InputError("the label has no labelled pixels (nothing is > --label-min-value)")
    H, W = mesh.shape
    struct = ndi.generate_binary_structure(2, 1 if p.connectivity == 4 else 2)
    comp, ncomp = ndi.label(lab, structure=struct)
    sizes = np.bincount(comp.ravel(), minlength=ncomp + 1)
    small = sizes < p.min_component_px
    small[0] = False
    keep_ids = np.flatnonzero(~small[1:]) + 1
    comp = np.where(small[comp], 0, comp)
    if len(keep_ids) == 0:
        raise InputError(f"all {ncomp} label components are smaller than --min-component-px {p.min_component_px}")
    remap = np.zeros(ncomp + 1, np.int32)
    remap[keep_ids] = np.arange(1, len(keep_ids) + 1)
    comp = remap[comp]
    lab = comp > 0

    nrm3 = surface_normals(mesh)
    nz2 = nrm3[..., 2] ** 2
    with np.errstate(all="ignore"):
        hn = np.hypot(nrm3[..., 0], nrm3[..., 1])
        n2 = np.stack([nrm3[..., 0] / hn, nrm3[..., 1] / hn], axis=-1)
    can = lab & mesh.valid & np.isfinite(n2[..., 0]) & (nz2 <= p.max_nz2)

    nan = lambda: np.full((H, W), np.nan, np.float64)  # noqa: E731
    drift, thick, pitch, conf = nan(), nan(), nan(), nan()
    onsheet = np.full((H, W), -1, np.int8)             # -1 not measured, 0 off, 1 on
    slice_used = np.full((H, W), -1, np.int64)

    sp, sc = ssc_params(p), vol.ct_scale
    rr, cc = np.nonzero(can)
    if len(rr):
        key = np.array([slice_index_for(z, sc) for z in mesh.z[rr, cc]])
        for k in np.unique(key):
            sel = key == k
            tile = origin = z_used = None
            pts = np.stack([mesh.x[rr[sel], cc[sel]], mesh.y[rr[sel], cc[sel]]], axis=1)
            for dk in [0] + [s * j for j in range(1, int(p.z_snap_vox // sc) + 1) for s in (1, -1)]:
                try:
                    tile, origin = _tile_for(vol, mesh, (int(k) + dk) * sc, pts, p, sp)
                    z_used = int(k) + dk
                    break
                except InputError:
                    continue                                 # this slice is not available: try the next nearest
            if tile is None:
                continue                                     # these nodes stay 'not measured'
            r_, c_ = rr[sel], cc[sel]
            slice_used[r_, c_] = z_used
            thr = ssc.otsu_threshold(tile, p.otsu_bins)
            onmask = maximum_filter(tile, footprint=ssc._disk(p.onsheet_radius_px), mode="nearest") > thr
            xy = np.stack([mesh.x[r_, c_], mesh.y[r_, c_]], axis=1)
            xy_px = to_px(xy, sc)
            onsheet[r_, c_] = ssc._lookup(onmask, xy_px, origin).astype(np.int8)
            for a in range(0, len(r_), 2048):
                b = slice(a, a + 2048)
                s_vox, prof = lpm.sample_profiles(tile, origin, xy_px[b], n2[r_[b], c_[b]], sc,
                                                  ssc.pitch_params(sp))
                d, t, pi, cf = measure_profiles(s_vox, prof, p, sc)
                drift[r_[b], c_[b]], thick[r_[b], c_[b]] = d, t
                pitch[r_[b], c_[b]], conf[r_[b], c_[b]] = pi, cf

    if len(rr) and not (slice_used >= 0).any():
        raise InputError("no CT slice could be read for any labelled node (does the volume cover the surface? "
                         "for sparse slices see --z-snap-vox)")
    measured = np.isfinite(drift)
    onsheet[~measured] = -1
    pitch_ok = np.isfinite(pitch) & (conf >= p.min_pitch_confidence)
    pitch_used = np.where(pitch_ok, pitch, np.nan)
    glob = float(np.nanmedian(pitch_used[measured])) if (measured & pitch_ok).any() else float("nan")
    for cid in range(1, len(keep_ids) + 1):
        m = measured & (comp == cid)
        if m.any():
            cm = np.nanmedian(pitch_used[m]) if (m & pitch_ok).any() else glob
            pitch_used[m & ~pitch_ok] = cm
    with np.errstate(invalid="ignore"):
        drift_pitch = drift / pitch_used

    table = [component_row(cid, comp, measured, drift, drift_pitch, pitch_used, onsheet, thick, mesh.valid, p)
             for cid in range(1, len(keep_ids) + 1)]
    out = dict(drift_vox=drift, drift_pitch=drift_pitch, pitch_vox=pitch_used, pitch_confidence=conf, thickness_vox=thick,
               onsheet=onsheet, component=comp.astype(np.int32), measured=measured, normals=n2, slice_index=slice_used)
    return out, table, dict(n_components=len(keep_ids), n_components_dropped_small=int(small.sum()),
                            n_labelled=int(lab.sum()), n_measured=int(measured.sum()),
                            n_labelled_invalid=int((lab & ~mesh.valid).sum()),
                            n_labelled_tilted=int((lab & mesh.valid & ~(nz2 <= p.max_nz2)).sum()),
                            n_labelled_no_slice=int((can & (slice_used < 0)).sum()),
                            n_labelled_no_peak=int((can & (slice_used >= 0) & ~measured).sum()),
                            global_pitch_vox=_num(glob))


def _num(v):
    v = float(v)
    return v if np.isfinite(v) else None


def robust_sigma(x):
    x = np.asarray(x, float)
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else float("nan")


def verdict_for(n_measured, med, spread, off_frac, p: Params):
    if n_measured < p.min_measured or not np.isfinite(med):
        return "NO-DATA"
    consistent = spread <= p.consistent_spread_pitch
    if consistent and abs(med) <= p.ok_pitch and off_frac <= p.mixed_off_frac:
        return "OK"
    if consistent and p.ok_pitch < abs(med) <= p.max_shift_pitch:
        return "SHIFTED"
    if off_frac >= p.off_sheet_frac or abs(med) > p.max_shift_pitch:
        return "OFF-SHEET"
    return "MIXED"


def component_row(cid, comp, measured, drift, drift_pitch, pitch, onsheet, thick, valid, p: Params):
    mine = comp == cid
    m = mine & measured
    rows, cols = np.nonzero(mine)
    n = int(m.sum())
    row = dict(component=cid, n_pixels=int(mine.sum()), n_valid=int((mine & valid).sum()), n_measured=n,
               row_min=int(rows.min()), row_max=int(rows.max()), col_min=int(cols.min()), col_max=int(cols.max()))
    if n == 0:
        row.update(mean_drift_vox=None, median_drift_vox=None, max_abs_drift_vox=None, mean_drift_pitch=None,
                   median_drift_pitch=None, max_abs_drift_pitch=None, spread_pitch=None, off_sheet_fraction=None,
                   mean_thickness_vox=None, median_pitch_vox=None, recommended_offset_vox=None,
                   recommended_offset_pitch=None, verdict="NO-DATA")
        return row
    d, dp = drift[m], drift_pitch[m]
    dpf = dp[np.isfinite(dp)]
    med_p = float(np.median(dpf)) if len(dpf) else float("nan")
    spread = robust_sigma(dpf)
    off = float(np.mean(onsheet[m] == 0))
    row.update(mean_drift_vox=_num(d.mean()), median_drift_vox=_num(np.median(d)), max_abs_drift_vox=_num(np.abs(d).max()),
               mean_drift_pitch=_num(dpf.mean()) if len(dpf) else None, median_drift_pitch=_num(med_p),
               max_abs_drift_pitch=_num(np.abs(dpf).max()) if len(dpf) else None, spread_pitch=_num(spread),
               off_sheet_fraction=off, mean_thickness_vox=_num(np.nanmean(thick[m])) if np.isfinite(thick[m]).any() else None,
               median_pitch_vox=_num(np.nanmedian(pitch[m])) if np.isfinite(pitch[m]).any() else None,
               recommended_offset_vox=_num(np.median(d)), recommended_offset_pitch=_num(med_p),
               verdict=verdict_for(n, med_p, spread, off, p))
    return row


# ------------------------------------------------------------------ outputs
def text_summary(report):
    r, t = report["result"], report["components"]
    s = r["summary"]
    L = [f"label_drift {report['tool_version']}",
         f"surface: {report['inputs']['surface']}   label: {report['inputs']['label']}   CT: {report['inputs']['ct']}",
         f"{s['n_labelled']} labelled pixels in {s['n_components']} components; {s['n_measured']} measured "
         f"(not measured: {s['n_labelled_invalid']} invalid grid cell, {s['n_labelled_tilted']} surface too tilted, "
         f"{s['n_labelled_no_slice']} no CT slice, {s['n_labelled_no_peak']} no sheet peak in range)",
         "sign: positive drift = the sheet peak lies along +normal, normal = d/drow x d/dcol of the grid; "
         "recommended offset = the move of the surface along the normal that re-centres the label", ""]
    for c in t:
        if c["verdict"] == "NO-DATA" and c["n_measured"] == 0:
            L.append(f"component {c['component']:>3}  NO-DATA  ({c['n_pixels']} px, none measured)")
            continue
        L.append(f"component {c['component']:>3}  {c['verdict']:<9} {c['n_measured']:>5}/{c['n_pixels']:<5} px  "
                 f"drift mean {_f(c['mean_drift_vox'])} vox ({_f(c['mean_drift_pitch'])} pitch), max |{_f(c['max_abs_drift_vox'])}| vox, "
                 f"off-sheet {100 * c['off_sheet_fraction']:.0f}%, thickness {c['mean_thickness_vox']:.2f} vox, "
                 f"recommended offset {_f(c['recommended_offset_vox'])} vox ({_f(c['recommended_offset_pitch'])} pitch)"
                 if c["off_sheet_fraction"] is not None else f"component {c['component']:>3}  {c['verdict']}")
    cnt = {v: sum(c["verdict"] == v for c in t) for v in VERDICTS}
    L += ["", "verdicts: " + ", ".join(f"{v} {n}" for v, n in cnt.items() if n)]
    return "\n".join(L) + "\n"


def _f(v):
    return "n/a" if v is None else f"{v:+.2f}" if abs(v) < 1e5 else str(v)


def write_drift_png(path, out, p: Params):
    from PIL import Image
    dp, lab, meas = out["drift_pitch"], out["component"] > 0, out["measured"]
    H, W = dp.shape
    img = np.empty((H, W, 3), np.uint8)
    img[:] = (28, 28, 28)
    t = np.clip(np.nan_to_num(dp) / p.png_range_pitch, -1, 1)
    pos = np.stack([255 * np.ones_like(t), 255 * (1 - t), 255 * (1 - t)], -1)     # + : white -> red
    neg = np.stack([255 * (1 + t), 255 * (1 + t), 255 * np.ones_like(t)], -1)     # - : white -> blue
    col = np.where((t >= 0)[..., None], pos, neg).astype(np.uint8)
    show = meas & np.isfinite(dp)
    img[show] = col[show]
    img[lab & ~show] = (255, 0, 255)                   # labelled, not measured: magenta
    img[show & (out["onsheet"] == 0)] = (img[show & (out["onsheet"] == 0)] * 0.55).astype(np.uint8)   # off-sheet: darker
    im = Image.fromarray(img, "RGB")
    if p.png_scale > 1:
        im = im.resize((W * p.png_scale, H * p.png_scale), Image.NEAREST)
    im.save(path)


def write_tifxyz(path, mesh, x, y, z, meta):
    import tifffile
    os.makedirs(path, exist_ok=True)
    bad = ~mesh.valid
    for ax, g in zip("xyz", (x, y, z)):
        g = np.asarray(g, np.float32).copy()
        g[bad] = -1.0
        tifffile.imwrite(os.path.join(path, f"{ax}.tif"), np.ascontiguousarray(g))
    with open(os.path.join(path, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=4, sort_keys=True)


def write_corrected(path, mesh, out, p: Params, src):
    """Tifxyz with every labelled, measured node moved to its nearest peak (along the in-plane normal, z unchanged).
    Never overwrites: refuses an existing non-empty folder or the input folder."""
    if os.path.realpath(path) == os.path.realpath(src):
        raise InputError("--write-corrected must not be the input surface folder")
    if os.path.exists(path) and (not os.path.isdir(path) or os.listdir(path)):
        raise InputError(f"--write-corrected target exists and is not an empty folder: {path}")
    d = out["drift_vox"]
    move = out["measured"] & np.isfinite(out["drift_pitch"]) & (np.abs(out["drift_pitch"]) <= p.correct_max_pitch)
    x, y, z = mesh.x.copy(), mesh.y.copy(), mesh.z.copy()
    n2 = out["normals"]
    x[move] += d[move] * n2[..., 0][move]
    y[move] += d[move] * n2[..., 1][move]
    meta = dict(mesh.meta)
    meta["label_drift"] = dict(tool_version=__version__, source=os.path.basename(os.path.normpath(src)),
                               nodes_moved=int(move.sum()), correct_max_pitch=p.correct_max_pitch)
    meta["uuid"] = f"{meta.get('uuid', 'surface')}-label-drift-corrected"
    write_tifxyz(path, mesh, x, y, z, meta)
    return int(move.sum())


def run(mesh, label, vol, p: Params):
    out, table, summary = analyse(mesh, label, vol, p)
    return out, dict(summary=summary), table


# ------------------------------------------------------------------ CLI
def build_parser():
    ap = argparse.ArgumentParser(description="Measure how far labels on a tifxyz surface sit from the nearest CT sheet peak.")
    ap.add_argument("surface", help="tifxyz folder")
    ap.add_argument("label", help="label image in the surface grid (PNG / TIFF / NPY; pixel > --label-min-value = labelled)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr", help="OME-Zarr volume")
    g.add_argument("--png-dir", help="directory of 2-D slice PNGs")
    ap.add_argument("--zarr-level", type=int, default=0, help="OME-Zarr level (coords are level-0 voxels)")
    ap.add_argument("--png-pixel-um", type=float, help="PNG pixel size in um (PNG input)")
    ap.add_argument("--png-pattern", default="{z:05d}.png", help="PNG name; {z} = slice index")
    ap.add_argument("--voxel-size-um", type=float, help="mesh voxel size; overrides meta.json")
    ap.add_argument("--transpose", action="store_true", help="grids have z varying along columns")
    ap.add_argument("--out-dir", required=True, help="writes drift.png, drift.npz, components.csv, report.json, summary.txt")
    ap.add_argument("--write-corrected", metavar="DIR", help="write a tifxyz with labelled nodes moved to the nearest peak (never overwrites)")
    for f in dataclasses.fields(Params):
        flag, v = "--" + f.name.replace("_", "-"), f.default
        if isinstance(v, bool):
            ap.add_argument(flag, action="store_true", default=v, help="(off by default)")
        else:
            ap.add_argument(flag, type=type(v), default=v, help=f"default {v}")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        p.validate()
        mesh = load_mesh(a.surface, p.invalid_value, a.transpose)
        label = load_label(a.label)
        vox = mesh_voxel_um(mesh, mesh, a.voxel_size_um)
        if a.zarr:
            vol, ct = ZarrVolume(a.zarr, a.zarr_level), f"{os.path.basename(os.path.normpath(a.zarr))} level {a.zarr_level}"
        else:
            vol, ct = PngVolume(a.png_dir, a.png_pixel_um, vox, a.png_pattern), os.path.basename(os.path.normpath(a.png_dir))
        out, res, table = run(mesh, label, vol, p)
        os.makedirs(a.out_dir, exist_ok=True)
        moved = write_corrected(a.write_corrected, mesh, out, p, a.surface) if a.write_corrected else None
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    report = dict(tool_version=__version__,
                  inputs=dict(surface=os.path.basename(os.path.normpath(a.surface)), label=os.path.basename(a.label), ct=ct,
                              voxel_um=vox),
                  params=asdict(p), result=res, components=table, corrected_nodes_moved=moved)
    write_drift_png(os.path.join(a.out_dir, "drift.png"), out, p)
    np.savez_compressed(os.path.join(a.out_dir, "drift.npz"), **{k: v for k, v in out.items() if k != "normals"})
    with open(os.path.join(a.out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    with open(os.path.join(a.out_dir, "components.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    txt = text_summary(report)
    with open(os.path.join(a.out_dir, "summary.txt"), "w") as fh:
        fh.write(txt)
    print(txt, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
