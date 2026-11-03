#!/usr/bin/env python3
"""report: grid.csv + sweeps.csv -> PNGs under docs/calibration/ and docs/OPERATING_RANGE.md (MIT). Needs matplotlib.

    python tools/calibration/report.py [--grid results/grid.csv] [--sweeps results/sweeps.csv] [--docs docs]

Balanced correctness = (mean verdict_correct over true cases + mean over bad cases) / 2, so a tool cannot score by
always saying PASS (or always FAIL). Classes (flags): reliable >= --reliable (0.95), degraded >= --degraded (0.70),
else fails. Text you write by hand goes in docs/calibration/commentary.md and is embedded verbatim.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from sweep_thresholds import SWEEPS, default_of  # noqa: E402

TOOLS = ["sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor"]
SHORT = {"sheet_spacing_check": "ssc", "sheet_switch_finder": "ssf", "umbilicus_finder": "uf", "trace_auditor": "ta"}
DEFORMS = ["round", "mild", "crushed", "merged"]
MIN_GAIN = 0.005      # a default is only proposed for change if the chosen value gains at least this much
C_TRUE, C_BAD, C_BAL, C_DEF, C_SEL = "#0072B2", "#D55E00", "#222222", "#888888", "#009E73"


def read(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def fnum(x):
    return float(x) if x not in ("", None) else float("nan")


def balanced(rows):
    t = [fnum(r["verdict_correct"]) for r in rows if r["kind"] == "true"]
    b = [fnum(r["verdict_correct"]) for r in rows if r["kind"] == "bad"]
    parts = [np.mean(x) for x in (t, b) if x]
    return (float(np.mean(parts)) if parts else float("nan"),
            float(np.mean(t)) if t else float("nan"), float(np.mean(b)) if b else float("nan"), len(t) + len(b))


def classify(v, rel, deg):
    return "nan" if not np.isfinite(v) else ("reliable" if v >= rel else "degraded" if v >= deg else "fails")


def grid_tables(rows):
    """tool -> {(deform, pitch, step): (bal, true, bad, n)}; the umbilicus_finder has step None (same for every step)."""
    g = defaultdict(list)
    for r in rows:
        st = None if r["tool"] == "umbilicus_finder" else float(r["grid_step"])
        g[(r["tool"], r["deform"], float(r["pitch"]), st)].append(r)
    out = defaultdict(dict)
    for (tool, d, p, st), rs in g.items():
        out[tool][(d, p, st)] = balanced(rs)
    return out


def plot_grid(tool, tab, steps, pitches, path, rel, deg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    cmap = ListedColormap(["#D55E00", "#F0E442", "#009E73"])
    norm = BoundaryNorm([0, deg, rel, 1.0001], cmap.N)
    fig, axs = plt.subplots(1, 4, figsize=(14, 3.6), sharey=True)
    for ax, d in zip(axs, DEFORMS):
        M = np.full((len(pitches), len(steps)), np.nan)
        for i, p in enumerate(pitches):
            for j, s in enumerate(steps):
                v = tab.get((d, p, None if tool == "umbilicus_finder" else s))
                if v:
                    M[i, j] = v[0]
        ax.imshow(np.ma.masked_invalid(M), cmap=cmap, norm=norm, origin="lower", aspect="auto")
        for i in range(len(pitches)):
            for j in range(len(steps)):
                if np.isfinite(M[i, j]):
                    ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=9)
        ax.set_xticks(range(len(steps)), [f"{s:g}" for s in steps])
        ax.set_xlabel("grid step (vox)")
        ax.set_title(d)
    axs[0].set_yticks(range(len(pitches)), [f"{p:g}" for p in pitches])
    axs[0].set_ylabel("sheet pitch (vox)")
    fig.suptitle(f"{tool}: balanced verdict correctness  (green >= {rel:g}, yellow >= {deg:g}, red below)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def sweep_curves(rows):
    """(group, param) -> sorted [(value, bal, true, bad, n)]"""
    g = defaultdict(list)
    for r in rows:
        g[(r["group"], r["param"], float(r["value"]))].append(r)
    cur = defaultdict(list)
    for (grp, par, v), rs in g.items():
        cur[(grp, par)].append((v,) + balanced(rs))
    return {k: sorted(v) for k, v in cur.items()}


def choose(curve, default):
    """Value whose own score and both neighbours' scores are best (a plateau, not a spike); ties -> nearest the default."""
    sc = np.array([c[1] for c in curve])
    vals = np.array([c[0] for c in curve])
    rob = np.array([np.nanmin(sc[max(0, i - 1):i + 2]) for i in range(len(sc))])
    best = np.nanmax(rob)
    cand = np.nonzero(rob >= best - 1e-9)[0]
    i = int(cand[np.argmin(np.abs(vals[cand] - default))])
    near = np.nonzero(sc >= sc[i] - 0.01)[0]
    lo = hi = i
    while lo - 1 in near:
        lo -= 1
    while hi + 1 in near:
        hi += 1
    return i, float(vals[lo]), float(vals[hi]), float(rob[i])


def plot_sweeps(tool_group, curves, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    keys = [k for k in curves if k[0] == tool_group]
    keys.sort(key=lambda k: [s[2] for s in SWEEPS if s[1] == k[0]].index(k[1]) if False else [s[2] for s in SWEEPS].index(k[1]))
    n = len(keys)
    cols = min(4, n)
    rws = int(np.ceil(n / cols))
    fig, axs = plt.subplots(rws, cols, figsize=(3.6 * cols, 2.9 * rws), squeeze=False)
    for ax in axs.ravel():
        ax.axis("off")
    for ax, k in zip(axs.ravel(), keys):
        ax.axis("on")
        c = curves[k]
        v = [x[0] for x in c]
        ax.plot(v, [x[2] for x in c], "o-", color=C_TRUE, ms=3, label="true")
        ax.plot(v, [x[3] for x in c], "s-", color=C_BAD, ms=3, label="bad")
        ax.plot(v, [x[1] for x in c], "-", color=C_BAL, lw=2, label="balanced")
        d = default_of(*k)
        i, *_ = choose(c, d)
        ax.axvline(d, color=C_DEF, ls="--", lw=1)
        ax.axvline(v[i], color=C_SEL, ls=":", lw=1.5)
        ax.axhline(0.95, color="#bbbbbb", lw=0.6)
        ax.set_ylim(-0.03, 1.05)
        ax.set_title(f"{k[1]}", fontsize=9)
        ax.tick_params(labelsize=7)
    axs[0, 0].legend(fontsize=7, loc="lower left")
    fig.suptitle(f"{tool_group}: verdict correctness vs threshold  (dashed grey = current default, dotted green = chosen)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def md_table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def regions(tab, tool, steps, pitches, rel, deg):
    lines = []
    for d in DEFORMS:
        for cls in ("reliable", "degraded", "fails"):
            cells = [(p, s) for p in pitches for s in steps
                     if (v := tab.get((d, p, None if tool == "umbilicus_finder" else s))) and classify(v[0], rel, deg) == cls]
            if cells:
                by_p = defaultdict(list)
                for p, s in cells:
                    by_p[p].append(s)
                txt = "; ".join(f"pitch {p:g}: " + (f"steps {', '.join(f'{s:g}' for s in ss)}" if tool != "umbilicus_finder" else "any step")
                                for p, ss in sorted(by_p.items()))
                lines.append(f"- {d}, **{cls}**: {txt}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--grid", default=os.path.join(HERE, "results", "grid.csv"))
    ap.add_argument("--sweeps", default=os.path.join(HERE, "results", "sweeps.csv"))
    ap.add_argument("--docs", default=os.path.normpath(os.path.join(HERE, "..", "..", "docs")))
    ap.add_argument("--reliable", type=float, default=0.95)
    ap.add_argument("--degraded", type=float, default=0.70)
    a = ap.parse_args(argv)
    png = os.path.join(a.docs, "calibration")
    os.makedirs(png, exist_ok=True)
    out = ["# Operating range of the trace-checking tools\n",
           "Measured on `phantom_scroll` phantoms (synthetic, exact truth). **Not** a statement about real scrolls: a region marked "
           "reliable here is a necessary condition, not evidence of success on scan data. Everything below is regenerated by "
           "`tools/calibration/report.py` from `tools/calibration/results/*.csv`; the hand-written commentary is "
           "`docs/calibration/commentary.md`.\n"]
    if os.path.isfile(os.path.join(png, "commentary.md")):
        out.append(open(os.path.join(png, "commentary.md")).read().rstrip() + "\n")
    rows = read(a.grid) if os.path.isfile(a.grid) else []
    if rows:
        seeds = sorted({r["seed"] for r in rows})
        steps = sorted({float(r["grid_step"]) for r in rows if r["grid_step"]})
        pitches = sorted({float(r["pitch"]) for r in rows})
        tabs = grid_tables(rows)
        out.append(f"## 1. Grid\n\n{len(seeds)} seeds x grid step {', '.join(f'{s:g}' for s in steps)} vox x sheet pitch "
                   f"{', '.join(f'{p:g}' for p in pitches)} vox x deformation {', '.join(DEFORMS)}; volume {rows[0]['size']}^3; "
                   f"{len(rows)} rows in `tools/calibration/results/grid.csv`. Cell value = balanced verdict correctness over all seeds "
                   f"(see the module docstring of `calib.py` for what correct means per tool). Classes: **reliable** >= {a.reliable:g}, "
                   f"**degraded** {a.degraded:g} to {a.reliable:g}, **fails** < {a.degraded:g}. Sheets that fall mostly outside the "
                   "volume (valid cells < 30%) are not tested, so pitch 60 at 192^3 only tests the first one or two sheets "
                   "(`valid_frac` column).\n")
        summary = []
        for tool in TOOLS:
            if tool not in tabs:
                continue
            f = f"grid_{SHORT[tool]}.png"
            plot_grid(tool, tabs[tool], steps, pitches, os.path.join(png, f), a.reliable, a.degraded)
            out.append(f"### {tool}\n\n![{tool}](calibration/{f})\n\n{regions(tabs[tool], tool, steps, pitches, a.reliable, a.degraded)}\n")
            for (d, p, s), (b, t, bd, n) in sorted(tabs[tool].items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0)):
                summary.append([tool, d, f"{p:g}", "" if s is None else f"{s:g}", f"{b:.4f}", f"{t:.4f}", f"{bd:.4f}", n])
        with open(os.path.join(os.path.dirname(a.grid), "grid_summary.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["tool", "deform", "pitch", "grid_step", "balanced", "true_correct", "bad_correct", "n_cases"])
            w.writerows(summary)
    if os.path.isfile(a.sweeps):
        curves = sweep_curves(read(a.sweeps))
        out.append("## 2. Threshold sweeps\n\nOne threshold varied at a time, others at their defaults, fixed phantoms "
                   "(`sweep_thresholds.py`). `true` = share of correct verdicts on true traces (false alarms are the rest), `bad` = on the "
                   "planted-fault traces (misses are the rest), balanced = their mean. Chosen = the value whose own score and both "
                   "neighbours' scores are best (a plateau, not a spike); ties go to the value nearest the default. "
                   "Plateau = the contiguous range around the chosen value within 0.01 of its score. **No default was changed.**\n")
        prop = []
        for grp, name in (("ssc", "sheet_spacing_check"), ("ssf", "sheet_switch_finder"), ("uf", "umbilicus_finder"), ("ta", "trace_auditor")):
            ks = [k for k in curves if k[0] == grp]
            if not ks:
                continue
            f = f"sweep_{grp}.png"
            plot_sweeps(grp, curves, os.path.join(png, f))
            tr = []
            for _, g2, field, _ in SWEEPS:
                if g2 != grp or (grp, field) not in curves:
                    continue
                c = curves[(grp, field)]
                d = default_of(grp, field)
                i, plo, phi, rob = choose(c, d)
                di = [x[0] for x in c].index(d)
                tr.append([f"`{field}`", f"{d:g}", f"{c[di][1]:.3f}", f"{c[i][0]:g}", f"{c[i][1]:.3f}", f"{plo:g} to {phi:g}",
                           f"{c[i][2]:.2f} / {c[i][3]:.2f}"])
                edge = c[i][0] in (c[0][0], c[-1][0])
                prop.append((name, field, d, c[di][1], c[i][0], c[i][1], plo, phi, edge))
            out.append(f"### {name}\n\n![{name} sweeps](calibration/{f})\n\n" + md_table(
                ["threshold", "default", "balanced at default", "chosen", "balanced at chosen", "plateau", "true / bad at chosen"], tr) + "\n")
        with open(os.path.join(os.path.dirname(a.sweeps), "proposed_defaults.md"), "w") as fh:
            for name, field, d, bd, ch, bc, lo, hi, edge in prop:
                if bc - bd < MIN_GAIN:
                    verb = f"keep (best value {ch:g} gains only {bc - bd:+.3f}: flat)"
                else:
                    verb = f"change to {ch:g} ({bd:.3f} -> {bc:.3f}, plateau {lo:g} to {hi:g})" + (
                        "; CHOSEN VALUE IS AT THE EDGE OF THE SWEPT RANGE, sweep wider before adopting" if edge else "")
                fh.write(f"- {name}.{field}: {verb}\n")
    with open(os.path.join(a.docs, "OPERATING_RANGE.md"), "w") as fh:
        fh.write("\n".join(out))
    print(os.path.join(a.docs, "OPERATING_RANGE.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
