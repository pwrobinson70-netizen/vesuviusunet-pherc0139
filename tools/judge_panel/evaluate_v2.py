#!/usr/bin/env python3
"""evaluate_v2: choose T on the tune set, report the 2x2 on the held-out set.  (MIT)

    python evaluate_v2.py --tune raw_a.csv [--heldout raw_b.csv] --out-dir results [--stem panel_v2]

Inputs are the raw-vote CSVs of `vun-panel2 --batch` (40 originals + 4 x 40 broken copies each). Rules, fixed before the held-out data is read:

* T is chosen on the tune set ONLY, from a grid 0.00 .. 1.00 step 0.01, by maximising Youden's J = detection - false alarm of the full
  panel_v2 verdict (required vote + advisory 2-of-3); ties: the median T of the plateau. The held-out CSV is not opened before T is fixed.
* Reported for every set: panel_v2, the required vote alone (surface prediction at T), the advisory CT votes alone (2 of 3, and any 1 of 3),
  detection per breakage kind (Wilson 95 %), the list of broken copies still missed, NOT JUDGED counts and the AUC of the on-sheet fraction.
* If no held-out CSV is given the tune set is reported and every table is labelled tuned-and-reported-on-the-same-data.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from panel_v2 import ADVISORY, FAIL, NJ, PASS, decide  # noqa: E402

KINDS = ("shift-half", "shift-full", "switch-mid", "scramble")


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def fmt(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]" if n else "n/a"


def load(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def auc(pos, neg):
    """P(score of a random original > score of a random broken copy), ties 1/2 (higher = more plausible)."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


SYSTEMS = {
    "panel_v2 (required surface vote at T + advisory 2-of-3)": lambda r, T: decide(r, T, 2)[0],
    "required vote alone (surface on-sheet fraction at T)": lambda r, T: decide({**r, **{k: PASS for k in ADVISORY}}, T, 2)[0],
    "advisory CT votes alone, 2 of 3 fail": lambda r, T: FAIL if sum(r.get(k) == FAIL for k in ADVISORY) >= 2 else PASS,
    "CT panel as in brief 26 (any of 3 fails)": lambda r, T: FAIL if any(r.get(k) == FAIL for k in ADVISORY) else PASS,
}


def counts(rows, fn, T):
    o = [r for r in rows if r["kind"] == "original"]
    b = [r for r in rows if r["kind"] != "original"]
    fa = sum(fn(r, T) == FAIL for r in o)
    det = sum(fn(r, T) == FAIL for r in b)
    return fa, len(o), det, len(b)


def tune(rows):
    grid = [round(0.01 * i, 2) for i in range(0, 101)]
    study = []
    for T in grid:
        fa, no, det, nb = counts(rows, SYSTEMS["panel_v2 (required surface vote at T + advisory 2-of-3)"], T)
        sfa, _, sdet, _ = counts(rows, SYSTEMS["required vote alone (surface on-sheet fraction at T)"], T)
        study.append(dict(T=T, false_alarms=fa, n_original=no, detected=det, n_broken=nb, youden_J=round(det / nb - fa / no, 4),
                          surface_only_false_alarms=sfa, surface_only_detected=sdet))
    best = max(s["youden_J"] for s in study)
    plateau = [s["T"] for s in study if abs(s["youden_J"] - best) < 1e-9]
    return study, float(np.median(plateau)), best, plateau


def report(rows, T, label):
    out = dict(label=label, T=T, systems=[], by_kind=[], misses=[], not_judged={}, auc={})
    for name, fn in SYSTEMS.items():
        fa, no, det, nb = counts(rows, fn, T)
        out["systems"].append(dict(system=name, original_fail=fa, original_not_fail=no - fa, broken_fail=det, broken_not_fail=nb - det,
                                   detection=fmt(det, nb), false_alarm=fmt(fa, no)))
        row = dict(system=name, false_alarms=fmt(fa, no))
        for k in KINDS:
            rk = [r for r in rows if r["kind"] == k]
            row[k] = fmt(sum(fn(r, T) == FAIL for r in rk), len(rk))
        out["by_kind"].append(row)
    fn = SYSTEMS["panel_v2 (required surface vote at T + advisory 2-of-3)"]
    for r in rows:
        if r["kind"] != "original" and fn(r, T) != FAIL:
            v, req, nf, why = decide(r, T, 2)
            out["misses"].append(dict(patch=r["patch"], kind=r["kind"], verdict=v, surface_on_fraction=r.get("surface_on_fraction"),
                                      advisory_fail=nf, why=why))
    for k in ("original", *KINDS):
        rk = [r for r in rows if r["kind"] == k]
        out["not_judged"][k] = sum(decide(r, T, 2)[0] == NJ for r in rk)
    sc = lambda r: float(r["surface_on_fraction"]) if r.get("surface_on_fraction") not in (None, "") else 0.0  # noqa: E731
    o = [sc(r) for r in rows if r["kind"] == "original"]
    out["auc"]["all broken"] = auc(o, [sc(r) for r in rows if r["kind"] != "original"])
    for k in KINDS:
        out["auc"][k] = auc(o, [sc(r) for r in rows if r["kind"] == k])
    out["false_alarm_patches"] = [r["patch"] for r in rows if r["kind"] == "original" and fn(r, T) == FAIL]
    return out


def md(rep):
    L = [f"### {rep['label']} (T = {rep['T']:g})", "", "| system | broken: not FAIL | broken: FAIL | original: not FAIL | original: FAIL | detection (broken FAILed) [Wilson 95%] | false alarm (originals FAILed) [Wilson 95%] |",
         "|---|---|---|---|---|---|---|"]
    for s in rep["systems"]:
        L.append(f"| {s['system']} | {s['broken_not_fail']} | {s['broken_fail']} | {s['original_not_fail']} | {s['original_fail']} | {s['detection']} | {s['false_alarm']} |")
    L += ["", "Detection by breakage kind (40 copies per kind):", "", "| system | " + " | ".join(KINDS) + " | false alarms |", "|---|" + "---|" * (len(KINDS) + 1)]
    for r in rep["by_kind"]:
        L.append(f"| {r['system']} | " + " | ".join(r[k] for k in KINDS) + f" | {r['false_alarms']} |")
    L += ["", "NOT JUDGED (panel_v2): " + ", ".join(f"{k} {v}" for k, v in rep["not_judged"].items()),
          "", "AUC of the on-sheet fraction (original vs broken): " + ", ".join(f"{k} {v:.3f}" for k, v in rep["auc"].items()), ""]
    return "\n".join(L)


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tune", required=True, help="raw votes CSV of the tune set (first 40 originals + 160 copies)")
    ap.add_argument("--heldout", help="raw votes CSV of the held-out set (opened only after T is fixed)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stem", default="panel_v2")
    ap.add_argument("--fixed-T", type=float, help="skip tuning and use this T (reproducing a recorded run)")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    tune_rows = load(a.tune)
    study, T, best, plateau = tune(tune_rows)
    if a.fixed_T is not None:
        T = a.fixed_T
    write_csv(os.path.join(a.out_dir, f"{a.stem}_threshold_study.csv"), study)
    reps = [report(tune_rows, T, "TUNE set (first 40 + 160): tuned-and-reported-on-the-same-data")]
    if a.heldout:
        reps.append(report(load(a.heldout), T, "HELD-OUT set (second 40 + 160): T fixed on the tune set"))
    flat = []
    for rep in reps:
        for s in rep["systems"]:
            flat.append(dict(set="held-out" if rep["label"].startswith("HELD") else "tune", T=T, **s))
    write_csv(os.path.join(a.out_dir, f"{a.stem}_2x2.csv"), flat)
    byk = []
    for rep in reps:
        for r in rep["by_kind"]:
            byk.append(dict(set="held-out" if rep["label"].startswith("HELD") else "tune", **r))
    write_csv(os.path.join(a.out_dir, f"{a.stem}_by_kind.csv"), byk)
    if a.heldout:
        write_csv(os.path.join(a.out_dir, f"{a.stem}_heldout_misses.csv"), reps[-1]["misses"] or [dict(patch="", kind="", verdict="", surface_on_fraction="", advisory_fail="", why="none missed")])
    with open(os.path.join(a.out_dir, f"{a.stem}_tables.md"), "w") as fh:
        fh.write(f"T chosen on the tune set: {T:g} (Youden J {best:.3f}; plateau {plateau[0]:g} .. {plateau[-1]:g}, {len(plateau)} grid points).\n\n")
        fh.write("\n".join(md(r) for r in reps) + "\n")
    print(json.dumps(dict(T=T, youden_J=best, plateau=[plateau[0], plateau[-1]],
                          sets=[dict(label=r["label"], **{s["system"]: (s["false_alarm"], s["detection"]) for s in r["systems"]}) for r in reps]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
