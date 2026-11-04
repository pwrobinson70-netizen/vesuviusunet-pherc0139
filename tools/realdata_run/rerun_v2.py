"""Brief 15 part D: re-run PR #17 real-data tasks 2-6 BEFORE (old behaviour) and AFTER (v0.2 defaults).
Usage: python tools/realdata_run/rerun_v2.py OUT_JSON   (PHerc. Paris 4 Scroll 1 slices + two tifxyz meshes in testdata/; CPU, a few minutes)
before = --global-pitch (ssc/ssf/auditor) and no --widen-low-coherence; after = the new defaults. Flags are otherwise the PR #17 ones."""
import glob, json, os, sys, tempfile
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
for d in ("common", "sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor", "realdata_run"):
    sys.path.insert(0, os.path.join(REPO, "tools", d))
import sheet_spacing_check as S, sheet_switch_finder as F, umbilicus_finder as UF, uf_io, trace_auditor as TA, ssc_io
from pad_meshes import pad_pair
from task6_break import make_broken
D = os.path.join(REPO, "testdata", "pherc_paris4_45um"); SL = D + "/slices"
A_DIR = glob.glob(D + "/*w116-117.tifxyz")[0]; B_DIR = glob.glob(D + "/*w118-119.tifxyz")[0]
HEIGHTS = (2073.0, 2600.0, 3128.0); VOX = 45.532
vol = ssc_io.PngVolume(SL, VOX, VOX)
out = {}
# ---- task 2: umbilicus_finder, --pitch-vox 8 as in PR #17, slice index relabelled to z
for label, kw in (("before", {}), ("after_widen", dict(widen_low_coherence=True))):
    uv = uf_io.open_volume(SL, "png", scale_xy=1.0)
    rows, summ = UF.run(uv, UF.Params(pitch_vox=8.0, **kw), z_start=0, z_stop=3, z_step=1)
    out.setdefault("task2", {})[label] = [dict(z=HEIGHTS[i], x=r["x"], y=r["y"], flag=r["flag"], confidence=r["confidence"],
                                                residual_pitch=r.get("residual_pitch")) for i, r in enumerate(rows)]
# ---- task 3: spacing check on the padded pair
tmp = tempfile.mkdtemp(); (pa, pb), _ = pad_pair(A_DIR, B_DIR, tmp)
Am, Bm = ssc_io.load_mesh(pa), ssc_io.load_mesh(pb)
for label, gp in (("before", True), ("after", False)):
    res = S.run_check(Am, Bm, vol, list(HEIGHTS), S.Params(global_pitch=gp), VOX)
    out.setdefault("task3", {})[label] = [{k: h.get(k) for k in ("z", "ct_pitch_vox", "mesh_pitch_vox", "clean_fraction", "shared_fraction",
        "skipped_fraction", "no_pitch_fraction", "pitch_mismatch_flag", "pitch_confidence_mean")} for h in res["heights"]]
    out["task3"][label + "_area_cm2"] = res["area"]["clean_area_cm2"]
# ---- task 4: switch finder per mesh (originals)
A, B = ssc_io.load_mesh(A_DIR), ssc_io.load_mesh(B_DIR)
for label, gp in (("before", True), ("after", False)):
    for nm, M in (("w116-117", A), ("w118-119", B)):
        r = F.run_finder(M, vol, list(HEIGHTS), F.Params(global_pitch=gp))
        out.setdefault("task4", {}).setdefault(label, {})[nm] = dict(
            pitch=[h["ct_pitch_vox"] for h in r["heights"]], tracked=[h["fraction_tracked"] for h in r["heights"]],
            n_switches=r["summary"]["n_switches"], n_conf03=sum(s["confidence"] >= 0.3 for s in r["switches"]),
            n_conf05=sum(s["confidence"] >= 0.5 for s in r["switches"]))
# ---- task 5: auditor on the pair with the PR #17 estimated centre file
cp = json.load(open(os.path.join(HERE, "out", "umbilicus_estimated.json")))["control_points"]
centre = TA.Centre(*(np.array([c[k] for c in cp], float) for k in ("z", "y", "x")), "estimated", np.inf)
def audit(meshes, **kw):
    p = TA.Params(**kw)
    r = TA.audit(meshes, vol, list(HEIGHTS), centre, p, F.Params(vertical=1), S.Params(band_height_vox=1.0 if False else None))
    return [dict(name=t["name"], verdict=t["verdict"], judged_fraction=t.get("judged_fraction"),
                 checks={c["check"]: c["status"] for c in t["checks"]},
                 n_jumps=sum(len(w.get("jumps", [])) for c in t["checks"] if c["check"] == "winding_jumps" for w in c.get("heights", [])),
                 n_switch_fail=len(next((c.get("switches", []) for c in t["checks"] if c["check"] == "switch_finder"), []))) for t in r["traces"]]
for label, kw in (("before", dict(global_pitch=True)), ("after", {})):
    out.setdefault("task5", {})[label] = dict(pair=audit([A, B], **kw), A_alone=audit([A], **kw), B_alone=audit([B], **kw))
# ---- task 6: deliberate break (col > 120 moved outward 9.5 vox)
bro, _ = make_broken(tempfile.mkdtemp(), 120, 9.5); Br = ssc_io.load_mesh(bro)
for label, gp in (("before", True), ("after", False)):
    for pv in (None, 9.5):
        for nm, M in (("original", A), ("broken", Br)):
            hits, allsw, n03 = [], 0, 0
            r = F.run_finder(M, vol, list(HEIGHTS), F.Params(global_pitch=gp, pitch_vox=pv))
            for s in r["switches"]:
                allsw += 1; n03 += s["confidence"] >= 0.3
                if s["kind"] == "horizontal" and abs(s["col"] - 120) <= 6:
                    hits.append((s["height"], s["col"], round(s["step"], 2), round(s["confidence"], 2)))
            out.setdefault("task6_switch", {}).setdefault(label, {}).setdefault("pitch_" + str(pv), {})[nm] = dict(n=allsw, n_conf03=int(n03), near_col120=hits)
    for nm, M in (("original", A), ("broken", Br)):
        out.setdefault("task6_auditor", {}).setdefault(label, {})[nm] = audit([M], **(dict(global_pitch=True) if gp else {}))
json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
print("written", sys.argv[1])
