#!/usr/bin/env python3
"""sweep_thresholds: vary one threshold at a time at fixed phantoms, record verdict correctness (MIT).

    python tools/calibration/sweep_thresholds.py --out tools/calibration/results/sweeps.csv --jobs 4

Every threshold that exists today in sheet_spacing_check, sheet_switch_finder, umbilicus_finder and trace_auditor is in
SWEEPS (tool, parameter group, field, values; the current default is read from the tool's Params). Phantoms: --seeds,
--pitches, --steps, --deforms (defaults: seeds 0-2, pitch 15 and 30, step 5, all four deformations). The auditor sweeps use
the TRUE centre line (--auditor-centre) so that a threshold of the winding check is not confounded with centre errors;
the umbilicus sweeps measure the centre line itself. Output: one CSV, columns of calib.COLUMNS plus param, value, group.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calib  # noqa: E402
from run_grid import parse_list  # noqa: E402

# (tool key, Cfg group, field, values)
SWEEPS = [
    ("ssc", "ssc", "ratio_min", [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
    ("ssc", "ssc", "ratio_max", [1.2, 1.35, 1.5, 1.7, 2.0, 2.5, 3.0]),
    ("ssc", "ssc", "median_window", [1, 3, 5, 9, 15, 25, 41]),
    ("ssc", "ssc", "onsheet_radius_px", [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]),
    ("ssf", "ssf", "step_min", [0.3, 0.45, 0.6, 0.75, 0.9]),
    ("ssf", "ssf", "step_max", [1.1, 1.25, 1.4, 1.6, 2.0, 3.0]),
    ("ssf", "ssf", "k_points", [1, 2, 3, 5, 8, 12, 20]),
    ("ssf", "ssf", "median_window", [1, 3, 5, 9, 15, 25, 41]),
    ("ssf", "ssf", "onsheet_radius_px", [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]),
    ("ssf", "ssf", "track_max_jump_pitch", [0.15, 0.25, 0.35, 0.5, 0.7, 1.0, 1.5]),
    ("ssf", "ssf", "max_tilt_deg", [5, 10, 15, 25, 40, 60, 85]),
    ("uf", "uf", "coherence_min", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]),
    ("uf", "uf", "min_coverage_deg", [60, 120, 180, 240, 300, 340]),
    ("uf", "uf", "max_residual_pitch", [0.15, 0.25, 0.4, 0.6, 1.0, 1.5, 3.0]),
    ("ta", "ta", "wn_jump_pitch", [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.3]),
    ("ta", "ta", "wn_pair_lo", [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
    ("ta", "ta", "wn_pair_hi", [1.2, 1.35, 1.5, 1.7, 2.0, 2.5]),
    ("ta", "ta", "wn_pair_frac", [0.5, 0.65, 0.8, 0.9, 0.95]),
    ("ta", "ta", "min_clean_fraction", [0.3, 0.5, 0.65, 0.8, 0.9, 0.95]),
    ("ta", "ta", "min_switch_confidence", [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9]),
]
EXTRA = ["param", "value", "group"]


def default_of(group, field):
    cls = {"ssc": calib.ssc.Params, "ssf": calib.ssf.Params, "uf": calib.uf.Params, "ta": calib.ta.Params}[group]
    return {f.name: f.default for f in dataclasses.fields(cls)}[field]


def _work(args):
    seed, pitch, deform, steps, size, cache, base, only = args
    t0 = time.time()
    out = []
    try:
        ph = calib.Phantom(seed, pitch, deform, size, cache)
        for tool, grp, field, values in SWEEPS:
            if only and f"{grp}.{field}" not in only:
                continue
            for v in values:
                cfg = base.with_override(grp, field, v)
                if tool == "uf":
                    rows = calib.eval_uf(ph, cfg)
                else:
                    rows = []
                    centre = calib.make_centre(ph, cfg)[0] if tool == "ta" else None
                    for st in steps:
                        rows += {"ssf": lambda: calib.eval_ssf(ph, st, cfg), "ssc": lambda: calib.eval_ssc(ph, st, cfg),
                                 "ta": lambda: calib.eval_ta(ph, st, cfg, centre)}[tool]()
                for r in rows:
                    r.update(param=field, value=v, group=grp)
                out += rows
        return (seed, pitch, deform), out, time.time() - t0, None
    except Exception:       # noqa: BLE001
        import traceback
        return (seed, pitch, deform), [], time.time() - t0, traceback.format_exc()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(HERE, "results", "sweeps.csv"))
    ap.add_argument("--cache", default=os.path.join(HERE, "cache"))
    ap.add_argument("--seeds", default="0-2")
    ap.add_argument("--pitches", default="15,30")
    ap.add_argument("--steps", default="5")
    ap.add_argument("--deforms", default=",".join(calib.DEFORMS))
    ap.add_argument("--size", type=int, default=192)
    ap.add_argument("--only", default="", help="comma list of group.field to sweep, e.g. ssf.k_points (default all)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--auditor-centre", choices=["estimated", "truth"], default="truth")
    a = ap.parse_args(argv)
    base = calib.Cfg(auditor_centre=a.auditor_centre)
    only = {s for s in a.only.split(",") if s}
    steps = parse_list(a.steps, float)
    tasks = [(s, p, d, steps, a.size, a.cache, base, only) for s in parse_list(a.seeds, int)
             for p in parse_list(a.pitches, float) for d in a.deforms.split(",")]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    bad = 0
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=calib.COLUMNS + EXTRA)
        w.writeheader()
        it = map(_work, tasks) if a.jobs <= 1 else mp.Pool(a.jobs).imap_unordered(_work, tasks)
        for n, (key, rows, dt, err) in enumerate(it, 1):
            if err:
                bad += 1
                print(f"FAILED {key}\n{err}", file=sys.stderr)
                continue
            w.writerows(rows)
            fh.flush()
            print(f"[{n}/{len(tasks)}] {key} {len(rows)} rows {dt:.0f}s", file=sys.stderr, flush=True)
    print(a.out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
