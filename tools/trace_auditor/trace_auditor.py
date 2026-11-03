#!/usr/bin/env python3
"""trace_auditor: one command, one verdict per trace (PASS / FAIL / NOT JUDGED) with the reasons.  (MIT)

    python trace_auditor.py TRACE_A [TRACE_B] --zarr VOL.zarr [--umbilicus FILE] --out-dir DIR

Runs, on one or two tifxyz traces and a CT volume:
  * a centre line (a given umbilicus file, or umbilicus_finder on the volume);
  * sheet_switch_finder on every trace;
  * a winding-number check on every trace: each cut-line point is unwrapped to (angle, radius) about the
    centre; within one turn the radius must change smoothly with the angle, and a step of about one CT
    pitch is a sheet switch;
  * for two traces (A = the reference, B = the proposed neighbour): sheet_spacing_check, and the winding
    OFFSET of B against A at equal angle (about +-1 pitch for an adjacent sheet), which catches a trace
    that lies on the wrong sheet from its first point (invisible to a switch finder, there is no switch).
Every threshold is a flag (see README.md); the sub-tools' own constants are flags too (--ssf-*, --ssc-*, --uf-*).
Exit code: 0 all PASS, 1 any FAIL, 4 no FAIL but something NOT JUDGED, 2 bad input.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
from dataclasses import asdict, dataclass

import numpy as np

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _d in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "crush_map"):
    _p = os.path.join(_TOOLS, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import sheet_spacing_check as ssc  # noqa: E402
import sheet_switch_finder as ssf  # noqa: E402
import uf_io  # noqa: E402
import umbilicus_finder as uf  # noqa: E402
import crush_map as cmap  # noqa: E402  (tools/crush_map: CrushMap reader for --crush-map)
from ssc_io import ArrayVolume, InputError, PngVolume, ZarrVolume, load_mesh  # noqa: E402

__version__ = "0.2.1"
PASS, FAIL, NJ = "PASS", "FAIL", "NOT JUDGED"


@dataclass
class Params:
    # --- which heights
    n_heights: int = 5                      # auto heights: this many, evenly spaced over the z range both traces cover
    height_margin: float = 0.10             # ... after trimming this fraction of that range at each end
    # --- centre line
    centre_z_step: float = 32.0             # umbilicus_finder z step (voxels) when the centre is estimated
    centre_max_gap: float = 1.5             # a height is judged only if an OK centre slice lies within this x z step
    umbilicus_scale: float = 1.0            # multiplies the coordinates of a given umbilicus file (to level-0 voxels)
    # --- switch finder verdict
    min_switch_confidence: float = 0.3      # a switch counts (-> FAIL) at or above this confidence
    min_tracked_fraction: float = 0.6       # a height is judged only if the finder tracked at least this fraction
    max_unjudged_height_fraction: float = 0.5   # more unjudged heights than this -> the check is NOT JUDGED
    # --- winding-number check (jumps within one trace)
    wn_jump_pitch: float = 0.6              # a radius step of at least this many CT pitches is a jump
    wn_window_deg: float = 20.0             # the step is the mean radius of this many degrees after minus before
    wn_window_min_points: int = 3           # ... each window needs at least this many cut-line points
    wn_slope_mismatch: float = 1.0          # if the two windows' own slopes differ by more than this x the jump threshold (over half a window), use the offset of two separately fitted lines
    wn_min_points: int = 12                 # a cut-line run needs at least this many points
    wn_min_span_deg: float = 60.0           # ... and to span at least this many degrees
    wn_monotonic: float = 0.95              # fraction of steps that must go the same way in angle (else not judged)
    # --- pair (B against A)
    wn_pair_lo: float = 0.5                 # adjacent: |offset| of B from the nearest A sheet in pitches, at least (same as sheet_spacing_check ratio_min) ...
    wn_pair_hi: float = 1.5                 # ... and at most
    wn_pair_frac: float = 0.8               # fraction of B points that must be adjacent
    min_clean_fraction: float = 0.8         # sheet_spacing_check: mean clean fraction over heights
    expect_side: str = "either"             # 'either', 'outward' (B further out than A) or 'inward'
    pitch_vox: float | None = None          # override the measured CT pitch (voxels)
    # --- v0.2: local pitch confidence -> NOT JUDGED regions (PR #17 finding 6: on real data every trace FAILed, the unbroken ones too)
    global_pitch: bool = False              # OLD behaviour: no confidence, every region judged, one-estimator pitch (also forwarded to --ssf-/--ssc-)
    min_pitch_confidence: float = 0.3       # a region whose median local-pitch confidence is below this is NOT JUDGED (judgement call; see the PR)
    region_points: int = 15                 # a region = this many consecutive cut-line points (tumbling windows along each run)
    min_judged_fraction: float = 0.5        # PASS needs at least this fraction of the cut line judged; below it the verdict is NOT JUDGED
    crush_map: str | None = None            # crush_map.npz from tools/crush_map: regions whose crush severity is at or above --max-crush-severity are NOT JUDGED
    windcheck: bool = False                 # add one more verdict, 'windcheck': self-intersection (windcheck engine) + CT off-sheet check (tools/upstream/windcheck); flags --wc-*
    max_crush_severity: float = 0.5         # judgement call (see the PR); severity 0..1, 1 = local spacing reduced 4x or more


def _sub_flags(ap, prefix, cls, skip=()):
    for f in dataclasses.fields(cls):
        if f.name in skip:
            continue
        v = f.default
        if isinstance(v, bool):
            ap.add_argument(f"--{prefix}-" + f.name.replace("_", "-"), dest=f"{prefix}__{f.name}", action="store_const", const=True,
                            default=None, help=f"{cls.__module__}.Params.{f.name} (default {v})")
            continue
        t = float if v is None else type(v)
        ap.add_argument(f"--{prefix}-" + f.name.replace("_", "-"), dest=f"{prefix}__{f.name}", type=t, default=None,
                        help=f"{cls.__module__}.Params.{f.name} (default {v})")


def _sub_params(a, prefix, cls, **fixed):
    kw = {f.name: getattr(a, f"{prefix}__{f.name}") for f in dataclasses.fields(cls)
          if getattr(a, f"{prefix}__{f.name}", None) is not None}
    kw.update(fixed)
    return cls(**kw)


def _wc_flags(ap):
    """--wc-* : ct_aware_check.Params (only used with --windcheck)."""
    d = os.path.join(_TOOLS, "upstream", "windcheck")
    if d not in sys.path:
        sys.path.insert(0, d)
    import ct_aware_check as wc
    _sub_flags(ap, "wc", wc.Params)


# ------------------------------------------------------------------------------ centre line
class Centre:
    """z -> (y, x) of the scroll axis from control points; judged only near a control point."""

    def __init__(self, z, y, x, source, max_gap):
        o = np.argsort(z)
        self.z, self.y, self.x = np.asarray(z, float)[o], np.asarray(y, float)[o], np.asarray(x, float)[o]
        self.source, self.max_gap = source, float(max_gap)

    def at(self, z0):
        """(y, x) or None when z0 is outside the control points or further than max_gap from the nearest one."""
        if len(self.z) < 2 or not (self.z[0] <= z0 <= self.z[-1]):
            return None
        if np.min(np.abs(self.z - z0)) > self.max_gap:
            return None
        return float(np.interp(z0, self.z, self.y)), float(np.interp(z0, self.z, self.x))


def read_umbilicus(path, fmt="auto", scale=1.0):
    """(z, y, x) arrays from a villa 'control_points' JSON, a native vc_umbilicus JSON, 'z, y, x' text or the
    villa 'thaumato' text (y, z, x, each + 500). See docs/FORMATS.md."""
    p = str(path)
    if not os.path.isfile(p):
        raise InputError(f"umbilicus file not found: {p}")
    if fmt == "auto":
        if not p.lower().endswith(".json"):
            raise InputError("a text umbilicus needs --umbilicus-format zyx-text or thaumato (the two orders differ)")
        fmt = "json"
    try:
        if fmt in ("json", "villa-json", "native-json"):
            doc = json.load(open(p))
            arr = doc if isinstance(doc, list) else doc.get("control_points", doc.get("points"))
            if arr is None:
                raise InputError(f"{p}: no 'control_points' or 'points' array")
            rows = [(e["z"], e["y"], e["x"]) if isinstance(e, dict) else (e[0], e[1], e[2]) for e in arr]
        elif fmt in ("zyx-text", "thaumato"):
            rows = []
            for ln in open(p):
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                v = [float(t) for t in ln.replace(" ", "").split(",")]
                if len(v) != 3:
                    raise InputError(f"{p}: expected 3 comma-separated numbers per line, got {ln!r}")
                rows.append((v[0], v[1], v[2]) if fmt == "zyx-text" else (v[1] - 500, v[0] - 500, v[2] - 500))
        else:
            raise InputError(f"unknown umbilicus format {fmt!r}")
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise InputError(f"cannot read umbilicus {p}: {e!r}") from e
    a = np.asarray(rows, float) * scale
    if len(a) < 2 or not np.isfinite(a).all():
        raise InputError(f"{p}: need at least two finite control points")
    return a[:, 0], a[:, 1], a[:, 2]


def estimate_centre(uf_vol, z_lo, z_hi, p: Params, uf_params, log=None):
    extent = uf_vol.shape[0] * uf_vol.scale_z
    z0, z1 = max(0.0, z_lo), min(extent, z_hi)
    rows, summ = uf.run(uf_vol, uf_params, z_start=z0, z_stop=max(z1, z0 + 1e-3), z_step=p.centre_z_step)
    ok = [r for r in rows if r["flag"] == "OK" and np.isfinite(r["y"])]
    info = dict(n_slices=len(rows), n_ok=len(ok), pitch_vox=summ["pitch_vox"])
    if len(ok) < 2:
        return None, info
    return (np.array([r["z"] for r in ok]), np.array([r["y"] for r in ok]), np.array([r["x"] for r in ok])), info


# ------------------------------------------------------------------------------ winding numbers
def detect_jumps(theta, r, pitch, p: Params):
    """Radius steps of >= wn_jump_pitch * pitch along a cut line unwrapped in angle.

    theta: unwrapped angle (rad) along the line (any monotone direction), r: radius (voxels).
    At each gap between points the step is mean(r) of the next wn_window_deg minus mean(r) of the previous
    wn_window_deg, minus the local spiral slope (median dr/dtheta in both windows, robust to the step itself)
    times the angle between the window centres. A bend of the sheet (the long axis of a squashed scroll, 4-7 degrees
    per point on a sheet_tracer patch) changes the slope between the two windows, which the common slope cannot
    absorb: where the windows' own slopes differ by more than wn_slope_mismatch x the threshold over half a window (1.0: enough to explain a whole threshold; 0.3 also swallowed the benchmark ramp)
    the step is instead the offset of two straight lines fitted separately to the two windows, evaluated at the
    gap (REVIEW_ROUND2 A1: the common-slope estimate read such a bend as a step of 0.61 pitch where the adjacent
    points differed by 0.4 voxel). Windows are cut at the ends of the line, not skipped (A2): a step needs
    wn_window_min_points points on each side. Returns [dict(index, step, pitches)] one per cluster
    (index = first point after the step, in line order)."""
    n = len(theta)
    pitch = np.broadcast_to(np.asarray(pitch, float), (n,))          # local CT pitch per point (scalar allowed)
    sgn = 1.0 if theta[-1] >= theta[0] else -1.0
    t = sgn * np.asarray(theta, float)
    win = math.radians(p.wn_window_deg)
    cand = []
    for i in range(1, n):
        tc = 0.5 * (t[i - 1] + t[i])
        lo, hi = int(np.searchsorted(t, tc - win)), int(np.searchsorted(t, tc + win, side="right"))
        if i - lo < p.wn_window_min_points or hi - i < p.wn_window_min_points:
            continue
        dt = np.diff(t[lo:hi])
        dr = np.diff(r[lo:hi])
        keep = np.ones(len(dt), bool)
        keep[i - lo - 1] = False                                    # the pair that straddles the candidate step
        keep &= dt > 1e-9
        slope = float(np.median(dr[keep] / dt[keep])) if keep.any() else 0.0
        step = (r[i:hi].mean() - r[lo:i].mean()) - slope * (t[i:hi].mean() - t[lo:i].mean())
        thr = p.wn_jump_pitch * pitch[i]
        if abs(step) >= thr:                                        # only a candidate pays for the two line fits
            fa = np.polyfit(t[lo:i] - tc, r[lo:i], 1)
            fb = np.polyfit(t[i:hi] - tc, r[i:hi], 1)
            if abs(fb[0] - fa[0]) * win / 2 > p.wn_slope_mismatch * thr:
                step = float(fb[1] - fa[1])                         # the windows bend: compare the lines at the gap
        if abs(step) >= thr:
            cand.append((i, float(step)))
    out = []
    for i, s in cand:                                               # one event per run of neighbouring candidates
        if out and i - out[-1]["_last"] <= 1 and (s > 0) == (out[-1]["step"] > 0):
            out[-1]["_last"] = i
            if abs(s) > abs(out[-1]["step"]):
                out[-1].update(index=i, step=s)
            continue
        out.append(dict(index=i, step=s, _last=i))
    for o in out:
        o.pop("_last")
        o["step"] = float(o["step"])                                # + = radius grows along the line (point order)
        o["pitches"] = float(o["step"] / pitch[o["index"]])
    return out


def local_pitch(vol, line, z0, ssf_p, override=None):
    """CT sheet pitch (voxels) at every cut-line point: the per-point median peak spacing of sheet_spacing_check,
    gaps filled from the nearest measured point and smoothed (running median of 15 points). None if nowhere measurable.
    A crushed scroll has a sheet spacing that varies several-fold round the turn; a single pitch per height would not do."""
    if line.n == 0:
        return None
    if override:
        return np.full(line.n, float(override))
    from scipy.ndimage import median_filter
    tile, origin = ssf._tile_for(vol, line, ssf_p.profile_halflen_vox, ssf_p, z0)
    pp = ssc.ct_pitches(tile, origin, line, vol.ct_scale, ssf_p.ssc(float("inf")))
    ok = np.isfinite(pp)
    if not ok.any():
        return None
    pp = np.interp(np.arange(line.n), np.flatnonzero(ok), pp[ok])
    return median_filter(pp, size=15, mode="nearest")


def judged_regions(conf, run, region_points, min_conf, severity=None, max_severity=None):
    """Boolean per point: True where the REGION (a tumbling window of `region_points` consecutive points of one run) has a
    median local-pitch confidence of at least `min_conf` and, if a crush-map `severity` per point is given, a median severity (over
    the points that have one) below `max_severity`. conf None = no confidence test (override / --global-pitch)."""
    n = len(run)
    c = np.ones(n) if conf is None else np.nan_to_num(np.asarray(conf, float), nan=0.0)
    out = np.zeros(n, bool)
    for s, e in ssc._run_bounds(run):
        for i in range(s, e, max(1, region_points)):
            j = min(e, i + max(1, region_points))
            ok = float(np.median(c[i:j])) >= min_conf if conf is not None else True
            if ok and severity is not None and max_severity is not None:
                sv = np.asarray(severity[i:j], float)
                sv = sv[np.isfinite(sv)]
                if len(sv) and float(np.median(sv)) >= max_severity:
                    ok = False
            out[i:j] = ok
    return out


def _col_lookup(cols, mask):
    return {int(c): bool(m) for c, m in zip(cols, mask)}


def _judged_at(table, col, reach=2):
    """Judged flag of grid column `col` (nearest cut point within `reach` columns); False if the trace has none there."""
    for d in sorted(range(-reach, reach + 1), key=abs):
        if int(col) + d in table:
            return table[int(col) + d]
    return False


def cut_polar(line, centre_yx, pitch, judged=None):
    """Cut line as runs of (col, angle unwrapped, radius, xy, pitch, judged). Runs are consecutive columns."""
    cy, cx = centre_yx
    runs = []
    for s, e in ssc._run_bounds(line.run):
        xy = line.xy[s:e]
        ang = np.unwrap(np.arctan2(xy[:, 1] - cy, xy[:, 0] - cx))
        runs.append(dict(col=line.col[s:e], theta=ang, r=np.hypot(xy[:, 0] - cx, xy[:, 1] - cy), xy=xy, pitch=pitch[s:e],
                         judged=np.ones(e - s, bool) if judged is None else judged[s:e]))
    return runs


def winding_check_height(line, centre, pitch, p: Params, judged=None):
    """-> dict(status, reason, jumps=[...], runs=[...]) for one trace at one height (pitch: per cut-line point). Jumps in regions
    that are not judged (`judged` per point) are left out and counted in `n_jumps_unjudged`."""
    runs = cut_polar(line, centre, pitch, judged)
    if not runs:
        return dict(status=NJ, reason="trace has no cut line at this height", jumps=[], runs=[])
    jumps, judged, why, skipped_jumps = [], 0, [], 0
    for ru in runs:
        th = ru["theta"]
        n = len(th)
        span = math.degrees(abs(th[-1] - th[0])) if n else 0.0
        if n < p.wn_min_points or span < p.wn_min_span_deg:
            why.append(f"run of {n} points / {span:.0f} deg is too short")
            continue
        d = np.diff(th)
        if np.mean(np.sign(d) == np.sign(th[-1] - th[0])) < p.wn_monotonic:
            why.append("angle is not monotonic along the line (the trace folds back)")
            continue
        judged += 1
        for j in detect_jumps(th, ru["r"], ru["pitch"], p):
            if not ru["judged"][j["index"]]:
                skipped_jumps += 1
                continue
            jumps.append(dict(col=int(ru["col"][j["index"]]), angle_deg=float(math.degrees(th[j["index"]]) % 360.0),
                              step_vox=j["step"], step_pitches=j["pitches"],
                              x=float(ru["xy"][j["index"], 0]), y=float(ru["xy"][j["index"], 1])))
    if judged == 0:
        return dict(status=NJ, reason="; ".join(why) or "no usable run", jumps=[], runs=runs, n_jumps_unjudged=skipped_jumps)
    if not any(ru["judged"].any() for ru in runs):
        return dict(status=NJ, reason="local pitch confidence too low everywhere on this line", jumps=[], runs=runs,
                    n_jumps_unjudged=skipped_jumps)
    return dict(status=FAIL if jumps else PASS, reason="", jumps=jumps, runs=runs, n_jumps_unjudged=skipped_jumps)


def pair_offsets(runs_a, runs_b):
    """Radial offset of every B point from the nearest A sheet at the same angle: array of (r_B - r_A) in voxels
    (nan where A has no sheet at that angle). A is a polyline per run; a multi-turn A has several sheets per angle."""
    segs = []
    for ru in runs_a:
        th = np.mod(ru["theta"], 2 * math.pi)
        for k in range(len(th) - 1):
            a0, a1 = th[k], th[k + 1]
            d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi           # signed short way round
            segs.append((a0, d, ru["r"][k], ru["r"][k + 1]))
    out = []
    for ru in runs_b:
        thb = np.mod(ru["theta"], 2 * math.pi)
        for ang, rb in zip(thb, ru["r"]):
            best = np.nan
            cand = []
            for a0, d, r0, r1 in segs:
                u = ((ang - a0 + math.pi) % (2 * math.pi) - math.pi)
                f = u / d if abs(d) > 1e-12 else np.nan
                if np.isfinite(f) and 0.0 <= f <= 1.0:
                    cand.append(rb - (r0 + f * (r1 - r0)))
            if cand:
                best = min(cand, key=abs)
            out.append(best)
    return np.asarray(out, float)


# ------------------------------------------------------------------------------ the audit
def auto_heights(meshes, p: Params):
    lo, hi = -math.inf, math.inf
    for m in meshes:
        z = m.z[m.valid]
        if not z.size:
            raise InputError(f"trace {m.name} has no valid points")
        lo, hi = max(lo, float(z.min())), min(hi, float(z.max()))
    if hi <= lo:
        raise InputError("the traces share no z range; pass --heights")
    span = hi - lo
    a, b = lo + p.height_margin * span, hi - p.height_margin * span
    n = max(1, p.n_heights)
    return [float(round(v)) for v in (np.linspace(a, b, n) if n > 1 else [(a + b) / 2])]


def _check(name, status, reason, **extra):
    return dict(check=name, status=status, reason=reason, **extra)


def _windcheck_checks(meshes, vol, pitches, p: Params, wc_p, log=None):
    """One 'windcheck' check per mesh: tools/upstream/windcheck/ct_aware_check (self-intersection + off-sheet), merged into one status."""
    d = os.path.join(_TOOLS, "upstream", "windcheck")
    if d not in sys.path:
        sys.path.insert(0, d)
    import ct_aware_check as wc
    wp = wc_p or wc.Params()
    meas = [v for v in pitches.values() if v and np.isfinite(v)]
    if not wp.pitch_vox and (p.pitch_vox or meas):
        wp = dataclasses.replace(wp, pitch_vox=float(p.pitch_vox or np.median(meas)))
    data = getattr(vol, "data", None)
    out = []
    for m in meshes:
        if log:
            log(f"windcheck (self-intersection + off-sheet) on {m.name}")
        P, valid = wc.mesh_arrays(m)
        res = wc.check_trace(P, valid, data, wp, getattr(vol, "ct_scale", 1.0))
        sub = res["checks"]
        if data is None:
            sub = sub + [dict(check="off_sheet", status=NJ, reason="this CT input has no 3-D array access (PNG directory): off-sheet not run")]
        st = [c["status"] for c in sub]
        status = FAIL if FAIL in st else (NJ if NJ in st else PASS)
        bad = [c for c in sub if c["status"] != PASS] or sub
        out.append(dict(check="windcheck", status=status, reason="; ".join(f"{c['check']}: {c['reason']}" for c in bad),
                        parts=[{k: v for k, v in c.items() if k not in ("events", "off_sample")} for c in sub]))
    return out


def audit(meshes, vol, heights, centre, p: Params, ssf_p, ssc_p, log=None, wc_p=None):
    """Returns the report dict. meshes = [A] or [A, B]."""
    log = log or (lambda m: None)
    if p.global_pitch:                                         # one flag switches the whole auditor back to the old pitch handling
        ssf_p, ssc_p = dataclasses.replace(ssf_p, global_pitch=True), dataclasses.replace(ssc_p, global_pitch=True)
    crush = cmap.CrushMap(p.crush_map) if p.crush_map else None
    traces = [dict(name=m.name, checks=[], heights=[], judged_fraction=0.0) for m in meshes]
    pitches = {}                                               # (trace index, height) -> pitch
    # ---- switch finder + winding jumps per trace
    polar = {}
    for ti, m in enumerate(meshes):
        log(f"sheet_switch_finder on {m.name}")
        res = ssf.run_finder(m, vol, heights, ssf_p, want_states=True)
        states = res.pop("states")
        recs = {r["z"]: r for r in res["heights"]}
        # regions whose local-pitch confidence is too low are NOT JUDGED: their switches and jumps do not count
        jarr, jtab, tot_pts, ok_pts = {}, {}, 0, 0
        for h in heights:
            stt = states.get(float(h))
            if stt is None:
                continue
            sev_pt = crush.at(float(h), stt["line"].xy) if crush is not None else None
            jm = judged_regions(stt["pitch_conf"], stt["line"].run, p.region_points, p.min_pitch_confidence, sev_pt, p.max_crush_severity)
            jarr[float(h)], jtab[float(h)] = jm, _col_lookup(stt["line"].col, jm)
            tot_pts, ok_pts = tot_pts + len(jm), ok_pts + int(jm.sum())
        traces[ti]["judged_fraction"] = (ok_pts / tot_pts) if tot_pts else 0.0
        cand_sw = [s for s in res["switches"] if s["confidence"] >= p.min_switch_confidence]
        bad_sw = [s for s in cand_sw if _judged_at(jtab.get(float(s["height"]), {}), s["col"])]
        unj_sw = len(cand_sw) - len(bad_sw)
        judged = [h for h in heights if recs[float(h)]["n_points"] > 0 and not recs[float(h)]["note"]
                  and recs[float(h)]["fraction_tracked"] >= p.min_tracked_fraction]
        unj = len(heights) - len(judged)
        if bad_sw:
            traces[ti]["checks"].append(_check("switch_finder", FAIL, "; ".join(
                f"{s['kind']} switch at z={s['height']:g} col {s['col']} row {s['row']:.1f} "
                f"({s['direction']}, step {s['step']:+.2f} pitch, confidence {s['confidence']:.2f})" for s in bad_sw),
                switches=bad_sw))
        elif unj > p.max_unjudged_height_fraction * len(heights):
            traces[ti]["checks"].append(_check("switch_finder", NJ, f"only {len(judged)} of {len(heights)} heights could be "
                                               f"followed (tracked fraction >= {p.min_tracked_fraction:g}); " + "; ".join(
                                                   f"z={h:g}: {recs[float(h)]['note'] or 'tracked ' + format(recs[float(h)]['fraction_tracked'], '.2f')}"
                                                   for h in heights if h not in judged)))
        else:
            traces[ti]["checks"].append(_check("switch_finder", PASS, f"no switch at {len(judged)} judged heights" + (
                f" ({unj_sw} switch(es) of confidence >= {p.min_switch_confidence:g} lie in regions whose local pitch is not "
                f"trusted and are not counted)" if unj_sw else "")))
        for h in heights:
            r = recs[float(h)]
            pitches[(ti, float(h))] = p.pitch_vox or r["ct_pitch_vox"]
            traces[ti]["heights"].append(dict(z=float(h), tracked=r["fraction_tracked"], pitch=r["ct_pitch_vox"],
                                              n_switches=r["n_switches"], pitch_confidence=r.get("pitch_confidence_mean"),
                                              judged_fraction=float(jarr[float(h)].mean()) if float(h) in jarr else 0.0))
        # ---- winding jumps
        log(f"winding-number check on {m.name}")
        sp = ssc.Params(max_gap_vox=float("inf"), invalid_value=ssf_p.invalid_value)
        wres, unj_w, fails = [], 0, []
        for h in heights:
            c = centre.at(float(h)) if centre else None
            line = ssc.cut_line(m, float(h), sp)
            stp = states.get(float(h))
            if c is None:
                parr = None
            elif (not p.global_pitch) and p.pitch_vox is None and stp is not None and len(stp["pitch_pp"]) == line.n:
                parr = stp["pitch_pp"]                          # the finder's local pitch (tilt-filtered normals, smoothed)
            else:
                parr = local_pitch(vol, line, float(h), ssf_p, p.pitch_vox)
            if c is None or parr is None:
                unj_w += 1
                wres.append(dict(z=float(h), status=NJ, reason="no centre here" if c is None else
                                 ("no cut line at this height" if line.n == 0 else "no CT pitch")))
                continue
            w = winding_check_height(line, c, parr, p, jarr.get(float(h)) if len(jarr.get(float(h), [])) == line.n else None)
            polar[(ti, float(h))] = (w["runs"], c, float(np.median(parr)), w["jumps"])
            wres.append(dict(z=float(h), status=w["status"], reason=w["reason"], jumps=w["jumps"],
                             n_jumps_unjudged=w.get("n_jumps_unjudged", 0)))
            unj_w += w["status"] == NJ
            fails += [dict(z=float(h), **j) for j in w["jumps"]]
        if fails:
            traces[ti]["checks"].append(_check("winding_jumps", FAIL, "; ".join(
                f"radius jumps {j['step_pitches']:+.2f} pitch at z={j['z']:g}, col {j['col']}, angle {j['angle_deg']:.0f} deg"
                for j in fails), jumps=fails, heights=wres))
        elif unj_w > p.max_unjudged_height_fraction * len(heights):
            traces[ti]["checks"].append(_check("winding_jumps", NJ, f"{unj_w} of {len(heights)} heights not judged: " + "; ".join(
                f"z={w['z']:g}: {w['reason']}" for w in wres if w["status"] == NJ), heights=wres))
        else:
            skipped = sum(w.get("n_jumps_unjudged", 0) for w in wres)
            traces[ti]["checks"].append(_check("winding_jumps", PASS, f"no radius jump at {len(heights) - unj_w} judged heights" + (
                f" ({skipped} jump(s) lie in regions whose local pitch is not trusted and are not counted)" if skipped else ""),
                heights=wres))
    pair = None
    if len(meshes) == 2:
        A, B = meshes
        # ---- sheet_spacing_check
        log("sheet_spacing_check")
        try:
            if ssc_p.band_height_vox is None and len(heights) < 2:
                ssc_p = dataclasses.replace(ssc_p, band_height_vox=1.0)
            rs = ssc.run_check(A, B, vol, heights, ssc_p)
            hh = [h for h in rs["heights"] if h["n_points_a"] and h["n_points_b"]]
            n_all = len(hh)
            if not ssc_p.global_pitch:                          # heights whose local pitch is not trusted are not judged
                hh = [h for h in hh if h.get("pitch_confidence_mean", 0.0) >= p.min_pitch_confidence]
            if not hh:
                sc = _check("spacing", NJ, "no height where both traces have a cut line" if not n_all else
                            f"local pitch confidence below {p.min_pitch_confidence:g} at all {n_all} heights")
            else:
                clean = float(np.mean([h["clean_fraction"] for h in hh]))
                sh, sk, un = (float(np.mean([h[k] for h in hh])) for k in ("shared_fraction", "skipped_fraction", "uncovered_fraction"))
                msg = (f"clean {100 * clean:.0f}% (shared {100 * sh:.0f}%, skipped {100 * sk:.0f}%, "
                       f"B missing {100 * un:.0f}%) over {len(hh)} heights")
                sc = _check("spacing", PASS if clean >= p.min_clean_fraction else FAIL, msg, clean_fraction=clean,
                            shared=sh, skipped=sk, uncovered=un, warnings=rs["warnings"])
        except InputError as e:
            sc = _check("spacing", NJ, str(e))
        # ---- winding offset of B against A
        offs, rows = [], []
        for h in heights:
            ka, kb = (0, float(h)), (1, float(h))
            if ka not in polar or kb not in polar:
                rows.append(dict(z=float(h), status=NJ, reason="no centre / pitch / usable cut line for both traces"))
                continue
            ra, c, pa, _ = polar[ka]
            rb, _, pb, _ = polar[kb]
            pit = np.concatenate([ru["pitch"] for ru in rb])         # B's local pitch at each of its points
            d = pair_offsets(ra, rb) / pit
            d = np.where(np.concatenate([ru["judged"] for ru in rb]), d, np.nan)     # B points in regions not judged are left out
            d = d[np.isfinite(d)]
            if d.size == 0:
                rows.append(dict(z=float(h), status=NJ, reason="A has no sheet at the angles of B (or B's local pitch is not trusted there)"))
                continue
            near = np.abs(d)
            sign_ok = np.ones(d.size, bool) if p.expect_side == "either" else (
                d > 0 if p.expect_side == "outward" else d < 0)
            ok = (near >= p.wn_pair_lo) & (near <= p.wn_pair_hi) & sign_ok
            rows.append(dict(z=float(h), status=PASS if ok.mean() >= p.wn_pair_frac else FAIL, n=int(d.size),
                             adjacent_fraction=float(ok.mean()), median_offset_pitches=float(np.median(d)),
                             integer_offset=int(round(float(np.median(d))))))
            offs.append(rows[-1])
        failed = [r for r in rows if r["status"] == FAIL]
        if failed:
            wo = _check("winding_offset", FAIL, "; ".join(
                f"z={r['z']:g}: B is {r['median_offset_pitches']:+.2f} pitch from the nearest A sheet "
                f"(whole sheets: {r['integer_offset']:+d}), only {100 * r['adjacent_fraction']:.0f}% of its points are adjacent"
                for r in failed), heights=rows)
        elif not offs:
            wo = _check("winding_offset", NJ, "no height judged: " + "; ".join(f"z={r['z']:g}: {r['reason']}" for r in rows), heights=rows)
        else:
            wo = _check("winding_offset", PASS, f"B is an adjacent sheet of A at {len(offs)} judged heights "
                        f"(median offset {np.median([r['median_offset_pitches'] for r in offs]):+.2f} pitch)", heights=rows)
        traces[1]["checks"] += [sc, wo]
        pair = dict(a=A.name, b=B.name, spacing=sc, winding_offset=wo)
    if p.windcheck:
        traces_wc = _windcheck_checks(meshes, vol, pitches, p, wc_p, log)
        for t, c in zip(traces, traces_wc):
            t["checks"].append(c)
    for t in traces:
        if not any(c["status"] == FAIL for c in t["checks"]) and t["judged_fraction"] < p.min_judged_fraction:
            t["checks"].append(_check("pitch_confidence", NJ, f"only {100 * t['judged_fraction']:.0f}% of the cut line has a trusted local "
                                      f"pitch (confidence >= {p.min_pitch_confidence:g} over {p.region_points} points; need "
                                      f"{100 * p.min_judged_fraction:.0f}%): a PASS would mean nothing here"))
        st = [c["status"] for c in t["checks"]]
        t["verdict"] = FAIL if FAIL in st else (NJ if NJ in st else PASS)
        t["reasons"] = [f"{c['check']}: {c['reason']}" for c in t["checks"] if c["status"] != PASS] or \
                       [f"{c['check']}: {c['reason']}" for c in t["checks"]]
    return dict(traces=traces, pair=pair, polar=polar)


# ------------------------------------------------------------------------------ output
def text_report(rep, inputs):
    out = [f"trace_auditor {__version__}", f"CT: {inputs['ct']}   centre: {inputs['centre']}   heights: "
           + ", ".join(f"{h:g}" for h in inputs["heights"]), ""]
    for t in rep["traces"]:
        out.append(f"{t['name']}: {t['verdict']}   (judged {100 * t['judged_fraction']:.0f}% of the cut line)")
        for c in t["checks"]:
            out.append(f"    [{c['status']:<10}] {c['check']}: {c['reason']}")
    for w in inputs.get("warnings", []):
        out.append(f"warning: {w}")
    return "\n".join(out) + "\n"


def write_pngs(rep, out_dir, names):
    """Radius vs unwrapped angle per trace and height; jumps in red."""
    from PIL import Image, ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    for (ti, h), (runs, c, pit, jumps) in rep["polar"].items():
        W, H, m = 900, 320, 30
        im = Image.new("RGB", (W, H), (20, 20, 20))
        d = ImageDraw.Draw(im)
        allt = np.concatenate([np.degrees(r["theta"]) for r in runs]) if runs else np.zeros(1)
        allr = np.concatenate([r["r"] for r in runs]) if runs else np.zeros(1)
        t0, t1, r0, r1 = allt.min(), allt.max() + 1e-9, allr.min() - pit * 0.2, allr.max() + pit * 0.2
        X = lambda t: m + (t - t0) / (t1 - t0) * (W - 2 * m)    # noqa: E731
        Y = lambda r: H - m - (r - r0) / (r1 - r0) * (H - 2 * m)  # noqa: E731
        for r in runs:
            d.line([(X(np.degrees(a)), Y(b)) for a, b in zip(r["theta"], r["r"])], fill=(90, 200, 90), width=2)
        for j in jumps:
            for r in runs:
                k = np.nonzero(r["col"] == j["col"])[0]
                if k.size:
                    d.ellipse([X(np.degrees(r["theta"][k[0]])) - 6, Y(r["r"][k[0]]) - 6,
                               X(np.degrees(r["theta"][k[0]])) + 6, Y(r["r"][k[0]]) + 6], outline=(255, 60, 60), width=2)
        d.text((m, 4), f"{names[ti]} z={h:g}  radius (vox) vs unwrapped angle (deg); pitch {pit:.1f}; jumps {len(jumps)}",
               fill=(255, 255, 0))
        im.save(os.path.join(out_dir, f"winding_{ti}_z{int(h):06d}.png"))


# ------------------------------------------------------------------------------ CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("trace_a", help="tifxyz folder: the trace to audit, or the reference when B is given")
    ap.add_argument("trace_b", nargs="?", help="tifxyz folder: the proposed neighbour of A (optional)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr")
    g.add_argument("--png-dir")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--png-pixel-um", type=float)
    ap.add_argument("--png-pattern", default="{z:05d}.png")
    ap.add_argument("--voxel-size-um", type=float, help="mesh voxel size (PNG input, area units)")
    ap.add_argument("--heights", help="comma-separated z heights (voxels); default: --n-heights over the common z range")
    ap.add_argument("--transpose", action="store_true", help="grids have z varying along columns")
    ap.add_argument("--umbilicus", help="centre line file (default: estimate with umbilicus_finder on the volume)")
    ap.add_argument("--umbilicus-format", default="auto", choices=["auto", "json", "villa-json", "native-json", "zyx-text", "thaumato"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--png", action="store_true", help="write winding plots to <out-dir>/png")
    d = Params()
    for f in dataclasses.fields(Params):
        v = getattr(d, f.name)
        if isinstance(v, bool):
            ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, action="store_true", help="(off by default)")
            continue
        ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, type=(str if f.name == "crush_map" else float if v is None else type(v)),
                        default=v)
    _sub_flags(ap, "ssf", ssf.Params)
    _sub_flags(ap, "ssc", ssc.Params)
    _sub_flags(ap, "uf", uf.Params)
    _wc_flags(ap)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        if p.expect_side not in ("either", "outward", "inward"):
            raise InputError("--expect-side must be either, outward or inward")
        if not 0 < p.wn_jump_pitch or not 0 < p.wn_pair_lo < p.wn_pair_hi:
            raise InputError("need --wn-jump-pitch > 0 and 0 < --wn-pair-lo < --wn-pair-hi")
        ssf_p = _sub_params(a, "ssf", ssf.Params, vertical=1, **({"pitch_vox": p.pitch_vox} if p.pitch_vox else {}))
        ssf_p.validate()
        ssc_p = _sub_params(a, "ssc", ssc.Params)
        if p.global_pitch:
            ssf_p, ssc_p = dataclasses.replace(ssf_p, global_pitch=True), dataclasses.replace(ssc_p, global_pitch=True)
        uf_p = _sub_params(a, "uf", uf.Params)
        wc_p = None
        if p.windcheck:
            import ct_aware_check as wc
            wc_p = _sub_params(a, "wc", wc.Params)
        meshes = [load_mesh(t, ssf_p.invalid_value, a.transpose) for t in (a.trace_a, a.trace_b) if t]
        vox = a.voxel_size_um or next((m.voxel_um for m in meshes if m.voxel_um), None)
        if a.zarr:
            vol, ct = ZarrVolume(a.zarr, a.zarr_level), f"{a.zarr} level {a.zarr_level}"
        else:
            vol, ct = PngVolume(a.png_dir, a.png_pixel_um, vox, a.png_pattern), a.png_dir
        try:
            heights = [float(h) for h in a.heights.split(",") if h.strip()] if a.heights else auto_heights(meshes, p)
        except ValueError as e:
            raise InputError(f"--heights must be comma-separated numbers: {e}") from e
        warnings = []
        if a.umbilicus:
            z, y, x = read_umbilicus(a.umbilicus, a.umbilicus_format, p.umbilicus_scale)
            centre, csrc = Centre(z, y, x, a.umbilicus, np.inf), f"file {a.umbilicus}"
        else:
            if a.zarr:
                uvol = uf_io.open_volume(a.zarr, "zarr", a.zarr_level)
            else:
                if not (a.png_pixel_um and vox):
                    raise InputError("estimating the centre from PNGs needs --png-pixel-um and a voxel size; or give --umbilicus")
                uvol = uf_io.open_volume(a.png_dir, "png", scale_xy=a.png_pixel_um / vox)
            zs = [float(m.z[m.valid].min()) for m in meshes] + [float(m.z[m.valid].max()) for m in meshes]
            cen, info = estimate_centre(uvol, min(zs) - p.centre_z_step, max(zs) + p.centre_z_step, p, uf_p)
            if cen is None:
                centre, csrc = None, f"umbilicus_finder: only {info['n_ok']} OK slices of {info['n_slices']}"
                warnings.append("no centre line: the winding-number checks are NOT JUDGED (give --umbilicus)")
            else:
                centre = Centre(*cen, "umbilicus_finder", p.centre_max_gap * p.centre_z_step)
                csrc = f"umbilicus_finder ({info['n_ok']} OK of {info['n_slices']} slices)"
        rep = audit(meshes, vol, heights, centre, p, ssf_p, ssc_p, log=lambda m: print(m, file=sys.stderr), wc_p=wc_p)
    except (InputError, uf_io.InputError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    os.makedirs(a.out_dir, exist_ok=True)
    inputs = dict(traces=[a.trace_a] + ([a.trace_b] if a.trace_b else []), ct=ct, centre=csrc, heights=heights, warnings=warnings)
    txt = text_report(rep, inputs)
    pol = rep.pop("polar")
    with open(os.path.join(a.out_dir, "audit.json"), "w") as fh:
        json.dump(dict(tool_version=__version__, inputs=inputs, params=asdict(p), result=rep), fh, indent=2, default=float)
    with open(os.path.join(a.out_dir, "audit.txt"), "w") as fh:
        fh.write(txt)
    if a.png:
        write_pngs(dict(polar=pol), os.path.join(a.out_dir, "png"), [m.name for m in meshes])
    print(txt, end="")
    v = [t["verdict"] for t in rep["traces"]]
    return 1 if FAIL in v else (4 if NJ in v else 0)


if __name__ == "__main__":
    sys.exit(main())
