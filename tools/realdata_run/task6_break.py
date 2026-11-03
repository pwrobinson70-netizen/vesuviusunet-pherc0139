"""Task 6: write a deliberately broken copy of w116-117 to a temp dir (NOT committed): every valid point with grid
column > N is moved radially outward in (x, y) by PITCH voxels from the estimated centre (centre interpolated in z)."""
import json, os, shutil, sys
from common import *
import numpy as np, tifffile
def make_broken(outdir, N=120, pitch=9.5, centre_json=None):
    cp = json.load(open(centre_json or os.path.join(REPO, "tools/realdata_run/out/umbilicus_estimated.json")))["control_points"]
    zs = np.array([c["z"] for c in cp]); cy = np.array([c["y"] for c in cp]); cx = np.array([c["x"] for c in cp])
    g = {a: tifffile.imread(f"{A_DIR}/{a}.tif").astype(np.float64) for a in "xyz"}
    valid = ~((g["x"] == -1) | (g["y"] == -1) | (g["z"] == -1))
    cols = np.arange(g["x"].shape[1])[None, :] > N
    m = valid & cols
    zc = g["z"][m]; ccx = np.interp(zc, zs, cx); ccy = np.interp(zc, zs, cy)
    dx, dy = g["x"][m] - ccx, g["y"][m] - ccy; r = np.hypot(dx, dy)
    g["x"][m] += pitch * dx / r; g["y"][m] += pitch * dy / r
    o = os.path.join(outdir, os.path.basename(A_DIR).replace("w116-117", "w116-117-BROKEN")); os.makedirs(o, exist_ok=True)
    for a in "xyz": tifffile.imwrite(f"{o}/{a}.tif", g[a].astype(np.float32))
    shutil.copy(f"{A_DIR}/meta.json", o)
    return o, int(m.sum())
if __name__ == "__main__":
    print(make_broken(sys.argv[1], int(sys.argv[2]), float(sys.argv[3])))
