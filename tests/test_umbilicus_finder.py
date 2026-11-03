"""Synthetic-only tests for tools/umbilicus_finder (no real scan data)."""
import json
import os
import sys

import numpy as np
import pytest

_TOOL = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "umbilicus_finder"))
if _TOOL not in sys.path:
    sys.path.insert(0, _TOOL)

import dataclasses  # noqa: E402

import uf_io  # noqa: E402
import umbilicus_finder as uf  # noqa: E402
from uf_io import ArrayVolume, InputError  # noqa: E402

SHAPE = (400, 480)         # (ny, nx), deliberately not square
CENTRE = (250.0, 190.0)    # (x, y), deliberately off-centre and x != y
PITCH = 12.0
P = uf.Params()


def spiral(shape=SHAPE, c=CENTRE, pitch=PITCH, rout=150.0, rin=8.0, squash=1.0, noise=0.05, seed=0):
    """Archimedean spiral of sheets (50 % duty, smooth edges) around c=(x, y). squash>1 makes an
    ellipse of axis ratio 1:squash (y compressed), simulating a crushed scroll."""
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx].astype(float)
    dx, dy = xx - c[0], (yy - c[1]) * squash
    r, th = np.hypot(dx, dy), np.arctan2(dy, dx)
    u = np.mod((r - pitch * th / (2 * np.pi)) / pitch, 1.0)
    img = np.where((r < rout) & (r > rin), 0.5 + 0.5 * np.cos(2 * np.pi * u), 0.0)
    return (img + noise * np.random.default_rng(seed).standard_normal(shape)).astype(np.float32)


def analyse(img, pitch=PITCH, params=P, scale=1.0):
    r = uf.analyse_slice(img, params, scale)
    return uf.finalize(r, pitch, params)


# ------------------------------------------------------------------ single slice
def test_round_spiral_centre_within_2px_and_confident():
    r = analyse(spiral())
    assert r.ok and r.flag == "OK"
    assert abs(r.cx - CENTRE[0]) < 2 and abs(r.cy - CENTRE[1]) < 2
    assert r.coverage_deg >= 300 and r.confidence > 0.8
    # an ideal Archimedean spiral leaves ~1/(2 pi) pitch of perpendicular residual
    assert 0.05 < r.residual_pitch < 0.4


def test_other_pitch_and_pitch_is_estimated_from_data():
    img = spiral(pitch=20.0)
    r = uf.analyse_slice(img, P)
    assert abs(r.cx - CENTRE[0]) < 2 and abs(r.cy - CENTRE[1]) < 2
    assert r.pitch_vox == pytest.approx(20.0, rel=0.1)


def test_downsampled_slice_keeps_level0_coordinates():
    # 2x larger image -> default target_px=1000 forces downsample factor 2 on a 1920-wide slice
    c = (500.0, 380.0)
    img = spiral(shape=(800, 1920), c=c, pitch=24.0, rout=300.0, rin=16.0)
    r = uf.analyse_slice(img, P)
    assert uf.downsample(img, P.target_px)[1] == 2
    assert abs(r.cx - c[0]) < 2 and abs(r.cy - c[1]) < 2


def test_huber_also_finds_centre():
    r = analyse(spiral(), params=uf.Params(robust="huber"))
    assert abs(r.cx - CENTRE[0]) < 2 and abs(r.cy - CENTRE[1]) < 2


def test_crushed_ellipse_returns_centre_with_lower_confidence():
    round_ = analyse(spiral())
    ell = analyse(spiral(squash=2.0))  # same known pitch for a like-for-like comparison
    assert ell.ok and np.isfinite(ell.cx) and np.isfinite(ell.cy)
    assert abs(ell.cx - CENTRE[0]) < 8 and abs(ell.cy - CENTRE[1]) < 8
    assert ell.confidence < round_.confidence
    assert ell.residual_pitch > 3 * round_.residual_pitch
    assert ell.flag == "LOW" and "high_residual" in ell.reasons


def test_bright_blob_and_case_ring_are_ignored_by_mask():
    img = spiral()
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]].astype(float)
    blob = np.hypot(xx - 70, yy - 330) < 25
    ring = np.abs(np.hypot(xx - CENTRE[0], yy - CENTRE[1]) - 172) < 2
    img[blob] = 2.0
    img[ring] = 1.5
    m = uf.scroll_mask(img, P)
    assert m is not None
    assert not m[330, 70] and not m[blob].any()
    assert not m[ring].any()
    assert m[int(CENTRE[1]) + 60, int(CENTRE[0])]  # scroll body kept
    r = analyse(img)
    assert abs(r.cx - CENTRE[0]) < 2 and abs(r.cy - CENTRE[1]) < 2 and r.flag == "OK"


@pytest.mark.parametrize("make", [
    lambda: np.zeros((400, 480), np.float32),
    lambda: np.full((400, 480), 7.0, np.float32),
    lambda: np.random.default_rng(1).standard_normal((400, 480)).astype(np.float32),
    lambda: np.full((400, 480), np.nan, np.float32),
    lambda: np.zeros((6, 6), np.float32),
    lambda: np.zeros((0, 5), np.float32),
])
def test_empty_or_noise_slice_is_low_and_does_not_crash(make):
    r = analyse(make())
    assert r.flag == "LOW"
    assert r.reasons
    assert r.confidence < 0.3


def test_unknown_pitch_is_low_not_a_crash():
    r = uf.finalize(uf.analyse_slice(spiral(), P), np.nan, P)
    assert r.flag == "LOW" and "no_pitch" in r.reasons


def test_partial_wedge_has_low_coverage():
    img = spiral()
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]].astype(float)
    ang = np.degrees(np.arctan2(yy - CENTRE[1], xx - CENTRE[0]))
    img[(ang > -100) & (ang < 100)] = 0.0  # only a 160-degree wedge of scroll left
    r = analyse(img)
    assert r.coverage_deg < 180
    assert r.flag == "LOW" and "low_coverage" in r.reasons


def test_solve_centre_exact_on_noise_free_lines():
    c = np.array([3.0, -2.0])
    ang = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    n = np.stack([np.cos(ang), np.sin(ang)], 1)
    p = c + n * np.linspace(5, 50, 40)[:, None]
    got = uf.solve_centre(p[:, 0], p[:, 1], n[:, 0], n[:, 1], np.ones(40))
    assert np.allclose(got, c)
    # all-parallel normals: centre undetermined -> None
    assert uf.solve_centre(p[:, 0], p[:, 1], np.ones(40), np.zeros(40), np.ones(40)) is None


def test_coverage_deg():
    az = np.linspace(0, np.pi, 2000)
    assert 160 <= uf.coverage_deg(az, P) <= 200
    assert uf.coverage_deg(np.linspace(0, 2 * np.pi, 3000), P) == 360


# ------------------------------------------------------------------ along z
def drift_volume(nz=9, dx=3.0, dy=-2.0, start=(150.0, 220.0)):
    vol = np.stack([spiral(c=(start[0] + dx * z, start[1] + dy * z), seed=z) for z in range(nz)])
    truth = [(start[0] + dx * z, start[1] + dy * z) for z in range(nz)]
    return vol, truth


def test_linear_drift_is_recovered():
    vol, truth = drift_volume()
    rows, summ = uf.run(ArrayVolume(vol), P, z_step=1)
    assert [r["flag"] for r in rows] == ["OK"] * 9
    z = np.array([r["z"] for r in rows])
    x = np.array([r["x"] for r in rows])
    y = np.array([r["y"] for r in rows])
    for i in range(9):
        assert abs(x[i] - truth[i][0]) < 2 and abs(y[i] - truth[i][1]) < 2
    assert np.polyfit(z, x, 1)[0] == pytest.approx(3.0, rel=0.05)
    assert np.polyfit(z, y, 1)[0] == pytest.approx(-2.0, rel=0.05)
    assert summ["pitch_vox"] == pytest.approx(PITCH, rel=0.1)
    assert summ["departure_vox"]["ranges"] == []


def test_bad_slice_is_downweighted_and_departure_reported():
    vol, truth = drift_volume()
    vol[4] = np.random.default_rng(5).standard_normal(SHAPE)  # one noise slice in the middle
    rows, summ = uf.run(ArrayVolume(vol), P, z_step=1)
    assert rows[4]["flag"] == "LOW"
    assert all(rows[i]["flag"] == "OK" for i in range(9) if i != 4)
    # smoothed line follows the drift through the bad slice, the raw estimate does not
    assert abs(rows[4]["x"] - truth[4][0]) < 3 and abs(rows[4]["y"] - truth[4][1]) < 3
    assert rows[4]["departure_vox"] > P.departure_vox  # raw noise-slice estimate is far off the line
    assert any(r["z_first"] <= rows[4]["z"] <= r["z_last"] for r in summ["departure_vox"]["ranges"])
    low = summ["low_confidence_ranges"]
    assert len(low) == 1 and low[0]["z_first"] == low[0]["z_last"] == rows[4]["z"]


def test_all_noise_volume_has_no_crash_and_all_low():
    vol = np.random.default_rng(2).standard_normal((4, 200, 200)).astype(np.float32)
    rows, summ = uf.run(ArrayVolume(vol), P, z_step=1)
    assert summ["n_low"] == 4 and summ["n_ok"] == 0
    assert all(r["flag"] == "LOW" for r in rows)


def test_empty_volume_gives_nan_line_and_cli_exit_3(tmp_path):
    import zarr
    path = tmp_path / "empty.zarr"
    zarr.open(str(path), mode="w", shape=(3, 64, 64), chunks=(1, 64, 64), dtype="f4")
    rows, summ = uf.run(ArrayVolume(np.zeros((3, 64, 64), np.float32)), P, z_step=1)
    assert all(not np.isfinite(r["y"]) for r in rows) and summ["n_ok"] == 0
    assert uf.main([str(path), "--out-dir", str(tmp_path / "o"), "--z-step", "1"]) == 3


def test_weighted_running_median_ignores_nan_and_low_weight():
    v = np.array([0, 0, 100, 0, 0, np.nan, 0.0])
    w = np.array([1, 1, 0.01, 1, 1, 1, 1.0])
    out = uf.weighted_running_median(v, w, 5)
    assert np.nanmax(np.abs(out)) == 0


def test_smooth_line_single_and_two_points():
    z = np.array([0.0, 10.0, 20.0])
    y = np.array([np.nan, 5.0, np.nan])
    sy, sx = uf.smooth_line(z, y, y, np.ones(3), P)
    assert np.allclose(sy, 5.0)
    y2 = np.array([0.0, 10.0, np.nan])
    sy, _ = uf.smooth_line(z, y2, y2, np.ones(3), P)
    assert np.isfinite(sy).all()


def test_level_scale_convention():
    # a level-1 volume (scale 2): centre must be reported at (c + 0.5) * 2 - 0.5 in level-0 voxels
    c1 = (125.0, 95.0)
    lvl = np.stack([spiral(shape=(200, 240), c=c1, pitch=10.0, rout=75.0, rin=4.0, seed=s) for s in range(3)])
    rows, summ = uf.run(ArrayVolume(lvl, scale_z=2.0, scale_xy=2.0), P, z_step=2)
    want = (uf.uf_io.centre_to_level0(c1[0], 2.0), uf.uf_io.centre_to_level0(c1[1], 2.0))
    assert [r["z"] for r in rows] == [0.5, 2.5, 4.5]
    for r in rows:
        assert abs(r["x"] - want[0]) < 4 and abs(r["y"] - want[1]) < 4  # 2 level pixels


# ------------------------------------------------------------------ inputs / errors
def test_every_param_is_a_cli_flag():
    ap = uf.build_parser()
    dests = {a.dest for a in ap._actions}
    assert {f.name for f in dataclasses.fields(uf.Params)} <= dests
    a = ap.parse_args(["in", "--out-dir", "o", "--tukey-c", "3.5", "--sigma-int", "5", "--robust", "huber"])
    assert a.tukey_c == 3.5 and a.sigma_int == 5.0 and a.robust == "huber"


def test_z_range_errors():
    v = ArrayVolume(np.zeros((5, 16, 16), np.float32), scale_z=2.0)  # level-0 z extent [0, 10)
    with pytest.raises(InputError, match="outside the volume"):
        uf.plan_slices(v, 0, 11, 2)
    with pytest.raises(InputError, match="outside the volume"):
        uf.plan_slices(v, -2, 6, 2)
    with pytest.raises(InputError, match="empty"):
        uf.plan_slices(v, 6, 6, 2)
    with pytest.raises(InputError, match="step"):
        uf.plan_slices(v, 0, 6, 0)
    assert uf.plan_slices(v, 0, 10, 2) == [0, 1, 2, 3, 4]
    assert uf.plan_slices(v, 0, 10, 0.5) == [0, 1, 2, 3, 4]  # step finer than the level: unique slices


def test_bad_paths_and_shapes(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        uf_io.open_volume(tmp_path / "nope.zarr")
    with pytest.raises(InputError, match="does not exist"):
        uf_io.PngVolume(tmp_path / "nope")
    (tmp_path / "emptydir").mkdir()
    with pytest.raises(InputError, match="no files"):
        uf_io.PngVolume(tmp_path / "emptydir")
    junk = tmp_path / "junk.zarr"
    junk.mkdir()
    with pytest.raises(InputError):
        uf_io.ZarrVolume(junk)
    with pytest.raises(InputError, match="3-D"):
        ArrayVolume(np.zeros((4, 4)))
    with pytest.raises(InputError):
        ArrayVolume(np.zeros((2, 4, 4)), scale_xy=0)
    with pytest.raises(InputError, match="outside"):
        ArrayVolume(np.zeros((2, 4, 4))).read_slice(2)
    import zarr
    flat = tmp_path / "flat.zarr"
    zarr.open(str(flat), mode="w", shape=(8, 8), dtype="f4")
    with pytest.raises(InputError, match="3-D"):
        uf_io.ZarrVolume(flat)


def test_cli_errors_exit_2(tmp_path, capsys):
    assert uf.main([str(tmp_path / "missing"), "--out-dir", str(tmp_path / "o")]) == 2
    assert "error:" in capsys.readouterr().err
    import zarr
    path = tmp_path / "v.zarr"
    zarr.open(str(path), mode="w", shape=(4, 32, 32), dtype="f4")
    assert uf.main([str(path), "--out-dir", str(tmp_path / "o"), "--z-stop", "99"]) == 2
    assert "outside the volume" in capsys.readouterr().err
    # an all-zero volume has no scroll: exit 3, and the summary must still be valid JSON (pitch unknown -> null)
    assert uf.main([str(path), "--out-dir", str(tmp_path / "o"), "--z-step", "1"]) == 3
    assert json.loads((tmp_path / "o" / "umbilicus_summary.json").read_text())["pitch_vox"] is None


# ------------------------------------------------------------------ end-to-end CLI
def _write_ome_zarr(path, level1):
    """OME-Zarr group: level 0 (zeros, 2x size, never read) and level 1 = the given volume."""
    import zarr
    nz, ny, nx = level1.shape
    g = zarr.open_group(str(path), mode="w")
    zarr.open(str(path / "0"), mode="w", shape=(2 * nz, 2 * ny, 2 * nx), chunks=(1, 64, 64), dtype="f4")
    a1 = zarr.open(str(path / "1"), mode="w", shape=level1.shape, chunks=(1, 100, 120), dtype="f4")
    a1[:] = level1
    g.attrs["multiscales"] = [{"version": "0.4", "axes": [{"name": n} for n in "zyx"], "datasets": [
        {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0, 1.0]}]},
        {"path": "1", "coordinateTransformations": [{"type": "scale", "scale": [2.0, 2.0, 2.0]}]}]}]


def test_cli_ome_zarr_level1_end_to_end(tmp_path):
    c1 = (125.0, 95.0)
    lvl = np.stack([spiral(shape=(200, 240), c=c1, pitch=10.0, rout=75.0, rin=4.0, seed=s) for s in range(4)])
    zpath, out = tmp_path / "scroll.zarr", tmp_path / "out"
    _write_ome_zarr(zpath, lvl)
    vol = uf_io.ZarrVolume(zpath, level=1)
    assert (vol.scale_z, vol.scale_xy, vol.shape) == (2.0, 2.0, (4, 200, 240))
    rc = uf.main([str(zpath), "--level", "1", "--out-dir", str(out), "--z-step", "2", "--overlays"])
    assert rc == 0
    lines = (out / "umbilicus.csv").read_text().splitlines()
    assert lines[0].split(",")[:5] == ["z", "y", "x", "confidence", "flag"]
    assert len(lines) == 1 + 4
    first = dict(zip(lines[0].split(","), lines[1].split(",")))
    assert abs(float(first["x"]) - (c1[0] + 0.5) * 2 + 0.5) < 4 and abs(float(first["y"]) - (c1[1] + 0.5) * 2 + 0.5) < 4
    assert first["flag"] == "OK"
    summ = json.loads((out / "umbilicus_summary.json").read_text())
    assert summ["n_slices"] == 4 and summ["scale_xy"] == 2.0 and summ["units"].startswith("level-0")
    assert summ["params"]["tukey_c"] == 4.685
    villa = json.loads((out / "umbilicus_villa.json").read_text())
    assert list(villa) == ["control_points"] and len(villa["control_points"]) == 4
    assert set(villa["control_points"][0]) == {"z", "y", "x"}
    zs = [p["z"] for p in villa["control_points"]]
    assert zs == sorted(zs)
    pngs = sorted((out / "overlays").glob("*.png"))
    assert len(pngs) == 4
    from PIL import Image
    assert Image.open(pngs[0]).size == (240, 200)


def test_cli_png_stack_with_pixel_size_and_export_all(tmp_path):
    from PIL import Image
    d = tmp_path / "png"
    d.mkdir()
    for z in range(3):
        g = np.clip(spiral(seed=z) * 120 + 20, 0, 255).astype(np.uint8)
        Image.fromarray(g).save(d / f"{z:05d}.png")
    bad = np.random.default_rng(3).standard_normal(SHAPE)
    Image.fromarray(np.clip(bad * 40 + 128, 0, 255).astype(np.uint8)).save(d / "00003.png")
    out = tmp_path / "out"
    rc = uf.main([str(d), "--out-dir", str(out), "--pixel-um", "15.82", "--voxel-um", "7.91", "--z-scale", "2",
                  "--z-step", "2", "--export-all"])
    assert rc == 0
    summ = json.loads((out / "umbilicus_summary.json").read_text())
    assert summ["scale_xy"] == pytest.approx(2.0) and summ["scale_z"] == 2.0 and summ["n_slices"] == 4
    assert summ["n_low"] >= 1
    rows = (out / "umbilicus.csv").read_text().splitlines()
    first = dict(zip(rows[0].split(","), rows[1].split(",")))
    assert abs(float(first["x"]) - ((CENTRE[0] + 0.5) * 2 - 0.5)) < 4
    assert len(json.loads((out / "umbilicus_villa.json").read_text())["control_points"]) == 4
    # default export keeps OK points only
    out2 = tmp_path / "out2"
    uf.main([str(d), "--out-dir", str(out2), "--xy-scale", "2", "--z-scale", "2", "--z-step", "2"])
    n_ok = json.loads((out2 / "umbilicus_summary.json").read_text())["n_ok"]
    assert len(json.loads((out2 / "umbilicus_villa.json").read_text())["control_points"]) == n_ok


def test_three_class_otsu_option_also_finds_centre():
    r = analyse(spiral(), params=uf.Params(otsu_classes=3))
    assert abs(r.cx - CENTRE[0]) < 2 and abs(r.cy - CENTRE[1]) < 2 and r.flag == "OK"
