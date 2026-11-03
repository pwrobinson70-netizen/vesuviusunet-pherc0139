"""Regression tests for REVIEW_ROUND1 (docs/REVIEW_ROUND1.md). One failing test per fixed finding.

Synthetic data only. Finding ids (B1..) match the review document.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("zarr")

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "tools" / "ink_infer", ROOT / "tools" / "umbilicus_finder"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tifffile  # noqa: E402

import sheet_spacing_check as ssc  # noqa: E402
import ssc_io  # noqa: E402
from ssc_io import ArrayVolume, InputError, build_mesh  # noqa: E402
from test_sheet_spacing_check import PITCH, R0, cylinder, make_ct, run  # noqa: E402


# ---------------------------------------------------------------------------------------------
# B1 (BUG) sheet_spacing_check: max_gap_vox=20 is absolute. A tifxyz grid whose cut-line points are
# more than 20 voxels apart (VC3D scale 0.05 = 20 vox per cell) is split into one-point runs, no
# normals, no pitch: every point is "no pitch", clean fraction 0, with no warning.
@pytest.mark.parametrize("step", [20.0, 24.0, 30.0])
def test_B1_coarse_grid_is_not_split_into_single_point_runs(step):
    ct = make_ct(0.0)
    ncol = int(round(2 * np.pi * R0 / step))
    res = run(cylinder(R0, n_cols=ncol), cylinder(R0 + PITCH, n_cols=ncol), ct)
    for h in res["heights"]:
        assert h["no_pitch_fraction"] == 0.0
        assert h["clean_fraction"] > 0.95
        assert h["ct_pitch_vox"] == pytest.approx(PITCH, rel=0.05)


def test_B1_a_real_jump_still_splits_a_fine_grid():
    """The gap rule must still cut a line at a hole on a fine grid (step ~0.9 vox, gap 20 vox)."""
    m = cylinder(R0, n_cols=720)
    x = m.x.copy()
    x[:, 300:] += 60.0                       # a 60-voxel jump in the cut line at column 300
    m2 = build_mesh("j", x, m.y, m.z, {})
    line = ssc.cut_line(m2, 30.0, ssc.Params())
    assert line.run.max() >= 1 and line.run[line.col == 299][0] != line.run[line.col == 300][0]


# B2 (RISK -> loud) sheet_spacing_check: when no CT pitch can be measured the only trace is
# ct_pitch_vox = null; the top-level warnings stay empty although every number is unusable.
def test_B2_unmeasurable_pitch_is_a_warning():
    pitch, r0, n = 80.0, 240.0, 900
    cx = cy = 450.0
    yy, xx = np.mgrid[0:n, 0:n]
    d = (np.hypot(xx - cx, yy - cy) - r0 + pitch / 2) % pitch - pitch / 2
    sl = (20 + 180 * np.exp(-d ** 2 / (2 * (pitch / 8) ** 2))).astype(np.float32)
    vol = ArrayVolume(np.broadcast_to(sl, (3, n, n)).copy())
    th = np.linspace(0, 2 * np.pi, 1000, endpoint=False)

    def cyl(r):
        return build_mesh("m", np.tile(cx + r * np.cos(th), (3, 1)), np.tile(cy + r * np.sin(th), (3, 1)),
                          np.tile(np.arange(3.0)[:, None], (1, th.size)), {})
    res = ssc.run_check(cyl(r0), cyl(r0 + pitch), vol, [1.0], ssc.Params(band_height_vox=1.0))
    assert res["heights"][0]["ct_pitch_vox"] is None
    assert any("pitch" in w and "profile-halflen-vox" in w for w in res["warnings"]), res["warnings"]


# ---------------------------------------------------------------------------------------------
# B3 (BUG) mask.tif (255 = valid, 0 = invalid, coordinates kept under masked cells) is ignored by
# ssc_io.load_mesh and ink_infer surface.load_mesh. See docs/FORMATS.md section 1 (QuadSurface.cpp:2776).
def _write_tifxyz(d, mask=None):
    d.mkdir(parents=True, exist_ok=True)
    r, c = np.mgrid[0:6, 0:8].astype(np.float32)
    for ax, a in zip("xyz", (1000 + 10 * c, 2000 + 5 * r, 3000 + c + 0 * r)):
        tifffile.imwrite(str(d / f"{ax}.tif"), a.astype(np.float32))
    if mask is not None:
        tifffile.imwrite(str(d / "mask.tif"), mask)
    (d / "meta.json").write_text(json.dumps({"scale": [0.1, 0.2], "format": "tifxyz", "type": "seg"}))
    return d


def _ink_surface():
    import surface
    return surface


def test_B3_ssc_mask_tif_invalidates_cells(tmp_path):
    mask = np.full((6, 8), 255, np.uint8)
    mask[1, 1] = 0
    mask[4, 6] = 254                              # VC3D keeps only >= 255
    m = ssc_io.load_mesh(_write_tifxyz(tmp_path / "s", mask))
    assert not m.valid[1, 1] and not m.valid[4, 6]
    assert m.valid.sum() == 48 - 2 and m.n_invalid == 2
    assert np.isnan(m.x[1, 1]) and np.isnan(m.z[4, 6])


def test_B3_ssc_mask_tif_that_is_a_multiple_of_the_grid(tmp_path):
    mask = np.full((12, 16), 255, np.uint8)      # 2x the grid; a cell is valid only if all 4 pixels are
    mask[3, 5] = 0                                # one pixel of cell (1, 2)
    m = ssc_io.load_mesh(_write_tifxyz(tmp_path / "s", mask))
    assert not m.valid[1, 2] and m.valid.sum() == 47


def test_B3_ssc_mask_tif_with_wrong_shape_is_an_input_error(tmp_path):
    with pytest.raises(InputError, match="mask.tif"):
        ssc_io.load_mesh(_write_tifxyz(tmp_path / "s", np.full((5, 7), 255, np.uint8)))


def test_B3_no_mask_file_changes_nothing(tmp_path):
    m = ssc_io.load_mesh(_write_tifxyz(tmp_path / "s"))
    assert m.valid.all()


def test_B3_ink_mask_tif_invalidates_cells(tmp_path):
    S = _ink_surface()
    mask = np.full((6, 8), 255, np.uint8)
    mask[1, 1] = 0
    m = S.load_mesh(_write_tifxyz(tmp_path / "s", mask))
    assert np.isnan(m.P[1, 1]).all() and m.n_invalid == 1
    assert np.isfinite(m.P[0, 0]).all()


# ---------------------------------------------------------------------------------------------
# B4 (RISK -> loud) ssc_io.ZarrVolume and ink_infer CTVolume.open_zarr assume level L is 2**L smaller
# on every axis. umbilicus_finder reads the OME scale transforms. A pyramid that does not halve z
# (common for anisotropic data) made them read the wrong slice with no message.
def _anisotropic_ome_zarr(path):
    import zarr
    g = zarr.open_group(str(path), mode="w")
    zarr.open(str(path / "0"), mode="w", shape=(8, 16, 16), dtype="f4")
    zarr.open(str(path / "1"), mode="w", shape=(8, 8, 8), dtype="f4")            # z kept, xy halved
    g.attrs["multiscales"] = [{"version": "0.4", "axes": [{"name": n} for n in "zyx"], "datasets": [
        {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0, 1.0]}]},
        {"path": "1", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 2.0, 2.0]}]}]}]
    return path


def test_B4_ssc_zarr_with_non_isotropic_pyramid_is_an_input_error(tmp_path):
    p = _anisotropic_ome_zarr(tmp_path / "a.zarr")
    ssc_io.ZarrVolume(p, level=0)                                                # level 0 is fine
    with pytest.raises(InputError, match="scale"):
        ssc_io.ZarrVolume(p, level=1)


def test_B4_ink_zarr_with_non_isotropic_pyramid_is_an_input_error(tmp_path):
    S = _ink_surface()
    p = _anisotropic_ome_zarr(tmp_path / "a.zarr")
    S.CTVolume.open_zarr(p, level=0)
    with pytest.raises(S.InputError, match="scale"):
        S.CTVolume.open_zarr(p, level=1)


def test_B4_plain_halving_pyramid_still_opens(tmp_path):
    import zarr
    p = tmp_path / "ok.zarr"
    g = zarr.open_group(str(p), mode="w")
    zarr.open(str(p / "0"), mode="w", shape=(8, 16, 16), dtype="f4")
    zarr.open(str(p / "1"), mode="w", shape=(4, 8, 8), dtype="f4")
    assert ssc_io.ZarrVolume(p, level=1).ct_scale == 2.0                          # no OME metadata: legacy rule
    g.attrs["multiscales"] = [{"datasets": [
        {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1, 1, 1]}]},
        {"path": "1", "coordinateTransformations": [{"type": "scale", "scale": [2, 2, 2]}]}]}]
    assert ssc_io.ZarrVolume(p, level=1).ct_scale == 2.0


# ---------------------------------------------------------------------------------------------
# B5 (RISK -> loud) umbilicus_finder: if no slice is OK (e.g. no pitch could be estimated) the
# command still exits 0 and writes `{"control_points": []}`, which villa's reader cannot use.
def test_B5_empty_villa_export_is_reported(tmp_path, capsys):
    import umbilicus_finder as uf
    from test_umbilicus_finder import spiral
    from PIL import Image
    d = tmp_path / "png"
    d.mkdir()
    for z in range(3):
        Image.fromarray(np.clip(spiral(seed=z) * 120 + 20, 0, 255).astype(np.uint8)).save(d / f"{z:05d}.png")
    out = tmp_path / "out"
    rc = uf.main([str(d), "--out-dir", str(out), "--z-step", "1", "--min-votes", "100000000"])
    err = capsys.readouterr().err
    assert json.loads((out / "umbilicus_villa.json").read_text())["control_points"] == []
    assert "no OK slice" in err and rc == 0
