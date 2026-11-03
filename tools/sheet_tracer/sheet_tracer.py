#!/usr/bin/env python3
"""sheet_tracer: grow a single-sheet surface patch from a seed voxel in a CT volume, as a tifxyz mesh (MIT).

    python sheet_tracer.py --zarr volume.zarr --seed X Y Z --out DIR [--max-rows 129 --max-cols 129 ...]

Method (CPU only, deterministic, no learned model):
  1. Local sheet normal = dominant eigenvector of the 3-D structure tensor (Gaussian-weighted sum of g g^T of the
     smoothed gradient, window `--sigma-tensor`). Oriented to agree with the neighbour it is grown from.
  2. Two in-sheet tangents: t_row = the z axis projected into the sheet plane (rows follow the scroll axis), t_col =
     normal x t_row. The scroll axis is assumed to be roughly z (as in VC3D data); a sheet lying flat (|n_z| > 0.95)
     uses y instead.
  3. Breadth-first rings: every cell next to an accepted cell (4-neighbourhood) is a front cell. Its position is
     predicted from the accepted neighbours as `neighbour + step * tangent` (mean of the predictions), then snapped
     to the nearest bright-sheet peak along the normal within +/- `--snap-pitch` x CT pitch.
  4. A front cell is REJECTED (and the reason logged) if: no peak with prominence >= `--peak-prominence` x the volume
     contrast lies in the snap window (`no_peak`); the new normal turns more than `--max-normal-turn-deg` from any
     accepted neighbour (`normal_turn`); the snapped point is closer than `--guard-pitch` x pitch to an accepted point
     that is NOT a grid neighbour (`self_intersection`: grid Chebyshev distance > `--guard-grid-radius`, i.e. on a
     different row AND column away from the local patch); the prediction leaves the volume (`volume_edge`); the snap
     moved the point more than `--max-step-stretch` x step from its neighbour (`step_stretch`, an extra guard); the
     tensor is degenerate (`bad_normal`). A rejected cell is retried only when it gains an accepted neighbour.
  5. Stops at `--max-rows` x `--max-cols` (a window with the seed in the middle), at the volume edge, or when a ring
     accepts nothing.
CT pitch (the bright-sheet peak spacing, the unit of every distance threshold) is measured at the seed with
sheet_spacing_check.ct_pitches (imported, not copied) unless `--pitch-vox` is given. The seed itself is checked: it
must have a planar structure tensor and a sheet peak within `--seed-snap-pitch` x pitch along its normal, else the
tracer stops at once with a message (exit code 3) -- a seed in a gap is not moved to the neighbouring sheet.

Output (--out DIR): tifxyz (x.tif y.tif z.tif float32, (rows, cols), (-1,-1,-1) where no point; meta.json with
scale = 1/step; docs/FORMATS.md), growth_log.json (summary, per-ring counts, every rejected front point with the reason),
all in level-0 voxels, XYZ order. The whole volume (one level) is held in memory: use a crop or a low level for big scrolls.
Dependencies: numpy, scipy, tifffile (zarr only for --zarr).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import uuid as _uuid
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.signal import find_peaks
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
_SSC = os.path.normpath(os.path.join(HERE, "..", "sheet_spacing_check"))
if _SSC not in sys.path:
    sys.path.insert(0, _SSC)

import sheet_spacing_check as ssc  # noqa: E402  (pitch: ct_pitches, Line, Params)

__version__ = "0.1.0"


class SeedError(ValueError):
    """The seed cannot start a patch (message says why)."""


@dataclass
class Params:
    pitch_vox: float | None = None        # CT sheet pitch (voxels); default: measured at the seed with ssc.ct_pitches
    global_pitch: bool = False            # v0.2: measure the seed pitch with the OLD sheet_spacing_check estimator (default: the local one)
    step_vox: float | None = None         # arc length between grid points (voxels); default step_pitch_frac x pitch
    step_pitch_frac: float = 0.2          # ... used when step_vox is not given
    snap_pitch: float = 0.5               # snap window: +/- this x pitch along the normal
    guard_pitch: float = 0.5              # self-intersection distance, x pitch
    guard_grid_radius: int | None = None  # grid Chebyshev radius exempt from the guard; default ceil(guard/step) + 1
    max_normal_turn_deg: float = 30.0     # reject if the normal turns more than this from an accepted neighbour
    max_step_stretch: float = 2.0         # reject if the snapped point is further than this x step from a neighbour
    max_rows: int = 129
    max_cols: int = 129
    sigma_smooth: float = 1.0             # voxels, smoothing of the volume for peak snapping
    sigma_grad: float = 1.5               # voxels, gradient scale of the structure tensor
    sigma_tensor: float = 3.0             # voxels, integration window of the structure tensor
    peak_prominence: float = 0.25         # min peak prominence as a fraction of the volume contrast (p99.5 - p0.5)
    sample_step: float = 0.5              # voxels, sampling step along the normal
    seed_snap_pitch: float = 0.25         # the seed must lie within this x pitch of a sheet peak
    seed_min_coherence: float = 0.3       # (l1 - l2) / l1 of the structure tensor at the seed
    edge_margin: float = 2.0              # voxels from the volume border where growth stops
    axis_xy: tuple | None = None          # (x, y) of the scroll axis: orient every normal away from it, so the grid has one handedness


class Tracer:
    def __init__(self, vol, p: Params):
        self.p = p
        v = np.asarray(vol, np.float32)
        if v.ndim != 3:
            raise ValueError(f"volume must be 3-D (z, y, x), got {v.shape}")
        self.raw = v
        self.shape = v.shape
        self.vs = gaussian_filter(v, p.sigma_smooth)
        self.g = [gaussian_filter(v, p.sigma_grad, order=o) for o in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]  # d/dz d/dy d/dx
        sub = self.vs[::2, ::2, ::2]
        lo, hi = np.percentile(sub, [0.5, 99.5])
        self.contrast = float(hi - lo)
        self.R = int(math.ceil(2.0 * p.sigma_tensor))
        o = np.arange(-self.R, self.R + 1)
        self.offs = np.stack(np.meshgrid(o, o, o, indexing="ij"), -1).reshape(-1, 3)

    # ---------------------------------------------------------------- geometry
    def inside(self, P, margin):
        nz, ny, nx = self.shape
        P = np.atleast_2d(P)
        return ((P[:, 0] >= margin) & (P[:, 0] <= nx - 1 - margin) & (P[:, 1] >= margin) & (P[:, 1] <= ny - 1 - margin)
                & (P[:, 2] >= margin) & (P[:, 2] <= nz - 1 - margin))

    def normals_at(self, P):
        """Structure-tensor normals (M, 3) xyz (sign arbitrary) and coherence (l1 - l2) / l1, for points P (M, 3) xyz."""
        P = np.atleast_2d(np.asarray(P, float))
        zyx = P[:, ::-1]
        nz, ny, nx = self.shape
        out_n, out_c = np.empty((len(P), 3)), np.empty(len(P))
        two_s2 = 2.0 * self.p.sigma_tensor ** 2
        for a in range(0, len(P), 128):
            q = zyx[a:a + 128]
            ii = np.rint(q)[:, None, :].astype(int) + self.offs[None]
            w = np.exp(-((ii - q[:, None, :]) ** 2).sum(-1) / two_s2)
            iz, iy, ix = (np.clip(ii[..., 0], 0, nz - 1), np.clip(ii[..., 1], 0, ny - 1), np.clip(ii[..., 2], 0, nx - 1))
            gv = np.stack([self.g[0][iz, iy, ix], self.g[1][iz, iy, ix], self.g[2][iz, iy, ix]], -1).astype(np.float64)
            S = np.einsum("mk,mki,mkj->mij", w, gv, gv)
            ev, evec = np.linalg.eigh(S)
            n = evec[:, :, 2][:, ::-1]
            out_n[a:a + 128] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            out_c[a:a + 128] = np.where(ev[:, 2] > 1e-12, (ev[:, 2] - ev[:, 1]) / np.maximum(ev[:, 2], 1e-12), 0.0)
        return out_n, out_c

    def profile(self, P, n, half):
        s = np.arange(-half, half + 1e-9, self.p.sample_step)
        c = P[:, None, :] + s[None, :, None] * n[:, None, :]
        pr = map_coordinates(self.vs, [c[..., 2], c[..., 1], c[..., 0]], order=1, mode="nearest")
        return s, pr

    def snap(self, P, n, window):
        """Nearest bright-sheet peak along n within +/- window. -> (P', offset, found, nearest_peak_offset)."""
        pad = 2.0
        s, pr = self.profile(P, n, window + pad)
        ds = self.p.sample_step
        newP, off, found, nearest = P.copy(), np.zeros(len(P)), np.zeros(len(P), bool), np.full(len(P), np.nan)
        for i in range(len(P)):
            pk, _ = find_peaks(pr[i], prominence=self.p.peak_prominence * self.contrast)
            if len(pk) == 0:
                continue
            nearest[i] = s[pk][np.argmin(np.abs(s[pk]))]
            pk = pk[np.abs(s[pk]) <= window + 1e-9]
            if len(pk) == 0:
                continue
            k = pk[np.lexsort((-pr[i][pk], np.abs(s[pk])))[0]]       # nearest to 0; ties: brighter
            d = 0.0
            if 0 < k < len(s) - 1:
                y0, y1, y2 = pr[i][k - 1], pr[i][k], pr[i][k + 1]
                den = y0 - 2 * y1 + y2
                if den < 0:
                    d = float(np.clip(0.5 * (y0 - y2) / den, -1, 1)) * ds
            off[i] = s[k] + d
            newP[i] = P[i] + off[i] * n[i]
            found[i] = True
        return newP, off, found, nearest

    # ---------------------------------------------------------------- pitch
    def measure_pitch(self, seed, n, global_pitch=False):
        """CT pitch at the seed with sheet_spacing_check.ct_pitches on the seed's z slice (reused, not copied)."""
        nxy = np.array([n[0], n[1]])
        L = np.linalg.norm(nxy)
        if L < 0.2:
            return float("nan")
        t = np.array([-nxy[1], nxy[0]]) / L
        k = np.arange(-4, 5) * 0.75
        xy = np.asarray(seed[:2], float)[None, :] + k[:, None] * t[None, :]
        line = ssc.Line(xy, np.arange(len(k)), np.zeros(len(k), int), np.zeros(len(k)))
        zi = int(round(seed[2]))
        tile = self.raw[zi].astype(np.float32)
        pp = ssc.ct_pitches(tile, (0, 0), line, 1.0, ssc.Params(global_pitch=global_pitch))
        pp = pp[np.isfinite(pp)]
        return float(np.median(pp)) if len(pp) else float("nan")


# ------------------------------------------------------------------------------------------------ growth
def _orient(n, ref):
    s = np.where((n * ref).sum(-1) < 0, -1.0, 1.0)
    return n * s[..., None]


def _tangents(n):
    """(t_row, t_col) for unit normals n (M, 3) xyz."""
    ax = np.zeros_like(n)
    ax[:, 2] = 1.0
    flat = np.abs(n[:, 2]) > 0.95
    ax[flat] = [0.0, 1.0, 0.0]
    tr = ax - (ax * n).sum(-1, keepdims=True) * n
    tr /= np.linalg.norm(tr, axis=1, keepdims=True)
    tc = np.cross(n, tr)
    tc /= np.linalg.norm(tc, axis=1, keepdims=True)
    return tr, tc


NB = ((-1, 0), (1, 0), (0, -1), (0, 1))


def trace(vol, seed_xyz, p: Params | None = None, tracer: Tracer | None = None, log=None):
    """Grow a patch. Returns a dict: points (R, C, 3) xyz float32 with -1 for none (window coordinates), accepted mask,
    ring index per cell, seed cell, pitch, step, rejections (list of dicts), rings (per-ring counts), stop_reason.
    Raises SeedError if the seed cannot start a patch."""
    p = p or Params()
    log = log or (lambda m: None)
    T = tracer or Tracer(vol, p)
    seed = np.asarray(seed_xyz, float)
    if not T.inside(seed, 0.0)[0]:
        raise SeedError(f"seed {seed.tolist()} is outside the volume (x,y,z < {T.shape[2]},{T.shape[1]},{T.shape[0]})")
    def canon(n, at):
        """Sign of the seed normal. With --axis-xy: away from the axis (REVIEW_ROUND2 T1: one handedness for every patch).
        Without: the largest component positive, so the direction the columns run depends on where the seed is."""
        if p.axis_xy is not None:
            out = np.asarray(at[:2], float) - np.asarray(p.axis_xy, float)
            return n * (1.0 if float(n[:2] @ out) >= 0 else -1.0)
        return n * (1.0 if n[int(np.argmax(np.abs(n)))] > 0 else -1.0)

    if p.axis_xy is None:
        log("warning: no --axis-xy: the direction the columns run (clockwise or counter-clockwise round the scroll) "
            "depends on where the seed is; patches grown from different seeds will have opposite handedness")
    n0, coh = T.normals_at(seed[None])
    n0 = canon(n0[0], seed)
    pitch = p.pitch_vox if p.pitch_vox else T.measure_pitch(seed, n0, p.global_pitch)
    if not np.isfinite(pitch) or pitch <= 0:
        raise SeedError("no sheet structure around the seed: the CT sheet pitch could not be measured (the seed is in a gap, "
                        "outside the scroll, or on a flat-lying sheet); move the seed onto a sheet or give --pitch-vox")
    if coh[0] < p.seed_min_coherence:
        raise SeedError(f"seed is not on a sheet: the structure tensor there is not planar (coherence {coh[0]:.2f} < "
                        f"{p.seed_min_coherence:g}); the seed is probably in a gap between sheets")
    s0, off0, found0, nearest0 = T.snap(seed[None], n0[None], p.seed_snap_pitch * pitch)
    if not found0[0]:
        d = nearest0[0]
        raise SeedError("seed is in a gap: no sheet peak within +/- %.1f voxels (%g x pitch %.1f) along the normal%s; "
                        "move the seed onto a sheet (the tracer never jumps to the neighbouring sheet)" % (
                            p.seed_snap_pitch * pitch, p.seed_snap_pitch, pitch,
                            "" if not np.isfinite(d) else f"; the nearest peak is {abs(d):.1f} voxels away"))
    n0 = canon(T.normals_at(s0)[0][0], s0[0])
    step = p.step_vox if p.step_vox else p.step_pitch_frac * pitch
    snapW = p.snap_pitch * pitch
    guard = p.guard_pitch * pitch
    grad = p.guard_grid_radius if p.guard_grid_radius is not None else int(math.ceil(guard / step)) + 1
    cos_max = math.cos(math.radians(p.max_normal_turn_deg))
    R, C = p.max_rows, p.max_cols
    if R < 1 or C < 1:
        raise ValueError("--max-rows and --max-cols must be >= 1")
    P = np.full((R, C, 3), np.nan)
    N = np.full((R, C, 3), np.nan)
    acc = np.zeros((R, C), bool)
    ringof = np.full((R, C), -1, int)
    sr, sc = R // 2, C // 2
    P[sr, sc], N[sr, sc], acc[sr, sc], ringof[sr, sc] = s0[0], n0, True, 0
    pending = set()

    def add_nb(r, c):
        for dr, dc in NB:
            rr, cc = r + dr, c + dc
            if 0 <= rr < R and 0 <= cc < C and not acc[rr, cc]:
                pending.add((rr, cc))

    add_nb(sr, sc)
    last_rej = {}
    rejections, rings = [], [dict(ring=0, front=1, accepted=1, rejected=0)]
    ring, stop = 0, None
    while True:
        cands = sorted(c for c in pending if not acc[c] and sum(
            1 for dr, dc in NB if 0 <= c[0] + dr < R and 0 <= c[1] + dc < C and acc[c[0] + dr, c[1] + dc]) > last_rej.get(c, 0))
        if not cands:
            stop = "max_rows_cols" if not pending else "ring_no_accepted"
            if not pending or all(sum(1 for dr, dc in NB if 0 <= c[0] + dr < R and 0 <= c[1] + dc < C and acc[c[0] + dr, c[1] + dc]) <= last_rej.get(c, 0) for c in pending):
                stop = "ring_no_accepted" if rings[-1]["accepted"] == 0 or pending else "max_rows_cols"
            break
        ring += 1
        snap_acc = acc.copy()
        pred, nref, nbl = [], [], []
        for (r, c) in cands:
            nbs = [(r + dr, c + dc, dr, dc) for dr, dc in NB if 0 <= r + dr < R and 0 <= c + dc < C and snap_acc[r + dr, c + dc]]
            nbl.append(nbs)
            pts, ns = [], []
            for rr, cc, dr, dc in nbs:
                tr, tc = _tangents(N[rr, cc][None])
                d = {(-1, 0): tr[0], (1, 0): -tr[0], (0, -1): tc[0], (0, 1): -tc[0]}[(dr, dc)]   # from neighbour toward (r, c)
                pts.append(P[rr, cc] + step * d)
                ns.append(N[rr, cc])
            pred.append(np.mean(pts, axis=0))
            nm = np.mean(ns, axis=0)
            nref.append(nm / max(np.linalg.norm(nm), 1e-12))
        pred, nref = np.array(pred), np.array(nref)
        ok_in = T.inside(pred, p.edge_margin)
        nn, _ = T.normals_at(pred)
        nn = _orient(nn, nref)
        P1, off, found, nearest = T.snap(pred, nn, snapW)
        n1, _ = T.normals_at(P1)
        n1 = _orient(n1, nref)
        tree = cKDTree(P[acc]) if acc.any() else None
        idx_acc = np.argwhere(acc)
        ring_pts, ring_idx = [], []
        n_ok = 0
        for i, (r, c) in enumerate(cands):
            def rej(reason, **detail):
                last_rej[(r, c)] = len(nbl[i])
                rejections.append(dict(ring=ring, row=r, col=c, reason=reason, n_neighbours=len(nbl[i]), **detail))

            if not ok_in[i]:
                rej("volume_edge", predicted=[round(float(v), 2) for v in pred[i]])
                continue
            if not found[i]:
                rej("no_peak", nearest_peak_offset_vox=None if not np.isfinite(nearest[i]) else round(float(nearest[i]), 2),
                    window_vox=round(snapW, 2))
                continue
            if not (np.isfinite(n1[i]).all() and np.isfinite(P1[i]).all()):
                rej("bad_normal")
                continue
            cosines = [float(np.dot(n1[i], N[rr, cc])) for rr, cc, _, _ in nbl[i]]
            if min(cosines) < cos_max:
                rej("normal_turn", angle_deg=round(math.degrees(math.acos(max(-1.0, min(cosines)))), 1))
                continue
            dists = [float(np.linalg.norm(P1[i] - P[rr, cc])) for rr, cc, _, _ in nbl[i]]
            if max(dists) > p.max_step_stretch * step:
                rej("step_stretch", distance_vox=round(max(dists), 2), step_vox=round(step, 2))
                continue
            hit = None
            if tree is not None:
                for j in tree.query_ball_point(P1[i], guard):
                    a, b = idx_acc[j]
                    if max(abs(a - r), abs(b - c)) > grad:
                        hit = (int(a), int(b), float(np.linalg.norm(P1[i] - P[a, b])))
                        break
            if hit is None:
                for (a, b), q in zip(ring_idx, ring_pts):
                    if max(abs(a - r), abs(b - c)) > grad and np.linalg.norm(P1[i] - q) < guard:
                        hit = (a, b, float(np.linalg.norm(P1[i] - q)))
                        break
            if hit is not None:
                rej("self_intersection", other_row=hit[0], other_col=hit[1], distance_vox=round(hit[2], 2), guard_vox=round(guard, 2))
                continue
            ring_pts.append(P1[i])
            ring_idx.append((r, c))
            P[r, c], N[r, c] = P1[i], n1[i]
            ringof[r, c] = ring
            n_ok += 1
        for (r, c) in ring_idx:
            acc[r, c] = True
            pending.discard((r, c))
            add_nb(r, c)
        rings.append(dict(ring=ring, front=len(cands), accepted=n_ok, rejected=len(cands) - n_ok))
        log(f"ring {ring}: front {len(cands)} accepted {n_ok} total {int(acc.sum())}")
        if n_ok == 0:
            stop = "ring_no_accepted"
            break
    out = np.where(acc[..., None], P, -1.0).astype(np.float32)
    return dict(points=out, accepted=acc, ring=ringof, seed_cell=(sr, sc), seed_snapped=s0[0].tolist(), seed_offset_vox=float(off0[0]),
                pitch=float(pitch), step=float(step), guard_vox=float(guard), snap_window_vox=float(snapW), guard_grid_radius=int(grad),
                contrast=T.contrast, rejections=rejections, rings=rings, stop_reason=stop,
                touches_window_edge=bool(acc[0].any() or acc[-1].any() or acc[:, 0].any() or acc[:, -1].any()))


# ------------------------------------------------------------------------------------------------ output
def crop(res):
    acc = res["accepted"]
    rr, cc = np.flatnonzero(acc.any(1)), np.flatnonzero(acc.any(0))
    r0, r1, c0, c1 = rr[0], rr[-1] + 1, cc[0], cc[-1] + 1
    return res["points"][r0:r1, c0:c1], (int(r0), int(c0))


def area_vx2(xyz):
    ok = xyz[..., 0] != -1
    q = ok[:-1, :-1] & ok[1:, :-1] & ok[:-1, 1:] & ok[1:, 1:]
    a, b, c, d = xyz[:-1, :-1], xyz[1:, :-1], xyz[:-1, 1:], xyz[1:, 1:]
    ar = 0.5 * (np.linalg.norm(np.cross(b - a, c - a), axis=-1) + np.linalg.norm(np.cross(d - b, d - c), axis=-1))
    return float(ar[q].sum())


def write_tifxyz(path, xyz, step, extra=None):
    import tifffile
    os.makedirs(path, exist_ok=True)
    xyz = np.asarray(xyz, np.float32)
    for k, ax in enumerate("xyz"):
        tifffile.imwrite(os.path.join(path, f"{ax}.tif"), np.ascontiguousarray(xyz[..., k]))
    ok = xyz[..., 0] != -1
    bbox = [xyz[ok].min(axis=0).tolist(), xyz[ok].max(axis=0).tolist()] if ok.any() else [[-1.0] * 3, [-1.0] * 3]
    meta = {"bbox": bbox, "format": "tifxyz", "scale": [1.0 / step, 1.0 / step], "type": "seg",
            "uuid": str(_uuid.uuid5(_uuid.NAMESPACE_URL, os.path.abspath(path))), "area_vx2": area_vx2(xyz), "source": "sheet_tracer"}
    meta.update(extra or {})
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=4)


def write_outputs(out, res, params, seed, volume_desc=""):
    xyz, off = crop(res)
    from collections import Counter
    summary = dict(tool_version=__version__, volume=volume_desc, seed_xyz=list(map(float, seed)), seed_snapped_xyz=res["seed_snapped"],
                   n_accepted=int(res["accepted"].sum()), grid_shape=list(xyz.shape[:2]), crop_offset_rc=list(off),
                   seed_cell_window_rc=list(res["seed_cell"]), pitch_vox=res["pitch"], step_vox=res["step"], guard_vox=res["guard_vox"],
                   snap_window_vox=res["snap_window_vox"], guard_grid_radius=res["guard_grid_radius"], stop_reason=res["stop_reason"],
                   touches_window_edge=res["touches_window_edge"], n_rejections=len(res["rejections"]),
                   rejections_by_reason=dict(Counter(r["reason"] for r in res["rejections"])), params=dataclasses.asdict(params))
    write_tifxyz(out, xyz, res["step"], extra={"tracer": {k: summary[k] for k in ("seed_xyz", "pitch_vox", "step_vox", "stop_reason")}})
    with open(os.path.join(out, "growth_log.json"), "w") as f:
        json.dump(dict(summary=summary, note="row/col in rejections are WINDOW coordinates; output index = window - crop_offset_rc",
                       rings=res["rings"], rejections=res["rejections"]), f, indent=1, default=float)
    return summary


def load_volume(a):
    if a.npy:
        return np.load(a.npy, mmap_mode="r"), a.npy
    import zarr
    g = zarr.open_group(a.zarr, mode="r")
    return np.asarray(g[str(a.zarr_level)][...]), f"{a.zarr} level {a.zarr_level}"


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr", help="OME-Zarr volume (level read fully into memory)")
    g.add_argument("--npy", help=".npy volume (z, y, x)")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--seed", type=float, nargs=3, required=True, metavar=("X", "Y", "Z"), help="seed voxel, XYZ (tifxyz order)")
    ap.add_argument("--out", required=True, help="output tifxyz directory")
    for f in dataclasses.fields(Params):
        v = f.default
        flag = "--" + f.name.replace("_", "-")
        if f.name in ("pitch_vox", "step_vox"):
            ap.add_argument(flag, type=float, default=None)
        elif f.name == "guard_grid_radius":
            ap.add_argument(flag, type=int, default=None)
        elif f.name == "axis_xy":
            ap.add_argument(flag, type=float, nargs=2, metavar=("X", "Y"), default=None,
                            help="scroll axis (x, y) in voxels: orient normals away from it (one handedness for all patches)")
        elif isinstance(v, bool):
            ap.add_argument(flag, action="store_true", help="(off by default)")
        else:
            ap.add_argument(flag, type=type(v), default=v)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    if p.axis_xy is not None:
        p.axis_xy = tuple(p.axis_xy)
    try:
        vol, desc = load_volume(a)
        res = trace(vol, a.seed, p, log=lambda m: print(m, file=sys.stderr))
    except SeedError as e:
        print(f"seed rejected: {e}", file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    s = write_outputs(a.out, res, p, a.seed, desc)
    print(json.dumps({k: s[k] for k in ("n_accepted", "grid_shape", "pitch_vox", "step_vox", "stop_reason", "rejections_by_reason")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
