#!/usr/bin/env python3
"""Score trace_auditor on phantom_scroll phantoms (needs tools/phantom_scroll, i.e. its pull request merged).

    python tools/trace_auditor/score_on_phantoms.py --size 256 --centre estimated --json score.json

For each phantom (round, mild, bad, merged; the same ones as phantom_scroll/benchmark.py):
  TRUE traces, expected PASS:  every true turn audited alone; B of each true adjacent pair (turn k, turn k+1).
  BAD traces, expected FAIL:   three traces with a planted switch, audited alone; B of the pairs
                               (turn 1, skipped / shared / off-sheet), i.e. a trace on the wrong sheet from its first point.
Reports counts of PASS / FAIL / NOT JUDGED per group, and for the bad ones which checks fired (so you can see what
the winding checks add over the switch finder and the spacing check alone).
--centre estimated: umbilicus_finder on the volume (OK slices); --centre truth: the exact deformed axis.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.environ.get("PHANTOM_SCROLL_DIR", os.path.normpath(os.path.join(HERE, "..", "phantom_scroll")))
if not os.path.isfile(os.path.join(PH, "phantom_scroll.py")):
    sys.exit(f"phantom_scroll not found in {PH}: merge tools/phantom_scroll or set PHANTOM_SCROLL_DIR")
for d in (HERE, PH):
    if d not in sys.path:
        sys.path.insert(0, d)

import benchmark as bm  # noqa: E402  (phantom_scroll/benchmark.py: presets)
import phantom_scroll as ps  # noqa: E402
import trace_auditor as ta  # noqa: E402
import uf_io  # noqa: E402
from ssc_io import ArrayVolume, load_mesh  # noqa: E402


def make_centre(mode, sc, vol, p):
    if mode == "truth":
        cl = sc.centre_line()
        return ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf), "truth"
    cen, info = ta.estimate_centre(uf_io.ArrayVolume(vol), 0.0, float(vol.shape[0]), ta.Params(), ta.uf.Params())
    if cen is None:
        return None, f"estimated: only {info['n_ok']} OK of {info['n_slices']}"
    return ta.Centre(*cen, "umbilicus_finder", 1.5 * 32.0), f"estimated ({info['n_ok']} OK of {info['n_slices']} slices)"


def fired(trace):
    return sorted(c["check"] for c in trace["checks"] if c["status"] == ta.FAIL)


def run_phantom(name, size, seed, mode, work, log):
    p = bm.make_params(name, size, seed)
    out = os.path.join(work, name)
    nc = ps.Scroll(p).n_cols()
    sc, vol, lab, truth = ps.build(p, out, zarr=False, bad_switches=bm.switch_specs(nc), bad_pairs=True)
    centre, csrc = make_centre(mode, sc, vol, p)
    avol = ArrayVolume(vol)
    heights = [float(round(f * (p.nz - 1))) for f in (0.25, 0.4, 0.5, 0.6, 0.75)]
    ssf_p, ssc_p = ta.ssf.Params(vertical=1), ta.ssc.Params(band_height_vox=float(heights[1] - heights[0]))
    par = ta.Params()
    S = os.path.join(out, "surfaces")
    turn = lambda k: load_mesh(os.path.join(S, f"turn_{k:02d}"))  # noqa: E731

    def one(meshes):
        return ta.audit(meshes, avol, heights, centre, par, ssf_p, ssc_p)["traces"]

    rows = []                                                 # (group, label, verdict, fired checks)
    for k in range(p.turns):
        t = one([turn(k)])[0]
        rows.append(("true", f"turn {k} alone", t["verdict"], fired(t)))
    for k in range(p.turns - 1):
        t = one([turn(k), turn(k + 1)])[1]
        rows.append(("true", f"turn {k+1} vs turn {k}", t["verdict"], fired(t)))
    for s in truth["switches"]:
        t = one([load_mesh(os.path.join(out, s["trace"]))])[0]
        rows.append(("bad", f"switch {s['delta']:+.0f} at col {s['col']} (turn {s['turn']})", t["verdict"], fired(t)))
    for pr in truth["pairs"]:
        if pr["name"] == "adjacent":
            continue
        t = one([turn(1), load_mesh(os.path.join(out, pr["b"]))])[1]
        rows.append(("bad", f"pair {pr['name']} (B vs turn 1)", t["verdict"], fired(t)))
    log(f"  {name}: {len(rows)} audits ({csrc})")
    return dict(phantom=name, centre=csrc, rows=rows)


def summarise(res):
    def count(group, v):
        return sum(1 for g, _, ver, _ in res["rows"] if g == group and ver == v)
    nt = sum(1 for g, *_ in res["rows"] if g == "true")
    nb = sum(1 for g, *_ in res["rows"] if g == "bad")
    by_check = {}
    for g, _, ver, f in res["rows"]:
        if g == "bad" and ver == ta.FAIL:
            for c in f:
                by_check[c] = by_check.get(c, 0) + 1
    return dict(n_true=nt, true_pass=count("true", ta.PASS), true_fail=count("true", ta.FAIL), true_nj=count("true", ta.NJ),
                n_bad=nb, bad_fail=count("bad", ta.FAIL), bad_pass=count("bad", ta.PASS), bad_nj=count("bad", ta.NJ),
                bad_by_check=by_check)


def table(results):
    head = ("| phantom | centre | true traces: PASS / FAIL / NOT JUDGED | bad traces: FAIL / PASS / NOT JUDGED | "
            "FAILs fired by (bad traces) |\n|---|---|---|---|---|")
    rows = []
    for r in results:
        s = summarise(r)
        rows.append(f"| {r['phantom']} | {r['centre']} | {s['true_pass']} / {s['true_fail']} / {s['true_nj']} (of {s['n_true']}) | "
                    f"{s['bad_fail']} / {s['bad_pass']} / {s['bad_nj']} (of {s['n_bad']}) | "
                    + ", ".join(f"{k} {v}" for k, v in sorted(s["bad_by_check"].items())) + " |")
    return head + "\n" + "\n".join(rows) + "\n"


def detail(results):
    out = []
    for r in results:
        out.append(f"\n{r['phantom']} ({r['centre']})")
        for g, label, ver, f in r["rows"]:
            ok = (ver == ta.PASS) if g == "true" else (ver == ta.FAIL)
            out.append(f"  {'ok ' if ok else 'XX '} [{g:<4}] {label:<42} {ver:<10} {','.join(f)}")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--phantoms", default="round,mild,bad,merged")
    ap.add_argument("--centre", choices=["estimated", "truth"], default="estimated")
    ap.add_argument("--out")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    work = a.out or tempfile.mkdtemp(prefix="auditor_phantoms_")
    res = [run_phantom(n, a.size, a.seed, a.centre, work, lambda m: print(m, file=sys.stderr)) for n in a.phantoms.split(",")]
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(res, fh, indent=2, default=float)
    print(table(res))
    print(detail(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
