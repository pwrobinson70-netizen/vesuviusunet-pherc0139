#!/usr/bin/env python3
"""reg24_sonnet_25102026c.py  [sonnet] 25 Oct 2026 (rev c: + --binary outline test; rev b: --hp SIGMA, --tifs A B) - wide registration search for plan C7 F8.
Reads an EXISTING converter folder (no download): mean of window tifs 04..11 (= source 10..17 for --native_layers 6 22) vs
label_raw.png (the area-meaned uint8 map crop). Pearson r for every integer shift (dy, dx) in -M..+M (default 24) on the
central region, by FFT (exact per-shift mean/std over the overlap window). Prints r(0,0), the best shift, the top 5,
and the r at the shift PREDICTED if the 2.399 and 9.362 grids share an origin (voxel ratio 9.362/2.399) instead of the
linspace (same-extent) mapping.
  python3 -I reg24_sonnet_25102026.py <folder> [--M 24] [--pred DY DX]
  python3 -I reg24_sonnet_25102026.py --selftest
"""
import sys, os, glob, argparse
import numpy as np

def ncc_all(S, L, M):
    """r[dy+M, dx+M] = Pearson(L_c, S[M+dy : M+dy+h, M+dx : M+dx+w]) where L_c = L[M:-M, M:-M] (h x w)."""
    from scipy.signal import fftconvolve
    Lc = L[M:L.shape[0] - M, M:L.shape[1] - M].astype(np.float64)
    h, w = Lc.shape
    Lz = Lc - Lc.mean(); Ln = np.sqrt((Lz * Lz).sum())
    S = S.astype(np.float64)
    num = fftconvolve(S, Lz[::-1, ::-1], mode="valid")              # sum S*Lz over each window (Lz zero-mean -> no S-mean term)
    one = np.ones((h, w))
    s1 = fftconvolve(S, one, mode="valid"); s2 = fftconvolve(S * S, one, mode="valid")
    var = np.maximum(s2 - s1 * s1 / (h * w), 1e-9)
    r = num / (np.sqrt(var) * Ln + 1e-9)
    assert r.shape == (2 * M + 1, 2 * M + 1), r.shape
    return r

def run(folder, M, pred, hp=0.0, t0=4, t1=12, binary=False):
    import tifffile
    from PIL import Image
    tifs = [os.path.join(folder, "%02d.tif" % i) for i in range(t0, t1)]
    for t in tifs:
        if not os.path.exists(t): sys.exit("STOPPED: missing %s" % t)
    S = np.mean([tifffile.imread(t).astype(np.float64) for t in tifs], axis=0)
    L = np.array(Image.open(os.path.join(folder, "label_raw.png"))).astype(np.float64)
    assert S.shape == L.shape, (S.shape, L.shape)
    if binary:                                   # rev c: pure geometry - papyrus outline in the scan vs where the map is non-zero
        S = (S > 0).astype(np.float64); L = (L > 0).astype(np.float64)
        print("binary outline: scan non-zero share %.4f, map non-zero share %.4f" % (S.mean(), L.mean()))
    if hp > 0:                                   # remove large-scale brightness so a broad bump cannot hide a residual offset
        from scipy.ndimage import gaussian_filter
        S = S - gaussian_filter(S, hp); L = L - gaussian_filter(L, hp)
    r = ncc_all(S, L, M)
    i = np.unravel_index(np.argmax(np.abs(r)), r.shape)
    order = np.argsort(-np.abs(r).ravel())[:5]
    print("folder %s  shape %s  M %d  hp %s  tifs %02d..%02d  binary %s" % (os.path.basename(folder.rstrip('/')), S.shape, M, hp, t0, t1 - 1, binary))
    print("r(0,0) = %+.4f" % r[M, M])
    print("best |r| = %+.4f at (dy, dx) = (%d, %d)" % (r[i], i[0] - M, i[1] - M))
    print("top5: " + "; ".join("(%d,%d) %+.4f" % (k // r.shape[1] - M, k % r.shape[1] - M, r.ravel()[k]) for k in order))
    med = np.median(np.abs(r))
    print("median |r| over all shifts %.4f; r(0,0)/median %.2f; best/median %.2f" % (med, abs(r[M, M]) / max(med, 1e-9), abs(r[i]) / max(med, 1e-9)))
    if pred:
        dy, dx = int(round(pred[0])), int(round(pred[1]))
        if abs(dy) <= M and abs(dx) <= M:
            print("r at predicted (%d, %d) = %+.4f" % (dy, dx, r[dy + M, dx + M]))
    np.save(os.path.join("/workspace", "reg24%s%s_%s.npy" % ("bin" if binary else "", "hp%g" % hp if hp else "", os.path.basename(folder.rstrip('/')))), r)

def selftest():
    rng = np.random.default_rng(0)
    H = W = 400; M = 24
    base = rng.normal(0, 1, (H + 80, W + 80))
    from scipy.ndimage import gaussian_filter
    base = gaussian_filter(base, 3)
    true_dy, true_dx = -9, -13          # label pixel y corresponds to volume pixel y + dy
    S = base[40:40 + H, 40:40 + W] + rng.normal(0, 0.5, (H, W))
    L = base[40 - true_dy:40 - true_dy + H, 40 - true_dx:40 - true_dx + W]
    # with L(y) = base(y - dy) and S(y) = base(y): L(y) matches S(y + ... ) -> check sign by brute force on one shift
    r = ncc_all(S, L, M)
    i = np.unravel_index(np.argmax(np.abs(r)), r.shape)
    got = (i[0] - M, i[1] - M)
    # brute-force check of the same r at two shifts against np.corrcoef
    for dy, dx in [got, (0, 0), (5, -7)]:
        Lc = L[M:H - M, M:W - M]; Ss = S[M + dy:M + dy + Lc.shape[0], M + dx:M + dx + Lc.shape[1]]
        ref = np.corrcoef(Lc.ravel(), Ss.ravel())[0, 1]
        assert abs(ref - r[dy + M, dx + M]) < 1e-6, (dy, dx, ref, r[dy + M, dx + M])
    assert got == (-true_dy, -true_dx) or got == (true_dy, true_dx), got
    print("SELFTEST PASSED: FFT r == np.corrcoef at 3 shifts; synthetic offset recovered at", got, "(peak %.3f, r(0,0) %.3f)" % (r[i], r[M, M]))
    # rev b: broad shared brightness field + small true offset (3,-4) in fine texture; raw search is dominated by the field,
    # hp 6 must recover (3,-4) exactly
    fine = gaussian_filter(rng.normal(0, 1, (H + 80, W + 80)), 1.5)
    yy, xx = np.mgrid[0:H + 80, 0:W + 80]
    field = 40 * np.sin(yy / 90.0) * np.cos(xx / 110.0)
    S2 = (field + fine)[40:40 + H, 40:40 + W]
    L2 = (field[40:40 + H, 40:40 + W]) + fine[40 + 3:40 + 3 + H, 40 - 4:40 - 4 + W]
    S2h = S2 - gaussian_filter(S2, 6); L2h = L2 - gaussian_filter(L2, 6)
    r2 = ncc_all(S2h, L2h, M); j = np.unravel_index(np.argmax(np.abs(r2)), r2.shape)
    assert (j[0] - M, j[1] - M) == (3, -4), (j[0] - M, j[1] - M)
    print("SELFTEST PASSED (rev b): high-pass recovers a (3,-4) fine offset under a broad shared field (peak %.3f, median %.3f)" % (r2[j], np.median(np.abs(r2))))
    from scipy.ndimage import gaussian_filter as gf
    blob = gf(rng.normal(0, 1, (H + 80, W + 80)), 25) > 0.0
    Sb = blob[40:40 + H, 40:40 + W].astype(float); Lb = blob[40 + 2:40 + 2 + H, 40 - 3:40 - 3 + W].astype(float)
    Sb -= gf(Sb, 3); Lb -= gf(Lb, 3)
    r3 = ncc_all(Sb, Lb, M); k = np.unravel_index(np.argmax(np.abs(r3)), r3.shape)
    assert (k[0] - M, k[1] - M) == (2, -3), (k[0] - M, k[1] - M)
    print("SELFTEST PASSED (rev c): outline (binary + hp 3) recovers a (2,-3) shift (peak %.3f, median %.3f)" % (r3[k], np.median(np.abs(r3))))
    return got

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?"); ap.add_argument("--M", type=int, default=24)
    ap.add_argument("--pred", type=float, nargs=2, default=None); ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--hp", type=float, default=0.0, help="Gaussian sigma (px) subtracted from both images first; 0 = off")
    ap.add_argument("--binary", action="store_true", help="rev c: correlate (scan > 0) with (map > 0) - outline geometry only")
    ap.add_argument("--tifs", type=int, nargs=2, default=[4, 12], help="half-open tif range averaged (default 04..11)")
    a = ap.parse_args()
    if a.selftest: selftest()
    else: run(a.folder, a.M, a.pred, a.hp, a.tifs[0], a.tifs[1], a.binary)
