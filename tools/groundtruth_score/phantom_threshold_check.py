#!/usr/bin/env python3
"""Re-run the trace_auditor phantom suite (tools/trace_auditor/score_on_phantoms.py) with trace_auditor thresholds changed.

PHANTOM numbers (synthetic scroll with exact truth), not real-data numbers.

    python phantom_threshold_check.py --set min_switch_confidence=0.5 [--set wn_min_span_deg=5] --json out.json

--set NAME=VALUE overrides a trace_auditor.Params field (underscored names, as in the dataclass). Without --set it
reproduces the unchanged suite. The suite itself is imported unchanged; only the Params it builds are replaced.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for d in ("trace_auditor", "sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "phantom_scroll"):
    sys.path.insert(0, os.path.join(TOOLS, d))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--phantoms", default="round,mild,bad,merged")
    ap.add_argument("--centre", choices=["estimated", "truth"], default="estimated")
    ap.add_argument("--json")
    ap.add_argument("--out", help="folder for the generated phantoms (default: temp)")
    a = ap.parse_args(argv)
    import score_on_phantoms as sop
    ta = sop.ta
    orig = ta.Params
    over = {}
    probe = orig()
    for kv in a.set:
        k, _, v = kv.partition("=")
        if not hasattr(probe, k):
            raise SystemExit(f"unknown trace_auditor Params field {k!r}")
        cur = getattr(probe, k)
        over[k] = int(float(v)) if isinstance(cur, int) and not isinstance(cur, bool) else float(v) if isinstance(cur, float) else v

    def patched(*args, **kw):
        return dataclasses.replace(orig(*args, **kw), **over)
    ta.Params = patched
    args = ["--size", str(a.size), "--seed", str(a.seed), "--phantoms", a.phantoms, "--centre", a.centre]
    if a.json:
        args += ["--json", a.json]
    if a.out:
        args += ["--out", a.out]
    print(f"# overrides: {over or 'none'}")
    return sop.main(args)


if __name__ == "__main__":
    sys.exit(main())
