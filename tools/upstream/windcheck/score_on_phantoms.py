#!/usr/bin/env python3
"""Score the windcheck-based verdict on a phantom_scroll 'folded' phantom with planted defects, before / after.  (ours, MIT)

    python tools/upstream/windcheck/score_on_phantoms.py --size 128 --json score.json [--out WORKDIR] [--reuse]

Traces (all from the same phantom; the fold is phantom_scroll v2's S-shaped pleat, turn 2):
  TRUE   every turn alone (the folded turn included)                                         expected PASS
  BAD    folded turn with the pleat CUT through (leaves the sheet)                           expected FAIL (off_sheet)
  BAD    folded turn with a planted CROSSING at amplitudes --cross-amps (voxels)             expected FAIL (self_intersection)
Columns: BEFORE = trace_auditor 0.2.x without --windcheck, AFTER = the same with --windcheck (one more verdict), and the two parts of
windcheck on their own.  trace_auditor runs with the exact centre line of the phantom.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", ".."))
for d in (HERE, os.path.join(TOOLS, "phantom_scroll"), os.path.join(TOOLS, "trace_auditor"), os.path.join(TOOLS, "sheet_spacing_check")):
    if d not in sys.path:
        sys.path.insert(0, d)

import benchmark as bm  # noqa: E402
import ct_aware_check as wc  # noqa: E402
import phantom_defects as pdef  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import trace_auditor as ta  # noqa: E402
from ssc_io import ArrayVolume, load_mesh  # noqa: E402


def build(size, seed, work, reuse=False):
    p = bm.make_params("folded", size, seed)
    out = os.path.join(work, "folded")
    vp = os.path.join(out, "vol.npy")
    if reuse and os.path.exists(vp):
        return p, ps.Scroll(p), np.load(vp), out
    sc, vol, _lab, _truth = ps.build(p, out, zarr=False)
    np.save(vp, vol)
    return p, sc, vol, out


def fired(t):
    return ",".join(sorted(c["check"] for c in t["checks"] if c["status"] == ta.FAIL))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=128)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fold-turn", type=int, default=2, help="turn that carries the pleat in the 'folded' preset (default %(default)s)")
    ap.add_argument("--cross-amps", type=float, nargs="+", default=[4.0, 8.0], help="crossing amplitudes in voxels at size 128 (scaled with --size/128)")
    ap.add_argument("--out")
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    work = a.out or tempfile.mkdtemp(prefix="windcheck_phantom_")
    p, sc, vol, out = build(a.size, a.seed, work, a.reuse)
    S = os.path.join(out, "surfaces")
    scale = (1.0 / p.grid_step,) * 2
    turn = lambda k: load_mesh(os.path.join(S, f"turn_{k:02d}"))  # noqa: E731
    fm = turn(a.fold_turn)
    P, v = wc.mesh_arrays(fm)
    win = pdef.fold_window(P, v)
    if win is None:
        sys.exit("no pleat found in the folded turn")
    N = wc.normals(P, v)
    ps_ = a.size / 128.0
    bad = {"cut through the pleat": pdef.cut(P, *win)}
    for A in a.cross_amps:
        bad[f"planted crossing, amplitude {A * ps_:g} vox"] = pdef.cross(P, N, *win, A * ps_)
    cl = sc.centre_line()
    centre = ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf)
    heights = [float(round(f * (p.nz - 1))) for f in (0.25, 0.4, 0.5, 0.6, 0.75)]
    ssf_p, ssc_p = ta.ssf.Params(vertical=1), ta.ssc.Params(band_height_vox=float(heights[1] - heights[0]))
    avol = ArrayVolume(vol)
    wp = wc.Params(pitch_vox=p.pitch)
    rows = []
    traces = [("true", f"turn {k} alone" + (" (pleat)" if k == a.fold_turn else ""), turn(k)) for k in range(p.turns)]
    for name, Q in bad.items():
        d = os.path.join(out, "planted", name.split(",")[0].replace(" ", "_") + (f"_{len(rows)}" if False else ""))
        d = os.path.join(out, "planted", f"bad_{len(traces) - p.turns:02d}")
        ps.write_tifxyz(d, Q, scale)
        traces.append(("bad", name, load_mesh(d)))
    for grp, label, m in traces:
        before = ta.audit([m], avol, heights, centre, ta.Params(), ssf_p, ssc_p)["traces"][0]
        after = ta.audit([m], avol, heights, centre, ta.Params(windcheck=True), ssf_p, ssc_p, wc_p=wp)["traces"][0]
        Pm, vm = wc.mesh_arrays(m)
        alone = wc.check_trace(Pm, vm, vol, wp)
        sub = {c["check"]: c["status"] for c in alone["checks"]}
        rows.append(dict(group=grp, label=label, before=before["verdict"], before_fired=fired(before), after=after["verdict"],
                         after_fired=fired(after), self_intersection=sub["self_intersection"], off_sheet=sub["off_sheet"],
                         detail={c["check"]: c["reason"] for c in alone["checks"]}))
        print(f"  {grp:<4} {label:<40} before {before['verdict']:<10} after {after['verdict']:<10}  "
              f"selfx {sub['self_intersection']:<10} offsheet {sub['off_sheet']}", file=sys.stderr)
    head = "| group | trace | BEFORE (auditor) | AFTER (auditor + windcheck) | fired after | self_intersection alone | off_sheet alone |\n|---|---|---|---|---|---|---|\n"
    tab = head + "\n".join(f"| {r['group']} | {r['label']} | {r['before']} {('(' + r['before_fired'] + ')') if r['before_fired'] else ''} | {r['after']} | "
                           f"{r['after_fired']} | {r['self_intersection']} | {r['off_sheet']} |" for r in rows) + "\n"
    ok_b = sum(1 for r in rows if (r["group"] == "true") == (r["before"] == ta.PASS) and r["before"] != ta.NJ)
    ok_a = sum(1 for r in rows if (r["group"] == "true") == (r["after"] == ta.PASS) and r["after"] != ta.NJ)
    tab += f"\nCorrect verdicts (true -> PASS, bad -> FAIL; NOT JUDGED counts as wrong): before {ok_b}/{len(rows)}, after {ok_a}/{len(rows)}.\n"
    print(tab)
    if a.json:
        json.dump(dict(size=a.size, window=win, rows=rows), open(a.json, "w"), indent=2, default=float)


if __name__ == "__main__":
    main()
