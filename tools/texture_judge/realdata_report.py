#!/usr/bin/env python3
"""realdata_report: run texture_judge on the two public real samples (both meshes) and on the deliberately broken copy from
tools/realdata_run, and write the numbers and the pictures to --out (default docs/texture_judge). (MIT)

The real samples hold only three slice PNGs each, so the judge runs in SECTION mode (a straightened cross-section of the slice along the
cut line). The broken copy is rebuilt in a temp dir exactly as tools/realdata_run/task6_break.py does (45 um mesh w116-117, every valid
point with grid column > 120 moved radially outward by 9.5 voxels); it is never written into the repo.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections import Counter

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "realdata_run"))
import texture_judge as tj  # noqa: E402
from ssc_io import PngVolume, load_mesh  # noqa: E402

SETS = [("45um", "pherc_paris4_45um", 45.532, [2073, 2600, 3128]), ("7p91um", "pherc_paris4_7p91um", 7.91, [2644, 5729, 8814])]
MESHES = ["w116-117", "w118-119"]


def mesh_dir(sample, tag):
    d = os.path.join(REPO, "testdata", sample)
    return os.path.join(d, next(x for x in os.listdir(d) if x.endswith(tag + ".tifxyz")))


def chunked_picture(sec, st, v, path, chunk=800, zoom=2, max_bytes=1_000_000):
    """The long straightened strip cut into chunks stacked top to bottom, window verdicts tinted, saved <= 1 MB."""
    from PIL import Image
    base = sec["layers"][0.0]
    ov = tj.overlay_image(base, v, st, [])
    H, W = base.shape[0], base.shape[1]
    raw = np.stack([tj._to_u8(base)] * 3, -1)
    rows = []
    for c0 in range(0, W, chunk):
        a = raw[:, c0:c0 + chunk]; b = ov[:, c0:c0 + chunk]
        pad = chunk - a.shape[1]
        if pad:
            a = np.pad(a, ((0, 0), (0, pad), (0, 0))); b = np.pad(b, ((0, 0), (0, pad), (0, 0)))
        rows += [a, b, np.full((4, chunk, 3), 255, np.uint8)]
    im = Image.fromarray(np.concatenate(rows, 0)).resize((chunk * zoom, sum(r.shape[0] for r in rows) * zoom), Image.NEAREST)
    im.save(path, optimize=True)
    while os.path.getsize(path) > max_bytes and im.size[0] > 400:
        im = im.resize((im.size[0] * 3 // 4, im.size[1] * 3 // 4), Image.BILINEAR)
        im.save(path, optimize=True)


def run_one(mesh_path, sample, um, heights, out_prefix, pics_dir, p):
    mesh = load_mesh(mesh_path)
    vol = PngVolume(os.path.join(REPO, "testdata", sample, "slices"), um, um)
    rep = tj.run(mesh, vol, p, heights, "section")
    I = rep.pop("_internal")
    if pics_dir:
        for o in I["outs"]:
            if o is not None:
                chunked_picture(o["sec"], o["st"], o["v"], os.path.join(pics_dir, f"{out_prefix}_z{int(o['sec']['z'])}.png"))
    rep["mesh_shape"] = list(mesh.shape)
    return rep


def near_break(rep, c0=108, c1=132):
    """Per height: verdict counts of the cut-line points with grid column in [c0, c1], and the BREAK centres in that range."""
    out = {}
    for c in rep["cut_lines"]:
        vs = [v for col, v in zip(c["col"], c["verdict"]) if c0 <= col <= c1]
        out[int(c["z"])] = dict(points=len(vs), verdicts=dict(Counter(vs)), break_centres=[round(b["grid_col"], 1) for b in c["breaks"] if c0 <= b["grid_col"] <= c1])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "texture_judge"))
    ap.add_argument("--no-pictures", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    p = tj.Params()
    results = {}
    pics = None if a.no_pictures else a.out
    for tag, sample, um, heights in SETS:
        for m in MESHES:
            name = f"{tag}_{m}"
            print("running", name, file=sys.stderr)
            results[name] = run_one(mesh_dir(sample, m), sample, um, heights, name, pics if m == "w116-117" else None, p)
    import task6_break
    tmp = tempfile.mkdtemp(prefix="texture_broken_")
    try:
        o, n = task6_break.make_broken(tmp, 120, 9.5)
        print("running broken copy", n, "points moved", file=sys.stderr)
        results["45um_w116-117_BROKEN"] = run_one(o, "pherc_paris4_45um", 45.532, SETS[0][3], "45um_w116-117_BROKEN", pics, p)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    summary = {}
    for k, r in results.items():
        w = r["windows"]
        summary[k] = dict(windows=w["n_windows"], counts=w["counts"], judged_fraction=round(w["judged_fraction"], 3), verdict=r["verdict"],
                          n_breaks=len(r["breaks"]), cut_lines={int(c["z"]): c["counts"] for c in r["cut_lines"]})
    cmp_ = {k: near_break(results[k]) for k in ("45um_w116-117", "45um_w116-117_BROKEN")}
    with open(os.path.join(a.out, "results.json"), "w") as fh:
        json.dump(dict(params=tj.Params().__dict__, summary=summary, columns_108_132_original_vs_broken=cmp_,
                       breaks={k: r["breaks"] for k, r in results.items()}), fh, indent=1, default=float)
    print(json.dumps(summary, indent=1))
    print(json.dumps(cmp_, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
