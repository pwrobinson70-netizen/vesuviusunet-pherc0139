#!/usr/bin/env python3
"""benchmark_ci: run the existing phantom benchmarks over many seeds and write ONE per-run CSV (MIT). Measurement only.

    python tools/benchmark_ci/run.py --seeds 0-19 --sizes 192 --out tools/benchmark_ci/results/runs.csv

One job = one (size, deformation, seed). A job builds the phantom once (phantom_scroll, cached on disk under --work; a finished
job leaves a JSON there and is skipped on rerun) and runs, UNCHANGED and at their current defaults:
  * phantom_scroll/benchmark.py run_one      -> switch recall, false switches, centre error, spacing clean fractions
  * trace_auditor/score_on_phantoms.py       -> verdicts on true and bad traces (centre: --auditor-centre, default estimated)
  * sheet_tracer/score_on_phantoms.py        -> tracer score, 3 seeds per phantom, exact centre line
Jobs run in a multiprocessing pool (--procs, default all cores, one BLAS thread each). The CSV has one row per job; rows already
in the CSV with the same (size, deformation, seed) are replaced, others are kept (so the size-sensitivity runs share the file).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, ".."))
DEFORMATIONS = ["round", "mild", "bad", "merged"]       # "bad" is the badly crushed preset; shown as "crushed"
LABEL = {"round": "round", "mild": "mild", "bad": "crushed", "merged": "merged"}
KEY = ("size", "deformation", "seed")

COLUMNS = [
    "size", "deformation", "seed", "status", "seconds", "error",
    # phantom benchmark: switch finder
    "switch_true", "switch_found", "switch_recall_trace_height", "switch_median_col_error",
    "false_switches_true_turns", "false_switches_bad_traces",
    # phantom benchmark: umbilicus finder (centre error, voxels)
    "centre_n_slices", "centre_n_ok", "centre_mean_err", "centre_max_err", "pitch_est", "pitch_true",
    # phantom benchmark: spacing check, mean clean fraction per pair kind
    "clean_true", "clean_shared", "clean_skipped", "clean_offsheet",
    # trace_auditor verdicts
    "aud_centre", "aud_true_n", "aud_true_pass", "aud_true_fail", "aud_true_nj",
    "aud_bad_n", "aud_bad_fail", "aud_bad_pass", "aud_bad_nj",
    "aud_true_pass_rate", "aud_bad_fail_rate", "aud_bad_fail_rate_pairs", "aud_bad_fail_rate_switches",
    # sheet_tracer score (3 seeds, exact centre)
    "tr_n", "tr_seed_rejected", "tr_on_turn_before_mean", "tr_on_turn_after_mean",
    "tr_pass_before", "tr_pass_after", "tr_pass_before_rate", "tr_pass_after_rate", "tr_repaired",
] + [f"tr_{s}_{k}" for s in ("t1mid", "t2mid", "t2low") for k in ("on_turn_before", "on_turn_after", "verdict_before", "verdict_after")]


def _load(name, path, extra_paths):
    for d in extra_paths:
        if d not in sys.path:
            sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_tools():
    ph = os.path.join(TOOLS, "phantom_scroll")
    paths = [ph] + [os.path.join(TOOLS, t) for t in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor",
                                                    "trace_repair", "sheet_tracer")]
    bm = _load("bm_benchmark", os.path.join(ph, "benchmark.py"), paths)
    sys.modules["benchmark"] = bm        # the two score scripts do `import benchmark as bm`
    aud = _load("bm_aud_score", os.path.join(TOOLS, "trace_auditor", "score_on_phantoms.py"), paths)
    trc = _load("bm_trc_score", os.path.join(TOOLS, "sheet_tracer", "score_on_phantoms.py"), paths)
    return bm, aud, trc


def _mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def job_dir(work, size, name, seed):
    return os.path.join(work, f"s{size}", f"{name}_seed{seed:02d}")


def run_job(args):
    size, name, seed, work, aud_centre = args
    t0 = time.time()
    row = dict(size=size, deformation=LABEL[name], seed=seed, status="ok", error="")
    jd = job_dir(work, size, name, seed)
    done = os.path.join(jd, "row.json")
    if os.path.isfile(done):
        return json.load(open(done))
    os.makedirs(jd, exist_ok=True)
    try:
        bm, aud, trc = load_tools()
        ps = bm.ps
        # build the phantom once on disk; the benchmark and the auditor scorer both call ps.build(p, <work>/<name>, ...)
        real_build, cache = ps.build, {}

        def build_cached(p, out, *a, **k):
            if out not in cache:
                cache[out] = real_build(p, out, *a, **k)
            return cache[out]
        ps.build = build_cached
        quiet = lambda m: None  # noqa: E731

        b = bm.run_one(name, size, seed, jd, log=quiet)
        s, c, sp = b["switch"], b["centre"], b["spacing"]
        row.update(switch_true=s["true"], switch_found=s["found"], switch_recall_trace_height=s["recall_trace_height"],
                   switch_median_col_error=s["median_col_error"], false_switches_true_turns=s["false_on_true_turns"],
                   false_switches_bad_traces=s["false_on_bad_traces"],
                   centre_n_slices=c["n"], centre_n_ok=c["n_ok"], centre_mean_err=c["mean_err"], centre_max_err=c["max_err"],
                   pitch_est=c["pitch_estimated"], pitch_true=c["pitch_true"],
                   clean_true=sp["true_mean"], clean_shared=sp["bad"].get("shared"), clean_skipped=sp["bad"].get("skipped"),
                   clean_offsheet=sp["bad"].get("off_sheet"))

        a = aud.run_phantom(name, size, seed, aud_centre, jd, quiet)
        sm = aud.summarise(a)
        pairs = [r for r in a["rows"] if r[0] == "bad" and r[1].startswith("pair")]
        sws = [r for r in a["rows"] if r[0] == "bad" and r[1].startswith("switch")]
        rate = lambda rows: (sum(1 for r in rows if r[2] == "FAIL") / len(rows)) if rows else None  # noqa: E731
        row.update(aud_centre=aud_centre, aud_true_n=sm["n_true"], aud_true_pass=sm["true_pass"], aud_true_fail=sm["true_fail"],
                   aud_true_nj=sm["true_nj"], aud_bad_n=sm["n_bad"], aud_bad_fail=sm["bad_fail"], aud_bad_pass=sm["bad_pass"],
                   aud_bad_nj=sm["bad_nj"], aud_true_pass_rate=sm["true_pass"] / max(sm["n_true"], 1),
                   aud_bad_fail_rate=sm["bad_fail"] / max(sm["n_bad"], 1), aud_bad_fail_rate_pairs=rate(pairs),
                   aud_bad_fail_rate_switches=rate(sws))

        tw = os.path.join(jd, "tracer")
        os.makedirs(tw, exist_ok=True)
        ps.build = real_build
        rows = trc.run_phantom(name, size, seed, "truth", tw, quiet)
        ok = [r for r in rows if "error" not in r]
        row.update(tr_n=len(rows), tr_seed_rejected=len(rows) - len(ok),
                   tr_on_turn_before_mean=_mean([r["on_turn_before"] for r in ok]),
                   tr_on_turn_after_mean=_mean([r["on_turn_after"] for r in ok]),
                   tr_pass_before=sum(r["verdict_before"] == "PASS" for r in ok), tr_pass_after=sum(r["verdict_after"] == "PASS" for r in ok),
                   tr_repaired=sum(bool(r["repaired"]) for r in ok))
        row["tr_pass_before_rate"] = row["tr_pass_before"] / len(rows)
        row["tr_pass_after_rate"] = row["tr_pass_after"] / len(rows)
        tag = {"t1-mid": "t1mid", "t2-mid": "t2mid", "t2-low": "t2low"}
        for r in ok:
            t = tag[r["seed"]]
            row[f"tr_{t}_on_turn_before"], row[f"tr_{t}_on_turn_after"] = r["on_turn_before"], r["on_turn_after"]
            row[f"tr_{t}_verdict_before"], row[f"tr_{t}_verdict_after"] = r["verdict_before"], r["verdict_after"]
    except Exception as e:  # noqa: BLE001  a failed job is recorded, never silently dropped
        row.update(status="error", error=f"{type(e).__name__}: {e}"[:300])
    row["seconds"] = round(time.time() - t0, 1)
    if row["status"] == "ok":
        json.dump(row, open(done, "w"), default=float)
    return row


def parse_seeds(s):
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def write_csv(path, new_rows):
    old = []
    if os.path.isfile(path):
        with open(path, newline="") as fh:
            old = list(csv.DictReader(fh))
    keys = {(str(r["size"]), r["deformation"], str(r["seed"])) for r in new_rows}
    keep = [r for r in old if (r["size"], r["deformation"], r["seed"]) not in keys]
    allr = keep + [{k: ("" if v is None else v) for k, v in r.items()} for r in new_rows]
    allr.sort(key=lambda r: (int(r["size"]), DEFORMATIONS.index(next(d for d in DEFORMATIONS if LABEL[d] == r["deformation"])), int(r["seed"])))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(allr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", default="0-19", help="e.g. 0-19 or 0,3,5-7")
    ap.add_argument("--sizes", default="192", help="comma list of cube sizes, e.g. 192 or 128,256")
    ap.add_argument("--deformations", default=",".join(DEFORMATIONS))
    ap.add_argument("--out", default=os.path.join(HERE, "results", "runs.csv"))
    ap.add_argument("--work", default=os.path.join(HERE, "results", "_cache"), help="phantom cache (gitignored)")
    ap.add_argument("--procs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--auditor-centre", choices=["estimated", "truth"], default="estimated")
    a = ap.parse_args(argv)
    jobs = [(int(sz), d, sd, a.work, a.auditor_centre) for sz in a.sizes.split(",") for d in a.deformations.split(",")
            for sd in parse_seeds(a.seeds)]
    print(f"{len(jobs)} jobs on {a.procs} processes", file=sys.stderr, flush=True)
    rows = []
    if a.procs > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(a.procs) as pool:
            for r in pool.imap_unordered(run_job, jobs):
                rows.append(r)
                print(f"  [{len(rows)}/{len(jobs)}] {r['size']} {r['deformation']} seed {r['seed']}: {r['status']} {r['seconds']}s {r['error']}",
                      file=sys.stderr, flush=True)
    else:
        for j in jobs:
            r = run_job(j)
            rows.append(r)
            print(f"  [{len(rows)}/{len(jobs)}] {r['size']} {r['deformation']} seed {r['seed']}: {r['status']} {r['seconds']}s {r['error']}",
                  file=sys.stderr, flush=True)
    write_csv(a.out, rows)
    bad = [r for r in rows if r["status"] != "ok"]
    print(f"wrote {a.out}: {len(rows)} rows, {len(bad)} errors", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
