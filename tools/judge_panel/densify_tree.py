"""densify_tree: densified copies of a ground-truth sample and of its broken copies.  (MIT)

    python densify_tree.py GROUNDTRUTH_DIR NEGATIVES_DIR OUT_ROOT [--spacing 1] [--jobs 4]

Writes OUT_ROOT/gt/ (README.md, umbilicus files and patches/<p>/{mesh.tifxyz densified, slices, surfpred as symlinks to the originals}) and
OUT_ROOT/neg/<p>/<kind>/ (each broken copy densified). The inputs are never touched. Scorers (tools/groundtruth_score/score.py,
tools/judge_panel/panel_v2.py) run on OUT_ROOT/gt and OUT_ROOT/neg unchanged.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "groundtruth_score"))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))


def _one(job):
    from vun_tools.densify import densify_dir
    src, dst, spacing = job
    densify_dir(src, dst, spacing)
    return dst


def run(gt, neg, out, spacing=1.0, jobs=4):
    from make_negatives import list_patches
    todo = []
    os.makedirs(os.path.join(out, "gt", "patches"), exist_ok=True)
    for f in ["README.md", *[os.path.basename(p) for p in glob.glob(os.path.join(gt, "umbilicus_*.json"))], "abs_winding.json"]:
        if os.path.isfile(os.path.join(gt, f)):
            shutil.copy(os.path.join(gt, f), os.path.join(out, "gt", f))
    for p in list_patches(gt):
        pd, od = os.path.join(gt, "patches", p), os.path.join(out, "gt", "patches", p)
        os.makedirs(od, exist_ok=True)
        for sub in ("slices", "surfpred"):
            link = os.path.join(od, sub)
            if not os.path.lexists(link):
                os.symlink(os.path.abspath(os.path.join(pd, sub)), link)
        todo.append((os.path.join(pd, "mesh.tifxyz"), os.path.join(od, "mesh.tifxyz"), spacing))
        pn = os.path.join(neg, p)
        if os.path.isdir(pn):
            for k in sorted(os.listdir(pn)):
                if os.path.isfile(os.path.join(pn, k, "meta.json")):
                    todo.append((os.path.join(pn, k), os.path.join(out, "neg", p, k), spacing))
    if jobs <= 1:
        list(map(_one, todo))
    else:
        with cf.ProcessPoolExecutor(jobs) as ex:
            list(ex.map(_one, todo, chunksize=2))
    return len(todo)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("groundtruth_dir")
    ap.add_argument("negatives_dir")
    ap.add_argument("out_root")
    ap.add_argument("--spacing", type=float, default=1.0)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    n = run(a.groundtruth_dir, a.negatives_dir, a.out_root, a.spacing, a.jobs)
    print(f"densified {n} meshes into {a.out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
