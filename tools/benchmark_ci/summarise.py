#!/usr/bin/env python3
"""benchmark_ci summary: per metric and deformation, mean / median / 95% bootstrap CI of the mean / min / max / n (MIT).

    python tools/benchmark_ci/summarise.py tools/benchmark_ci/results/runs.csv --md docs/BENCHMARK_CI.md --png-dir docs/benchmark_ci

Reads the CSV written by run.py (numpy + csv only; matplotlib only for the PNGs, skipped with a note if missing). The CI is the
percentile bootstrap of the MEAN over seeds (--resamples 1000, fixed --rng-seed, so the table is reproducible). A metric with a pass
threshold (the trace_auditor default it is judged against) is FLAGGED where mean's CI contains the threshold, i.e. the data cannot
say on which side of the threshold the typical run lies. This is measurement of the current defaults, not a threshold sweep.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

DEFORMATIONS = ["round", "mild", "crushed", "merged"]

# column, title, what it is, (threshold, "ge" | "le", what the threshold is) or None
MIN_CLEAN = 0.8          # trace_auditor Params.min_clean_fraction (spacing check: PASS if mean clean fraction >= this)
METRICS = [
    ("switch_recall_trace_height", "Switch recall (trace x height)", "fraction of (bad trace, height) with the planted switch found", None),
    ("false_switches_true_turns", "False switches on true turns", "count per phantom (4 true turns); expected 0", None),
    ("false_switches_bad_traces", "Spurious switches on bad traces", "count per phantom (3 bad traces) besides the planted ones", None),
    ("switch_median_col_error", "Switch column error (median)", "columns, found switches", None),
    ("centre_mean_err", "Centre error, mean", "voxels, umbilicus_finder vs exact centre line", None),
    ("centre_max_err", "Centre error, max", "voxels", None),
    ("clean_true", "Spacing clean fraction, true pairs", "mean over the 3 true adjacent pairs; auditor PASS needs >= 0.8",
     (MIN_CLEAN, "ge", "min_clean_fraction 0.8")),
    ("clean_shared", "Spacing clean fraction, shared sheet", "bad pair; auditor FAILs below 0.8", (MIN_CLEAN, "le", "min_clean_fraction 0.8")),
    ("clean_skipped", "Spacing clean fraction, skipped sheet", "bad pair; auditor FAILs below 0.8", (MIN_CLEAN, "le", "min_clean_fraction 0.8")),
    ("clean_offsheet", "Spacing clean fraction, off-sheet", "bad pair; auditor FAILs below 0.8", (MIN_CLEAN, "le", "min_clean_fraction 0.8")),
    ("aud_true_pass_rate", "Auditor: PASS rate on true traces", "7 true audits per phantom", None),
    ("aud_bad_fail_rate", "Auditor: FAIL rate on bad traces", "6 bad audits per phantom", None),
    ("aud_bad_fail_rate_pairs", "Auditor: FAIL rate, wrong-sheet pairs", "3 pair audits per phantom", None),
    ("aud_bad_fail_rate_switches", "Auditor: FAIL rate, planted switches", "3 switch audits per phantom", None),
    ("tr_on_turn_before_mean", "Tracer: points on the seed's turn", "fraction, mean of 3 seeds, before repair", None),
    ("tr_on_turn_after_mean", "Tracer: points on the seed's turn, repaired", "fraction, after trace_repair where the audit FAILed", None),
    ("tr_pass_before_rate", "Tracer: auditor PASS rate", "of 3 patches, before repair", None),
    ("tr_pass_after_rate", "Tracer: auditor PASS rate, repaired", "of 3 patches, after repair", None),
]


def bootstrap_ci(x, resamples=1000, level=0.95, seed=0):
    """Percentile bootstrap CI of the mean. A constant sample gives a zero-width interval."""
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(resamples, len(x)))].mean(axis=1)
    a = (1 - level) / 2
    return float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


def stats(x, resamples=1000, seed=0):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if not len(x):
        return None
    lo, hi = bootstrap_ci(x, resamples, seed=seed)
    return dict(n=int(len(x)), mean=float(x.mean()), median=float(np.median(x)), lo=lo, hi=hi, min=float(x.min()), max=float(x.max()))


def read_rows(path):
    with open(path, newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("status", "ok") == "ok"]


def column(rows, key, size, deformation, seeds=None):
    out = []
    for r in rows:
        if int(r["size"]) != size or r["deformation"] != deformation:
            continue
        if seeds is not None and int(r["seed"]) not in seeds:
            continue
        v = r.get(key, "")
        if v not in ("", None):
            out.append(float(v))
    return out


def crosses(st, thr):
    return st is not None and st["lo"] <= thr[0] <= st["hi"]


def wrong_side(values, thr):
    """Runs on the wrong side of the threshold: a 'ge' metric (true pairs) should be >= it, a 'le' metric (bad pairs) below it."""
    return int(sum(1 for v in values if (v < thr[0] if thr[1] == "ge" else v >= thr[0])))


def fmt(v, d=3):
    return "n/a" if v is None else f"{v:.{d}f}"


def main_table(rows, size, resamples, seed):
    lines = ["| metric | deformation | runs | mean | median | 95% CI of mean | min | max | flag |", "|---|---|---|---|---|---|---|---|---|"]
    flagged, wrong, table = [], [], {}
    for key, title, _, thr in METRICS:
        for d in DEFORMATIONS:
            st = stats(column(rows, key, size, d), resamples, seed)
            table[(key, d)] = st
            if st is None:
                lines.append(f"| {title} | {d} | 0 | n/a | n/a | n/a | n/a | n/a | |")
                continue
            flag = ""
            if thr:
                vals = column(rows, key, size, d)
                nw = wrong_side(vals, thr)
                if crosses(st, thr):
                    flag = f"CI crosses {thr[2]}"
                    flagged.append((title, d, st, thr))
                if nw:
                    flag = (flag + "; " if flag else "") + f"{nw}/{len(vals)} runs on the wrong side"
                    wrong.append((title, d, nw, len(vals), min(vals) if thr[1] == "ge" else max(vals), thr))
            lines.append(f"| {title} | {d} | {st['n']} | {fmt(st['mean'])} | {fmt(st['median'])} | [{fmt(st['lo'])}, {fmt(st['hi'])}] | "
                         f"{fmt(st['min'])} | {fmt(st['max'])} | {flag} |")
    return "\n".join(lines), flagged, wrong, table


def size_table(rows, sizes, seeds, resamples, seed):
    keys = [m for m in METRICS if m[0] in ("switch_recall_trace_height", "false_switches_true_turns", "centre_mean_err", "clean_true",
                                          "clean_skipped", "clean_shared", "clean_offsheet", "aud_true_pass_rate", "aud_bad_fail_rate",
                                          "tr_on_turn_before_mean", "tr_pass_before_rate")]
    head = "| metric | deformation | " + " | ".join(f"{s}^3" for s in sizes) + " |"
    lines = [head, "|---|---|" + "---|" * len(sizes)]
    for key, title, _, _ in keys:
        for d in DEFORMATIONS:
            cells = []
            for s in sizes:
                st = stats(column(rows, key, s, d, seeds), resamples, seed)
                cells.append("n/a" if st is None else f"{st['mean']:.3f} [{st['lo']:.3f}, {st['hi']:.3f}] (n={st['n']})")
            lines.append(f"| {title} | {d} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def plots(rows, size, png_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib missing: PNGs skipped", file=sys.stderr)
        return []
    os.makedirs(png_dir, exist_ok=True)
    made = []
    rng = np.random.default_rng(0)
    for key, title, what, thr in METRICS:
        data = [column(rows, key, size, d) for d in DEFORMATIONS]
        if not any(len(v) for v in data):
            continue
        fig, ax = plt.subplots(figsize=(6, 3.8), dpi=110)
        ax.boxplot([v if len(v) else [np.nan] for v in data], positions=range(len(DEFORMATIONS)), widths=0.5, showfliers=False)
        for i, v in enumerate(data):
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(v)), v, s=14, alpha=0.6, zorder=3)
        if thr:
            ax.axhline(thr[0], color="crimson", ls="--", lw=1, label=thr[2])
            ax.legend(fontsize=7, loc="best")
        ax.set_xticks(range(len(DEFORMATIONS)))
        ax.set_xticklabels(DEFORMATIONS)
        ax.set_title(f"{title}  ({size}^3, one point per seed)", fontsize=9)
        ax.set_ylabel(what[:48], fontsize=7)
        fig.tight_layout()
        p = os.path.join(png_dir, f"{key}.png")
        fig.savefig(p)
        plt.close(fig)
        made.append(p)
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv")
    ap.add_argument("--size", type=int, default=192, help="size of the main many-seed table")
    ap.add_argument("--sensitivity-sizes", default="128,192,256")
    ap.add_argument("--sensitivity-seeds", default="0-4")
    ap.add_argument("--resamples", type=int, default=1000)
    ap.add_argument("--rng-seed", type=int, default=0)
    ap.add_argument("--md", help="write the markdown report here")
    ap.add_argument("--png-dir")
    a = ap.parse_args(argv)
    rows = read_rows(a.csv)
    lo, _, hi = a.sensitivity_seeds.partition("-")
    seeds = set(range(int(lo), int(hi or lo) + 1))
    sizes = [int(s) for s in a.sensitivity_sizes.split(",")]
    tbl, flagged, wrong, _ = main_table(rows, a.size, a.resamples, a.rng_seed)
    nseeds = sorted({int(r["seed"]) for r in rows if int(r["size"]) == a.size})
    out = [f"# Benchmark with confidence intervals ({a.size}^3, {len(nseeds)} seeds)", "",
           "Generated by `tools/benchmark_ci/summarise.py` from `tools/benchmark_ci/results/runs.csv` (written by `run.py`). "
           "Measurement only: the tools run at their current defaults; nothing is tuned. CI = 95% percentile bootstrap of the mean "
           f"over seeds ({a.resamples} resamples, rng seed {a.rng_seed}). The seeds are phantom seeds: the CI says how much a quoted number "
           "moves with the random phantom (texture, warp, wobble), not how a real scroll behaves.", "",
           "## Flags: CI crosses a pass threshold", ""]
    if flagged:
        for title, d, st, thr in flagged:
            out.append(f"- **{title}, {d}**: mean {st['mean']:.3f}, CI [{st['lo']:.3f}, {st['hi']:.3f}] contains {thr[2]}.")
    else:
        out.append("None: no CI of the mean contains the threshold it is judged against (only the spacing clean fractions have a numeric auditor threshold).")
    out += ["", "Single runs on the wrong side of that threshold (true pairs should be >= 0.8, bad pairs below it):", ""]
    if wrong:
        for title, d, nw, n, ext, thr in wrong:
            out.append(f"- {title}, {d}: {nw} of {n} runs ({'lowest' if thr[1] == 'ge' else 'highest'} {ext:.3f}).")
    else:
        out.append("- none.")
    out += ["", "## Per metric and deformation", "", tbl, "", f"## Sensitivity to size (seeds {a.sensitivity_seeds})", "",
            "Mean [95% CI] over those seeds; with n this small the CIs are wide, read the means for a trend only.", "",
            size_table(rows, sizes, seeds, a.resamples, a.rng_seed), "", "## Metrics", ""]
    out += [f"- `{k}`: {t}. {w}." for k, t, w, _ in METRICS]
    out += ["", "Plots: `docs/benchmark_ci/<metric>.png` (box plot with one point per seed)." if a.png_dir else ""]
    if a.png_dir:
        plots(rows, a.size, a.png_dir)
    if a.md:
        os.makedirs(os.path.dirname(os.path.abspath(a.md)), exist_ok=True)
        with open(a.md, "w") as fh:
            fh.write("\n".join(out) + "\n")
    else:
        print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
