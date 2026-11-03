"""Tests for tools/winding_sweep on phantom_scroll phantoms (synthetic only; no real scan data)."""
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("zarr")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parent.parent
for d in ("winding_sweep", "phantom_scroll"):
    sys.path.insert(0, str(ROOT / "tools" / d))

import benchmark as bm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import winding_sweep as ws  # noqa: E402
from ssc_io import InputError, load_mesh  # noqa: E402

SIZE, ANGLE = 128, 30.0


@pytest.fixture(scope="module")
def phantoms(tmp_path_factory):
    out = {}
    for name in ("round", "merged", "bad"):
        p = bm.make_params(name, SIZE, 0)
        sc, vol, lab, truth = ps.build(p, str(tmp_path_factory.mktemp(name)), zarr=False)
        out[name] = (p, vol.astype(np.float32))
    return out


def run(phantoms, name, out, **kw):
    p, vol = phantoms[name]
    nz = vol.shape[0]
    return ws.sweep(ws.Source(vol, name), nz // 4, nz - nz // 4, str(out), ws.Params(angle=ANGLE, **kw))


@pytest.fixture(scope="module")
def round_sweep(phantoms, tmp_path_factory):
    out = tmp_path_factory.mktemp("sweep_round")
    return run(phantoms, "round", out, n_angles=4), out


def test_round_every_turn_one_patch_all_pass(phantoms, round_sweep):
    r, out = round_sweep
    turns = phantoms["round"][0].turns
    assert [m["winding"] for m in r["manifest"]] == list(range(turns))
    assert [m["verdict"] for m in r["manifest"]] == [ws.PASS] * turns
    assert all(m["area_vx2"] > 0 and m["judged_fraction"] > 0.5 for m in r["manifest"])
    # seeds are ordered outward
    assert all(a["radius"] < b["radius"] for a, b in zip(r["manifest"], r["manifest"][1:]))


def test_round_consistent_at_every_angle(round_sweep):
    s = round_sweep[0]["summary"]
    assert s["n_crossings_per_angle"] == [4, 4, 4, 4]
    assert s["windings_found_at_every_angle"] == [0, 1, 2, 3]
    assert all(m["consistent"] for m in round_sweep[0]["manifest"])


def test_outputs_vc3d_and_window_below_one_circumference(round_sweep):
    r, out = round_sweep
    for m in r["manifest"]:
        d = out / m["patch"]
        for f in ("x.tif", "y.tif", "z.tif", "meta.json", "growth_log.json"):
            assert (d / f).is_file()
        meta = json.loads((d / "meta.json").read_text())
        assert meta["format"] == "tifxyz" and meta["winding"] == m["winding"]
        mesh = load_mesh(str(d))
        step = 1.0 / meta["scale"][0]
        assert mesh.shape[1] * step <= ws.Params().circumference_fraction * 2 * math.pi * m["radius"] + step
        z = mesh.z[mesh.valid]
        assert z.min() >= 32 - 1e-3 and z.max() <= 96 + 1e-3          # full-volume z, inside the band
    assert (out / "overlay_z64.png").is_file()
    for f in ("manifest.json", "manifest.csv", "summary.json", "summary.txt"):
        assert (out / f).is_file()


def test_patch_windings_match_true_turns(phantoms, round_sweep):
    from scipy.spatial import cKDTree
    r, out = round_sweep
    sc = ps.Scroll(phantoms["round"][0])
    trees = []
    for k in range(4):
        g = sc.turn_surface(k)
        g = g.reshape(-1, 3)
        trees.append(cKDTree(g[g[:, 0] != -1]))
    for m in r["manifest"]:
        mesh = load_mesh(str(out / m["patch"]))
        pts = np.stack([mesh.x[mesh.valid], mesh.y[mesh.valid], mesh.z[mesh.valid]], -1)[::20]
        d = np.stack([t.query(pts)[0] for t in trees], 1)
        assert np.bincount(d.argmin(1), minlength=4).argmax() == m["winding"]


def test_merged_reports_which_turns_were_found(phantoms, tmp_path):
    r = run(phantoms, "merged", tmp_path, n_angles=4)
    s = r["summary"]
    found = [m["winding"] for m in r["manifest"]]
    assert found and set(found) <= set(range(6))
    assert s["windings_found_per_angle"] and s["n_patches"] == len(found)
    assert sum(s["verdicts"].values()) == len(found)
    assert (tmp_path / "summary.txt").read_text().count("\n") > len(found)


def test_crushed_marks_not_judged_where_the_auditor_says_so(phantoms, tmp_path):
    r = run(phantoms, "bad", tmp_path)
    for m in r["manifest"]:
        st = [c["status"] for c in m["checks"]]
        if m["verdict"] == ws.NOPATCH:
            continue
        want = ws.FAIL if ws.FAIL in st else (ws.NJ if ws.NJ in st else ws.PASS)
        assert m["verdict"] == want
        if m["verdict"] == ws.NJ:
            assert m["reasons"]
    assert any(m["verdict"] == ws.NJ for m in r["manifest"])      # the crushed preset has a poorly followed centre line


def test_deterministic_across_runs_and_worker_counts(phantoms, tmp_path):
    a = run(phantoms, "round", tmp_path / "a", workers=1)
    b = run(phantoms, "round", tmp_path / "b", workers=2)

    def strip(r):
        return [{k: v for k, v in m.items() if k != "seconds"} for m in r["manifest"]]
    assert strip(a) == strip(b)
    for m in a["manifest"]:
        for f in ("x.tif", "y.tif", "z.tif"):
            assert (tmp_path / "a" / m["patch"] / f).read_bytes() == (tmp_path / "b" / m["patch"] / f).read_bytes()
        ma, mb = (json.loads((tmp_path / d / m["patch"] / "meta.json").read_text()) for d in "ab")
        ma.pop("uuid"), mb.pop("uuid")                                # sheet_tracer derives the uuid from the output path
        assert ma == mb


def test_band_outside_volume_errors_cleanly(phantoms, tmp_path):
    vol = phantoms["round"][1]
    nz = vol.shape[0]
    for lo, hi in ((nz - 10, nz + 40), (-5, 30), (40, 40), (50, 20)):
        with pytest.raises(InputError):
            ws.sweep(ws.Source(vol, "x"), lo, hi, str(tmp_path / "o"), ws.Params())
    np.save(tmp_path / "v.npy", vol)
    assert ws.main(["--npy", str(tmp_path / "v.npy"), "--z-lo", str(nz + 5), "--z-hi", str(nz + 50),
                    "--out-dir", str(tmp_path / "o2")]) == 2


def test_cli_end_to_end_exit_code(phantoms, tmp_path):
    np.save(tmp_path / "v.npy", phantoms["round"][1])
    code = ws.main(["--npy", str(tmp_path / "v.npy"), "--z-lo", "32", "--z-hi", "96", "--angle", str(ANGLE),
                    "--out-dir", str(tmp_path / "o"), "--workers", "1"])
    assert code == 0
    assert json.loads((tmp_path / "o" / "summary.json").read_text())["verdicts"]["PASS"] == 4


def test_bad_flags_error_cleanly(phantoms, tmp_path):
    vol = phantoms["round"][1]
    with pytest.raises(InputError):
        ws.sweep(ws.Source(vol, "x"), 32, 96, str(tmp_path), ws.Params(circumference_fraction=1.2))
    with pytest.raises(InputError):
        ws.sweep(ws.Source(vol, "x"), 32, 96, str(tmp_path), ws.Params(height=200.0))
