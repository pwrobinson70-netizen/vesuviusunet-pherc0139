"""Input loaders for sheet_spacing_check: tifxyz meshes and CT volumes (MIT)."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import numpy as np


class InputError(ValueError):
    """Raised for unusable user input (bad path, mismatched shapes, ...)."""


# ----------------------------------------------------------------- meshes
@dataclass
class Mesh:
    name: str
    x: np.ndarray            # (H, W) float64, volume voxels
    y: np.ndarray
    z: np.ndarray
    valid: np.ndarray        # (H, W) bool
    meta: dict = field(default_factory=dict)
    scale: tuple | None = None       # meta.json "scale" (grid steps per voxel)
    voxel_um: float | None = None    # meta.json voxel size, if present
    n_invalid: int = 0               # grid cells with no usable data

    @property
    def shape(self):
        return self.z.shape


def _first_number(meta, keys):
    for k in keys:
        v = meta.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def mask_validity(mask, shape):
    """VC3D mask.tif -> (H, W) bool. A cell is valid only if every mask pixel it covers is >= 255
    (QuadSurface.cpp:2776-2840, SurfaceGrid.hpp:25-28); the mask may be a whole multiple of the grid."""
    m = np.asarray(mask)
    if m.ndim == 3:                                    # channel 0 carries validity
        m = m[..., 0] if m.shape[-1] <= 4 else m[0]
    H, W = shape
    if m.ndim != 2 or m.shape[0] % H or m.shape[1] % W or not m.shape[0] or not m.shape[1]:
        raise InputError(f"mask.tif shape {tuple(np.shape(mask))} is not the grid {H}x{W} or a whole multiple of it")
    fy, fx = m.shape[0] // H, m.shape[1] // W
    return (m >= 255).reshape(H, fy, W, fx).all(axis=(1, 3))


def build_mesh(name, x, y, z, meta=None, invalid_value=-1.0, transpose=False, mask=None):
    """Make a Mesh from three (H, W) arrays (used by load_mesh and tests). `mask`: optional mask.tif array
    (pre-transpose grid); masked-out cells are invalid even though x/y/z hold real values there."""
    x, y, z = (np.array(a, dtype=np.float64) for a in (x, y, z))   # copies: never mutate the caller's arrays
    if x.ndim != 2 or not (x.shape == y.shape == z.shape):
        raise InputError(f"{name}: x/y/z grids must be 2-D and the same shape, got "
                         f"{x.shape}, {y.shape}, {z.shape}")
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    # a cell is invalid if ANY coordinate carries the no-data marker (partial sentinels exist)
    valid &= ~((x == invalid_value) | (y == invalid_value) | (z == invalid_value))
    if mask is not None:
        valid &= mask_validity(mask, x.shape)
    for a in (x, y, z):
        a[~valid] = np.nan
    n_invalid = int((~valid).sum())
    if transpose:
        x, y, z, valid = x.T.copy(), y.T.copy(), z.T.copy(), valid.T.copy()
    meta = dict(meta or {})
    scale = meta.get("scale")
    if isinstance(scale, (list, tuple)) and len(scale) >= 2 and all(
            isinstance(s, (int, float)) and s > 0 for s in scale[:2]):
        scale = (float(scale[0]), float(scale[1]))
    else:
        scale = None
    if transpose and scale:
        scale = (scale[1], scale[0])       # the axes were swapped, so the scale pair must be too
    vox = _first_number(meta, ("voxelsize", "voxel_size", "voxel_size_um", "voxelsize_um"))
    return Mesh(name, x, y, z, valid, meta, scale, vox, n_invalid)


def load_mesh(path, invalid_value=-1.0, transpose=False):
    path = str(path)
    if not os.path.isdir(path):
        raise InputError(f"mesh path is not a directory: {path}")
    import tifffile
    grids = {}
    for ax in "xyz":
        f = os.path.join(path, f"{ax}.tif")
        if not os.path.isfile(f):
            raise InputError(f"missing {ax}.tif in {path}")
        try:
            grids[ax] = np.asarray(tifffile.imread(f))
        except Exception as e:  # noqa: BLE001 - re-raise with context
            raise InputError(f"cannot read {f}: {e}") from e
    mf = os.path.join(path, "meta.json")
    if not os.path.isfile(mf):
        raise InputError(f"missing meta.json in {path}")
    try:
        with open(mf) as fh:
            meta = json.load(fh)
    except Exception as e:  # noqa: BLE001
        raise InputError(f"cannot parse {mf}: {e}") from e
    if not isinstance(meta, dict):
        raise InputError(f"{mf} must hold a JSON object")
    mask = None
    mp = os.path.join(path, "mask.tif")
    if os.path.isfile(mp):
        try:
            mask = np.asarray(tifffile.imread(mp))
        except Exception as e:  # noqa: BLE001
            raise InputError(f"cannot read {mp}: {e}") from e
    return build_mesh(os.path.basename(os.path.normpath(path)), grids["x"], grids["y"],
                      grids["z"], meta, invalid_value, transpose, mask)


# ---------------------------------------------------------------- volumes
# Convention: a CT pixel/slice at level L (ct_scale = 2**L mesh voxels per pixel) covers the
# voxels [k*sc, k*sc + sc - 1]; its centre is k*sc + (sc - 1)/2 in level-0 voxel coordinates.
def slice_index_for(z, ct_scale):
    """Slice holding level-0 height z: floor(z / sc) (the epsilon absorbs float noise)."""
    return int(math.floor(z / ct_scale + 1e-9))


def to_px(xy, ct_scale):
    """Level-0 voxel coordinates -> CT pixel coordinates (pixel centres at integers)."""
    return (np.asarray(xy, dtype=np.float64) - (ct_scale - 1) / 2) / ct_scale


class ArrayVolume:
    """CT volume held in memory, indexed [z, y, x]. `ct_scale` = mesh voxels per CT pixel."""

    def __init__(self, data, ct_scale=1.0):
        data = np.asarray(data)
        if data.ndim != 3:
            raise InputError(f"volume must be 3-D (z, y, x), got shape {data.shape}")
        self.data, self.ct_scale = data, float(ct_scale)
        self.shape_yx = data.shape[1:]

    def slice_index(self, z):
        zi = slice_index_for(z, self.ct_scale)
        if not 0 <= zi < self.data.shape[0]:
            raise InputError(f"height z={z} maps to slice {zi}, outside the volume "
                             f"(0..{self.data.shape[0] - 1})")
        return zi

    def probe_shape(self, z):
        self.slice_index(z)
        return tuple(self.shape_yx)

    def tile(self, z, x0, y0, x1, y1):
        return np.asarray(self.data[self.slice_index(z), y0:y1, x0:x1], dtype=np.float32)


def check_ome_scale(node, level, path):
    """This tool treats level L as 2**L smaller on every axis. If the OME-Zarr scale transforms say
    otherwise (e.g. z not downsampled) the slice/pixel maths would be silently wrong: refuse."""
    attrs = dict(node.attrs)
    ms = attrs.get("multiscales") or (attrs.get("ome") or {}).get("multiscales")
    datasets = ms[0].get("datasets", []) if ms else []
    if not datasets or level >= len(datasets):
        return

    def sc(ds):
        for t in ds.get("coordinateTransformations", []) or []:
            if t.get("type") == "scale" and "scale" in t:
                return [float(v) for v in t["scale"]][-3:]
        return None
    s0, s1 = sc(datasets[0]), sc(datasets[level])
    if s0 and s1 and len(s0) == len(s1) == 3:
        rel = [b / a for a, b in zip(s0, s1)]
        if any(abs(r - 2.0 ** level) > 1e-6 * 2.0 ** level for r in rel):
            raise InputError(f"{path}: OME scale transforms put level {level} at {rel} x level 0 (z, y, x) but this "
                             f"tool assumes {2.0 ** level:g} on every axis; use level 0 or resample the pyramid")


class ZarrVolume(ArrayVolume):
    """OME-Zarr level `level` (default 0). Coordinates are level-0 voxels."""

    def __init__(self, path, level=0):
        if not os.path.exists(str(path)):
            raise InputError(f"zarr path does not exist: {path}")
        import zarr
        try:
            node = zarr.open(str(path), mode="r")
            arr = node[str(level)] if hasattr(node, "keys") else node
        except Exception as e:  # noqa: BLE001
            raise InputError(f"cannot open zarr level {level} in {path}: {e}") from e
        if hasattr(node, "keys"):
            check_ome_scale(node, level, path)
        if len(arr.shape) != 3:
            raise InputError(f"zarr array must be 3-D (z, y, x), got {arr.shape}")
        self.data, self.ct_scale = arr, float(2 ** level)
        self.shape_yx = tuple(arr.shape[1:])


class PngVolume:
    """Directory of 2-D slice PNGs. Slice file index = floor(z / ct_scale)."""

    def __init__(self, directory, pixel_um, voxel_um, pattern="{z:05d}.png"):
        if not os.path.isdir(str(directory)):
            raise InputError(f"PNG directory does not exist: {directory}")
        if not (pixel_um and voxel_um and pixel_um > 0 and voxel_um > 0):
            raise InputError("PNG input needs --png-pixel-um and a mesh voxel size "
                             "(meta.json or --voxel-size-um)")
        self.dir, self.pattern = str(directory), pattern
        self.ct_scale = float(pixel_um) / float(voxel_um)
        self._shape = None

    @property
    def shape_yx(self):
        if self._shape is None:
            raise InputError("PNG shape unknown until the first slice is read")
        return self._shape

    def _load(self, z):
        from PIL import Image
        zi = slice_index_for(z, self.ct_scale)
        f = os.path.join(self.dir, self.pattern.format(z=zi))
        if not os.path.isfile(f):
            raise InputError(f"slice PNG not found for z={z}: {f}")
        arr = np.asarray(Image.open(f))
        if arr.ndim == 3:
            arr = arr[..., :3].mean(axis=2)
        self._shape = arr.shape
        return arr

    def tile(self, z, x0, y0, x1, y1):
        return self._load(z)[y0:y1, x0:x1].astype(np.float32)

    def probe_shape(self, z):
        self._load(z)
        return self._shape


def mesh_voxel_um(a, b, override=None):
    if override:
        return float(override)
    for m in (a, b):
        if m.voxel_um:
            return m.voxel_um
    return None


def ceil_int(v):
    return int(math.ceil(v))
