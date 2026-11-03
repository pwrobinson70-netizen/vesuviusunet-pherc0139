"""Core tifxyz reading and bbox computation.

Semantics deliberately mirror VC3D's C++ implementation
(villa/volume-cartographer/core/src/QuadSurface.cpp):

- A tifxyz patch is a directory with ``x.tif``, ``y.tif``, ``z.tif``
  (float32 2D grids of equal shape; cell (row, col) holds one 3D vertex)
  and a ``meta.json`` sidecar.
- A vertex is *invalid* when any of the following holds, matching what the
  loader (``load_quad_from_tifxyz_impl``) does before ``QuadSurface::bbox()``
  is ever called:
    1. ``z <= 0``: the loader rewrites the point to (-1, -1, -1)
    2. ``mask.tif`` channel 0 below 255, when a usable mask is present
    3. ``x == -1``: the test ``bbox()`` itself performs
  Rule 3 alone is *not* sufficient: rules 1 and 2 have already been applied
  to the in-memory grid, so replaying only rule 3 over the raw TIFFs counts
  points VC3D treats as invalid and inflates the extent.
- ``meta.json``'s ``bbox`` is ``[[min_x, min_y, min_z], [max_x, max_y, max_z]]``
  computed over valid vertices only.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import tifffile

COORD_FILES = ("x.tif", "y.tif", "z.tif")
INVALID_SENTINEL = -1.0
# QuadSurface.cpp's mask retain threshold: channel-0 values >= this are kept.
MASK_RETAIN_THRESHOLD = 255


def is_tifxyz_dir(path: Path) -> bool:
    return all((path / f).is_file() for f in COORD_FILES)


def find_patches(root: Path) -> list[Path]:
    """Find all tifxyz directories under ``root`` (including root itself)."""
    root = Path(root)
    if is_tifxyz_dir(root):
        return [root]
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        names = set(filenames)
        if all(f in names for f in COORD_FILES):
            found.append(Path(dirpath))
            dirnames.clear()  # tifxyz dirs don't nest
    return sorted(found)


@dataclass
class Patch:
    """A loaded tifxyz patch."""

    path: Path
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    meta: Optional[dict] = None
    meta_error: Optional[str] = None
    mask: Optional[np.ndarray] = None
    read_errors: dict[str, str] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.x.shape

    @property
    def valid(self) -> np.ndarray:
        """Validity mask under VC3D's loader semantics.

        ``QuadSurface::bbox()`` itself only tests ``x != -1``, but by the
        time it runs the loader has already invalidated points two other
        ways (QuadSurface.cpp, ``load_quad_from_tifxyz_impl``):

        1. ``z <= 0`` → point set to (-1, -1, -1)   [\"Invalidate by z<=0\"]
        2. ``mask.tif`` present → channel 0 below the retain threshold
           (255) invalidates the point; the mask may be an integer-multiple
           upscale of the grid, in which case it is sampled down.

        Reproducing only the ``x != -1`` test therefore counts points VC3D
        considers invalid, which inflates the computed extent and produces
        false \"stale bbox\" reports. All three rules are applied here.
        """
        # Mismatched grid shapes cannot be interpreted; treat every vertex as
        # invalid and let the grid-shape check report the corruption instead
        # of crashing on a broadcast error.
        if self.x.shape != self.y.shape or self.x.shape != self.z.shape:
            return np.zeros(self.x.shape, dtype=bool)
        # NB: the C++ test is ``z <= 0``, and IEEE comparisons against NaN are
        # false, so a NaN z is *not* invalidated by the loader. Negating the
        # same predicate (rather than testing ``z > 0``) reproduces that;
        # NaN coordinates are reported separately by the nan-vertices check.
        with np.errstate(invalid="ignore"):
            valid = (self.x != INVALID_SENTINEL) & ~(self.z <= 0)
        mask = self._mask_valid()
        if mask is not None:
            valid = valid & mask
        return valid

    def _mask_valid(self) -> Optional[np.ndarray]:
        """Per-vertex validity from ``mask.tif``, or None when unusable.

        Mirrors the loader: channel 0, ``>= 255`` retained, and a mask whose
        dimensions are an integer multiple of the grid maps every mask pixel
        to grid cell ``(src // scale)``, so *any* below-threshold pixel in a
        scale x scale block invalidates that vertex (a non-integer ratio is
        ignored by VC3D, so it is ignored here too).
        """
        if self.mask is None or self.x.size == 0:
            return None
        m = self.mask
        if m.ndim == 3:
            # tifffile returns (H, W, C) for contiguous TIFFs but (C, H, W)
            # for PLANARCONFIG_SEPARATE; the loader reads channel 0 either way.
            if m.shape[-1] <= 4 and m.shape[0] > 4:
                m = m[..., 0]
            else:
                m = m[0]
        if m.ndim != 2:
            return None
        h, w = self.x.shape
        mh, mw = m.shape
        if (mh, mw) != (h, w):
            if h == 0 or w == 0 or mh % h or mw % w:
                return None
            sy, sx = mh // h, mw // w
            # Match the loader's invalidate(): every mask pixel maps onto
            # grid cell (src // scale), so a block is retained only when all
            # its pixels pass the threshold. Plain striding would sample one
            # pixel per block and keep vertices VC3D discards.
            m = m[: h * sy, : w * sx].reshape(h, sy, w, sx).min(axis=(1, 3))
        if m.shape != (h, w):
            return None
        return m >= MASK_RETAIN_THRESHOLD

    def points(self) -> np.ndarray:
        """(H, W, 3) float32 array in (x, y, z) channel order."""
        return np.stack([self.x, self.y, self.z], axis=-1)


def load_patch(path: Path, *, load_mask: bool = True) -> Patch:
    """Load a tifxyz directory. Coordinate read errors are captured
    per-file in ``read_errors`` (with a zero-size placeholder array) so
    validation can report them instead of crashing."""
    path = Path(path)
    arrays: dict[str, np.ndarray] = {}
    read_errors: dict[str, str] = {}
    for fname in COORD_FILES:
        key = fname[0]
        try:
            arrays[key] = tifffile.imread(path / fname)
        except Exception as e:  # noqa: BLE001 - report, don't crash
            arrays[key] = np.zeros((0, 0), dtype=np.float32)
            read_errors[fname] = f"{type(e).__name__}: {e}"

    meta: Optional[dict] = None
    meta_error: Optional[str] = None
    meta_path = path / "meta.json"
    if meta_path.is_file():
        try:
            # meta.json is UTF-8 (JSON); never trust the locale encoding.
            meta = json.loads(meta_path.read_bytes())
        except Exception as e:  # noqa: BLE001
            meta_error = f"{type(e).__name__}: {e}"
    else:
        meta_error = "meta.json not found"

    mask = None
    if load_mask and (path / "mask.tif").is_file():
        try:
            mask = tifffile.imread(path / "mask.tif")
        except Exception as e:  # noqa: BLE001
            read_errors["mask.tif"] = f"{type(e).__name__}: {e}"

    return Patch(
        path=path,
        x=arrays["x"],
        y=arrays["y"],
        z=arrays["z"],
        meta=meta,
        meta_error=meta_error,
        mask=mask,
        read_errors=read_errors,
    )


def compute_bbox(patch: Patch) -> Optional[tuple[list[float], list[float]]]:
    """Recompute the true bbox over valid vertices, mirroring
    ``QuadSurface::bbox()``. Returns ``(low, high)`` in (x, y, z) order,
    or ``None`` when the patch has no valid vertices.

    NaNs are excluded from min/max so a few corrupt vertices cannot
    poison the box (they are reported separately by the nan check).
    """
    valid = patch.valid
    if not valid.any():
        return None
    low, high = [], []
    for arr in (patch.x, patch.y, patch.z):
        vals = arr[valid]
        finite = vals[np.isfinite(vals)]
        if finite.size == 0:
            return None
        low.append(float(finite.min()))
        high.append(float(finite.max()))
    return low, high


def parse_meta_bbox(meta: dict) -> Optional[tuple[list[float], list[float]]]:
    """Parse meta.json's bbox field into (low, high), or None if absent
    or malformed (malformedness is reported by the bbox check)."""
    raw = meta.get("bbox")
    if raw is None:
        return None
    try:
        low = [float(v) for v in raw[0]]
        high = [float(v) for v in raw[1]]
        if len(low) != 3 or len(high) != 3:
            return None
        if any(not math.isfinite(v) for v in low + high):
            return None
        return low, high
    except (TypeError, ValueError, IndexError, KeyError):
        return None
