#!/usr/bin/env python3
# [fable] c11_humanlabel_fable_28102026.py (rev1c: Sonnet 424 fixes 1-4, gate null = far ring 16-24 px; rev1b: Sonnet 420 additions 1-5) - C11: score the EXISTING C9 w045 maps against the public HUMAN ink labels.
# Pre-registered in relay 417 (Sonnet 414 item 3). Read-only: it writes one result folder and touches nothing else.
#
# Inputs (all already on the pod volume, except the labels, which are read over HTTP from the open-data bucket):
#   maps   : VesuviusUNET/c4_maps_c9transfer_20261027_2344/{ens_c4,map_c4}_fw45_20261027_2343_r5*.png
#            (the 8-bit maps C9's AUC 0.81 was computed from - the same files, so this is like-for-like)
#   native : VesuviusUNET/data_seg_fw45_*_native  (label_raw.png = the new_canon map at L2, mask.png)
#   labels : PHerc0139/segments/<seg>/ink-labels/2.399um-volume-20260102150214/20260918/{inklabels,supervision,validation}.zarr
#            level 2 (9.596 um = our C8/C9 grid), cropped to the fw45 box.
#
# Modes
#   probe   : print each label array's level-2 shape / chunks / dtype / value counts in the box and the root attrs. No scoring.
#   score   : GATE first: band-pass correlation of the human-label crop vs label_raw over shifts +-8 px; the best shift must be
#             within 2 px of (0,0) or the script STOPS (nothing scored). Then pixel AUC (sklearn roc_auc_score, no thresholds)
#             of the ensemble, each member, and - descriptive reference - the new_canon map itself, vs (inklabels > 0),
#             inside (supervision > 0); reported for all, inside validation, outside validation. One number per region.
#   selftest: synthetic arrays; checks the gate passes on aligned / fails on shifted data and AUC math.
import argparse, glob, json, os, sys, time

B = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
LABDIR = "ink-labels/2.399um-volume-20260102150214/20260918"
SEG = "20260126000000-w045_2026012619"
BOX = (1171, 2146, 3169, 4144)            # X0 Y0 X1 Y1 at level 2 (c9_night W045)
MAPDIR = "VesuviusUNET/c4_maps_c9transfer_20261027_2344"
STEM = "fw45_20261027_2343_r5"
MEMBERS = ("f042", "f043", "f044", "f047")
MAXSHIFT_OK = 2
SEARCH = 8


def bandpass(x):
    import numpy as np
    from scipy.ndimage import gaussian_filter
    y = gaussian_filter(x.astype(np.float32), 2) - gaussian_filter(x.astype(np.float32), 16)
    return (y - y.mean()) / (y.std() + 1e-6)


def best_shift(a, b, M=SEARCH, R=24):
    """Return (dy, dx, r_best, r00): shift of b relative to a maximising the band-pass correlation within +-M px.
    The null level (best_shift.median_abs) is the median |r| over a FAR ring 16..R px (step 2) - shifts that cannot be the
    true alignment - so the strength floor is not inflated by the labels' own short-range autocorrelation (Sonnet 424 item 2)."""
    import numpy as np
    A, Bb = bandpass(a), bandpass(b)
    Ac = A[R:-R, R:-R]
    def r_at(dy, dx):
        Bc = Bb[R + dy:Bb.shape[0] - R + dy, R + dx:Bb.shape[1] - R + dx]
        return float((Ac * Bc).mean())
    best = (0, 0, -9.0)
    for dy in range(-M, M + 1):
        for dx in range(-M, M + 1):
            r = r_at(dy, dx)
            if r > best[2]:
                best = (dy, dx, r)
    far = [abs(r_at(dy, dx)) for dy in range(-R, R + 1, 2) for dx in range(-R, R + 1, 2) if max(abs(dy), abs(dx)) >= 16]
    best_shift.median_abs = float(np.median(far))
    return best[0], best[1], best[2], r_at(0, 0)


def auc(score, lab, sel):
    import numpy as np
    from sklearn.metrics import roc_auc_score
    y = lab[sel]; s = score[sel]
    npos, nneg = int(y.sum()), int((~y).sum())
    if npos == 0 or nneg == 0:
        return None, npos, nneg
    return float(roc_auc_score(y, s)), npos, nneg


def read_level(name, level):
    import zarr
    g = zarr.open_group("%s/PHerc0139/segments/%s/%s/%s.zarr" % (B, SEG, LABDIR, name), mode="r")
    a = g[str(level)]
    k = 1 if level == 2 else 4            # level 0 = 2.399 um = 4x our L2 grid
    X0, Y0, X1, Y1 = BOX
    return g, a, a[Y0 * k:Y1 * k, X0 * k:X1 * k]


def read_level2(name):
    return read_level(name, 2)


def blocks4(x):
    """R=4 origin-anchored integer blocks (the C8 convention): returns (mean of x>0, all-16 flag) per L2 pixel."""
    import numpy as np
    b = (np.asarray(x) > 0)
    if b.ndim == 3:
        b = b[0]
    H, W = b.shape[0] // 4, b.shape[1] // 4
    v = b[:H * 4, :W * 4].reshape(H, 4, W, 4)
    blocks4.any_ = v.any(axis=(1, 3))
    return v.mean(axis=(1, 3)), v.all(axis=(1, 3))


def load_png(p):
    import numpy as np
    from PIL import Image
    a = np.array(Image.open(p)); return a[..., 0] if a.ndim == 3 else a


def probe():
    import numpy as np
    for n in ("inklabels", "supervision", "validation"):
        g, a, c = read_level2(n)
        u, k = np.unique(c, return_counts=True)
        print("PROBE %s: level2 shape %s chunks %s dtype %s | box crop %s values %s" %
              (n, a.shape, getattr(a, "chunks", "?"), a.dtype, c.shape, dict(zip(u.tolist()[:8], k.tolist()[:8]))))
        _, a0, c0 = read_level(n, 0)
        u0, k0 = np.unique(np.asarray(c0), return_counts=True)
        print("PROBE %s: level0 shape %s dtype %s | box x4 crop %s values %s" % (n, a0.shape, a0.dtype, np.shape(c0), dict(zip(u0.tolist()[:8], k0.tolist()[:8]))))
        if n == "inklabels":
            print("PROBE root attrs: %s" % json.dumps(dict(g.attrs))[:1500])


def sha16(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()[:16]


def repro_gate(w, res):
    """Sonnet 420 item 2: the archived ensemble map, scored by the SAME scorer against the same new_canon pseudo-label on the
    same _rev5 folder, must give C9's recorded w045 AUC 0.8086 +- 0.005. These are the identical files C9 scored (no re-inference)."""
    import subprocess
    proj = os.path.join(w, "VesuviusUNET")
    r5 = sorted(glob.glob(os.path.join(proj, "data_seg_fw45_*_native_rev5")))
    if not r5:
        sys.exit("STOPPED: no data_seg_fw45_*_native_rev5 folder")
    ens = os.path.join(w, MAPDIR, "ens_c4_%s.png" % STEM)
    jp = os.path.join(res["out"], "repro_ensemble.json")
    r = subprocess.run([sys.executable, "-u", os.path.join(proj, "sweep_saved_map_rev2_fable.py"), "--prob_map", ens, "--data_dir", r5[-1], "--out", jp],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, cwd=proj, timeout=3600)
    if r.returncode != 0:
        sys.exit("STOPPED: scorer failed: %s" % r.stdout[-400:])
    a = float(json.load(open(jp))["papyrus"]["auc"])
    shas = {"ensemble_png": sha16(ens)}
    for t in MEMBERS:
        shas["map_" + t] = sha16(os.path.join(w, MAPDIR, "map_c4_%s_%s.png" % (STEM, t)))
        ck = os.path.join(proj, "runs/c8_%s_e240_27102026/last.pt" % t)
        shas["last_pt_" + t] = sha16(ck) if os.path.exists(ck) else "MISSING"
    res["repro"] = {"auc_vs_new_canon": a, "recorded": 0.8086, "tol": 0.005, "rev5": r5[-1], "sha256_16": shas}
    print("REPRO GATE: ensemble vs new_canon on %s AUC %.4f (C9 recorded 0.8086, tol 0.005); sha16 %s" % (os.path.basename(r5[-1]), a, json.dumps(shas)))
    if abs(a - 0.8086) > 0.005:
        sys.exit("STOPPED: does not reproduce C9 - nothing scored against human labels")


def score(w, out):
    import numpy as np
    res = {"stamp": out, "out": out, "seg": SEG, "box": BOX, "rule": "relay 417 + Sonnet 420 (1-5)"}
    nat = sorted(glob.glob(os.path.join(w, "VesuviusUNET/data_seg_fw45_*_native")))
    if not nat:
        sys.exit("STOPPED: no data_seg_fw45_*_native folder")
    nat = nat[-1]; res["native"] = nat
    repro_gate(w, res)
    lraw = load_png(os.path.join(nat, "label_raw.png"))
    H, W = lraw.shape
    _, a0, ink0 = read_level("inklabels", 0); _, _, sup0 = read_level("supervision", 0); _, _, val0 = read_level("validation", 0)
    print("level-0 crops: inklabels %s supervision %s validation %s (need %d x %d)" % (np.shape(ink0), np.shape(sup0), np.shape(val0), H * 4, W * 4))
    inkm, _ = blocks4(ink0); _, S = blocks4(sup0); _, V = blocks4(val0); Vany = blocks4.any_
    if inkm.shape != (H, W) or S.shape != (H, W) or V.shape != (H, W):
        sys.exit("STOPPED: built L2 labels %s / %s / %s != our L2 box %s - grid mismatch, nothing scored" % (inkm.shape, S.shape, V.shape, (H, W)))
    lab = (inkm * 255) >= 128                       # ink = block mean >= 128 (our new_canon rule)
    dy, dx, rb, r00 = best_shift(lraw, inkm * 255)
    med = best_shift.median_abs
    res["gate"] = {"best_dy": dy, "best_dx": dx, "r_best": rb, "r00": r00, "median_abs_r": med, "limit_px": MAXSHIFT_OK, "floor": "r_best >= 3 x median|r|"}
    print("GRID GATE: human labels (R=4 from level 0) vs new_canon label_raw: best shift (dy,dx)=(%d,%d) r %.3f, r(0,0) %.3f, median|r| %.3f (need r_best >= %.3f)" % (dy, dx, rb, r00, med, 3 * med))
    if rb < 3 * med:
        json.dump(res, open(os.path.join(out, "c11_result.json"), "w"), indent=1)
        sys.exit("STOPPED: grid gate correlation too weak (r_best %.3f < 3 x median %.3f) - NOT scored" % (rb, med))
    if max(abs(dy), abs(dx)) > MAXSHIFT_OK:
        json.dump(res, open(os.path.join(out, "c11_result.json"), "w"), indent=1)
        sys.exit("STOPPED: grid offset %d,%d px > %d px - NOT scored, not corrected (pre-registered, relay 417 / Sonnet 420)" % (dy, dx, MAXSHIFT_OK))
    P = load_png(os.path.join(nat, "mask.png")) > 0
    if P.shape != (H, W):
        sys.exit("STOPPED: mask.png shape %s != box %s" % (P.shape, (H, W)))
    SP = S & P
    regions = {"PRIMARY_supervision_and_papyrus": SP, "PRIMARY_in_validation": SP & V, "PRIMARY_outside_validation": SP & ~Vany,
               "descriptive_supervision_only": S}
    res["mask_counts"] = {"supervised_blocks": int(S.sum()), "supervised_outside_papyrus_mask": int((S & ~P).sum()),
                          "partial_validation_blocks_dropped": int((SP & Vany & ~V).sum())}
    print("MASK: supervised blocks %d, of which outside our papyrus mask %d; partial-validation blocks dropped from both splits %d" %
          (S.sum(), (S & ~P).sum(), (SP & Vany & ~V).sum()))
    res["counts"] = {rn: {"supervised_blocks": int(sel.sum()), "ink_blocks": int((lab & sel).sum()),
                          "ink_fraction": float((lab & sel).sum() / max(1, sel.sum()))} for rn, sel in regions.items()}
    res["box_supervised_fraction"] = float(S.mean())
    print("COUNTS %s; supervised fraction of the fw45 box %.3f (box-only scored; the rest of the segment is not inferred)" % (json.dumps(res["counts"]), S.mean()))
    maps = {"ENSEMBLE": os.path.join(w, MAPDIR, "ens_c4_%s.png" % STEM)}
    for t in MEMBERS:
        maps["member_" + t] = os.path.join(w, MAPDIR, "map_c4_%s_%s.png" % (STEM, t))
    res["scores"] = {}
    for k, p in list(maps.items()) + [("REFERENCE_new_canon_map", None)]:
        s = lraw if p is None else load_png(p)
        if s.shape != lab.shape:
            sys.exit("STOPPED: %s shape %s != label %s" % (k, s.shape, lab.shape))
        res["scores"][k] = {}
        for rn, sel in regions.items():
            a, npos, nneg = auc(s.astype(np.float64), lab, sel)
            res["scores"][k][rn] = {"auc": a, "ink_px": npos, "noink_px": nneg}
            print("SCORE %-24s %-31s AUC %s  (ink px %d, no-ink px %d)" % (k, rn, "%.4f" % a if a is not None else "n/a", npos, nneg))
    print("NOTE: REFERENCE_new_canon_map is descriptive only; the pseudo-label source may have been trained on these labels (Sonnet 420 item 4).")
    json.dump(res, open(os.path.join(out, "c11_result.json"), "w"), indent=1)
    print("written %s" % os.path.join(out, "c11_result.json"))


def selftest():
    import numpy as np
    from scipy.ndimage import gaussian_filter
    rng = np.random.default_rng(0)
    base = gaussian_filter(rng.normal(size=(300, 300)), 3)
    lab = base > 0.02
    lraw = (gaussian_filter(lab.astype(float), 1.5) * 255)
    dy, dx, rb, _ = best_shift(lraw, lab.astype(np.float32) * 255)
    assert max(abs(dy), abs(dx)) <= 1, (dy, dx)
    sh = np.roll(lab, (6, -5), (0, 1))
    dy2, dx2, _, _ = best_shift(lraw, sh.astype(np.float32) * 255)
    assert max(abs(dy2), abs(dx2)) > MAXSHIFT_OK, (dy2, dx2)
    sel = np.ones_like(lab)
    a, _, _ = auc(lraw, lab, sel); assert a > 0.9, a
    r, _, _ = auc(rng.random(lab.shape), lab, sel); assert 0.45 < r < 0.55, r
    lv0 = np.kron(lab, np.ones((4, 4))); m, al = blocks4(lv0); assert (m == lab).all() and (al == lab).all()
    part = lv0.copy(); part[0, 0] = 0; m2, al2 = blocks4(part); assert (not al2[0, 0]) or (not lab[0, 0])
    print("SELFTEST PASSED (aligned shift %d,%d; shifted detected %d,%d; AUC good %.3f random %.3f)" % (dy, dx, dy2, dx2, a, r))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe", "score", "selftest"])
    ap.add_argument("--workspace", default="/workspace")
    a = ap.parse_args()
    if a.mode == "selftest":
        selftest()
    elif a.mode == "probe":
        probe()
    else:
        out = os.path.join(a.workspace, "c11_humanlabel_%s" % time.strftime("%Y%m%d_%H%M", time.gmtime()))
        os.makedirs(out, exist_ok=True)
        score(a.workspace, out)
