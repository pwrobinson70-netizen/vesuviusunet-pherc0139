#!/usr/bin/env python3
"""
c4_maps_fable_27102026_rev4c.py  (rev4c, [fable], 27 Oct 2026: + --members C8 (depth 32, runs/c8_<t>_e240_<day>); rev4, rev3b + --members C7, DEPTH per member family; rev3b = rev2 + plan C5 rev2; rev3b = Sonnet 250 M1 (both dataset.py hashes accepted): --members C3|C5, HIGH flag, top-10 % pictures,
--score for the w078/w085 yardstick (S1 baseline / S3 check), rev5 folders accepted) -- ink maps from four models on folders they never saw.
REV3: --members C5 takes the four C5 last.pt (runs/c5_<t>_md_s42_bc8_d32_<day>/last.pt, --c5_day) and records their sha256 and
  run banners instead of checking against the S4 json; HIGH flag = in-mask frac>=0.5 > 0.8 (uninformative, like LOW); ens_c4_<f>_top10.png
  = in-mask top 10 % of the ensemble (E1 picture); --score runs sweep_saved_map_rev2 on the ensemble AND each member for folders that
  carry a published map (papyrus AUC, F0.5 at 0.5) -> "scores" in the json. Folder names may end _native or _native_rev5.
NOT a test: nothing is scored. For every native folder named on the command line it
  1. checks the code hashes (frozen list) and the four C3 last.pt hashes against the S4 record C3_HELDOUT_20261024_1022.json
     (the models are USED AS THEY ARE; any retraining would be a new plan);
  2. runs vesuvius_unet.cross_infer --depth 32 --stride STRIDE (default 16; Sonnet 231 M1 - finer than S4's 32 so the tile
     grid does not pass for strokes; the same stride for C4a and C4b) once per model -> map_c4_<folder>_<model>.png;
  3. writes the pixel-wise MEAN ensemble (ensemble_maps_fable_08102026.py) -> ens_c4_<folder>.png, plus pictures for the
     by-eye call: ens_c4_<folder>_ds8.png (1/8 box shrink), ens_c4_<folder>_thr0p5.png, and label_raw_<folder>_ds8.png when
     the folder has a published map (PHerc0172 only; PHerc0800 has none);
  4. records per folder: mean probability, fraction >= 0.5, max, and the same three numbers for the S4 held-out ensemble as
     the reference scale (read from the S4 json's ensemble_pictures); a LOW flag (plan section 4: frac>=0.5 in mask below
     1/10 of the reference, or mean prob in mask below 0.05 - a pointer for the eye, not a verdict); and, for folders that
     carry a published map, ONE declared INFO number: Pearson r of the ds8 ensemble vs the ds8 label_raw (not a test, no
     threshold; Sonnet 231 m5) -> C4_MAPS_<stamp>.json/.txt, and a tgz of the PNGs.
Judging (plan C4 section 4): by eye, both reviewers independently, against the written rule; the numbers are context only.
Usage (Linux shell, pod):  python3 -I /workspace/c4_maps_fable_24102026.py --go data_seg_p800a_<stamp>_native ...
  without --go: preflight only.
"""
import argparse, hashlib, json, os, subprocess, sys, time

ROOT = "/workspace"
PROJ = os.path.join(ROOT, "VesuviusUNET")
S4_JSON = os.path.join(PROJ, "c3_heldout_20261024_1022", "C3_HELDOUT_20261024_1022.json")
TAGS = ("w088", "w081", "w087", "w084")
TAGS_C7 = ("w042", "w043", "w044", "w047")          # rev4: plan C7 members (PHerc0139 training boxes)
MEMBERS = {t: "runs/c3_%s_md_s42_bc8_d32_24102026/last.pt" % t for t in TAGS}
DEPTH = ["32"]                                       # rev4: cross_infer --depth follows the member family (C3/C5 32, C7 16)
HIGH_FRAC = 0.8
SCORER = "sweep_saved_map_rev2_fable.py"
CODE_WANT = {"vesuvius_unet/cross_infer.py": "9ec7afb600c2dfce", "vesuvius_unet/infer.py": "272a50c315ac3eaf",
             "vesuvius_unet/model.py": "fc5b726de544a959", "vesuvius_unet/dataset.py": ("43a643cf5b3948aa", "910335e3d79c88f8"),
             "ensemble_maps_fable_08102026.py": "2f51b63656822a1f"}
TAG = "    | [no labels: nothing here is a score] "
_LOGF = None


def log(m):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), m)
    print(line, flush=True)
    if _LOGF:
        _LOGF.write(line + "\n"); _LOGF.flush()


def sha256_file(p, nocr=False):
    with open(p, "rb") as f:
        data = f.read()
    if nocr:
        data = data.replace(b"\r", b"")
    return hashlib.sha256(data).hexdigest()


def run_logged(cmd, cwd, timeout_s):
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    t0 = time.time()
    for line in p.stdout:
        log(TAG + line.rstrip())
        if time.time() - t0 > timeout_s:
            p.kill(); raise RuntimeError("timeout after %d s" % timeout_s)
    return p.wait(), time.time() - t0


def preflight(folders):
    import numpy as np
    from PIL import Image
    rec = {"code": {}, "members": {}, "folders": {}}
    for f, want in CODE_WANT.items():
        p = os.path.join(PROJ, f)
        if not os.path.exists(p) and f.startswith("ensemble_maps"):
            p = os.path.join(ROOT, f)
        wants = want if isinstance(want, tuple) else (want,)
        got = sha256_file(p, nocr=True)[:len(wants[0])]
        if got not in wants:
            raise RuntimeError("code hash mismatch %s: %s not in %s" % (f, got, wants))
        rec["code"][f] = got
        if len(wants) > 1:
            log("code %s = %s (%s)" % (f, got, "frozen C3" if got == wants[0] else "C5 patch (Sonnet 250: inference path untouched, C5_AUG unset)"))
    log("code hashes ok (%d files)" % len(CODE_WANT))
    s4 = json.load(open(S4_JSON))
    rec["s4_json_sha256"] = sha256_file(S4_JSON)
    rec["s4_reference_ensemble_pictures"] = s4["ensemble_pictures"]
    rec["member_set"] = MEMBER_SET[0]
    for t, rel in MEMBERS.items():
        p = os.path.join(PROJ, rel)
        if not os.path.exists(p):
            raise RuntimeError("missing checkpoint %s" % rel)
        got = sha256_file(p)
        if MEMBER_SET[0] == "C3":
            want = s4["preflight"]["members"][t]["sha256"]
            if got != want:
                raise RuntimeError("checkpoint %s sha256 %s != S4 record %s" % (t, got[:16], want[:16]))
            rec["members"][t] = {"path": rel, "sha256": got}
            log("member %s sha256 %s = S4 record" % (t, got[:16]))
        else:
            rd = os.path.dirname(p)
            banners = sorted(x for x in os.listdir(rd) if x.startswith("run_banner") and x.endswith(".json"))
            rec["members"][t] = {"path": rel, "sha256": got, "bytes": os.path.getsize(p), "run_banner": banners[-1] if banners else None,
                                 "run_banner_sha256": sha256_file(os.path.join(rd, banners[-1])) if banners else None}
            log("member %s (%s) %s sha256 %s (%d B); banner %s" % (t, MEMBER_SET[0], rel, got[:16], os.path.getsize(p), banners[-1] if banners else "NONE"))
    if SCORE[0]:
        sp = os.path.join(PROJ, SCORER)
        if not os.path.exists(sp):
            raise RuntimeError("--score needs %s" % sp)
        rec["scorer_sha256"] = sha256_file(sp, nocr=True)
        log("scorer %s sha256 %s" % (SCORER, rec["scorer_sha256"][:16]))
    for d in folders:
        full = os.path.join(PROJ, d)
        tifs = sorted(x for x in os.listdir(full) if x.endswith(".tif"))
        mask = np.array(Image.open(os.path.join(full, "mask.png")))
        ink = np.array(Image.open(os.path.join(full, "inklabels.png")))
        has_label = os.path.exists(os.path.join(full, "label_raw.png"))
        if len(tifs) != int(DEPTH[0]):
            raise RuntimeError("%s has %d tifs, not %s (member family %s)" % (d, len(tifs), DEPTH[0], MEMBER_SET[0]))
        rec["folders"][d] = {"tifs": len(tifs), "shape": list(mask.shape), "mask_px": int((mask > 0).sum()),
                             "ink_px": int((ink > 0).sum()), "has_published_map": has_label}
        log("folder %s: %d tifs, %s, papyrus px %d, label %s" % (d, len(tifs), mask.shape, int((mask > 0).sum()), "published map" if has_label else "NONE (all-zero)"))
    if subprocess.run(["pgrep", "-f", "vesuvius_unet.train"], stdout=subprocess.PIPE).stdout.strip():
        raise RuntimeError("a training process is running")
    r = subprocess.run([sys.executable, "-c", "import torch;print(torch.cuda.is_available())"], stdout=subprocess.PIPE, universal_newlines=True)
    if "True" not in r.stdout:
        raise RuntimeError("CUDA not available")
    return rec


def pictures(out, name, ens_map, folder_full):
    import numpy as np
    from PIL import Image
    a = np.array(Image.open(ens_map)); a = a[..., 0] if a.ndim == 3 else a
    prob = a.astype(np.float64) / 255.0
    Image.fromarray(((prob >= 0.5) * 255).astype(np.uint8)).save(os.path.join(out, "ens_c4_%s_thr0p5.png" % name))
    Image.fromarray(a).resize((max(1, a.shape[1] // 8), max(1, a.shape[0] // 8)), Image.BOX).save(os.path.join(out, "ens_c4_%s_ds8.png" % name))
    lp = os.path.join(folder_full, "label_raw.png")
    if os.path.exists(lp):
        lab = np.array(Image.open(lp))
        Image.fromarray(lab).resize((max(1, lab.shape[1] // 8), max(1, lab.shape[0] // 8)), Image.BOX).save(os.path.join(out, "label_raw_%s_ds8.png" % name))
    mask = np.array(Image.open(os.path.join(folder_full, "mask.png"))) > 0
    pm = prob[mask] if mask.any() else prob.ravel()
    q = float(np.quantile(pm, 0.9))
    Image.fromarray((((prob >= q) & mask) * 255).astype(np.uint8)).save(os.path.join(out, "ens_c4_%s_top10.png" % name))
    return {"mean_prob": float(prob.mean()), "frac_ge_0p5": float((prob >= 0.5).mean()), "max_prob": float(prob.max()),
            "mean_prob_in_mask": float(pm.mean()), "frac_ge_0p5_in_mask": float((pm >= 0.5).mean()), "top10_cut_in_mask": q}


def pearson_ds8(out, name):
    """INFO only (Sonnet 231 m5): Pearson r between the ds8 ensemble picture and the ds8 label_raw picture, where a map exists."""
    import numpy as np
    from PIL import Image
    lp = os.path.join(out, "label_raw_%s_ds8.png" % name)
    if not os.path.exists(lp):
        return None
    a = np.array(Image.open(os.path.join(out, "ens_c4_%s_ds8.png" % name))).astype(np.float64).ravel()
    b = np.array(Image.open(lp)).astype(np.float64).ravel()
    if a.size != b.size or a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


MEMBER_SET = ["C3"]
SCORE = [False]


def score_map(pm, data_dir, jp):
    r = subprocess.run([sys.executable, "-u", os.path.join(PROJ, SCORER), "--prob_map", pm, "--data_dir", data_dir, "--out", jp],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=3600, cwd=PROJ)
    if r.returncode != 0:
        raise RuntimeError("scorer failed for %s: %s" % (pm, r.stdout[-600:]))
    d = json.load(open(jp))
    pap = d["papyrus"]
    row = min(pap["sweep"], key=lambda x: abs(x["threshold"] - 0.5))
    return {"auc": float(pap["auc"]), "f05_at_0p5": float(row["f05"]), "precision_at_0p5": float(row["precision"]), "recall_at_0p5": float(row["recall"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+", help="native folder names under /workspace/VesuviusUNET (…_native or …_native_rev5)")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--stride", type=int, default=16, help="cross_infer stride (plan C4 rev2: 16 for C4a and C4b alike)")
    ap.add_argument("--members", choices=["C3", "C5", "C7", "C8"], default="C3", help="rev4c: C8 = runs/c8_<t>_e240_<c5_day>/last.pt (depth 32, tags f042 f043 f044 f047, plan C8); C3 = the four S4-recorded last.pt; C5 = runs/c5_<t>_md_s42_bc8_d32_<c5_day>/last.pt; C7 = runs/c7_<t>_md_s42_bc8_d16_<c5_day>/last.pt (depth 16, tags w042 w043 w044 w047)")
    ap.add_argument("--c5_day", default=None, help="DDMMYYYY suffix of the C5 / C7 run folders (required with --members C5 or C7)")
    ap.add_argument("--score", action="store_true", help="plan C5 S1/S3: score ensemble + members with the scorer on folders that carry a published map")
    ap.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M", time.gmtime()))
    args = ap.parse_args()
    global _LOGF, MEMBERS
    MEMBER_SET[0] = args.members; SCORE[0] = args.score
    if args.members == "C5":
        if not args.c5_day:
            ap.error("--c5_day DDMMYYYY is required with --members C5")
        MEMBERS = {t: "runs/c5_%s_md_s42_bc8_d32_%s/last.pt" % (t, args.c5_day) for t in TAGS}
    elif args.members == "C8":   # rev4c (plan C8 / c9 night branch A)
        if not args.c5_day:
            ap.error("--c5_day DDMMYYYY is required with --members C8")
        MEMBERS = {t: "runs/c8_%s_e240_%s/last.pt" % (t, args.c5_day) for t in ("f042", "f043", "f044", "f047")}
        DEPTH[0] = "32"
    elif args.members == "C7":
        if not args.c5_day:
            ap.error("--c5_day DDMMYYYY is required with --members C7")
        MEMBERS = {t: "runs/c7_%s_md_s42_bc8_d16_%s/last.pt" % (t, args.c5_day) for t in TAGS_C7}
        DEPTH[0] = "16"
    out = os.path.join(PROJ, "c4_maps_%s" % args.stamp)
    os.makedirs(out, exist_ok=True)
    _LOGF = open(os.path.join(out, "c4_maps_%s.log" % args.stamp), "a")
    log("=== C4 MAPS %s (fable rev4) mode %s; script sha256 %s; stride %d; members %s depth %s; score %s; %d folder(s) ===" %
        (args.stamp, "GO" if args.go else "DRY RUN", sha256_file(os.path.abspath(__file__))[:16], args.stride, args.members, DEPTH[0], args.score, len(args.folders)))
    if args.score:
        log("SCORING ON (plan C5 S1/S3): papyrus AUC and F0.5@0.5 against the published-map pseudo-label on folders that carry one; w078/w085 become a USED yardstick.")
    else:
        log("NOT A TEST: no scoring. Maps from the four %s models as they are; judged by eye against the written rule." % args.members)
    rec = preflight(args.folders)
    if not args.go:
        log("DRY RUN complete: preflight passed.")
        return 0
    ens = os.path.join(PROJ, "ensemble_maps_fable_08102026.py")
    if not os.path.exists(ens):
        ens = os.path.join(ROOT, "ensemble_maps_fable_08102026.py")
    res = {"stamp": args.stamp, "stride": args.stride, "members": args.members, "scored": bool(args.score), "preflight": rec, "folders": {}}
    for d in args.folders:
        full = os.path.join(PROJ, d)
        name = d.replace("data_seg_", "").replace("_native_rev5", "_r5").replace("_native", "")
        maps = []
        for t, rel in MEMBERS.items():
            mp = os.path.join(out, "map_c4_%s_%s.png" % (name, t))
            log("=== MAP %s model %s ===" % (name, t))
            rc, sec = run_logged([sys.executable, "-u", "-m", "vesuvius_unet.cross_infer", "--data_dir", full, "--checkpoint", os.path.join(PROJ, rel),
                                  "--output", mp, "--depth", DEPTH[0], "--stride", str(args.stride)], PROJ, 7200)
            if rc != 0 or not os.path.exists(mp):
                raise RuntimeError("cross_infer failed for %s / %s (rc %s)" % (name, t, rc))
            maps.append(mp)
            log("map %s %s done in %.1f min" % (name, t, sec / 60))
        ensp = os.path.join(out, "ens_c4_%s.png" % name)
        r = subprocess.run([sys.executable, "-u", ens, "--out", ensp] + maps, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=3600, cwd=PROJ)
        if r.returncode != 0 or not os.path.exists(ensp):
            raise RuntimeError("ensemble failed for %s: %s" % (name, r.stdout[-400:]))
        pic = pictures(out, name, ensp, full)
        ref = rec["s4_reference_ensemble_pictures"]
        low = (pic["frac_ge_0p5_in_mask"] < 0.1 * ref["frac_ge_0p5"]) or (pic["mean_prob_in_mask"] < 0.05)
        high = pic["frac_ge_0p5_in_mask"] > HIGH_FRAC
        pic["LOW_flag"] = bool(low); pic["HIGH_flag"] = bool(high)
        pic["info_pearson_r_ds8_vs_label"] = pearson_ds8(out, name)
        res["folders"][d] = {"ensemble": os.path.basename(ensp), "stats": pic, "ensemble_sha256": sha256_file(ensp), "members": [os.path.basename(m) for m in maps]}
        log("ENSEMBLE %s: mean prob %.3f (in mask %.3f), frac>=0.5 %.4f (in mask %.4f), max %.3f, top10 cut %.3f%s%s  | S4 held-out reference: mean %.3f frac>=0.5 %.4f max %.3f%s" %
            (name, pic["mean_prob"], pic["mean_prob_in_mask"], pic["frac_ge_0p5"], pic["frac_ge_0p5_in_mask"], pic["max_prob"], pic["top10_cut_in_mask"],
             "  LOW" if low else "", "  HIGH" if high else "", ref["mean_prob"], ref["frac_ge_0p5"], ref["max_prob"],
             "" if pic["info_pearson_r_ds8_vs_label"] is None else "  | INFO (not a test) r(ds8 ens, ds8 label) = %.3f" % pic["info_pearson_r_ds8_vs_label"]))
        if args.score and rec["folders"][d]["has_published_map"]:
            sc = {}
            for t, mp in zip(MEMBERS.keys(), maps):
                sc[t] = score_map(mp, full, os.path.join(out, "score_%s_%s.json" % (name, t)))
                log("SCORE %s member %s: AUC %.4f F0.5@0.5 %.4f (P %.3f R %.3f)" % (name, t, sc[t]["auc"], sc[t]["f05_at_0p5"], sc[t]["precision_at_0p5"], sc[t]["recall_at_0p5"]))
            sc["ensemble"] = score_map(ensp, full, os.path.join(out, "score_%s_ensemble.json" % name))
            sc["mean_member_auc"] = sum(sc[t]["auc"] for t in MEMBERS) / len(MEMBERS)
            log("SCORE %s ENSEMBLE: AUC %.4f F0.5@0.5 %.4f (P %.3f R %.3f); mean member AUC %.4f" %
                (name, sc["ensemble"]["auc"], sc["ensemble"]["f05_at_0p5"], sc["ensemble"]["precision_at_0p5"], sc["ensemble"]["recall_at_0p5"], sc["mean_member_auc"]))
            res["folders"][d]["scores"] = sc
        elif args.score:
            log("SCORE %s: no published map in the folder -> not scored" % name)
    jp = os.path.join(out, "C4_MAPS_%s.json" % args.stamp)
    json.dump(res, open(jp, "w"), indent=1, sort_keys=True)
    with open(os.path.join(out, "C4_MAPS_%s.txt" % args.stamp), "w") as f:
        f.write("C4 MAPS %s members %s%s\n" % (args.stamp, args.members, " (scored: plan C5 S1/S3 yardstick)" if args.score else " (not a test; by-eye judging)"))
        for d, v in res["folders"].items():
            s = v["stats"]
            f.write("%s mean_prob %.3f in_mask %.3f frac>=0.5 %.4f in_mask %.4f max %.3f top10cut %.3f%s%s%s\n" % (d, s["mean_prob"], s["mean_prob_in_mask"], s["frac_ge_0p5"], s["frac_ge_0p5_in_mask"], s["max_prob"], s["top10_cut_in_mask"],
                    " LOW" if s["LOW_flag"] else "", " HIGH" if s["HIGH_flag"] else "", "" if s["info_pearson_r_ds8_vs_label"] is None else " INFO_r_ds8=%.3f" % s["info_pearson_r_ds8_vs_label"]))
            if "scores" in v:
                sc = v["scores"]
                f.write("  scores: " + " ".join("%s AUC %.4f F0.5 %.4f;" % (t, sc[t]["auc"], sc[t]["f05_at_0p5"]) for t in list(MEMBERS) + ["ensemble"]) + " mean member AUC %.4f\n" % sc["mean_member_auc"])
        f.write("json sha256 %s\n" % sha256_file(jp))
    tgz = os.path.join(PROJ, "c4_maps_%s.tgz" % args.stamp)
    subprocess.run(["tar", "czf", tgz, "-C", PROJ, os.path.basename(out)], check=False)
    log("C4 MAPS COMPLETE: %s; tgz %s %d B sha256 %s" % (out, tgz, os.path.getsize(tgz), sha256_file(tgz)[:16]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:   # noqa: BLE001
        import traceback; traceback.print_exc()
        log("STOPPED: %s" % e)
        sys.exit(2)
