"""Our readers vs. files written exactly the way ScrollPrize/villa (VC3D) writes them. See docs/FORMATS.md.

The grid is deliberately non-square (H=6 rows, W=8 cols) with different spacing and scale on the two
axes, so any row/column or x/y swap shows up. Cases marked xfail are known mismatches
(BUG-A*); they are listed in docs/FORMATS.md and fixed in the review branch.
"""
import json

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")

import ssc_io  # noqa: E402
from vc3d_writers import (read_control_points_reference, read_native_reference,  # noqa: E402
                          read_thaumato_reference, write_tifxyz, write_umbilicus_control_points,
                          write_umbilicus_native, write_umbilicus_text_zyx, write_umbilicus_thaumato)

H, W = 6, 8
SX, SY = 0.1, 0.2          # grid cells per voxel: columns are 10 voxels apart, rows 5 voxels apart


def make_xyz():
    r, c = np.mgrid[0:H, 0:W].astype(np.float64)
    x = 1000 + 10 * c + 0.5 * r
    y = 2000 + 5 * r + 0.25 * c
    z = 3000 + 3 * c - 2 * r
    return np.stack([x, y, z], axis=-1).astype(np.float32)


@pytest.fixture
def xyz():
    return make_xyz()


def _ink_surface():
    sys_path = __import__("sys").path
    p = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "tools" / "ink_infer")
    if p not in sys_path:
        sys_path.insert(0, p)
    import surface
    return surface


# ----------------------------------------------------------------- tifxyz: sheet_spacing_check
@pytest.mark.parametrize("tiled", [False, True])
def test_ssc_loads_axis_order_scale_dtype(tmp_path, xyz, tiled):
    d = write_tifxyz(tmp_path / "seg", xyz, (SX, SY), tiled=tiled)
    m = ssc_io.load_mesh(d)
    assert m.shape == (H, W)                       # (rows, cols), not (W, H)
    np.testing.assert_allclose(m.x, xyz[..., 0])   # x.tif is the x coordinate
    np.testing.assert_allclose(m.y, xyz[..., 1])
    np.testing.assert_allclose(m.z, xyz[..., 2])
    assert m.valid.all() and m.n_invalid == 0
    assert m.scale == (pytest.approx(SX), pytest.approx(SY))   # scale[0] <-> columns, scale[1] <-> rows
    assert 1 / m.scale[0] == pytest.approx(10.0) and 1 / m.scale[1] == pytest.approx(5.0)
    # along a row (varying column) x advances by 10 voxels = 1 / scale[0]
    assert np.hypot(np.diff(m.x, axis=1), np.diff(m.y, axis=1)).mean() == pytest.approx(10.0, abs=0.1)


def test_ssc_invalid_points(tmp_path, xyz):
    bad = xyz.copy()
    bad[2, 3] = (-1, -1, -1)            # the VC3D sentinel
    bad[4, 5] = (-1, 2222, 3333)        # partial sentinel: any -1 coordinate invalidates the cell
    bad[0, 0, 2] = np.nan               # non-finite
    d = write_tifxyz(tmp_path / "seg", bad, (SX, SY))
    m = ssc_io.load_mesh(d)
    assert m.n_invalid == 3
    assert not m.valid[2, 3] and not m.valid[4, 5] and not m.valid[0, 0]
    assert m.valid.sum() == H * W - 3
    assert np.isnan(m.x[2, 3]) and np.isnan(m.z[4, 5])      # no -1 leaks into later arithmetic


def test_ssc_tolerates_extra_meta_keys(tmp_path, xyz):
    d = write_tifxyz(tmp_path / "seg", xyz, (SX, SY), extra_meta={"tags": {"approved": {}}, "components": [[0, 1]]})
    m = ssc_io.load_mesh(d)
    assert m.meta["bbox"][0] == pytest.approx([1000.0, 2000.0, 2990.0])
    assert m.meta["format"] == "tifxyz" and m.meta["type"] == "seg"


def test_written_bbox_order_is_xyz(tmp_path, xyz):
    """meta.json bbox = [[xmin, ymin, zmin], [xmax, ymax, zmax]] (QuadSurface.cpp:2461-2467)."""
    d = write_tifxyz(tmp_path / "seg", xyz, (SX, SY))
    bb = json.loads((d / "meta.json").read_text())["bbox"]
    lo, hi = np.array(bb[0]), np.array(bb[1])
    np.testing.assert_allclose(lo, xyz.reshape(-1, 3).min(axis=0))
    np.testing.assert_allclose(hi, xyz.reshape(-1, 3).max(axis=0))
    assert lo[0] >= 1000 and hi[0] <= 1080          # first entry is x, not z
    assert lo[2] >= 2980                            # third entry is z


def test_ssc_mask_tif_invalidates(tmp_path, xyz):
    mask = np.full((H, W), 255, np.uint8)
    mask[1, 1] = 0
    d = write_tifxyz(tmp_path / "seg", xyz, (SX, SY), mask=mask)
    m = ssc_io.load_mesh(d)
    assert not m.valid[1, 1]


# ----------------------------------------------------------------- tifxyz: ink_infer
@pytest.mark.parametrize("tiled", [False, True])
def test_ink_mesh_axis_order_and_scale(tmp_path, xyz, tiled):
    S = _ink_surface()
    d = write_tifxyz(tmp_path / "seg", xyz, (SX, SY), tiled=tiled)
    m = S.load_mesh(d)
    assert m.P.shape == (H, W, 3)
    np.testing.assert_allclose(m.P, xyz.astype(np.float64))      # last axis is (x, y, z)
    assert m.scale == (pytest.approx(SX), pytest.approx(SY))


def test_ink_resample_uses_scale_per_axis(tmp_path, xyz):
    S = _ink_surface()
    m = S.load_mesh(write_tifxyz(tmp_path / "seg", xyz, (SX, SY)))
    s = S.resample_mesh(m, 1.0)                  # 1 voxel per output pixel
    assert s.shape == (26, 71)                   # rows: 5 cells * 5 vox + 1, cols: 7 cells * 10 vox + 1
    # output pixel (i, j) = i voxels down the rows, j voxels along the columns
    for i, j in [(0, 0), (5, 10), (25, 70), (13, 33)]:
        r, c = i * SY, j * SX                    # grid cell coordinates
        exp = np.array([1000 + 10 * c + 0.5 * r, 2000 + 5 * r + 0.25 * c, 3000 + 3 * c - 2 * r])
        np.testing.assert_allclose(s.P[i, j], exp, atol=1e-3)


def test_ink_invalid_points_propagate(tmp_path, xyz):
    S = _ink_surface()
    bad = xyz.copy()
    bad[2, 3] = (-1, -1, -1)
    bad[4, 5] = (-1, 2222, 3333)
    m = S.load_mesh(write_tifxyz(tmp_path / "seg", bad, (SX, SY)))
    assert m.n_invalid == 2
    assert np.isnan(m.P[2, 3]).all() and np.isnan(m.P[4, 5]).all()
    s = S.resample_mesh(m, 1.0)
    assert not s.valid.all()
    # output pixel exactly on the hole is invalid; one far from it is valid
    assert not s.valid[int(2 / SY), int(3 / SX)]
    assert s.valid[0, 0]


def test_ink_mask_tif_invalidates(tmp_path, xyz):
    S = _ink_surface()
    mask = np.full((H, W), 255, np.uint8)
    mask[1, 1] = 0
    m = S.load_mesh(write_tifxyz(tmp_path / "seg", xyz, (SX, SY), mask=mask))
    assert np.isnan(m.P[1, 1]).all()


# ----------------------------------------------------------------- umbilicus
ZYX = [(0, 120, 100), (250, 123, 98), (500, 130, 101), (1000, 128, 105)]


def test_uf_writer_matches_villa_json_reader(tmp_path):
    """tools/umbilicus_finder writes the file villa's json_umbilicus_z_to_yx reads: keys z/y/x, sorted by z."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "tools" / "umbilicus_finder"))
    import uf_io
    rows = [dict(z=float(z), y=float(y), x=float(x), flag="OK") for z, y, x in reversed(ZYX)]  # unsorted input
    p = tmp_path / "umb.json"
    assert uf_io.write_villa_json(p, rows) == len(ZYX)
    got = read_control_points_reference(p)
    np.testing.assert_allclose(got, np.array(ZYX, float))
    # the same interpolation villa builds: z -> (y, x)
    from scipy.interpolate import interp1d
    f = interp1d(got[:, 0], got[:, 1:], axis=0, fill_value="extrapolate")
    np.testing.assert_allclose(f(250), [123, 98])


def test_umbilicus_formats_agree(tmp_path):
    """All four documented umbilicus encodings decode to the same (z, y, x) points."""
    want = np.array(ZYX, float)
    write_umbilicus_control_points(tmp_path / "a.json", ZYX)
    write_umbilicus_native(tmp_path / "b.json", ZYX)
    write_umbilicus_thaumato(tmp_path / "c.txt", ZYX)
    np.testing.assert_allclose(read_control_points_reference(tmp_path / "a.json"), want)
    np.testing.assert_allclose(read_native_reference(tmp_path / "b.json"), want)
    np.testing.assert_allclose(read_thaumato_reference(tmp_path / "c.txt"), want)
    # thaumato text really is `y, z, x` + 500, i.e. the first row 120+500, 0+500, 100+500
    assert (tmp_path / "c.txt").read_text().splitlines()[0].replace(" ", "") == "620,500,600"
    write_umbilicus_text_zyx(tmp_path / "d.txt", ZYX)
    assert (tmp_path / "d.txt").read_text().splitlines()[1] == "0, 120, 100"
