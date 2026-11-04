"""break_trace: a deliberately broken copy of a tifxyz trace (as tools/realdata_run/task6_break.py, without a centre line).  (MIT)

    python break_trace.py TRACE OUT_DIR --after-col N --shift-vox S

Every valid grid node with column > N is moved by S voxels along its own surface normal (the in-plane part of it, so the
points stay in their slice), i.e. across the sheet; S = one CT pitch puts the points on the neighbouring sheet. x/y/z.tif and
meta.json are written to OUT_DIR; the original is not touched.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _d in ("sheet_spacing_check", "label_drift"):
    sys.path.insert(0, os.path.join(_TOOLS, _d))
import label_drift as ld  # noqa: E402
from ssc_io import load_mesh  # noqa: E402


def break_trace(src, out, after_col, shift_vox, invalid_value=-1.0):
    import tifffile
    m = load_mesh(src, invalid_value, False)
    n = ld.surface_normals(m)
    hn = np.hypot(n[..., 0], n[..., 1])
    with np.errstate(all="ignore"):
        ux, uy = n[..., 0] / hn, n[..., 1] / hn
    cols = np.arange(m.shape[1])[None, :] > after_col
    mv = m.valid & cols & np.isfinite(ux)
    x, y, z = m.x.copy(), m.y.copy(), m.z.copy()
    x[mv] += shift_vox * ux[mv]
    y[mv] += shift_vox * uy[mv]
    os.makedirs(out, exist_ok=True)
    for a, g in zip("xyz", (x, y, z)):
        g = np.where(m.valid, g, invalid_value)
        tifffile.imwrite(os.path.join(out, f"{a}.tif"), g.astype(np.float32))
    shutil.copy(os.path.join(src, "meta.json"), os.path.join(out, "meta.json"))
    return int(mv.sum())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trace")
    ap.add_argument("out_dir")
    ap.add_argument("--after-col", type=int, required=True, help="nodes with a grid column greater than this are moved")
    ap.add_argument("--shift-vox", type=float, required=True, help="distance along the in-plane normal (voxels)")
    a = ap.parse_args(argv)
    print(json.dumps(dict(moved_nodes=break_trace(a.trace, a.out_dir, a.after_col, a.shift_vox))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
