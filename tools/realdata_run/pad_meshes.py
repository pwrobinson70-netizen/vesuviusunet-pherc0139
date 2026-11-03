"""Write same-shape copies of the two meshes (pad with -1 at the bottom/right) so sheet_spacing_check
(which refuses unequal grids, sheet_spacing_check.py:321) can run. Output goes to a temp dir, never into the repo."""
import json, os, shutil, sys
import numpy as np, tifffile
def pad_pair(a, b, outdir):
    shapes = [tifffile.imread(f"{d}/x.tif").shape for d in (a, b)]
    H, W = max(s[0] for s in shapes), max(s[1] for s in shapes)
    outs = []
    for d in (a, b):
        o = os.path.join(outdir, os.path.basename(d)); os.makedirs(o, exist_ok=True); outs.append(o)
        for ax in "xyz":
            g = tifffile.imread(f"{d}/{ax}.tif"); P = np.full((H, W), -1.0, np.float32); P[:g.shape[0], :g.shape[1]] = g
            tifffile.imwrite(f"{o}/{ax}.tif", P)
        shutil.copy(f"{d}/meta.json", o)
    return outs, (H, W)
if __name__ == "__main__":
    from common import A_DIR, B_DIR
    print(pad_pair(A_DIR, B_DIR, sys.argv[1]))
