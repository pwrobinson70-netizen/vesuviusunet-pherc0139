#!/usr/bin/env python3
"""Part C of the ground-truth score: winding_sweep's winding index against the annotated absolute winding numbers.

abs_winding.json is a VC3D point-collection file (see docs/REALDATA_GROUNDTRUTH.md): collections -> points -> {p: [x, y, z],
wind_a: absolute winding number}, coordinates on the 9.6 um grid. For every annotated point this casts winding_sweep's ray
(`ray_crossings`, the step that numbers the sheet crossings outward from the centre) from the published centre through the
point on the level-4 slice at the point's height, takes the crossing nearest to the point's radius as "the sweep's sheet
for this point" and compares.

The sweep numbers from --first-winding (0) at the innermost crossing it sees, so its numbers equal the absolute ones
only up to a constant per ray. Reported: (a) raw agreement (sweep index == absolute number), (b) the implied constant
per point (absolute - sweep), and (c) agreement after removing the most common constant per height: the question "does the
sweep count the same number of sheets between two annotated points as the annotators did".

    python winding_l4.py DATA_DIR --slices-dir CACHE --out results
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
H = 2                                  # slab half-height (winding_sweep ray_z_halfwidth default)


def _tools():
    for c in (os.path.dirname(HERE), os.path.join(os.path.dirname(HERE), "_tools")):
        if os.path.isdir(os.path.join(c, "winding_sweep")):
            for d in ("winding_sweep", "sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor", "sheet_tracer"):
                sys.path.insert(0, os.path.join(c, d))
            return
    raise SystemExit("cannot find winding_sweep")


def read_points(data):
    d = json.load(open(os.path.join(data, "abs_winding.json")))
    out = []
    for cid, c in d["collections"].items():
        for pid, p in c["points"].items():
            out.append(dict(collection=c["name"], pid=pid, x=p["p"][0], y=p["p"][1], z=p["p"][2], wind=float(p["wind_a"])))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("data")
    ap.add_argument("--slices-dir", required=True, help="level-4 PNG cache (fetched from the public zarr if missing)")
    ap.add_argument("--out", default="results")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="override a winding_sweep Params field, e.g. pitch_vox=6 (diagnostic runs)")
    ap.add_argument("--stem", default="winding_agreement_l4")
    ap.add_argument("--match-pitch", type=float, default=0.5, help="a point matches a crossing within this x local pitch")
    a = ap.parse_args(argv)
    _tools()
    import winding_sweep as ws
    from centre_l4 import load_or_fetch, published_centre
    z4s, y4s, x4s = published_centre(a.data)
    pts = read_points(a.data)
    byz = collections.defaultdict(list)
    for p in pts:
        byz[int(round(p["z"] / 4.0))].append(p)
    prm = ws.Params()
    for kv in a.set:
        k, _, v = kv.partition("=")
        if not hasattr(prm, k):
            raise SystemExit(f"unknown winding_sweep parameter {k!r}")
        setattr(prm, k, type(getattr(prm, k) if getattr(prm, k) is not None else 1.0)(float(v)) if not isinstance(getattr(prm, k), int) else int(float(v)))
    rows, per_h = [], []
    for z4 in sorted(byz):
        slab = np.stack([load_or_fetch(z4 + k, a.slices_dir) for k in range(-H, H + 1)]).astype(np.float32)
        cy, cx = float(np.interp(z4, z4s, y4s)), float(np.interp(z4, z4s, x4s))
        for p in byz[z4]:
            px, py = p["x"] / 4.0, p["y"] / 4.0
            ang = math.degrees(math.atan2(py - cy, px - cx))
            r_a = math.hypot(px - cx, py - cy)
            row = dict(z_l4=z4, collection=p["collection"], pid=p["pid"], wind_abs=int(p["wind"]), angle_deg=f"{ang:.1f}",
                       radius_l4=f"{r_a:.1f}", sweep_index="", n_crossings="", cross_r_l4="", dist_pitch="", pitch_l4="",
                       matched=0, implied_offset="", note="")
            try:
                cr, _, pitch = ws.ray_crossings(slab, H, (cy, cx), ang, prm, 0)
            except Exception as e:     # noqa: BLE001 - recorded, not hidden
                row["note"] = f"{type(e).__name__}: {e}"[:120]
                rows.append(row)
                continue
            rr = np.array([c.r for c in cr])
            k = int(np.argmin(np.abs(rr - r_a)))
            loc = cr[k].pitch if cr[k].pitch > 0 else pitch
            dp = abs(rr[k] - r_a) / loc
            row.update(n_crossings=len(cr), cross_r_l4=f"{rr[k]:.1f}", dist_pitch=f"{dp:.2f}", pitch_l4=f"{loc:.1f}")
            if dp <= a.match_pitch:
                row.update(matched=1, sweep_index=cr[k].winding, implied_offset=int(p["wind"]) - cr[k].winding)
            else:
                row["note"] = "no crossing within match tolerance"
            rows.append(row)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, a.stem + ".csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    m = [r for r in rows if r["matched"]]
    L = ["# Winding numbers: our sweep vs the annotated absolute numbers (level 4)", "",
         "AI-assisted (Claude Code and Claude), human-directed.", "",
         f"Overrides: {a.set or 'none (winding_sweep defaults)'}.", "",
         f"Annotated points: {len(rows)} at {len(byz)} heights; matched to a ray crossing within {a.match_pitch:g} pitch: {len(m)}.", ""]
    raw = sum(1 for r in m if r["implied_offset"] == 0)
    L.append(f"(a) raw agreement (sweep index == absolute number): {raw}/{len(m)}.")
    tot_ok = tot_n = 0
    errs = []
    L += ["", "| z level-4 | points | matched | most common offset (abs - sweep) | points at that offset | median abs error after removing it (windings) | max abs error |", "|---|---|---|---|---|---|---|"]
    for z4 in sorted(byz):
        mm = [r for r in m if r["z_l4"] == z4]
        if not mm:
            L.append(f"| {z4} | {len(byz[z4])} | 0 | | | | |")
            continue
        off = collections.Counter(r["implied_offset"] for r in mm).most_common(1)[0][0]
        e = [abs(r["implied_offset"] - off) for r in mm]
        tot_ok += sum(1 for v in e if v == 0)
        tot_n += len(e)
        errs += e
        L.append(f"| {z4} | {len(byz[z4])} | {len(mm)} | {off:+d} | {sum(1 for v in e if v == 0)} | {np.median(e):.1f} | {max(e)} |")
    if tot_n:
        L += ["", f"(c) agreement after removing the per-height constant: {tot_ok}/{tot_n} = {100 * tot_ok / tot_n:.1f}%; "
              f"typical error (median |error|) {np.median(errs):.1f} windings, mean {np.mean(errs):.2f}, worst {max(errs)}.",
              "Single-point heights agree trivially with their own constant, so the figure is driven by the 48- and 8-point rays; see the CSV."]
    for z4 in sorted(byz):
        mm = [r for r in m if r["z_l4"] == z4]
        if len(mm) >= 5:
            wv = np.array([int(r["wind_abs"]) for r in mm], float)
            sv = np.array([int(r["sweep_index"]) for r in mm], float)
            rv = np.array([float(r["radius_l4"]) for r in mm])
            pv = np.array([float(r["pitch_l4"]) for r in mm])
            L += ["", f"z={z4}: sweep crossings per annotated winding (fit slope) {np.polyfit(wv, sv, 1)[0]:.2f}; "
                  f"annotated radial spacing {np.polyfit(wv, rv, 1)[0]:.1f} level-4 px per winding; "
                  f"sweep's measured local pitch (median) {np.median(pv):.1f} px."]
    d = [int(r["implied_offset"]) for r in m]
    if d:
        L += ["", f"(b) implied constant per point (absolute - sweep): min {min(d)}, max {max(d)}, distribution "
              f"{dict(sorted(collections.Counter(d).items()))}."]
    unm = [r for r in rows if not r["matched"]]
    if unm:
        L += ["", f"Unmatched points: {len(unm)} (" + "; ".join(sorted({r['note'] for r in unm})) + ")."]
    open(os.path.join(a.out, a.stem + ".md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
