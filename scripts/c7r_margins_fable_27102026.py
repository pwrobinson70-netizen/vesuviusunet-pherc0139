#!/usr/bin/env python3
"""c7r_margins_fable_27102026.py  [fable] 27 Oct 2026 - read-only footprint geometry for converter folders (Sonnet 346 positive control).
For each folder with label_raw.png: scan footprint s = mean(tifs 04..11) > 0, map footprint l = label_raw > 0.
Prints shares, containment, and the median margin by which the MAP edge lies beyond the SCAN edge on each side
(top/bottom per column, left/right per row; + = map larger on that side, - = map smaller). A translation gives + on one side and - on the
opposite; a pure growth gives + on all sides. Folders whose scan footprint fills the crop (share > 0.995) have no edge: reported, skipped.
  python3 -I c7r_margins_fable_27102026.py FOLDER [FOLDER ...]
"""
import os, sys
import numpy as np


def edges(b, axis):
    n = b.shape[axis]
    any_ = b.any(axis=axis)
    if axis == 0:
        f = b.argmax(0); la = n - 1 - b[::-1].argmax(0)
    else:
        f = b.argmax(1); la = n - 1 - b[:, ::-1].argmax(1)
    return any_, f, la


def main(folders):
    import tifffile
    from PIL import Image
    for d in folders:
        d = d.rstrip("/")
        name = os.path.basename(d)
        lp = os.path.join(d, "label_raw.png")
        tifs = [os.path.join(d, "%02d.tif" % i) for i in range(4, 12)]
        if not os.path.exists(lp) or not all(os.path.exists(t) for t in tifs):
            print("%s: no label_raw.png or tifs 04..11 - skipped" % name); continue
        S = np.mean([tifffile.imread(t).astype(np.float32) for t in tifs], axis=0)
        L = np.array(Image.open(lp))
        s, l = S > 0, L > 0
        line = "%s shape %s  scan>0 %.4f  map>0 %.4f  scan-only %.4f  map-only %.4f" % (name, s.shape, s.mean(), l.mean(), (s & ~l).mean(), (~s & l).mean())
        if s.mean() > 0.995:
            print(line + "  -> scan fills the crop: no edge, uninformative"); continue
        out = []
        for axis, (a, b) in ((0, ("top", "bottom")), (1, ("left", "right"))):
            a1, f1, l1 = edges(s, axis); a2, f2, l2 = edges(l, axis); ok = a1 & a2
            if ok.sum() < 20:
                out.append("%s/%s n/a" % (a, b)); continue
            out.append("%s %+d %s %+d (n %d)" % (a, int(np.median(f1[ok] - f2[ok])), b, int(np.median(l2[ok] - l1[ok])), ok.sum()))
        print(line + "\n    margins map-beyond-scan (median px): " + "; ".join(out), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
