"""tifxyz-repair command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .checks import validate_patch, worst_severity
from .core import find_patches, load_patch
from .repair import repair_bbox
from .report import audit_tree, summarize_markdown, write_csv

SEV_ICON = {"error": "✗", "warning": "!", "info": "·"}


def _print_findings(path: Path, findings, *, verbose: bool) -> None:
    shown = [f for f in findings if verbose or f["severity"] != "info"]
    status = worst_severity(findings)
    print(f"[{status:>7}] {path}")
    for f in shown:
        print(f"    {SEV_ICON[f['severity']]} {f['check']}: {f['message']}")


def _collect_patches(paths) -> tuple[list[Path], int]:
    """Resolve CLI path arguments to patch dirs. Returns (patches, exit_code):
    exit code 2 when a path does not exist or contains no patches at all,
    so a typo can never masquerade as a clean run."""
    patches: list[Path] = []
    bad = False
    for target in paths:
        t = Path(target)
        if not t.exists():
            print(f"error: path does not exist: {t}", file=sys.stderr)
            bad = True
            continue
        found = find_patches(t)
        if not found:
            print(f"error: no tifxyz patches under {t}", file=sys.stderr)
            bad = True
        patches.extend(found)
    return patches, (2 if bad else 0)


def cmd_validate(args) -> int:
    patches, exit_code = _collect_patches(args.paths)
    results = []
    for p in patches:
        patch = load_patch(p)
        findings = validate_patch(patch)
        results.append({"path": str(p), "status": worst_severity(findings), "findings": findings})
        if exit_code == 0 and any(f["severity"] == "error" for f in findings):
            exit_code = 1
        if not args.json:
            _print_findings(p, findings, verbose=args.verbose)
    if args.json:
        print(json.dumps(results, indent=2))
    return exit_code


def cmd_fix(args) -> int:
    patches, exit_code = _collect_patches(args.paths)
    n_fixed = 0
    n_failed = 0
    for p in patches:
        # One unreadable patch must never abort the rest of the batch.
        try:
            patch = load_patch(p)
            change = repair_bbox(
                patch,
                dry_run=args.dry_run,
                backup=not args.no_backup,
                strip=args.strip_bbox,
            )
        except Exception as e:  # noqa: BLE001
            n_failed += 1
            print(f"error: {p}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if change:
            n_fixed += 1
            print(f"{p}: {change}")
    verb = "would fix" if args.dry_run else "fixed"
    summary = f"\n{verb} {n_fixed} patch(es)"
    if n_failed:
        summary += f", {n_failed} failed (see stderr)"
    print(summary)
    if n_failed and exit_code == 0:
        exit_code = 1
    return exit_code


def cmd_report(args) -> int:
    root = Path(args.root)
    print(f"scanning {root} ...", file=sys.stderr)
    results = audit_tree(root, workers=args.workers)
    if not results:
        print("no tifxyz patches found", file=sys.stderr)
        return 2
    if args.csv:
        write_csv(results, Path(args.csv))
        print(f"wrote {args.csv}", file=sys.stderr)
    text = summarize_markdown(results, Path(args.out) if args.out else None)
    print(text)
    n_err = sum(1 for r in results if r["status"] == "error")
    return 1 if n_err else 0


def cmd_inspect(args) -> int:
    try:
        from .deep import defect_points, export_pointset, inspect_patch, render_defect_map
    except ImportError as e:
        print(f"inspect requires the [deep] extra (scipy, matplotlib): {e}", file=sys.stderr)
        return 2
    patches, exit_code = _collect_patches(args.paths)
    export_items = []
    for p in patches:
        # One unreadable patch must never abort the rest of the batch.
        try:
            patch = load_patch(p)
            metrics = inspect_patch(patch, collect_cells=bool(args.export_pointset))
        except Exception as e:  # noqa: BLE001
            print(f"error: {p}: {type(e).__name__}: {e}", file=sys.stderr)
            if exit_code == 0:
                exit_code = 1
            continue
        if args.export_pointset:
            export_items.append((p.name, defect_points(patch, metrics)))
            metrics.pop("defect_cells", None)  # keep the printed report readable
        print(f"== {p}")
        print(json.dumps(metrics, indent=2))
        if args.png_dir:
            out_dir = Path(args.png_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            png = out_dir / (p.name + ".png")
            render_defect_map(patch, metrics, png)
            print(f"   wrote {png}", file=sys.stderr)
    if args.export_pointset:
        out = Path(args.export_pointset)
        data = export_pointset(export_items, out)
        n_cols = len(data["collections"])
        n_pts = sum(len(c["points"]) for c in data["collections"].values())
        print(f"   wrote {out} ({n_cols} collections, {n_pts} points)", file=sys.stderr)
    return exit_code


def main(argv=None) -> int:
    # On non-UTF-8 consoles (Windows cp1252, LC_ALL=C) printing the severity
    # icons must degrade, not crash the run.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        prog="tifxyz-repair",
        description="Validate, audit, and repair tifxyz surface-mesh patches "
        "(Vesuvius Challenge / VC3D format).",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="validate one or more patches (or trees of patches)")
    p_val.add_argument("paths", nargs="+")
    p_val.add_argument("--json", action="store_true", help="machine-readable output")
    p_val.add_argument("-v", "--verbose", action="store_true", help="also show info-level findings")
    p_val.set_defaults(func=cmd_validate)

    p_fix = sub.add_parser("fix", help="repair stale/malformed bboxes in meta.json (villa #1272)")
    p_fix.add_argument("paths", nargs="+")
    p_fix.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    p_fix.add_argument("--no-backup", action="store_true", help="skip writing meta.json.bak")
    p_fix.add_argument(
        "--strip-bbox",
        action="store_true",
        help="remove the bbox field instead of recomputing it (mirrors vc_tifxyz_trim)",
    )
    p_fix.set_defaults(func=cmd_fix)

    p_rep = sub.add_parser("report", help="audit a whole tree of patches in parallel")
    p_rep.add_argument("root")
    p_rep.add_argument("--csv", help="write per-finding CSV here")
    p_rep.add_argument("--out", help="write Markdown summary here (also printed)")
    p_rep.add_argument("--workers", type=int, default=8)
    p_rep.set_defaults(func=cmd_report)

    p_ins = sub.add_parser(
        "inspect", help="deep geometry checks: holes, spacing distortion, sheet-switch suspects, normal flips"
    )
    p_ins.add_argument("paths", nargs="+")
    p_ins.add_argument("--png-dir", help="write per-patch defect-map PNGs into this directory")
    p_ins.add_argument(
        "--export-pointset",
        metavar="OUT.json",
        help="write defect locations as a VC3D point-collection JSON "
        "(load it from VC3D's Points panel to see flagged zones on the scroll data)",
    )
    p_ins.set_defaults(func=cmd_inspect)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
