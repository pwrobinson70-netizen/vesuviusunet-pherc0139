"""Synthetic-data tests for tools/sheet_spacing_check (no real scan data)."""
import json

import numpy as np
import pytest
import tifffile

import sheet_spacing_check as ssc
from ssc_io import (ArrayVolume, InputError, PngVolume, ZarrVolume, build_mesh, load_mesh,
                    slice_index_for, to_px)

PITCH = 12.0
# Deliberately OFF-CENTRE and asymmetric (CX != CY, non-square image): a circle centred at
# (256, 256) is symmetric under x<->y, which hid axis-order bugs in the first version.
CX, CY = 200.0, 330.0
NZ, NY, NX = 100, 640, 512
R0 = 100.0           # a sheet centre; sheets sit at R0 + k*PITCH (+ SLOPE*z for the cone CT)


def make_ct(slope=0.0, pitch=PITCH):
    """Concentric sheets, pitch 12 px, dark gaps between. Sheet radius = R0 + k*PITCH + slope*z,
    so slope != 0 makes the CT vary along z (a cone)."""
    yy, xx = np.mgrid[0:NY, 0:NX]
    r = np.hypot(xx - CX, yy - CY)
    vol = np.empty((NZ, NY, NX), np.float32)
    for z in range(NZ):
        d = (r - slope * z - R0 + pitch / 2) % pitch - pitch / 2     # signed distance to nearest sheet
        vol[z] = 20 + 180 * np.exp(-d ** 2 / (2 * 1.5 ** 2))
    return vol


@pytest.fixture(scope="module")
def ct():
    return make_ct(0.0)


@pytest.fixture(scope="module")
def ct_cone():
    return make_ct(CONE_SLOPE)


CONE_SLOPE = 2.0     # steep: a 3-slice error moves the sheet 6 px = half a pitch


def cylinder(radius, n_cols=720, n_rows=NZ, name="m", swap_xy=False):
    th = np.linspace(0, 2 * np.pi, n_cols, endpoint=False)
    x = np.tile(CX + radius * np.cos(th), (n_rows, 1))
    y = np.tile(CY + radius * np.sin(th), (n_rows, 1))
    z = np.tile(np.arange(n_rows, dtype=float)[:, None], (1, n_cols))
    if swap_xy:
        x, y = y, x
    return build_mesh(name, x, y, z, {"scale": [0.5, 0.5], "voxelsize": 10.0})


def cone(radius0, slope=CONE_SLOPE, n_cols=720, n_rows=60, name="c"):
    """Surface r = radius0 + slope*z."""
    th = np.linspace(0, 2 * np.pi, n_cols, endpoint=False)
    zz = np.arange(n_rows, dtype=float)[:, None]
    r = radius0 + slope * zz
    return build_mesh(name, CX + r * np.cos(th), CY + r * np.sin(th),
                      np.tile(zz, (1, n_cols)), {"voxelsize": 10.0})


def run(a, b, ct, heights=(30.0, 50.0, 70.0), **kw):
    if len(heights) == 1:
        kw.setdefault("band_height_vox", 10.0)
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


# ===================================================== review-driven tests (PR #1 comment)
def test_swapped_xy_is_not_clean(ct):
    """Off-centre scroll: meshes with x<->y swapped sit off the sheets (mirror image)."""
    good = run(cylinder(R0), cylinder(R0 + PITCH), ct)
    bad = run(cylinder(R0, swap_xy=True), cylinder(R0 + PITCH, swap_xy=True), ct)
    for g, b in zip(good["heights"], bad["heights"]):
        assert g["clean_fraction"] > 0.98
        assert b["clean_fraction"] < 0.5


def test_cone_over_z_varying_ct_area_matches_analytic(ct_cone):
    """Sheets move with z; tilt factor and slice index both matter. Area = 2*pi*r*h*sqrt(1+s^2)."""
    heights = (15.0, 25.0, 35.0)
    a, b = cone(R0), cone(R0 + PITCH)
    res = run(a, b, ct_cone, heights=heights, band_height_vox=10.0)
    for h in res["heights"]:
        assert h["clean_fraction"] > 0.95
        assert h["ct_pitch_vox"] == pytest.approx(PITCH, rel=0.05)
    expected = sum(2 * np.pi * (R0 + CONE_SLOPE * z) * 10.0 * np.sqrt(1 + CONE_SLOPE ** 2)
                   for z in heights)
    assert res["area"]["clean_area_vox2"] == pytest.approx(expected, rel=0.02)
    assert res["area"]["sampled_area_vox2"] == pytest.approx(expected, rel=0.02)


def test_wrong_slice_is_not_clean(ct_cone):
    """A CT shifted by 3 slices (= 6 px of sheet motion) must break on-sheet."""
    shifted = np.roll(ct_cone, 3, axis=0)
    res = run(cone(R0), cone(R0 + PITCH), shifted, heights=(15.0, 25.0, 35.0), band_height_vox=10.0)
    assert all(h["clean_fraction"] < 0.5 for h in res["heights"])


def test_tilt_factor_kept_when_only_a_has_cut_points(ct_cone):
    """B1: A covers the height, B does not. Sampled area must still include 1/sqrt(1-nz^2)."""
    b = cone(R0 + PITCH)
    b.z[:] += 1000
    res = run(cone(R0), b, ct_cone, heights=(15.0,), band_height_vox=10.0)
    expected = 2 * np.pi * (R0 + CONE_SLOPE * 15) * 10.0 * np.sqrt(1 + CONE_SLOPE ** 2)
    assert res["area"]["sampled_area_vox2"] == pytest.approx(expected, rel=0.01)
    assert res["area"]["clean_area_vox2"] == 0.0


def test_half_resolution_ct_agrees_with_full(ct):
    half = ct[::2].reshape(NZ // 2, NY // 2, 2, NX // 2, 2).mean(axis=(2, 4)).astype(np.float32)
    a, b = cylinder(R0), cylinder(R0 + PITCH)
    full = run(a, b, ct)
    low = ssc.run_check(a, b, ArrayVolume(half, ct_scale=2), [30.0, 50.0, 70.0], ssc.Params(),
                        voxel_um=10.0)
    for f, h in zip(full["heights"], low["heights"]):
        assert h["clean_fraction"] > 0.95
        assert h["ct_pitch_vox"] == pytest.approx(f["ct_pitch_vox"], rel=0.1)
        assert h["median_ratio"] == pytest.approx(f["median_ratio"], abs=0.1)
    assert low["area"]["clean_area_vox2"] == pytest.approx(full["area"]["clean_area_vox2"], rel=0.05)


def _flags(a, b, ct, z0):
    la = ssc.cut_line(a, z0, ssc.Params())
    res, pts, _ = ssc.analyse_height(a, b, ArrayVolume(ct), z0, ssc.Params())
    return pts


def test_one_point_run_keeps_own_flag(ct):
    """The running median must not cross runs: an isolated clean point between off-sheet
    neighbours (separated by holes in A) keeps its own flag."""
    a, b = cylinder(R0), cylinder(R0 + PITCH)
    for c in range(10, 41):                         # A pushed 5 px into the dark gap ...
        th = 2 * np.pi * c / 720
        if c == 22:
            continue                                # ... except column 22, which stays on its sheet
        a.x[:, c], a.y[:, c] = CX + (R0 + 5) * np.cos(th), CY + (R0 + 5) * np.sin(th)
    for c in (21, 23):                              # holes isolate column 22 as a one-point run
        a.valid[:, c] = False
        for g in (a.x, a.y, a.z):
            g[:, c] = np.nan
    pts = _flags(a, b, ct, 30.0)
    cols, clean = pts["col"], pts["clean"]
    assert clean[cols == 22].all()
    assert not clean[(cols >= 12) & (cols <= 19)].any()
    assert not clean[(cols >= 25) & (cols <= 38)].any()
    assert clean[(cols >= 100) & (cols <= 200)].all()


def test_running_median_smooths_isolated_failure(ct):
    """One A point in the dark gap (raw not clean) inside a clean run is smoothed to clean."""
    a, b = cylinder(R0), cylinder(R0 + PITCH)
    th = 2 * np.pi * 100 / 720
    a.x[:, 100], a.y[:, 100] = CX + (R0 + 5) * np.cos(th), CY + (R0 + 5) * np.sin(th)
    pts = _flags(a, b, ct, 30.0)
    assert pts["clean"][pts["col"] == 100].all()
    raw = ssc.run_check(a, b, ArrayVolume(ct), [30.0], ssc.Params(median_window=1, band_height_vox=10.0),
                        voxel_um=10.0)["heights"][0]
    smooth = ssc.run_check(a, b, ArrayVolume(ct), [30.0], ssc.Params(band_height_vox=10.0),
                        voxel_um=10.0)["heights"][0]
    assert smooth["clean_fraction"] > raw["clean_fraction"]
    assert raw["clean_fraction"] == pytest.approx(719 / 720, abs=1e-6)


@pytest.mark.parametrize("ratio, expect", [(0.45, "shared"), (0.55, "clean"),
                                           (1.45, "clean"), (1.55, "skipped")])
def test_ratio_edges(ct, ratio, expect):
    # on-sheet radius made huge so only the ratio window decides
    res = run(cylinder(R0), cylinder(R0 + ratio * PITCH), ct, heights=(30.0,), onsheet_radius_px=12.0)
    h = res["heights"][0]
    if expect == "clean":
        assert h["clean_fraction"] > 0.98
    else:
        assert h["clean_fraction"] < 0.02
        assert h[expect + "_fraction"] > 0.98


def test_partial_invalid_sentinel_marks_cell_invalid():
    x = np.full((4, 4), 5.0); y = x.copy(); z = np.arange(16, dtype=float).reshape(4, 4)
    z[1, 2] = -1.0                                  # only z carries the sentinel
    x0 = x.copy()
    m = build_mesh("m", x, y, z)
    assert not m.valid[1, 2] and m.valid.sum() == 15 and m.n_invalid == 1
    assert np.array_equal(x, x0) and x[1, 2] == 5.0     # caller's arrays untouched (N2)
    assert z[1, 2] == -1.0


def test_invalid_cells_warning(ct):
    a, b = cylinder(R0), cylinder(R0 + PITCH)
    a.z[10, 10] = np.nan
    a2 = build_mesh("holey", a.x, a.y, np.where(np.isnan(a.z), -1.0, a.z))
    res = run(a2, b, ct, heights=(30.0,))
    assert any("holey" in w and "no valid data" in w for w in res["warnings"])


def test_transpose_swaps_meta_scale():
    g = np.arange(24, dtype=float).reshape(4, 6)
    m = build_mesh("t", g, g, g, {"scale": [0.1, 0.5]}, transpose=True)
    assert m.shape == (6, 4)
    assert m.scale == (0.5, 0.1)
    m2 = build_mesh("t", g, g, g, {"scale": [0.1, 0.5]}, transpose=False)
    assert m2.scale == (0.1, 0.5)


def test_b_hole_is_uncovered_not_skipped(ct):
    a, b = cylinder(R0), cylinder(R0 + PITCH)
    b.valid[:, 300:421] = False
    for g in (b.x, b.y, b.z):
        g[:, 300:421] = np.nan
    h = run(a, b, ct, heights=(30.0,))["heights"][0]
    assert h["uncovered_fraction"] == pytest.approx(111 / 720, abs=0.003)   # cols 305..415
    assert h["skipped_fraction"] == 0.0
    assert h["shared_fraction"] == 0.0
    assert h["clean_fraction"] == pytest.approx(1 - h["uncovered_fraction"], abs=0.03)
    assert h["clean_fraction"] < 1 - 100 / 720                                   # uncovered never clean


def test_nan_normals_next_to_hole_are_excluded_not_vertical():
    a = cone(R0)
    full = ssc.run_check(a, _far(cone(R0 + PITCH)), _NoCT(), [25.5], ssc.Params(band_height_vox=10.0))
    holed = cone(R0)
    for g in (holed.x, holed.y, holed.z):
        g[26, 100] = -1.0
    holed = build_mesh("h", holed.x, holed.y, holed.z, {})
    res = ssc.run_check(holed, _far(cone(R0 + PITCH)), _NoCT(), [25.5], ssc.Params(band_height_vox=10.0))
    ar, a0 = res["area"], full["area"]
    assert ar["excluded_nan_normal_points"] == 2            # columns 99 and 101; column 100 has no cut
    assert ar["sampled_area_vox2"] / a0["sampled_area_vox2"] == pytest.approx(717 / 720, abs=5e-4)
    assert any("undefined surface normal" in w for w in res["warnings"])


class _NoCT:
    ct_scale = 1.0

    def probe_shape(self, z):
        raise AssertionError("CT should not be read when B has no cut points")


def _far(m):
    m.z[:] += 1000
    return m


def test_slice_and_pixel_conventions():
    assert [slice_index_for(z, 2) for z in (0, 1, 2, 3, 4, 5, 6, 7)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert [slice_index_for(z, 1) for z in (0.0, 3.0, 49.0)] == [0, 3, 49]
    assert [slice_index_for(z, 4) for z in (3, 4, 7, 8)] == [0, 1, 1, 2]
    # pixel k at level L is centred on voxel k*sc + (sc-1)/2
    assert to_px(np.array([[0.5, 4.5]]), 2)[0] == pytest.approx([0.0, 2.0])
    assert to_px(np.array([[1.5]]), 4)[0] == pytest.approx([0.0])
    assert to_px(np.array([[7.0]]), 1)[0] == pytest.approx([7.0])


def test_pitch_comes_from_the_ct_not_a_constant():
    """Sheets 20 px apart: the CT pitch must be measured (20), and B one pitch away is clean."""
    ct20 = make_ct(0.0, pitch=20.0)
    res = run(cylinder(R0), cylinder(R0 + 20.0), ct20, heights=(30.0, 50.0, 70.0))
    for h in res["heights"]:
        assert h["ct_pitch_vox"] == pytest.approx(20.0, rel=0.05)
        assert h["clean_fraction"] > 0.98
        assert h["median_ratio"] == pytest.approx(1.0, abs=0.05)
