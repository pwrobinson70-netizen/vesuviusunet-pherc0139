#!/usr/bin/env python3
"""benchmark: score the repository's tools on phantom scrolls with known truth (MIT).

    python tools/phantom_scroll/benchmark.py --size 256 --out bench_out --json bench.json

For each phantom (round, mild, bad = badly crushed, merged = sheets touching) it
  * runs sheet_switch_finder on the true turns (must report nothing) and on traces with known switches
    (a switch is FOUND if a horizontal switch lies within --col-tol columns of the true column, with the
    right direction, at >= 1 height; the per-(trace, height) recall is also given);
  * runs umbilicus_finder on the volume and compares with the true centre line (voxels);
  * runs sheet_spacing_check on the true adjacent pairs and on deliberately bad pairs (skipped sheet,
    shared sheet, mesh in the dark gap) and reports the mean clean fraction of each kind.
ink_infer is NOT benchmarked (it needs torch and a checkpoint). Prints a markdown table.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, ".."))
for d in (HERE, os.path.join(TOOLS, "sheet_spacing_check"), os.path.join(TOOLS, "sheet_switch_finder"),
          os.path.join(TOOLS, "umbilicus_finder")):
    if d not in sys.path:
        sys.path.insert(0, d)

import phantom_scroll as ps  # noqa: E402
import sheet_spacing_check as ssc  # noqa: E402
import sheet_switch_finder as ssf  # noqa: E402
import umbilicus_finder as uf  # noqa: E402
import uf_io  # noqa: E402
from ssc_io import ArrayVolume, load_mesh  # noqa: E402

PRESETS = {
    "round": dict(),
    "mild": dict(squash=0.85, squash_angle=30.0, warp_amp=3.0, irregular=0.05, tilt=(0.05, -0.03)),
    "bad": dict(squash=0.55, squash_angle=30.0, warp_amp=7.0, irregular=0.12, tilt=(0.10, -0.08)),
    "merged": dict(squash=0.8, warp_amp=3.0, irregular=0.05, merge_strength=0.85, merge_turn=1.5,
                   merge_phi=90.0, merge_sigma=0.09),      # merge_sigma given as a fraction of --size
}


def make_params(name, size, seed):
    kw = dict(PRESETS[name])
    if "merge_sigma" in kw:
        kw["merge_sigma"] = kw["merge_sigma"] * size
    scale = size / 256.0
    return ps.Params(shape=(size,) * 3, seed=seed, turns=4, r0=18.0 * scale, pitch=22.0 * scale,
                     thickness=6.0 * scale, grid_step=4.0 * scale, **kw)


def switch_specs(n_cols):
    """Known switches on three separate traces: outward hard hop, inward ramp, outward hop in the second half."""
    return [dict(turn=1, col=int(n_cols * 0.30), delta=1.0, width=0, row0=0),
            dict(turn=2, col=int(n_cols * 0.55), delta=-1.0, width=4, row0=0),
            dict(turn=0, col=int(n_cols * 0.70), delta=1.0, width=0, row0=0)]


def run_one(name, size, seed, workdir, col_tol=3, log=print):
    p = make_params(name, size, seed)
    out = os.path.join(workdir, name)
    nc = ps.Scroll(p).n_cols()
    sc, vol, lab, truth = ps.build(p, out, zarr=False, bad_switches=switch_specs(nc), bad_pairs=True)
    nz = p.nz
    heights = [float(round(f * (nz - 1))) for f in (0.25, 0.4, 0.5, 0.6, 0.75)]
    avol = ArrayVolume(vol)
    res = dict(phantom=name, size=size, seed=seed, n_cols=nc, pitch=p.pitch, params=truth["params"])

    # ---- sheet_switch_finder
    sp = ssf.Params(vertical=0)
    clean_sw = 0
    for k in range(p.turns):
        r = ssf.run_finder(load_mesh(os.path.join(out, "surfaces", f"turn_{k:02d}")), avol, heights, sp)
        clean_sw += sum(1 for s in r["switches"] if s["kind"] == "horizontal")
    found, hits, trials, errs, spurious = 0, 0, 0, [], 0
    per_trace = []
    for s in truth["switches"]:
        r = ssf.run_finder(load_mesh(os.path.join(out, s["trace"])), avol, heights, sp)
        want_dir = s["direction"]
        tol = col_tol + s["width"] / 2.0
        by_h = {}
        for w in r["switches"]:
            if w["kind"] != "horizontal":
                continue
            ok = abs(w["col"] - s["centre_col"]) <= tol and w["direction"] == want_dir
            by_h.setdefault(w["height"], []).append((ok, abs(w["col"] - s["centre_col"])))
        n_hit = 0
        for h in heights:
            trials += 1
            m = [e for ok, e in by_h.get(h, []) if ok]
            if m:
                hits += 1
                n_hit += 1
                errs.append(min(m))
            spurious += sum(1 for ok, _ in by_h.get(h, []) if not ok)
        found += n_hit > 0
        per_trace.append(dict(trace=s["trace"], turn=s["turn"], col=s["col"], delta=s["delta"], heights_hit=n_hit))
    res["switch"] = dict(true=len(truth["switches"]), found=int(found), recall_trace_height=hits / max(trials, 1),
                         median_col_error=float(np.median(errs)) if errs else None, false_on_bad_traces=int(spurious),
                         false_on_true_turns=int(clean_sw), per_trace=per_trace)

    # ---- umbilicus_finder
    cvol = uf_io.ArrayVolume(vol)
    rows, summ = uf.run(cvol, uf.Params(), z_start=8, z_stop=nz - 8, z_step=8.0)
    truth_c = sc.centre_line()
    err_s, err_raw = [], []
    for r in rows:
        t = truth_c[int(round(r["z"]))]
        if np.isfinite(r["y"]):
            err_s.append(float(np.hypot(r["y"] - t[1], r["x"] - t[2])))
        if r["flag"] == "OK" and np.isfinite(r["raw_y"]):
            err_raw.append(float(np.hypot(r["raw_y"] - t[1], r["raw_x"] - t[2])))
    res["centre"] = dict(n=len(rows), n_ok=summ["n_ok"], mean_err=float(np.mean(err_s)) if err_s else None,
                         max_err=float(np.max(err_s)) if err_s else None,
                         mean_err_raw_ok=float(np.mean(err_raw)) if err_raw else None,
                         pitch_estimated=summ["pitch_vox"], pitch_true=p.pitch)

    # ---- sheet_spacing_check
    spp = ssc.Params(band_height_vox=float(heights[1] - heights[0]))
    A0 = os.path.join(out, "surfaces")

    def clean(a, b):
        r = ssc.run_check(load_mesh(a), load_mesh(b), avol, heights, spp)
        return float(np.mean([h["clean_fraction"] for h in r["heights"]]))
    true_pairs = [clean(os.path.join(A0, f"turn_{k:02d}"), os.path.join(A0, f"turn_{k + 1:02d}")) for k in range(p.turns - 1)]
    bad = {}
    for pr in truth["pairs"]:
        if pr["name"] != "adjacent":
            bad[pr["name"]] = clean(os.path.join(out, pr["a"]), os.path.join(out, pr["b"]))
    res["spacing"] = dict(true_pairs=true_pairs, true_mean=float(np.mean(true_pairs)), bad=bad)
    log(f"  {name}: done")
    return res


def table(results):
    f = lambda v, fmt="{:.2f}": "n/a" if v is None else fmt.format(v)  # noqa: E731
    head = ("| phantom | switches found / true | recall (trace x height) | col err (med) | false sw. on true turns | "
            "false sw. on bad traces | centre err mean / max (vox) | umb. OK slices | clean: true pairs | "
            "clean: skipped | clean: shared | clean: off-sheet |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    rows = []
    for r in results:
        s, c, p = r["switch"], r["centre"], r["spacing"]
        rows.append(f"| {r['phantom']} | {s['found']} / {s['true']} | {f(s['recall_trace_height'])} | {f(s['median_col_error'], '{:.1f}')} | "
                    f"{s['false_on_true_turns']} | {s['false_on_bad_traces']} | {f(c['mean_err'], '{:.1f}')} / {f(c['max_err'], '{:.1f}')} | "
                    f"{c['n_ok']} / {c['n']} | {f(p['true_mean'])} | {f(p['bad'].get('skipped'))} | "
                    f"{f(p['bad'].get('shared'))} | {f(p['bad'].get('off_sheet'))} |")
    return head + "\n" + "\n".join(rows) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--phantoms", default="round,mild,bad,merged")
    ap.add_argument("--out", help="keep the phantoms here (default: a temp dir)")
    ap.add_argument("--json")
    ap.add_argument("--col-tol", type=int, default=3, help="columns: a switch within this of the truth counts as found")
    a = ap.parse_args(argv)
    work = a.out or tempfile.mkdtemp(prefix="phantoms_")
    results = [run_one(n, a.size, a.seed, work, a.col_tol, log=lambda m: print(m, file=sys.stderr))
               for n in a.phantoms.split(",")]
    txt = table(results)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(results, fh, indent=2, default=float)
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
