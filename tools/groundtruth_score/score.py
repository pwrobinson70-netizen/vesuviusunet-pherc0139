"""score: run the checking panel on the verified Scroll 1 patches and on their deliberately broken copies.  (MIT)

    python score.py GROUNDTRUTH_DIR NEGATIVES_DIR --out results/groundtruth_panel_scores.csv [--jobs 4]
        [--min-switch-confidence 0.3] [--wn-jump-pitch 0.6] [--surface-pass-on-fraction 0.8]

This is the minimal scorer (Brief 25's own scorer was not on origin when this was written). One row per case = 40 originals + 40 x 4
negatives (NEGATIVES_DIR/<patch>/<kind>/, from make_negatives.py). Every case is judged against the ORIGINAL patch's CT slices and
surface prediction (the broken copies keep the same window and heights). The panel, per case, with every tool at its default unless a flag
above says otherwise:

  audit_default   trace_auditor, local-pitch mode (the default)            verdict PASS / FAIL / NOT JUDGED
  audit_global    trace_auditor --global-pitch (the old pitch handling)    verdict
  switch          sheet_switch_finder, FAIL = a switch of confidence >= --min-switch-confidence (the auditor's own rule)
  spacing         sheet_spacing_check of the patch against ITSELF (the tool needs a pair; a single patch has no neighbour).
                  Recorded for completeness only; it is degenerate (see docs/REALDATA_2X2.md) and is NOT part of the panel.
  surface         surface_agreement, trace PASS if ON-PREDICTED-SHEET fraction >= --surface-pass-on-fraction, NOT JUDGED if
                  fewer than 10 points judged, else FAIL (same rule the tool applies per height)

The centre line is the spiral dataset's umbilicus shifted by the patch window origin. A NOT JUDGED verdict counts as "not detected" in
the 2x2 tables (it is reported separately).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import csv
import io
import json
import os
import signal
import sys
import tempfile

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _d in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor", "crush_map", "label_drift",
           "surface_agreement", "common"):
    sys.path.insert(0, os.path.join(_TOOLS, _d))

KINDS = ("original", "shift-half", "shift-full", "switch-mid", "scramble")
PASS, FAIL, NJ = "PASS", "FAIL", "NOT JUDGED"
VOX = "9.6"
CASE_TIMEOUT_S = 600


def _quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn(argv)
    return rc


def _alarm(_s, _f):
    raise TimeoutError("case timeout")


def score_case(job):
    """job: dict(patch, kind, mesh, ct, pred, umb, heights, min_conf, pass_on). Returns a flat result dict."""
    import trace_auditor as ta
    import sheet_switch_finder as ssf
    import sheet_spacing_check as ssc
    import surface_agreement as sa
    has_alarm = hasattr(signal, "SIGALRM")  # POSIX only; Windows has no SIGALRM, so the per-case timeout is skipped there
    if has_alarm:
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(CASE_TIMEOUT_S)
    row = dict(patch=job["patch"], kind=job["kind"])
    hs = ",".join(str(h) for h in job["heights"])
    ct = ["--png-dir", job["ct"], "--png-pixel-um", VOX, "--voxel-size-um", VOX, "--heights", hs]
    tmp = tempfile.mkdtemp(prefix="gts_")
    try:
        # --- trace_auditor, both pitch modes
        for tag, extra in (("audit_default", []), ("audit_global", ["--global-pitch"])):
            try:
                o = os.path.join(tmp, tag)
                _quiet(ta.main, [job["mesh"], *ct, "--umbilicus", job["umb"], "--out-dir", o,
                                 "--min-switch-confidence", str(job["min_conf"]),
                                 "--wn-jump-pitch", str(job["wn_jump"]), *extra])
                with open(os.path.join(o, "audit.json")) as fh:
                    t = json.load(fh)["result"]["traces"][0]
                st = {c["check"]: c["status"] for c in t["checks"]}
                row[tag] = t["verdict"]
                row[tag + "_checks"] = ";".join(f"{k}={v}" for k, v in st.items())
                row[tag + "_failed_by"] = ";".join(k for k, v in st.items() if v == FAIL)
                row[tag + "_other_fail"] = int(any(v == FAIL for k, v in st.items() if k != "switch_finder"))
                row[tag + "_judged_fraction"] = round(float(t.get("judged_fraction") or 0.0), 4)
            except Exception as e:  # noqa: BLE001
                row[tag], row[tag + "_checks"] = "ERROR", repr(e)[:120]
        # --- switch finder (standalone)
        try:
            o = os.path.join(tmp, "ssf.json")
            _quiet(ssf.main, [job["mesh"], *ct, "--out-json", o])
            with open(o) as fh:
                r = json.load(fh)["result"]
            confs = [s["confidence"] for s in r["switches"]]
            mc = max(confs) if confs else 0.0
            row["switch_max_conf"] = round(float(mc), 4)
            row["switch_n"] = len(confs)
            row["switch_fraction_tracked"] = round(float(r["summary"]["fraction_tracked"]), 4)
            row["switch"] = FAIL if mc >= job["min_conf"] else PASS
        except Exception as e:  # noqa: BLE001
            row["switch"] = "ERROR"
            row["switch_error"] = repr(e)[:120]
        # --- spacing check against itself (degenerate; not in the panel)
        try:
            o = os.path.join(tmp, "ssc.json")
            _quiet(ssc.main, [job["mesh"], job["mesh"], *ct, "--out-json", o])
            with open(o) as fh:
                r = json.load(fh)
            hh = r["result"]["heights"]
            nflag = sum(1 for h in hh if h.get("pitch_mismatch_flag"))
            on = [h["onsheet_fraction_a"] for h in hh if h.get("onsheet_fraction_a") is not None]
            row["spacing_flagged_heights"] = nflag
            row["spacing_onsheet_fraction"] = round(sum(on) / len(on), 4) if on else None
            row["spacing"] = FAIL if nflag else PASS
        except Exception as e:  # noqa: BLE001
            row["spacing"] = "ERROR"
            row["spacing_error"] = repr(e)[:120]
        # --- surface agreement
        try:
            o = os.path.join(tmp, "sa")
            _quiet(sa.main, [job["mesh"], "--pred-png-dir", job["pred"], "--ct-png-dir", job["ct"], "--png-pixel-um", VOX,
                             "--voxel-size-um", VOX, "--heights", hs, "--out-dir", o, "--png-scale", "1"])
            with open(os.path.join(o, "report.json")) as fh:
                t = json.load(fh)["traces"][0]
            judged = t["pred_on"] + t["pred_off"]
            f = t["pred_on_fraction"]
            row["surface_on_fraction"] = None if f is None else round(float(f), 4)
            row["surface_judged"] = judged
            row["surface_agreement"] = None if t.get("agreement_fraction") is None else round(float(t["agreement_fraction"]), 4)
            row["surface"] = NJ if judged < 10 or f is None else (PASS if f >= job["pass_on"] else FAIL)
        except Exception as e:  # noqa: BLE001
            row["surface"] = "ERROR"
            row["surface_error"] = repr(e)[:120]
    except TimeoutError:
        row["error"] = "timeout"
    finally:
        if has_alarm:
            signal.alarm(0)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return row


def shifted_umbilicus(root, window, path):
    with open(os.path.join(root, "umbilicus_9p6um.json")) as fh:
        u = json.load(fh)
    for c in u["control_points"]:
        c["x"] -= window["x0"]
        c["y"] -= window["y0"]
    with open(path, "w") as fh:
        json.dump(u, fh)


def build_jobs(root, neg, min_conf, pass_on, wn_jump, umb_dir, only_patches=None, only_kinds=None):
    from make_negatives import list_patches
    jobs = []
    for p in list_patches(root):
        if only_patches and p not in only_patches:
            continue
        pd = os.path.join(root, "patches", p)
        with open(os.path.join(pd, "mesh.tifxyz", "meta.json")) as fh:
            w = json.load(fh)["window"]
        umb = os.path.join(umb_dir, p + ".json")
        shifted_umbilicus(root, w, umb)
        for k in KINDS:
            if only_kinds and k not in only_kinds:
                continue
            mesh = os.path.join(pd, "mesh.tifxyz") if k == "original" else os.path.join(neg, p, k)
            if not os.path.isdir(mesh):
                continue
            jobs.append(dict(patch=p, kind=k, mesh=mesh, ct=os.path.join(pd, "slices"), pred=os.path.join(pd, "surfpred"),
                             umb=umb, heights=w["heights"], min_conf=min_conf, pass_on=pass_on, wn_jump=wn_jump))
    return jobs


def run(root, neg, out, jobs_n=4, min_conf=0.3, pass_on=0.8, wn_jump=0.6, only_patches=None, only_kinds=None):
    with tempfile.TemporaryDirectory(prefix="gts_umb_") as umb_dir:
        jobs = build_jobs(root, neg, min_conf, pass_on, wn_jump, umb_dir, only_patches, only_kinds)
        rows = []
        if jobs_n <= 1:
            rows = [score_case(j) for j in jobs]
        else:
            with cf.ProcessPoolExecutor(jobs_n) as ex:
                rows = list(ex.map(score_case, jobs, chunksize=1))
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("groundtruth_dir")
    ap.add_argument("negatives_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--min-switch-confidence", type=float, default=0.3)
    ap.add_argument("--wn-jump-pitch", type=float, default=0.6)
    ap.add_argument("--surface-pass-on-fraction", type=float, default=0.8)
    ap.add_argument("--patch", action="append")
    ap.add_argument("--kind", action="append", choices=KINDS)
    a = ap.parse_args(argv)
    from make_negatives import check_readme
    check_readme(a.groundtruth_dir)
    rows = run(a.groundtruth_dir, a.negatives_dir, a.out, a.jobs, a.min_switch_confidence, a.surface_pass_on_fraction, a.wn_jump_pitch, a.patch, a.kind)
    print(json.dumps(dict(cases=len(rows), out=a.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
