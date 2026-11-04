#!/usr/bin/env python3
"""agreement_table: how often do the texture judge and the peak-based auditor agree? (MIT)

Runs both judges on every phantom preset (the true trace, a planted sheet switch, a trace shifted into the gap, a trace that starts on the wrong
sheet and stays on it) and, if the sample folders are present, on the real samples. Writes agreement.json and agreement.md:
a 2 x 2 table of verdicts (rows texture judge PASS / FAIL, columns auditor PASS / FAIL), NOT JUDGED counted on the side, and for the phantoms
the truth-labelled score of each judge (true trace = should PASS, planted switch and gap trace = should FAIL; the wrong-sheet trace is listed
separately because no continuity judge can see it).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
sys.path[:0] = [_HERE, os.path.join(_TOOLS, "texture_judge")]
import judge_panel as jp  # noqa: E402
import phantom_cases as pc  # noqa: E402

PRESETS = ["round", "mild", "crushed", "merged", "folded", "delaminated", "torn", "gappy", "crushed-hard"]
KINDS = {"true": "good", "switch": "bad", "gap": "bad", "wrong_sheet": "bad-undetectable"}


def phantom_rows(size, presets, work, log):
    rows = []
    for preset in presets:
        d = os.path.join(work, preset)
        sc, paths, p = pc.build_on_disk(d, preset, size)
        nz = size
        heights = [round(nz * f) for f in (0.4, 0.5, 0.6)]
        for kind, truth in KINDS.items():
            log(f"{preset}/{kind}")
            res = jp.run_judges(paths[kind], None, dict(zarr=paths["volume"]), heights, os.path.join(d, "out_" + kind), jp.Params(),
                                umbilicus=paths["umbilicus"], judges=("auditor", "texture"))
            v = jp.judge_verdicts(res, jp.Params())
            rows.append(dict(source="phantom", preset=preset, trace=kind, truth=truth, texture=v["texture_judge"], auditor=v["auditor"]))
        shutil.rmtree(os.path.join(d, "volume.zarr"), ignore_errors=True)
    return rows


def real_rows(repo, work, log):
    rows = []
    sets = [("pherc_paris4_45um", 45.532, [2073, 2600, 3128]), ("pherc_paris4_7p91um", 7.91, [2644, 5729, 8814])]
    for name, um, heights in sets:
        d = os.path.join(repo, "testdata", name)
        for w in ("w116-117", "w118-119"):
            m = [os.path.join(d, x) for x in os.listdir(d) if x.endswith(w + ".tifxyz")]
            if not m:
                continue
            log(f"{name}/{w}")
            res = jp.run_judges(m[0], None, dict(png_dir=os.path.join(d, "slices"), png_pixel_um=um, voxel_size_um=um), heights,
                                os.path.join(work, f"{name}_{w}"), jp.Params(), judges=("auditor", "texture"))
            v = jp.judge_verdicts(res, jp.Params())
            rows.append(dict(source=name, preset=w, trace="original", truth="unknown", texture=v["texture_judge"], auditor=v["auditor"]))
    return rows


def table(rows):
    t = {tv: {av: 0 for av in ("PASS", "FAIL", "NOT JUDGED")} for tv in ("PASS", "FAIL", "NOT JUDGED")}
    for r in rows:
        t[r["texture"]][r["auditor"]] += 1
    return t


def score(rows, judge):
    out = {}
    for kind in ("good", "bad", "bad-undetectable"):
        rr = [r for r in rows if r["truth"] == kind]
        out[kind] = {v: sum(r[judge] == v for r in rr) for v in ("PASS", "FAIL", "NOT JUDGED")}
    return out


def markdown(rows):
    L = []
    for title, sel in (("Phantoms, all presets (true and bad traces)", [r for r in rows if r["source"] == "phantom"]),
                       ("Real samples", [r for r in rows if r["source"] != "phantom"])):
        if not sel:
            continue
        t = table(sel)
        L += [f"### {title}", "", f"{len(sel)} traces. Rows: texture judge. Columns: trace_auditor.", "",
              "| texture \\ auditor | PASS | FAIL | NOT JUDGED |", "|---|---|---|---|"]
        for tv in ("PASS", "FAIL", "NOT JUDGED"):
            L.append(f"| {tv} | {t[tv]['PASS']} | {t[tv]['FAIL']} | {t[tv]['NOT JUDGED']} |")
        both = [r for r in sel if "NOT JUDGED" not in (r["texture"], r["auditor"])]
        agree = sum(r["texture"] == r["auditor"] for r in both)
        L += ["", f"Both judged: {len(both)}; agree {agree}, disagree {len(both) - agree}.", ""]
        if sel[0]["source"] == "phantom":
            L += ["Truth-labelled (good = true trace; bad = planted switch or trace in the gap; undetectable = starts on the wrong sheet):", "",
                  "| judge | truth | PASS | FAIL | NOT JUDGED |", "|---|---|---|---|---|"]
            for j in ("texture", "auditor"):
                for k, v in score(sel, j).items():
                    L.append(f"| {j} | {k} | {v['PASS']} | {v['FAIL']} | {v['NOT JUDGED']} |")
            L.append("")
        L += ["| source | preset / mesh | trace | truth | texture | auditor |", "|---|---|---|---|---|---|"]
        L += [f"| {r['source']} | {r['preset']} | {r['trace']} | {r['truth']} | {r['texture']} | {r['auditor']} |" for r in sel]
        L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--size", type=int, default=128, help="phantom cube edge (voxels)")
    ap.add_argument("--presets", default=",".join(PRESETS))
    ap.add_argument("--no-real", action="store_true")
    ap.add_argument("--broken-dir", help="folder holding a deliberately broken tifxyz copy (tools/realdata_run/task6_break.py) to add as a real-data row")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="agreement_")
    log = lambda m: print(m, file=sys.stderr)       # noqa: E731
    try:
        rows = phantom_rows(a.size, [x for x in a.presets.split(",") if x], work, log)
        if not a.no_real:
            repo = os.path.dirname(_TOOLS)
            rows += real_rows(repo, work, log)
            if a.broken_dir:
                d = os.path.join(repo, "testdata", "pherc_paris4_45um")
                for b in os.listdir(a.broken_dir):
                    res = jp.run_judges(os.path.join(a.broken_dir, b), None, dict(png_dir=os.path.join(d, "slices"), png_pixel_um=45.532, voxel_size_um=45.532),
                                        [2073, 2600, 3128], os.path.join(work, "broken"), jp.Params(), judges=("auditor", "texture"))
                    v = jp.judge_verdicts(res, jp.Params())
                    rows.append(dict(source="pherc_paris4_45um", preset=b, trace="deliberately broken (col > 120 shifted 9.5 vox)", truth="bad",
                                     texture=v["texture_judge"], auditor=v["auditor"]))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with open(os.path.join(a.out_dir, "agreement.json"), "w") as fh:
        json.dump(dict(rows=rows, phantom_table=table([r for r in rows if r["source"] == "phantom"]),
                       real_table=table([r for r in rows if r["source"] != "phantom"])), fh, indent=1)
    md = markdown(rows)
    with open(os.path.join(a.out_dir, "agreement.md"), "w") as fh:
        fh.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
