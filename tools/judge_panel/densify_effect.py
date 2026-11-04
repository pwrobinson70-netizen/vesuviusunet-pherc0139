"""densify_effect: NOT JUDGED and the CT 2x2 on coarse vs densified traces (tune set).  (MIT)

    python densify_effect.py --coarse results/groundtruth_panel_scores.csv --dense results/panel_v2_densify_scores_set_a.csv \
        --dense-scaled results/panel_v2_raw_set_a.csv --out results/panel_v2_densify_effect.csv

Columns of the three inputs are the ones written by tools/groundtruth_score/score.py (coarse, dense) and by vun-panel2 --batch (dense-scaled:
densified, CT point-count parameters x the densify factor). The CT panel is "any of trace_auditor default, trace_auditor --global-pitch,
sheet_switch_finder FAILs" (the brief 26 panel).
"""
import argparse
import csv
import sys

TOOLS = ("audit_default", "audit_global", "switch")


def load(p):
    return list(csv.DictReader(open(p)))


def rows_for(name, R):
    out = []
    o = [r for r in R if r["kind"] == "original"]
    b = [r for r in R if r["kind"] != "original"]
    for t in TOOLS:
        out.append(dict(variant=name, tool=t, not_judged_of_200=sum(r.get(t) == "NOT JUDGED" for r in R),
                        not_judged_originals=sum(r.get(t) == "NOT JUDGED" for r in o),
                        fail_originals=sum(r.get(t) == "FAIL" for r in o), fail_broken=sum(r.get(t) == "FAIL" for r in b)))
    anyf = lambda r: any(r.get(t) == "FAIL" for t in TOOLS)  # noqa: E731
    out.append(dict(variant=name, tool="CT panel (any of 3)", not_judged_of_200="", not_judged_originals="",
                    fail_originals=sum(anyf(r) for r in o), fail_broken=sum(anyf(r) for r in b)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--coarse", required=True)
    ap.add_argument("--dense", required=True)
    ap.add_argument("--dense-scaled", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rows = rows_for("coarse", load(a.coarse)) + rows_for("densified 1 voxel, unscaled CT parameters", load(a.dense)) \
        + rows_for("densified 1 voxel, CT point-count parameters x20", load(a.dense_scaled))
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
