"""Writers (and reference readers) that reproduce the ScrollPrize/villa on-disk formats byte-for-byte
in the ways that matter to a reader: tifxyz surfaces and umbilicus files. See docs/FORMATS.md for the
source references (file:line) each choice below comes from.

Test support only. Needs numpy + tifffile (both installed by CI).
"""
from __future__ import annotations

import json
import uuid as _uuid
from pathlib import Path

import numpy as np


def write_tifxyz(path, xyz, scale, *, mask=None, tiled=False, extra_meta=None):
    """Write a tifxyz directory the way villa `QuadSurface::save` does.

    xyz   : (H, W, 3) array, last axis = (x, y, z) in level-0 volume voxels; rows = grid v, cols = grid u.
            Invalid vertices must already be (-1, -1, -1).
    scale : (sx, sy) = grid cells per voxel along columns / rows (meta.json "scale").
    mask  : optional (H, W) uint8, 255 = valid, 0 = invalid (written as mask.tif; coordinates are kept).
    tiled : write x/y/z.tif tiled (VC3D reads both; its own writer is untiled).

    Files: x.tif, y.tif, z.tif = single-channel float32, shape (H, W), one file per coordinate
    (QuadSurface.cpp:2243-2250, cv::split of a Mat_<Vec3f>); meta.json with bbox/format/scale/type/uuid
    (QuadSurface.cpp:2454-2476).
    """
    import tifffile
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    xyz = np.asarray(xyz, dtype=np.float32)
    assert xyz.ndim == 3 and xyz.shape[2] == 3
    kw = dict(tile=(16, 16)) if tiled else {}
    for k, ax in enumerate("xyz"):
        tifffile.imwrite(str(path / f"{ax}.tif"), np.ascontiguousarray(xyz[..., k]), **kw)
    if mask is not None:
        tifffile.imwrite(str(path / "mask.tif"), np.asarray(mask, dtype=np.uint8))
    # bbox: QuadSurface::bbox() = min/max over cells whose x != -1, order [[xmin,ymin,zmin],[xmax,ymax,zmax]]
    ok = xyz[..., 0] != -1
    if ok.any():
        pts = xyz[ok]
        bbox = [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()]
    else:
        bbox = [[-1.0, -1.0, -1.0], [-1.0, -1.0, -1.0]]
    meta = {"bbox": bbox, "format": "tifxyz", "scale": [float(scale[0]), float(scale[1])],
            "type": "seg", "uuid": str(_uuid.uuid4())}
    meta.update(extra_meta or {})
    (path / "meta.json").write_text(json.dumps(meta, indent=4))
    return path


# ------------------------------------------------------------------ umbilicus
def write_umbilicus_control_points(path, zyx):
    """villa spiral-fitting/umbilicus.py `json_umbilicus_z_to_yx` input: {"control_points": [{z, y, x}]}."""
    pts = [{"z": float(z), "y": float(y), "x": float(x)} for z, y, x in zyx]
    Path(path).write_text(json.dumps({"control_points": pts}, indent=2))


def write_umbilicus_native(path, zyx):
    """vc_object_store native file: {"vc_umbilicus_json_version": "1", "points": [{x, y, z}]}
    (GeometryOutput.cpp:66-75)."""
    pts = [{"x": float(x), "y": float(y), "z": float(z)} for z, y, x in zyx]
    Path(path).write_text(json.dumps({"vc_umbilicus_json_version": "1", "points": pts}, indent=2))


def write_umbilicus_thaumato(path, zyx):
    """'thaumato' text: integer `y, z, x` per line with +500 added (spiral-fitting/umbilicus.py:6-13)."""
    lines = [f"{int(round(y)) + 500}, {int(round(z)) + 500}, {int(round(x)) + 500}" for z, y, x in zyx]
    Path(path).write_text("\n".join(lines) + "\n")


def write_umbilicus_text_zyx(path, zyx):
    """vc_object_store text import: `z, y, x` per line, '#' comments allowed (UmbilicusFile.cpp:45-77)."""
    Path(path).write_text("# z, y, x\n" + "\n".join(f"{z}, {y}, {x}" for z, y, x in zyx) + "\n")


# reference readers: line-by-line transcriptions of the villa code, returning (N, 3) arrays of (z, y, x)
def read_thaumato_reference(path):
    """Transcription of spiral-fitting/umbilicus.py read_thaumato_umbilicus + the yx swap in
    thaumato_umbilicus_z_to_yx."""
    lines = Path(path).read_text().splitlines()
    a = np.asarray([tuple(map(int, ln.strip().replace(" ", "").split(","))) for ln in lines])[:, [2, 0, 1]] - 500
    zs, xys = a[:, 2], a[:, :2]
    yxs = xys[:, ::-1]
    return np.column_stack([zs, yxs[:, 0], yxs[:, 1]]).astype(float)


def read_control_points_reference(path):
    """Transcription of json_umbilicus_z_to_yx (sorted by z) -> (N, 3) of (z, y, x)."""
    data = json.loads(Path(path).read_text())
    pts = sorted(data["control_points"], key=lambda p: p["z"])
    return np.asarray([(p["z"], p["y"], p["x"]) for p in pts], dtype=float)


def read_native_reference(path):
    """Transcription of formats/UmbilicusInput.cpp -> (N, 3) of (z, y, x)."""
    root = json.loads(Path(path).read_text())
    assert root["vc_umbilicus_json_version"] == "1"
    return np.asarray([(p["z"], p["y"], p["x"]) for p in root["points"]], dtype=float)
