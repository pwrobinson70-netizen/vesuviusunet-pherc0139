"""analyse: the real-data 2x2 (false alarms on the verified originals x detection of the broken copies) from score.py's CSV.  (MIT)

    python analyse.py results/groundtruth_panel_scores.csv --sweeps results/threshold_study --out-dir results

Writes results/groundtruth_2x2.csv, groundtruth_detection_by_kind.csv, groundtruth_caught_by.csv, groundtruth_surface_auc.csv,
groundtruth_threshold_study.csv and results/REALDATA_2X2_tables.md (the tables docs/REALDATA_2X2.md quotes).
FAIL is the positive call; PASS and NOT JUDGED both count as "not detected" (NOT JUDGED is also counted separately).
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import sys

import numpy as np

BROKEN = ("shift-half", "shift-full", "switch-mid", "scramble")
CT_TOOLS = ("audit_default", "audit_global", "switch")
ALL_TOOLS = CT_TOOLS + ("spacing", "surface")
LABEL = dict(audit_default="trace_auditor (default, local pitch)", audit_global="trace_auditor --global-pitch",
             switch="sheet_switch_finder", spacing="sheet_spacing_check (self-pair; degenerate)", surface="surface_agreement (m7 prediction)")


def wilson(k, n, z=1.959964):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def fmt(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]" if n else "n/a"


def load(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def calls(rows, panel):
    """Per row: True if the panel (a tuple of tool names, 'any FAIL') calls FAIL."""
    return np.array([any(r.get(t) == "FAIL" for t in panel) for r in rows])


def kinds_of(rows):
    return np.array([r["kind"] for r in rows])


def rates(rows, panel):
    k = kinds_of(rows)
    f = calls(rows, panel)
    o = k == "original"
    b = ~o
    return dict(fa=int(f[o].sum()), n_o=int(o.sum()), det=int(f[b].sum()), n_b=int(b.sum()),
                det_by_kind={kk: (int(f[k == kk].sum()), int((k == kk).sum())) for kk in BROKEN})


def auc(neg_scores, pos_scores):
    """P(score of a broken case is LOWER than an original's), ties 1/2 (scores: on-fraction; low = suspicious)."""
    a = np.asarray(pos_scores, float)[:, None]
    b = np.asarray(neg_scores, float)[None, :]
    return float(((a < b) + 0.5 * (a == b)).mean())


def table_2x2(name, r):
    fa, no, det, nb = r["fa"], r["n_o"], r["det"], r["n_b"]
    return (f"| {name} | {nb - det} | {det} | {no - fa} | {fa} | {fmt(det, nb)} | {fmt(fa, no)} |")


def study(sweeps, base_rows, panel_fn):
    """Panel FA / detection for every sweep CSV; returns list of dict."""
    out = []
    for f in sorted(glob.glob(os.path.join(sweeps, "*.csv"))):
        name = os.path.basename(f)[:-4]
        knob, val = name.rsplit("_", 1)
        rows = load(f)
        r = rates(rows, panel_fn)
        out.append(dict(knob=knob, value=float(val), rows=rows, **r))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scores")
    ap.add_argument("--sweeps", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    rows = load(a.scores)
    k = kinds_of(rows)
    L = []
    P = lambda *s: L.append(" ".join(str(x) for x in s))   # noqa: E731

    # ------------------------------------------------------------------ 2x2 per tool and panels
    units = {t: (t,) for t in ALL_TOOLS}
    panels = {"PANEL (any of trace_auditor default, trace_auditor --global-pitch, sheet_switch_finder)": CT_TOOLS,
              "PANEL + surface_agreement": CT_TOOLS + ("surface",)}
    P("### 2x2 per tool and for the panel (rows: truth; FAIL = the tool calls the trace broken)\n")
    P("| tool | broken: not FAIL | broken: FAIL | original: not FAIL | original: FAIL | detection rate (160 broken) [Wilson 95%] | false-alarm rate (40 verified) [Wilson 95%] |")
    P("|---|---|---|---|---|---|---|")
    csv_rows = []
    for t in ALL_TOOLS:
        r = rates(rows, (t,))
        P(table_2x2(LABEL[t], r))
        csv_rows.append(dict(unit=t, **{kk: r[kk] for kk in ("fa", "n_o", "det", "n_b")}))
    for name, pt in panels.items():
        r = rates(rows, pt)
        P(table_2x2("**" + name + "**", r))
        csv_rows.append(dict(unit=name, **{kk: r[kk] for kk in ("fa", "n_o", "det", "n_b")}))
    P("")
    P("NOT JUDGED counts (a NOT JUDGED verdict is neither FAIL nor PASS; it counts as not detected above):\n")
    P("| tool | original | " + " | ".join(BROKEN) + " |")
    P("|---|---|" + "---|" * len(BROKEN))
    for t in ALL_TOOLS:
        cells = [str(sum(1 for r in rows if r["kind"] == kk and r.get(t) == "NOT JUDGED")) for kk in ("original",) + BROKEN]
        P(f"| {LABEL[t]} | " + " | ".join(cells) + " |")
    P("")
    write_csv(os.path.join(a.out_dir, "groundtruth_2x2.csv"), csv_rows)

    # ------------------------------------------------------------------ per kind detection
    P("### Detection by kind (fraction FAILED, 40 patches per kind; Wilson 95% interval)\n")
    P("| unit | " + " | ".join(BROKEN) + " | false alarms on originals |")
    P("|---|" + "---|" * (len(BROKEN) + 1))
    kind_rows = []
    for t in ALL_TOOLS:
        r = rates(rows, (t,))
        P(f"| {LABEL[t]} | " + " | ".join(fmt(*r['det_by_kind'][kk]) for kk in BROKEN) + f" | {fmt(r['fa'], r['n_o'])} |")
        for kk in BROKEN:
            kind_rows.append(dict(unit=t, kind=kk, failed=r["det_by_kind"][kk][0], n=r["det_by_kind"][kk][1]))
    for name, pt in panels.items():
        r = rates(rows, pt)
        P(f"| **{name}** | " + " | ".join(fmt(*r['det_by_kind'][kk]) for kk in BROKEN) + f" | {fmt(r['fa'], r['n_o'])} |")
        for kk in BROKEN:
            kind_rows.append(dict(unit=name, kind=kk, failed=r["det_by_kind"][kk][0], n=r["det_by_kind"][kk][1]))
    P("")
    write_csv(os.path.join(a.out_dir, "groundtruth_detection_by_kind.csv"), kind_rows)

    # ------------------------------------------------------------------ who caught it
    P("### Which tool caught it (number of the 40 broken copies of each kind each tool FAILED; 'only' = no other panel tool failed it)\n")
    P("| kind | " + " | ".join(LABEL[t] for t in CT_TOOLS + ("surface",)) + " | caught by none of the CT tools | caught by nothing (incl. surface) |")
    P("|---|" + "---|" * (len(CT_TOOLS) + 3))
    caught = []
    for kk in BROKEN:
        sub = [r for r in rows if r["kind"] == kk]
        cells = []
        for t in CT_TOOLS + ("surface",):
            n = sum(1 for r in sub if r.get(t) == "FAIL")
            only = sum(1 for r in sub if r.get(t) == "FAIL" and not any(r.get(u) == "FAIL" for u in CT_TOOLS + ("surface",) if u != t))
            cells.append(f"{n} ({only} only)")
            caught.append(dict(kind=kk, tool=t, failed=n, only_this_tool=only))
        none_ct = sum(1 for r in sub if not any(r.get(u) == "FAIL" for u in CT_TOOLS))
        none_all = sum(1 for r in sub if not any(r.get(u) == "FAIL" for u in CT_TOOLS + ("surface",)))
        P(f"| {kk} | " + " | ".join(cells) + f" | {none_ct}/{len(sub)} | {none_all}/{len(sub)} |")
    P("")
    write_csv(os.path.join(a.out_dir, "groundtruth_caught_by.csv"), caught)

    # ------------------------------------------------------------------ part C: surface prediction alone
    P("### Part C: does the surface prediction alone separate originals from broken copies?\n")
    P("Score = ON-PREDICTED-SHEET fraction per trace (low = suspicious). AUC = P(an original scores higher than a broken copy), ties 1/2.\n")
    P("| comparison | AUC | n originals | n broken |")
    P("|---|---|---|---|")
    on = np.array([float(r["surface_on_fraction"]) if r.get("surface_on_fraction") not in (None, "") else np.nan for r in rows])
    ok = np.isfinite(on)
    auc_rows = []
    sets = [("originals vs ALL broken", BROKEN)] + [(f"originals vs {kk}", (kk,)) for kk in BROKEN]
    for name, ks in sets:
        pos = on[ok & (k == "original")]
        neg = on[ok & np.isin(k, ks)]
        v = auc(pos, neg)
        # bootstrap over patches would be better; report the plain AUC and a Hanley-McNeil 95% interval
        P(f"| {name} | {v:.3f} | {len(pos)} | {len(neg)} |")
        auc_rows.append(dict(comparison=name, auc=round(v, 4), n_original=len(pos), n_broken=len(neg)))
    P("")
    write_csv(os.path.join(a.out_dir, "groundtruth_surface_auc.csv"), auc_rows)

    # ------------------------------------------------------------------ threshold study
    P("### Threshold study (panel = trace_auditor default + --global-pitch + sheet_switch_finder)\n")
    base = rates(rows, CT_TOOLS)
    P(f"Before (all defaults): false alarms {fmt(base['fa'], base['n_o'])}, detection {fmt(base['det'], base['n_b'])}.\n")
    sw = study(a.sweeps, rows, CT_TOOLS)
    th_rows = []
    P("| knob | value | false alarms on 40 originals | detection on 160 broken | detection shift-half / shift-full / switch-mid / scramble |")
    P("|---|---|---|---|---|")
    for s in sorted(sw, key=lambda s: (s["knob"], s["value"])):
        P(f"| {s['knob']} | {s['value']:g} | {s['fa']}/{s['n_o']} | {s['det']}/{s['n_b']} | " +
          " / ".join(f"{s['det_by_kind'][kk][0]}" for kk in BROKEN) + " |")
        th_rows.append(dict(knob=s["knob"], value=s["value"], fa=s["fa"], n_o=s["n_o"], det=s["det"], n_b=s["n_b"],
                            **{f"det_{kk}": s["det_by_kind"][kk][0] for kk in BROKEN}))
    P("")
    okc = [s for s in sw if s["fa"] <= base["fa"]]
    best = max(okc, key=lambda s: (s["det"], -abs(s["value"])))
    P(f"Best single setting with false alarms held at or below the default's {base['fa']}/{base['n_o']}: **{best['knob']} = {best['value']:g}**: "
      f"false alarms {fmt(best['fa'], best['n_o'])}, detection {fmt(best['det'], best['n_b'])}.\n")
    # two-fold check by patch (even / odd index): choose on one half, apply to the other
    patches = sorted({r["patch"] for r in rows})
    P("Two-fold check (choose the setting on half the patches, apply it to the other half; false alarms on the choosing half held at the default's rate there):\n")
    P("| fold | chosen on | setting | held-out false alarms | held-out detection |")
    P("|---|---|---|---|---|")
    for fold in (0, 1):
        tr = {p for i, p in enumerate(patches) if i % 2 == fold}
        te = set(patches) - tr
        sub = lambda rr, S: [r for r in rr if r["patch"] in S]   # noqa: E731
        b_tr = rates(sub(rows, tr), CT_TOOLS)
        cand = []
        for s in sw:
            rt = rates(sub(s["rows"], tr), CT_TOOLS)
            if rt["fa"] <= b_tr["fa"]:
                cand.append((rt["det"], -abs(s["value"]), s))
        _, _, ch = max(cand, key=lambda c: (c[0], c[1]))
        re = rates(sub(ch["rows"], te), CT_TOOLS)
        P(f"| {fold} | {len(tr)} patches | {ch['knob']} = {ch['value']:g} | {fmt(re['fa'], re['n_o'])} | {fmt(re['det'], re['n_b'])} |")
    P("")
    write_csv(os.path.join(a.out_dir, "groundtruth_threshold_study.csv"), th_rows)

    # surface pass-on-fraction knob (offline, from the stored ON fractions), panel + surface
    P("### Surface threshold (offline, from the stored ON-PREDICTED-SHEET fractions)\n")
    P("| pass_on_fraction | surface alone: false alarms | surface alone: detection | panel + surface: false alarms | panel + surface: detection |")
    P("|---|---|---|---|---|")
    ctf = calls(rows, CT_TOOLS)
    o = k == "original"
    for th in (0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1):
        sf = ok & (on < th)       # NOT JUDGED rows are not FAIL
        pf = ctf | sf
        P(f"| {th:g} | {int(sf[o].sum())}/{int(o.sum())} | {int(sf[~o].sum())}/{int((~o).sum())} | {int(pf[o].sum())}/{int(o.sum())} | {int(pf[~o].sum())}/{int((~o).sum())} |")
    P("")
    # best surface setting with the panel's false alarms held at the CT panel's default rate; two-fold check by patch
    grid = [round(0.05 * i, 2) for i in range(1, 19)]
    def surf_eval(mask_rows, th):
        idx = np.array([i for i, r in enumerate(rows) if r["patch"] in mask_rows])
        pf = ctf[idx] | (ok[idx] & (on[idx] < th))
        oo = o[idx]
        return int(pf[oo].sum()), int(oo.sum()), int(pf[~oo].sum()), int((~oo).sum())
    allp = set(patches)
    cands = [(surf_eval(allp, th), th) for th in grid]
    good = [c for c in cands if c[0][0] <= base["fa"]]
    (fa_, no_, de_, nb_), th_ = max(good, key=lambda c: (c[0][2], c[1]))
    P(f"Best surface setting with panel + surface false alarms held at or below the CT panel's {base['fa']}/{base['n_o']}: "
      f"**pass_on_fraction = {th_:g}**: false alarms {fmt(fa_, no_)}, detection {fmt(de_, nb_)} (CT panel alone: {fmt(base['det'], base['n_b'])}).\n")
    P("Two-fold check for the surface setting (chosen on one half of the patches, applied to the other):\n")
    P("| fold | setting | held-out false alarms | held-out detection |")
    P("|---|---|---|---|")
    for fold in (0, 1):
        tr = {p for i, p in enumerate(patches) if i % 2 == fold}
        te = allp - tr
        b_tr = rates([r for r in rows if r["patch"] in tr], CT_TOOLS)
        cs = [(surf_eval(tr, th), th) for th in grid]
        gd = [c for c in cs if c[0][0] <= b_tr["fa"]]
        _, thc = max(gd, key=lambda c: (c[0][2], c[1]))
        fa2, no2, de2, nb2 = surf_eval(te, thc)
        P(f"| {fold} | pass_on_fraction = {thc:g} | {fmt(fa2, no2)} | {fmt(de2, nb2)} |")
    P("")
    write_csv(os.path.join(a.out_dir, "groundtruth_surface_threshold.csv"),
              [dict(pass_on_fraction=th, fa=c[0], n_o=c[1], det=c[2], n_b=c[3]) for c, th in cands])
    with open(os.path.join(a.out_dir, "REALDATA_2X2_tables.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


def write_csv(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    sys.exit(main())
