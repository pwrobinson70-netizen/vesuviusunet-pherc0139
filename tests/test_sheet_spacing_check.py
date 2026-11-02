"""Synthetic-data tests for tools/sheet_spacing_check (no real scan data)."""
import json

import numpy as np
import pytest
import tifffile

import sheet_spacing_check as ssc
from ssc_io import ArrayVolume, InputError, PngVolume, ZarrVolume, build_mesh, load_mesh

PITCH = 12.0
CX = CY = 256.0
NZ, NY, NX = 100, 512, 512
RADII = np.arange(40, 230, PITCH)          # sheet centres, 100 and 112 etc. are on sheets
R0 = 100.0
assert any(abs(RADII - R0) < 1e-6)


@pytest.fixture(scope="module")
def ct():
    """Concentric cylindrical sheets (axis along z), pitch 12 px, dark gaps between."""
    yy, xx = np.mgrid[0:NY, 0:NX]
    r = np.hypot(xx - CX, yy - CY)
    img = np.full((NY, NX), 20.0)
    for rc in RADII:
        img = np.maximum(img, 20 + 180 * np.exp(-((r - rc) ** 2) / (2 * 1.5 ** 2)))
    return np.broadcast_to(img.astype(np.float32), (NZ, NY, NX)).copy()


def cylinder(radius, n_cols=720, n_rows=NZ, name="m"):
    th = np.linspace(0, 2 * np.pi, n_cols, endpoint=False)
    x = np.tile(CX + radius * np.cos(th), (n_rows, 1))
    y = np.tile(CY + radius * np.sin(th), (n_rows, 1))
    z = np.tile(np.arange(n_rows, dtype=float)[:, None], (1, n_cols))
    return build_mesh(name, x, y, z, {"scale": [0.5, 0.5], "voxelsize": 10.0})


def run(a, b, ct, heights=(30.0, 50.0, 70.0), **kw):
    return ssc.run_check(a, b, ArrayVolume(ct), list(heights), ssc.Params(**kw), voxel_um=10.0)


def test_one_pitch_apart_is_clean(ct):
    res = run(cylinder(R0), cylinder(R0 + PITCH), ct)
    for h in res["heights"]:
        assert h["clean_fraction"] > 0.98
        assert h["median_ratio"] == pytest.approx(1.0, abs=0.05)
        assert h["ct_pitch_vox"] == pytest.approx(PITCH, rel=0.05)
        assert h["mesh_pitch_vox"] == pytest.approx(PITCH, rel=0.02)
        assert not h["pitch_mismatch_flag"]
    a = res["area"]
    expected = 2 * np.pi * R0 * 60.0 * (1e-3 ** 2)        # 3 heights x 20 vox, 10 um voxels
    assert a["clean_area_cm2"] == pytest.approx(expected, rel=0.03)
    assert a["clean_area_cm2"] == pytest.approx(a["sampled_area_cm2"], rel=1e-6)


def test_same_mesh_twice_is_shared(ct):
    res = run(cylinder(R0), cylinder(R0), ct)
    for h in res["heights"]:
        assert h["shared_fraction"] > 0.98
        assert h["clean_fraction"] < 0.02
        assert h["pitch_mismatch_flag"]                    # mesh pitch 0 vs CT pitch 12
    assert res["area"]["clean_area_cm2"] == 0.0


def test_two_pitches_apart_is_skipped(ct):
    res = run(cylinder(R0), cylinder(R0 + 2 * PITCH), ct)
    for h in res["heights"]:
        assert h["skipped_fraction"] > 0.98
        assert h["clean_fraction"] < 0.02
        assert h["median_ratio"] == pytest.approx(2.0, abs=0.1)


def test_mesh_in_dark_gap_fails_on_sheet(ct):
    # B at 117: 1.42 pitches from A (inside [0.5,1.5]) but 5 px from the sheet at 112
    res = run(cylinder(R0), cylinder(R0 + PITCH + 5), ct)
    for h in res["heights"]:
        assert h["onsheet_fraction_a"] > 0.98
        assert h["onsheet_fraction_b"] < 0.02
        assert h["clean_fraction"] < 0.02
        assert h["skipped_fraction"] == 0.0 and h["shared_fraction"] == 0.0


def test_height_outside_mesh_range_is_uncovered_not_clean(ct):
    a, b = cylinder(R0), cylinder(R0 + PITCH)
    res = run(a, b, ct, heights=(50.0, 500.0), band_height_vox=10.0)
    ok, out = res["heights"]
    assert ok["clean_fraction"] > 0.98 and not ok["uncovered_a"]
    assert out["uncovered_a"] and out["uncovered_b"]
    assert out["clean_fraction"] == 0.0 and out["n_points_a"] == 0
    assert out["uncovered_fraction"] == 1.0
    # only one of two heights is clean -> default N = ceil(2/2) = 1 still passes
    assert res["area"]["clean_columns"] == 720
    # requiring both heights now fails: the uncovered one counts as not clean
    res2 = run(a, b, ct, heights=(50.0, 500.0), band_height_vox=10.0, min_clean_heights=2)
    assert res2["area"]["clean_columns"] == 0


def test_only_one_mesh_covers_height(ct):
    a = cylinder(R0)
    short = cylinder(R0 + PITCH, n_rows=NZ)
    short.z[:] = short.z + 1000                          # B lives at z=1000..1099
    res = run(a, short, ct, heights=(50.0,), band_height_vox=10.0)
    h = res["heights"][0]
    assert h["uncovered_b"] and not h["uncovered_a"]
    assert h["clean_fraction"] == 0.0 and h["uncovered_fraction"] == 1.0


def test_mismatched_grid_shapes(ct):
    with pytest.raises(InputError, match="grid shapes differ"):
        run(cylinder(R0, n_cols=720), cylinder(R0 + PITCH, n_cols=600), ct)


def test_bad_input_paths(tmp_path):
    with pytest.raises(InputError, match="not a directory"):
        load_mesh(tmp_path / "nope")
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(InputError, match="missing x.tif"):
        load_mesh(d)
    with pytest.raises(InputError, match="zarr path does not exist"):
        ZarrVolume(tmp_path / "nope.zarr")
    with pytest.raises(InputError, match="PNG directory does not exist"):
        PngVolume(tmp_path / "nope", 10.0, 10.0)
    with pytest.raises(InputError, match="needs --png-pixel-um"):
        PngVolume(tmp_path, None, 10.0)


def test_bad_meta_and_mismatched_tifs(tmp_path):
    m = cylinder(R0)
    d = tmp_path / "seg"
    d.mkdir()
    for ax in "xyz":
        tifffile.imwrite(d / f"{ax}.tif", getattr(m, ax).astype(np.float32))
    (d / "meta.json").write_text("{not json")
    with pytest.raises(InputError, match="cannot parse"):
        load_mesh(d)
    (d / "meta.json").write_text("{}")
    tifffile.imwrite(d / "z.tif", m.z[:, :10].astype(np.float32))
    with pytest.raises(InputError, match="same shape"):
        load_mesh(d)


def _write_mesh(d, m):
    d.mkdir()
    for ax in "xyz":
        arr = np.nan_to_num(getattr(m, ax), nan=-1).astype(np.float32)
        tifffile.imwrite(d / f"{ax}.tif", arr)
    (d / "meta.json").write_text(json.dumps(m.meta))


def test_cli_end_to_end_zarr_png_overlay(tmp_path, ct):
    import zarr
    from PIL import Image
    _write_mesh(tmp_path / "a", cylinder(R0))
    _write_mesh(tmp_path / "b", cylinder(R0 + PITCH))
    zp = tmp_path / "ct.zarr"
    root = zarr.open_group(str(zp), mode="w")
    root.create_array("0", data=ct)
    pngs = tmp_path / "png"
    pngs.mkdir()
    for z in (30, 50, 70):
        Image.fromarray(np.clip(ct[z], 0, 255).astype(np.uint8)).save(pngs / f"{z:05d}.png")
    for src in (["--zarr", str(zp)], ["--png-dir", str(pngs), "--png-pixel-um", "10"]):
        out = tmp_path / "out"
        rc = ssc.main([str(tmp_path / "a"), str(tmp_path / "b"), *src, "--heights", "30,50,70",
                       "--out-json", str(out) + ".json", "--out-txt", str(out) + ".txt",
                       "--overlay-dir", str(tmp_path / "ov")])
        assert rc == 0
        rep = json.loads(open(str(out) + ".json").read())
        assert rep["params"]["ratio_min"] == 0.5
        assert all(h["clean_fraction"] > 0.98 for h in rep["result"]["heights"])
        assert "Area clean at >= 2 of 3 heights" in open(str(out) + ".txt").read()
    assert len(list((tmp_path / "ov").glob("*.png"))) == 3
    assert ssc.main([str(tmp_path / "nope"), str(tmp_path / "b"), "--zarr", str(zp),
                     "--heights", "30"]) == 2


def test_otsu_bimodal():
    img = np.r_[np.full(1000, 20.0), np.full(1000, 200.0)]
    assert 20 < ssc.otsu_threshold(img) < 200
