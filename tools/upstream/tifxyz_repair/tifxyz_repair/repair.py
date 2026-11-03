"""Repair stale metadata in tifxyz patches.

Only the ``bbox`` field is ever modified (or stripped); everything else in
meta.json is preserved byte-for-byte at the JSON level. Writes are atomic
(temp file + rename), mirroring how VC3D saves metadata
(QuadSurface.cpp: ``meta.json.tmp`` then rename), with indent 4 and a
trailing newline to match its output format.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .core import Patch, compute_bbox, parse_meta_bbox
from .checks import BBOX_TOLERANCE


def repair_bbox(
    patch: Patch,
    *,
    dry_run: bool = False,
    backup: bool = True,
    strip: bool = False,
) -> Optional[str]:
    """Rewrite meta.json with a recomputed bbox (or with bbox removed when
    ``strip`` is True, mirroring vc_tifxyz_trim's erase-on-change behavior).

    Returns a human-readable description of the change made (or that would
    be made under ``dry_run``), or None when no change is needed.
    """
    if patch.meta is None:
        return None
    meta_path = patch.path / "meta.json"

    stored = parse_meta_bbox(patch.meta)
    true = compute_bbox(patch)

    if strip:
        if "bbox" not in patch.meta:
            return None
        change = "remove bbox field (recomputed lazily by VC3D on next load)"
        new_meta = {k: v for k, v in patch.meta.items() if k != "bbox"}
    else:
        if true is None:
            return None  # nothing trustworthy to write
        if stored is not None:
            drift = max(
                abs(a - b) for a, b in zip(true[0] + true[1], stored[0] + stored[1])
            )
            if drift <= BBOX_TOLERANCE:
                return None
            change = f"recompute bbox (drift {drift:.1f} voxels)"
        else:
            if "bbox" in patch.meta:
                change = "replace malformed bbox with recomputed bbox"
            else:
                return None  # absent bbox is legal; don't add one unasked
        new_meta = dict(patch.meta)
        new_meta["bbox"] = [list(true[0]), list(true[1])]

    if dry_run:
        return f"[dry-run] {change}"

    if backup:
        bak = meta_path.with_suffix(".json.bak")
        if not bak.exists():
            bak.write_bytes(meta_path.read_bytes())

    tmp = meta_path.with_name("meta.json.tmp")
    tmp.write_text(json.dumps(new_meta, indent=4) + "\n", encoding="utf-8")
    os.replace(tmp, meta_path)
    patch.meta = new_meta
    return change
