"""Synthetic demo: a drifting spiral that is progressively crushed to an ellipse in the upper slices.

    python demo_synthetic.py OUT_DIR

Writes OUT_DIR/demo.zarr (one 3-D array) and runs the finder on it with overlays.
No real scan data is used or needed.
"""
import sys
from pathlib import Path

import numpy as np
import zarr

import umbilicus_finder as uf


def spiral(shape, c, pitch, rout, squash, seed):
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx].astype(float)
    dx, dy = xx - c[0], (yy - c[1]) * squash
    r, th = np.hypot(dx, dy), np.arctan2(dy, dx)
    u = np.mod((r - pitch * th / (2 * np.pi)) / pitch, 1.0)
    img = np.where((r < rout) & (r > 8), 0.5 + 0.5 * np.cos(2 * np.pi * u), 0.0)
    return (img + 0.05 * np.random.default_rng(seed).standard_normal(shape)).astype(np.float32)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    nz = 24
    arr = zarr.open(str(out / "demo.zarr"), mode="w", shape=(nz, 400, 480), chunks=(1, 400, 480), dtype="f4")
    for z in range(nz):
        squash = 1.0 if z < 12 else 1.0 + (z - 11) / 6.0  # crushing sets in at z=12, reaching ~3:1
        arr[z] = spiral((400, 480), (150 + 3 * z, 220 - 2 * z), 12.0, 150.0, squash, z)
    return uf.main([str(out / "demo.zarr"), "--out-dir", str(out / "result"), "--z-step", "1", "--overlays"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "demo_out"))
