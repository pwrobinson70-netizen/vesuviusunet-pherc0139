#!/usr/bin/env python3
"""Score winding_sweep on phantom_scroll phantoms (round, mild, bad, merged; the benchmark presets).

    python tools/winding_sweep/score_on_phantoms.py --size 192 --json score.json

Per phantom: build it, sweep the middle half of its z range at --angle (and --n-angles - 1 more), then compare with the
truth. A patch is labelled with the true turn nearest to its points (majority over a sample, tools' own turn_NN surfaces);
it is CORRECT if that turn equals its winding number. Reported: crossings found / true turns, true turns recovered by a
CORRECT patch, patches PASS / FAIL / NOT JUDGED / NO PATCH, windings found at every angle, total area, wall time.
Default angle 30: at angle 0 the ray lies on the phantom's spiral cut and sees one extra crossing (the end of the last turn).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.environ.get("PHANTOM_SCROLL_DIR", os.path.normpath(os.path.join(HERE, "..", "phantom_scroll")))
for d in (HERE, PH):
    if d not in sys.path:
        sys.path.insert(0, d)

import benchmark as bm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import winding_sweep as ws  # noqa: E402
from ssc_io import load_mesh  # noqa: E402


def true_turn(patch_dir, trees, n_sample=300):
    m = load_mesh(patch_dir)
    pts = np.stack([m.x[m.valid], m.y[m.valid], m.z[m.valid]], -1)
    if len(pts) == 0:
        return None
    pts = pts[np.linspace(0, len(pts) - 1, min(n_sample, len(pts))).astype(int)]
    d = np.stack([t.query(pts)[0] for t in trees], 1)
    return int(np.bincount(d.argmin(1), minlength=len(trees)).argmax())


def score_one(name, size, seed, angle, n_angles, workers, work, centre="estimated", log=print):
    p = bm.make_params(name, size, seed)
    out = os.path.join(work, name)
    if not os.path.isdir(os.path.join(out, "surfaces")):
        ps.build(p, out, zarr=False)
    vol = ps.Scroll(p).render()[0]
    trees = []
    for k in range(p.turns):
        m = load_mesh(os.path.join(out, "surfaces", f"turn_{k:02d}"))
        trees.append(cKDTree(np.stack([m.x[m.valid], m.y[m.valid], m.z[m.valid]], -1)))
    nz = vol.shape[0]
    z_lo, z_hi = nz // 4, nz - nz // 4
    src = ws.Source(vol.astype(np.float32), f"phantom {name} size {size} seed {seed}")
    t0 = time.time()
    um = os.path.join(out, "centreline_villa.json") if centre == "truth" else None
    sdir = os.path.join(out, "sweep_" + centre)
    try:
        r = ws.sweep(src, z_lo, z_hi, sdir, ws.Params(angle=angle, n_angles=n_angles, workers=workers), umbilicus=um)
    except ws.InputError as e:
        return dict(phantom=name, centre=centre, size=size, true_turns=p.turns, error=str(e), wall=time.time() - t0)
    wall = time.time() - t0
    s = r["summary"]
    correct, rows = set(), []
    for m in r["manifest"]:
        tt = true_turn(os.path.join(sdir, m["patch"]), trees) if m["patch"] else None
        ok = tt == m["winding"]
        if ok:
            correct.add(m["winding"])
        rows.append(dict(winding=m["winding"], true_turn=tt, correct=ok, verdict=m["verdict"], area=m["area_vx2"],
                         judged=m["judged_fraction"]))
    v = s["verdicts"]
    return dict(phantom=name, centre=centre, size=size, true_turns=p.turns, found=s["n_crossings_per_angle"][0],
                recovered=len(correct), pass_=v["PASS"], fail=v["FAIL"], nj=v["NOT JUDGED"], nopatch=v["NO PATCH"],
                at_every_angle=len(s["windings_found_at_every_angle"]), n_angles=n_angles,
                area=s["total_area_vx2"], wall=wall, patches=rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=192)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--angle", type=float, default=30.0)
    ap.add_argument("--n-angles", type=int, default=4)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--phantoms", nargs="+", default=list(bm.PRESETS), choices=list(bm.PRESETS))
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    res = []
    with tempfile.TemporaryDirectory() as work:
        for n in a.phantoms:
            res.append(score_one(n, a.size, a.seed, a.angle, a.n_angles, a.workers, work))
            if "error" in res[-1]:        # centre not found: also score with the exact centre line (the error row is kept)
                res.append(score_one(n, a.size, a.seed, a.angle, a.n_angles, a.workers, work, centre="truth"))
    print(f"\nwinding_sweep on phantoms, size {a.size}, seed {a.seed}, angle {a.angle:g} (+{a.n_angles - 1} more), middle half of z\n")
    print("| phantom | centre | turns found / true | recovered (correct winding) | PASS | FAIL | NOT JUDGED | NO PATCH | at every angle | total area (vox^2) | wall (s) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        if "error" in r:
            print(f"| {r['phantom']} | {r['centre']} | ERROR: {r['error']} | | | | | | | | {r['wall']:.1f} |")
            continue
        print(f"| {r['phantom']} | {r['centre']} | {r['found']} / {r['true_turns']} | {r['recovered']} / {r['true_turns']} | {r['pass_']} | {r['fail']} | "
              f"{r['nj']} | {r['nopatch']} | {r['at_every_angle']} of {r['found']} | {r['area']:.0f} | {r['wall']:.1f} |")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f, indent=2, default=float)
    return 0


if __name__ == "__main__":
    sys.exit(main())
