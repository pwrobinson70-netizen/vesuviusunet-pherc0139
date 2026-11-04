"""Corpus-level auditing: walk a tree of tifxyz patches, validate each in
parallel, and emit CSV + Markdown summaries."""

from __future__ import annotations

import csv
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Optional

from .checks import validate_patch, worst_severity
from .core import find_patches, load_patch


def audit_one(path: Path) -> dict[str, Any]:
    try:
        patch = load_patch(path)
        findings = validate_patch(patch)
        return {
            "path": str(path),
            "status": worst_severity(findings),
            "findings": findings,
        }
    except Exception as e:  # noqa: BLE001 - a crash on one patch must not kill the audit
        return {
            "path": str(path),
            "status": "error",
            "findings": [
                {"check": "internal", "severity": "error", "message": f"{type(e).__name__}: {e}"}
            ],
        }


def audit_tree(root: Path, workers: int = 8) -> list[dict[str, Any]]:
    patches = find_patches(Path(root))
    if not patches:
        return []
    if workers <= 1 or len(patches) == 1:
        return [audit_one(p) for p in patches]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(audit_one, patches, chunksize=16))


def write_csv(results: list[dict[str, Any]], out: Path) -> None:
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "status", "check", "severity", "message", "data"])
        for r in results:
            findings = [f for f in r["findings"] if f["severity"] != "info"]
            if not findings:
                w.writerow([r["path"], r["status"], "", "", "", ""])
                continue
            for f in findings:
                data = {k: v for k, v in f.items() if k not in ("check", "severity", "message")}
                w.writerow(
                    [r["path"], r["status"], f["check"], f["severity"], f["message"],
                     json.dumps(data) if data else ""]
                )


def summarize_markdown(results: list[dict[str, Any]], out: Optional[Path] = None, top_n: int = 25) -> str:
    n = len(results)
    by_status: dict[str, int] = {}
    by_check: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        for f in r["findings"]:
            if f["severity"] in ("error", "warning"):
                by_check[f["check"]] = by_check.get(f["check"], 0) + 1

    stale = []
    for r in results:
        for f in r["findings"]:
            if f["check"] == "bbox-stale":
                stale.append((f.get("max_drift", 0.0), f.get("frac_outside", 0.0), r["path"]))
    stale.sort(reverse=True)

    lines = [
        "# tifxyz-repair audit report",
        "",
        f"Patches audited: **{n}**",
        "",
        "| status | patches |",
        "|---|---|",
    ]
    for s in ("ok", "info", "warning", "error"):
        if s in by_status:
            lines.append(f"| {s} | {by_status[s]} |")
    if by_check:
        lines += ["", "## Findings by check", "", "| check | patches affected |", "|---|---|"]
        for chk, cnt in sorted(by_check.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {chk} | {cnt} |")
    if stale:
        lines += [
            "",
            f"## Stale bboxes (villa #1272). {len(stale)} patches, worst {top_n} by drift",
            "",
            "| drift (voxels) | valid vertices outside stored bbox | patch |",
            "|---|---|---|",
        ]
        for drift, frac, path in stale[:top_n]:
            lines.append(f"| {drift:.1f} | {frac:.1%} | `{Path(path).name}` |")
    text = "\n".join(lines) + "\n"
    if out is not None:
        Path(out).write_text(text, encoding="utf-8")
    return text
