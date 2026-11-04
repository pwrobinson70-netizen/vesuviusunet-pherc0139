"""vc3d_handoff: run the trace auditor on every patch of a VC3D project folder and write the verdict next to it.

    vun-audit --vc3d-folder PROJECT [--volume VOL] [--umbilicus FILE] [any other vun-audit flag]

Walks PROJECT (see docs/FORMATS.md): every directory that holds ``meta.json`` and ``x.tif``/``y.tif``/``z.tif`` is
a tifxyz patch. For each one it runs the ordinary auditor (same code, same defaults, same grid heights) and writes

    <patch>/verdict.json    machine-readable: verdict, per-check status and reasons, heights, judged fraction
    <patch>/verdict.txt     the same in words
    <PROJECT>/verdict_summary.txt   one table, one row per patch (and verdict_summary.csv)

Only those two files per patch (and the two summary files) are ever written. x/y/z.tif, mask.tif and meta.json
are never opened for writing. The output has no timestamps, so a re-run overwrites the verdict files with identical bytes.

The volume: ``--volume PATH`` (a .zarr folder, or a folder of PNG slices; PNG needs --png-pixel-um), else
``--zarr`` / ``--png-dir`` as for a single trace, else the patch's meta.json key ``volume`` (a path, or a
name under ``PROJECT/volumes/``), else the only entry of ``PROJECT/volumes/``. Nothing found -> every patch is NOT JUDGED
with that reason (exit 4), not a crash.
Exit code: 0 all PASS, 1 any FAIL, 4 no FAIL but something NOT JUDGED, 2 bad input.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import sys
import tempfile

VERDICT_FILES = ("verdict.json", "verdict.txt")
SUMMARY_FILES = ("verdict_summary.txt", "verdict_summary.csv")
META_VOLUME_KEYS = ("volume", "volume_path", "volume_name")


def find_patches(root):
    """Sorted list of tifxyz patch folders under root (a folder with meta.json and x/y/z.tif). Does not descend into a patch."""
    found = []
    for d, dirs, files in os.walk(root):
        names = set(files)
        if "meta.json" in names and {"x.tif", "y.tif", "z.tif"} <= names:
            found.append(d)
            dirs[:] = []
        else:
            dirs.sort()
    return sorted(found, key=lambda p: os.path.relpath(p, root).replace(os.sep, "/"))


def _is_png_dir(p):
    return os.path.isdir(p) and any(f.lower().endswith(".png") for f in os.listdir(p))


def volume_args(path):
    return ["--png-dir", path] if _is_png_dir(path) else ["--zarr", path]


def volume_from_meta(root, patch):
    """Volume path named by the patch's meta.json, or the only entry of PROJECT/volumes/; None if neither."""
    try:
        with open(os.path.join(patch, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        meta = {}
    for k in META_VOLUME_KEYS:
        v = meta.get(k) if isinstance(meta, dict) else None
        if isinstance(v, str) and v:
            for c in (v, os.path.join(root, v), os.path.join(root, "volumes", v), os.path.join(root, "volumes", v + ".zarr")):
                if os.path.exists(c):
                    return c
    vd = os.path.join(root, "volumes")
    if os.path.isdir(vd):
        ent = sorted(os.listdir(vd))
        if len(ent) == 1:
            return os.path.join(vd, ent[0])
    return None


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def verdict_text(v):
    lines = [f"{v['patch']}: {v['verdict']}"]
    if v.get("volume"):
        lines.append(f"volume: {v['volume']}")
    if v.get("judged_fraction") is not None:
        lines.append(f"judged fraction of the cut line: {100 * v['judged_fraction']:.0f}%")
    for c in v["checks"]:
        lines.append(f"  [{c['status']}] {c['check']}: {c['reason']}")
    if v.get("heights"):
        lines.append("heights: " + ", ".join(f"{h:g}" for h in v["heights"]))
    lines.append(f"auditor {v['tool_version']}")
    return "\n".join(lines) + "\n"


def _clean_check(c):
    return {k: c[k] for k in ("check", "status", "reason") if k in c}


def audit_patch(auditor_main, patch, rel, vol, passthrough):
    """Run the ordinary auditor on one patch; return the verdict dict (never raises for a bad patch)."""
    base = dict(patch=rel, volume=(vol.replace(os.sep, "/") if vol else None))
    if vol is None:
        return dict(base, verdict="NOT JUDGED", checks=[dict(check="volume", status="NOT JUDGED",
                    reason="no volume: give --volume, or name one in meta.json, or leave exactly one in PROJECT/volumes/")],
                    heights=[], judged_fraction=None, tool_version=None)
    with tempfile.TemporaryDirectory() as tmp:
        argv = list(passthrough) + volume_args(vol) + ["--out-dir", tmp, patch]
        sink, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(err):
            try:
                rc = auditor_main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 2
        ap = os.path.join(tmp, "audit.json")
        if rc == 2 or not os.path.isfile(ap):
            msg = (err.getvalue().strip().splitlines() or ["the auditor could not read this patch"])[-1]
            return dict(base, verdict="NOT JUDGED", checks=[dict(check="input", status="NOT JUDGED", reason=msg)],
                        heights=[], judged_fraction=None, tool_version=None)
        with open(ap, encoding="utf-8") as fh:
            rep = json.load(fh)
    tr = rep["result"]["traces"][0]
    return dict(base, verdict=tr["verdict"], checks=[_clean_check(c) for c in tr["checks"]], heights=rep["inputs"]["heights"],
                judged_fraction=tr.get("judged_fraction"), tool_version=rep["tool_version"])


def summary_table(rows):
    w = max([len("patch")] + [len(r["patch"]) for r in rows])
    out = [f"{'patch':<{w}}  {'verdict':<10}  judged  first reason", "-" * (w + 40)]
    for r in rows:
        jf = "   -  " if r["judged_fraction"] is None else f"{100 * r['judged_fraction']:5.0f}%"
        bad = [c for c in r["checks"] if c["status"] != "PASS"] or r["checks"]
        why = f"{bad[0]['check']}: {bad[0]['reason']}" if bad else ""
        out.append(f"{r['patch']:<{w}}  {r['verdict']:<10}  {jf}  {why[:110]}")
    n = {k: sum(r["verdict"] == k for r in rows) for k in ("PASS", "FAIL", "NOT JUDGED")}
    out.append(f"\n{len(rows)} patches: {n['PASS']} PASS, {n['FAIL']} FAIL, {n['NOT JUDGED']} NOT JUDGED")
    return "\n".join(out) + "\n"


def run(argv, auditor_main):
    hp = argparse.ArgumentParser(add_help=False)
    hp.add_argument("--vc3d-folder", required=True)
    hp.add_argument("--volume")
    a, rest = hp.parse_known_args(argv)
    root = a.vc3d_folder
    if not os.path.isdir(root):
        print(f"error: --vc3d-folder {root!r} is not a folder", file=sys.stderr)
        return 2
    patches = find_patches(root)
    if not patches:
        print(f"error: no tifxyz patch (a folder with meta.json and x/y/z.tif) under {root!r}", file=sys.stderr)
        return 2
    explicit, pt, skip = a.volume, [], False
    for i, tok in enumerate(rest):                      # --zarr / --png-dir behave like --volume (the first one wins)
        if skip:
            skip = False
        elif tok in ("--zarr", "--png-dir") and i + 1 < len(rest):
            explicit, skip = explicit or rest[i + 1], True
        else:
            pt.append(tok)
    rows = []
    for p in patches:
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        vol = explicit or volume_from_meta(root, p)
        v = audit_patch(auditor_main, p, rel, vol, pt)
        _write(os.path.join(p, "verdict.json"), json.dumps(v, indent=2, default=float) + "\n")
        _write(os.path.join(p, "verdict.txt"), verdict_text(v))
        rows.append(v)
        print(f"{rel}: {v['verdict']}", file=sys.stderr)
    table = summary_table(rows)
    _write(os.path.join(root, "verdict_summary.txt"), table)
    with open(os.path.join(root, "verdict_summary.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["patch", "verdict", "judged_fraction", "reasons"])
        for r in rows:
            bad = [c for c in r["checks"] if c["status"] != "PASS"] or r["checks"]
            w.writerow([r["patch"], r["verdict"], "" if r["judged_fraction"] is None else f"{r['judged_fraction']:.3f}",
                        " | ".join(f"{c['check']}: {c['reason']}" for c in bad)])
    print(table, end="")
    vs = [r["verdict"] for r in rows]
    return 1 if "FAIL" in vs else (4 if "NOT JUDGED" in vs else 0)
