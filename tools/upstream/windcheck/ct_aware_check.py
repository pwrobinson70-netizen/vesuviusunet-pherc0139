#!/usr/bin/env python3
"""ct_aware_check: self-intersection AND off-sheet check for a tifxyz trace, built on windcheck's engine (MIT, Josep Carreras).  (MIT)

OUR code, a separate module.  The self-intersection predicate is windcheck's own C++ engine ``engines/selfcross.cpp`` (vendored,
unmodified); we only call it.  The CT-aware off-sheet check is new.  See ATTRIBUTION.md.

    python ct_aware_check.py TRACE.tifxyz --zarr VOL.zarr  [--pitch-vox 22]
    python ct_aware_check.py TRACE.tifxyz --npy VOL.npy    [--pitch-vox 22]        # (z, y, x) array, e.g. a phantom_scroll vol.npy

Two checks, one verdict (PASS / FAIL / NOT JUDGED) with the reasons; exit code 0 PASS, 1 FAIL, 4 NOT JUDGED, 2 bad input:

  self_intersection  the trace's triangles are tested exactly against each other (windcheck's engine, both quad diagonals).  A
                     transverse crossing between triangles farther apart than --exclude grid cells is a defect: a tight fold
                     whose layers touch but do not cross is NOT.  FAIL at >= --min-crossings crossings that BOTH diagonals
                     report (a crossing seen under one diagonal only is tessellation-dependent: reported, not failed, unless
                     --any-diagonal).
  off_sheet          the CT is sampled along the surface normal at every --stride-th vertex over +-(--half-range-pitches x pitch).
                     The vertex is ON a sheet if the nearest bright ridge (a local maximum standing out by >= --min-contrast of the
                     volume's intensity range) is within --off-tol-pitches x pitch of the surface; OFF if the nearest ridge is farther or
                     there is none; not judged where the profile is bright everywhere (a merged or solid region: no ridge to find).
                     FAIL if more than --max-off-fraction of the judged vertices are off; NOT JUDGED if fewer than
                     --min-judged-fraction of the sampled vertices could be judged.  Assumes bright sheets on a darker background.
What it does not do: it cannot tell the RIGHT sheet from a wrong one (a trace that sits on a neighbouring sheet is on a sheet);
that is what trace_auditor's winding checks are for.  Off-sheet and crossing are necessary-not-sufficient evidence of a bad trace.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL, NJ = "PASS", "FAIL", "NOT JUDGED"
__version__ = "0.1.0"


@dataclass
class Params:
    # --- self-intersection (windcheck engine)
    exclude: int = 2                 # triangles whose quads are within this many grid cells (v and u) are neighbours, never compared
    cell: float = 40.0               # engine broad-phase cell (voxels)
    max_edge: float = 60.0           # engine drops triangles with an edge longer than this (voxels): grid discontinuities, not crossings
    min_crossings: int = 1           # FAIL at this many transverse triangle pairs confirmed under both diagonals
    any_diagonal: bool = False       # count a crossing seen under either diagonal (default: both must agree)
    threads: int = 0                 # 0 = all
    # --- off-sheet (CT)
    pitch_vox: float | None = None   # sheet-to-sheet distance (voxels), REQUIRED for the off-sheet check; trace_auditor passes its measured pitch
    stride: int = 2                  # sample every k-th row and column of the grid
    half_range_pitches: float = 0.5  # profile along the normal: +- this x pitch
    step_vox: float = 0.5            # sample spacing along the normal (voxels)
    off_tol_pitches: float = 0.2     # a ridge within this x pitch of the surface = on the sheet
    min_contrast: float = 0.15       # a ridge must stand out of its profile by this fraction of the volume's intensity range (p1..p99)
    solid_frac: float = 0.6          # profile minimum above lo + this x range => bright everywhere => not judged
    max_off_fraction: float = 0.10   # FAIL if more than this fraction of judged vertices are off-sheet
    min_judged_fraction: float = 0.5 # NOT JUDGED if fewer of the sampled vertices could be judged
    block: int = 6                   # local rule: a window of block x block sampled vertices (block*stride grid cells a side) ...
    block_off_fraction: float = 0.5  # ... in which at least this fraction of the judged vertices is off-sheet is a FAIL on its own (a local defect
    block_min_judged: int = 12       # ... needs at least this many judged vertices in the window); the global fraction dilutes small defects


# ----------------------------------------------------------------------------------------------- engine
def engine_path():
    return os.environ.get("WINDCHECK_ENGINE") or os.path.join(_HERE, "engines", "selfcross")


def build_engine(path=None):
    """Compile engines/selfcross.cpp (g++ or clang++) if the binary is missing.  Returns the path or None."""
    path = path or engine_path()
    if os.path.isfile(path):
        return path
    src = os.path.join(_HERE, "engines", "selfcross.cpp")
    for cxx in ("g++", "clang++", "c++"):
        if shutil.which(cxx) and os.path.isfile(src):
            r = subprocess.run([cxx, "-O2", "-std=c++17", "-pthread", "-o", path, src], capture_output=True, text=True)
            if r.returncode == 0 and os.path.isfile(path):
                return path
    return None


def write_atlas(path, P, valid):
    """windcheck's WCAT container, one surface (same bytes as upstream tests/test_selfcross.py writes)."""
    rows, cols = valid.shape
    with open(path, "wb") as fh:
        fh.write(b"WCAT")
        fh.write(struct.pack("<II", 1, 1))
        fh.write(struct.pack("<iII", -1, rows, cols))
        fh.write(np.ascontiguousarray(P, dtype="<f4").tobytes())
        fh.write(np.ascontiguousarray(valid, dtype=np.uint8).tobytes())


def run_engine(engine, P, valid, p: Params, diagonal, work):
    a, o = os.path.join(work, "a.bin"), os.path.join(work, f"o{diagonal}.csv")
    write_atlas(a, P, valid)
    r = subprocess.run([engine, a, o, str(p.threads), str(p.cell), str(p.exclude), str(diagonal), str(p.max_edge)],
                       capture_output=True, text=True, check=True)
    summary = json.loads(r.stdout.strip().splitlines()[-1])
    events = []
    with open(o) as f:
        next(f)
        for line in f:
            s = line.strip().split(",")
            if s[4] == "transverse":
                events.append(dict(v1=int(s[0]), u1=int(s[1]), v2=int(s[2]), u2=int(s[3]), penetration=float(s[5]), angle_deg=float(s[6])))
    return summary, events


def self_intersection(P, valid, p: Params, engine=None):
    """Returns a check dict.  P is (H, W, 3) float32 XYZ voxels, valid (H, W) bool."""
    engine = engine or build_engine()
    if engine is None:
        return dict(check="self_intersection", status=NJ, reason="windcheck engine not built and no C++ compiler found "
                    "(g++ -O2 -std=c++17 -pthread -o engines/selfcross engines/selfcross.cpp)")
    with tempfile.TemporaryDirectory() as work:
        res = [run_engine(engine, P, valid, p, d, work) for d in (0, 1)]
    t = [r[0]["transverse"] for r in res]
    n = max(t) if p.any_diagonal else min(t)
    ev = res[0][1] if t[0] >= t[1] else res[1][1]
    extra = dict(transverse_by_diagonal=t, coplanar=[r[0]["coplanar"] for r in res], grazing=[r[0]["grazing"] for r in res],
                 triangles=res[0][0]["triangles"], events=ev[:20])
    if res[0][0]["triangles"] == 0:
        return dict(check="self_intersection", status=NJ, reason="no triangles (no quad with four valid corners and edges <= max_edge)", **extra)
    if n >= p.min_crossings:
        span = max((abs(e["u1"] - e["u2"]) for e in ev), default=0)
        return dict(check="self_intersection", status=FAIL, reason=f"{n} transverse triangle crossings confirmed "
                    f"({'either' if p.any_diagonal else 'both'} diagonals: {t}), up to {span} grid columns apart along u", **extra)
    note = f" ({max(t)} under one diagonal only: tessellation-dependent, not counted)" if max(t) > n else ""
    return dict(check="self_intersection", status=PASS, reason=f"no transverse crossing confirmed under both diagonals{note}; "
                f"coplanar {extra['coplanar']}, grazing {extra['grazing']} (reported, not failed)", **extra)


# ----------------------------------------------------------------------------------------------- off-sheet (CT)
def normals(P, valid):
    """Unit normals from the grid tangents (central differences over valid neighbours); NaN where undefined."""
    H, W, _ = P.shape
    Pn = np.where(valid[..., None], P, np.nan).astype(np.float64)
    du = np.full_like(Pn, np.nan)
    dv = np.full_like(Pn, np.nan)
    du[:, 1:-1] = Pn[:, 2:] - Pn[:, :-2]
    dv[1:-1] = Pn[2:] - Pn[:-2]
    n = np.cross(du, dv)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return n / ln


def sample_volume(data, pts_zyx, ct_scale=1.0, block=2048):
    """Trilinear samples of `data` [z,y,x] at (N, 3) points given in mesh voxels (z, y, x).  Out of range -> NaN.
    Reads only the sub-box each block of points needs, so a zarr array is not loaded whole."""
    from scipy.ndimage import map_coordinates
    pts = np.asarray(pts_zyx, np.float64) / ct_scale
    out = np.full(len(pts), np.nan, np.float32)
    shp = np.array(data.shape[:3])
    order = np.argsort(pts[:, 0])
    for s in range(0, len(pts), block):
        idx = order[s:s + block]
        q = pts[idx]
        ok = np.isfinite(q).all(1) & (q >= 0).all(1) & (q <= shp - 1).all(1)
        if not ok.any():
            continue
        qq = q[ok]
        lo = np.maximum(np.floor(qq.min(0)).astype(int) - 1, 0)
        hi = np.minimum(np.ceil(qq.max(0)).astype(int) + 2, shp)
        sub = np.asarray(data[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]], dtype=np.float32)
        out[idx[ok]] = map_coordinates(sub, (qq - lo).T, order=1, mode="nearest")
    return out


def intensity_range(data, max_voxels=2_000_000):
    """(p1, p99) of the whole volume, from a strided subsample of about `max_voxels` voxels (the reference for 'a ridge stands out')."""
    s = max(1, int(np.ceil((np.prod(data.shape[:3]) / max_voxels) ** (1 / 3))))
    sub = np.asarray(data[::s, ::s, ::s], dtype=np.float32)
    return float(np.percentile(sub, 1)), float(np.percentile(sub, 99))


def off_sheet(P, valid, data, p: Params, ct_scale=1.0):
    """Returns a check dict.  `data` is the CT [z, y, x] (array-like), P in mesh voxels XYZ."""
    if not p.pitch_vox or p.pitch_vox <= 0:
        return dict(check="off_sheet", status=NJ, reason="no sheet pitch (give --pitch-vox, or run it through trace_auditor which measures it)")
    N = normals(P, valid)
    H, W = valid.shape
    rr, cc = np.mgrid[0:H:p.stride, 0:W:p.stride]
    sel = valid[rr, cc] & np.isfinite(N[rr, cc]).all(-1)
    rr, cc = rr[sel], cc[sel]
    if rr.size == 0:
        return dict(check="off_sheet", status=NJ, reason="no vertex with a defined normal")
    n_all = int(rr.size)
    T = p.half_range_pitches * p.pitch_vox
    ts = np.arange(-T, T + 1e-9, p.step_vox)
    base, nrm = P[rr, cc].astype(np.float64), N[rr, cc]
    pts = base[:, None, :] + ts[None, :, None] * nrm[:, None, :]                  # (n, nt, 3) XYZ
    prof = sample_volume(data, pts[..., ::-1].reshape(-1, 3), ct_scale).reshape(len(rr), len(ts))
    fin = np.isfinite(prof).all(1)
    prof = prof[fin]
    rr, cc = rr[fin], cc[fin]
    if prof.shape[0] == 0:
        return dict(check="off_sheet", status=NJ, reason="every sampled profile leaves the volume")
    lo, hi = intensity_range(data)
    if not hi > lo:
        return dict(check="off_sheet", status=NJ, reason="the volume has no intensity contrast")
    rng = hi - lo
    pmin, pmax = prof.min(1), prof.max(1)
    solid = pmin > lo + p.solid_frac * rng
    # local maxima with prominence
    mid = prof[:, 1:-1]
    is_pk = (mid >= prof[:, :-2]) & (mid > prof[:, 2:]) & ((mid - pmin[:, None]) >= p.min_contrast * rng)
    state = np.zeros(prof.shape[0], np.int8)                                      # 0 on, 1 off, 2 not judged
    dist = np.full(prof.shape[0], np.nan)
    for i in range(prof.shape[0]):
        if solid[i]:
            state[i] = 2
            continue
        k = np.nonzero(is_pk[i])[0]
        if k.size == 0:
            state[i] = 1
            continue
        d = np.abs(ts[k + 1])
        dist[i] = d.min()
        state[i] = 0 if d.min() <= p.off_tol_pitches * p.pitch_vox else 1
    n_j = int((state != 2).sum())
    n_off = int((state == 1).sum())
    extra = dict(sampled=int(n_all), judged=n_j, off=n_off, off_fraction=(n_off / n_j if n_j else None),
                 median_ridge_distance_vox=(float(np.nanmedian(dist)) if np.isfinite(dist).any() else None),
                 off_tol_vox=p.off_tol_pitches * p.pitch_vox, pitch_vox=p.pitch_vox,
                 off_sample=[dict(v=int(rr[i]), u=int(cc[i])) for i in np.nonzero(state == 1)[0][:20]])
    if n_all == 0 or n_j / n_all < p.min_judged_fraction:
        return dict(check="off_sheet", status=NJ, reason=f"only {n_j} of {n_all} sampled vertices could be judged (need "
                    f"{100 * p.min_judged_fraction:.0f}%): bright everywhere or outside the volume", **extra)
    f = n_off / n_j
    # local rule: worst block x block window of sampled vertices
    gs = np.zeros(((H - 1) // p.stride + 1, (W - 1) // p.stride + 1, 2), np.int32)       # [..., 0] judged, [..., 1] off
    gs[rr // p.stride, cc // p.stride, 0] = (state != 2)
    gs[rr // p.stride, cc // p.stride, 1] = (state == 1)
    ii = np.pad(gs.cumsum(0).cumsum(1), ((1, 0), (1, 0), (0, 0)))
    b = min(p.block, ii.shape[0] - 1, ii.shape[1] - 1)
    win = ii[b:, b:] - ii[:-b, b:] - ii[b:, :-b] + ii[:-b, :-b] if b > 0 else ii[:0, :0]
    worst, wpos = 0.0, None
    if win.size:
        jj, oo = win[..., 0], win[..., 1]
        frac = np.where(jj >= p.block_min_judged, oo / np.maximum(jj, 1), 0.0)
        k = np.unravel_index(np.argmax(frac), frac.shape)
        worst, wpos = float(frac[k]), dict(v=int(k[0] * p.stride), u=int(k[1] * p.stride), cells=int(b * p.stride))
    extra.update(worst_block_off_fraction=worst, worst_block=wpos)
    if f > p.max_off_fraction or worst >= p.block_off_fraction:
        why = (f"{100 * f:.1f}% of {n_j} judged vertices are off every sheet (limit {100 * p.max_off_fraction:.0f}%)" if f > p.max_off_fraction else
               f"{100 * worst:.0f}% of the judged vertices in the {wpos['cells']}x{wpos['cells']}-cell window at row {wpos['v']}, column {wpos['u']} "
               f"are off every sheet (limit {100 * p.block_off_fraction:.0f}%); overall {100 * f:.1f}%")
        return dict(check="off_sheet", status=FAIL, reason=why + f"; off = nearest ridge > {extra['off_tol_vox']:.1f} voxels away or none", **extra)
    return dict(check="off_sheet", status=PASS, reason=f"{100 * f:.1f}% of {n_j} judged vertices are off-sheet (limit {100 * p.max_off_fraction:.0f}%), "
                f"worst {p.block}x{p.block}-sample window {100 * worst:.0f}% (limit {100 * p.block_off_fraction:.0f}%)", **extra)


# ----------------------------------------------------------------------------------------------- one verdict
def check_trace(P, valid, data, p: Params, ct_scale=1.0, engine=None):
    """Both checks.  Returns dict(verdict, checks=[...]).  `data` None => only the self-intersection check runs."""
    checks = [self_intersection(P, valid, p, engine)]
    if data is not None:
        checks.append(off_sheet(P, valid, data, p, ct_scale))
    st = [c["status"] for c in checks]
    return dict(verdict=FAIL if FAIL in st else (NJ if NJ in st else PASS), checks=checks)


def mesh_arrays(mesh):
    """ssc_io mesh -> (P (H,W,3) float32, valid (H,W) bool)."""
    return np.stack([mesh.x, mesh.y, mesh.z], -1).astype(np.float32), np.asarray(mesh.valid, bool)


def add_flags(ap, prefix="", skip=()):
    d = Params()
    for f in dataclasses.fields(Params):
        if f.name in skip:
            continue
        flag = "--" + prefix + f.name.replace("_", "-")
        v = getattr(d, f.name)
        if isinstance(v, bool):
            ap.add_argument(flag, action="store_true", default=v, help=f"(default {v})")
        else:
            ap.add_argument(flag, type=float if v is None else type(v), default=v, help="(default %(default)s)")


def params_from(a, prefix=""):
    return Params(**{f.name: getattr(a, prefix + f.name) for f in dataclasses.fields(Params)})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="tifxyz directory")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--zarr", help="OME-Zarr volume (level 0)")
    g.add_argument("--npy", help="(z, y, x) .npy volume")
    ap.add_argument("--ct-scale", type=float, default=1.0, help="mesh voxels per CT pixel of the volume (default %(default)s)")
    ap.add_argument("--json", help="write the full result here")
    add_flags(ap)
    a = ap.parse_args(argv)
    sys.path.insert(0, os.path.join(_HERE, "..", "..", "sheet_spacing_check"))
    from ssc_io import InputError, ZarrVolume, load_mesh
    try:
        mesh = load_mesh(a.trace)
        if a.zarr:
            data = ZarrVolume(a.zarr).data
        elif a.npy:
            data = np.load(a.npy, mmap_mode="r")
        else:
            data = None
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    P, valid = mesh_arrays(mesh)
    res = check_trace(P, valid, data, params_from(a), a.ct_scale)
    print(f"{mesh.name}: {res['verdict']}")
    for c in res["checks"]:
        print(f"  {c['check']}: {c['status']}  {c['reason']}")
    if data is None:
        print("  off_sheet: not run (no --zarr / --npy)")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f, indent=2, default=float)
    return {PASS: 0, FAIL: 1, NJ: 4}[res["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
