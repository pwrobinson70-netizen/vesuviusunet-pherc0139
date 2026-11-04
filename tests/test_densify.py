"""vun-densify: bilinear densification of tifxyz grids on a phantom with a known analytic surface."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
import tifffile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from vun_tools import densify as dz  # noqa: E402

R, CX, CY = 300.0, 400.0, 100.0           # cylinder axis along z through (CX, CY): x = CX + R cos t, y = CY + R sin t


def cylinder(h=24, w=36, step=20.0, t0=-0.4):
    """Coarse grid of a cylinder patch: columns run round the axis (arc step voxels apart), rows along z (step apart)."""
    t = t0 + np.arange(w) * (step / R)
    z = 5000.0 + np.arange(h) * step
    T, Z = np.meshgrid(t, z)
    return CX + R * np.cos(T), CY + R * np.sin(T), Z


def write(path, x, y, z, valid, scale=(0.05, 0.05)):
    path.mkdir(parents=True)
    for a, g in zip("xyz", (x, y, z)):
        tifffile.imwrite(path / f"{a}.tif", np.where(valid, g, -1.0).astype(np.float32))
    tifffile.imwrite(path / "mask.tif", (valid * 255).astype(np.uint8))
    (path / "meta.json").write_text(json.dumps({"scale": list(scale), "format": "tifxyz"}))


def test_densified_cylinder_lies_within_half_a_voxel_of_the_analytic_surface():
    x, y, z = cylinder()
    valid = np.ones(x.shape, bool)
    x2, y2, z2, v2 = dz.densify_arrays(x, y, z, valid, 20, 20)
    assert x2.shape == ((24 - 1) * 20 + 1, (36 - 1) * 20 + 1) and v2.all()
    radial = np.hypot(x2 - CX, y2 - CY)
    assert np.abs(radial - R).max() < 0.5          # chord sagitta 20^2 / (8 * 300) = 0.17 voxel
    assert np.abs(radial - R).max() > 0.05         # and it really is a chord (not secretly exact)
    # z is linear in the row index: exact
    assert np.allclose(z2[:, 0], 5000.0 + np.arange(z2.shape[0]) * 1.0)


def test_coarse_nodes_are_kept_exactly():
    x, y, z = cylinder()
    x2, y2, z2, v2 = dz.densify_arrays(x, y, z, np.ones(x.shape, bool), 5, 4)
    assert np.allclose(x2[::5, ::4], x) and np.allclose(y2[::5, ::4], y) and np.allclose(z2[::5, ::4], z)


def test_never_interpolates_across_invalid_cells():
    x, y, z = cylinder(8, 10)
    valid = np.ones(x.shape, bool)
    valid[3, 4] = False
    valid[:, 7] = False                             # a whole invalid column splits the patch
    x2, y2, z2, v2 = dz.densify_arrays(x, y, z, valid, 4, 4)
    # nodes that depend on an invalid coarse node are invalid
    assert not v2[3 * 4, 4 * 4]
    assert not v2[2 * 4 + 1:4 * 4, 3 * 4 + 1:5 * 4].any()
    assert not v2[:, 6 * 4 + 1:8 * 4].any()
    # no value was invented there, and valid nodes are unaffected
    assert np.isnan(x2[~v2]).all() and np.isfinite(x2[v2]).all()
    assert v2[0, 0] and v2[7 * 4, 0] and v2[0, 9 * 4]
    # nodes on the far side of the gap are valid again and exact
    assert v2[0, 8 * 4] and np.isclose(x2[0, 8 * 4], x[0, 8])


def test_factors_never_coarsen_and_follow_scale():
    assert dz.factors_for((0.05, 0.05), 1.0) == (20, 20)
    assert dz.factors_for((0.05, 0.1), 1.0) == (10, 20)       # (rows, cols) = (1/sy, 1/sx)
    assert dz.factors_for((0.05, 0.05), 40.0) == (1, 1)        # asking for a coarser grid does nothing
    with pytest.raises(ValueError):
        dz.factors_for((0.0, 0.05), 1.0)


def test_cli_writes_a_valid_tifxyz_with_updated_scale_and_note(tmp_path):
    x, y, z = cylinder(6, 8)
    valid = np.ones(x.shape, bool)
    valid[2, 2] = False
    write(tmp_path / "in.tifxyz", x, y, z, valid)
    assert dz.main([str(tmp_path / "in.tifxyz"), str(tmp_path / "out.tifxyz"), "--spacing", "5"]) == 0
    meta = json.loads((tmp_path / "out.tifxyz" / "meta.json").read_text())
    assert meta["scale"] == pytest.approx([0.05 * 4, 0.05 * 4])
    note = meta["densify_note"]
    assert note["factor_rows"] == 4 and note["factor_cols"] == 4 and note["shape_hw"] == [21, 29] and note["source_shape_hw"] == [6, 8]
    xo = tifffile.imread(tmp_path / "out.tifxyz" / "x.tif")
    mo = tifffile.imread(tmp_path / "out.tifxyz" / "mask.tif")
    assert xo.shape == (21, 29) and ((xo == -1.0) == (mo == 0)).all() and mo.max() == 255
    # the input is untouched
    assert tifffile.imread(tmp_path / "in.tifxyz" / "x.tif").shape == (6, 8)


def test_cli_rejects_bad_input(tmp_path, capsys):
    assert dz.main([str(tmp_path / "nope"), str(tmp_path / "o")]) == 2
    x, y, z = cylinder(4, 4)
    write(tmp_path / "in.tifxyz", x, y, z, np.ones(x.shape, bool))
    assert dz.main([str(tmp_path / "in.tifxyz"), str(tmp_path / "in.tifxyz")]) == 2     # refuses to overwrite
    assert dz.main([str(tmp_path / "in.tifxyz"), str(tmp_path / "o"), "--spacing", "0"]) == 2
