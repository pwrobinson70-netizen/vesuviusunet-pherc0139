"""Synthetic-data tests for tools/sheet_switch_finder (no real scan data)."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
for _p in (_TOOLS / "sheet_switch_finder", _TOOLS / "sheet_spacing_check"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import sheet_switch_finder as ssf  # noqa: E402
from ssc_io import ArrayVolume, InputError, build_mesh  # noqa: E402

PITCH = 12.0
CX, CY = 210.0, 235.0           # off-centre, non-square image
NZ, NY, NX = 40, 470, 420
R0 = 100.0                      # a sheet centre; sheets sit at R0 + k*PITCH
NC = 720
HEIGHTS = (10.0, 20.0, 30.0)


@pytest.fixture(scope="module")
def ct():
    """Concentric sheets (pitch 12 px, sigma 1.5 px), dark gaps between; constant along z."""
    yy, xx = np.mgrid[0:NY, 0:NX]
    d = (np.hypot(xx - CX, yy - CY) - R0 + PITCH / 2) % PITCH - PITCH / 2
    sl = (20 + 180 * np.exp(-d ** 2 / (2 * 1.5 ** 2))).astype(np.float32)
    return ArrayVolume(np.broadcast_to(sl, (NZ, NY, NX)).copy())


def mesh_from_radius(r, name="m", n_rows=NZ):
    """Cylinder-like mesh; r is the radius per column (scalar, (NC,) or (n_rows, NC))."""
    th = np.linspace(0, 2 * np.pi, NC, endpoint=False)
    r = np.broadcast_to(np.asarray(r, float), (n_rows, NC))
    x, y = CX + r * np.cos(th), CY + r * np.sin(th)
    z = np.tile(np.arange(n_rows, dtype=float)[:, None], (1, NC))
    return build_mesh(name, x, y, z, {"voxelsize": 10.0})


def ramp(at, n_cols, size, width):
    """Radius offset (pixels) that rises by `size` over `width` columns starting at column `at`;
    stays up for `n_cols` columns (None = to the end)."""
    c = np.arange(NC, dtype=float)
    up = np.clip((c - at) / max(width, 1e-9), 0, 1) if width else (c >= at).astype(float)
    if n_cols is None:
        return size * up
    end = at + n_cols
    down = np.clip((c - end) / max(width, 1e-9), 0, 1) if width else (c >= end).astype(float)
    return size * (up - down)


def find(mesh, ct, heights=HEIGHTS, **kw):
    kw.setdefault("vertical", 0)
    return ssf.run_finder(mesh, ct, list(heights), ssf.Params(**kw))


def hs(res, kind="horizontal"):
    return [s for s in res["switches"] if s["kind"] == kind]


# ---------------------------------------------------------------- clean meshes
def test_one_sheet_no_switches(ct):
    res = find(mesh_from_radius(R0 + PITCH), ct)
    assert res["switches"] == []
    for h in res["heights"]:
        assert h["ct_pitch_vox"] == pytest.approx(PITCH, rel=0.05)
        assert h["fraction_tracked"] > 0.95
        assert h["fraction_off_sheet"] < 0.05
    assert res["summary"]["n_switches"] == 0


def test_offset_is_zero_on_sheet_and_signed(ct):
    """Mesh 0.2 pitch outside the sheet it follows: offset +0.2 (mesh - sheet, outward positive)."""
    sp = ssf.Params()
    _, _, st = ssf.analyse_height(mesh_from_radius(R0 + PITCH + 0.2 * PITCH), ct, 20.0, sp)
    off = st["offset"][st["usable"]]
    assert len(off) > 600
    assert np.median(off) == pytest.approx(0.2, abs=0.05)
    _, _, st = ssf.analyse_height(mesh_from_radius(R0 + PITCH - 0.2 * PITCH), ct, 20.0, sp)
    assert np.median(st["offset"][st["usable"]]) == pytest.approx(-0.2, abs=0.05)


# -------------------------------------------------------------------- hops
@pytest.mark.parametrize("width", [0, 5])
def test_hop_outward_one_switch_at_index(ct, width):
    at = 300
    res = find(mesh_from_radius(R0 + PITCH + ramp(at, None, PITCH, width)), ct)
    for h in HEIGHTS:
        sw = [s for s in hs(res) if s["height"] == h]
        assert len(sw) == 1, sw
        s = sw[0]
        assert abs(s["line_index"] - (at + width // 2)) <= 2
        assert abs(s["col"] - (at + width // 2)) <= 2
        assert s["direction"] == "outward"
        assert s["step"] == pytest.approx(1.0, abs=0.2)
        assert s["n_sheets"] == 1 and not s["double_switch"]
        assert s["confidence"] > 0.5
        assert s["z"] == h
        assert 0 <= s["row"] <= NZ - 1 and abs(s["row"] - h) < 1
        # reported voxel position is on the mesh near the hop
        assert np.hypot(s["x"] - CX, s["y"] - CY) == pytest.approx(R0 + PITCH + (PITCH if width == 0 else PITCH / 2), abs=PITCH)


def test_hop_inward_one_switch(ct):
    res = find(mesh_from_radius(R0 + 2 * PITCH + ramp(400, None, -PITCH, 4)), ct)
    sw = [s for s in hs(res) if s["height"] == 20.0]
    assert len(sw) == 1
    assert sw[0]["direction"] == "inward" and sw[0]["step"] == pytest.approx(-1.0, abs=0.2)
    assert abs(sw[0]["col"] - 402) <= 2


def test_hop_inward_then_back_two_switches(ct):
    res = find(mesh_from_radius(R0 + 2 * PITCH + ramp(200, 250, -PITCH, 4)), ct)
    for h in HEIGHTS:
        sw = sorted([s for s in hs(res) if s["height"] == h], key=lambda s: s["col"])
        assert [s["direction"] for s in sw] == ["inward", "outward"]
        assert abs(sw[0]["col"] - 202) <= 2 and abs(sw[1]["col"] - 452) <= 2
        assert all(not s["double_switch"] for s in sw)


def test_hard_hop_one_switch(ct):
    """A jump between neighbouring columns (normals next to it are garbage) is still found."""
    res = find(mesh_from_radius(R0 + PITCH + ramp(300, None, PITCH, 0)), ct, heights=[20.0])
    sw = hs(res)
    assert len(sw) == 1 and sw[0]["direction"] == "outward" and abs(sw[0]["col"] - 300) <= 2


def test_hop_of_two_sheets_is_double(ct):
    res = find(mesh_from_radius(R0 + PITCH + ramp(300, None, 2 * PITCH, 6)), ct)
    for h in HEIGHTS:
        sw = [s for s in hs(res) if s["height"] == h]
        assert len(sw) == 1, sw
        s = sw[0]
        assert abs(s["col"] - 303) <= 2
        assert s["step"] == pytest.approx(2.0, abs=0.3)
        assert s["double_switch"] and s["n_sheets"] == 2
        assert s["direction"] == "outward"
    assert res["summary"]["n_double"] == 3


def test_hop_shorter_than_k_is_not_a_switch(ct):
    """A 3-point excursion does not stay for K=5 points on both sides."""
    res = find(mesh_from_radius(R0 + PITCH + ramp(300, 3, PITCH, 0)), ct, heights=[20.0])
    assert hs(res) == []
    # ... but is a pair of switches once K is lowered
    res = find(mesh_from_radius(R0 + PITCH + ramp(300, 8, PITCH, 0)), ct, heights=[20.0], k_points=3)
    assert len(hs(res)) == 2


def test_orientation_grid_flips_direction(ct):
    mesh = mesh_from_radius(R0 + PITCH + ramp(300, None, PITCH, 4))
    a = hs(find(mesh, ct, heights=[20.0], orientation="radial"))[0]
    b = hs(find(mesh, ct, heights=[20.0], orientation="grid"))[0]
    assert {a["direction"], b["direction"]} == {"outward", "inward"}      # grid normal here points inward
    c = hs(find(mesh, ct, heights=[20.0], centre_x=CX, centre_y=CY))[0]
    assert c["direction"] == "outward"


# ------------------------------------------------------------ noise, gaps
def test_wobble_below_040_pitch_no_switches(ct):
    rng = np.random.default_rng(1)
    th = np.linspace(0, 2 * np.pi, NC, endpoint=False)
    for wob in (0.2 * PITCH * np.sin(th * 7),                       # smooth, peak-to-peak 0.4
                rng.uniform(-0.2, 0.2, NC) * PITCH,                  # white, peak-to-peak 0.4
                rng.normal(0, 0.08, NC) * PITCH):
        res = find(mesh_from_radius(R0 + PITCH + wob), ct)
        assert res["switches"] == [], res["switches"]
        assert res["summary"]["fraction_tracked"] > 0.7      # white noise tilts (drops) some normals


def test_dark_gap_is_off_sheet_not_switch(ct):
    res = find(mesh_from_radius(R0 + PITCH / 2), ct)                  # mesh runs in the gap between sheets
    assert res["switches"] == []
    for h in res["heights"]:
        assert h["fraction_off_sheet"] > 0.95
        assert h["fraction_tracked"] < 0.05


def test_dark_gap_patch_is_off_sheet_not_switch(ct):
    """Mesh dips into the gap for 100 columns, then returns to the same sheet."""
    res = find(mesh_from_radius(R0 + PITCH + ramp(300, 100, PITCH / 2, 3)), ct)
    assert res["switches"] == []
    h = res["heights"][1]
    assert 0.08 < h["fraction_off_sheet"] < 0.3


def test_long_gap_resets_tracking(ct):
    """After more than max_offsheet_bridge off-sheet points the track restarts at the nearest peak,
    so a hop hidden inside a long gap is invisible (documented limit)."""
    mesh = mesh_from_radius(R0 + PITCH * np.where(np.arange(NC) < 300, 1, 2)
                            + np.where((np.arange(NC) >= 280) & (np.arange(NC) < 320), -PITCH / 2, 0.0))
    # 40-column off-sheet stretch holding the hop of 1 sheet: both sides sit on a sheet, offsets reset to 0
    res = find(mesh, ct, heights=[20.0])
    assert hs(res) == []
    # a long bridge allowance finds it again
    res = find(mesh, ct, heights=[20.0], max_offsheet_bridge=100)
    assert len(hs(res)) == 1


# ----------------------------------------------------------------- vertical
def test_vertical_switch_between_heights(ct):
    """Columns 250-400 are on the next sheet outward from z=20 up; the vertical test sees the step
    between z=10 and z=20 (and not between 20 and 30)."""
    c = np.arange(NC)
    patch = np.where((c >= 250) & (c < 400), PITCH, 0.0)[None, :] * (np.arange(NZ)[:, None] >= 15)
    mesh = mesh_from_radius(R0 + PITCH + patch)
    res = ssf.run_finder(mesh, ct, list(HEIGHTS), ssf.Params(vertical=1))
    v = hs(res, "vertical")
    assert len(v) == 1, v
    v = v[0]
    assert (v["height_from"], v["height_to"]) == (10.0, 20.0)
    assert v["direction"] == "outward" and v["step"] == pytest.approx(1.0, abs=0.2)
    assert 250 <= v["col_start"] and v["col_end"] <= 400 and v["n_columns"] >= 140
    assert 250 <= v["col"] < 400
    # the horizontal test finds the two edges of the patch at z=20 and z=30, none at z=10
    h = hs(res)
    assert sorted((s["height"] for s in h)) == [20.0, 20.0, 30.0, 30.0]
    assert [s["direction"] for s in sorted([s for s in h if s["height"] == 20.0], key=lambda s: s["col"])] \
        == ["outward", "inward"]
    assert res["heights"][1]["n_vertical_switches"] == 1


def test_vertical_off_switch(ct):
    c = np.arange(NC)
    patch = np.where((c >= 250) & (c < 400), PITCH, 0.0)[None, :] * (np.arange(NZ)[:, None] >= 15)
    res = ssf.run_finder(mesh_from_radius(R0 + PITCH + patch), ct, list(HEIGHTS), ssf.Params(vertical=0))
    assert hs(res, "vertical") == []


def test_no_vertical_switch_on_clean_mesh(ct):
    res = ssf.run_finder(mesh_from_radius(R0 + PITCH), ct, list(HEIGHTS), ssf.Params())
    assert res["switches"] == []


# ------------------------------------------------------------- bad inputs
def test_height_outside_mesh_z_range(ct):
    res = find(mesh_from_radius(R0 + PITCH, n_rows=30), ct, heights=[20.0, 35.0])
    assert res["heights"][1]["n_points"] == 0 and "outside the z range" in res["heights"][1]["note"]
    assert any("z=35" in w for w in res["warnings"])
    assert res["heights"][0]["n_points"] > 0
    only = find(mesh_from_radius(R0 + PITCH, n_rows=30), ct, heights=[35.0])
    assert only["switches"] == [] and only["summary"]["n_points"] == 0
    assert only["summary"]["fraction_tracked"] is None


def test_height_outside_ct_volume_is_input_error(ct):
    with pytest.raises(InputError, match="outside the volume"):
        find(mesh_from_radius(R0 + PITCH, n_rows=80), ct, heights=[60.0])


def test_mismatched_grid_shapes():
    with pytest.raises(InputError, match="same shape"):
        build_mesh("bad", np.zeros((5, 6)), np.zeros((5, 6)), np.zeros((5, 7)))


def test_bad_parameters(ct):
    mesh = mesh_from_radius(R0 + PITCH)
    for kw in (dict(median_window=4), dict(k_points=0), dict(step_min=1.5), dict(orientation="up"),
               dict(centre_x=1.0), dict(pitch_vox=-1.0), dict(sample_pitches=0.0)):
        with pytest.raises(InputError):
            ssf.run_finder(mesh, ct, [20.0], ssf.Params(**kw))
    with pytest.raises(InputError):
        ssf.run_finder(mesh, ct, [], ssf.Params())
    with pytest.raises(InputError):
        ssf.run_finder(mesh, ct, [float("nan")], ssf.Params())


def _write_mesh(d, mesh):
    d.mkdir()
    for ax, a in zip("xyz", (mesh.x, mesh.y, mesh.z)):
        a = np.where(np.isfinite(a), a, -1.0).astype(np.float32)
        tifffile.imwrite(str(d / f"{ax}.tif"), a)
    (d / "meta.json").write_text(json.dumps({"voxelsize": 10.0}))


@pytest.fixture
def zarr_path(tmp_path, ct):
    import zarr
    path = tmp_path / "vol.zarr"
    root = zarr.open_group(str(path), mode="w")
    arr = root.create_array("0", shape=ct.data.shape, dtype="float32") if hasattr(root, "create_array") \
        else root.create_dataset("0", shape=ct.data.shape, dtype="float32")
    arr[:] = ct.data
    return path


def test_cli_bad_paths(tmp_path, capsys, zarr_path):
    assert ssf.main([str(tmp_path / "nope"), "--zarr", str(zarr_path), "--heights", "20"]) == 2
    assert "not a directory" in capsys.readouterr().err
    m = tmp_path / "m"
    _write_mesh(m, mesh_from_radius(R0 + PITCH))
    assert ssf.main([str(m), "--zarr", str(tmp_path / "missing.zarr"), "--heights", "20"]) == 2
    assert "does not exist" in capsys.readouterr().err
    assert ssf.main([str(m), "--zarr", str(zarr_path), "--heights", "abc"]) == 2
    assert ssf.main([str(m), "--zarr", str(zarr_path), "--heights", "20", "--median-window", "4"]) == 2
    (m / "y.tif").unlink()
    assert ssf.main([str(m), "--zarr", str(zarr_path), "--heights", "20"]) == 2
    assert "missing y.tif" in capsys.readouterr().err


def test_cli_mismatched_grid_shapes_on_disk(tmp_path, capsys, zarr_path):
    m = tmp_path / "m"
    _write_mesh(m, mesh_from_radius(R0 + PITCH))
    tifffile.imwrite(str(m / "z.tif"), np.zeros((10, 10), np.float32))
    assert ssf.main([str(m), "--zarr", str(zarr_path), "--heights", "20"]) == 2
    assert "same shape" in capsys.readouterr().err


def test_cli_end_to_end(tmp_path, capsys, zarr_path):
    m = tmp_path / "m"
    _write_mesh(m, mesh_from_radius(R0 + PITCH + ramp(300, None, PITCH, 4)))
    out_json, out_txt, ov = tmp_path / "r.json", tmp_path / "r.txt", tmp_path / "ov"
    rc = ssf.main([str(m), "--zarr", str(zarr_path), "--heights", "20,30", "--out-json", str(out_json),
                   "--out-txt", str(out_txt), "--overlay-dir", str(ov)])
    assert rc == 0
    rep = json.loads(out_json.read_text())
    assert rep["result"]["summary"]["n_switches"] == 2
    sw = rep["result"]["switches"][0]
    for k in ("height", "row", "col", "x", "y", "z", "direction", "step", "confidence", "double_switch"):
        assert k in sw
    assert rep["params"]["step_min"] == 0.6 and rep["params"]["k_points"] == 5
    txt = out_txt.read_text()
    assert "SWITCHES: 2" in txt and "outward" in txt and "tracked" in txt and "off-sheet" in txt
    assert capsys.readouterr().out == txt
    pngs = sorted(os.listdir(ov))
    assert pngs == ["overlay_z000020.png", "overlay_z000030.png"]
    from PIL import Image
    im = np.asarray(Image.open(ov / pngs[0]))
    assert im.ndim == 3 and (im[..., 0] != im[..., 1]).any()          # coloured, not grey
    assert ((im == [0, 255, 255]).all(axis=2)).any()                  # switch ring drawn


def test_cli_flags_are_params():
    flags = {a.dest for a in ssf.build_parser()._actions}
    for f in ssf.Params.__dataclass_fields__:
        assert f in flags


def test_ssc_files_untouched():
    """The tool imports the spacing tool, it must not have copied or shadowed it."""
    assert ssf.ssc.__file__.endswith(os.path.join("sheet_spacing_check", "sheet_spacing_check.py"))
