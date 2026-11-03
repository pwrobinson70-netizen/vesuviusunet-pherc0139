#!/usr/bin/env python3
"""trace_repair: pull the part of a tifxyz trace that lies beyond a sheet switch back onto the tracked sheet (MIT).

    python trace_repair.py TRACE --audit audit.json (--zarr V | --npy V) --out NEW_TRACE [--origin low]

Input: a tifxyz trace, the `audit.json` that tools/trace_auditor wrote for it, and the CT volume. For every switch
the audit reports (sheet_switch_finder switches and winding-number jumps with confidence >= --min-switch-confidence) the
points beyond it, in the growth direction, are re-snapped to the sheet that was tracked BEFORE the switch:
  * growth runs along grid columns for horizontal switches and winding jumps, along rows for vertical switches;
    `--origin low` (default) means the trace was grown from the low-index side (column / row 0), `high` from the other;
    `--origin-cell ROW COL` says it grew outward from one cell (sheet_tracer patches): each side is repaired outward from it;
  * the first repaired line is `min(switch lines) - --margin` (a ramp switch starts before its reported centre);
  * each point is predicted from its already-repaired neighbour one step back: neighbour + (original step with its
    component along the sheet normal removed), i.e. the sheet jump is dropped and the advance along the sheet is kept;
    then it is snapped to the nearest bright-sheet peak along the structure-tensor normal within +/- `--snap-pitch` x
    pitch (sheet_tracer.Tracer.snap, imported). This walks onto the pre-switch sheet and carries on along the grid, so
    neighbours stay continuous. Further switches (a double switch) are handled by the same chain.
  * A snap that disagrees with the median offset of the neighbouring lines by more than `--outlier-pitch` x pitch is
    replaced by the prediction shifted by that median offset; a point with no peak keeps its prediction (counted).
Never overwrites the input: --out must be a different, not yet existing directory. If the audit has no switch to
repair, the input files are copied byte for byte. Also writes `repair_summary.json` (the diff summary) in --out.
Exit codes: 0 repaired or nothing to repair, 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for d in ("sheet_tracer", "sheet_spacing_check"):
    p = os.path.normpath(os.path.join(HERE, "..", d))
    if p not in sys.path:
        sys.path.insert(0, p)

import sheet_tracer as st  # noqa: E402  (Tracer: normals_at, snap, load_volume; write_tifxyz, area_vx2)
from ssc_io import InputError, load_mesh  # noqa: E402

__version__ = "0.1.0"


def collect_switches(audit, trace_name=None, min_conf=0.3):
    """-> (switches, pitch, trace_name). switches: list of dict(axis='cols'|'rows', line, source, ...)."""
    res = audit.get("result", audit)
    traces = res.get("traces", [])
    if not traces:
        raise InputError("audit.json has no traces")
    tr = next((t for t in traces if t["name"] == trace_name), None)
    if tr is None:
        tr = traces[-1]
    sw = []
    for c in tr["checks"]:
        if c["check"] == "switch_finder":
            for s in c.get("switches", []):
                if s["confidence"] >= min_conf:
                    horiz = s["kind"] == "horizontal"
                    sw.append(dict(axis="cols" if horiz else "rows", line=int(s["col"]) if horiz else int(np.ceil(s["row"])),
                                   source="switch_finder", direction=s["direction"], height=s["height"]))
        elif c["check"] == "winding_jumps":
            for j in c.get("jumps", []):
                sw.append(dict(axis="cols", line=int(j["col"]), source="winding_jumps",
                               direction="outward" if j["step_pitches"] > 0 else "inward", height=j["z"]))
    pit = [h["pitch"] for h in tr.get("heights", []) if h.get("pitch")]
    return sw, (float(np.median(pit)) if pit else None), tr["name"]


def repair_axis(P, start, T, pitch, a):
    """Repair P (R, C, 3) in place along axis 1 from column `start` on. Returns counters."""
    from scipy.ndimage import generic_filter
    R, C, _ = P.shape
    orig = P.copy()
    valid = orig[..., 0] != -1
    out = dict(unsnapped=0, outliers=0)
    for c in range(max(start, 1), C):
        rows = np.flatnonzero(valid[:, c] & valid[:, c - 1])
        if len(rows) == 0:
            continue
        q = P[rows, c - 1]
        n, _ = T.normals_at(q)
        d = orig[rows, c] - orig[rows, c - 1]
        dt = d - (d * n).sum(-1, keepdims=True) * n
        pred = q + dt
        n2, _ = T.normals_at(pred)
        n2 = np.where((n2 * n).sum(-1, keepdims=True) < 0, -n2, n2)
        new, off, found, _ = T.snap(pred, n2, a.snap_pitch * pitch)
        if len(rows) >= 5 and found.sum() >= 3:
            full = np.full(R, np.nan)
            full[rows] = np.where(found, off, np.nan)
            med = generic_filter(full, np.nanmedian, size=5, mode="nearest")
            bad = np.isfinite(full) & np.isfinite(med) & (np.abs(full - med) > a.outlier_pitch * pitch)
            for k in np.flatnonzero(bad[rows]):
                new[k] = pred[k] + med[rows[k]] * n2[k]
                out["outliers"] += 1
        out["unsnapped"] += int((~found).sum())
        P[rows, c] = new
    return out


def repair(xyz, switches, T, pitch, a):
    P = np.array(xyz, np.float64)
    info = dict(cols=None, rows=None, unsnapped=0, outliers=0)
    for axis in ("cols", "rows"):
        lines = [s["line"] for s in switches if s["axis"] == axis]
        if not lines:
            continue
        Q = P if axis == "cols" else np.ascontiguousarray(P.transpose(1, 0, 2))
        C = Q.shape[1]
        jobs = []                                    # (flip, first line to repair, in the possibly flipped array)
        if a.origin_cell is None:
            if a.origin == "low":
                jobs.append((False, max(1, min(lines) - a.margin)))
            else:
                jobs.append((True, max(1, C - 1 - max(lines) - a.margin)))
        else:                                        # growth radiates from the cell: chain outward both ways
            o = a.origin_cell[1] if axis == "cols" else a.origin_cell[0]
            hi, lo = [x for x in lines if x >= o], [x for x in lines if x < o]
            if hi:
                jobs.append((False, max(o + 1, min(hi) - a.margin)))
            if lo:
                jobs.append((True, max(C - o, C - 1 - max(lo) - a.margin)))
        for flip, first in jobs:
            R_ = np.ascontiguousarray(Q[:, ::-1]) if flip else Q
            r = repair_axis(R_, first, T, pitch, a)
            Q = np.ascontiguousarray(R_[:, ::-1]) if flip else R_
            info["unsnapped"] += r["unsnapped"]
            info["outliers"] += r["outliers"]
            info[axis] = dict(info[axis] or {}, **{("high_to_low" if flip else "low_to_high"): int(first)}, n_switches=len(lines))
        P = Q if axis == "cols" else np.ascontiguousarray(Q.transpose(1, 0, 2))
    return P.astype(np.float32), info


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("trace", help="tifxyz folder to repair (never modified)")
    ap.add_argument("--audit", required=True, help="audit.json of tools/trace_auditor for this trace")
    ap.add_argument("--audit-trace", help="trace name inside audit.json (default: the one named like the folder, else the last)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr")
    g.add_argument("--npy")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--out", required=True, help="new tifxyz folder (must not exist)")
    ap.add_argument("--origin", choices=["low", "high"], default="low", help="side of the grid the trace was grown from")
    ap.add_argument("--origin-cell", type=int, nargs=2, metavar=("ROW", "COL"),
                    help="grid cell the trace was grown from (growth radiates from it, e.g. a sheet_tracer seed); overrides --origin")
    ap.add_argument("--min-switch-confidence", type=float, default=0.3)
    ap.add_argument("--margin", type=int, default=2, help="lines before the first reported switch where repair starts")
    ap.add_argument("--snap-pitch", type=float, default=1.0, help="snap window +/- x pitch")
    ap.add_argument("--outlier-pitch", type=float, default=0.35,
                    help="snap offset deviating from the neighbouring lines' median by more than this x pitch is replaced")
    ap.add_argument("--pitch-vox", type=float, help="CT pitch (voxels); default: median of the audit's per-height pitch")
    ap.add_argument("--sigma-smooth", type=float, default=1.0)
    ap.add_argument("--sigma-grad", type=float, default=1.5)
    ap.add_argument("--sigma-tensor", type=float, default=3.0)
    ap.add_argument("--peak-prominence", type=float, default=0.25)
    return ap


def run(a):
    src, out = os.path.abspath(a.trace), os.path.abspath(a.out)
    if out == src or os.path.exists(out):
        raise InputError(f"--out {a.out} exists or is the input; trace_repair never overwrites")
    mesh = load_mesh(src)
    with open(a.audit) as fh:
        audit = json.load(fh)
    sw, apitch, tname = collect_switches(audit, os.path.basename(src.rstrip("/")) if not a.audit_trace else a.audit_trace,
                                         a.min_switch_confidence)
    summary = dict(tool_version=__version__, input=src, output=out, audit=os.path.abspath(a.audit), audit_trace=tname,
                   switches=sw, repaired=False)
    if not sw:
        shutil.copytree(src, out)
        summary["note"] = "no switch to repair: input copied byte for byte"
    else:
        pitch = a.pitch_vox or apitch
        if not pitch:
            raise InputError("no pitch in the audit; give --pitch-vox")
        vol, desc = st.load_volume(a)
        T = st.Tracer(vol, st.Params(sigma_smooth=a.sigma_smooth, sigma_grad=a.sigma_grad, sigma_tensor=a.sigma_tensor,
                                     peak_prominence=a.peak_prominence))
        xyz0 = np.where(mesh.valid[..., None], np.stack([mesh.x, mesh.y, mesh.z], -1), -1.0)
        new, info = repair(xyz0, sw, T, pitch, a)
        new = np.where(mesh.valid[..., None], new, -1.0).astype(np.float32)
        meta = dict(mesh.meta)
        sc = meta.get("scale") or [0.25, 0.25]
        st.write_tifxyz(out, new, 1.0 / float(sc[0]))
        written = json.load(open(os.path.join(out, "meta.json")))
        meta.update(bbox=written["bbox"], area_vx2=written["area_vx2"], scale=sc, repaired_from=os.path.basename(src.rstrip("/")))
        json.dump(meta, open(os.path.join(out, "meta.json"), "w"), indent=4)
        if os.path.isfile(os.path.join(src, "mask.tif")):
            shutil.copy(os.path.join(src, "mask.tif"), os.path.join(out, "mask.tif"))
        d = np.linalg.norm(new.astype(np.float64) - xyz0, axis=-1)[mesh.valid]
        moved = d > 0.5
        summary.update(repaired=True, pitch_vox=pitch, volume=desc, n_valid=int(mesh.valid.sum()),
                       n_moved_over_half_voxel=int(moved.sum()), fraction_moved=float(moved.mean()), max_move_vox=float(d.max()),
                       median_move_of_moved_vox=float(np.median(d[moved])) if moved.any() else 0.0,
                       n_unsnapped=info["unsnapped"], n_outliers_replaced=info["outliers"],
                       axes={k: info[k] for k in ("cols", "rows") if info[k]})
    with open(os.path.join(out, "repair_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2, default=float)
    return summary


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        s = run(a)
    except (InputError, OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in s.items() if k != "switches"}, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
