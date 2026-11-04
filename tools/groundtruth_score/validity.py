"""validity: do the broken copies sit where they were meant to? Fraction of points within 2 voxels of a CT sheet peak (label_drift's measure,
via surface_agreement's `ours_on_fraction`) for the original and each broken copy.  Writes results/groundtruth_negatives_validity.csv.  (MIT)

    python validity.py GROUNDTRUTH_DIR NEGATIVES_DIR --out results/groundtruth_negatives_validity.csv
A one-pitch shift that lands on the neighbouring sheet should keep this fraction close to the original's; half a pitch should lower it.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_T = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _d in ("sheet_spacing_check", "label_drift", "surface_agreement", "common"):
    sys.path.insert(0, os.path.join(_T, _d))
import surface_agreement as sa  # noqa: E402
from make_negatives import check_readme, list_patches  # noqa: E402

KINDS = ("original", "shift-half", "shift-full", "switch-mid", "scramble")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("groundtruth_dir")
    ap.add_argument("negatives_dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    check_readme(a.groundtruth_dir)
    rows = []
    for p in list_patches(a.groundtruth_dir):
        pd = os.path.join(a.groundtruth_dir, "patches", p)
        hs = json.load(open(os.path.join(pd, "mesh.tifxyz", "meta.json")))["window"]["heights"]
        for k in KINDS:
            mesh = os.path.join(pd, "mesh.tifxyz") if k == "original" else os.path.join(a.negatives_dir, p, k)
            with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                sa.main([mesh, "--pred-png-dir", os.path.join(pd, "surfpred"), "--ct-png-dir", os.path.join(pd, "slices"), "--png-pixel-um", "9.6",
                         "--voxel-size-um", "9.6", "--heights", ",".join(map(str, hs)), "--out-dir", td, "--png-scale", "1"])
                t = json.load(open(os.path.join(td, "report.json")))["traces"][0]
            n = sum(h["n_points"] for h in t["heights"])
            on = sum(h["n_points"] * (h.get("ours_on_fraction") or 0.0) for h in t["heights"])
            rows.append(dict(patch=p, kind=k, n_points=n, ct_peak_on_fraction=round(on / n, 4) if n else None))
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    import statistics
    for k in KINDS:
        v = [r["ct_peak_on_fraction"] for r in rows if r["kind"] == k and r["ct_peak_on_fraction"] is not None]
        print(f"{k:11s} median CT-peak-ON fraction {statistics.median(v):.3f}  (n={len(v)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
