#!/usr/bin/env python3
"""judge_panel: run every available judge on one trace (and optionally its neighbour) and compare them region by region. (MIT)

Judges run (each through its own command line, so the panel adds no logic to them):
  trace_auditor          with its sub-checks as separate columns: switch_finder, winding_jumps, spacing / winding_offset (neighbour given),
                         windcheck (when tools/upstream/windcheck is present), pitch_confidence
  sheet_switch_finder    stand-alone run (the auditor's switch_finder column uses the same code; it is listed separately on purpose)
  sheet_spacing_check    stand-alone run, only when a neighbour is given
  texture_judge          the fibre-texture judge: a different signal from every one above (they all start from bright peaks along the normal)

A REGION is one cut-line height z and a window of `--region-cols` grid columns, the same cut lines and columns the other tools report.
Judges that localise to a column vote per region; judges that only give a verdict per height (spacing, winding_offset) vote on every region of
that height; judges that only give one verdict per trace (windcheck, pitch_confidence) are shown separately and enter the trace verdict.

Panel verdict per region: PASS only if every judge that could judge says PASS; FAIL if the judges that could judge say FAIL and none says PASS;
NOT JUDGED if no judge could judge OR the judges are split (some PASS, some FAIL: listed as "X says A, Y says B"; --on-disagreement fail turns a split into FAIL).
Trace verdict: FAIL if any region or any trace-level judge is FAIL, else NOT JUDGED if any region is a split or nothing could be judged, else PASS.

Exit code 0 = PASS, 1 = FAIL, 2 = bad input, 4 = NOT JUDGED.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_TOOLS, "sheet_spacing_check"))
from ssc_io import InputError, load_mesh  # noqa: E402

__version__ = "0.1.0"
PASS, FAIL, NJ = "PASS", "FAIL", "NOT JUDGED"
SCRIPTS = dict(
    auditor=os.path.join(_TOOLS, "trace_auditor", "trace_auditor.py"),
    finder=os.path.join(_TOOLS, "sheet_switch_finder", "sheet_switch_finder.py"),
    spacing=os.path.join(_TOOLS, "sheet_spacing_check", "sheet_spacing_check.py"),
    texture=os.path.join(_TOOLS, "texture_judge", "texture_judge.py"),
)
WINDCHECK = os.path.join(_TOOLS, "upstream", "windcheck", "ct_aware_check.py")


@dataclass
class Params:
    region_cols: int = 16                # grid columns per region
    min_switch_confidence: float = 0.3   # a switch finder switch counts as FAIL at or above this (the auditor's own default)
    min_tracked_fraction: float = 0.6    # the switch finder judges a height only if it followed this fraction of the line
    min_clean_fraction: float = 0.8      # spacing: a height is PASS at or above this clean fraction
    min_pitch_confidence: float = 0.3    # spacing: a height whose local pitch confidence is below this is NOT JUDGED
    texture_blurred_fraction: float = 0.5  # texture: a region is FAIL if more than this fraction of its cut-line points is BLURRED
    texture_on_fraction: float = 0.5     # texture: a region is PASS if at least this fraction is ON-SHEET-TEXTURED (and none BREAK)
    on_disagreement: str = "not-judged"  # a region whose judges are split (PASS vs FAIL): "not-judged" or "fail"
    timeout: float = 3600.0              # per judge command (seconds)


# ------------------------------------------------------------------------------------------------------------- running the judges
def _run(cmd, timeout, ok_codes):
    p = subprocess.run([sys.executable, *map(str, cmd)], capture_output=True, text=True, timeout=timeout)
    if p.returncode not in ok_codes:
        raise InputError(f"{os.path.basename(str(cmd[0]))} failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-600:]}")
    return p


def _vol_args(a):
    if a.get("zarr"):
        return ["--zarr", a["zarr"], "--zarr-level", a.get("zarr_level", 0)]
    out = ["--png-dir", a["png_dir"]]
    for k, f in (("png_pixel_um", "--png-pixel-um"), ("voxel_size_um", "--voxel-size-um"), ("png_pattern", "--png-pattern")):
        if a.get(k):
            out += [f, a[k]]
    return out


def run_judges(trace, neighbour, vol, heights, out_dir, p: Params, umbilicus=None, windcheck=None, pitch_vox=None,
               extra=None, log=None, judges=("auditor", "finder", "spacing", "texture")):
    """Run every judge, return {name: parsed JSON / error string}. vol = dict(zarr=..., zarr_level=..., png_dir=..., png_pixel_um=..., voxel_size_um=...)."""
    log = log or (lambda m: None)
    extra = extra or {}
    os.makedirs(out_dir, exist_ok=True)
    H = ",".join(f"{h:g}" for h in heights)
    va = _vol_args(vol)
    res = {}
    # trace_auditor (+ windcheck sub-check when the tool is present)
    use_wc = (os.path.isfile(WINDCHECK) if windcheck is None else windcheck)
    cmd = [SCRIPTS["auditor"], trace] + ([neighbour] if neighbour else []) + va + ["--heights", H, "--out-dir", os.path.join(out_dir, "auditor")]
    if umbilicus:
        cmd += ["--umbilicus", umbilicus]
    if pitch_vox:
        cmd += ["--pitch-vox", pitch_vox]
    if use_wc:
        cmd += ["--windcheck"]
    cmd += shlex.split(extra.get("auditor", ""))
    if "auditor" in judges:
        log("trace_auditor")
        try:
            _run(cmd, p.timeout, (0, 1, 4))
            res["auditor"] = json.load(open(os.path.join(out_dir, "auditor", "audit.json")))["result"]
        except (InputError, OSError, subprocess.TimeoutExpired) as e:
            res["auditor"] = f"error: {e}"
    # stand-alone switch finder
    cmd = [SCRIPTS["finder"], trace] + va + ["--heights", H, "--out-json", os.path.join(out_dir, "finder.json"), "--out-txt", os.path.join(out_dir, "finder.txt")]
    if pitch_vox:
        cmd += ["--pitch-vox", pitch_vox]
    cmd += shlex.split(extra.get("finder", ""))
    if "finder" in judges:
        log("sheet_switch_finder")
        try:
            _run(cmd, p.timeout, (0, 1, 4))
            res["finder"] = json.load(open(os.path.join(out_dir, "finder.json")))["result"]
        except (InputError, OSError, subprocess.TimeoutExpired) as e:
            res["finder"] = f"error: {e}"
    # stand-alone spacing check
    if neighbour and "spacing" in judges:
        cmd = [SCRIPTS["spacing"], trace, neighbour] + va + ["--heights", H, "--out-json", os.path.join(out_dir, "spacing.json"), "--out-txt", os.path.join(out_dir, "spacing.txt")]
        cmd += shlex.split(extra.get("spacing", ""))
        log("sheet_spacing_check")
        try:
            _run(cmd, p.timeout, (0, 1, 4))
            res["spacing"] = json.load(open(os.path.join(out_dir, "spacing.json")))["result"]
        except (InputError, OSError, subprocess.TimeoutExpired) as e:
            res["spacing"] = f"error: {e}"
    # texture judge
    cmd = [SCRIPTS["texture"], trace] + va + ["--heights", H, "--out-dir", os.path.join(out_dir, "texture"), "--no-png"] + shlex.split(extra.get("texture", ""))
    if "texture" in judges:
        log("texture_judge")
        try:
            _run(cmd, p.timeout, (0, 1, 4))
            res["texture"] = json.load(open(os.path.join(out_dir, "texture", "texture_judge.json")))
        except (InputError, OSError, subprocess.TimeoutExpired) as e:
            res["texture"] = f"error: {e}"
    res["_windcheck_run"] = bool(use_wc)
    return res


# ------------------------------------------------------------------------------------------------------------- per-judge region verdicts
def _v(verdict, detail):
    return dict(verdict=verdict, detail=detail)


def _in(col, c0, c1):
    return c0 <= col < c1


def texture_region(res, z, c0, c1, p: Params):
    if isinstance(res, str):
        return _v(NJ, res)
    cl = next((c for c in res["cut_lines"] if c["z"] == z), None)
    if not cl or not cl["n_points"]:
        return _v(NJ, (cl or {}).get("note") or "no cut line here")
    vs = [v for c, v in zip(cl["col"], cl["verdict"]) if _in(c, c0, c1)]
    if not vs:
        return _v(NJ, "no cut-line point in this region")
    n = len(vs)
    brk = [b for b in cl.get("breaks", []) if c0 <= b["grid_col"] < c1]            # a break belongs to the region holding its centre
    nl, no = vs.count("BLURRED"), vs.count("ON-SHEET-TEXTURED")
    d = f"{no} on-sheet, {nl} BLURRED, {n - no - nl} other of {n} points" + (
        f"; BREAK at col {brk[0]['grid_col']:.0f} (orientation jump {brk[0]['jump_deg']:.0f} deg)" if brk else "")
    if brk or nl / n > p.texture_blurred_fraction:
        return _v(FAIL, d)
    if no / n >= p.texture_on_fraction:
        return _v(PASS, d)
    return _v(NJ, d)


def _switch_region(switches, rec, z, c0, c1, p: Params, name):
    if rec is None:
        return _v(NJ, f"no {name} record for this height")
    bad = [s for s in switches if s.get("height") == z and _in(s["col"], c0, c1) and s["confidence"] >= p.min_switch_confidence]
    if bad:
        s = bad[0]
        return _v(FAIL, f"{s['kind']} switch at col {s['col']} row {s['row']:.1f} ({s['direction']}, step {s['step']:+.2f} pitch, confidence {s['confidence']:.2f})")
    if rec.get("n_points", 1) == 0 or rec.get("note") or rec.get("fraction_tracked", 1.0) < p.min_tracked_fraction:
        return _v(NJ, rec.get("note") or f"tracked only {rec.get('fraction_tracked', 0):.2f} of the line")
    return _v(PASS, "no switch")


def finder_region(res, z, c0, c1, p: Params):
    if isinstance(res, str):
        return _v(NJ, res)
    rec = next((r for r in res["heights"] if r["z"] == z), None)
    return _switch_region(res["switches"], rec, z, c0, c1, p, "finder")


def _check(trace_rep, name):
    return next((c for c in trace_rep["checks"] if c["check"] == name), None)


def auditor_switch_region(res, z, c0, c1, p: Params):
    if isinstance(res, str):
        return _v(NJ, res)
    t = res["traces"][0]
    c = _check(t, "switch_finder")
    h = next((h for h in t["heights"] if h["z"] == z), None)
    if c is None or h is None:
        return _v(NJ, "no switch_finder check")
    bad = [s for s in c.get("switches", []) if s["height"] == z and _in(s["col"], c0, c1)]
    if bad:
        s = bad[0]
        return _v(FAIL, f"{s['kind']} switch at col {s['col']} row {s['row']:.1f} ({s['direction']}, step {s['step']:+.2f} pitch, confidence {s['confidence']:.2f})")
    if c["status"] == NJ or h["tracked"] < p.min_tracked_fraction or not h.get("judged_fraction"):
        return _v(NJ, f"tracked {h['tracked']:.2f}, judged {h.get('judged_fraction') or 0:.2f} of the line")
    return _v(PASS, "no switch")


def auditor_jumps_region(res, z, c0, c1, p: Params):
    if isinstance(res, str):
        return _v(NJ, res)
    c = _check(res["traces"][0], "winding_jumps")
    if c is None:
        return _v(NJ, "no winding_jumps check")
    bad = [j for j in c.get("jumps", []) if j["z"] == z and _in(j["col"], c0, c1)]
    if bad:
        j = bad[0]
        return _v(FAIL, f"radius jumps {j['step_pitches']:+.2f} pitch at col {j['col']}, angle {j['angle_deg']:.0f} deg")
    row = next((r for r in c.get("heights", []) if r["z"] == z), None)
    if row is None or row["status"] == NJ:
        return _v(NJ, (row or {}).get("reason", "no winding result for this height"))
    return _v(PASS, "no radius jump")


def spacing_height(res, z, p: Params):
    if isinstance(res, str):
        return _v(NJ, res)
    r = next((h for h in res["heights"] if h["z"] == z), None)
    if r is None or not r["n_points_a"] or not r["n_points_b"]:
        return _v(NJ, "no cut line on one of the two traces")
    if r.get("pitch_confidence_mean", 1.0) < p.min_pitch_confidence:
        return _v(NJ, f"local pitch confidence {r['pitch_confidence_mean']:.2f} < {p.min_pitch_confidence:g}")
    d = f"clean {100 * r['clean_fraction']:.0f}%, shared {100 * r['shared_fraction']:.0f}%, skipped {100 * r['skipped_fraction']:.0f}%"
    return _v(PASS if r["clean_fraction"] >= p.min_clean_fraction else FAIL, d)


def offset_height(res, z, p: Params):
    if isinstance(res, str) or res.get("pair") is None:
        return _v(NJ, "no neighbour" if not isinstance(res, str) else res)
    row = next((r for r in res["pair"]["winding_offset"].get("heights", []) if r["z"] == z), None)
    if row is None or row["status"] == NJ:
        return _v(NJ, (row or {}).get("reason", "no result"))
    if row["status"] == FAIL:
        return _v(FAIL, f"B is {row['median_offset_pitches']:+.2f} pitch from A, {100 * row['adjacent_fraction']:.0f}% adjacent")
    return _v(PASS, f"B is an adjacent sheet (median {row['median_offset_pitches']:+.2f} pitch)")


def trace_level(res):
    """Judges that give one verdict per trace: windcheck, pitch_confidence (only present when it raised NOT JUDGED)."""
    out = {}
    a = res.get("auditor")
    if isinstance(a, str):
        out["auditor"] = _v(NJ, a)
        return out
    t = a["traces"][0]
    for name in ("windcheck", "pitch_confidence"):
        c = _check(t, name)
        if c is not None:
            out["auditor:" + name] = _v(c["status"], c["reason"][:400])
    if not res.get("_windcheck_run"):
        out["auditor:windcheck"] = _v(NJ, "tools/upstream/windcheck not present or switched off")
    if "auditor:pitch_confidence" not in out:
        out["auditor:pitch_confidence"] = _v(PASS, f"{100 * t['judged_fraction']:.0f}% of the cut line has a trusted local pitch")
    return out


# ------------------------------------------------------------------------------------------------------------- the panel
def combine(votes, p: Params):
    """votes {judge: {verdict, detail}} -> (panel verdict, disagreement text list)."""
    judged = {k: v for k, v in votes.items() if v["verdict"] != NJ}
    if not judged:
        return NJ, []
    P_ = sorted(k for k, v in judged.items() if v["verdict"] == PASS)
    F_ = sorted(k for k, v in judged.items() if v["verdict"] == FAIL)
    if P_ and F_:
        txt = f"{', '.join(F_)} say{'s' if len(F_) == 1 else ''} FAIL ({'; '.join(judged[k]['detail'] for k in F_[:2])}); " \
              f"{', '.join(P_)} say{'s' if len(P_) == 1 else ''} PASS"
        return (FAIL if p.on_disagreement == "fail" else NJ), [txt]
    return (FAIL if F_ else PASS), []


def build_report(res, mesh_shape, heights, p: Params, names=None):
    H, W = mesh_shape
    regions = []
    tex = res.get("texture")
    for z in heights:
        sp = spacing_height(res["spacing"], z, p) if "spacing" in res else None
        wo = offset_height(res["auditor"], z, p) if "spacing" in res else None
        for c0 in range(0, W, p.region_cols):
            c1 = min(c0 + p.region_cols, W)
            votes = {"texture_judge": texture_region(tex, z, c0, c1, p),
                     "sheet_switch_finder": finder_region(res["finder"], z, c0, c1, p),
                     "auditor:switch_finder": auditor_switch_region(res["auditor"], z, c0, c1, p),
                     "auditor:winding_jumps": auditor_jumps_region(res["auditor"], z, c0, c1, p)}
            if sp is not None:
                votes["sheet_spacing_check"] = sp
                votes["auditor:winding_offset"] = wo
            verdict, dis = combine(votes, p)
            if all(v["verdict"] == NJ for v in votes.values()):
                continue                        # a region no judge saw (outside the cut line) is not reported
            regions.append(dict(z=float(z), col0=c0, col1=c1, judges=votes, panel=verdict, disagreement=dis))
    tl = trace_level(res)
    reg_v = [r["panel"] for r in regions]
    if FAIL in reg_v or any(v["verdict"] == FAIL for v in tl.values()):
        trace = FAIL
    elif not regions or NJ in reg_v:
        trace = NJ
    else:
        trace = PASS
    # per-judge summary over regions
    summary = {}
    for r in regions:
        for k, v in r["judges"].items():
            summary.setdefault(k, {PASS: 0, FAIL: 0, NJ: 0})[v["verdict"]] += 1
    dis = [f"z={r['z']:g} cols {r['col0']}-{r['col1'] - 1}: {t}" for r in regions for t in r["disagreement"]]
    return dict(panel_verdict=trace, regions=regions, trace_level=tl, judge_summary=summary, disagreements=dis,
                region_counts={v: reg_v.count(v) for v in (PASS, FAIL, NJ)})


def judge_verdicts(res, p: Params):
    """One verdict per judge for the whole trace (used for the agreement table): texture_judge and the auditor."""
    t, a = res.get("texture"), res.get("auditor")
    tv = NJ if isinstance(t, str) else {"PASS": PASS, "FAIL": FAIL}.get(t["verdict"], NJ)
    av = NJ if isinstance(a, str) else a["traces"][0]["verdict"]
    return dict(texture_judge=tv, auditor=av)


def text_report(rep, inputs):
    L = [f"judge_panel {__version__}   trace: {inputs['trace']}" + (f"   neighbour: {inputs['neighbour']}" if inputs.get("neighbour") else ""),
         f"PANEL VERDICT: {rep['panel_verdict']}   regions: " + ", ".join(f"{k} {v}" for k, v in rep["region_counts"].items()),
         "per judge (regions PASS / FAIL / NOT JUDGED):"]
    for k, s in rep["judge_summary"].items():
        L.append(f"  {k:<24} {s[PASS]:>4} {s[FAIL]:>4} {s[NJ]:>4}")
    L.append("trace-level judges:")
    for k, v in rep["trace_level"].items():
        L.append(f"  {k:<24} {v['verdict']:<11} {v['detail'][:160]}")
    L.append("regions that are not a unanimous PASS:")
    n = 0
    for r in rep["regions"]:
        if r["panel"] == PASS:
            continue
        n += 1
        L.append(f"  z={r['z']:g} cols {r['col0']}-{r['col1'] - 1}: {r['panel']}")
        for k, v in r["judges"].items():
            if v["verdict"] != NJ:
                L.append(f"      {k:<24} {v['verdict']:<5} {v['detail'][:140]}")
    if not n:
        L.append("  (none)")
    if rep["disagreements"]:
        L.append("DISAGREEMENTS:")
        L += [f"  {d}" for d in rep["disagreements"]]
    return "\n".join(L) + "\n"


def run_panel(trace, neighbour, vol, heights, out_dir, p: Params, umbilicus=None, windcheck=None, pitch_vox=None, extra=None, log=None, invalid_value=-1.0):
    if p.on_disagreement not in ("not-judged", "fail"):
        raise InputError("--on-disagreement must be not-judged or fail")
    if p.region_cols < 1:
        raise InputError("--region-cols must be >= 1")
    mesh = load_mesh(trace, invalid_value)
    res = run_judges(trace, neighbour, vol, heights, out_dir, p, umbilicus, windcheck, pitch_vox, extra, log)
    rep = build_report(res, mesh.shape, heights, p)
    rep["judge_verdicts"] = judge_verdicts(res, p)
    return rep, res


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("trace", help="tifxyz folder of the trace")
    ap.add_argument("neighbour", nargs="?", help="tifxyz folder of the neighbouring trace (enables the spacing judges)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--zarr"); g.add_argument("--png-dir")
    ap.add_argument("--zarr-level", type=int, default=0)
    ap.add_argument("--png-pixel-um", type=float); ap.add_argument("--png-pattern", default="{z:05d}.png")
    ap.add_argument("--voxel-size-um", type=float)
    ap.add_argument("--heights", required=True, help="comma-separated cut-line heights (voxels)")
    ap.add_argument("--umbilicus", help="centre line file for the auditor's winding checks")
    ap.add_argument("--pitch-vox", type=float, help="sheet pitch in voxels for the auditor and the finder (default: measured)")
    ap.add_argument("--no-windcheck", action="store_true", help="do not run the windcheck sub-check even if tools/upstream/windcheck exists")
    for j in ("auditor", "finder", "spacing", "texture"):
        ap.add_argument(f"--{j}-args", default="", help=f"extra command-line flags for the {j} judge, as one quoted string")
    ap.add_argument("--out-dir", required=True)
    d = Params()
    for f in dataclasses.fields(Params):
        ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, type=type(getattr(d, f.name)), default=getattr(d, f.name))
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        heights = [float(h) for h in a.heights.split(",") if h.strip()]
        if not heights:
            raise InputError("--heights is empty")
        for t in (a.trace, a.neighbour):
            if t and not os.path.isdir(t):
                raise InputError(f"mesh path is not a directory: {t}")
        vol = dict(zarr=a.zarr, zarr_level=a.zarr_level, png_dir=a.png_dir, png_pixel_um=a.png_pixel_um,
                   voxel_size_um=a.voxel_size_um, png_pattern=a.png_pattern)
        rep, res = run_panel(a.trace, a.neighbour, vol, heights, a.out_dir, p, a.umbilicus, False if a.no_windcheck else None, a.pitch_vox,
                             {j: getattr(a, f"{j}_args") for j in ("auditor", "finder", "spacing", "texture")},
                             log=lambda m: print(f"running {m}", file=sys.stderr))
    except (InputError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    inputs = dict(trace=a.trace, neighbour=a.neighbour, ct=a.zarr or a.png_dir, heights=heights)
    rep.update(tool_version=__version__, inputs=inputs, params=dataclasses.asdict(p))
    with open(os.path.join(a.out_dir, "panel.json"), "w") as fh:
        json.dump(rep, fh, indent=1, default=float)
    txt = text_report(rep, inputs)
    with open(os.path.join(a.out_dir, "panel.txt"), "w") as fh:
        fh.write(txt)
    print(txt, end="")
    return {PASS: 0, FAIL: 1, NJ: 4}[rep["panel_verdict"]]


if __name__ == "__main__":
    sys.exit(main())
