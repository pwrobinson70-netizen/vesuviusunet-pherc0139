"""[fable] 5 Nov 2026 - brief 30 Part C, laptop stage C1: the Scroll 1 letter test on the fixed windows.

For each window in scroll1_letter_windows.csv (3 letter + 1 blank, fixed and committed before this runs):
 1. crop the segment's 2.4 um trace (tifxyz) to the window by HTTP range reads (no full download);
 2. make broken copies with the repo's make_negatives (shift-full, shift-half, scramble; fixed seed 20261104;
    pitch = median CT pitch of the 40 verified patches, results/groundtruth_patches.csv, times 4 for 2.4 um);
 3. our ink image = vun-ink-sample on the published 3-D ink zarr along each trace (level 1 = 9.6 um, offsets -2..+2
    at level 1 = +-19 um, the tool's default +-4 at the zarr's native 4.8 um level 0; fixed 5 Nov before real data:
    the planted test showed +-4 at level 1 reaches across half a sheet gap, so shift-half could not be told apart);
 4. the published 2-D ink picture over the same window, block-averaged 4 x 4 to the same 9.6 um grid;
 5. agreement: Pearson r, and IoU of the two images each thresholded at its own 90th percentile.
Readout (brief 30, fixed before data): per LETTER window, r(original) >= 0.5 AND >= 2 x best broken copy; BLANK
r < 0.2 or IoU < 0.1. AMENDED 5 Nov 2026 by Pedro, before any real data: "best broken copy" = best of shift-full and
scramble; shift-half is reported as a diagnostic only (on a planted test it kept the real signal, r 0.97, because half a
Scroll 1 sheet gap is barely wider than the sheet plus the sampling depth). The panel_v2 part of the rule needs CT and prediction slices: stage C2, NOT run here.
Private results (numbers, small thumbnails); nothing is published.

Run:  python -u scripts/letter_test_c1_scroll1.py --windows results/scroll1_letter_windows.csv --out OUT [--only letter2,letter3]
"""
import argparse
import csv
import json
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
ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ap.add_argument("--windows", default=r"C:\VesuviusUNET\private\scroll1_windows_05112026\scroll1_letter_windows.csv")
ap.add_argument("--out", default=r"C:\VesuviusUNET\private\scroll1_letter_test_c1_05112026")
ap.add_argument("--bucket", default="https://vesuvius-challenge-open-data.s3.amazonaws.com")
ap.add_argument("--ink3d", default="PHercParis4/representations/predictions/ink-3d/"
                "20260411134726-ink3d-20260926084000-student-v12A-25000-c7766be9-L1.zarr")
ap.add_argument("--only", default="", help="comma list of roles to run, e.g. letter1,blank (default: all)")
ap.add_argument("--kinds", default="shift-full,shift-half,scramble")
ap.add_argument("--max-gb", type=float, default=16.0)
ap.add_argument("--margin-cells", type=int, default=2)
a = ap.parse_args()
B = a.bucket.rstrip("/")
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
UM = 2.4            # ink picture and trace grid voxel
STATS = {"bytes": 0, "requests": 0}
for p in ("tools/ink_sample", "tools/ink_infer", "tools/groundtruth_score"):
    sys.path.insert(0, os.path.join(a.repo, *p.split("/")))
import http_zarr  # noqa: E402
import ink_sample  # noqa: E402
import tifffile  # noqa: E402

os.makedirs(a.out, exist_ok=True)
logf = open(os.path.join(a.out, "c1_log_fable_05112026.txt"), "a", encoding="utf-8", newline="\n")


def log(m):
    line = f"{time.strftime('%H:%M:%S')} {m}"
    print(line, flush=True)
    logf.write(line + "\n")
    logf.flush()


def total_bytes():
    return STATS["bytes"] + http_zarr.STATS["bytes"]


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
                return b, {k.lower(): v for k, v in f.headers.items()}
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            err = e
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(2)
    raise ConnectionError(f"{url}: {err}")


class HttpFile:
    BLOCK = 1 << 20

    def __init__(self, url):
        self.url, self.pos, self.cache = url, 0, {}
        _, h = req(url, method="HEAD")
        self.size, self.etag, self.name = int(h["content-length"]), h.get("etag", "").strip('"'), url.rsplit("/", 1)[-1]

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
            take = self._block(i)[o:o + n]
            if not take:
                break
            out += take
            self.pos += len(take)
            n -= len(take)
        return bytes(out)

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)

    def close(self):
        pass


def open_tiff(url):
    fh = HttpFile(url)
    return fh, tifffile.TiffFile(fh).pages[0]


def read_region(fh, page, r0, r1, c0, c1):
    """Pixels [r0:r1, c0:c1] of a 2-D tiled or striped TIFF page, fetching only the tiles/strips that overlap."""
    H, W = page.shape[:2]
    r0, r1, c0, c1 = max(0, r0), min(H, r1), max(0, c0), min(W, c1)
    out = np.zeros((max(0, r1 - r0), max(0, c1 - c0)), page.dtype)
    if out.size == 0:
        return out
    if page.is_tiled:
        th, tw = page.tilelength, page.tilewidth
    else:
        th, tw = page.rowsperstrip, W
    ntx = math.ceil(W / tw)
    for ty in range(r0 // th, (r1 - 1) // th + 1):
        for tx in range(c0 // tw, (c1 - 1) // tw + 1):
            idx = ty * ntx + tx
            off, cnt = page.dataoffsets[idx], page.databytecounts[idx]
            if not cnt:
                continue
            raw, _ = req(fh.url, (off, off + cnt))
            seg, _, shape = page.decode(raw, idx, jpegtables=page.jpegtables)
            arr = np.asarray(seg).reshape(shape[-3], shape[-2])
            gy0, gx0 = ty * th, tx * tw
            ys0, ys1 = max(r0, gy0), min(r1, gy0 + arr.shape[0])
            xs0, xs1 = max(c0, gx0), min(c1, gx0 + arr.shape[1])
            if ys1 > ys0 and xs1 > xs0:
                out[ys0 - r0:ys1 - r0, xs0 - c0:xs1 - c0] = arr[ys0 - gy0:ys1 - gy0, xs0 - gx0:xs1 - gx0]
    return out


def listing(prefix):
    q = urllib.parse.urlencode({"list-type": "2", "prefix": prefix, "delimiter": "/"})
    b, _ = req(f"{B}/?{q}")
    root = ET.fromstring(b)
    return ([p.findtext(f"{NS}Prefix") for p in root.findall(f"{NS}CommonPrefixes")],
            [(c.findtext(f"{NS}Key"), int(c.findtext(f"{NS}Size") or 0)) for c in root.findall(f"{NS}Contents")])


def pearson(x, y):
    x, y = x - x.mean(), y - y.mean()
    d = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
    return float((x * y).sum() / d) if d > 0 else float("nan")


def top10(v):
    """Exactly the top 10% of pixels by value (rank-based, stable), so ties cannot select everything."""
    b = np.zeros(v.size, bool)
    b[np.argsort(-v, kind="stable")[:max(1, v.size // 10)]] = True
    return b


def iou90(x, y):
    if x.std() == 0 or y.std() == 0:
        return float("nan")
    bx, by = top10(x), top10(y)
    return float((bx & by).sum() / (bx | by).sum())


# ---- windows
with open(a.windows, encoding="utf-8") as f:
    wins = list(csv.DictReader(f))
only = [s for s in a.only.split(",") if s]
if only:
    wins = [w for w in wins if w["role"] in only]
seg = wins[0]["segment"]
seg_prefix = f"PHercParis4/segments/{seg}/"
ink_key = wins[0]["ink_key"]
log(f"{len(wins)} windows on {seg}: {', '.join(w['role'] for w in wins)}")

# ---- the 2.4 um trace of this segment
dirs, _ = listing(seg_prefix + "mesh/")
tx_dirs = [d for d in dirs if "20260411134726-2.4um.tifxyz" in d]
if len(tx_dirs) != 1:
    log(f"STOP: expected one 2.4um tifxyz under mesh/, found {dirs}")
    sys.exit(4)
txp = tx_dirs[0]
_, tkeys = listing(txp)
names = {k.rsplit("/", 1)[-1]: s for k, s in tkeys}
log(f"trace folder {txp}: {', '.join(f'{n} ({s / 1e6:.0f} MB)' for n, s in sorted(names.items()))}")
meta = json.loads(req(f"{B}/{urllib.parse.quote(txp + 'meta.json')}")[0])
sc = meta.get("scale")
log(f"trace meta: scale {sc}, keys {sorted(meta.keys())[:20]}")
grid = {}
for ax in ("x", "y", "z", "mask"):
    if f"{ax}.tif" in names:
        grid[ax] = open_tiff(f"{B}/{urllib.parse.quote(txp + ax + '.tif')}")
gH, gW = grid["x"][1].shape[:2]
ink_fh, ink_page = open_tiff(f"{B}/{urllib.parse.quote(ink_key)}")
iH, iW = ink_page.shape[:2]
log(f"grid {gW} x {gH} cells; ink picture {iW} x {iH} px; ink/grid = {iW / gW:.4f} x {iH / gH:.4f}; 1/scale = "
    f"{1 / sc[0]:.4f} x {1 / sc[1]:.4f}")
fx, fy = iW / gW, iH / gH
if not (abs(fx * sc[0] - 1) < 0.02 and abs(fy * sc[1] - 1) < 0.02):
    log("STOP: the ink picture is not 1/scale pixels per grid cell; send this log to fable")
    sys.exit(5)

# ---- pitch for broken copies (median CT pitch of the verified patches, 9.6 um voxels) -> 2.4 um voxels
pv = []
with open(os.path.join(a.repo, "results", "groundtruth_patches.csv"), encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row.get("mode") == "default":
            pv += [float(row[k]) for k in ("pitch_h1", "pitch_h2", "pitch_h3") if row.get(k) not in (None, "", "nan")]
pitch24 = float(np.median(pv)) * 4.0
log(f"broken-copy pitch: median {np.median(pv):.2f} voxels at 9.6 um = {pitch24:.1f} voxels at 2.4 um ({len(pv)} values)")
import make_negatives as mn  # noqa: E402

kinds = [k for k in a.kinds.split(",") if k]
INK = f"{B}/{a.ink3d}"
results = []
for wi, w in enumerate(wins):
    role = w["role"]
    r0, c0, r1, c1 = (int(w[k]) for k in ("row0_px", "col0_px", "row1_px", "col1_px"))
    wd = os.path.join(a.out, role)
    os.makedirs(wd, exist_ok=True)
    # grid cells covering the window (+ margin)
    gr0, gr1 = int(math.floor(r0 * sc[1])) - a.margin_cells, int(math.ceil(r1 * sc[1])) + a.margin_cells
    gc0, gc1 = int(math.floor(c0 * sc[0])) - a.margin_cells, int(math.ceil(c1 * sc[0])) + a.margin_cells
    gr0, gc0 = max(0, gr0), max(0, gc0)
    td = os.path.join(wd, "trace")
    os.makedirs(td, exist_ok=True)
    for ax, (fh, page) in grid.items():
        arr = read_region(fh, page, gr0, gr1, gc0, gc1)
        tifffile.imwrite(os.path.join(td, f"{ax}.tif"), arr, compression="zlib")
    m2 = dict(meta)
    m2["crop_note"] = f"[fable] crop of {txp} rows {gr0}:{gr1} cols {gc0}:{gc1} (grid cells) for window {role}"
    m2["window_px"] = [r0, c0, r1, c1]
    with open(os.path.join(td, "meta.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(m2, f, indent=2)
    log(f"[{role}] trace crop {gc1 - gc0} x {gr1 - gr0} cells written ({total_bytes() / 1e6:.0f} MB so far)")
    sign = 1.0 if np.random.default_rng([mn.DEFAULT_SEED, wi]).random() < 0.5 else -1.0
    bd = os.path.join(wd, "broken")
    done = mn.make_one(td, bd, sign * pitch24, mn.DEFAULT_SEED, kinds=tuple(kinds))
    log(f"[{role}] broken copies {done}, signed pitch {sign * pitch24:+.1f}")
    # published picture over the cropped grid, at the ink-sample output grid (step 2 level-0 = 4 picture px)
    pr0, pc0 = int(round(gr0 / sc[1])), int(round(gc0 / sc[0]))
    pub_full = read_region(ink_fh, ink_page, pr0, int(round(gr1 / sc[1])), pc0, int(round(gc1 / sc[0])))
    rows = {}
    for name, tdir in [("original", td)] + [(k, os.path.join(bd, k)) for k in kinds]:
        if total_bytes() > a.max_gb * 1e9:
            log(f"STOP: download reached {total_bytes() / 1e9:.1f} GB (--max-gb {a.max_gb})")
            break
        od = os.path.join(wd, "ink", name)
        args = ink_sample.build_parser().parse_args(["--trace", tdir, "--ink-zarr", INK, "--level", "1",
                                                     "--lo", "-2", "--hi", "2", "--trace-scale", "0.5", "--thumb-max", "256", "--out", od])
        mx, _, surf = ink_sample.run(args, log=lambda m: None)
        h, wdt = mx.shape
        pub = pub_full[:h * 4, :wdt * 4].astype(np.float32)
        hh, ww = pub.shape[0] // 4, pub.shape[1] // 4
        pub = pub[:hh * 4, :ww * 4].reshape(hh, 4, ww, 4).mean(axis=(1, 3)) / 255.0
        ours = mx[:hh, :ww]
        # only the window itself (not the margin), where both images have data
        wr0, wc0 = int(round((r0 - pr0) / 4)), int(round((c0 - pc0) / 4))
        wr1, wc1 = wr0 + int(round((r1 - r0) / 4)), wc0 + int(round((c1 - c0) / 4))
        o, p = ours[wr0:wr1, wc0:wc1], pub[wr0:wr1, wc0:wc1]
        ok = np.isfinite(o) & (p > 0)
        r = pearson(o[ok], p[ok]) if ok.sum() > 100 else float("nan")
        iou = iou90(o[ok], p[ok]) if ok.sum() > 100 else float("nan")
        rows[name] = dict(r=r, iou=iou, n=int(ok.sum()), cover=float(ok.mean()))
        log(f"[{role}] {name:10s} r {r:+.3f}  IoU90 {iou:.3f}  pixels {int(ok.sum())} ({ok.mean():.0%} of window)  "
            f"total {total_bytes() / 1e9:.2f} GB")
    results.append((role, rows))
    if total_bytes() > a.max_gb * 1e9:
        break

# ---- readout
out_csv = os.path.join(a.out, "scroll1_letter_test_c1.csv")
with open(out_csv, "w", encoding="utf-8", newline="\n") as f:
    wr = csv.writer(f, lineterminator="\n")
    wr.writerow(["window", "trace", "pearson_r", "iou90", "pixels", "window_cover"])
    for role, rows in results:
        for name, v in rows.items():
            wr.writerow([role, name, f"{v['r']:.4f}", f"{v['iou']:.4f}", v["n"], f"{v['cover']:.3f}"])
print()
print(f"[fable] Part C stage C1 - Scroll 1 letter test - {time.strftime('%d %b %Y %H:%M')}")
print(f"segment {seg}; 3-D ink {a.ink3d} level 1 (9.6 um); published picture {ink_key.rsplit('/', 1)[-1]}")
print(f"downloaded {total_bytes() / 1e9:.2f} GB")
passes = 0
for role, rows in results:
    o = rows.get("original", {})
    br = [v["r"] if np.isfinite(v["r"]) else 0.0 for k, v in rows.items() if k in ("shift-full", "scramble")]
    best = max(br) if br else float("nan")      # no agreement (nan) counts as 0
    line = f"{role:8s} original r {o.get('r', float('nan')):+.3f} IoU {o.get('iou', float('nan')):.3f}; best broken (shift-full/scramble) r {best:+.3f}"
    if role.startswith("letter"):
        ro = o.get("r", float("nan"))
        okr = np.isfinite(ro) and ro >= 0.5 and np.isfinite(best) and ro >= 2 * best
        passes += int(okr)
        line += f"  -> r>=0.5 and >=2x broken: {'YES' if okr else 'no'}"
        if "shift-half" in rows:
            hr = rows["shift-half"]["r"]
            line += f"  [diagnostic, not the rule: shift-half r {hr:+.3f}]"
    else:
        okb = o.get("r", 1) < 0.2 or o.get("iou", 1) < 0.1
        line += f"  -> blank r<0.2 or IoU<0.1: {'YES' if okb else 'no'}"
    print(line)
print(f"letter windows meeting the ink part of the rule: {passes} of {sum(1 for r, _ in results if r.startswith('letter'))}"
      " (PASS also needs the blank condition and panel_v2, stage C2)")
print(f"written {out_csv}; per-trace ink images and thumbnails under {a.out} (private)")
