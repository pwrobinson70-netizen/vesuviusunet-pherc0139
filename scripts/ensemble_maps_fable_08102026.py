#!/usr/bin/env python
"""ensemble_maps_fable_08102026.py -- [fable], 8 Oct 2026 -- average several saved probability maps into one.

Reads the 8-bit PNG maps that cross_infer.py writes ((prob * 255).astype(uint8), mode L), averages them
pixel by pixel as floats in [0, 1], and writes the mean back as the same kind of 8-bit PNG, so
sweep_saved_map_rev2_fable.py can score it exactly like a single model's map. Nothing else: no weighting,
no test-time augmentation, no resizing. All inputs must have the same width and height.

    python ensemble_maps_fable_08102026.py --out ens.png map1.png map2.png map3.png

Prints one line per input (shape, mean, levels) and one for the output, then exits 0; any problem exits 1
with a message. Standalone: numpy and Pillow only. Does not import or touch the project code.
"""
import argparse
import hashlib
import sys

import numpy as np
from PIL import Image


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="PNG to write (8-bit, mode L)")
    p.add_argument("maps", nargs="+", help="two or more PNG probability maps from cross_infer.py")
    a = p.parse_args()
    if len(a.maps) < 2:
        print("need at least two maps", file=sys.stderr)
        return 1
    acc = None
    shape = None
    for path in a.maps:
        try:
            img = Image.open(path)
        except Exception as e:  # noqa: BLE001
            print(f"cannot open {path}: {e}", file=sys.stderr)
            return 1
        raw = np.array(img.convert("L"))
        if shape is None:
            shape = raw.shape
            acc = np.zeros(shape, dtype=np.float64)
        elif raw.shape != shape:
            print(f"shape mismatch: {path} is {raw.shape}, first map is {shape}", file=sys.stderr)
            return 1
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]
        print(f"in : {path}  mode={img.mode} shape={raw.shape} mean={raw.mean() / 255.0:.4f} levels={len(np.unique(raw))} sha256={sha}")
        acc += raw.astype(np.float64) / 255.0
    mean = acc / len(a.maps)
    out8 = np.clip(np.round(mean * 255.0), 0, 255).astype(np.uint8)
    Image.fromarray(out8, mode="L").save(a.out)
    sha = hashlib.sha256(open(a.out, "rb").read()).hexdigest()[:12]
    print(f"out: {a.out}  n={len(a.maps)} shape={out8.shape} mean={out8.mean() / 255.0:.4f} levels={len(np.unique(out8))} sha256={sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
