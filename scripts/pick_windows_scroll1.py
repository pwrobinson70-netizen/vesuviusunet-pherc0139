"""[fable] 5 Nov 2026 - brief 30 Part A, step 2: pick the Scroll 1 letter-test windows by a rule fixed in advance.

Reads ONLY a sparse sample of tiles of ONE published ink picture, by HTTP range requests (no full download),
builds a coarse ink-density map (one value per sampled tile, a few mm apart: too coarse to show letter shapes),
then applies the rule below. Private results; nothing here goes into the repo except the windows CSV, later,
by Pedro's decision.

RULE (fixed 5 Nov 2026, before any scoring):
  source  = segment 20260623142658-w028-037 (windings 28-37, named readable on the data page); its published
            ink picture on the 2.4 um grid of volume 20260411134726.
  letter  = the 3 non-overlapping 2 x 2 cm squares with the highest mean published ink, each >= 90% valid.
  blank   = the 2 x 2 cm square with the lowest mean ink, >= 90% valid, >= 2 cm (gap) from every letter window.
  valid   = pixel value > 0 (assumption: the published picture is exactly 0 outside the traced surface; the
            script prints the share of exact zeros so this can be checked).
  record  = segment, file key, size, ETag, every window's pixel corners, and sha256 of every tile read
            -> OUT/scroll1_letter_windows.csv and OUT/tiles_read.csv, BEFORE any scoring (Part C).

Run (PowerShell):  C:\\VesuviusUNET\\venv_repo\\Scripts\\python.exe -u C:\\VesuviusUNET\\pick_windows_fable_05112026.py
"""
import argparse
import csv
import hashlib
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--bucket", default="https://vesuvius-challenge-open-data.s3.amazonaws.com")
ap.add_argument("--segment", default="PHercParis4/segments/20260623142658-w028-037/")
ap.add_argument("--must-contain", default="2.4um,20260411134726", help="comma list: the ink file name must contain all")
ap.add_argument("--um", type=float, default=2.4, help="pixel size of the ink picture, um")
ap.add_argument("--window-cm", type=float, default=2.0)
ap.add_argument("--gap-cm", type=float, default=2.0)
ap.add_argument("--min-valid", type=float, default=0.9)
ap.add_argument("--n-letter", type=int, default=3)
ap.add_argument("--max-mb", type=float, default=150.0, help="download budget for sampled tiles")
ap.add_argument("--out", default=r"C:\VesuviusUNET\private\scroll1_windows_05112026")
a = ap.parse_args()
B = a.bucket.rstrip("/")
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
os.makedirs(a.out, exist_ok=True)
STATS = {"bytes": 0, "requests": 0}


def log(m):
    print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)


def req(url, rng=None, method="GET", tries=4):
    err = None
    for _ in range(tries):
        try:
            r = urllib.request.Request(url, method=method)
            if rng:
                r.add_header("Range", f"bytes={rng[0]}-{rng[1] - 1}")
            with urllib.request.urlopen(r, timeout=120) as f:
                b = f.read()
                STATS["bytes"] += len(b)
                STATS["requests"] += 1
                return b, dict(f.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            err = e
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(2)
    raise ConnectionError(f"{url}: {err}")


class HttpFile:
    """Read-only, seekable file over HTTP range requests, 1 MB block cache (enough for TIFF headers and tiles)."""
    BLOCK = 1 << 20

    def __init__(self, url):
        self.url, self.pos, self.cache = url, 0, {}
        _, h = req(url, method="HEAD")
        h = {k.lower(): v for k, v in h.items()}
        self.size = int(h["content-length"])
        self.etag = h.get("etag", "").strip('"')
        self.name = url.rsplit("/", 1)[-1]

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True

    def _block(self, i):
        if i not in self.cache:
            if len(self.cache) > 64:
                self.cache.clear()
            s = i * self.BLOCK
            self.cache[i], _ = req(self.url, (s, min(self.size, s + self.BLOCK)))
        return self.cache[i]

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        out = bytearray()
        while n > 0:
            i, o = divmod(self.pos, self.BLOCK)
            blk = self._block(i)
            take = blk[o:o + n]
            out += take
            self.pos += len(take)
            n -= len(take)
            if not take:
                break
        return bytes(out)

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)

    def range(self, off, n):
        """Exact bytes off..off+n with one request (tiles; not cached)."""
        b, _ = req(self.url, (off, off + n))
        return b

    def close(self):
        pass


# ---- 1. find the ink file
q = urllib.parse.urlencode({"list-type": "2", "prefix": a.segment + "ink-detection/", "delimiter": "/"})
b, _ = req(f"{B}/?{q}")
root = ET.fromstring(b)
keys = [(c.findtext(f"{NS}Key"), int(c.findtext(f"{NS}Size") or 0)) for c in root.findall(f"{NS}Contents")]
need = [s for s in a.must_contain.split(",") if s]
cand = [(k, s) for k, s in keys if k.lower().endswith((".tif", ".tiff")) and all(t in k for t in need)]
log(f"ink-detection files: {len(keys)}; matching {need}: {len(cand)}")
for k, s in keys:
    log(f"  {s / 1e6:9.1f} MB  {k.rsplit('/', 1)[-1]}")
if len(cand) != 1:
    log("STOP: need exactly one matching ink picture; send this log to fable")
    sys.exit(4)
key, size = cand[0]
url = f"{B}/{urllib.parse.quote(key)}"

# ---- 2. open the TIFF by range requests
import tifffile  # noqa: E402

fh = HttpFile(url)
tf = tifffile.TiffFile(fh)
page = tf.pages[0]
H, W = page.shape[:2]
tiled = page.is_tiled
th, tw = (page.tilelength, page.tilewidth) if tiled else (page.rowsperstrip, W)
log(f"{fh.name}: {W} x {H} px ({W * a.um / 1e4:.1f} x {H * a.um / 1e4:.1f} cm), dtype {page.dtype}, "
    f"{'tiles' if tiled else 'strips'} {tw} x {th}, compression {page.compression!r}, {fh.size / 1e6:.0f} MB, "
    f"{len(tf.pages)} page(s); header read {STATS['bytes'] / 1e6:.1f} MB")
if page.samplesperpixel != 1 and len(page.shape) > 2:
    log("STOP: multi-channel ink picture; send this log to fable")
    sys.exit(5)
nty, ntx = math.ceil(H / th), math.ceil(W / tw)
offs, cnts = page.dataoffsets, page.databytecounts
mean_tile = max(1.0, float(np.mean([c for c in cnts if c])))
k = max(1, math.ceil(math.sqrt(nty * ntx * mean_tile / (a.max_mb * 1e6))))
if not tiled:
    k = max(k, 1)
ky = k
kx = k if tiled else 1
log(f"grid {ntx} x {nty} {'tiles' if tiled else 'strips'}, mean {mean_tile / 1e3:.0f} kB each; sampling every {ky} "
    f"in y{' and x' if tiled else ''} -> about {math.ceil(nty / ky) * math.ceil(ntx / kx) * mean_tile / 1e6:.0f} MB")

# ---- 3. sample tiles -> coarse maps (mean value, valid share) per sampled tile
sy, sx = list(range(0, nty, ky)), list(range(0, ntx, kx))
mean_map = np.full((len(sy), len(sx) if tiled else 1), np.nan)
valid_map = np.full_like(mean_map, np.nan)
zero_px = tot_px = 0
maxval = float(np.iinfo(page.dtype).max) if np.dtype(page.dtype).kind in "ui" else 1.0
strip_cols = 64  # strips: split each sampled strip into this many column blocks
if not tiled:
    mean_map = np.full((len(sy), strip_cols), np.nan)
    valid_map = np.full_like(mean_map, np.nan)
rows = []
t0 = time.time()
for iy, ty in enumerate(sy):
    for ix, tx in enumerate(sx):
        idx = ty * ntx + tx
        if not cnts[idx]:
            if tiled:
                mean_map[iy, ix], valid_map[iy, ix] = 0.0, 0.0
            continue
        raw = fh.range(offs[idx], cnts[idx])
        rows.append((idx, ty, tx, offs[idx], cnts[idx], hashlib.sha256(raw).hexdigest()))
        seg, _, shape = page.decode(raw, idx, jpegtables=page.jpegtables)
        arr = np.asarray(seg).reshape(shape[-3], shape[-2]) if seg is not None else np.zeros((th, tw))
        hh = min(th, H - ty * th)
        ww = min(tw, W - tx * tw)
        arr = arr[:hh, :ww].astype(np.float32) / maxval
        zero_px += int((arr == 0).sum())
        tot_px += arr.size
        if tiled:
            mean_map[iy, ix] = float(arr.mean())
            valid_map[iy, ix] = float((arr > 0).mean())
        else:
            for j, blk in enumerate(np.array_split(arr, strip_cols, axis=1)):
                mean_map[iy, j], valid_map[iy, j] = float(blk.mean()), float((blk > 0).mean())
    if iy % max(1, len(sy) // 10) == 0:
        log(f"row {iy + 1}/{len(sy)}  {STATS['bytes'] / 1e6:.0f} MB  {time.time() - t0:.0f}s")
log(f"sampled {len(rows)} {'tiles' if tiled else 'strips'}, {STATS['bytes'] / 1e6:.0f} MB in {STATS['requests']} "
    f"requests; exact-zero share of sampled pixels {zero_px / max(tot_px, 1):.3f}")

# cell size of the coarse map in pixels
cy = th * ky
cx = (tw * kx) if tiled else W / strip_cols
win = a.window_cm * 1e4 / a.um
gap = a.gap_cm * 1e4 / a.um
wy, wx = max(1, round(win / cy)), max(1, round(win / cx))
log(f"coarse cell {cx * a.um / 1e3:.2f} x {cy * a.um / 1e3:.2f} mm; a {a.window_cm} cm window = {wx} x {wy} cells")

# ---- 4. apply the rule
M, V = np.nan_to_num(mean_map), np.nan_to_num(valid_map)
have = np.isfinite(mean_map).astype(float)


def box(S, y, x):
    return S[y:y + wy, x:x + wx]


cands = []
for y in range(0, M.shape[0] - wy + 1):
    for x in range(0, M.shape[1] - wx + 1):
        h = box(have, y, x)
        if h.mean() < 0.999 or y * cy + win > H or x * cx + win > W:      # whole window inside the picture
            continue
        cands.append((float(box(M, y, x).mean()), float(box(V, y, x).mean()), y, x))
ok = [c for c in cands if c[1] >= a.min_valid]
log(f"{len(cands)} candidate windows, {len(ok)} with valid >= {a.min_valid}")
if len(ok) < a.n_letter + 1:
    log("STOP: not enough valid windows; send this log to fable")
    sys.exit(6)


def px(c):
    _, _, y, x = c
    r0, c0 = int(y * cy), int(x * cx)
    return (r0, c0, r0 + int(round(win)), c0 + int(round(win)))      # exactly window-cm on a side


def apart(p, q, g):
    """Gap between two rectangles (r0, c0, r1, c1) is at least g pixels (0 = just not overlapping)."""
    dy = max(q[0] - p[2], p[0] - q[2])
    dx = max(q[1] - p[3], p[1] - q[3])
    return max(dy, dx) >= g


letters = []
for c in sorted(ok, key=lambda c: -c[0]):
    if all(apart(px(c), px(l), 0) for l in letters):
        letters.append(c)
    if len(letters) == a.n_letter:
        break
blank = None
for c in sorted(ok, key=lambda c: c[0]):
    if all(apart(px(c), px(l), gap) for l in letters):
        blank = c
        break

# ---- 5. record
seg_name = a.segment.rstrip("/").rsplit("/", 1)[-1]
rule = (f"letter: top {a.n_letter} non-overlapping {a.window_cm} cm squares by mean ink, valid>={a.min_valid}; "
        f"blank: lowest mean, valid>={a.min_valid}, gap>={a.gap_cm} cm; valid = value>0; sample step {ky}x{kx}")
with open(os.path.join(a.out, "scroll1_letter_windows.csv"), "w", encoding="utf-8", newline="\n") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["role", "segment", "ink_key", "ink_bytes", "ink_etag", "row0_px", "col0_px", "row1_px", "col1_px",
                "mean_ink_0to1", "valid_share", "rule", "fixed_on"])
    for i, c in enumerate(letters, 1):
        w.writerow([f"letter{i}", seg_name, key, fh.size, fh.etag, *px(c), f"{c[0]:.4f}", f"{c[1]:.3f}", rule, "2026-11-05"])
    if blank:
        w.writerow(["blank", seg_name, key, fh.size, fh.etag, *px(blank), f"{blank[0]:.4f}", f"{blank[1]:.3f}", rule,
                    "2026-11-05"])
with open(os.path.join(a.out, "tiles_read.csv"), "w", encoding="utf-8", newline="\n") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["index", "row", "col", "offset", "bytes", "sha256"])
    w.writerows(rows)
np.save(os.path.join(a.out, "coarse_mean.npy"), mean_map)
np.save(os.path.join(a.out, "coarse_valid.npy"), valid_map)

print()
print(f"[fable] Part A step 2 - window pick - {time.strftime('%d %b %Y %H:%M')}")
print(f"ink picture: {key} ({fh.size / 1e6:.0f} MB, ETag {fh.etag})")
print(f"size {W} x {H} px = {W * a.um / 1e4:.1f} x {H * a.um / 1e4:.1f} cm; downloaded {STATS['bytes'] / 1e6:.0f} MB")
print(f"exact-zero share {zero_px / max(tot_px, 1):.3f}; candidate windows {len(cands)}, valid {len(ok)}")
print(f"all valid windows: mean ink min {min(c[0] for c in ok):.4f}, median {np.median([c[0] for c in ok]):.4f}, "
      f"max {max(c[0] for c in ok):.4f}")
for i, c in enumerate(letters, 1):
    print(f"letter{i}: rows {px(c)[0]}-{px(c)[2]}, cols {px(c)[1]}-{px(c)[3]} px, mean {c[0]:.4f}, valid {c[1]:.3f}")
print(f"blank:   " + (f"rows {px(blank)[0]}-{px(blank)[2]}, cols {px(blank)[1]}-{px(blank)[3]} px, mean {blank[0]:.4f}, "
                      f"valid {blank[1]:.3f}" if blank else "NONE found with the gap rule"))
print(f"written: {os.path.join(a.out, 'scroll1_letter_windows.csv')} and tiles_read.csv (sha256 of {len(rows)} pieces)")
print("Numbers and corners only: no image of the ink was saved.")
