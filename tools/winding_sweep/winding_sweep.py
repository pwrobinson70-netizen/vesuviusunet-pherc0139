#!/usr/bin/env python3
"""winding_sweep: one command, every layer of a band -- a seed, a patch and an audit verdict per winding.  (MIT)

    python winding_sweep.py --zarr VOL.zarr --z-lo 100 --z-hi 160 --out-dir sweep/ [--angle 0 --n-angles 4 ...]
    python winding_sweep.py --npy  vol.npy  --z-lo 40  --z-hi 120 --out-dir sweep/

Pipeline (CPU only, deterministic, no learned model; every threshold is a flag, `--help` lists them):
  1. centre line: umbilicus_finder on the band (+ `--centre-margin` voxels each side), or a given `--umbilicus` file.
  2. ray: at `--height` (default: band middle) a straight ray leaves the centre at `--angle` (degrees from +x towards +y).
     The slice (mean of +/- `--ray-z-halfwidth` slices) is sampled along it, smoothed, and every bright-sheet peak
     (prominence >= `--ray-prominence` x profile range, spacing >= `--ray-min-sep-pitch` x pitch) is a CROSSING.
     Pitch = sheet_spacing_check.ct_pitches (imported, not copied) on lines parallel to the ray, or `--pitch-vox`.
     Crossings are numbered outward: the first is winding `--first-winding` (default 0), then +1 each.
     With `--n-angles K` the ray is repeated at K evenly spaced angles; the summary says which windings were found
     at every angle. Patches are grown from the first angle only.
  3. seeds: one per crossing, at the ray hit, at the ray height.
  4. patches: sheet_tracer from every seed, in parallel (`--workers`). Local pitch for a patch = the mean gap to its
     neighbouring crossings (or `--pitch-vox`). The patch window is limited to `--circumference-fraction` (default 0.9)
     of the circumference 2 pi r at the seed, and to `--max-rows` x `--max-cols`; its rows to the band height. The
     volume that is loaded is the band itself, so a patch cannot leave the band.
  5. audit: trace_auditor.audit on every patch alone (same centre line).
  6. outputs in `--out-dir`: patches/winding_NNN/ (tifxyz, VC3D format, level-0 voxels, XYZ; growth_log.json),
     overlay_z<height>.png (patches coloured by winding), manifest.json / manifest.csv, summary.json / summary.txt.
Verdicts per patch: PASS / FAIL / NOT JUDGED (the auditor's own) and NO PATCH (the seed was rejected by sheet_tracer).
judged_fraction = (heights where the winding check was judged + heights where the switch finder tracked
>= `--audit-min-tracked-fraction`) / (2 x heights).
Exit code: 0 every patch PASS, 1 any FAIL, 4 no FAIL but some NOT JUDGED / NO PATCH, 2 bad input, 3 no sheet crossing found.
Volumes are used at the level you load (`--zarr-level`); coordinates in and out are voxels of that level.
Dependencies: numpy, scipy, tifffile, pillow (+ zarr for --zarr). Needs the sibling tool folders (repo layout or vun_tools install).
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import multiprocessing as mp
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates
from scipy.signal import find_peaks

HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.normpath(os.path.join(HERE, ".."))
for _d in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor", "sheet_tracer"):
    _p = os.path.join(_TOOLS, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import sheet_spacing_check as ssc  # noqa: E402
import sheet_tracer as st  # noqa: E402
import trace_auditor as ta  # noqa: E402
import umbilicus_finder as uf  # noqa: E402
import uf_io  # noqa: E402
from ssc_io import ArrayVolume, InputError, build_mesh  # noqa: E402

__version__ = "0.1.0"
PASS, FAIL, NJ, NOPATCH = "PASS", "FAIL", "NOT JUDGED", "NO PATCH"


class NoCrossings(ValueError):
    """No bright-sheet crossing along the ray (exit code 3)."""


@dataclass
class Params:
    # --- where
    height: float | None = None             # z of the ray and the seeds (voxels); default band middle
    angle: float = 0.0                      # first ray angle, degrees from +x towards +y
    n_angles: int = 1                       # rays at angle + k * 360 / n_angles; consistency is reported when > 1
    first_winding: int = 0                  # winding number of the innermost crossing
    # --- centre line
    centre_z_step: float = 16.0             # umbilicus_finder z step (voxels)
    centre_margin: float = 32.0             # centre slices are taken this far outside the band too
    centre_max_gap: float = 1.5             # a height has a centre only within this x z step of an OK centre slice
    # --- ray / crossings
    ray_z_halfwidth: int = 2                # slices averaged each side of the height
    ray_step: float = 0.5                   # sample step along the ray (voxels)
    ray_sigma: float = 1.0                  # Gaussian smoothing along the ray (voxels)
    ray_prominence: float = 0.25            # min peak prominence, fraction of the profile range
    ray_min_sep_pitch: float = 0.5          # min distance between crossings, x pitch
    ray_min_radius: float = 0.0             # ignore the ray inside this radius (voxels)
    ray_max_radius: float | None = None     # stop the ray here (voxels); default the volume border minus ray_edge_margin
    ray_edge_margin: float = 4.0            # voxels kept clear of the volume border
    pitch_vox: float | None = None          # CT sheet pitch (voxels); default measured on the ray
    # --- patches
    max_rows: int = 129                     # sheet_tracer window rows (also limited to the band height)
    max_cols: int = 129                     # sheet_tracer window columns (also limited by the circumference)
    circumference_fraction: float = 0.9     # window width <= this x 2 pi r at the seed (< 1: never onto the next turn)
    workers: int = 0                        # processes; 0 = all CPUs
    # --- consistency
    min_consistency: float = 1.0            # a winding is "consistent" if found at >= this fraction of the angles


def _prefix_flags(ap, prefix, cls, skip=()):
    for f in dataclasses.fields(cls):
        if f.name in skip:
            continue
        v = f.default
        t = float if v is None else type(v)
        ap.add_argument(f"--{prefix}-" + f.name.replace("_", "-"), dest=f"{prefix}__{f.name}", type=t, default=None,
                        help=f"{cls.__module__}.Params.{f.name} (default {v})")


def _prefix_params(a, prefix, cls, **fixed):
    kw = {f.name: getattr(a, f"{prefix}__{f.name}") for f in dataclasses.fields(cls)
          if getattr(a, f"{prefix}__{f.name}", None) is not None}
    kw.update(fixed)
    return cls(**kw)


# ------------------------------------------------------------------------------------------------ volume
class Source:
    """The volume (z, y, x) as a lazy array: .data (np array / memmap / zarr), .shape, .desc."""

    def __init__(self, data, desc):
        if len(data.shape) != 3:
            raise InputError(f"volume must be 3-D (z, y, x), got {tuple(data.shape)}")
        self.data, self.shape, self.desc = data, tuple(int(s) for s in data.shape), desc

    def slab(self, z0, z1):
        return np.asarray(self.data[z0:z1], dtype=np.float32)


def open_source(zarr_path=None, npy_path=None, level=0):
    if npy_path:
        if not os.path.isfile(npy_path):
            raise InputError(f"npy volume not found: {npy_path}")
        return Source(np.load(npy_path, mmap_mode="r"), npy_path)
    if not zarr_path or not os.path.exists(zarr_path):
        raise InputError(f"zarr path does not exist: {zarr_path}")
    import zarr
    try:
        g = zarr.open(str(zarr_path), mode="r")
        arr = g[str(level)] if hasattr(g, "keys") else g
    except Exception as e:  # noqa: BLE001
        raise InputError(f"cannot open zarr level {level} in {zarr_path}: {e}") from e
    return Source(arr, f"{zarr_path} level {level}")


def check_band(src, z_lo, z_hi):
    nz = src.shape[0]
    if not (np.isfinite(z_lo) and np.isfinite(z_hi)) or z_hi <= z_lo:
        raise InputError(f"the z band is empty: --z-lo {z_lo} --z-hi {z_hi}")
    if z_lo < 0 or z_hi > nz:
        raise InputError(f"the z band [{z_lo:g}, {z_hi:g}) is outside the volume (z extent [0, {nz}))")
    z0, z1 = int(math.floor(z_lo)), int(math.ceil(z_hi))
    if z1 - z0 < 5:
        raise InputError(f"the z band is only {z1 - z0} slices; need at least 5")
    return z0, z1


class OffsetVolume(ArrayVolume):
    """The loaded band as a CT volume indexed by FULL-volume z (slab slice 0 is slice z0)."""

    def __init__(self, slab, z0):
        super().__init__(slab, 1.0)
        self.z0 = int(z0)

    def slice_index(self, z):
        zi = int(math.floor(z + 1e-9)) - self.z0
        if not 0 <= zi < self.data.shape[0]:
            raise InputError(f"height z={z} is outside the loaded band [{self.z0}, {self.z0 + self.data.shape[0]})")
        return zi


# ------------------------------------------------------------------------------------------------ centre line
def find_centre(src, z0, z1, p: Params, uf_p, umbilicus=None, umbilicus_format="auto"):
    """-> ta.Centre (full-volume z), source description."""
    if umbilicus:
        z, y, x = ta.read_umbilicus(umbilicus, umbilicus_format)
        return ta.Centre(z, y, x, f"file {umbilicus}", np.inf), f"file {umbilicus}"
    lo, hi = max(0.0, z0 - p.centre_margin), min(float(src.shape[0]), z1 + p.centre_margin)
    vol = uf_io.ArrayVolume(src.data)
    rows, _ = uf.run(vol, uf_p, z_start=lo, z_stop=hi, z_step=p.centre_z_step)
    ok = [r for r in rows if r["flag"] == "OK" and np.isfinite(r["y"])]
    if len(ok) < 2:
        raise InputError(f"umbilicus_finder found a centre at only {len(ok)} of {len(rows)} slices in z [{lo:g}, {hi:g}); "
                         "give --umbilicus or a larger band")
    z = np.array([r["z"] for r in ok])
    return (ta.Centre(z, np.array([r["y"] for r in ok]), np.array([r["x"] for r in ok]), "umbilicus_finder",
                      p.centre_max_gap * p.centre_z_step),
            f"umbilicus_finder ({len(ok)} OK of {len(rows)} slices)")


# ------------------------------------------------------------------------------------------------ ray
@dataclass
class Crossing:
    winding: int
    r: float                # voxels from the centre
    x: float
    y: float
    pitch: float            # local pitch (mean gap to neighbouring crossings)
    angle: float


def ray_pitch(img, cx, cy, ang, r_max, ssc_p=None):
    """CT pitch along the ray by sheet_spacing_check.ct_pitches: a short line across the ray, whose normals are the
    ray direction, so the profile of every point is a line parallel to the ray. Median over the points."""
    ca, sa = math.cos(ang), math.sin(ang)
    r_mid = 0.5 * r_max
    k = np.arange(-4, 5) * 1.0
    xy = np.array([[cx + r_mid * ca - kk * sa, cy + r_mid * sa + kk * ca] for kk in k])
    line = ssc.Line(xy, np.arange(len(k)), np.zeros(len(k), int), np.zeros(len(k)))
    sp = dataclasses.replace(ssc_p or ssc.Params(), profile_halflen_vox=float(r_max))
    pp = ssc.ct_pitches(img, (0, 0), line, 1.0, sp)
    pp = pp[np.isfinite(pp)]
    return float(np.median(pp)) if len(pp) else float("nan")


def ray_crossings(slab, zi, centre_yx, angle_deg, p: Params, first_winding=None):
    """Bright-sheet crossings along one ray in slab slice zi. -> (list[Crossing], profile dict, pitch)."""
    nz, ny, nx = slab.shape
    cy, cx = centre_yx
    h = p.ray_z_halfwidth
    img = slab[max(0, zi - h):zi + h + 1].mean(axis=0)
    ang = math.radians(angle_deg)
    ca, sa = math.cos(ang), math.sin(ang)
    # largest r keeping the ray inside the image
    lim = []
    for c, d, n in ((cx, ca, nx), (cy, sa, ny)):
        if d > 1e-9:
            lim.append((n - 1 - p.ray_edge_margin - c) / d)
        elif d < -1e-9:
            lim.append((p.ray_edge_margin - c) / d)
    r_max = min(lim) if lim else 0.0
    if p.ray_max_radius is not None:
        r_max = min(r_max, p.ray_max_radius)
    if not (np.isfinite(r_max) and r_max > p.ray_min_radius + 5):
        raise InputError(f"the centre ({cx:.1f}, {cy:.1f}) leaves no room for a ray at {angle_deg:g} deg")
    pitch = p.pitch_vox or ray_pitch(img, cx, cy, ang, r_max)
    if not (np.isfinite(pitch) and pitch > 0):
        raise NoCrossings(f"no sheet pitch could be measured along the ray at {angle_deg:g} deg (fewer than 3 sheet peaks); "
                          "the slice may be outside the scroll, or give --pitch-vox")
    r = np.arange(p.ray_min_radius, r_max + 1e-9, p.ray_step)
    prof = map_coordinates(img, [cy + r * sa, cx + r * ca], order=1, mode="nearest")
    prof = gaussian_filter1d(prof, p.ray_sigma / p.ray_step)
    rng = float(prof.max() - prof.min())
    dist = max(1, int(round(p.ray_min_sep_pitch * pitch / p.ray_step)))
    pk, _ = find_peaks(prof, prominence=p.ray_prominence * rng, distance=dist) if rng > 0 else (np.array([], int), None)
    rr = []
    for k in pk:                                          # parabolic sub-sample refinement
        d = 0.0
        if 0 < k < len(r) - 1:
            y0, y1, y2 = prof[k - 1], prof[k], prof[k + 1]
            den = y0 - 2 * y1 + y2
            if den < 0:
                d = float(np.clip(0.5 * (y0 - y2) / den, -1, 1)) * p.ray_step
        rr.append(float(r[k] + d))
    if not rr:
        raise NoCrossings(f"no bright-sheet crossing on the ray at {angle_deg:g} deg, z={zi}: nothing with prominence "
                          f">= {p.ray_prominence:g} x the profile range")
    fw = p.first_winding if first_winding is None else first_winding
    out = []
    for i, ri in enumerate(rr):
        gaps = ([ri - rr[i - 1]] if i > 0 else []) + ([rr[i + 1] - ri] if i + 1 < len(rr) else [])
        out.append(Crossing(fw + i, ri, cx + ri * ca, cy + ri * sa, float(np.mean(gaps)) if gaps else float(pitch), angle_deg))
    return out, dict(r=r, profile=prof), float(pitch)


# ------------------------------------------------------------------------------------------------ patches
@dataclass
class Job:
    crossing: Crossing
    z: float                 # seed height, slab frame (slab slice 0 = full-volume z0)
    max_rows: int
    max_cols: int
    pitch: float


_G = {}      # fork-shared state: tracer, slab, volume, centre, params


def plan_window(c: Crossing, band_h, p: Params, tp: st.Params):
    pitch = p.pitch_vox or c.pitch
    step = tp.step_vox if tp.step_vox else tp.step_pitch_frac * pitch
    cols = int(p.circumference_fraction * 2.0 * math.pi * c.r / step)
    rows = int(band_h / step) + 1
    return max(3, min(p.max_rows, rows)), max(3, min(p.max_cols, cols)), pitch, step


def _judged_fraction(trace, par):
    heights = trace.get("heights", [])
    n = len(heights)
    if n == 0:
        return 0.0
    sw = sum(1 for h in heights if h["tracked"] >= par.min_tracked_fraction)
    wn = 0
    for c in trace["checks"]:
        if c["check"] == "winding_jumps":
            wn = sum(1 for h in c.get("heights", []) if h["status"] != NJ)
    return (sw + wn) / (2.0 * n)


def run_job(job: Job):
    G = _G
    tp, par = G["tracer_params"], G["audit_params"]
    t0 = time.time()
    c = job.crossing
    base = dict(winding=c.winding, ok=False, verdict=NOPATCH, judged_fraction=0.0, area_vx2=0.0, reasons=[])
    p = dataclasses.replace(tp, pitch_vox=job.pitch, max_rows=job.max_rows, max_cols=job.max_cols)
    seed = (c.x, c.y, job.z)
    try:
        res = st.trace(None, seed, p, tracer=G["tracer"])
    except st.SeedError as e:
        base["reasons"] = [f"seed rejected: {e}"]
        base["seconds"] = time.time() - t0
        return base
    xyz, off = st.crop(res)
    xyz = np.where((xyz[..., 0] != -1)[..., None], xyz + np.array([0.0, 0.0, G["z0"]], np.float32), xyz)   # full-volume z
    step = res["step"]
    area = st.area_vx2(xyz)
    summary = dict(seed_snapped_xyz=res["seed_snapped"], stop_reason=res["stop_reason"], grid_shape=list(xyz.shape[:2]),
                   pitch_vox=res["pitch"], step_vox=step, touches_window_edge=res["touches_window_edge"],
                   n_accepted=int(res["accepted"].sum()))
    mesh = build_mesh(f"winding_{c.winding:03d}", xyz[..., 0], xyz[..., 1], xyz[..., 2],
                      {"scale": [1.0 / step, 1.0 / step]})
    out = dict(base, ok=True, area_vx2=area, summary=summary, res=res, xyz=xyz, step=step, seed=seed)
    try:
        heights = ta.auto_heights([mesh], par)
        ssf_p = G["ssf_params"]
        ssc_p = ssc.Params(band_height_vox=float(max(1.0, (heights[-1] - heights[0]) / max(1, len(heights) - 1))))
        rep = ta.audit([mesh], G["avol"], heights, G["centre"], par, ssf_p, ssc_p)
        t = rep["traces"][0]
        out.update(verdict=t["verdict"], reasons=t["reasons"], judged_fraction=_judged_fraction(t, par),
                   audit_heights=heights, checks=[dict(check=k["check"], status=k["status"], reason=k["reason"])
                                                  for k in t["checks"]])
    except (InputError, ValueError) as e:
        out.update(verdict=NJ, reasons=[f"audit could not run: {e}"], checks=[])
    out["seconds"] = time.time() - t0
    return out


def _pool_run(jobs, workers):
    n = min(len(jobs), workers if workers > 0 else (os.cpu_count() or 1))
    if n <= 1 or "fork" not in mp.get_all_start_methods():
        return [run_job(j) for j in jobs]
    with mp.get_context("fork").Pool(n) as pool:
        return pool.map(run_job, jobs, chunksize=1)


# ------------------------------------------------------------------------------------------------ outputs
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212)]


def colour(w):
    return PALETTE[int(w) % len(PALETTE)]


def write_overlay(path, slab, zi, z_abs, centre_yx, crossings, ray_angle, r_max, results, meshes, title):
    from PIL import Image, ImageDraw
    img = slab[zi].astype(np.float64)
    lo, hi = np.percentile(img, [0.5, 99.5])
    g = (np.clip((img - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype(np.uint8)
    im = Image.fromarray(np.stack([g] * 3, -1)).convert("RGB")
    d = ImageDraw.Draw(im)
    cy, cx = centre_yx
    ca, sa = math.cos(math.radians(ray_angle)), math.sin(math.radians(ray_angle))
    d.line([(cx, cy), (cx + r_max * ca, cy + r_max * sa)], fill=(255, 255, 255), width=1)
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], outline=(255, 255, 255))
    sp = ssc.Params(max_gap_vox=float("inf"))
    for res, mesh in zip(results, meshes):
        if mesh is None:
            continue
        line = ssc.cut_line(mesh, float(z_abs), sp)
        col = colour(res["winding"])
        for s, e in ssc._run_bounds(line.run):
            pts = [(float(x), float(y)) for x, y in line.xy[s:e]]
            if len(pts) > 1:
                d.line(pts, fill=col, width=2)
    for c in crossings:
        col = colour(c.winding)
        d.ellipse([c.x - 4, c.y - 4, c.x + 4, c.y + 4], outline=col, width=2)
        d.text((c.x + 6, c.y - 12), f"w{c.winding}", fill=col)
    d.text((4, 4), title, fill=(255, 255, 255))
    im.save(path)


def write_manifest(out_dir, rows):
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(rows, f, indent=2, default=float)
    cols = ["winding", "seed_x", "seed_y", "seed_z", "radius", "pitch", "patch", "verdict", "judged_fraction", "area_vx2",
            "grid_rows", "grid_cols", "stop_reason", "found_at_angles", "consistent", "reasons"]
    with open(os.path.join(out_dir, "manifest.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(k) if k != "reasons" else " | ".join(r["reasons"]) for k in cols])


# ------------------------------------------------------------------------------------------------ sweep
def sweep(src, z_lo, z_hi, out_dir, p: Params, tracer_params=None, audit_params=None, ssf_params=None, uf_params=None,
          umbilicus=None, umbilicus_format="auto", log=None):
    """Run the whole sweep. Returns dict(manifest=[...], summary={...}). Raises InputError / NoCrossings."""
    log = log or (lambda m: None)
    t_start = time.time()
    tp = tracer_params or st.Params()
    par = audit_params or ta.Params()
    ssf_p = ssf_params or ta.ssf.Params(vertical=1)
    if not 0 < p.circumference_fraction < 1:
        raise InputError("--circumference-fraction must be > 0 and < 1")
    if p.n_angles < 1:
        raise InputError("--n-angles must be >= 1")
    z0, z1 = check_band(src, z_lo, z_hi)
    height = (z0 + z1 - 1) / 2.0 if p.height is None else p.height
    if not z0 <= height <= z1 - 1:
        raise InputError(f"--height {height:g} is outside the band [{z0}, {z1 - 1}]")
    height = float(int(round(height)))                 # seeds and the ray sit on a slice
    os.makedirs(out_dir, exist_ok=True)
    log("loading the band")
    slab = src.slab(z0, z1)
    centre, csrc = find_centre(src, z0, z1, p, uf_params or uf.Params(), umbilicus, umbilicus_format)
    zi = int(round(height - z0))                       # slab slice of the height
    cyx = centre.at(float(height))
    if cyx is None:
        raise InputError(f"no centre line at z={height:g} (control points do not reach it)")
    # ---- rays
    angles = [p.angle + k * 360.0 / p.n_angles for k in range(p.n_angles)]
    per_angle, first_r = [], None
    for k, a in enumerate(angles):
        try:
            cr, prof, pitch = ray_crossings(slab, zi, cyx, a, p)
        except NoCrossings:
            if k == 0:
                raise
            per_angle.append(dict(angle=a, crossings=[], pitch=None, error="no crossing"))
            continue
        per_angle.append(dict(angle=a, crossings=cr, pitch=pitch, r_max=float(prof["r"][-1])))
    main = per_angle[0]
    crossings = main["crossings"]
    log(f"{len(crossings)} crossings at {angles[0]:g} deg: " + ", ".join(f"w{c.winding}@r={c.r:.1f}" for c in crossings))
    found = {a["angle"]: {c.winding for c in a["crossings"]} for a in per_angle}
    all_w = sorted(set().union(*found.values()))
    need = max(1, int(math.ceil(p.min_consistency * len(angles) - 1e-9)))
    cons = {w: sum(w in s for s in found.values()) for w in all_w}
    consistent = [w for w in all_w if cons[w] >= need]
    # ---- patches
    tracer = st.Tracer(slab, tp)
    _G.update(tracer=tracer, tracer_params=tp, audit_params=par, ssf_params=ssf_p, avol=OffsetVolume(slab, z0), centre=centre, z0=z0)
    jobs = []
    for c in crossings:
        rows, cols, pitch, step = plan_window(c, z1 - z0 - 1, p, tp)
        jobs.append(Job(c, float(zi), rows, cols, pitch))
    log(f"growing and auditing {len(jobs)} patches")
    results = _pool_run(jobs, p.workers)
    # ---- write
    manifest, meshes = [], []
    pdir = os.path.join(out_dir, "patches")
    for job, r in zip(jobs, results):
        c = job.crossing
        row = dict(winding=c.winding, seed_x=c.x, seed_y=c.y, seed_z=float(height), radius=c.r, pitch=job.pitch,
                   patch=None, verdict=r["verdict"], judged_fraction=r["judged_fraction"], area_vx2=r["area_vx2"],
                   grid_rows=None, grid_cols=None, stop_reason=None, reasons=r["reasons"],
                   window_rows=job.max_rows, window_cols=job.max_cols, checks=r.get("checks", []),
                   found_at_angles=cons.get(c.winding, 0), consistent=c.winding in consistent, seconds=r["seconds"])
        mesh = None
        if r["ok"]:
            res = r["res"]
            xyz = r["xyz"]
            mesh = build_mesh(f"winding_{c.winding:03d}", xyz[..., 0], xyz[..., 1], xyz[..., 2], {})
            shifted = dict(res)
            pts = res["points"].copy()
            m = res["accepted"]
            pts[..., 2] = np.where(m, pts[..., 2] + z0, pts[..., 2])
            shifted["points"] = pts
            ss = list(res["seed_snapped"])
            ss[2] += z0
            shifted["seed_snapped"] = ss
            rel = os.path.join("patches", f"winding_{c.winding:03d}")
            full = os.path.join(out_dir, rel)
            os.makedirs(pdir, exist_ok=True)
            st.write_outputs(full, shifted, dataclasses.replace(tp, pitch_vox=job.pitch, max_rows=job.max_rows,
                                                                max_cols=job.max_cols), (c.x, c.y, height), src.desc)
            meta_p = os.path.join(full, "meta.json")
            meta = json.load(open(meta_p))
            meta.update(winding=c.winding, sweep=dict(tool="winding_sweep", version=__version__, verdict=r["verdict"],
                                                      angle_deg=c.angle, radius_vox=c.r))
            json.dump(meta, open(meta_p, "w"), indent=4)
            row.update(patch=rel, grid_rows=r["summary"]["grid_shape"][0], grid_cols=r["summary"]["grid_shape"][1],
                       stop_reason=r["summary"]["stop_reason"])
        meshes.append(mesh)
        manifest.append(row)
    write_manifest(out_dir, manifest)
    png = os.path.join(out_dir, f"overlay_z{height:g}.png")
    write_overlay(png, slab, zi, height, cyx, crossings, angles[0], main.get("r_max", 0.0), manifest, meshes,
                  f"z={height:g}: {sum(m['verdict'] == PASS for m in manifest)}/{len(manifest)} PASS")
    counts = {v: sum(m["verdict"] == v for m in manifest) for v in (PASS, FAIL, NJ, NOPATCH)}
    summary = dict(tool="winding_sweep", version=__version__, volume=src.desc, band=[z0, z1], height=float(height),
                   centre_source=csrc, centre_yx=list(cyx), angles=angles,
                   pitch_vox=[a["pitch"] for a in per_angle], n_crossings_per_angle=[len(a["crossings"]) for a in per_angle],
                   windings_found_per_angle={f"{a:g}": sorted(s) for a, s in found.items()},
                   windings_found_at_every_angle=sorted(w for w in all_w if cons[w] == len(angles)),
                   windings_consistent=consistent, min_consistency=p.min_consistency,
                   n_patches=len(manifest), verdicts=counts, total_area_vx2=float(sum(m["area_vx2"] for m in manifest)),
                   overlay=os.path.basename(png), wall_seconds=time.time() - t_start,
                   params=dataclasses.asdict(p), tracer_params=dataclasses.asdict(tp), audit_params=dataclasses.asdict(par))
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=float)
    txt = text_summary(summary, manifest)
    with open(os.path.join(out_dir, "summary.txt"), "w") as f:
        f.write(txt)
    return dict(manifest=manifest, summary=summary, text=txt)


def text_summary(s, manifest):
    L = [f"winding_sweep {s['version']}   CT: {s['volume']}   band z [{s['band'][0]}, {s['band'][1]})   height {s['height']:g}",
         f"centre: {s['centre_source']}   angles: " + ", ".join(f"{a:g}" for a in s["angles"]),
         f"crossings per angle: {s['n_crossings_per_angle']}   windings found at every angle: {s['windings_found_at_every_angle']}",
         ""]
    L.append(f"{'wind':>4} {'r':>7} {'pitch':>6} {'verdict':<11} {'judged':>6} {'area':>9} {'grid':>9} {'angles':>6}  patch / reason")
    for m in manifest:
        g = f"{m['grid_rows']}x{m['grid_cols']}" if m["grid_rows"] else "-"
        why = m["patch"] if m["verdict"] == PASS else (m["reasons"][0] if m["reasons"] else "")
        L.append(f"{m['winding']:>4} {m['radius']:>7.1f} {m['pitch']:>6.1f} {m['verdict']:<11} {m['judged_fraction']:>6.2f} "
                 f"{m['area_vx2']:>9.0f} {g:>9} {m['found_at_angles']:>6}  {why}")
    v = s["verdicts"]
    L += ["", f"{s['n_patches']} patches: {v[PASS]} PASS, {v[FAIL]} FAIL, {v[NJ]} NOT JUDGED, {v[NOPATCH]} NO PATCH; "
              f"total area {s['total_area_vx2']:.0f} vox^2; wall {s['wall_seconds']:.1f} s", ""]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------------ CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr", help="OME-Zarr volume (group or array)")
    g.add_argument("--npy", help=".npy volume (z, y, x)")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--z-lo", type=float, required=True, help="band start (voxels, inclusive)")
    ap.add_argument("--z-hi", type=float, required=True, help="band end (voxels, exclusive)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--umbilicus", help="centre line file (default: umbilicus_finder on the band)")
    ap.add_argument("--umbilicus-format", default="auto", choices=["auto", "json", "villa-json", "native-json", "zyx-text", "thaumato"])
    d = Params()
    for f in dataclasses.fields(Params):
        v = getattr(d, f.name)
        t = float if v is None else type(v)
        ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, type=t, default=v)
    _prefix_flags(ap, "tracer", st.Params, skip=("pitch_vox", "max_rows", "max_cols"))
    _prefix_flags(ap, "audit", ta.Params)
    _prefix_flags(ap, "ssf", ta.ssf.Params)
    _prefix_flags(ap, "uf", uf.Params)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        src = open_source(a.zarr, a.npy, a.zarr_level)
        tp = _prefix_params(a, "tracer", st.Params)
        par = _prefix_params(a, "audit", ta.Params)
        ssf_p = _prefix_params(a, "ssf", ta.ssf.Params, vertical=1)
        ssf_p.validate()
        uf_p = _prefix_params(a, "uf", uf.Params)
        r = sweep(src, a.z_lo, a.z_hi, a.out_dir, p, tp, par, ssf_p, uf_p, a.umbilicus, a.umbilicus_format,
                  log=lambda m: print(m, file=sys.stderr))
    except NoCrossings as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except (InputError, uf_io.InputError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(r["text"], end="")
    v = r["summary"]["verdicts"]
    return 1 if v[FAIL] else (4 if v[NJ] or v[NOPATCH] else 0)


if __name__ == "__main__":
    sys.exit(main())
