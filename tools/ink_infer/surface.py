"""Surface-volume extraction for ink_infer: tifxyz mesh + CT -> (D, H, W) layers (MIT).

CPU/numpy only (no torch). Coordinates are level-0 volume voxels, arrays are [z, y, x].
"""
from __future__ import annotations

import json
import os

import numpy as np
from scipy.ndimage import map_coordinates


class InputError(ValueError):
    """Unusable user input (bad path, missing file, mismatched shapes)."""


# ------------------------------------------------------------------ mesh
def mask_validity(mask, shape):
    """VC3D mask.tif -> (H, W) bool: valid only if every covered mask pixel is >= 255 (QuadSurface.cpp:2776-2840)."""
    m = np.asarray(mask)
    if m.ndim == 3:                                    # channel 0 carries validity
        m = m[..., 0] if m.shape[-1] <= 4 else m[0]
    H, W = shape
    if m.ndim != 2 or m.shape[0] % H or m.shape[1] % W or not m.shape[0] or not m.shape[1]:
        raise InputError(f"mask.tif shape {tuple(np.shape(mask))} is not the grid {H}x{W} or a whole multiple of it")
    fy, fx = m.shape[0] // H, m.shape[1] // W
    return (m >= 255).reshape(H, fy, W, fx).all(axis=(1, 3))


class Mesh:
    def __init__(self, x, y, z, meta, name="mesh", invalid_value=-1.0, mask=None):
        x, y, z = (np.array(a, dtype=np.float64) for a in (x, y, z))   # copies
        if x.ndim != 2 or not (x.shape == y.shape == z.shape):
            raise InputError(f"{name}: x/y/z must be 2-D and the same shape, got {x.shape}, {y.shape}, {z.shape}")
        bad = ~(np.isfinite(x) & np.isfinite(y) & np.isfinite(z))
        bad |= (x == invalid_value) | (y == invalid_value) | (z == invalid_value)
        if mask is not None:                             # masked-out cells keep real x/y/z in VC3D files
            bad |= ~mask_validity(mask, x.shape)
        for a in (x, y, z):
            a[bad] = np.nan
        self.P = np.stack([x, y, z], axis=-1)           # (rows, cols, 3) xyz, NaN = no data
        self.meta, self.name, self.n_invalid = dict(meta or {}), name, int(bad.sum())
        sc = self.meta.get("scale")
        self.scale = (float(sc[0]), float(sc[1])) if (
            isinstance(sc, (list, tuple)) and len(sc) >= 2 and sc[0] > 0 and sc[1] > 0) else None
        vox = None
        for k in ("voxelsize", "voxel_size", "voxel_size_um", "voxelsize_um"):
            v = self.meta.get(k)
            if isinstance(v, (int, float)) and v > 0:
                vox = float(v)
                break
        self.voxel_um = vox


def load_mesh(path, invalid_value=-1.0):
    path = str(path)
    if not os.path.isdir(path):
        raise InputError(f"mesh path is not a directory: {path}")
    import tifffile
    g = {}
    for ax in "xyz":
        f = os.path.join(path, f"{ax}.tif")
        if not os.path.isfile(f):
            raise InputError(f"missing {ax}.tif in {path}")
        g[ax] = tifffile.imread(f)
    mf = os.path.join(path, "meta.json")
    try:
        meta = json.load(open(mf)) if os.path.isfile(mf) else {}
    except Exception as e:  # noqa: BLE001
        raise InputError(f"cannot parse {mf}: {e}") from e
    mask = None
    mp = os.path.join(path, "mask.tif")
    if os.path.isfile(mp):
        mask = tifffile.imread(mp)
    return Mesh(g["x"], g["y"], g["z"], meta, os.path.basename(os.path.normpath(path)), invalid_value, mask)


# --------------------------------------------------------------- resampling
class Surface:
    """Regular output grid: P (H, W, 3) positions, N (H, W, 3) unit normals, valid (H, W)."""

    def __init__(self, P, N):
        self.P, self.N = P, N
        self.valid = np.isfinite(P).all(axis=-1) & np.isfinite(N).all(axis=-1)
        self.shape = P.shape[:2]


def resample_mesh(mesh: Mesh, step_vox: float, flip_normal=False, scale=None) -> Surface:
    """Resample the mesh grid so output pixels are `step_vox` voxels apart along the surface.

    The grid step is 1/scale voxels (meta.json `scale` = [sx, sy], x <-> columns, y <-> rows),
    so one output pixel is step_vox * scale grid cells. Any output pixel touching a no-data
    cell is invalid (NaN propagates through the linear interpolation).
    """
    sc = scale or mesh.scale
    if sc is None:
        raise InputError("mesh has no usable meta.json 'scale'; pass --mesh-scale SX SY")
    rows, cols = mesh.P.shape[:2]
    nr = int(np.floor((rows - 1) / (step_vox * sc[1]))) + 1
    nc = int(np.floor((cols - 1) / (step_vox * sc[0]))) + 1
    if nr < 2 or nc < 2:
        raise InputError(f"mesh grid {rows}x{cols} is too small for step {step_vox} vox at scale {sc}")
    rr, cc = np.meshgrid(np.arange(nr) * step_vox * sc[1], np.arange(nc) * step_vox * sc[0], indexing="ij")
    P = np.stack([map_coordinates(mesh.P[..., k], [rr, cc], order=1, mode="nearest", prefilter=False)
                  for k in range(3)], axis=-1)
    with np.errstate(all="ignore"):
        dr = np.gradient(P, step_vox, axis=0)
        dc = np.gradient(P, step_vox, axis=1)
        n = np.cross(dr, dc)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
    if flip_normal:
        n = -n
    return Surface(P, n)


def pad_surface(s: Surface, minimum: int) -> Surface:
    """Pad with invalid pixels so both sides are >= minimum (tiny segments)."""
    H, W = s.shape
    ph, pw = max(0, minimum - H), max(0, minimum - W)
    if not (ph or pw):
        return s
    P = np.full((H + ph, W + pw, 3), np.nan)
    N = np.full((H + ph, W + pw, 3), np.nan)
    P[:H, :W], N[:H, :W] = s.P, s.N
    return Surface(P, N)


# -------------------------------------------------------------------- CT
def _check_ome_scale(node, level, path):
    """This module treats level L as 2**L smaller on every axis; refuse an OME pyramid that says otherwise."""
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


class CTVolume:
    """[z, y, x] array-like (numpy or zarr) at OME level `level`; coordinates are level-0 voxels.

    `norm_max` converts to the training scale: uint8 -> /255 (== x257/65535), uint16 -> /65535.
    """

    def __init__(self, data, level=0, norm_max=None):
        if len(data.shape) != 3:
            raise InputError(f"CT volume must be 3-D (z, y, x), got shape {tuple(data.shape)}")
        self.data, self.level, self.s = data, level, float(2 ** level)
        if norm_max is None:
            dt = np.dtype(data.dtype)
            norm_max = float(np.iinfo(dt).max) if dt.kind in "ui" else 1.0
        self.norm_max = float(norm_max)

    @classmethod
    def open_zarr(cls, path, level=0, norm_max=None):
        if not os.path.exists(str(path)):
            raise InputError(f"zarr path does not exist: {path}")
        import zarr
        try:
            node = zarr.open(str(path), mode="r")
            arr = node[str(level)] if hasattr(node, "keys") else node
        except Exception as e:  # noqa: BLE001
            raise InputError(f"cannot open zarr level {level} in {path}: {e}") from e
        if hasattr(node, "keys"):
            _check_ome_scale(node, level, path)
        return cls(arr, level, norm_max)

    def to_px(self, v):
        """level-0 voxel coordinate -> pixel index at this level (pixel-centre convention)."""
        return (v - (self.s - 1) / 2) / self.s

    def sample(self, pts_xyz):
        """Trilinear samples at level-0 xyz points (..., 3); outside the volume -> 0. Normalised."""
        shp = pts_xyz.shape[:-1]
        q = self.to_px(pts_xyz.reshape(-1, 3))
        ok = np.isfinite(q).all(axis=1)
        out = np.zeros(len(q), np.float32)
        if ok.any():
            qq = q[ok]
            lo = np.floor(qq.min(axis=0)).astype(int) - 1
            hi = np.ceil(qq.max(axis=0)).astype(int) + 2
            zyx_max = np.array(self.data.shape)[::-1]            # (x, y, z)
            lo, hi = np.maximum(lo, 0), np.minimum(hi, zyx_max)
            if (hi > lo).all():
                blk = np.asarray(self.data[lo[2]:hi[2], lo[1]:hi[1], lo[0]:hi[0]], dtype=np.float32)
                c = (qq - lo)[:, ::-1].T                          # (z, y, x) block coords
                out[ok] = map_coordinates(blk, c, order=1, mode="constant", cval=0.0, prefilter=False)
        return (out / self.norm_max).reshape(shp)


def layer_offsets(depth, step_vox):
    """Surface-centred offsets along the normal, in voxels: (d - (D-1)/2) * step."""
    return (np.arange(depth) - (depth - 1) / 2.0) * step_vox


def extract_patch(vol: CTVolume, surf: Surface, y0, x0, size, offsets):
    """(D, size, size) float32 surface volume + (size, size) valid mask for one patch."""
    P = surf.P[y0:y0 + size, x0:x0 + size]
    N = surf.N[y0:y0 + size, x0:x0 + size]
    valid = surf.valid[y0:y0 + size, x0:x0 + size]
    out = np.zeros((len(offsets), size, size), np.float32)
    if valid.any():
        pts = P[None] + offsets[:, None, None, None] * N[None]    # (D, size, size, 3)
        out = vol.sample(np.where(valid[None, ..., None], pts, np.nan))
        out[:, ~valid] = 0.0
    return out, valid
