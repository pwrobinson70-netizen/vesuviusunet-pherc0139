#!/usr/bin/env python3
"""crush_map: where is the scroll crushed, and where can the trace tools not be trusted?  (MIT)

    python crush_map.py --zarr VOL.zarr --heights 500,1000,1500 --out-dir OUT [--png-dir ... --png-pixel-um ...]

Per CT slice, on a grid of cells (`--grid-step-px` CT pixels), four maps:
  * pitch        local sheet spacing (voxels): tools/common/local_pitch.py along the structure-tensor normal (NaN where the
                 coherence is below --coherence-min or no spacing can be measured);
  * variability  robust scatter of ln(pitch) over a --var-window x --var-window block of cells (how much the spacing changes
                 round that point);
  * coherence    structure-tensor coherence of the sheet normals (0..1);
  * severity     0..1 estimate of how crushed the sheets are (0 = nominal spacing, 1 = spacing reduced by --full-factor or
                 more): built from
                   - density:  ln(phi / phi_ref) / ln(full factor), phi = local papyrus fill fraction (smoothed above-Otsu
                               mask inside the filled scroll region), phi_ref = its --density-ref-percentile in the slice;
                   - spacing:  ln(pitch_ref / pitch) / ln(full factor), pitch_ref = the --pitch-ref-percentile of the confident
                               pitches in the slice;
                 clipped to 0..1. The severity is the MEAN of the two terms; a cell where the pitch could not be measured keeps its
                 density term only (on the phantoms the mean ranked the true severity best across presets: Spearman 0.85 crushed-hard,
                 0.74 crushed, 0.68 merged, 0.63 mild; the larger of the two ranked mild / merged worse, the spacing term alone ranked
                 crushed-hard worse).
Outputs: crush_map.npz (all maps, stacked over the heights), crush_zNNNNNN.png per height, summary.csv / summary.json per height,
optionally crush_map.zarr (--write-zarr). The npz is what `trace_auditor --crush-map` reads: regions whose severity is at or
above --max-crush-severity become NOT JUDGED.

Assumptions and limits (read before trusting): the density term assumes sheets of roughly constant thickness; real scans have
dust, varying thickness and brightness, so there it also tracks thickness. The scroll region is the Otsu foreground, closed by
--region-close-px and hole-filled; sheets further apart than twice that are not bridged. The estimates were checked on synthetic
phantoms only (tests/test_crush_map.py; the PR gives the numbers). Every constant is a flag.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import os
import sys
from dataclasses import dataclass, asdict

import numpy as np
from scipy import ndimage as ndi

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.normpath(os.path.join(_HERE, ".."))
for _d in ("common", "sheet_spacing_check", "umbilicus_finder"):
    _p = os.path.join(_TOOLS, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import local_pitch as lpm  # noqa: E402
import umbilicus_finder as uf  # noqa: E402
from ssc_io import InputError, PngVolume, ZarrVolume, mesh_voxel_um, to_px  # noqa: E402

__version__ = "0.1.0"


@dataclass
class Params:
    grid_step_px: int = 4               # map cell size (CT pixels)
    coherence_min: float = 0.25         # cells below this normal coherence get no pitch
    sigma_grad: float = 1.5             # structure tensor: gradient sigma (CT px)
    sigma_int: float = 4.0              # structure tensor: integration sigma (CT px)
    region_close_px: int = 12           # scroll region = Otsu foreground, closed by this radius, hole-filled (CT px)
    density_sigma_px: float = 8.0       # papyrus fill fraction: Gaussian window sigma (CT px)
    density_ref_percentile: float = 20.0    # phi_ref: this percentile of the fill fraction inside the region (the least crushed part)
    pitch_ref_percentile: float = 75.0      # pitch_ref: this percentile of the confident pitches (the least crushed part)
    pitch_ref_min_confidence: float = 0.3   # pitches below this confidence do not enter pitch_ref
    full_factor: float = 4.0            # spacing change at which severity reaches 1
    var_window: int = 5                 # variability window (cells, odd)
    edge_margin_px: int = 8             # cells this close to the region border get no severity (the window is cut by the border)
    # local pitch (tools/common/local_pitch.py)
    pitch_half_len_vox: float = 40.0
    pitch_prominence_frac: float = 0.05
    pitch_window_pitches: float = 3.0
    pitch_cv_max: float = 0.5
    pitch_ac_full: float = 0.5
    min_peaks: int = 3
    profile_step_px: float = 0.5
    profile_sigma_px: float = 1.0
    peak_min_distance_px: float = 3.0

    def validate(self):
        if self.grid_step_px < 1 or self.var_window < 1 or self.var_window % 2 == 0:
            raise InputError("--grid-step-px must be >= 1 and --var-window odd")
        if self.full_factor <= 1:
            raise InputError("--full-factor must be > 1")
        if not (0 <= self.density_ref_percentile <= 100 and 0 <= self.pitch_ref_percentile <= 100):
            raise InputError("percentiles must be in 0..100")
        return self

    def pitch_params(self):
        return lpm.PitchParams(half_len_vox=self.pitch_half_len_vox, step_px=self.profile_step_px, sigma_px=self.profile_sigma_px,
                               prominence_frac=self.pitch_prominence_frac, min_distance_px=self.peak_min_distance_px,
                               min_peaks=self.min_peaks, window_pitches=self.pitch_window_pitches, cv_max=self.pitch_cv_max,
                               ac_full=self.pitch_ac_full).validate()


MAPS = ("pitch", "variability", "coherence", "confidence", "density", "severity")


def _disk(r):
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx ** 2 + yy ** 2) <= r * r


def region_and_density(img, p: Params):
    """(region mask, above-Otsu sheet mask, local papyrus fill fraction (full-resolution array))."""
    sm = ndi.gaussian_filter(np.asarray(img, float), 1.0)
    t = uf.otsu_lower_threshold(sm, 2)
    if t is None:
        z = np.zeros(sm.shape, bool)
        return z, z, np.zeros(sm.shape)
    sheet = sm > t
    reg = sheet
    if p.region_close_px > 0:
        reg = ndi.binary_closing(sheet, structure=_disk(int(p.region_close_px)), border_value=0)
    reg = ndi.binary_fill_holes(reg)
    num = ndi.gaussian_filter((sheet & reg).astype(float), p.density_sigma_px)
    den = np.maximum(ndi.gaussian_filter(reg.astype(float), p.density_sigma_px), 1e-6)
    return reg, sheet, num / den


def _local_std_ln(P, win):
    """Robust (1.4826 MAD) scatter of ln P over win x win blocks of cells, NaN-aware; NaN where fewer than 4 finite."""
    L = np.log(P)
    out = np.full(P.shape, np.nan)
    h = win // 2
    for i in range(P.shape[0]):
        for j in range(P.shape[1]):
            w = L[max(0, i - h): i + h + 1, max(0, j - h): j + h + 1].ravel()
            w = w[np.isfinite(w)]
            if len(w) >= 4:
                out[i, j] = 1.4826 * np.median(np.abs(w - np.median(w)))
    return out


def slice_maps(img, ct_scale, p: Params):
    """Maps of one slice (2-D array, CT pixels). Returns a dict of grid arrays (n_i, n_j) plus the grid geometry."""
    p.validate()
    img = np.asarray(img, np.float64)
    H, W = img.shape
    g = int(p.grid_step_px)
    ii, jj = np.mgrid[g // 2:H:g, g // 2:W:g]
    out = {k: np.full(ii.shape, np.nan) for k in MAPS}
    out["confidence"][:] = 0.0
    out["region"] = np.zeros(ii.shape, bool)
    out["grid_step_px"] = g
    out["ct_scale"] = float(ct_scale)
    if img.size == 0 or not img.max() > img.min():
        return out
    reg, sheet, phi_full = region_and_density(img, p)
    if not reg.any():
        return out
    inner = ndi.binary_erosion(reg, structure=_disk(max(1, int(p.edge_margin_px))), border_value=0) if p.edge_margin_px > 0 else reg
    out["region"] = reg[ii, jj]
    nx, ny, coh, _ = uf.structure_tensor(ndi.gaussian_filter(img, 1.0), p.sigma_grad, p.sigma_int)
    out["coherence"] = np.where(reg[ii, jj], coh[ii, jj], np.nan)
    phi = phi_full[ii, jj]
    out["density"] = np.where(reg[ii, jj], phi, np.nan)
    # local pitch along the normal at cells with enough coherence
    sel = reg[ii, jj] & (coh[ii, jj] >= p.coherence_min)
    if sel.any():
        xy_px = np.stack([jj[sel], ii[sel]], axis=1).astype(float)
        nrm = np.stack([nx[ii, jj][sel], ny[ii, jj][sel]], axis=1)
        lp = lpm.local_pitch(img, (0.0, 0.0), xy_px, nrm, ct_scale, np.zeros(len(xy_px), int), p.pitch_params())
        out["pitch"][sel] = lp.pitch
        out["confidence"][sel] = lp.confidence
    P = out["pitch"]
    out["variability"] = _local_std_ln(P, p.var_window)
    # severity
    ln_full = math.log(p.full_factor)
    cell_in = inner[ii, jj]
    ref_phi = float(np.percentile(phi_full[inner], p.density_ref_percentile)) if inner.any() else float("nan")
    s_den = np.zeros(ii.shape)
    if np.isfinite(ref_phi) and ref_phi > 0:
        s_den = np.clip(np.log(np.maximum(phi, 1e-3) / ref_phi) / ln_full, 0, 1)
    good = np.isfinite(P) & (out["confidence"] >= p.pitch_ref_min_confidence)
    s_pit = np.full(ii.shape, np.nan)
    if good.sum() >= 10:
        ref_p = float(np.percentile(P[good], p.pitch_ref_percentile))
        with np.errstate(invalid="ignore", divide="ignore"):
            s_pit = np.where(np.isfinite(P), np.clip(np.log(ref_p / P) / ln_full, 0, 1), np.nan)
        out["pitch_ref"] = ref_p
    out["density_ref"] = ref_phi
    sev = np.where(np.isfinite(s_pit), 0.5 * (s_den + np.nan_to_num(s_pit)), s_den)
    out["severity"] = np.where(cell_in, sev, np.nan)
    out["s_density"], out["s_spacing"] = np.where(cell_in, s_den, np.nan), np.where(cell_in, s_pit, np.nan)
    return out


def _summary(z, m, p: Params):
    f = lambda a, q: float(np.nanpercentile(a, q)) if np.isfinite(a).any() else None   # noqa: E731
    sev = m["severity"]
    ok = np.isfinite(sev)
    mean = lambda a: float(np.nanmean(a)) if np.isfinite(a).any() else None            # noqa: E731
    return dict(z=float(z), n_cells=int(m["region"].sum()), pitch_p10=f(m["pitch"], 10), pitch_median=f(m["pitch"], 50),
                pitch_p90=f(m["pitch"], 90), variability_mean=mean(m["variability"]), coherence_mean=mean(m["coherence"]),
                confidence_mean=mean(m["confidence"][m["region"]]) if m["region"].any() else None,
                severity_mean=mean(sev), severity_p90=f(sev, 90),
                fraction_severe=float(np.mean(sev[ok] >= 0.5)) if ok.any() else None,
                pitch_ref=m.get("pitch_ref"), density_ref=m.get("density_ref"))


def run(vol, heights, p: Params, log=None):
    """-> list of (z, maps dict) for every height."""
    p.validate()
    res = []
    for z in heights:
        H, W = vol.probe_shape(z)
        tile = np.asarray(vol.tile(z, 0, 0, W, H), float)
        if log:
            log(f"z={z:g}: {W}x{H} px")
        res.append((float(z), slice_maps(tile, vol.ct_scale, p)))
    return res


# --------------------------------------------------------------------------------------------- outputs
_LUT = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], float)    # viridis, 5 stops


def _colour(a, lo, hi):
    t = np.clip((np.nan_to_num(a, nan=lo) - lo) / max(hi - lo, 1e-12), 0, 1) * (len(_LUT) - 1)
    k = np.minimum(t.astype(int), len(_LUT) - 2)
    rgb = _LUT[k] * (1 - (t - k))[..., None] + _LUT[k + 1] * (t - k)[..., None]
    rgb[~np.isfinite(a)] = (30, 30, 30)
    return rgb.astype(np.uint8)


def write_png(path, z, m, img):
    from PIL import Image
    lo, hi = np.percentile(img, [1, 99])
    ct = np.clip((img - lo) / max(hi - lo, 1e-9), 0, 1)
    g = m["grid_step_px"]
    ct_small = ct[g // 2::g, g // 2::g][: m["severity"].shape[0], : m["severity"].shape[1]]
    ct_rgb = np.repeat((ct_small * 255).astype(np.uint8)[..., None], 3, axis=2)
    pit = m["pitch"]
    pl, ph = (np.nanpercentile(pit, [5, 95]) if np.isfinite(pit).any() else (0, 1))
    panels = [ct_rgb, _colour(pit, pl, ph), _colour(m["variability"], 0, 0.5), _colour(m["coherence"], 0, 1),
              _colour(m["severity"], 0, 1)]
    up = max(1, int(round(256 / max(panels[0].shape[:2]))))
    panels = [np.repeat(np.repeat(a, up, 0), up, 1) for a in panels]
    Image.fromarray(np.concatenate(panels, axis=1)).save(path)


def write_outputs(out_dir, results, p: Params, vol_info, imgs=None, write_png_files=True, write_zarr=False):
    os.makedirs(out_dir, exist_ok=True)
    zs = np.array([z for z, _ in results])
    stack = {k: np.stack([m[k] for _, m in results]) for k in MAPS}
    stack["region"] = np.stack([m["region"] for _, m in results])
    stack["s_density"] = np.stack([m["s_density"] for _, m in results])
    stack["s_spacing"] = np.stack([m["s_spacing"] for _, m in results])
    meta = dict(tool_version=__version__, grid_step_px=int(p.grid_step_px), ct_scale=float(results[0][1]["ct_scale"]),
                params=asdict(p), **vol_info)
    np.savez_compressed(os.path.join(out_dir, "crush_map.npz"), heights=zs, meta=json.dumps(meta), **stack)
    rows = [_summary(z, m, p) for z, m in results]
    with open(os.path.join(out_dir, "summary.json"), "w") as fh:
        json.dump(dict(meta=meta, heights=rows), fh, indent=2)
    with open(os.path.join(out_dir, "summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    if write_png_files and imgs is not None:
        for (z, m), img in zip(results, imgs):
            write_png(os.path.join(out_dir, f"crush_z{int(round(z)):06d}.png"), z, m, img)
    if write_zarr:
        import zarr
        g = zarr.open_group(os.path.join(out_dir, "crush_map.zarr"), mode="w", zarr_format=2)
        for k in MAPS + ("region",):
            a = np.asarray(stack[k], np.float32 if k != "region" else np.uint8)
            arr = g.create_array(k, shape=a.shape, chunks=(1,) + a.shape[1:], dtype=a.dtype)
            arr[...] = a
        g.attrs.update(dict(heights=zs.tolist(), grid_step_px=int(p.grid_step_px), ct_scale=float(meta["ct_scale"])))
    return rows


class CrushMap:
    """Reader for crush_map.npz: severity (and the other maps) at a level-0 voxel position."""

    def __init__(self, path):
        d = np.load(path, allow_pickle=False)
        self.heights = np.asarray(d["heights"], float)
        self.maps = {k: np.asarray(d[k]) for k in MAPS if k in d.files}
        meta = json.loads(str(d["meta"]))
        self.grid = int(meta["grid_step_px"])
        self.ct_scale = float(meta["ct_scale"])
        self.meta = meta

    def at(self, z, xy_vox, name="severity", max_dz=None):
        """Value of map `name` at height z and xy (n, 2) level-0 voxel coords (x, y): nearest height, nearest cell. NaN where the
        nearest height is further than max_dz (default: the largest spacing between the map heights) or the cell has no value."""
        xy = np.atleast_2d(np.asarray(xy_vox, float))
        k = int(np.argmin(np.abs(self.heights - z)))
        gap = float(np.max(np.diff(np.sort(self.heights)))) if len(self.heights) > 1 else math.inf
        if abs(self.heights[k] - z) > (gap if max_dz is None else max_dz):
            return np.full(len(xy), np.nan)
        px = to_px(xy, self.ct_scale)
        a = self.maps[name][k]
        i = np.clip(np.rint((px[:, 1] - self.grid // 2) / self.grid).astype(int), 0, a.shape[0] - 1)
        j = np.clip(np.rint((px[:, 0] - self.grid // 2) / self.grid).astype(int), 0, a.shape[1] - 1)
        return a[i, j]


# --------------------------------------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr", help="OME-Zarr volume")
    g.add_argument("--png-dir", help="directory of 2-D slice PNGs")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--png-pixel-um", type=float)
    ap.add_argument("--png-pattern", default="{z:05d}.png")
    ap.add_argument("--voxel-size-um", type=float, help="voxel size (PNG input)")
    ap.add_argument("--heights", help="comma-separated z heights (level-0 voxels)")
    ap.add_argument("--z-start", type=float), ap.add_argument("--z-stop", type=float)
    ap.add_argument("--z-step", type=float, default=64.0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--no-png", action="store_true", help="do not write the per-height PNGs")
    ap.add_argument("--write-zarr", action="store_true", help="also write crush_map.zarr")
    for f in dataclasses.fields(Params):
        ap.add_argument("--" + f.name.replace("_", "-"), type=type(f.default), default=f.default)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        p.validate()
        if a.zarr:
            vol, ct = ZarrVolume(a.zarr, a.zarr_level), f"{a.zarr} level {a.zarr_level}"
        else:
            if not (a.png_pixel_um and a.voxel_size_um):
                raise InputError("PNG input needs --png-pixel-um and --voxel-size-um")
            vol, ct = PngVolume(a.png_dir, a.png_pixel_um, a.voxel_size_um, a.png_pattern), a.png_dir
        if a.heights:
            heights = [float(h) for h in a.heights.split(",") if h.strip()]
        elif a.z_start is not None and a.z_stop is not None:
            heights = list(np.arange(a.z_start, a.z_stop, a.z_step))
        else:
            raise InputError("give --heights or --z-start and --z-stop")
        if not heights:
            raise InputError("no heights")
        res = run(vol, heights, p, log=lambda m: print(m, file=sys.stderr))
        imgs = None
        if not a.no_png:
            imgs = [np.asarray(vol.tile(z, 0, 0, *reversed(vol.probe_shape(z))), float) for z, _ in res]
        rows = write_outputs(a.out_dir, res, p, dict(ct=ct, heights=heights), imgs, not a.no_png, a.write_zarr)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print("     z  pitch(p10/med/p90)   var   coh  severity(mean/p90)  severe%")
    for r in rows:
        f = lambda v, fmt: "  n/a" if v is None else fmt % v   # noqa: E731
        print(f"{r['z']:6.0f}  {f(r['pitch_p10'], '%5.1f')}/{f(r['pitch_median'], '%5.1f')}/{f(r['pitch_p90'], '%5.1f')}   "
              f"{f(r['variability_mean'], '%4.2f')}  {f(r['coherence_mean'], '%4.2f')}   {f(r['severity_mean'], '%4.2f')}/"
              f"{f(r['severity_p90'], '%4.2f')}   {f(None if r['fraction_severe'] is None else 100 * r['fraction_severe'], '%5.1f')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
