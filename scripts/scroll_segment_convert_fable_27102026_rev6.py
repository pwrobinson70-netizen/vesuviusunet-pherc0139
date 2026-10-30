#!/usr/bin/env python3
"""
scroll_segment_convert_fable_25102026_rev5c.py  (rev5c, [fable], 25 Oct 2026; Sonnet 314 M1: a PARTIAL last block (coarse grid passing the
  map's end mid-block) kept its full area but lost its last fine row/col - fixed by a one-pixel zero pad; rev5b, Sonnet 310: --label_vox = ORIGIN-ANCHORED area mean,
  block edges rint(i * seg_vox/label_vox) from a shared (0,0) corner, blocks past the map's end = 0; the rev5 same-extent (linspace) rule
  was WRONG for PHerc0139 (map/volume ratio 3.88-3.90 < 3.9025: both grids share an origin, padded at the far edge) and is kept only as
  --label_mode extent for the record. rev5 = rev4 + plan C7: --label_downsample, window-indexed
registration, --mask_lcc largest-component mask with --cut_stop, ink-share warning; Sonnet 284 r4, 294 W1, 300 M1/M2, 304 P1-P3)

REV5 ADDITIONS (plan C7 rev2 + addendum A1)
  --label_downsample  the published map may be on a FINER grid than the volume (PHerc0139: 2.399 um map vs 9.362 um render).
                The map is area-meaned onto the EXACT level-0 (H, W) of the volume, y and x factors separately: block edges =
                rint(linspace(0, Hs, H+1)) / rint(linspace(0, Ws, W+1)); block sums by np.add.reduceat in uint32 (rows first,
                then columns), divided by the block areas, rounded to uint8. THEN the box is cut, THEN the >= 128 threshold.
                Without the flag a shape mismatch still STOPS (rev3 rule). label_raw.png = the downsampled uint8 crop.
  REGISTRATION  now defined on the KEPT stack in WINDOW indices: the central 8 of the n kept layers, REG_WIN = (n//2-4, n//2+4)
                (16 layers -> window 4..11 = source NATIVE_LAYERS[0]+4 .. +11; 0139 window 6..22 -> source 10..17; Sonnet 294 W1).
                Both are printed and stored in the provenance. Applied only when a label exists; otherwise "REG: n/a (no label)".
  --mask_lcc    M1 (Sonnet 300): mask.png = the LARGEST 4-connected component of (any non-zero voxel in the kept window),
                not every non-zero pixel; detached slivers are excluded. Component count and the kept share are logged.
  --cut_stop    with --mask_lcc: STOP if the largest component touches a box edge that lies INSIDE the sheet (a cut); a box edge
                that coincides with the sheet border (x0 == 0, y0 == 0, x1 == W, y1 == H) is not a cut (Sonnet 304 P1).
                NOT for the 0139 training boxes (they are cut inside the papyrus on purpose): targets only.
  INK SHARE     a box with ink share > 0.35 in the mask prints a WARNING (Sonnet 288: dense zones are the map's failures, not text).

Turns a crop of a Vesuvius scroll-segment surface volume (zarr, 33 layers, uint8, 7.91 um)
into a VesuviusUNET fragment folder (65 x NN.tif uint16 + mask.png + inklabels.png) at the
TRAINING voxel pitch (3.24 um, Sonnet 200 from the data server's meta.json), so the frozen
Frag1/Frag2 checkpoints can be run on it unchanged by vesuvius_unet.cross_infer.

NO LABELS EXIST FOR A SEGMENT. inklabels.png is written all-zero so the loader accepts the
folder; every precision/recall/F0.5/AUC line cross_infer prints on this folder is MEANINGLESS
and must be read as "[NO LABELS: metric lines meaningless]". The output is a picture, not a score.

PRE-REGISTERED PILOT RULES (agreed fable 199 / sonnet 200, 21 Oct 2026; written here so they
cannot drift after the map is seen):
  ORIENTATION: candidate (b) is run twice, on the as-is folder and on the z-reversed folder
    (same bytes, layer order reversed). Keep the orientation whose 0.5-thresholded map overlaps
    the TimeSformer tile (shrunk/aligned to the same box) more; if neither shows letter-like
    strokes by eye, the pilot is NEGATIVE and P4 (whole segment / eligible scroll) does not run.
    Asymmetry (Sonnet 202 f5): cross_infer reads the first 64 of the 65 files, so the as-is folder
    uses kept layers 0..63 and the z-reversed folder uses kept layers 64..1; each orientation drops
    a different outermost layer. Negligible for a picture; stated here so it is not a surprise.
  INTENSITY: dataset/infer divide by a fixed 65535, so brightness matters. The only allowed fix
    is one linear rescale mapping the crop's 1st/99th percentiles onto the reference fragment
    tif's 1st/99th percentiles, and it is applied MECHANICALLY by this rule, decided before the
    pilot runs: rescale if and only if (crop p99 x 257) is outside [0.5 x ref p99, 2.0 x ref p99].
    Otherwise the crop is written as uint8 x 257 with no change. Like for like (Sonnet 202 f3):
    the crop percentiles are taken over the MIDDLE kept layers 24..40 inside the mask (an exact
    256-bin histogram, no copy), the reference percentiles over pixels > 0 of ONE middle Frag4
    layer (default 32.tif). If the rescale fires it is applied to all 65 layers with that one map.
  RESAMPLING (fable 199 Q1): all three axes are zoomed by seg_vox/train_vox (7.91/3.24 = 2.441,
    axis order z, y, x), linear (order 1), on uint8; z 33 -> 81 layers, centre-cropped to 65.
    scipy zoom with grid_mode=False is edge-aligned (output i -> input i*(n_in-1)/(n_out-1)), so the
    effective factor differs from 2.441 by well under 1 px over the crop (Sonnet 202 f4); recorded
    in the provenance JSON as "zoom_geometry".
  MISSING CHUNKS (Sonnet 202 f1): zarr does not store all-fill chunks; an HTTP 404 for a chunk means
    "all zero" and is filled with 0 (no retry), counted and listed in the provenance JSON. A chunk
    that exists but is not exactly 540,672 B still stops the run.

REV3 ADDITIONS (plan C3, Sonnet 212/214)
  --native      NO resampling: the crop is written at the segment's own pitch (7.91 um), layers 1..32 of the 33 (layer 0
                dropped) -> 32 files 00.tif..31.tif, uint8 x 257, ONE folder data_seg_<tag>_<stamp>_native (no z-reversed
                twin: C3 trains and tests in the same orientation). The INTENSITY rule is NOT applied in native mode (no
                fragment reference is relevant when training on scroll data); percentiles are still logged.
  --label_tif   URL (or local path) of the segment's published TimeSformer map (level-0, uint8 0..255 probability x 255,
                same grid as the volume; Sonnet 214). The map is fetched whole, its shape must equal the .zarray level-0
                (H, W) exactly or the run STOPS; the box is cut out on the same grid (no resampling); inklabels.png =
                (map >= 128) * 255 (PSEUDO-LABEL RULE, fixed in Sonnet 214 / fable plan rev2); label_raw.png = the uint8
                crop as is. Without --label_tif, inklabels.png is all-zero as before.
  REGISTRATION CHECK (Sonnet 214 [verify]): with --label_tif, the label crop is correlated with the mean of the central
                source layers (12..20) at integer offsets -8..+8 px in x and y; the offset with the largest |r| is logged
                (expected (0, 0)); a peak elsewhere is logged as a WARNING, not a stop - Sonnet judges it in review.
  Native mode + --label_tif is the C3 training/held-out converter; --native without --label_tif is the C3 PHerc0800 path.

Modes
  (no flag)   DRY RUN: fetch .zarray/.zattrs (metadata only), list the chunk keys the box needs,
              their count and bytes, the output shape and size. No chunk is downloaded.
  --head      DRY RUN + one HTTP HEAD on the first chunk (expects Content-Length 540672).
  --go        download the chunks, convert, write the two folders, provenance JSON, log.
  --selftest  synthetic chunks in memory (no network): shapes, dtype, mask, stroke position,
              z-reversal links, percentile rule. Exits 0 on pass.

Usage (on a pod; label the shell "Linux"):
  python3 -I scroll_segment_convert_fable_21102026.py --box 4096 8192 6144 10240 \
      --out_root /workspace/VesuviusUNET --ref_tif /workspace/VesuviusUNET/data_frag4/32.tif
  then with --go. Output folders: <out_root>/data_seg_<segtag>_<stamp>_asis and ..._zrev.
"""
import argparse, hashlib, json, os, resource, sys, time, urllib.request, urllib.error

import numpy as np

DEFAULT_BASE = ("https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0172/segments/"
                "20251206184729-w095_20251206184729906_flatboi/surface-volumes/"
                "7.91um-53keV-volume-20241024131838.zarr")
EXPECT_CHUNK = (33, 128, 128)          # from .zarray, Sonnet 197 (verbatim)
EXPECT_BYTES = 33 * 128 * 128          # 540,672 B raw uint8, compressor null (Sonnet 200 2b)
DEPTH_OUT = 65                          # VesuviusUNET fragment folders: 00.tif .. 64.tif (resampled mode)
NATIVE_LAYERS = (1, 33)                 # native mode keeps source layers [1, 33) = 1..32 -> 32 files (plan C3 section 2)
PAD_TO = 0                              # rev4: native mode, if > 0, pad the kept stack to this many layers by repeating the LAST kept layer
                                        # (plan C4: PHerc0800 has 31 layers -> keep 0..30, pad to 32 so the depth-32 models can run)
LABEL_THR = 128                         # pseudo-label rule: map >= 128 (0.5 x 255) is ink (Sonnet 214)
REG_LAYERS = (12, 21)                   # rev4 source-layer range (kept for the percentile log only); rev5 registration uses REG_WIN below
LABEL_DOWNSAMPLE = False                # rev5: area-mean a finer map onto the volume's level-0 (H, W) before cutting the box
MASK_LCC = False                        # rev5: mask = largest 4-connected component of the any-non-zero mask (M1)
CUT_STOP = False                        # rev5: with MASK_LCC, STOP when the component touches a box edge inside the sheet (P1)
LABEL_R = None                          # rev5b: seg_vox / label_vox when --label_vox is given (origin-anchored area mean)
LABEL_VOX = None
ZLEVEL = 0                              # rev6 (plan C8): zarr multiscale level read (0 = full res); keys "<level>/z/y/x"
INK_SHARE_WARN = 0.35                   # rev5: warn when the box ink share in the mask exceeds this (not a stop)


def reg_window(n_kept):
    """Registration layers in WINDOW indices: the central 8 of the n kept layers, half-open (Sonnet 294 W1 / 304 P2)."""
    return (n_kept // 2 - 4, n_kept // 2 + 4)
PAD = 16                                # source pixels of border kept around the box for the zoom
MID_LAYERS = (24, 41)                   # kept layers [24, 41) used for the crop percentiles (f3)

_LOG = []
_LOGF = None


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), msg)
    print(line, flush=True)
    _LOG.append(line)
    if _LOGF:
        _LOGF.write(line + "\n"); _LOGF.flush()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def peak_rss_mb():
    # ru_maxrss is KiB on Linux
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


# ----------------------------------------------------------------------------- fetching
class HttpFetcher:
    def __init__(self, base, timeout=120, retries=3):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def get(self, rel):
        url = rel if rel.startswith(("http://", "https://")) else self.base + "/" + rel
        if rel.startswith("/") or rel.startswith("file:"):
            with open(rel[7:] if rel.startswith("file:") else rel, "rb") as f:
                return f.read()
        last = None
        for i in range(self.retries):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None          # zarr omits all-fill chunks: absent == all zero (no retry)
                last = e
            except (urllib.error.URLError, OSError) as e:
                last = e
                log("fetch retry %d/%d for %s: %s" % (i + 1, self.retries, rel, e))
                time.sleep(2 * (i + 1))
        raise RuntimeError("fetch failed for %s: %s" % (url, last))

    def head_len(self, rel):
        url = self.base + "/" + rel
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return int(r.headers.get("Content-Length", "-1"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise


class DictFetcher:
    """selftest: chunks from memory; .zarray/.zattrs synthesised."""
    def __init__(self, chunks, shape):
        self.chunks = chunks
        self.shape = shape

    def get(self, rel):
        if rel == "%d/.zarray" % ZLEVEL:
            return json.dumps({"shape": list(self.shape), "chunks": list(EXPECT_CHUNK), "dtype": "|u1",
                               "compressor": None, "dimension_separator": "/"}).encode()
        if rel in ("0/.zattrs", ".zattrs"):
            return json.dumps({"synthetic": True}).encode()
        if rel.startswith("label:"):
            return self.chunks[rel]
        return self.chunks.get(rel)      # None == absent (all-fill) chunk, as a 404 would be

    def head_len(self, rel):
        return len(self.chunks[rel]) if rel in self.chunks else None


def read_zarray(fetcher):
    za = json.loads(fetcher.get("%d/.zarray" % ZLEVEL).decode())
    shape = tuple(int(v) for v in za["shape"])
    chunks = tuple(int(v) for v in za["chunks"])
    if chunks != EXPECT_CHUNK:
        raise RuntimeError(".zarray chunks %s != expected %s" % (chunks, EXPECT_CHUNK))
    if za.get("dtype") != "|u1":
        raise RuntimeError(".zarray dtype %r != '|u1'" % za.get("dtype"))
    if za.get("compressor") is not None:
        raise RuntimeError(".zarray compressor %r is not null; raw-chunk reader cannot be used" % za.get("compressor"))
    if za.get("dimension_separator", ".") != "/":
        raise RuntimeError(".zarray dimension_separator %r != '/'" % za.get("dimension_separator"))
    if len(shape) != 3 or shape[0] != EXPECT_CHUNK[0]:
        raise RuntimeError(".zarray shape %s: expected 3-D with %d layers" % (shape, EXPECT_CHUNK[0]))
    return shape, za


def chunk_keys_for(box, shape):
    """box = (x0, y0, x1, y1) in level-0 segment pixels, half-open. Returns (keys, y_lo, x_lo, y_hi, x_hi)
    where the fetched region is chunk-aligned and covers box padded by PAD on each side, clipped to shape."""
    x0, y0, x1, y1 = box
    cz, cy, cx = EXPECT_CHUNK
    ya, yb = max(0, y0 - PAD), min(shape[1], y1 + PAD)
    xa, xb = max(0, x0 - PAD), min(shape[2], x1 + PAD)
    yc0, yc1 = ya // cy, (yb - 1) // cy
    xc0, xc1 = xa // cx, (xb - 1) // cx
    keys = ["%d/0/%d/%d" % (ZLEVEL, yc, xc) for yc in range(yc0, yc1 + 1) for xc in range(xc0, xc1 + 1)]
    return keys, (yc0, yc1, xc0, xc1), (ya, yb, xa, xb)


def assemble(fetcher, keys, grid, region, prov):
    """Fetch the chunks and return the uint8 array for region (ya:yb, xa:xb), all 33 layers."""
    yc0, yc1, xc0, xc1 = grid
    ya, yb, xa, xb = region
    cz, cy, cx = EXPECT_CHUNK
    H = (yc1 - yc0 + 1) * cy
    W = (xc1 - xc0 + 1) * cx
    vol = np.zeros((cz, H, W), dtype=np.uint8)
    prov.setdefault("missing_chunks", [])
    for k in keys:
        _, _, yc, xc = k.split("/")
        yc, xc = int(yc), int(xc)
        b = fetcher.get(k)
        if b is None:
            prov["missing_chunks"].append(k)   # tile stays 0 in vol
            continue
        if len(b) != EXPECT_BYTES:
            raise RuntimeError("chunk %s is %d B, not %d; refusing (compressed or truncated)" % (k, len(b), EXPECT_BYTES))
        prov["chunks"].append({"key": k, "bytes": len(b), "sha256": sha256_bytes(b)})
        arr = np.frombuffer(b, dtype=np.uint8).reshape(EXPECT_CHUNK)   # C order z, y, x as zarr stores it
        oy, ox = (yc - yc0) * cy, (xc - xc0) * cx
        vol[:, oy:oy + cy, ox:ox + cx] = arr
    log("%d of %d chunks absent on the server (zarr all-fill; written as 0)" % (len(prov["missing_chunks"]), len(keys)))
    oy0, ox0 = yc0 * cy, xc0 * cx
    sub = vol[:, ya - oy0:yb - oy0, xa - ox0:xb - ox0]
    return np.ascontiguousarray(sub)


# ----------------------------------------------------------------------------- conversion
def zoom_uint8(vol, f):
    """Linear zoom by factor f on all three axes (z, y, x), output stays uint8 (Sonnet 200 (a))."""
    from scipy.ndimage import zoom
    out = zoom(vol, (f, f, f), order=1, mode="nearest", prefilter=False, grid_mode=False)
    assert out.dtype == np.uint8, out.dtype
    return out


def expected_out_hw(box, f):
    x0, y0, x1, y1 = box
    return int(round((y1 - y0) * f)), int(round((x1 - x0) * f))


def convert(vol, box, region, f, prov):
    """vol: uint8 (33, yb-ya, xb-xa) covering region; returns uint8 (DEPTH_OUT, H, W) for the box only."""
    ya, yb, xa, xb = region
    x0, y0, x1, y1 = box
    z = zoom_uint8(vol, f)                       # axis order (z, y, x)
    prov["zoom_output_shape"] = list(z.shape)
    nz = z.shape[0]
    if nz < DEPTH_OUT:
        raise RuntimeError("zoomed depth %d < %d; segment slab too thin for this pitch" % (nz, DEPTH_OUT))
    zs = (nz - DEPTH_OUT) // 2
    z = z[zs:zs + DEPTH_OUT]
    prov["z_layers_kept"] = [zs, zs + DEPTH_OUT - 1]
    H, W = expected_out_hw(box, f)
    ty, tx = int(round((y0 - ya) * f)), int(round((x0 - xa) * f))
    if ty + H > z.shape[1] or tx + W > z.shape[2]:
        raise RuntimeError("zoomed region %s cannot supply %dx%d at offset %d,%d" % (z.shape, H, W, ty, tx))
    out = np.ascontiguousarray(z[:, ty:ty + H, tx:tx + W])
    del z
    assert out.shape == (DEPTH_OUT, H, W), out.shape
    return out


def percentiles(a, mask=None):
    v = a[mask] if mask is not None else a.ravel()
    if v.size == 0:
        return [0.0, 0.0, 0.0]
    return [float(x) for x in np.percentile(v, [1, 50, 99])]


def percentiles_uint8_hist(vol8, m, layers):
    """Exact 1/50/99 percentiles of uint8 voxels in vol8[layers] where m (H, W) is True, by a 256-bin
    histogram (no copy of the voxels; Sonnet 202 f2). Same definition as np.percentile's default
    linear interpolation evaluated on the sorted values, which for integers equals the value at the
    interpolated rank; we return the lower-rank value (differs from np.percentile by < 1 grey level)."""
    hist = np.zeros(256, dtype=np.int64)
    for i in range(layers[0], layers[1]):
        hist += np.bincount(vol8[i][m], minlength=256)
    n = int(hist.sum())
    if n == 0:
        return [0.0, 0.0, 0.0]
    cum = np.cumsum(hist)
    out = []
    for q in (1, 50, 99):
        rank = (q / 100.0) * (n - 1)           # np.percentile 'linear' rank
        lo = int(np.floor(rank))
        out.append(float(np.searchsorted(cum, lo + 1)))
    return out


def intensity_rule(crop_p, ref_p):
    """Returns (rescale: bool, reason). crop_p are uint8 percentiles x257; ref_p uint16 percentiles."""
    c99, r99 = crop_p[2], ref_p[2]
    if r99 <= 0:
        return False, "reference p99 is 0; no rescale"
    ratio = c99 / r99
    if ratio < 0.5 or ratio > 2.0:
        return True, "crop p99 x257 = %.0f vs ref p99 = %.0f (ratio %.2f outside [0.5, 2.0]) -> linear 1st/99th match" % (c99, r99, ratio)
    return False, "crop p99 x257 = %.0f vs ref p99 = %.0f (ratio %.2f inside [0.5, 2.0]) -> written as uint8 x257" % (c99, r99, ratio)


def to_uint16_slice(s8, rescale, crop_p, ref_p):
    if not rescale:
        return s8.astype(np.uint16) * np.uint16(257)
    c1, c99 = crop_p[0], crop_p[2]
    r1, r99 = ref_p[0], ref_p[2]
    if c99 <= c1:
        return s8.astype(np.uint16) * np.uint16(257)
    x = s8.astype(np.float64) * 257.0
    y = (x - c1) * (r99 - r1) / (c99 - c1) + r1
    return np.clip(np.rint(y), 0, 65535).astype(np.uint16)


def convert_native(vol, box, region, prov):
    """Native mode: no zoom; cut the box out of the fetched region and keep source layers NATIVE_LAYERS -> (n, h, w) uint8.
    rev4: if PAD_TO > n, the last kept layer is repeated until the stack has PAD_TO layers (declared in provenance)."""
    ya, yb, xa, xb = region
    x0, y0, x1, y1 = box
    out = np.ascontiguousarray(vol[NATIVE_LAYERS[0]:NATIVE_LAYERS[1], y0 - ya:y1 - ya, x0 - xa:x1 - xa])
    prov["native_layers_kept"] = [NATIVE_LAYERS[0], NATIVE_LAYERS[1] - 1]
    prov["zoom_factor_zyx"] = [1.0, 1.0, 1.0]
    prov["zoom_geometry"] = "native: no resampling"
    assert out.shape == (NATIVE_LAYERS[1] - NATIVE_LAYERS[0], y1 - y0, x1 - x0), out.shape
    n = out.shape[0]
    if PAD_TO > n:
        pad = np.repeat(out[-1:], PAD_TO - n, axis=0)
        out = np.ascontiguousarray(np.concatenate([out, pad], axis=0))
        prov["pad_layers"] = {"rule": "repeat last kept source layer", "source_layer_repeated": NATIVE_LAYERS[1] - 1,
                              "copies": int(PAD_TO - n), "stack_depth": int(PAD_TO)}
        log("PAD: %d kept layers padded to %d by repeating source layer %d (%d copies)" % (n, PAD_TO, NATIVE_LAYERS[1] - 1, PAD_TO - n))
    elif PAD_TO and PAD_TO < n:
        raise RuntimeError("--pad_to %d is smaller than the %d kept layers" % (PAD_TO, n))
    return out


def area_mean_to(lab, shape_hw, R=None):
    """Area mean of a uint8 map onto the exact (H, W) target; block sums by np.add.reduceat in uint32 (rows, then columns), divided
    by the block areas, rounded to uint8; no interpolation (Sonnet 290 item 6).
    R None  (rev5 'extent' rule): edges rint(linspace(0, Hs, H+1)) - assumes both grids span the same physical extent. WRONG when the
            fine map is padded differently from the volume (PHerc0139, Sonnet 310); kept for the record / --label_mode extent.
    R given (rev5b 'origin' rule, default): coarse pixel i covers fine rows [rint(i*R), rint((i+1)*R)) with R = seg_vox / label_vox,
            both grids anchored at the same (0, 0) corner; coarse blocks lying past the fine map's end are 0 (padding)."""
    H, W = int(shape_hw[0]), int(shape_hw[1])
    Hs, Ws = lab.shape
    if R is None:
        ey = np.rint(np.linspace(0, Hs, H + 1)).astype(np.int64)
        ex = np.rint(np.linspace(0, Ws, W + 1)).astype(np.int64)
        if np.any(np.diff(ey) <= 0) or np.any(np.diff(ex) <= 0):
            raise RuntimeError("area_mean_to: degenerate block edges (target larger than source on some axis)")
    else:
        if R < 1.0:
            raise RuntimeError("area_mean_to: R = %.4f < 1 (the map is coarser than the volume; only shrinking is defined)" % R)
        ey = np.minimum(np.rint(np.arange(H + 1) * R), Hs).astype(np.int64)
        ex = np.minimum(np.rint(np.arange(W + 1) * R), Ws).astype(np.int64)
        lab = np.pad(lab[:int(ey[-1]), :int(ex[-1])], ((0, 1), (0, 1)))      # the fine map beyond the coarse grid's reach is ignored; one zero
                                                                               # row/col absorbs past-end block starts (rev5c, Sonnet 314 M1)
    dy, dx = np.diff(ey), np.diff(ex)
    iy = np.minimum(ey[:-1], lab.shape[0] - 1); ix = np.minimum(ex[:-1], lab.shape[1] - 1)                  # reduceat needs in-range starts
    rows = np.add.reduceat(lab, iy, axis=0, dtype=np.uint32)                # (H, Ws') uint32
    blk = np.add.reduceat(rows, ix, axis=1, dtype=np.uint32)                # (H, W)   uint32
    del rows
    area = (dy[:, None] * dx[None, :]).astype(np.float64)
    out = np.where(area > 0, np.rint(blk.astype(np.float64) / np.maximum(area, 1.0)), 0.0)   # empty (past-end) blocks = 0
    return np.clip(out, 0, 255).astype(np.uint8)


def largest_component(m):
    """Largest 4-connected component of a boolean mask (scipy.ndimage.label, default cross structure). Returns (lcc, n_components)."""
    from scipy.ndimage import label as cc_label
    lab, n = cc_label(m)
    if n <= 1:
        return m.astype(bool), int(n)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return lab == int(sizes.argmax()), int(n)


def load_label(fetcher, src, shape_hw, prov):
    """Fetch the published map (whole), check its shape against the level-0 (H, W), return the uint8 array."""
    import io, tifffile
    b = fetcher.get(src)
    if b is None:
        raise RuntimeError("label map not found: %s" % src)
    lab = tifffile.imread(io.BytesIO(b))
    if lab.ndim == 3 and lab.shape[-1] in (3, 4):
        lab = lab[..., 0]
    if lab.ndim != 2:
        raise RuntimeError("label map is not a single 2-D page: shape %s" % (lab.shape,))
    if lab.dtype != np.uint8:
        raise RuntimeError("label map dtype %s is not uint8; the >= 128 rule is defined on uint8 (STOP, ask Sonnet)" % lab.dtype)
    src_shape = list(lab.shape)
    if tuple(lab.shape) != tuple(shape_hw):
        if not LABEL_DOWNSAMPLE:
            raise RuntimeError("label map shape %s != volume level-0 (H, W) %s; labels cannot be aligned (STOP; use --label_downsample "
                               "only for a map on a finer grid of the same mesh)" % (lab.shape, tuple(shape_hw)))
        if lab.shape[0] < shape_hw[0] or lab.shape[1] < shape_hw[1]:
            raise RuntimeError("label map %s is SMALLER than the volume %s; --label_downsample only shrinks (STOP)" % (lab.shape, tuple(shape_hw)))
        fy, fx = lab.shape[0] / shape_hw[0], lab.shape[1] / shape_hw[1]
        if LABEL_R is None:
            lab = area_mean_to(lab, shape_hw)
            mapping = "extent (rev5 linspace; same-extent assumption)"
            log("label map downsampled by area mean %s -> %s (factors y %.4f x %.4f, EXTENT rule - for the record only)" % (src_shape, list(lab.shape), fy, fx))
        else:
            lab = area_mean_to(lab, shape_hw, R=LABEL_R)
            mapping = "origin-anchored R=%.4f (seg_vox/label_vox)" % LABEL_R
            cov_y, cov_x = shape_hw[0] * LABEL_R, shape_hw[1] * LABEL_R
            log("label map downsampled by area mean %s -> %s, ORIGIN-ANCHORED, R %.4f per axis (extent ratios y %.4f x %.4f for the record); "
                "coarse grid reaches fine row %.0f of %d, col %.0f of %d (%s)" % (src_shape, list(lab.shape), LABEL_R, fy, fx, cov_y, src_shape[0], cov_x, src_shape[1],
                "volume padded past the map" if cov_y >= src_shape[0] and cov_x >= src_shape[1] else "MAP extends past the volume on some axis - check"))
    prov["label"] = {"source": src, "bytes": len(b), "sha256": sha256_bytes(b), "shape_hw": list(lab.shape), "source_shape_hw": src_shape,
                     "downsampled": src_shape != list(lab.shape), "mapping": mapping if src_shape != list(lab.shape) else "same grid",
                     "label_vox_um": LABEL_VOX, "dtype": str(lab.dtype),
                     "min": int(lab.min()), "max": int(lab.max()), "threshold": LABEL_THR}
    log("label map %s: %d B sha256 %s shape %s dtype %s min %d max %d == volume (H, W): ok" %
        (src.split("/")[-1][-60:], len(b), prov["label"]["sha256"][:16], lab.shape, lab.dtype, lab.min(), lab.max()))
    return lab


def registration_check(out8, lab_crop, prov, maxoff=8):
    """|Pearson r| between the label crop and the mean of the central 8 KEPT layers (REG_WIN, window indices), at integer offsets
    -maxoff..+maxoff; the peak is expected at (0, 0). out8 and lab_crop are both box-sized (rev5: no region arithmetic)."""
    n = out8.shape[0]
    w0, w1 = reg_window(n)
    s0, s1 = NATIVE_LAYERS[0] + w0, NATIVE_LAYERS[0] + w1
    sub = out8[w0:w1].mean(axis=0)
    h, w = lab_crop.shape
    L = lab_crop[maxoff:h - maxoff, maxoff:w - maxoff].astype(np.float64)
    L -= L.mean(); Ln = np.sqrt((L * L).sum()) + 1e-9
    best = (0.0, 0, 0); r00 = 0.0
    for dy in range(-maxoff, maxoff + 1):
        for dx in range(-maxoff, maxoff + 1):
            S = sub[maxoff + dy:h - maxoff + dy, maxoff + dx:w - maxoff + dx].astype(np.float64)
            S -= S.mean(); Sn = np.sqrt((S * S).sum()) + 1e-9
            r = float((L * S).sum() / (Ln * Sn))
            if dy == 0 and dx == 0:
                r00 = r
            if abs(r) > abs(best[0]):
                best = (r, dy, dx)
    prov["registration"] = {"window_layers": [w0, w1 - 1], "source_layers": [s0, s1 - 1], "max_offset_px": maxoff,
                            "r_at_0_0": r00, "best_r": best[0], "best_dy": best[1], "best_dx": best[2]}
    msg = "registration (window %d..%d = source %d..%d): r(0,0) = %+.4f; best |r| %+.4f at (dy, dx) = (%d, %d)" % (w0, w1 - 1, s0, s1 - 1, r00, best[0], best[1], best[2])
    if max(abs(best[1]), abs(best[2])) > 2 or abs(best[0]) < 0.05:
        log("WARNING " + msg + " - label grid may be offset or uncorrelated; plan C7 F8: STOP if this is a training/held-out box")
    else:
        log(msg + " - label grid aligned")


def write_native_folder(out8, lab_crop, out_root, tag, stamp, prov, box=None, sheet_hw=None):
    import tifffile
    from PIL import Image
    d = os.path.join(out_root, "data_seg_%s_%s_native" % (tag, stamp))
    if os.path.exists(d):
        raise RuntimeError("refusing to overwrite existing folder %s" % d)
    D, H, W = out8.shape
    m = out8.max(axis=0) > 0
    prov["mask"] = {"rule": "any non-zero voxel in the kept window", "share": float(m.mean())}
    if MASK_LCC:
        lcc, ncomp = largest_component(m)
        prov["mask"] = {"rule": "largest 4-connected component of any-non-zero (M1)", "components": ncomp,
                        "share_any": float(m.mean()), "share_lcc": float(lcc.mean())}
        log("mask M1: %d component(s); any-non-zero share %.3f -> largest component share %.3f" % (ncomp, m.mean(), lcc.mean()))
        if CUT_STOP:
            if box is None or sheet_hw is None:
                raise RuntimeError("--cut_stop needs the box and the sheet shape")
            x0, y0, x1, y1 = box
            cuts = []
            if y0 > 0 and lcc[0, :].any(): cuts.append("top (y0=%d)" % y0)
            if y1 < sheet_hw[0] and lcc[-1, :].any(): cuts.append("bottom (y1=%d < H=%d)" % (y1, sheet_hw[0]))
            if x0 > 0 and lcc[:, 0].any(): cuts.append("left (x0=%d)" % x0)
            if x1 < sheet_hw[1] and lcc[:, -1].any(): cuts.append("right (x1=%d < W=%d)" % (x1, sheet_hw[1]))
            prov["mask"]["cut_edges"] = cuts
            if cuts:
                raise RuntimeError("CUT STOP: the largest papyrus component touches box edge(s) inside the sheet: %s; box %s, sheet (H, W) %s - enlarge the box (Sonnet 304 P1)"
                                   % (", ".join(cuts), list(box), list(sheet_hw)))
            log("cut check: no interior box edge touched by the component (sheet-border edges do not count)")
        m = lcc
    os.makedirs(d)
    mask = m.astype(np.uint8) * 255
    files = {}
    for i in range(D):
        p = os.path.join(d, "%02d.tif" % i)
        tifffile.imwrite(p, out8[i].astype(np.uint16) * np.uint16(257), photometric="minisblack")
        files["%02d.tif" % i] = sha256_file(p)
    Image.fromarray(mask, mode="L").save(os.path.join(d, "mask.png"))
    if lab_crop is None:
        ink = np.zeros((H, W), dtype=np.uint8)
    else:
        ink = ((lab_crop >= LABEL_THR) * 255).astype(np.uint8)
        Image.fromarray(lab_crop, mode="L").save(os.path.join(d, "label_raw.png"))
        files["label_raw.png"] = sha256_file(os.path.join(d, "label_raw.png"))
    Image.fromarray(ink, mode="L").save(os.path.join(d, "inklabels.png"))
    files["mask.png"] = sha256_file(os.path.join(d, "mask.png"))
    files["inklabels.png"] = sha256_file(os.path.join(d, "inklabels.png"))
    ink_in_mask = int(((ink > 0) & (mask > 0)).sum())
    share = float(ink_in_mask / max(1, (mask > 0).sum()))
    prov["output"] = {"native": d, "shape_dhw": [D, H, W], "dtype": "uint16", "mask_papyrus_px": int((mask > 0).sum()),
                      "ink_px": int((ink > 0).sum()), "ink_px_in_mask": ink_in_mask, "ink_share_in_mask": share, "files_sha256": files}
    if lab_crop is not None and share > INK_SHARE_WARN:
        log("WARNING ink share in mask %.3f > %.2f: dense zones of the published map are its own failures, not text (Sonnet 288) - check the box by eye" % (share, INK_SHARE_WARN))
    return d, mask, ink


def write_folders(out8, out_root, tag, stamp, rescale, crop_p, ref_p, prov):
    import tifffile
    from PIL import Image
    asis = os.path.join(out_root, "data_seg_%s_%s_asis" % (tag, stamp))
    zrev = os.path.join(out_root, "data_seg_%s_%s_zrev" % (tag, stamp))
    for d in (asis, zrev):
        if os.path.exists(d):
            raise RuntimeError("refusing to overwrite existing folder %s" % d)
        os.makedirs(d)
    D, H, W = out8.shape
    assert D == DEPTH_OUT
    mask = (out8.max(axis=0) > 0).astype(np.uint8) * 255
    files = {}
    for i in range(D):
        p = os.path.join(asis, "%02d.tif" % i)
        tifffile.imwrite(p, to_uint16_slice(out8[i], rescale, crop_p, ref_p), photometric="minisblack")
        files["%02d.tif" % i] = sha256_file(p)
    Image.fromarray(mask, mode="L").save(os.path.join(asis, "mask.png"))
    Image.fromarray(np.zeros((H, W), dtype=np.uint8), mode="L").save(os.path.join(asis, "inklabels.png"))
    files["mask.png"] = sha256_file(os.path.join(asis, "mask.png"))
    files["inklabels.png"] = sha256_file(os.path.join(asis, "inklabels.png"))
    # z-reversed folder: same bytes, reversed layer order; hard links when the filesystem allows, else copies
    link_mode = "hardlink"
    for i in range(D):
        src = os.path.join(asis, "%02d.tif" % (D - 1 - i))
        dst = os.path.join(zrev, "%02d.tif" % i)
        try:
            os.link(src, dst)
        except OSError:
            link_mode = "copy"
            with open(src, "rb") as a, open(dst, "wb") as b:
                b.write(a.read())
    for n in ("mask.png", "inklabels.png"):
        try:
            os.link(os.path.join(asis, n), os.path.join(zrev, n))
        except OSError:
            with open(os.path.join(asis, n), "rb") as a, open(os.path.join(zrev, n), "wb") as b:
                b.write(a.read())
    prov["output"] = {"asis": asis, "zrev": zrev, "zrev_mode": link_mode, "shape_dhw": [D, H, W],
                      "dtype": "uint16", "mask_papyrus_px": int((mask > 0).sum()), "files_sha256": files}
    return asis, zrev, mask


# ----------------------------------------------------------------------------- driver
def run(args, fetcher, stamp):
    prov = {"script": os.path.basename(__file__), "stamp": stamp, "base_url": args.base_url, "box_x0y0x1y1": list(args.box),
            "seg_vox_um": args.seg_vox, "train_vox_um": args.train_vox, "zoom_factor_zyx": None, "chunks": [],
            "pad_src_px": PAD, "depth_out": DEPTH_OUT}
    shape, za = read_zarray(fetcher)
    try:
        attrs = json.loads(fetcher.get("0/.zattrs").decode())
    except Exception as e:   # noqa: BLE001 - attrs are informational only
        attrs = {"error": str(e)}
    prov["zarray"] = za
    prov["zattrs"] = attrs
    prov["zarr_level"] = ZLEVEL
    log("zarr level %d: shape" % ZLEVEL + " %s chunks %s dtype %s compressor %s" % (shape, za["chunks"], za["dtype"], za.get("compressor")))
    x0, y0, x1, y1 = args.box
    if not (0 <= x0 < x1 <= shape[2] and 0 <= y0 < y1 <= shape[1]):
        raise RuntimeError("box %s outside volume y<%d x<%d" % (args.box, shape[1], shape[2]))
    f = 1.0 if getattr(args, "native", False) else args.seg_vox / args.train_vox
    prov["mode"] = "native" if args.native else "resampled"
    prov["zoom_factor_zyx"] = [f, f, f]
    prov["zoom_geometry"] = "scipy.ndimage.zoom order=1 grid_mode=False (edge-aligned: output i -> input i*(n_in-1)/(n_out-1)); the nominal factor is not exact at the sub-pixel level"
    keys, grid, region = chunk_keys_for(args.box, shape)
    H, W = expected_out_hw(args.box, f)
    nz = int(round(shape[0] * f))
    if args.native:
        log("NATIVE mode: box x %d..%d y %d..%d (%d x %d px at %.2f um, no resampling); layers %d..%d kept -> %d files%s; label: %s" %
            (x0, x1, y0, y1, x1 - x0, y1 - y0, args.seg_vox, NATIVE_LAYERS[0], NATIVE_LAYERS[1] - 1, NATIVE_LAYERS[1] - NATIVE_LAYERS[0],
             " (+%d padded copies of the last -> %d)" % (PAD_TO - (NATIVE_LAYERS[1] - NATIVE_LAYERS[0]), PAD_TO) if PAD_TO > NATIVE_LAYERS[1] - NATIVE_LAYERS[0] else "",
             args.label_tif if args.label_tif else "NONE (inklabels all-zero)"))
    else:
        log("box x %d..%d y %d..%d (%d x %d source px); zoom %.4f on (z, y, x); z %d -> %d layers, keep central %d" %
            (x0, x1, y0, y1, x1 - x0, y1 - y0, f, shape[0], nz, DEPTH_OUT))
    log("chunks needed: %d (%d B each, %.1f MB); region fetched y %d..%d x %d..%d" %
        (len(keys), EXPECT_BYTES, len(keys) * EXPECT_BYTES / 1e6, region[0], region[1], region[2], region[3]))
    if args.native:
        nd = max(PAD_TO, NATIVE_LAYERS[1] - NATIVE_LAYERS[0])
        log("output: 1 folder x %d x %d x %d uint16 (%.2f GB on disk)" % (nd, H, W, nd * H * W * 2 / 1e9))
    else:
        log("output: 2 folders x %d x %d x %d uint16 (%.2f GB on disk for asis; zrev hard-linked when possible)" %
            (DEPTH_OUT, H, W, DEPTH_OUT * H * W * 2 / 1e9))
    if args.head:
        n = fetcher.head_len(keys[0])
        if n is None:
            log("HEAD %s: 404 (absent = all-fill chunk); fine" % keys[0])
        else:
            log("HEAD %s Content-Length %d %s" % (keys[0], n, "ok" if n == EXPECT_BYTES else "MISMATCH (expected %d)" % EXPECT_BYTES))
    if not args.go:
        log("DRY RUN complete: no chunk downloaded, nothing written. Re-run with --go after Sonnet's review and Pedro's word.")
        return prov
    if args.native:
        lab = load_label(fetcher, args.label_tif, shape[1:], prov) if args.label_tif else None
        t0 = time.time()
        vol = assemble(fetcher, keys, grid, region, prov)
        log("fetched %d chunk keys in %.0f s; region array %s uint8; peak RSS %.0f MB" % (len(keys), time.time() - t0, vol.shape, peak_rss_mb()))
        out8 = convert_native(vol, args.box, region, prov)
        del vol
        lab_crop = None
        if lab is not None:
            lab_crop = np.ascontiguousarray(lab[y0:y1, x0:x1])
            registration_check(out8, lab_crop, prov)
            del lab
        else:
            w0, w1 = reg_window(out8.shape[0])
            prov["registration"] = {"status": "n/a (no label)", "window_layers": [w0, w1 - 1], "source_layers": [NATIVE_LAYERS[0] + w0, NATIVE_LAYERS[0] + w1 - 1]}
            log("REG: n/a (no label); window %d..%d = source %d..%d recorded" % (w0, w1 - 1, NATIVE_LAYERS[0] + w0, NATIVE_LAYERS[0] + w1 - 1))
        m = out8.max(axis=0) > 0
        mid = reg_window(out8.shape[0])
        crop_p8 = percentiles_uint8_hist(out8, m, mid)
        log("native crop percentiles 1/50/99 (uint8, inside mask, kept layers %d..%d) = %.1f / %.1f / %.1f (no intensity rule in native mode)" %
            (mid[0], mid[1] - 1, *crop_p8))
        prov["intensity"] = {"mode": "native, no rescale", "crop_layers_kept_index": list(mid), "crop_percentiles_uint8": crop_p8}
        d, mask, ink = write_native_folder(out8, lab_crop, args.out_root, args.tag, stamp, prov, box=args.box, sheet_hw=shape[1:])
        log("written %s: %s; mask papyrus px %d of %d; ink px %d (share in mask %.3f); peak RSS %.0f MB" %
            (d, prov["output"]["shape_dhw"], prov["output"]["mask_papyrus_px"], mask.size, prov["output"]["ink_px"], prov["output"]["ink_share_in_mask"], peak_rss_mb()))
        prov["peak_rss_mb"] = peak_rss_mb()
        return prov
    # reference percentiles (Frag4 tif) - required for the intensity rule (resampled mode only)
    import tifffile
    ref = tifffile.imread(args.ref_tif)
    ref_p = percentiles(ref, ref > 0)
    log("reference %s: shape %s dtype %s percentiles 1/50/99 = %.0f / %.0f / %.0f (pixels > 0)" %
        (args.ref_tif, ref.shape, ref.dtype, *ref_p))
    prov["ref_tif"] = {"path": args.ref_tif, "sha256": sha256_file(args.ref_tif), "percentiles_1_50_99": ref_p}
    del ref
    t0 = time.time()
    vol = assemble(fetcher, keys, grid, region, prov)
    log("fetched %d chunk keys in %.0f s; region array %s uint8; peak RSS %.0f MB" % (len(keys), time.time() - t0, vol.shape, peak_rss_mb()))
    out8 = convert(vol, args.box, region, f, prov)
    del vol
    log("zoomed + cropped: %s uint8; peak RSS %.0f MB" % (out8.shape, peak_rss_mb()))
    m = out8.max(axis=0) > 0
    crop_p8 = percentiles_uint8_hist(out8, m, MID_LAYERS)
    crop_p = [v * 257.0 for v in crop_p8]
    rescale, reason = intensity_rule(crop_p, ref_p)
    log("crop percentiles 1/50/99 (uint8, inside mask, kept layers %d..%d) = %.1f / %.1f / %.1f; x257 = %.0f / %.0f / %.0f" %
        (MID_LAYERS[0], MID_LAYERS[1] - 1, *crop_p8, *crop_p))
    log("INTENSITY RULE: %s" % reason)
    prov["intensity"] = {"crop_layers_kept_index": list(MID_LAYERS), "crop_percentiles_uint8": crop_p8, "crop_percentiles_x257": crop_p,
                         "rescale": rescale, "reason": reason}
    asis, zrev, mask = write_folders(out8, args.out_root, args.tag, stamp, rescale, crop_p, ref_p, prov)
    log("written %s and %s (%s); mask papyrus px %d of %d; peak RSS %.0f MB" %
        (asis, zrev, prov["output"]["zrev_mode"], prov["output"]["mask_papyrus_px"], mask.size, peak_rss_mb()))
    prov["peak_rss_mb"] = peak_rss_mb()
    return prov


def selftest():
    """Synthetic 2 x 2 chunk grid (33 x 256 x 256) with a bright vertical stroke; converts a 128 x 128 box."""
    from scipy.ndimage import zoom  # noqa: F401 - import check
    import tifffile, tempfile
    shape = (33, 256, 256)
    full = np.full(shape, 120, dtype=np.uint8)     # 120 x 257 = 30840 vs ref p99 ~39600: ratio 0.78 -> no rescale
    full[16, 80:160, 100:104] = 250                # stroke in layer 16 (centre), rows 80..159, cols 100..103
    full[:, 70:78, :] = 0                          # a blank band inside the box so the mask has holes
    full[:, 128:256, 128:256] = 0                  # chunk 0/0/1/1 is all-fill: NOT stored (simulates the 404)
    chunks = {}
    for yc in range(2):
        for xc in range(2):
            if (yc, xc) == (1, 1):
                continue
            chunks["0/0/%d/%d" % (yc, xc)] = full[:, yc * 128:(yc + 1) * 128, xc * 128:(xc + 1) * 128].tobytes()
    assert len(chunks) == 3 and all(len(b) == EXPECT_BYTES for b in chunks.values())
    fetcher = DictFetcher(chunks, shape)
    tmp = tempfile.mkdtemp(prefix="segconv_selftest_")
    reftif = os.path.join(tmp, "ref.tif")
    tifffile.imwrite(reftif, (np.random.default_rng(0).integers(2000, 40000, (64, 64))).astype(np.uint16))
    args = argparse.Namespace(base_url="selftest://", box=(64, 64, 192, 192), seg_vox=7.91, train_vox=3.24, out_root=tmp,
                              tag="selftest", ref_tif=reftif, go=True, head=False, native=False, label_tif=None)
    prov = run(args, fetcher, "selftest")
    f = 7.91 / 3.24
    D, H, W = prov["output"]["shape_dhw"]
    assert (D, H, W) == (DEPTH_OUT, int(round(128 * f)), int(round(128 * f))), (D, H, W)
    assert prov["zoom_output_shape"][0] == 81, prov["zoom_output_shape"]
    assert prov["z_layers_kept"] == [8, 72], prov["z_layers_kept"]
    asis, zrev = prov["output"]["asis"], prov["output"]["zrev"]
    # stroke: source layer 16 -> zoomed layer round(16*f)=39 -> kept index 39-8=31; cols (100-64)*f=87.9..(104-64)*f=97.6
    mid = tifffile.imread(os.path.join(asis, "31.tif"))
    assert mid.dtype == np.uint16 and mid.shape == (H, W), (mid.dtype, mid.shape)
    col = np.argmax(mid.max(axis=0))
    assert 86 <= col <= 99, "stroke column %d not in 86..99" % col
    row_lo, row_hi = np.nonzero(mid.max(axis=1) > 40000)[0][[0, -1]]
    exp_lo, exp_hi = int(round((80 - 64) * f)), int(round((160 - 64) * f))
    assert abs(row_lo - exp_lo) <= 3 and abs(row_hi - exp_hi) <= 3, (row_lo, row_hi, exp_lo, exp_hi)
    far = tifffile.imread(os.path.join(asis, "00.tif"))
    assert far.max() < 40000, "stroke leaked to layer 0"
    assert prov["intensity"]["rescale"] is False, prov["intensity"]   # p99 = 120*257 = 30840 vs ref p99 ~39600: ratio 0.78 -> no rescale
    assert prov["missing_chunks"] == ["0/0/1/1"], prov["missing_chunks"]
    # the absent chunk covers source (128.., 128..) -> output rows/cols >= round((128-64)*f) = 156 must be 0 and masked out
    q = int(round((128 - 64) * f))
    assert mid[q + 2:, q + 2:].max() == 0, "absent chunk not zero-filled"
    assert mid[:10, :q - 2].min() > 0            # rows before the blank band, left of the absent chunk
    # z-reversal: zrev/00.tif must be byte-identical to asis/64.tif
    assert sha256_file(os.path.join(zrev, "00.tif")) == sha256_file(os.path.join(asis, "64.tif"))
    assert sha256_file(os.path.join(zrev, "33.tif")) == sha256_file(os.path.join(asis, "31.tif"))
    from PIL import Image
    mask = np.array(Image.open(os.path.join(asis, "mask.png")))
    ink = np.array(Image.open(os.path.join(asis, "inklabels.png")))
    assert mask.shape == (H, W) and ink.shape == (H, W) and ink.max() == 0 and mask.max() == 255
    assert mask.min() == 0 and (mask == 0).sum() > 0, "blank band should give mask holes"
    assert mask[q + 2:, q + 2:].max() == 0 and mask[:10, :q - 2].min() == 255, "mask must exclude the absent chunk"
    # histogram percentiles agree with np.percentile on a random uint8 block (within one grey level)
    rng = np.random.default_rng(1)
    blk = rng.integers(0, 256, (65, 40, 40)).astype(np.uint8)
    mm = rng.random((40, 40)) > 0.3
    hp = percentiles_uint8_hist(blk, mm, MID_LAYERS)
    npp = percentiles(blk[MID_LAYERS[0]:MID_LAYERS[1]], np.broadcast_to(mm, (MID_LAYERS[1] - MID_LAYERS[0], 40, 40)))
    assert all(abs(a - b) <= 1.0 for a, b in zip(hp, npp)), (hp, npp)
    assert sorted(os.listdir(asis)) == ["%02d.tif" % i for i in range(DEPTH_OUT)] + ["inklabels.png", "mask.png"]
    # intensity rule edges
    assert intensity_rule([0, 0, 100 * 257], [0, 0, 40000])[0] is False    # 25700/40000 = 0.64, inside [0.5, 2.0]
    assert intensity_rule([0, 0, 10 * 257], [0, 0, 40000])[0] is True
    assert intensity_rule([0, 0, 255 * 257], [0, 0, 20000])[0] is True
    assert to_uint16_slice(np.array([[0, 255]], dtype=np.uint8), False, None, None).tolist() == [[0, 65535]]
    s = to_uint16_slice(np.array([[10, 100]], dtype=np.uint8), True, [10 * 257, 0, 100 * 257], [1000, 0, 40000])
    assert s.tolist() == [[1000, 40000]], s.tolist()
    # ---- native mode with a pseudo-label (rev3): synthetic level-0 map, same grid, stroke at the same place as the volume stroke
    lab_full = np.zeros((256, 256), dtype=np.uint8)
    lab_full[80:160, 100:104] = 230                 # ink where the volume stroke is -> registration peak at (0, 0)
    lab_full[64:134, 64:80] = 90                    # a below-threshold patch inside the box (must NOT become ink)
    import io
    buf = io.BytesIO(); tifffile.imwrite(buf, lab_full); chunks["label:ok"] = buf.getvalue()
    bad = io.BytesIO(); tifffile.imwrite(bad, lab_full[:200, :]); chunks["label:badshape"] = bad.getvalue()
    # native-test volume: no blank band, stroke present in layers 12..20 (the registration layers), absent chunk restored
    full2 = np.full(shape, 120, dtype=np.uint8)
    full2[12:21, 80:160, 100:104] = 250
    chunks = {k: v for k, v in chunks.items() if k.startswith("label:")}
    for yc in range(2):
        for xc in range(2):
            chunks["0/0/%d/%d" % (yc, xc)] = full2[:, yc * 128:(yc + 1) * 128, xc * 128:(xc + 1) * 128].tobytes()
    fetcher = DictFetcher(chunks, shape)
    argsn = argparse.Namespace(base_url="selftest://", box=(64, 64, 192, 192), seg_vox=7.91, train_vox=3.24, out_root=tmp,
                               tag="selftestnat", ref_tif=reftif, go=True, head=False, native=True, label_tif="label:ok")
    provn = run(argsn, fetcher, "selftest")
    Dn, Hn, Wn = provn["output"]["shape_dhw"]
    assert (Dn, Hn, Wn) == (32, 128, 128), (Dn, Hn, Wn)
    assert provn["native_layers_kept"] == [1, 32] and provn["zoom_factor_zyx"] == [1.0, 1.0, 1.0]
    dn = provn["output"]["native"]
    assert sorted(os.listdir(dn)) == ["%02d.tif" % i for i in range(32)] + ["inklabels.png", "label_raw.png", "mask.png"], sorted(os.listdir(dn))
    t15 = tifffile.imread(os.path.join(dn, "15.tif"))        # file 15 = source layer 16 (the stroke layer)
    assert t15.dtype == np.uint16 and t15[50, 37] == 250 * 257 and t15[20, 20] == 120 * 257, (t15[50, 37], t15[20, 20])
    t00 = tifffile.imread(os.path.join(dn, "00.tif"))        # file 00 = source layer 1, no stroke
    assert t00[50, 37] == 120 * 257
    ink = np.array(Image.open(os.path.join(dn, "inklabels.png")))
    assert ink[16:96, 36:40].min() == 255 and ink[0:6, 0:6].max() == 0 and ink.max() == 255, "pseudo-label threshold wrong"
    raw = np.array(Image.open(os.path.join(dn, "label_raw.png")))
    assert raw[20, 38] == 230 and raw[2, 2] == 90
    assert provn["label"]["threshold"] == LABEL_THR and provn["label"]["shape_hw"] == [256, 256]
    assert (provn["registration"]["best_dy"], provn["registration"]["best_dx"]) == (0, 0), provn["registration"]
    assert abs(provn["output"]["ink_share_in_mask"] - (80 * 4) / (128 * 128)) < 0.005, provn["output"]["ink_share_in_mask"]
    # shape mismatch must STOP
    argsb = argparse.Namespace(**{**vars(argsn), "tag": "selftestbad", "label_tif": "label:badshape"})
    try:
        run(argsb, fetcher, "selftest"); raise AssertionError("bad-shape label was not refused")
    except RuntimeError as e:
        assert "cannot be aligned" in str(e), str(e)
    # ---- rev4: 31-layer source (PHerc0800 shape), keep 0..30, pad to 32 by repeating layer 30; no label
    global EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO
    keep = (EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO)
    try:
        EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO = (31, 128, 128), 31 * 128 * 128, (0, 31), 32
        shape31 = (31, 256, 256)
        full3 = np.full(shape31, 100, dtype=np.uint8)
        full3[30, :, :] = 200                           # last layer distinct -> the padded copy must equal it
        full3[15, 80:160, 100:104] = 250
        chunks31 = {}
        for yc in range(2):
            for xc in range(2):
                chunks31["0/0/%d/%d" % (yc, xc)] = full3[:, yc * 128:(yc + 1) * 128, xc * 128:(xc + 1) * 128].tobytes()
        f31 = DictFetcher(chunks31, shape31)
        argsp = argparse.Namespace(base_url="selftest://", box=(64, 64, 192, 192), seg_vox=8.64, train_vox=3.24, out_root=tmp,
                                   tag="selftestpad", ref_tif=reftif, go=True, head=False, native=True, label_tif=None)
        provp = run(argsp, f31, "selftest")
        assert provp["output"]["shape_dhw"] == [32, 128, 128], provp["output"]["shape_dhw"]
        assert provp["native_layers_kept"] == [0, 30] and provp["pad_layers"]["copies"] == 1 and provp["pad_layers"]["source_layer_repeated"] == 30
        dp = provp["output"]["native"]
        assert sorted(os.listdir(dp)) == ["%02d.tif" % i for i in range(32)] + ["inklabels.png", "mask.png"], sorted(os.listdir(dp))
        t30 = tifffile.imread(os.path.join(dp, "30.tif")); t31 = tifffile.imread(os.path.join(dp, "31.tif"))
        assert t30[20, 20] == 200 * 257 and np.array_equal(t30, t31), "padded layer 31 must equal layer 30"
        t15 = tifffile.imread(os.path.join(dp, "15.tif")); assert t15[50, 37] == 250 * 257
        assert np.array(Image.open(os.path.join(dp, "inklabels.png"))).max() == 0
        # a 33-layer chunk against a 31-layer expectation must be refused
        try:
            read_zarray(DictFetcher(chunks31, (33, 256, 256))); raise AssertionError("33-layer shape accepted with --layers 31")
        except RuntimeError as e:
            assert "layers" in str(e) or "shape" in str(e), str(e)
    finally:
        EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO = keep
    # ---- rev5 (plan C7): 28-layer source (PHerc0139 shape), window 6..22 (16 kept), finer label map downsampled, M1 mask, cut stop
    global LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP, LABEL_R, LABEL_VOX
    keep5 = (EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO, LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP)
    try:
        EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO = (28, 128, 128), 28 * 128 * 128, (6, 22), 0
        assert reg_window(16) == (4, 12) and NATIVE_LAYERS[0] + 4 == 10 and NATIVE_LAYERS[0] + 11 == 17, "REG window 4..11 must be source 10..17 for the 6..22 window"
        assert reg_window(32) == (12, 20)
        shape28 = (28, 256, 256)
        full5 = np.full(shape28, 110, dtype=np.uint8)
        full5[10:18, 90:150, 100:104] = 250            # stroke in source layers 10..17 (= the registration layers), rows 90..149, cols 100..103
        full5[:, 0:256, 200:256] = 0                   # empty band on the right: the sheet's papyrus ends at x=200 (inside the volume)
        full5[:, 10:30, 220:240] = 90                  # a detached sliver inside the empty band (M1 must drop it)
        chunks5 = {}
        for yc in range(2):
            for xc in range(2):
                chunks5["0/0/%d/%d" % (yc, xc)] = full5[:, yc * 128:(yc + 1) * 128, xc * 128:(xc + 1) * 128].tobytes()
        # finer label map: 3.9x per axis, with a NON-integer ratio (998 x 1000 -> 256 x 256), stroke at the same place scaled
        Hs, Ws = 998, 1000
        fy, fx = Hs / 256.0, Ws / 256.0
        labf = np.zeros((Hs, Ws), dtype=np.uint8)
        labf[int(round(90 * fy)):int(round(150 * fy)), int(round(100 * fx)):int(round(104 * fx))] = 240
        labf[int(round(70 * fy)):int(round(80 * fy)), int(round(70 * fx)):int(round(80 * fx))] = 100      # below threshold after the mean
        import io
        bf = io.BytesIO(); tifffile.imwrite(bf, labf); chunks5["label:fine"] = bf.getvalue()
        f5 = DictFetcher(chunks5, shape28)
        # (a) downsample ON, plain mask, box inside the papyrus (training-box case): stroke lands within 1 px; share matches
        LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP = True, False, False
        LABEL_VOX = 2.399; LABEL_R = 9.362 / 2.399                      # rev5b: origin rule (256 x 3.9025 = 999 >= 998 fine rows: last coarse row is padding)
        args5 = argparse.Namespace(base_url="selftest://", box=(64, 64, 192, 192), seg_vox=9.362, train_vox=3.24, out_root=tmp,
                                   tag="selftestc7", ref_tif=reftif, go=True, head=False, native=True, label_tif="label:fine")
        prov5 = run(args5, f5, "selftest")
        assert prov5["label"]["mapping"].startswith("origin-anchored R=3.9025"), prov5["label"]["mapping"]
        assert prov5["output"]["shape_dhw"] == [16, 128, 128] and prov5["native_layers_kept"] == [6, 21], prov5["output"]["shape_dhw"]
        assert prov5["label"]["downsampled"] is True and prov5["label"]["shape_hw"] == [256, 256] and prov5["label"]["source_shape_hw"] == [998, 1000]
        d5 = prov5["output"]["native"]
        ink5 = np.array(Image.open(os.path.join(d5, "inklabels.png")))
        ys, xs = np.nonzero(ink5)
        assert abs(ys.min() - (90 - 64)) <= 1 and abs(ys.max() - (149 - 64)) <= 1 and abs(xs.min() - (100 - 64)) <= 1 and abs(xs.max() - (103 - 64)) <= 1, (ys.min(), ys.max(), xs.min(), xs.max())
        assert ink5[70 - 64:80 - 64, 70 - 64:80 - 64].max() == 0, "sub-threshold patch must not be ink after the area mean"
        raw5 = np.array(Image.open(os.path.join(d5, "label_raw.png")))
        assert 230 <= raw5[100 - 64, 101 - 64] <= 240 and 95 <= raw5[75 - 64, 75 - 64] <= 100, (raw5[36, 37], raw5[11, 11])
        reg = prov5["registration"]
        assert reg["window_layers"] == [4, 11] and reg["source_layers"] == [10, 17], reg
        assert (reg["best_dy"], reg["best_dx"]) == (0, 0), reg
        t4 = tifffile.imread(os.path.join(d5, "04.tif"))        # file 04 = source layer 10 (first stroke layer)
        assert t4[100 - 64, 101 - 64] == 250 * 257 and t4[5, 5] == 110 * 257
        t3 = tifffile.imread(os.path.join(d5, "03.tif")); assert t3[100 - 64, 101 - 64] == 110 * 257, "source layer 9 has no stroke"
        # area_mean_to exactness: constant map stays constant; mean of a 2x2 block is exact
        assert area_mean_to(np.full((20, 30), 77, np.uint8), (10, 15)).min() == 77
        q = np.zeros((4, 4), np.uint8); q[0, 0] = 200
        assert area_mean_to(q, (2, 2)).tolist() == [[50, 0], [0, 0]]
        # rev5b ORIGIN rule vs EXTENT rule (Sonnet 310): fine 1000 x 1000, coarse 250 x 250, R = 4.5 -> the coarse grid spans 1125 fine
        # rows. A square at fine 450..458 lands at coarse 100..101 under ORIGIN (450/4.5 = 100, 458/4.5 = 101.8) but at 112..114 under
        # EXTENT (1000/250 = 4: 450/4 = 112.5, 458/4 = 114.5). Values: block (100,100) = fine [450,454.5->454) x same = all 200.
        fo = np.zeros((1000, 1000), np.uint8); fo[450:459, 450:459] = 200
        o = area_mean_to(fo, (250, 250), R=4.5); e = area_mean_to(fo, (250, 250))
        yo, xo = np.nonzero(o > 0); ye, xe = np.nonzero(e > 0)
        assert (yo.min(), yo.max(), xo.min(), xo.max()) == (100, 101, 100, 101), (yo.min(), yo.max(), xo.min(), xo.max())
        assert (ye.min(), ye.max()) == (112, 114), (ye.min(), ye.max())
        assert o[100, 100] == 200 and o[101, 101] == 200 and o[102, 102] == 0, (o[100, 100], o[101, 101], o[102, 102])
        # past-end padding: a square at fine rows 990..999, cols 0..8 -> coarse rows 220..222 (990/4.5 = 220, 999/4.5 = 222), cols 0..1;
        # every coarse row >= 223 lies beyond the fine map and must be 0 (padding), never an error
        fo2 = np.zeros((1000, 1000), np.uint8); fo2[990:1000, 0:9] = 200
        o2 = area_mean_to(fo2, (250, 250), R=4.5)
        assert o2[220:223, 0:2].min() == 200 and o2[:220].max() == 0 and o2[223:].max() == 0 and o2[:, 2:].max() == 0, "origin rule: past-end blocks must be 0"
        assert area_mean_to(np.full((39, 39), 9, np.uint8), (10, 10), R=3.9025).tolist()[-1][-1] == 9   # 10 x 3.9025 = 39.0 exactly reaches the end
        assert area_mean_to(np.full((30, 30), 9, np.uint8), (10, 10), R=3.9025)[-1, -1] == 0           # coarse grid overshoots the map: padding = 0
        # rev5c (Sonnet 314 M1): a PARTIAL last block keeps its full content: 10x10 map, 4x4 coarse at R 4 -> blocks [8,10) are full 100
        assert area_mean_to(np.full((10, 10), 100, np.uint8), (4, 4), R=4.0).tolist() == [[100, 100, 100, 0], [100, 100, 100, 0], [100, 100, 100, 0], [0, 0, 0, 0]]
        # (b) M1 mask + cut stop on a TARGET-style box: box reaches the sheet border on the left/top (x0=0, y0=0), ends at x1=192 inside the
        #     volume but beyond the papyrus edge (200 > 192 -> the component DOES touch x1=192, an interior edge) -> must STOP
        LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP = False, True, True
        argsc = argparse.Namespace(base_url="selftest://", box=(0, 0, 192, 192), seg_vox=9.362, train_vox=3.24, out_root=tmp,
                                   tag="selftestcut", ref_tif=reftif, go=True, head=False, native=True, label_tif=None)
        try:
            run(argsc, f5, "selftest"); raise AssertionError("cut box was not refused")
        except RuntimeError as e:
            assert "CUT STOP" in str(e) and "right" in str(e) and "top" not in str(e) and "left" not in str(e), str(e)
        # (c) same sheet, box to the volume border on the right (x1 = 256 = W): the papyrus ends at 200 inside the box, so no interior
        #     edge is touched; bottom edge y1 = 192 < H is interior BUT the component does touch it (papyrus spans all rows) -> STOP again
        argsc2 = argparse.Namespace(**{**vars(argsc), "tag": "selftestcut2", "box": (0, 0, 256, 192)})
        try:
            run(argsc2, f5, "selftest"); raise AssertionError("bottom-cut box was not refused")
        except RuntimeError as e:
            assert "bottom" in str(e) and "right" not in str(e), str(e)
        # (d) whole-sheet box (all four edges on the sheet border): passes; M1 drops the sliver (2 components -> 1 kept)
        argsc3 = argparse.Namespace(**{**vars(argsc), "tag": "selftestcut3", "box": (0, 0, 256, 256)})
        provc = run(argsc3, f5, "selftest")
        assert provc["mask"]["components"] == 2 and provc["mask"]["cut_edges"] == [], provc["mask"]
        mk = np.array(Image.open(os.path.join(provc["output"]["native"], "mask.png")))
        assert mk[:, :200].min() == 255 and mk[:, 200:].max() == 0, "M1 mask must keep the papyrus body and drop the sliver"
        assert abs(provc["mask"]["share_lcc"] - 200 / 256) < 1e-6 and provc["mask"]["share_any"] > provc["mask"]["share_lcc"]
        assert provc["registration"]["status"].startswith("n/a") and provc["registration"]["source_layers"] == [10, 17]
        # (e) ink-share warning: a map that is ink everywhere in the box -> share 1.0 -> WARNING line logged (not a stop)
        LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP = False, False, False
        chunks5["label:dense"] = (lambda b: (tifffile.imwrite(b, np.full((256, 256), 200, np.uint8)), b.getvalue())[1])(io.BytesIO())
        argsd = argparse.Namespace(**{**vars(args5), "tag": "selftestdense", "label_tif": "label:dense"})
        n0 = len(_LOG)
        provd = run(argsd, f5, "selftest")
        assert provd["output"]["ink_share_in_mask"] > 0.99 and any("WARNING ink share" in l for l in _LOG[n0:]), "ink-share warning missing"
    finally:
        EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO, LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP = keep5
    # (rev6) zarr level: keys and .zarray come from "<level>/..." and the chunk data lands where level 0's would
    global ZLEVEL
    keep6 = (ZLEVEL, EXPECT_CHUNK, EXPECT_BYTES)
    try:
        ZLEVEL = 2; EXPECT_CHUNK = (5, 128, 128); EXPECT_BYTES = 5 * 128 * 128
        g = np.random.default_rng(6).integers(1, 255, (5, 256, 384), dtype=np.uint8)
        ch = {"2/0/%d/%d" % (yc, xc): g[:, yc * 128:(yc + 1) * 128, xc * 128:(xc + 1) * 128].tobytes() for yc in range(2) for xc in range(3)}
        f6 = DictFetcher(ch, (5, 256, 384))
        sh6, _ = read_zarray(f6)
        assert sh6 == (5, 256, 384)
        k6, grid6, reg6 = chunk_keys_for((150, 20, 300, 200), sh6)
        assert all(k.startswith("2/0/") for k in k6) and len(k6) == 4, k6
        prov6 = {"chunks": []}
        sub6 = assemble(f6, k6, grid6, reg6, prov6)
        ya, yb, xa, xb = reg6
        assert np.array_equal(sub6, g[:, ya:yb, xa:xb]), "level-2 assembly mismatch"
        log("SELFTEST (rev6): level 2 keys %s ... region %s assembled exactly" % (k6[0], reg6))
    finally:
        ZLEVEL, EXPECT_CHUNK, EXPECT_BYTES = keep6
    log("SELFTEST PASSED (%s)" % tmp)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base_url", default=DEFAULT_BASE, help="zarr root (level-0 .zarray at <base>/0/.zarray)")
    ap.add_argument("--box", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), help="crop in level-0 segment pixels, half-open")
    ap.add_argument("--seg_vox", type=float, default=7.91, help="segment voxel pitch, um (from .zattrs; Sonnet 197)")
    ap.add_argument("--train_vox", type=float, default=3.24, help="training fragments' pitch, um (meta.json; Sonnet 200)")
    ap.add_argument("--out_root", default="/workspace/VesuviusUNET")
    ap.add_argument("--tag", default="w095", help="segment tag used in the output folder names")
    ap.add_argument("--ref_tif", default="/workspace/VesuviusUNET/data_frag4/32.tif", help="reference fragment slice for the intensity rule")
    ap.add_argument("--native", action="store_true", help="C3: no resampling, layers 1..32, one folder, no intensity rule")
    ap.add_argument("--layers", type=int, default=33, help="rev4: layer count of the source zarr (chunk z); 33 for PHerc0172, 31 for PHerc0800")
    ap.add_argument("--native_layers", type=int, nargs=2, metavar=("A", "B"), default=None,
                    help="rev4: native mode keeps source layers [A, B); default 1 33 (C3); PHerc0800: 0 31")
    ap.add_argument("--pad_to", type=int, default=0, help="rev4: native mode, pad the kept stack to this depth by repeating the last kept layer (0 = off)")
    ap.add_argument("--label_tif", default=None, help="C3: URL/path of the segment's published level-0 map (uint8); inklabels = map >= 128")
    ap.add_argument("--label_downsample", action="store_true", help="rev5: area-mean a finer-grid map onto the volume's exact (H, W) before the box and the threshold")
    ap.add_argument("--label_vox", type=float, default=None, help="rev5b: the finer map's pixel pitch (um); with --label_downsample the area mean is ORIGIN-ANCHORED with R = seg_vox/label_vox")
    ap.add_argument("--label_mode", choices=("origin", "extent"), default="origin", help="rev5b: origin (default, needs --label_vox) or extent (the rev5 linspace rule, record only)")
    ap.add_argument("--mask_lcc", action="store_true", help="rev5 M1: mask = largest 4-connected component of any-non-zero (targets)")
    ap.add_argument("--cut_stop", action="store_true", help="rev5 P1: with --mask_lcc, STOP if the component touches a box edge inside the sheet")
    ap.add_argument("--head", action="store_true", help="dry run + HEAD the first chunk")
    ap.add_argument("--go", action="store_true", help="download and write (after Sonnet's review and Pedro's word)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--level", type=int, default=0, help="rev6 (plan C8): zarr multiscale level to read; --box and --seg_vox are in THAT level's pixels/pitch")
    ap.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M", time.gmtime()))
    args = ap.parse_args()
    global _LOGF
    if args.selftest:
        return selftest()
    if not args.box:
        ap.error("--box X0 Y0 X1 Y1 is required (or --selftest)")
    args.box = tuple(args.box)
    global EXPECT_CHUNK, EXPECT_BYTES, NATIVE_LAYERS, PAD_TO, ZLEVEL
    ZLEVEL = args.level
    if args.layers != 33:
        EXPECT_CHUNK = (args.layers, 128, 128)
        EXPECT_BYTES = args.layers * 128 * 128
    if args.native_layers:
        if not (0 <= args.native_layers[0] < args.native_layers[1] <= args.layers):
            ap.error("--native_layers must satisfy 0 <= A < B <= --layers")
        NATIVE_LAYERS = tuple(args.native_layers)
    if args.pad_to:
        if not args.native:
            ap.error("--pad_to is only defined with --native")
        PAD_TO = args.pad_to
    global LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP, LABEL_R, LABEL_VOX
    LABEL_DOWNSAMPLE, MASK_LCC, CUT_STOP = args.label_downsample, args.mask_lcc, args.cut_stop
    LABEL_VOX = args.label_vox
    if args.label_downsample and args.label_mode == "origin":
        if not args.label_vox:
            ap.error("--label_downsample needs --label_vox (origin-anchored rule, rev5b); --label_mode extent is the old rule, record only")
        LABEL_R = args.seg_vox / args.label_vox
    else:
        LABEL_R = None
    if args.cut_stop and not args.mask_lcc:
        ap.error("--cut_stop is only defined with --mask_lcc")
    if (args.label_downsample or args.mask_lcc) and not args.native:
        ap.error("--label_downsample / --mask_lcc are only defined with --native")
    os.makedirs(args.out_root, exist_ok=True)
    logp = os.path.join(args.out_root, "segconv_%s_%s.log" % (args.tag, args.stamp))
    _LOGF = open(logp, "a")
    if args.label_tif and not args.native:
        ap.error("--label_tif is only defined with --native (same grid, no resampling)")
    log("=== scroll_segment_convert rev6 [fable] zarr level %d;" % ZLEVEL + " stamp %s mode %s%s; code sha256 %s ===" %
        (args.stamp, "GO" if args.go else "DRY RUN", " NATIVE" if args.native else " RESAMPLED", sha256_file(os.path.abspath(__file__))[:16]))
    if args.label_tif:
        log("PSEUDO-LABELS: inklabels.png = (published TimeSformer map >= %d); scores against it measure agreement with that model, not ink truth." % LABEL_THR)
    else:
        log("NO LABELS: inklabels.png is all-zero; every cross_infer metric line on these folders is meaningless.")
    fetcher = HttpFetcher(args.base_url)
    prov = run(args, fetcher, args.stamp)
    if args.go:
        pj = os.path.join(args.out_root, "segconv_%s_%s_provenance.json" % (args.tag, args.stamp))
        with open(pj, "w") as f:
            json.dump(prov, f, indent=1, sort_keys=True)
        log("provenance written %s (sha256 %s)" % (pj, sha256_file(pj)[:16]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:   # noqa: BLE001 - last-resort reporting; traceback also printed
        import traceback
        traceback.print_exc()
        log("STOPPED: %s" % e)
        sys.exit(2)
