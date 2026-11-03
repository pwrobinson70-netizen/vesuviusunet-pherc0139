"""Tests for tools/trace_auditor on synthetic concentric-ring CT and cylinder meshes (no real scan data)."""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("zarr")
pytest.importorskip("scipy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "trace_auditor"))

import trace_auditor as ta  # noqa: E402
from ssc_io import ArrayVolume, build_mesh  # noqa: E402
from test_sheet_spacing_check import CX, CY, NZ, PITCH, R0, cylinder, make_ct  # noqa: E402

HEIGHTS = [30.0, 50.0, 70.0]
P = ta.Params()


@pytest.fixture(scope="module")
def vol():
    return ArrayVolume(make_ct(0.0))


@pytest.fixture(scope="module")
def centre():
    z = np.arange(0, NZ, 10.0)
    return ta.Centre(z, np.full_like(z, CY), np.full_like(z, CX), "test", np.inf)


def hop_mesh(r0, col, delta, n_cols=720):
    th = np.linspace(0, 2 * np.pi, n_cols, endpoint=False)
    r = r0 + delta * (np.arange(n_cols) >= col)
    x, y = CX + r * np.cos(th), CY + r * np.sin(th)
    z = np.arange(NZ, dtype=float)
    return build_mesh("hop", np.tile(x, (NZ, 1)), np.tile(y, (NZ, 1)), np.tile(z[:, None], (1, n_cols)), {"scale": [0.5, 0.5]})


def audit(meshes, vol, centre, **kw):
    p = ta.Params(**kw)
    ssf_p, ssc_p = ta.ssf.Params(vertical=1), ta.ssc.Params()
    return ta.audit(meshes, vol, HEIGHTS, centre, p, ssf_p, ssc_p)


def check(trace, name):
    return next(c for c in trace["checks"] if c["check"] == name)


# ------------------------------------------------------------------ the winding-number jump detector
def spiral(n=300, turns=1.0, pitch=22.0, r0=60.0, wobble=0.0):
    th = np.linspace(0, 2 * math.pi * turns, n)
    return th, r0 + pitch * th / (2 * math.pi) + wobble * np.sin(3 * th)


def test_smooth_spiral_has_no_jump():
    th, r = spiral(turns=2.0)
    assert ta.detect_jumps(th, r, 22.0, P) == []


def test_squashed_ellipse_radius_variation_is_not_a_jump():
    th = np.linspace(0, 4 * math.pi, 400)
    a, b = 100.0, 55.0                                              # a squash of 0.55: radius swings by 45 voxels
    r = a * b / np.sqrt((b * np.cos(th)) ** 2 + (a * np.sin(th)) ** 2) + 12.0 * th / (2 * math.pi)
    assert ta.detect_jumps(th, r, 12.0, P) == []


@pytest.mark.parametrize("step", [22.0, -22.0, 1.5 * 22.0])
@pytest.mark.parametrize("direction", [1, -1])
def test_a_step_of_about_a_pitch_is_found_at_the_right_point(step, direction):
    th, r = spiral(n=360, turns=1.5)
    at = 200
    r = r + step * (np.arange(len(r)) >= at)
    if direction < 0:
        th, r = th[::-1], r[::-1]
        at = len(th) - at
    (j,) = ta.detect_jumps(th, r, 22.0, P)
    assert abs(j["index"] - at) <= 1
    assert abs(abs(j["pitches"]) - abs(step) / 22.0) < 0.15
    assert (j["step"] > 0) == ((step > 0) == (direction > 0))


def test_ramped_step_is_found_and_a_small_step_is_not():
    th, r = spiral(n=360, turns=1.5)
    ramp = np.clip((np.arange(360) - 180) / 12.0, 0, 1)
    assert len(ta.detect_jumps(th, r + 22.0 * ramp, 22.0, P)) == 1
    assert ta.detect_jumps(th, r + 0.4 * 22.0 * (np.arange(360) >= 200), 22.0, P) == []      # 0.4 pitch < 0.6
    assert len(ta.detect_jumps(th, r + 0.4 * 22.0 * (np.arange(360) >= 200), 22.0, ta.Params(wn_jump_pitch=0.3))) == 1


def test_step_inside_the_first_window_is_not_tested():
    th, r = spiral(n=360, turns=1.5)                                # 20 deg = 1/18 turn = 20 of 540 deg... first ~13 points
    assert ta.detect_jumps(th, r + 22.0 * (np.arange(360) >= 4), 22.0, P) == []


def test_local_pitch_is_measured_per_point_and_overridable(vol):
    sp = ta.ssc.Params(max_gap_vox=float("inf"))
    line = ta.ssc.cut_line(cylinder(R0), 50.0, sp)
    pp = ta.local_pitch(vol, line, 50.0, ta.ssf.Params())
    assert pp.shape == (line.n,) and np.allclose(pp, PITCH, rtol=0.05)
    assert np.all(ta.local_pitch(vol, line, 50.0, ta.ssf.Params(), override=9.0) == 9.0)
    assert ta.local_pitch(vol, ta.ssc.cut_line(cylinder(R0), 500.0, sp), 500.0, ta.ssf.Params()) is None


def test_jump_threshold_follows_the_local_pitch():
    th, r = spiral(n=360, turns=1.5)
    r = r + 12.0 * (np.arange(360) >= 200)                         # a 12-voxel step
    assert ta.detect_jumps(th, r, 22.0, P) == []                   # 0.55 of a 22-voxel pitch: below 0.6
    local = np.where(np.arange(360) >= 150, 12.0, 22.0)            # but a full pitch where the sheets are 12 apart
    (j,) = ta.detect_jumps(th, r, local, P)
    assert j["pitches"] == pytest.approx(1.0, abs=0.1)


# ------------------------------------------------------------------ offsets of B against A
def ring_runs(r, n=360, cx=0.0, cy=0.0):
    th = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return [dict(theta=th, r=np.full(n, float(r)), col=np.arange(n), xy=np.stack([cx + r * np.cos(th), cy + r * np.sin(th)], 1))]


def test_pair_offsets_nearest_sheet_of_a_multi_turn_a():
    a = ring_runs(100.0) + ring_runs(112.0) + ring_runs(124.0)
    off = ta.pair_offsets(a, ring_runs(118.5))
    assert np.allclose(np.abs(off), 5.5, atol=1e-6)                 # nearest of 112 and 124 is 112 (6.5) .. 124 (5.5): 124
    off = ta.pair_offsets(ring_runs(100.0), ring_runs(112.0))
    assert np.allclose(off, 12.0)
    assert np.allclose(ta.pair_offsets(ring_runs(100.0), ring_runs(88.0)), -12.0)


# ------------------------------------------------------------------ centre line input
def test_read_umbilicus_formats_agree(tmp_path):
    zyx = [(0, 120, 100), (250, 123, 98), (500, 130, 101)]
    (tmp_path / "a.json").write_text(json.dumps({"control_points": [{"z": z, "y": y, "x": x} for z, y, x in zyx]}))
    (tmp_path / "b.json").write_text(json.dumps({"vc_umbilicus_json_version": "1", "points": [{"x": x, "y": y, "z": z} for z, y, x in zyx]}))
    (tmp_path / "c.txt").write_text("# z, y, x\n" + "\n".join(f"{z}, {y}, {x}" for z, y, x in zyx))
    (tmp_path / "d.txt").write_text("\n".join(f"{y + 500}, {z + 500}, {x + 500}" for z, y, x in zyx))
    want = np.array(zyx, float).T
    for name, fmt in (("a.json", "auto"), ("b.json", "auto"), ("c.txt", "zyx-text"), ("d.txt", "thaumato")):
        got = np.array(ta.read_umbilicus(tmp_path / name, fmt))
        assert np.allclose(got, want), name
    assert np.allclose(np.array(ta.read_umbilicus(tmp_path / "a.json", "auto", 2.0)), 2 * want)
    for bad in (("c.txt", "auto"), ("missing.json", "auto"), ("a.json", "nope")):
        with pytest.raises(ta.InputError):
            ta.read_umbilicus(tmp_path / bad[0], bad[1])


def test_centre_is_judged_only_near_a_control_point():
    c = ta.Centre([0, 100], [5, 5], [7, 7], "t", 40.0)
    assert c.at(10) == (5.0, 7.0) and c.at(95) == (5.0, 7.0)
    assert c.at(50) is None and c.at(-1) is None and c.at(101) is None


# ------------------------------------------------------------------ verdicts
def test_clean_single_trace_passes(vol, centre):
    rep = audit([cylinder(R0)], vol, centre)
    (t,) = rep["traces"]
    assert t["verdict"] == ta.PASS and [c["status"] for c in t["checks"]] == [ta.PASS, ta.PASS]


def test_adjacent_clean_pair_passes(vol, centre):
    rep = audit([cylinder(R0, name="a"), cylinder(R0 + PITCH, name="b")], vol, centre)
    assert [t["verdict"] for t in rep["traces"]] == [ta.PASS, ta.PASS]
    wo = check(rep["traces"][1], "winding_offset")
    assert wo["heights"][0]["median_offset_pitches"] == pytest.approx(1.0, abs=0.05)
    assert check(rep["traces"][1], "spacing")["clean_fraction"] > 0.95


def test_sheet_switch_fails_with_reasons_from_both_checks(vol, centre):
    rep = audit([hop_mesh(R0 + PITCH, 300, PITCH)], vol, centre)
    (t,) = rep["traces"]
    assert t["verdict"] == ta.FAIL
    sw, wj = check(t, "switch_finder"), check(t, "winding_jumps")
    assert sw["status"] == ta.FAIL and wj["status"] == ta.FAIL
    assert all(abs(j["col"] - 300) <= 3 and 0.8 < j["step_pitches"] < 1.2 for j in wj["jumps"])
    assert len(wj["jumps"]) == len(HEIGHTS) and len(sw["switches"]) >= len(HEIGHTS)


def test_trace_that_starts_on_the_wrong_sheet_is_caught_only_by_the_winding_offset(vol, centre):
    """B lies on the sheet two away from A for its whole length: no switch, no jump, but it is not A's neighbour."""
    rep = audit([cylinder(R0, name="a"), cylinder(R0 + 2 * PITCH, name="b")], vol, centre)
    b = rep["traces"][1]
    assert check(b, "switch_finder")["status"] == ta.PASS and check(b, "winding_jumps")["status"] == ta.PASS
    wo = check(b, "winding_offset")
    assert wo["status"] == ta.FAIL and "+2" in wo["reason"]
    assert b["verdict"] == ta.FAIL and rep["traces"][0]["verdict"] == ta.PASS
    # the same wrong sheet for the whole trace is invisible to a lone audit of B
    assert audit([cylinder(R0 + 2 * PITCH, name="b")], vol, centre)["traces"][0]["verdict"] == ta.PASS


def test_shared_sheet_fails(vol, centre):
    rep = audit([cylinder(R0, name="a"), cylinder(R0 + 0.1 * PITCH, name="b")], vol, centre)
    b = rep["traces"][1]
    assert b["verdict"] == ta.FAIL and check(b, "winding_offset")["status"] == ta.FAIL and check(b, "spacing")["status"] == ta.FAIL


def test_expect_side_flag(vol, centre):
    pair = [cylinder(R0, name="a"), cylinder(R0 - PITCH, name="b")]
    assert audit(pair, vol, centre, expect_side="either")["traces"][1]["verdict"] == ta.PASS
    assert check(audit(pair, vol, centre, expect_side="outward")["traces"][1], "winding_offset")["status"] == ta.FAIL
    assert check(audit(pair, vol, centre, expect_side="inward")["traces"][1], "winding_offset")["status"] == ta.PASS


def test_no_centre_is_not_judged_not_pass(vol):
    rep = audit([cylinder(R0)], vol, None)
    (t,) = rep["traces"]
    assert check(t, "winding_jumps")["status"] == ta.NJ and t["verdict"] == ta.NJ
    # a real failure is still a FAIL without a centre
    assert audit([hop_mesh(R0 + PITCH, 300, PITCH)], vol, None)["traces"][0]["verdict"] == ta.FAIL


def test_mesh_off_the_sheets_is_not_judged_by_the_switch_finder(vol, centre):
    rep = audit([cylinder(R0 + PITCH + 5)], vol, centre)           # in the dark gap: nothing to follow
    t = rep["traces"][0]
    assert check(t, "switch_finder")["status"] == ta.NJ and "tracked" in check(t, "switch_finder")["reason"]
    assert t["verdict"] == ta.NJ                                            # never a PASS when the sheet could not be followed


def test_thresholds_are_live(vol, centre):
    m = hop_mesh(R0 + PITCH, 300, 0.5 * PITCH)                      # half a pitch
    assert check(audit([m], vol, centre)["traces"][0], "winding_jumps")["status"] == ta.PASS
    assert check(audit([m], vol, centre, wn_jump_pitch=0.3)["traces"][0], "winding_jumps")["status"] == ta.FAIL
    clean = [cylinder(R0, name="a"), cylinder(R0 + PITCH, name="b")]
    assert audit(clean, vol, centre, min_clean_fraction=1.01)["traces"][1]["verdict"] == ta.FAIL


# ------------------------------------------------------------------ CLI
def _write_mesh(d, m):
    import tifffile
    d.mkdir(parents=True, exist_ok=True)
    for ax in "xyz":
        tifffile.imwrite(str(d / f"{ax}.tif"), np.nan_to_num(getattr(m, ax), nan=-1).astype(np.float32))
    (d / "meta.json").write_text(json.dumps({"scale": [0.5, 0.5], "format": "tifxyz", "type": "seg"}))


@pytest.fixture(scope="module")
def disk(tmp_path_factory):
    import zarr
    d = tmp_path_factory.mktemp("aud")
    z = zarr.open(str(d / "ct.zarr"), mode="w", shape=(NZ, 640, 512), chunks=(1, 320, 256), dtype="f4")
    z[:] = make_ct(0.0)
    _write_mesh(d / "a", cylinder(R0))
    _write_mesh(d / "b", cylinder(R0 + PITCH))
    _write_mesh(d / "c", cylinder(R0 + 2 * PITCH))
    zs = list(range(0, NZ, 10))
    (d / "umb.json").write_text(json.dumps({"control_points": [{"z": z_, "y": CY, "x": CX} for z_ in zs]}))
    (d / "umb_far.json").write_text(json.dumps({"control_points": [{"z": 1000 + z_, "y": CY, "x": CX} for z_ in zs]}))
    return d


def run_cli(disk, tmp_path, *args):
    return ta.main([*args, "--zarr", str(disk / "ct.zarr"), "--out-dir", str(tmp_path / "out"), "--heights", "30,50,70"])


def test_cli_pass_fail_and_not_judged_exit_codes(disk, tmp_path, capsys):
    umb = ["--umbilicus", str(disk / "umb.json")]
    assert run_cli(disk, tmp_path, str(disk / "a"), str(disk / "b"), *umb, "--png") == 0
    out = tmp_path / "out"
    rep = json.loads((out / "audit.json").read_text())
    assert [t["verdict"] for t in rep["result"]["traces"]] == ["PASS", "PASS"]
    assert rep["params"]["wn_jump_pitch"] == 0.6 and rep["inputs"]["heights"] == [30.0, 50.0, 70.0]
    assert "PASS" in (out / "audit.txt").read_text() and list((out / "png").glob("winding_*.png"))
    assert run_cli(disk, tmp_path, str(disk / "a"), str(disk / "c"), *umb) == 1
    assert "FAIL" in capsys.readouterr().out
    assert run_cli(disk, tmp_path, str(disk / "a"), "--umbilicus", str(disk / "umb_far.json")) == 4
    assert run_cli(disk, tmp_path, str(disk / "a"), "--umbilicus", str(disk / "nope.json")) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_estimates_the_centre_when_none_is_given(disk, tmp_path):
    rc = ta.main([str(disk / "a"), "--zarr", str(disk / "ct.zarr"), "--out-dir", str(tmp_path / "o"), "--heights", "30,50,70",
                  "--centre-z-step", "10"])
    rep = json.loads((tmp_path / "o" / "audit.json").read_text())
    assert rep["inputs"]["centre"].startswith("umbilicus_finder") or "only" in rep["inputs"]["centre"]
    assert rc in (0, 4)                                                      # never a FAIL on a clean ring


def test_every_threshold_is_a_flag_and_in_the_readme():
    import dataclasses
    parser = ta.build_parser()
    flags = {s for a in parser._actions for s in a.option_strings}
    readme = (ROOT / "tools" / "trace_auditor" / "README.md").read_text()
    for f in dataclasses.fields(ta.Params):
        flag = "--" + f.name.replace("_", "-")
        assert flag in flags, flag
        assert flag in readme, f"{flag} is not documented in README.md"
    for prefix, cls in (("ssf", ta.ssf.Params), ("ssc", ta.ssc.Params), ("uf", ta.uf.Params)):
        for f in dataclasses.fields(cls):
            assert f"--{prefix}-" + f.name.replace("_", "-") in flags
    assert re.search(r"--ssf-", readme) and re.search(r"--ssc-", readme) and re.search(r"--uf-", readme)
