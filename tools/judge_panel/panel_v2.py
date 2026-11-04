#!/usr/bin/env python3
"""panel_v2: a prediction-first judge panel for tifxyz traces.  (MIT)

    vun-panel2 TRACE --pred-png-dir DIR --ct-png-dir DIR --heights z1,z2,.. [--umbilicus J] [--threshold T] [--out-json F]
    vun-panel2 --batch GROUNDTRUTH_DIR NEGATIVES_DIR --out raw.csv [--jobs 4]      # raw votes for 40 originals + 4 x 40 broken copies

The verdict (brief 27) is built around the organisers' surface prediction, because on the verified Scroll 1 patches that was the only signal
that separated originals from broken copies (AUC 0.938, docs/REALDATA_2X2.md):

  REQUIRED vote   surface_agreement: ON-PREDICTED-SHEET fraction of the judged cut-line points, over all given heights.
                  fraction >= T -> pass; below T -> the trace FAILS. Fewer than --min-judged judged points -> no required vote.
  ADVISORY votes  the CT checks, run on the (densified) trace: trace_auditor (local-pitch), trace_auditor --global-pitch, sheet_switch_finder.
                  They are always reported. They cannot fail a trace alone: the trace FAILS on them only when at least
                  --advisory-k (default 2) of the three FAIL. NOT JUDGED counts as no vote.

  verdict = FAIL        if the required vote fails, or at least k advisory votes fail
          = NOT JUDGED  if the required vote could not be made and the advisory votes did not fail it
          = PASS        otherwise

T (DEFAULT_T) was chosen on the first 40 verified patches and their 160 broken copies only (results/panel_v2_threshold_study.csv); the
second set (testdata/pherc_paris4_groundtruth_b) is held out. Feed it densified traces (vun-densify): the CT checks were built for dense traces.
Exit code 0 (verdict is in the output), 2 bad input.
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
for _d in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor", "crush_map", "label_drift",
           "surface_agreement", "common", "groundtruth_score"):
    sys.path.insert(0, os.path.join(_TOOLS, _d))

__version__ = "0.1.0"
PASS, FAIL, NJ = "PASS", "FAIL", "NOT JUDGED"
ADVISORY = ("audit_default", "audit_global", "switch")
DEFAULT_T = 0.415         # chosen on the tune set only (first 40 verified patches + 160 broken copies): results/panel_v2_threshold_study.csv
MIN_JUDGED = 10
MIN_SWITCH_CONF = 0.3      # the auditor's own switch-finder FAIL line
WN_JUMP_PITCH = 0.6
VOX = "9.6"
CASE_TIMEOUT_S = 600


def _quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return fn(argv)


def decide(row, threshold=DEFAULT_T, advisory_k=2, min_judged=MIN_JUDGED):
    """Pure verdict from raw votes. row needs surface_on_fraction, surface_judged and the three advisory verdict fields.
    Returns (verdict, required_vote, n_advisory_fail, reason)."""
    f, n = row.get("surface_on_fraction"), row.get("surface_judged")
    f = None if f in (None, "") else float(f)
    n = 0 if n in (None, "") else int(float(n))
    if f is None or n < min_judged:
        req = NJ
    else:
        req = PASS if f >= threshold else FAIL
    nfail = sum(1 for k in ADVISORY if row.get(k) == FAIL)
    if req == FAIL:
        return FAIL, req, nfail, f"surface on-sheet fraction {f:.3f} < T {threshold:g}"
    if nfail >= advisory_k:
        return FAIL, req, nfail, f"{nfail} of {len(ADVISORY)} advisory CT checks fail"
    if req == NJ:
        return NJ, req, nfail, f"surface prediction judged {n} points (< {min_judged})"
    return PASS, req, nfail, f"surface on-sheet fraction {f:.3f} >= T {threshold:g}"


def _alarm(_s, _f):
    raise TimeoutError("case timeout")


def auto_point_scale(mesh_dir):
    """Column factor recorded by vun-densify in meta.json (densify_note), else 1: the CT checks count cut-line points, and a densified
    trace has that many times more of them per voxel (docs/PANEL_V2.md: unscaled they fail 38 of 40 verified patches)."""
    try:
        with open(os.path.join(mesh_dir, "meta.json")) as fh:
            return max(1, int(json.load(fh)["densify_note"]["factor_cols"]))
    except (OSError, KeyError, ValueError, TypeError):
        return 1


def collect(job):
    """Run the required check and the advisory checks once. job: dict(mesh, ct, pred, umb, heights[, patch, kind]). Returns a flat row."""
    import trace_auditor as ta
    import sheet_switch_finder as ssf
    import surface_agreement as sa
    row = {k: job[k] for k in ("patch", "kind") if k in job}
    ps = int(job.get("point_scale") or 0) or auto_point_scale(job["mesh"])   # point-count parameters of the CT checks, multiplied for a densified grid
    ssf_p, ta_p = ssf.Params(), ta.Params()

    def _odd(n):
        return n if n % 2 else n + 1
    ssf_extra = [] if ps == 1 else ["--k-points", str(ssf_p.k_points * ps), "--median-window", str(_odd(ssf_p.median_window * ps)),
                                    "--max-lost-points", str(ssf_p.max_lost_points * ps),
                                    "--pitch-smooth-points", str(_odd(ssf_p.pitch_smooth_points * ps))]
    ta_extra = [] if ps == 1 else ["--ssf-k-points", str(ssf_p.k_points * ps), "--ssf-median-window", str(_odd(ssf_p.median_window * ps)),
                                   "--ssf-max-lost-points", str(ssf_p.max_lost_points * ps),
                                   "--wn-window-min-points", str(ta_p.wn_window_min_points * ps), "--wn-min-points", str(ta_p.wn_min_points * ps)]
    hs = ",".join(str(h) for h in job["heights"])
    ct = ["--png-dir", job["ct"], "--png-pixel-um", VOX, "--voxel-size-um", VOX, "--heights", hs]
    tmp = tempfile.mkdtemp(prefix="pv2_")
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(CASE_TIMEOUT_S)
    try:
        try:                                                    # REQUIRED: the prediction
            o = os.path.join(tmp, "sa")
            _quiet(sa.main, [job["mesh"], "--pred-png-dir", job["pred"], "--ct-png-dir", job["ct"], "--png-pixel-um", VOX,
                             "--voxel-size-um", VOX, "--heights", hs, "--out-dir", o, "--png-scale", "1"])
            with open(os.path.join(o, "report.json")) as fh:
                t = json.load(fh)["traces"][0]
            f = t["pred_on_fraction"]
            row["surface_on_fraction"] = None if f is None else round(float(f), 5)
            row["surface_judged"] = t["pred_on"] + t["pred_off"]
        except Exception as e:  # noqa: BLE001
            row["surface_on_fraction"], row["surface_judged"], row["surface_error"] = None, 0, repr(e)[:120]
        for tag, extra in (("audit_default", []), ("audit_global", ["--global-pitch"])):   # ADVISORY: trace_auditor
            try:
                o = os.path.join(tmp, tag)
                argv = [job["mesh"], *ct, "--out-dir", o, "--min-switch-confidence", str(MIN_SWITCH_CONF),
                        "--wn-jump-pitch", str(WN_JUMP_PITCH), *ta_extra, *extra]
                if job.get("umb"):
                    argv += ["--umbilicus", job["umb"]]
                _quiet(ta.main, argv)
                with open(os.path.join(o, "audit.json")) as fh:
                    tr = json.load(fh)["result"]["traces"][0]
                st = {c["check"]: c["status"] for c in tr["checks"]}
                row[tag] = tr["verdict"]
                row[tag + "_failed_by"] = ";".join(k for k, v in st.items() if v == FAIL)
                row[tag + "_not_judged_by"] = ";".join(k for k, v in st.items() if v == NJ)
            except Exception as e:  # noqa: BLE001
                row[tag], row[tag + "_failed_by"] = "ERROR", repr(e)[:120]
        try:                                                    # ADVISORY: sheet_switch_finder
            o = os.path.join(tmp, "ssf.json")
            _quiet(ssf.main, [job["mesh"], *ct, *ssf_extra, "--out-json", o])
            with open(o) as fh:
                r = json.load(fh)["result"]
            confs = [s["confidence"] for s in r["switches"]]
            mc = max(confs) if confs else 0.0
            row["switch_max_conf"] = round(float(mc), 4)
            row["switch"] = FAIL if mc >= MIN_SWITCH_CONF else PASS
        except Exception as e:  # noqa: BLE001
            row["switch"], row["switch_error"] = "ERROR", repr(e)[:120]
    except TimeoutError:
        row["error"] = "timeout"
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return row


def collect_batch(root, neg, jobs_n=4, only_patches=None, only_kinds=None, point_scale=0):
    """Raw votes for the originals of a ground-truth root and their broken copies (same layout as groundtruth_score/score.py)."""
    import score as gscore
    with tempfile.TemporaryDirectory(prefix="pv2_umb_") as umb_dir:
        js = gscore.build_jobs(root, neg, 0.3, 0.8, 0.6, umb_dir, only_patches, only_kinds)
        jobs = [dict(patch=j["patch"], kind=j["kind"], mesh=j["mesh"], ct=j["ct"], pred=j["pred"], umb=j["umb"], heights=j["heights"], point_scale=point_scale)
                for j in js]
        if jobs_n <= 1:
            return [collect(j) for j in jobs]
        with cf.ProcessPoolExecutor(jobs_n) as ex:
            return list(ex.map(collect, jobs, chunksize=1))


def write_rows(rows, path):
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trace", nargs="?", help="tifxyz folder (densified)")
    ap.add_argument("--pred-png-dir", help="surface prediction PNGs (named by height)")
    ap.add_argument("--ct-png-dir", help="CT slice PNGs (named by height)")
    ap.add_argument("--heights", help="comma-separated heights (z, volume voxels)")
    ap.add_argument("--umbilicus", help="centre line JSON (optional; enables the winding-jump check of the auditor)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_T, help="T: required on-sheet fraction (default %(default)s)")
    ap.add_argument("--advisory-k", type=int, default=2, help="advisory FAILs needed to fail a trace on them alone (default 2)")
    ap.add_argument("--out-json")
    ap.add_argument("--batch", nargs=2, metavar=("GROUNDTRUTH_DIR", "NEGATIVES_DIR"))
    ap.add_argument("--out", help="batch: raw-votes CSV")
    ap.add_argument("--point-scale", type=int, default=0,
                    help="multiply the CT checks' point-count parameters (k-points, windows, min points) by this; 0 (default) = the densify factor recorded in the trace's meta.json, else 1")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    if a.batch:
        if not a.out:
            ap.error("--batch needs --out")
        rows = collect_batch(a.batch[0], a.batch[1], a.jobs, point_scale=a.point_scale)
        write_rows(rows, a.out)
        print(json.dumps(dict(cases=len(rows), out=a.out)))
        return 0
    if not (a.trace and a.pred_png_dir and a.ct_png_dir and a.heights):
        ap.error("TRACE, --pred-png-dir, --ct-png-dir and --heights are required (or use --batch)")
    if not (0.0 <= a.threshold <= 1.0) or a.advisory_k < 1:
        print("error: --threshold must be in [0, 1] and --advisory-k >= 1", file=sys.stderr)
        return 2
    try:
        hs = [float(v) for v in a.heights.split(",") if v]
    except ValueError:
        print("error: --heights must be numbers", file=sys.stderr)
        return 2
    row = collect(dict(mesh=a.trace, ct=a.ct_png_dir, pred=a.pred_png_dir, umb=a.umbilicus, point_scale=a.point_scale, heights=[int(h) if h == int(h) else h for h in hs]))
    v, req, nfail, why = decide(row, a.threshold, a.advisory_k)
    out = dict(tool="vun-panel2", version=__version__, threshold=a.threshold, advisory_k=a.advisory_k, verdict=v, required_vote=req,
               advisory_fail_count=nfail, reason=why, votes=row)
    if a.out_json:
        with open(a.out_json, "w") as fh:
            json.dump(out, fh, indent=2)
    print(f"{v}: {why} (required={req}; advisory FAIL {nfail}/{len(ADVISORY)}: "
          + ", ".join(f"{k}={row.get(k)}" for k in ADVISORY) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
