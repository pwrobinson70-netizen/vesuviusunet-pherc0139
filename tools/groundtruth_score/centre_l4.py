#!/usr/bin/env python3
"""Part B of the ground-truth score: umbilicus_finder against the published centre line, on full level-4 slices.

Heights: --n-spread evenly spaced over the z range the published centre file covers, plus the heights of the
absolute-winding annotations (so Part C can reuse the same slices). Slices are read from --slices-dir if present
(PNG, 8-bit, `{z4:05d}.png`, z4 = level-4 index), else fetched from the public zarr (fetch_l4_slices.py).

    python centre_l4.py DATA_DIR --slices-dir testdata/pherc_paris4_umbilicus_l4 --out results
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
UM_L4 = 38.4          # um per level-4 voxel (9.6 um x 4)


def _tools():
    for c in (os.path.join(os.path.dirname(HERE)), os.path.join(os.path.dirname(HERE), "_tools")):
        if os.path.isdir(os.path.join(c, "umbilicus_finder")):
            sys.path.insert(0, os.path.join(c, "umbilicus_finder"))
            return
    raise SystemExit("cannot find umbilicus_finder")


def published_centre(data):
    """-> z4, y4, x4 arrays (level-4 voxels) of the published 9.6 um centre line."""
    cp = json.load(open(os.path.join(data, "umbilicus_9p6um.json")))["control_points"]
    a = np.array([[c["z"], c["y"], c["x"]] for c in cp], float)
    a = a[np.argsort(a[:, 0])] / 4.0
    return a[:, 0], a[:, 1], a[:, 2]


def annotated_heights(data):
    d = json.load(open(os.path.join(data, "abs_winding.json")))
    return sorted({int(round(p["p"][2] / 4.0)) for c in d["collections"].values() for p in c["points"].values()})


def choose_heights(data, n_spread):
    z4, _, _ = published_centre(data)
    lo, hi = z4.min(), z4.max()
    spread = [int(round(v)) for v in np.linspace(lo, hi, n_spread + 2)[1:-1]]
    return sorted(set(spread) | set(annotated_heights(data)))


def load_or_fetch(z4, slices_dir):
    from PIL import Image
    p = os.path.join(slices_dir, f"{z4:05d}.png")
    if os.path.isfile(p):
        return np.array(Image.open(p))
    from fetch_l4_slices import fetch_plane
    img = fetch_plane(z4)
    os.makedirs(slices_dir, exist_ok=True)
    Image.fromarray(img).save(p, optimize=True, compress_level=9)
    return img


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("data")
    ap.add_argument("--slices-dir", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--n-spread", type=int, default=15)
    a = ap.parse_args(argv)
    _tools()
    import umbilicus_finder as uf
    z4s, y4s, x4s = published_centre(a.data)
    heights = choose_heights(a.data, a.n_spread)
    ann = set(annotated_heights(a.data))
    p = uf.Params()
    rng = np.random.default_rng(p.seed)
    res = []
    for z4 in heights:
        img = load_or_fetch(z4, a.slices_dir)
        res.append(uf.analyse_slice(img, p, 1.0, rng=rng))
    pitches = [r.pitch_vox for r in res if r.ok and np.isfinite(r.pitch_vox)]
    pitch = float(np.median(pitches)) if pitches else float("nan")
    rows = []
    for z4, r in zip(heights, res):
        uf.finalize(r, pitch, p)
        ty, tx = float(np.interp(z4, z4s, y4s)), float(np.interp(z4, z4s, x4s))
        err = float(np.hypot(r.cy - ty, r.cx - tx)) if r.ok else float("nan")
        rows.append(dict(z_l4=z4, z_9p6=z4 * 4, annotated_height=int(z4 in ann), true_y_l4=f"{ty:.2f}", true_x_l4=f"{tx:.2f}",
                         est_y_l4=f"{r.cy:.2f}", est_x_l4=f"{r.cx:.2f}", err_l4_vox=f"{err:.2f}", err_um=f"{err * UM_L4:.0f}",
                         confidence=f"{r.confidence:.3f}", flag=r.flag, reason=";".join(r.reasons), n_inliers=r.n_inliers,
                         coverage_deg=f"{r.coverage_deg:.0f}", ok=int(r.ok)))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "centre_error_l4.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    e = np.array([float(r["err_l4_vox"]) for r in rows])
    e = e[np.isfinite(e)]
    okm = np.array([r["flag"] == "OK" for r in rows])
    ee = np.array([float(r["err_l4_vox"]) for r in rows])
    L = ["# Centre line vs the published umbilicus (level 4, 38.4 um)", "",
         "AI-assisted (Claude Code and Claude), human-directed.", "",
         f"Slices: {len(rows)} ({len(ann)} at annotated-winding heights). Estimates produced: {len(e)}. "
         f"Flag OK: {int(okm.sum())}, LOW: {int((~okm).sum())}.", "",
         f"Error, all estimates: mean {e.mean():.1f} vox ({e.mean() * UM_L4 / 1000:.2f} mm), worst {e.max():.1f} vox "
         f"({e.max() * UM_L4 / 1000:.2f} mm), median {np.median(e):.1f} vox." if len(e) else "No estimate produced.", ""]
    if okm.any():
        eo = ee[okm]
        L += [f"Error, OK-flagged only (n={int(okm.sum())}): mean {eo.mean():.1f} vox ({eo.mean() * UM_L4 / 1000:.2f} mm), "
              f"worst {eo.max():.1f} vox ({eo.max() * UM_L4 / 1000:.2f} mm).", ""]
    L += ["| z level-4 | z 9.6um | est (y,x) | published (y,x) | error vox | error um | conf | flag | reason |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['z_l4']} | {r['z_9p6']} | {r['est_y_l4']}, {r['est_x_l4']} | {r['true_y_l4']}, {r['true_x_l4']} | "
                 f"{r['err_l4_vox']} | {r['err_um']} | {r['confidence']} | {r['flag']} | {r['reason']} |")
    open(os.path.join(a.out, "centre_error_l4.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
