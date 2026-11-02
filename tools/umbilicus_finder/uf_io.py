"""I/O for umbilicus_finder: volume readers, CSV/JSON/villa writers, overlay PNGs.

MIT licence (see repository LICENSE). CPU only. Dependencies: numpy, pillow, zarr (optional import).

Coordinates: every volume reports its per-axis scale = level-0 voxels per voxel of the opened
level. A level voxel i covers level-0 voxels [i*s, (i+1)*s), so its centre in level-0 voxel
coordinates is (i + 0.5) * s - 0.5. All outputs use that convention.
"""
import csv
import json
from pathlib import Path

import numpy as np


class InputError(ValueError):
    """Bad user input (path, shape, z range). The CLI reports it and exits with code 2."""


def centre_to_level0(i, scale):
    """Level-voxel (possibly fractional) index -> level-0 voxel coordinate of its centre."""
    return (np.asarray(i, dtype=float) + 0.5) * scale - 0.5


def level0_to_slice_index(z, scale):
    """Level-0 z -> nearest level slice index (inverse of centre_to_level0, rounded)."""
    return int(np.round((float(z) + 0.5) / scale - 0.5))


# --------------------------------------------------------------------------- volumes
class ArrayVolume:
    """In-memory (z, y, x) array. scale = (sz, sxy): level-0 voxels per voxel."""

    def __init__(self, data, scale_z=1.0, scale_xy=1.0):
        data = np.asarray(data) if not hasattr(data, "shape") else data
        if len(data.shape) != 3:
            raise InputError(f"volume must be 3-D (z, y, x), got shape {tuple(data.shape)}")
        if min(data.shape) < 1:
            raise InputError(f"volume has an empty axis: {tuple(data.shape)}")
        if scale_z <= 0 or scale_xy <= 0:
            raise InputError("scales must be > 0")
        self.data = data
        self.shape = tuple(int(s) for s in data.shape)
        self.scale_z = float(scale_z)
        self.scale_xy = float(scale_xy)

    def read_slice(self, zi):
        if not 0 <= zi < self.shape[0]:
            raise InputError(f"slice index {zi} outside 0..{self.shape[0] - 1}")
        return np.asarray(self.data[zi])


def _ome_multiscales(attrs):
    """multiscales list from zarr attrs (OME-Zarr 0.4 at top level, 0.5 under 'ome')."""
    attrs = dict(attrs)
    if "multiscales" in attrs:
        return attrs["multiscales"]
    if isinstance(attrs.get("ome"), dict) and "multiscales" in attrs["ome"]:
        return attrs["ome"]["multiscales"]
    return None


def _dataset_scale(ds):
    for t in ds.get("coordinateTransformations", []) or []:
        if t.get("type") == "scale" and "scale" in t:
            return [float(v) for v in t["scale"]]
    return None


class ZarrVolume(ArrayVolume):
    """OME-Zarr group (any level) or a bare 3-D zarr array.

    Scale relative to level 0 comes from the OME 'scale' transforms when present, else 2**level
    for a group. scale_z / scale_xy override it (needed for a bare array at a coarse level).
    """

    def __init__(self, path, level=0, scale_z=None, scale_xy=None):
        path = Path(path)
        if not path.exists():
            raise InputError(f"zarr path does not exist: {path}")
        try:
            import zarr
            node = zarr.open(str(path), mode="r")
        except Exception as e:  # zarr raises several different types
            raise InputError(f"cannot open {path} as zarr: {e}") from e
        sz = sxy = 1.0
        if hasattr(node, "shape"):  # bare array
            arr = node
        else:
            ms = _ome_multiscales(node.attrs)
            datasets = ms[0].get("datasets", []) if ms else []
            try:
                if datasets:
                    ds = datasets[level]
                    arr = node[ds["path"]]
                    s0, s1 = _dataset_scale(datasets[0]), _dataset_scale(ds)
                    if s0 and s1 and len(s0) >= 3 and len(s1) >= 3:
                        sz, sxy = s1[-3] / s0[-3], s1[-1] / s0[-1]
                    else:
                        sz = sxy = 2.0 ** level
                else:
                    arr = node[str(level)]
                    sz = sxy = 2.0 ** level
            except (KeyError, IndexError) as e:
                raise InputError(f"zarr level {level} not found in {path}: {e!r}") from e
        if len(arr.shape) != 3:
            raise InputError(f"zarr array must be 3-D (z, y, x), got {tuple(arr.shape)}")
        super().__init__(arr, scale_z if scale_z else sz, scale_xy if scale_xy else sxy)


class PngVolume:
    """A directory of 2-D slice PNGs (sorted by name = z order); known in-plane / z scale."""

    def __init__(self, directory, scale_xy=1.0, scale_z=None, pattern="*.png"):
        d = Path(directory)
        if not d.is_dir():
            raise InputError(f"PNG directory does not exist: {d}")
        self.files = sorted(d.glob(pattern))
        if not self.files:
            raise InputError(f"no files matching {pattern!r} in {d}")
        if scale_xy <= 0 or (scale_z is not None and scale_z <= 0):
            raise InputError("scales must be > 0")
        self.scale_xy = float(scale_xy)
        self.scale_z = float(scale_z if scale_z else scale_xy)
        first = self.read_slice(0)
        self.shape = (len(self.files),) + first.shape

    def read_slice(self, zi):
        if not 0 <= zi < len(self.files):
            raise InputError(f"slice index {zi} outside 0..{len(self.files) - 1}")
        from PIL import Image
        try:
            with Image.open(self.files[zi]) as im:
                if im.mode not in ("L", "I;16", "I", "F"):
                    im = im.convert("L")
                a = np.asarray(im)
        except Exception as e:
            raise InputError(f"cannot read PNG {self.files[zi]}: {e}") from e
        if a.ndim != 2:
            raise InputError(f"PNG {self.files[zi]} is not a single-channel image")
        return a


def open_volume(path, kind="auto", level=0, scale_z=None, scale_xy=None, png_glob="*.png"):
    p = Path(path)
    if not p.exists():
        raise InputError(f"input path does not exist: {p}")
    if kind == "auto":
        is_zarr = any((p / m).exists() for m in (".zarray", ".zgroup", "zarr.json")) or p.suffix == ".zarr"
        kind = "zarr" if is_zarr else "png"
    if kind == "zarr":
        return ZarrVolume(p, level, scale_z, scale_xy)
    if kind == "png":
        return PngVolume(p, scale_xy or 1.0, scale_z, png_glob)
    raise InputError(f"unknown input type {kind!r}")


# --------------------------------------------------------------------------- writers
CSV_COLUMNS = ["z", "y", "x", "confidence", "flag", "raw_y", "raw_x", "departure_vox",
               "n_votes", "n_inliers", "coverage_deg", "residual_pitch", "reason"]


def _fmt(v):
    if isinstance(v, (float, np.floating)):
        return "nan" if not np.isfinite(v) else f"{v:.4f}"
    return str(v)


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for r in rows:
            w.writerow([_fmt(r[c]) for c in CSV_COLUMNS])


def _clean(o):
    """Make JSON-safe: numpy scalars -> python, NaN/inf -> null (bare NaN is not valid JSON)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item"):
        o = o.item()
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(_clean(obj), f, indent=2, allow_nan=False)


def write_villa_json(path, rows, include_low=False):
    """ScrollPrize/villa `spiral-fitting/umbilicus.py` JSON: {"control_points": [{z, y, x}]}.

    Level-0 voxel units, sorted by z. By default only OK-flag points are exported.
    Returns the number of points written.
    """
    pts = [{"z": float(r["z"]), "y": float(r["y"]), "x": float(r["x"])}
           for r in rows
           if np.isfinite(r["y"]) and np.isfinite(r["x"]) and (include_low or r["flag"] == "OK")]
    pts.sort(key=lambda p: p["z"])
    write_json(path, {"control_points": pts})
    return len(pts)


def write_overlay(path, img_ds, centre_xy, votes_xy, normals_xy, inlier, label, max_lines=150, seed=0):
    """Greyscale slice (downsampled) + voting normals (red = inlier, blue = outlier) + centre cross.

    Each drawn normal is the segment from the voting pixel to the foot of the perpendicular from
    the centre onto its line, so a good estimate shows short segments converging on the cross.
    """
    from PIL import Image, ImageDraw
    a = np.asarray(img_ds, dtype=np.float32)
    lo, hi = np.percentile(a, [1, 99.5]) if a.size else (0, 1)
    g = np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1)
    im = Image.fromarray((g * 255).astype(np.uint8)).convert("RGB")
    dr = ImageDraw.Draw(im)
    if centre_xy is not None and votes_xy is not None and len(votes_xy):
        rng = np.random.default_rng(seed)
        n = len(votes_xy)
        idx = rng.choice(n, size=min(max_lines, n), replace=False)
        cx, cy = centre_xy
        for i in idx:
            px, py = votes_xy[i]
            nx, ny = normals_xy[i]
            t = (cx - px) * nx + (cy - py) * ny  # signed distance along the normal to the foot
            colour = (255, 60, 60) if inlier[i] else (80, 120, 255)
            dr.line([(px, py), (px + t * nx, py + t * ny)], fill=colour, width=1)
    if centre_xy is not None and np.all(np.isfinite(centre_xy)):
        cx, cy = centre_xy
        dr.line([(cx - 8, cy), (cx + 8, cy)], fill=(0, 255, 0), width=2)
        dr.line([(cx, cy - 8), (cx, cy + 8)], fill=(0, 255, 0), width=2)
    dr.text((4, 4), label, fill=(255, 255, 0))
    im.save(path)
