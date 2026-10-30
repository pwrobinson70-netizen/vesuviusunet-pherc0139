#!/usr/bin/env python3
"""
segprep_c5_fable_25102026_rev2.py  (rev1, [fable], 24 Oct 2026) -- plan C5 rev2 items C5-1 and C5-2: FOLDER -> FOLDER preparation.
Reads an existing VesuviusUNET native folder (NN.tif uint16 = uint8 x 257, mask.png, inklabels.png, optional label_raw.png,
written by scroll_segment_convert rev3/rev4) and writes a new folder data_seg_<tag>_<stamp>_native_rev5 (the suffix does NOT
match the c3/c4 globs 'data_seg_<tag>_*_native', Sonnet 248 m3) with:
  C5-1  physical-scale resampling: x and y zoomed by --xy_zoom (= seg_vox / 7.91; 1.0 for PHerc0172, 8.64/7.91 = 1.0923 for
        PHerc0800), volume bilinear per layer, mask / inklabels / label_raw nearest; optional --z_zoom (same factor on the REAL
        source layers, padded copies dropped first, then a 32-layer window centred on the stack) - use it only when the
        segment's layer step equals its voxel size (plan C5 rev2 Q5; read it from the .zattrs printed in the C4 provenance,
        do not assume). The decision and the factors are written into the provenance.
  C5-2  per-SEGMENT intensity normalisation: y = (x - median) * (S / IQR) + L on uint8 units (x = tif / 257), where median and
        IQR (p75 - p25) are exact 256-bin-histogram statistics over ALL in-mask voxels of the REAL layers of THIS folder, and
        L, S are the fixed targets (--L --S, = the median over the four C3 training crops of their own median and IQR, read
        with --stats first). Output written as uint16 = round(y) x 257 after clipping y to [0, 255]. The clipped fraction
        (in-mask voxels pushed below 0 or above 255) is recorded; above --max_clip (default 0.005 = 0.5 %) the run STOPS
        before writing anything (Sonnet 248 m2). Order: zoom first, then normalise (statistics are taken on the zoomed stack,
        so the written folder's own median/IQR equal L/S by construction; --stats on the output verifies it).
NO network. Nothing in the source folder is touched. Usage (Linux shell, pod):
  python3 -I segprep_c5_fable_24102026.py --stats data_seg_w088_20261022_2218_native [more folders]   -> median/IQR per folder
  python3 -I segprep_c5_fable_24102026.py --src data_seg_w088_20261022_2218_native --tag w088 --L 150 --S 40 [--xy_zoom 1.0923]
                                          [--z_zoom] [--go]           (without --go: dry run, statistics and output shape only)
  python3 -I segprep_c5_fable_24102026.py --selftest
"""
import argparse, hashlib, json, os, sys, time
import numpy as np

DEPTH_OUT = 32                 # rev2: set by --depth (C7 runs at 16; the C5 control at 32)
PAD_MODE = "last"              # rev2: "last" = repeat the last real layer (rev1 behaviour); "symmetric" = half below (copies of the first), half above
_LOGF = None


def log(m):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), m)
    print(line, flush=True)
    if _LOGF:
        _LOGF.write(line + "\n"); _LOGF.flush()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def read_folder(src):
    """Returns vol8 (D, H, W) uint8 (tif / 257, exact for the x257 encoding), mask bool (H, W), ink uint8, label_raw uint8 or None,
    plus the list of real (non-padded) layer indices read from the sibling provenance json when present."""
    import tifffile
    from PIL import Image
    tifs = sorted(f for f in os.listdir(src) if f.endswith(".tif") and f[:-4].isdigit())
    if not tifs:
        raise RuntimeError("no NN.tif in %s" % src)
    layers = []
    for f in tifs:
        a = tifffile.imread(os.path.join(src, f))
        if a.dtype != np.uint16:
            raise RuntimeError("%s/%s is %s, expected uint16" % (src, f, a.dtype))
        if int(a.max()) % 257 != 0 or (a % 257).any():
            raise RuntimeError("%s/%s is not a uint8 x 257 encoding (rev3/rev4 native folders only)" % (src, f))
        layers.append((a // 257).astype(np.uint8))
    vol = np.stack(layers, axis=0)
    mask = np.array(Image.open(os.path.join(src, "mask.png")).convert("L")) > 0
    ink = np.array(Image.open(os.path.join(src, "inklabels.png")).convert("L"))
    lr = os.path.join(src, "label_raw.png")
    label_raw = np.array(Image.open(lr).convert("L")) if os.path.exists(lr) else None
    if mask.shape != vol.shape[1:] or ink.shape != vol.shape[1:]:
        raise RuntimeError("mask/inklabels shape %s %s != volume %s" % (mask.shape, ink.shape, vol.shape[1:]))
    real = list(range(vol.shape[0]))
    prov_src = None
    root, name = os.path.split(os.path.abspath(src.rstrip("/")))
    for f in os.listdir(root):
        if f.startswith("segconv_") and f.endswith("_provenance.json"):
            try:
                with open(os.path.join(root, f)) as fh:
                    pj = json.load(fh)
                if pj.get("output", {}).get("native", "").rstrip("/").endswith(name):
                    prov_src = f
                    pl = pj.get("pad_layers")
                    if pl:
                        real = list(range(vol.shape[0] - int(pl["copies"])))
                    break
            except Exception:   # noqa: BLE001 - provenance is informational for the pad only
                pass
    return vol, mask, ink, label_raw, real, prov_src


def hist_stats(vol8, mask, real):
    """Exact median and IQR (p75 - p25) of in-mask uint8 voxels over the real layers, by 256-bin histogram (lower-rank value)."""
    hist = np.zeros(256, dtype=np.int64)
    for i in real:
        hist += np.bincount(vol8[i][mask], minlength=256)
    n = int(hist.sum())
    if n == 0:
        raise RuntimeError("empty mask")
    cum = np.cumsum(hist)
    def q(p):
        rank = (p / 100.0) * (n - 1)
        return float(np.searchsorted(cum, int(np.floor(rank)) + 1))
    p25, p50, p75 = q(25), q(50), q(75)
    return {"n_voxels": n, "p25": p25, "median": p50, "p75": p75, "iqr": p75 - p25}


def zoom_stack(vol8, mask, ink, label_raw, real, fxy, fz):
    """Zoom the REAL layers; x,y by fxy (volume order 1, masks order 0); z by fz on the real stack then a DEPTH_OUT window centred.
    Without z zoom the padded layers are rebuilt by repeating the last real layer (as rev4 did) so the stack stays DEPTH_OUT."""
    from scipy.ndimage import zoom
    v = vol8[real]
    if fxy != 1.0:
        v = zoom(v, (1.0, fxy, fxy), order=1, mode="nearest", prefilter=False, grid_mode=False)
        mask = zoom(mask.astype(np.uint8), (fxy, fxy), order=0, mode="nearest", grid_mode=False) > 0
        ink = zoom(ink, (fxy, fxy), order=0, mode="nearest", grid_mode=False)
        if label_raw is not None:
            label_raw = zoom(label_raw, (fxy, fxy), order=0, mode="nearest", grid_mode=False)
    assert v.dtype == np.uint8, v.dtype
    zinfo = {"fz": fz, "real_layers_in": len(real)}
    if fz != 1.0:
        v = zoom(v, (fz, 1.0, 1.0), order=1, mode="nearest", prefilter=False, grid_mode=False)
        zinfo["layers_after_zoom"] = int(v.shape[0])
        if v.shape[0] < DEPTH_OUT:
            raise RuntimeError("z zoom gave %d layers < %d" % (v.shape[0], DEPTH_OUT))
        zs = (v.shape[0] - DEPTH_OUT) // 2
        v = v[zs:zs + DEPTH_OUT]
        zinfo["window_kept"] = [zs, zs + DEPTH_OUT - 1]
        zinfo["pad_layers"] = 0
    else:
        if v.shape[0] > DEPTH_OUT:
            raise RuntimeError("%d real layers > %d; refuse to drop layers silently" % (v.shape[0], DEPTH_OUT))
        pad = DEPTH_OUT - v.shape[0]
        below = 0
        if pad:
            if PAD_MODE == "symmetric":
                below, above = pad // 2, pad - pad // 2
                v = np.concatenate([np.repeat(v[:1], below, axis=0), v, np.repeat(v[-1:], above, axis=0)], axis=0)
            else:
                v = np.concatenate([v, np.repeat(v[-1:], pad, axis=0)], axis=0)
        zinfo["pad_layers"] = int(pad); zinfo["pad_mode"] = PAD_MODE; zinfo["pad_below"] = int(below)
        zinfo["window_kept"] = [0, DEPTH_OUT - 1]
    if zinfo.get("pad_below"):
        real_out = list(range(zinfo["pad_below"], zinfo["pad_below"] + len(real)))
    else:
        real_out = list(range(DEPTH_OUT - zinfo["pad_layers"]))
    return np.ascontiguousarray(v), mask, ink, label_raw, real_out, zinfo


def normalise(vol8, mask, real, L, S, max_clip):
    """y = (x - med) * (S / iqr) + L on uint8 units over the WHOLE stack (padded copies get the same map). Returns uint16 x257, stats."""
    st = hist_stats(vol8, mask, real)
    if st["iqr"] <= 0:
        raise RuntimeError("IQR is 0 inside the mask; cannot normalise")
    gain = float(S) / st["iqr"]
    offset = float(L) - st["median"] * gain
    y = vol8.astype(np.float32) * np.float32(gain) + np.float32(offset)
    inmask = y[:, mask][np.array(real)] if len(real) < vol8.shape[0] else y[:, mask]
    clipped = float(((inmask < 0) | (inmask > 255)).mean())
    st.update({"L": float(L), "S": float(S), "gain": gain, "offset": offset, "clipped_fraction_in_mask": clipped, "max_clip": max_clip})
    if clipped > max_clip:
        raise RuntimeError("clipped fraction %.4f > %.4f (L/S choice wrong for this segment); nothing written" % (clipped, max_clip))
    y16 = (np.clip(np.rint(y), 0, 255).astype(np.uint16) * np.uint16(257))
    y16[:, ~mask] = 0
    return y16, st


def write_folder(out_dir, y16, mask, ink, label_raw):
    import tifffile
    from PIL import Image
    if os.path.exists(out_dir):
        raise RuntimeError("refusing to overwrite %s" % out_dir)
    os.makedirs(out_dir)
    files = {}
    for i in range(y16.shape[0]):
        p = os.path.join(out_dir, "%02d.tif" % i)
        tifffile.imwrite(p, y16[i], photometric="minisblack")
        files["%02d.tif" % i] = sha256_file(p)
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(os.path.join(out_dir, "mask.png"))
    Image.fromarray(((ink > 0).astype(np.uint8) * 255), mode="L").save(os.path.join(out_dir, "inklabels.png"))
    if label_raw is not None:
        Image.fromarray(label_raw.astype(np.uint8), mode="L").save(os.path.join(out_dir, "label_raw.png"))
        files["label_raw.png"] = sha256_file(os.path.join(out_dir, "label_raw.png"))
    files["mask.png"] = sha256_file(os.path.join(out_dir, "mask.png"))
    files["inklabels.png"] = sha256_file(os.path.join(out_dir, "inklabels.png"))
    return files


def prep(src, tag, stamp, L, S, fxy, z_zoom, go, out_root, max_clip):
    t0 = time.time()
    vol, mask, ink, label_raw, real, prov_src = read_folder(src)
    log("source %s: %s uint8 (from uint16 x257), real layers %d..%d%s, mask px %d of %d, ink px %d, label_raw %s; provenance %s" %
        (src, vol.shape, real[0], real[-1], "" if len(real) == vol.shape[0] else " (+%d padded copies)" % (vol.shape[0] - len(real)),
         int(mask.sum()), mask.size, int((ink > 0).sum()), "yes" if label_raw is not None else "none", prov_src))
    st_in = hist_stats(vol, mask, real)
    log("source stats (in mask, real layers): median %.1f IQR %.1f (p25 %.1f p75 %.1f) over %d voxels" % (st_in["median"], st_in["iqr"], st_in["p25"], st_in["p75"], st_in["n_voxels"]))
    fz = fxy if z_zoom else 1.0
    Hn, Wn = int(round(vol.shape[1] * fxy)), int(round(vol.shape[2] * fxy))
    log("plan: xy zoom %.4f -> %d x %d; z zoom %s; normalise to L %.1f S %.1f; out %s/data_seg_%s_%s_native_rev5" %
        (fxy, Hn, Wn, ("%.4f on %d real layers -> window %d" % (fz, len(real), DEPTH_OUT)) if z_zoom else "off (pad as source)", L, S, out_root, tag, stamp))
    prov = {"script": os.path.basename(__file__), "code_sha256": sha256_file(os.path.abspath(__file__)), "stamp": stamp, "source_folder": os.path.abspath(src),
            "source_provenance": prov_src, "source_shape_dhw": list(vol.shape), "source_real_layers": [real[0], real[-1]], "source_stats": st_in,
            "xy_zoom": fxy, "z_zoom": bool(z_zoom), "target": {"L": L, "S": S}, "rule": "y = (x - median) * (S / IQR) + L on uint8 units; uint16 = round(clip(y,0,255)) * 257; zoom before normalise"}
    if not go:
        log("DRY RUN: nothing written. Re-run with --go on Pedro's word.")
        return prov
    v, mask2, ink2, lr2, real2, zinfo = zoom_stack(vol, mask, ink, label_raw, real, fxy, fz)
    del vol
    prov["zoom"] = zinfo
    y16, st = normalise(v, mask2, real2, L, S, max_clip)
    prov["normalisation"] = st
    log("after zoom %s; stats before normalise: median %.1f IQR %.1f; gain %.4f offset %.2f; clipped %.5f (limit %.4f)" %
        (v.shape, st["median"], st["iqr"], st["gain"], st["offset"], st["clipped_fraction_in_mask"], max_clip))
    out_dir = os.path.join(out_root, "data_seg_%s_%s_native_rev5" % (tag, stamp))
    files = write_folder(out_dir, y16, mask2, ink2, lr2)
    chk = hist_stats((y16 // 257).astype(np.uint8), mask2, real2)
    prov["output"] = {"folder": out_dir, "shape_dhw": list(y16.shape), "mask_papyrus_px": int(mask2.sum()), "ink_px": int((ink2 > 0).sum()),
                      "stats_check": chk, "files_sha256": files, "real_layers": [real2[0], real2[-1]]}
    log("written %s: %s; output stats median %.1f IQR %.1f (targets %.1f / %.1f); %d files; %.0f s" %
        (out_dir, y16.shape, chk["median"], chk["iqr"], L, S, len(files), time.time() - t0))
    if abs(chk["median"] - L) > 1.5 or abs(chk["iqr"] - S) > 1.5:
        log("WARNING: output median/IQR differ from L/S by more than 1.5 grey levels (quantisation + clipping); Sonnet to judge")
    pj = os.path.join(out_root, "segprep_%s_%s_provenance.json" % (tag, stamp))
    with open(pj, "w") as f:
        json.dump(prov, f, indent=1, sort_keys=True)
    log("provenance written %s (sha256 %s)" % (pj, sha256_file(pj)[:16]))
    return prov


def selftest():
    import tempfile, tifffile
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="segprep_selftest_")
    rng = np.random.default_rng(0)
    # synthetic native folder: 31 real layers + 1 padded copy (like PHerc0800 rev4), 200 x 240, median ~100 IQR ~20, a stroke
    D, H, W = 32, 200, 240
    vol = np.clip(rng.normal(100, 15, (31, H, W)), 0, 255).astype(np.uint8)
    vol[10:20, 60:140, 100:104] = 220                 # stroke, cols 100..103
    vol = np.concatenate([vol, vol[-1:]], axis=0)     # padded copy of layer 30
    mask = np.ones((H, W), dtype=bool); mask[:, :20] = False
    vol[:, ~mask] = 0
    src = os.path.join(tmp, "data_seg_t1_20261024_0000_native"); os.makedirs(src)
    for i in range(D):
        tifffile.imwrite(os.path.join(src, "%02d.tif" % i), vol[i].astype(np.uint16) * np.uint16(257))
    Image.fromarray(mask.astype(np.uint8) * 255).save(os.path.join(src, "mask.png"))
    ink = np.zeros((H, W), np.uint8); ink[60:140, 100:104] = 255
    Image.fromarray(ink).save(os.path.join(src, "inklabels.png"))
    with open(os.path.join(tmp, "segconv_t1_20261024_0000_provenance.json"), "w") as f:
        json.dump({"output": {"native": src}, "pad_layers": {"copies": 1}}, f)
    v, m, i2, lr, real, ps = read_folder(src)
    assert v.shape == (32, H, W) and real == list(range(31)) and ps.startswith("segconv_"), (v.shape, real, ps)
    st = hist_stats(v, m, real)
    assert abs(st["median"] - 100) <= 2 and 15 <= st["iqr"] <= 25, st
    # (a) no zoom, normalise to L 150 S 40 -> output stats hit the targets, stroke stays put, padded copy equals layer 30
    p = prep(src, "t1", "s1", 150.0, 40.0, 1.0, False, True, tmp, 0.005)
    out = p["output"]["folder"]
    chk = p["output"]["stats_check"]
    assert abs(chk["median"] - 150) <= 1.5 and abs(chk["iqr"] - 40) <= 1.5, chk
    assert out.endswith("_native_rev5") and not out.endswith("_native")
    t15 = tifffile.imread(os.path.join(out, "15.tif")); assert t15.dtype == np.uint16
    assert t15[100, 101] > t15[100, 50] and t15[100, 19] == 0 and t15[100, 10] == 0, (t15[100, 101], t15[100, 50], t15[100, 19])
    assert np.array_equal(tifffile.imread(os.path.join(out, "30.tif")), tifffile.imread(os.path.join(out, "31.tif")))
    assert p["zoom"]["pad_layers"] == 1 and p["normalisation"]["clipped_fraction_in_mask"] < 0.005
    # (b) xy zoom 1.0923 + z zoom: shapes, stroke column moves to round(101.5*f), 31 -> 34 layers -> window 1..32, no pad
    f = 8.64 / 7.91
    p2 = prep(src, "t1", "s2", 150.0, 40.0, f, True, True, tmp, 0.005)
    Hn, Wn = int(round(H * f)), int(round(W * f))
    assert p2["output"]["shape_dhw"] == [32, Hn, Wn], p2["output"]["shape_dhw"]
    assert p2["zoom"]["layers_after_zoom"] == int(round(31 * f)) and p2["zoom"]["pad_layers"] == 0 and p2["zoom"]["window_kept"] == [1, 32]
    o2 = p2["output"]["folder"]
    mid = tifffile.imread(os.path.join(o2, "15.tif"))
    col = int(np.argmax(mid[100]))
    assert abs(col - round(101.5 * f)) <= 2, (col, round(101.5 * f))
    ink2 = np.array(Image.open(os.path.join(o2, "inklabels.png")))
    assert ink2.shape == (Hn, Wn) and ink2[100, col] == 255 and ink2[10, 10] == 0
    mk = np.array(Image.open(os.path.join(o2, "mask.png"))); assert mk[100, 5] == 0 and mk[100, 100] == 255
    # (c) clipping guard: L 250 pushes most voxels above 255 -> must STOP and write nothing
    try:
        prep(src, "t1", "s3", 250.0, 40.0, 1.0, False, True, tmp, 0.005); raise AssertionError("clip guard did not fire")
    except RuntimeError as e:
        assert "clipped fraction" in str(e), str(e)
    assert not os.path.exists(os.path.join(tmp, "data_seg_t1_s3_native_rev5"))
    # (d) a folder that is already at L/S is a near no-op
    p4 = prep(out, "t1", "s4", 150.0, 40.0, 1.0, False, True, tmp, 0.005)
    a = tifffile.imread(os.path.join(out, "15.tif")).astype(int); b = tifffile.imread(os.path.join(p4["output"]["folder"], "15.tif")).astype(int)
    assert np.abs(a - b).max() <= 2 * 257, np.abs(a - b).max()
    _selftest_rev2(tmp)
    log("SELFTEST PASSED (%s)" % tmp)
    return 0


def _selftest_rev2(tmp):
    """rev2: a 16-layer folder at --depth 16 passes through with no padding; a 28-layer folder at --depth 32 symmetric gets 2 + 2 copies."""
    import tifffile
    from PIL import Image
    global DEPTH_OUT, PAD_MODE
    keep = (DEPTH_OUT, PAD_MODE)
    rng = np.random.default_rng(2)
    H, W = 96, 128
    try:
        for D, depth, mode, exp_below, exp_pad in ((16, 16, "last", 0, 0), (28, 32, "symmetric", 2, 4), (28, 32, "last", 0, 4)):
            vol = np.clip(rng.normal(100, 15, (D, H, W)), 0, 255).astype(np.uint8)
            vol[0] = 96; vol[-1] = 104                      # first and last layers distinct (and within range) so the copies can be identified
            mask = np.ones((H, W), dtype=bool)
            src = os.path.join(tmp, "data_seg_r2_%d_%s_native" % (D, mode)); os.makedirs(src)
            for i in range(D):
                tifffile.imwrite(os.path.join(src, "%02d.tif" % i), vol[i].astype(np.uint16) * np.uint16(257))
            Image.fromarray(mask.astype(np.uint8) * 255).save(os.path.join(src, "mask.png"))
            Image.fromarray(np.zeros((H, W), np.uint8)).save(os.path.join(src, "inklabels.png"))
            DEPTH_OUT, PAD_MODE = depth, mode
            p = prep(src, "r2_%d_%s" % (D, mode), "s", 150.0, 40.0, 1.0, False, True, tmp, 0.005)
            assert p["output"]["shape_dhw"][0] == depth and p["zoom"]["pad_layers"] == exp_pad and p["zoom"].get("pad_below", 0) == exp_below, (p["output"]["shape_dhw"], p["zoom"])
            out = p["output"]["folder"]
            assert sorted(f for f in os.listdir(out) if f.endswith(".tif")) == ["%02d.tif" % i for i in range(depth)]
            t0 = tifffile.imread(os.path.join(out, "00.tif")); tl = tifffile.imread(os.path.join(out, "%02d.tif" % (depth - 1)))
            if mode == "symmetric" and exp_pad:
                assert np.array_equal(t0, tifffile.imread(os.path.join(out, "02.tif"))) and np.array_equal(tl, tifffile.imread(os.path.join(out, "29.tif"))), "symmetric pad must copy the first layer below and the last above"
                assert p["output"]["real_layers"] == [2, 29], p["output"]["real_layers"]
            elif exp_pad:
                assert np.array_equal(tl, tifffile.imread(os.path.join(out, "27.tif"))) and p["output"]["real_layers"] == [0, 27]
            else:
                assert p["output"]["real_layers"] == [0, 15]
    finally:
        DEPTH_OUT, PAD_MODE = keep
    log("rev2 depth/pad checks passed (16 -> 16 no pad; 28 -> 32 symmetric 2+2; 28 -> 32 last 4)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", nargs="+", metavar="FOLDER", help="print median / IQR (in mask, real layers) for each folder and exit")
    ap.add_argument("--src", help="source native folder")
    ap.add_argument("--tag", help="segment tag for the output name")
    ap.add_argument("--L", type=float, help="target median (uint8 units)")
    ap.add_argument("--S", type=float, help="target IQR (uint8 units)")
    ap.add_argument("--xy_zoom", type=float, default=1.0, help="seg_vox / 7.91 (PHerc0800: 1.0923)")
    ap.add_argument("--z_zoom", action="store_true", help="also zoom z by the same factor (only if the layer step equals the voxel size)")
    ap.add_argument("--max_clip", type=float, default=0.005)
    ap.add_argument("--depth", type=int, default=32, help="rev2: output stack depth (multiple of 16): 16 for plan C7, 32 for the C5 control")
    ap.add_argument("--pad_mode", choices=("last", "symmetric"), default="last", help="rev2: how a short real stack is padded to --depth")
    ap.add_argument("--out_root", default="/workspace/VesuviusUNET")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M", time.gmtime()))
    a = ap.parse_args()
    global _LOGF
    if a.selftest:
        return selftest()
    if a.stats:
        rows = []
        for d in a.stats:
            v, m, _, _, real, ps = read_folder(d)
            st = hist_stats(v, m, real)
            rows.append(st)
            log("STATS %s: median %.1f IQR %.1f (p25 %.1f p75 %.1f) n %d real layers %d%s" % (d, st["median"], st["iqr"], st["p25"], st["p75"], st["n_voxels"], len(real), "" if ps else " (no provenance found: all layers taken as real)"))
        if len(rows) > 1:
            log("MEDIAN OVER FOLDERS: L = %.1f  S = %.1f  (use these as --L --S)" % (float(np.median([r["median"] for r in rows])), float(np.median([r["iqr"] for r in rows]))))
        return 0
    if not (a.src and a.tag and a.L is not None and a.S is not None):
        ap.error("--src --tag --L --S are required (or --stats / --selftest)")
    os.makedirs(a.out_root, exist_ok=True)
    _LOGF = open(os.path.join(a.out_root, "segprep_%s_%s.log" % (a.tag, a.stamp)), "a")
    log("=== segprep_c5 rev1 [fable] stamp %s mode %s; code sha256 %s ===" % (a.stamp, "GO" if a.go else "DRY RUN", sha256_file(os.path.abspath(__file__))[:16]))
    global DEPTH_OUT, PAD_MODE
    if a.depth % 16 != 0 or a.depth <= 0:
        ap.error("--depth must be a positive multiple of 16")
    DEPTH_OUT, PAD_MODE = a.depth, a.pad_mode
    prep(a.src, a.tag, a.stamp, a.L, a.S, a.xy_zoom, a.z_zoom, a.go, a.out_root, a.max_clip)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:   # noqa: BLE001
        import traceback; traceback.print_exc()
        log("STOPPED: %s" % e)
        sys.exit(1)
