#!/usr/bin/env python3
"""groundtruth_score: score the trace-checking tools against human-verified Scroll 1 patches.

Every patch in the ground-truth folder is a correct trace, so a trace checker should PASS all of them. For each
patch this runs trace_auditor (default mode, and a global-pitch mode), sheet_switch_finder and the CT pitch estimate of
sheet_spacing_check, and writes one CSV row per (patch, mode) plus a markdown summary. Optional: surface_agreement
from a checkout of origin/tool/surface-agreement (--surface-root).

    vun-groundtruth testdata/pherc_paris4_groundtruth --out results [--audit-args "--wn-jump-pitch 1.0"] [--tag NAME]

Notes on what is and is not run (see docs/REALDATA_GROUNDTRUTH.md):
* The centre line is the published one (umbilicus_9p6um.json) shifted by the patch window origin: a 700 x 150 px
  crop cannot give its own centre.
* sheet_spacing_check compares two traces; a single verified patch has no neighbour, so only its CT pitch estimate
  (the same function) is recorded; the pair verdict is not applicable.
* "global-pitch mode": main's auditor has no --global-pitch flag, so the closest equivalent is used: one pitch for
  the whole patch (--pitch-vox = median of the default-mode per-height pitch estimates). With --alt-root pointing at a
  checkout that does have --global-pitch (origin/tool/surface-agreement), that checkout's auditor is also run in
  its default and --global-pitch modes.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

__version__ = "0.1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
CONF = 0.3        # trace_auditor --min-switch-confidence default (used to count "flagged" switches)


def tools_root():
    for c in (os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools"), os.path.join(os.path.dirname(HERE), "_tools"),
              os.path.dirname(HERE)):
        if os.path.isdir(os.path.join(c, "trace_auditor")):
            return c
    raise SystemExit("groundtruth_score: cannot find the tools folder")


def wilson(k, n, z=1.959964):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def list_patches(data):
    """The patches the README lists (complete ones: mesh + slices at the three heights)."""
    out = []
    pd = os.path.join(data, "patches")
    for name in sorted(os.listdir(pd)):
        d = os.path.join(pd, name)
        mesh = os.path.join(d, "mesh.tifxyz")
        mp = os.path.join(mesh, "meta.json")
        if not os.path.isfile(mp):
            continue
        win = json.load(open(mp)).get("window")
        if not win:
            continue
        hs = [int(h) for h in win["heights"]]
        if not all(os.path.isfile(os.path.join(d, "slices", f"{h:05d}.png")) for h in hs):
            continue
        out.append(dict(name=name, mesh=mesh, slices=os.path.join(d, "slices"), surfpred=os.path.join(d, "surfpred"),
                        window=win, heights=hs))
    return out


def shifted_umbilicus(data, win, dst):
    u = json.load(open(os.path.join(data, "umbilicus_9p6um.json")))
    for c in u["control_points"]:
        c["x"] -= win["x0"]
        c["y"] -= win["y0"]
    json.dump(u, open(dst, "w"))
    return dst


def run(cmd, timeout=900):
    env = dict(os.environ, PAGER="cat", GIT_PAGER="cat", PYTHONWARNINGS="ignore")
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout, r.stderr


def norm_reason(s):
    """Group key for a reason: the check name and the first clause with numbers removed."""
    s = re.sub(r"z=[\d.]+", "z=#", s)
    s = re.sub(r"[-+]?\d+(\.\d+)?", "#", s)
    return s[:90]


def audit_patch(auditor, patch, umb, extra, work, tag, pitch=None, flag_global=False):
    out = os.path.join(work, f"audit_{tag}")
    cmd = [sys.executable, auditor, patch["mesh"], "--png-dir", patch["slices"], "--png-pixel-um", "9.6",
           "--voxel-size-um", "9.6", "--umbilicus", umb, "--heights", ",".join(map(str, patch["heights"])),
           "--out-dir", out]
    if pitch:
        cmd += ["--pitch-vox", f"{pitch:.4f}"]
    if flag_global:
        cmd += ["--global-pitch"]
    cmd += extra
    rc, so, se = run(cmd)
    ap = os.path.join(out, "audit.json")
    if not os.path.isfile(ap):
        msg = [(se or so).strip().splitlines()[-1] if (se or so).strip() else f"rc={rc}"]
        return dict(verdict="ERROR", reasons=msg, fail_reasons=msg, nj_reasons=[], checks={}, pitches=[], n_jumps=0,
                    n_switches=0, wn_judged=0, sw_judged=0)
    t = json.load(open(ap))["result"]["traces"][0]
    ch = {c["check"]: c for c in t["checks"]}
    wj = ch.get("winding_jumps", {})
    sw = ch.get("switch_finder", {})
    hts = wj.get("heights", []) or []
    return dict(verdict=t["verdict"],
                reasons=[f"{c['check']}: {c['reason']}" for c in t["checks"] if c["status"] != "PASS"],
                fail_reasons=[f"{c['check']}: {c['reason']}" for c in t["checks"] if c["status"] == "FAIL"],
                nj_reasons=[f"{c['check']}: {c['reason']}" for c in t["checks"] if c["status"] == "NOT JUDGED"],
                checks={k: v["status"] for k, v in ch.items()},
                pitches=[h.get("pitch") for h in t["heights"]],
                n_jumps=len(wj.get("jumps", []) or []), n_switches=len(sw.get("switches", []) or []),
                wn_judged=sum(1 for h in hts if h.get("status") != "NOT JUDGED"),
                sw_judged=sum(1 for h in t["heights"] if h.get("tracked", 0) >= 0.6))


def switch_patch(finder, patch, work):
    out = os.path.join(work, "ssf.json")
    cmd = [sys.executable, finder, patch["mesh"], "--png-dir", patch["slices"], "--png-pixel-um", "9.6",
           "--voxel-size-um", "9.6", "--heights", ",".join(map(str, patch["heights"])), "--out-json", out]
    run(cmd)
    if not os.path.isfile(out):
        return dict(n_all=None, n_flag=None, tracked=None, pitches=[])
    r = json.load(open(out))["result"]
    sws = r["switches"]
    return dict(n_all=len(sws), n_flag=sum(1 for s in sws if s["confidence"] >= CONF),
                tracked=[h["fraction_tracked"] for h in r["heights"]], pitches=[h["ct_pitch_vox"] for h in r["heights"]])


def surface_patch(surface_root, patch, umb, work):
    sa = os.path.join(surface_root, "tools", "surface_agreement", "surface_agreement.py")
    out = os.path.join(work, "sa")
    cmd = [sys.executable, sa, patch["mesh"], "--pred-png-dir", patch["surfpred"], "--ct-png-dir", patch["slices"],
           "--png-pixel-um", "9.6", "--voxel-size-um", "9.6", "--heights", ",".join(map(str, patch["heights"])),
           "--out-dir", out]
    run(cmd)
    rp = os.path.join(out, "report.json")
    if not os.path.isfile(rp):
        return None
    return json.load(open(rp))


def sa_summary(rep):
    """surface_agreement report.json -> dict(on, off, nj, agree, compared, verdicts) summed over heights."""
    on = off = nj = agree = comp = 0
    verdicts = []
    for tr in rep.get("traces", []):
        on += int(tr.get("pred_on", 0))
        off += int(tr.get("pred_off", 0))
        nj += int(tr.get("pred_not_judged", 0))
        t = tr.get("table_2x2", {})
        agree += int(t.get("ours_on_pred_on", 0)) + int(t.get("ours_off_pred_off", 0))
        comp += int(tr.get("n_compared", 0))
        verdicts += [h.get("pred_verdict") for h in tr.get("heights", [])]
    return dict(on=on, judged=on + off, not_judged=nj, agree=agree, compared=comp, verdicts=verdicts)


def score_one(args, data, patch):
    work = tempfile.mkdtemp(prefix="gt_", dir=args.work)
    umb = shifted_umbilicus(data, patch["window"], os.path.join(work, "umb.json"))
    root = tools_root()
    aud = os.path.join(root, "trace_auditor", "trace_auditor.py")
    fnd = os.path.join(root, "sheet_switch_finder", "sheet_switch_finder.py")
    extra = args.audit_args.split() if args.audit_args else []
    rows = []
    d = audit_patch(aud, patch, umb, extra, work, "default")
    if args.fast:                         # default mode only (threshold sweeps)
        return [dict(patch=patch["name"].replace(".tifxyz", ""), mode="default", verdict=d["verdict"],
                     fail_reasons=" | ".join(d["fail_reasons"]), nj_reasons=" | ".join(d["nj_reasons"]))]
    ssf = switch_patch(fnd, patch, work)
    ps = [p for p in d["pitches"] if p]
    gp = float(sorted(ps)[len(ps) // 2]) if ps else None
    g = audit_patch(aud, patch, umb, extra, work, "global", pitch=gp) if gp else \
        dict(verdict="NOT JUDGED", reasons=["pitch: no pitch estimate at any height"], fail_reasons=[],
             nj_reasons=["pitch: no pitch estimate at any height"], checks={}, pitches=[], n_jumps=0,
             n_switches=0, wn_judged=0, sw_judged=0)
    rows.append(("default", d, None))
    rows.append(("global-pitch(--pitch-vox)", g, gp))
    if args.alt_root:
        alt = os.path.join(args.alt_root, "tools", "trace_auditor", "trace_auditor.py")
        rows.append(("alt-default", audit_patch(alt, patch, umb, extra, work, "altd"), None))
        rows.append(("alt-global-pitch", audit_patch(alt, patch, umb, extra, work, "altg", flag_global=True), None))
    sa = None
    if args.surface_root:
        rep = surface_patch(args.surface_root, patch, umb, work)
        if rep:
            sa = sa_summary(rep)
    out = []
    for mode, r, gpv in rows:
        out.append(dict(patch=patch["name"].replace(".tifxyz", ""), mode=mode, verdict=r["verdict"],
                        reasons=" | ".join(r["reasons"]), fail_reasons=" | ".join(r["fail_reasons"]),
                        nj_reasons=" | ".join(r["nj_reasons"]), checks=json.dumps(r["checks"], sort_keys=True),
                        pitch_h1=_f(r["pitches"], 0), pitch_h2=_f(r["pitches"], 1), pitch_h3=_f(r["pitches"], 2),
                        pitch_used=("%.3f" % gpv) if gpv else "", n_wn_jumps=r["n_jumps"], n_audit_switches=r["n_switches"],
                        wn_judged_heights=r["wn_judged"], sw_judged_heights=r["sw_judged"],
                        ssf_switches_all=ssf["n_all"], ssf_switches_flagged=ssf["n_flag"],
                        sa_on=(sa or {}).get("on", ""), sa_judged=(sa or {}).get("judged", ""),
                        sa_agree=(sa or {}).get("agree", ""), sa_compared=(sa or {}).get("compared", ""),
                        sa_verdicts=",".join(str(v) for v in (sa or {}).get("verdicts", []))))
    return out


def _f(lst, i):
    return ("%.3f" % lst[i]) if i < len(lst) and lst[i] is not None else ""


COLS = ["patch", "mode", "verdict", "fail_reasons", "nj_reasons", "reasons", "checks", "pitch_h1", "pitch_h2", "pitch_h3", "pitch_used", "n_wn_jumps",
        "n_audit_switches", "wn_judged_heights", "sw_judged_heights", "ssf_switches_all", "ssf_switches_flagged",
        "sa_on", "sa_judged", "sa_agree", "sa_compared", "sa_verdicts"]


def summarise(rows, args):
    modes = []
    for r in rows:
        if r["mode"] not in modes:
            modes.append(r["mode"])
    L = [f"# Ground-truth patch scoring ({args.tag})", "",
         "AI-assisted (Claude Code and Claude), human-directed. Data: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0.", "",
         f"Patches: {len({r['patch'] for r in rows})}. Every patch is a human-verified correct trace, so PASS is correct.",
         f"Extra auditor arguments: `{args.audit_args or '(none)'}`.", ""]
    L += ["| mode | PASS | FAIL | NOT JUDGED | ERROR | false-alarm rate FAIL/N (Wilson 95%) |", "|---|---|---|---|---|---|"]
    for m in modes:
        rs = [r for r in rows if r["mode"] == m]
        c = {v: sum(1 for r in rs if r["verdict"] == v) for v in ("PASS", "FAIL", "NOT JUDGED", "ERROR")}
        lo, hi = wilson(c["FAIL"], len(rs))
        L.append(f"| {m} | {c['PASS']} | {c['FAIL']} | {c['NOT JUDGED']} | {c['ERROR']} | "
                 f"{c['FAIL']}/{len(rs)} = {100 * c['FAIL'] / len(rs):.1f}% ({100 * lo:.1f}-{100 * hi:.1f}%) |")
    for m in modes:
        rs = [r for r in rows if r["mode"] == m and r["verdict"] in ("FAIL", "NOT JUDGED", "ERROR")]
        L += ["", f"## Reasons not PASS: {m}", ""]
        g = {}
        for r in rs:
            seen = set()
            for part in (r["fail_reasons"] if r["verdict"] in ("FAIL", "ERROR") else r["nj_reasons"]).split(" | "):
                if not part:
                    continue
                head, _, tail = part.partition(": ")
                tail = re.sub(r"^\d+ of \d+ heights not judged: ", "", tail)
                for clause in tail.split("; "):
                    clause = re.sub(r"^z=[\d.]+: ", "", clause)
                    k = norm_reason(head + ": " + clause)
                    if k not in seen:
                        seen.add(k)
                        g.setdefault((r["verdict"], k), []).append(r["patch"])
        L += ["| verdict | reason (numbers masked) | patches |", "|---|---|---|"]
        for (v, k), ps in sorted(g.items(), key=lambda kv: -len(kv[1])):
            L.append(f"| {v} | {k} | {len(ps)} |")
    L += ["", "## Per patch (default mode)", "",
          "| patch | verdict | pitch h1/h2/h3 | wn jumps | audit switches | ssf switches all/flagged |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r["mode"] == modes[0]:
            g = r.get
            L.append(f"| {r['patch'][:30]} | {r['verdict']} | {g('pitch_h1', '')}/{g('pitch_h2', '')}/{g('pitch_h3', '')} | "
                     f"{g('n_wn_jumps', '')} | {g('n_audit_switches', '')} | {g('ssf_switches_all', '')}/{g('ssf_switches_flagged', '')} |")
    sa = [r for r in rows if r["mode"] == modes[0] and r.get("sa_judged", "") not in ("", None)]
    if args.surface_root:
        L += ["", "## surface_agreement (from a checkout of origin/tool/surface-agreement)", ""]
        if sa:
            on = sum(int(r["sa_on"]) for r in sa)
            j = sum(int(r["sa_judged"]) for r in sa)
            ag = sum(int(r["sa_agree"]) for r in sa)
            cp = sum(int(r["sa_compared"]) for r in sa)
            hv = [v for r in sa for v in r["sa_verdicts"].split(",") if v]
            L.append(f"ON-PREDICTED-SHEET: {on}/{j} judged points = {100 * on / max(j, 1):.1f}% over {len(sa)} patches "
                     f"(height verdicts PASS {hv.count('PASS')} / FAIL {hv.count('FAIL')} / NOT JUDGED {hv.count('NOT JUDGED')} "
                     f"of {len(hv)}; our CT-peak judge and the prediction agree on {ag}/{cp} compared points).")
        else:
            L.append("surface_agreement produced no report.")
    else:
        L += ["", "surface_agreement was not run (no `--surface-root`)."]
    return "\n".join(L) + "\n"


def build_parser():
    ap = argparse.ArgumentParser(prog="vun-groundtruth", description=__doc__.split("\n\n")[0])
    ap.add_argument("data", help="ground-truth folder (patches/, umbilicus_9p6um.json, ...)")
    ap.add_argument("--out", default="results", help="output folder (groundtruth_patches.csv / .md)")
    ap.add_argument("--tag", default="default thresholds", help="label in the report; also the file stem suffix if --suffix")
    ap.add_argument("--stem", default="groundtruth_patches", help="output file stem")
    ap.add_argument("--audit-args", default="", help="extra arguments passed to trace_auditor, e.g. '--wn-jump-pitch 1.0'")
    ap.add_argument("--alt-root", help="checkout of origin/tool/surface-agreement: also run its auditor (has --global-pitch)")
    ap.add_argument("--surface-root", help="checkout of origin/tool/surface-agreement: also run surface_agreement per patch")
    ap.add_argument("--parts", default="A", help="A = patch scoring (default); B = centre line vs the published umbilicus on level-4 "
                    "slices; C = winding numbers vs abs_winding.json. e.g. A,B,C (B and C need --l4-slices)")
    ap.add_argument("--l4-slices", help="folder of level-4 PNG slices ({z:05d}.png); missing ones are fetched from the public zarr")
    ap.add_argument("--fast", action="store_true", help="default-mode audit only (used by --sweep)")
    ap.add_argument("--sweep", help="one-flag threshold sweep over the patches, e.g. "
                    "'min-switch-confidence=0.5,0.6;wn-min-span-deg=5,10'; writes <stem>_threshold_sweep.csv/.md")
    ap.add_argument("--only", help="comma-separated substrings; score only matching patches")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--work", default=None, help="scratch folder (default: system temp)")
    return ap


def sweep(a, patches):
    """One audit flag at a time (default mode): PASS / FAIL / NOT JUDGED counts over the patches for every value."""
    import copy
    a = copy.copy(a)
    a.fast = True
    base = a.audit_args.split() if a.audit_args else []
    cases = [("(default)", "")]
    for item in a.sweep.split(";"):
        flag, _, vals = item.partition("=")
        cases += [(flag.strip(), v) for v in vals.split(",") if v]
    out = []
    for flag, v in cases:
        a.audit_args = " ".join(base + ([f"--{flag}", v] if v else []))
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            res = [r for rr in ex.map(lambda p: score_one(a, a.data, p), patches) for r in rr]
        c = {k: sum(1 for r in res if r["verdict"] == k) for k in ("PASS", "FAIL", "NOT JUDGED", "ERROR")}
        lo, hi = wilson(c["FAIL"], len(res))
        out.append(dict(flag=flag, value=v, n=len(res), PASS=c["PASS"], FAIL=c["FAIL"], NOT_JUDGED=c["NOT JUDGED"],
                        ERROR=c["ERROR"], fail_rate=f"{c['FAIL'] / len(res):.3f}", wilson_lo=f"{lo:.3f}", wilson_hi=f"{hi:.3f}",
                        fail_patches=";".join(r["patch"][:24] for r in res if r["verdict"] == "FAIL")))
        print(out[-1]["flag"], out[-1]["value"], c, flush=True)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, a.stem + "_threshold_sweep.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, list(out[0]))
        w.writeheader()
        w.writerows(out)
    L = ["# Single-threshold sweep on the 40 verified patches (default mode, one flag changed at a time)", "",
         "AI-assisted (Claude Code and Claude), human-directed.", "",
         "| flag | value | PASS | FAIL | NOT JUDGED | FAIL rate (Wilson 95%) |", "|---|---|---|---|---|---|"]
    for r in out:
        L.append(f"| {r['flag']} | {r['value'] or 'default'} | {r['PASS']} | {r['FAIL']} | {r['NOT_JUDGED']} | "
                 f"{float(r['fail_rate']) * 100:.1f}% ({float(r['wilson_lo']) * 100:.1f}-{float(r['wilson_hi']) * 100:.1f}%) |")
    open(os.path.join(a.out, a.stem + "_threshold_sweep.md"), "w").write("\n".join(L) + "\n")
    return 0


def main(argv=None):
    a = build_parser().parse_args(argv)
    if not os.path.isdir(os.path.join(a.data, "patches")):
        print(f"error: {a.data}/patches not found", file=sys.stderr)
        return 2
    patches = list_patches(a.data)
    if a.only:
        keys = a.only.split(",")
        patches = [p for p in patches if any(k in p["name"] for k in keys)]
    if not patches:
        print("error: no complete patches", file=sys.stderr)
        return 2
    parts = set(a.parts.upper().replace(" ", "").split(","))
    if parts - set("ABC") or not parts:
        print("error: --parts is a comma list of A, B, C", file=sys.stderr)
        return 2
    if parts & {"B", "C"} and not a.l4_slices:
        print("error: parts B and C need --l4-slices", file=sys.stderr)
        return 2
    if parts & {"B", "C"}:
        sys.path.insert(0, HERE)
        import centre_l4
        import winding_l4
        if "B" in parts:
            centre_l4.main([a.data, "--slices-dir", a.l4_slices, "--out", a.out])
        if "C" in parts:
            winding_l4.main([a.data, "--slices-dir", a.l4_slices, "--out", a.out])
    if "A" not in parts:
        return 0
    a.work = a.work or tempfile.mkdtemp(prefix="vun_gt_")
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    if a.sweep:
        return sweep(a, patches)
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        res = list(ex.map(lambda p: score_one(a, a.data, p), patches))
    rows = [r for rr in res for r in rr]
    with open(os.path.join(a.out, a.stem + ".csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, COLS, restval="")
        w.writeheader()
        w.writerows(rows)
    md = summarise(rows, a)
    open(os.path.join(a.out, a.stem + ".md"), "w").write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
