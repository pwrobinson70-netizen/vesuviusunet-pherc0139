"""Tests for tools/texture_judge: the fibre-texture continuity judge, and the phantom's anisotropic fibre texture (v0.3, default off)."""
import dataclasses
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("tifffile")

ROOT = Path(__file__).resolve().parent.parent
for d in ("texture_judge", "phantom_scroll", "sheet_spacing_check"):
    sys.path.insert(0, str(ROOT / "tools" / d))

import phantom_cases as pc  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import texture_judge as tj  # noqa: E402
from ssc_io import InputError  # noqa: E402

TJ = ROOT / "tools" / "texture_judge" / "texture_judge.py"
SIZE = 160


@pytest.fixture(scope="module")
def world():
    sc, vol, p = pc.make_phantom("round", SIZE, 0)
    return sc, pc.volume_of(vol), vol


def judged_on_fraction(rep):
    w = rep["windows"]
    return w["counts"][tj.ON] / max(1, w["n_windows"] - w["counts"][tj.NJ])


# ---------------------------------------------------------------------------------------------------- phantom: fibre texture, default off
def test_phantom_defaults_unchanged_by_fibre_option():
    """With the fibre flag off the volume, labels and truth.json are byte for byte what origin/main produced (hashes recorded from main)."""
    for name, vh, lh in (("round", "4289cb76f9c83c9ffda985988aa66bcee595c19eb13ec3c00ad1895e0f8cf33f",
                          "08c0a5ab908cfd6d0757bd03baa413a2f4c93eeb8fca6e0df6b3787293455515"),
                         ("crushed", "ebc0fb1834c8b08f9096c58c52e476aeb311aed116bd0c4bcd507c215f9ce306",
                          "740429bcf071a19b9cdec781d444284e24c36a8922014abe10f7f4292c57f385")):
        p = ps.make_params(name, 64, 3)
        assert p.fibre == 0.0
        v, lab = ps.Scroll(p).render()
        assert hashlib.sha256(v.tobytes()).hexdigest() == vh and hashlib.sha256(lab.tobytes()).hexdigest() == lh


def test_phantom_truth_json_unchanged_by_fibre_option(tmp_path):
    ps.build(ps.make_params("round", 48, 1), str(tmp_path), zarr=False)
    assert hashlib.sha256((tmp_path / "truth.json").read_bytes()).hexdigest() == \
        "71c83131a9c83d60c675e917df7163302e2fd88e55a5207efadf3edbb8dfea77"
    assert "fibre" not in json.loads((tmp_path / "truth.json").read_text())["params"]


def test_fibre_flag_changes_only_the_sheet_brightness():
    p0 = ps.make_params("round", 64, 3)
    p1 = dataclasses.replace(p0, fibre=0.4)
    (v0, l0), (v1, l1) = ps.Scroll(p0).render(), ps.Scroll(p1).render()
    assert (l0 == l1).all() and (v0 != v1).any()
    assert v1.std() != v0.std()
    # air far from any sheet is untouched
    assert (v0[l0 < 0] == v1[l0 < 0]).all()


def test_fibre_orientation_steps_by_the_drift_between_neighbouring_sheets(world):
    """Turn k and turn k+1 at the same angle differ by fibre_drift degrees (40): the quantity a planted switch exposes."""
    sc, V, _ = world
    th = []
    for w in (1.0, 2.0):
        R = tj.render_surface(pc.mesh_of(sc, w), V, tj.Params())
        st = tj.window_stats(R["layers"], tj.Params())
        th.append(st["orientation"][2, 1])
    d = float(tj.angdiff_deg(th[0], th[1], 2))
    assert 20 < d < 60, d   # nominal 40; windows of the two turns cover slightly different angles


# ---------------------------------------------------------------------------------------------------- the judge on phantoms
def test_true_trace_is_textured_and_has_no_break(world):
    sc, V, _ = world
    rep = tj.run(pc.mesh_of(sc, 1.0), V, tj.Params(), [80], "surface")
    assert rep["mode"] == "surface"
    assert judged_on_fraction(rep) >= 0.95
    assert rep["windows"]["counts"][tj.BRK] == 0 and rep["breaks"] == []
    assert rep["windows"]["judged_fraction"] > 0.8
    assert rep["verdict"] == "PASS" and rep["exit_code"] == 0
    assert rep["cut_lines"][0]["counts"][tj.ON] > 0.9 * rep["cut_lines"][0]["n_points"]


@pytest.mark.parametrize("turn,delta", [(1, 1), (2, -1)])
def test_planted_switch_is_a_break_within_three_windows(world, turn, delta):
    sc, V, _ = world
    col = sc.n_cols() // 2
    mesh, truth = pc.switch_mesh(sc, turn=turn, col=col, delta=delta)
    p = tj.Params()
    rep = tj.run(mesh, V, p, [80], "surface")
    assert rep["verdict"] == "FAIL" and rep["exit_code"] == 1
    cols = [b["grid_col"] for b in rep["breaks"] if b["axis"] == "cols"]
    tol = 3 * rep["grid"]["window_grid_rows_cols"][1]
    assert cols and min(abs(c - col) for c in cols) <= tol, (cols, col, tol)
    b = rep["breaks"][0]
    assert b["jump_deg"] > p.max_jump_deg and len(b["xyz"]) == 3 and all(np.isfinite(b["xyz"]))


def test_trace_in_the_gap_is_blurred(world):
    sc, V, _ = world
    rep = tj.run(pc.gap_mesh(sc), V, tj.Params(), [80], "surface")
    w = rep["windows"]
    assert w["counts"][tj.BLR] >= 0.9 * (w["n_windows"] - w["counts"][tj.NJ])
    assert w["counts"][tj.ON] == 0 and rep["verdict"] == "FAIL"


def test_trace_that_starts_on_the_wrong_sheet_and_stays_is_not_flagged(world):
    """KNOWN LIMIT (same as the switch finder): a trace that is consistent on the wrong sheet looks fine to a continuity judge."""
    sc, V, _ = world
    rep = tj.run(pc.wrong_sheet_mesh(sc, 2), V, tj.Params(), [80], "surface")
    assert rep["windows"]["counts"][tj.BRK] == 0 and rep["breaks"] == []
    assert judged_on_fraction(rep) >= 0.95


def test_deterministic(world):
    sc, V, _ = world
    mesh, _ = pc.switch_mesh(sc)
    a = tj.run(mesh, V, tj.Params(), [80], "surface")
    b = tj.run(mesh, V, tj.Params(), [80], "surface")
    for r in (a, b):
        r.pop("_internal")
    assert json.dumps(a, sort_keys=True, default=float) == json.dumps(b, sort_keys=True, default=float)


def test_window_flag_and_thresholds_are_cli_flags():
    ap = tj.build_parser()
    flags = {a.dest for a in ap._actions}
    for f in dataclasses.fields(tj.Params):
        assert f.name in flags, f"threshold {f.name} has no CLI flag"
    text = ap.format_help()
    assert "--max-jump-deg" in text and "--min-coherence" in text and "--break-run" in text


def test_pictures_are_written_with_the_break_marked(world, tmp_path):
    sc, V, _ = world
    mesh, _ = pc.switch_mesh(sc)
    rep = tj.run(mesh, V, tj.Params(), [80], "surface")
    files = tj.write_pictures(rep, tj.Params(), str(tmp_path), [80])
    names = {Path(f).name for f in files}
    assert {"surface_k+0.png", "surface_k+2.png", "surface_k-2.png", "overlay.png", "fibre_orientation.png"} <= names
    from PIL import Image
    ov = np.asarray(Image.open(tmp_path / "overlay.png"))
    red = (ov[..., 0] > 200) & (ov[..., 1] < 80) & (ov[..., 2] < 80)
    assert red.sum() > 50


# ---------------------------------------------------------------------------------------------------- bad inputs
def test_bad_parameters_are_refused():
    for kw in (dict(symmetry=3), dict(window=2), dict(max_jump_deg=95.0), dict(k=0.0), dict(break_run=0)):
        with pytest.raises(InputError):
            dataclasses.replace(tj.Params(), **kw).validate()


def test_cli_bad_inputs_exit_2(tmp_path, world):
    sc, V, vol = world
    def run(*a):
        return subprocess.run([sys.executable, str(TJ), *map(str, a)], capture_output=True, text=True)
    assert run(tmp_path / "nope", "--png-dir", tmp_path, "--out-dir", tmp_path / "o").returncode == 2
    assert run().returncode == 2                                    # argparse: required arguments
    ps.write_tifxyz(str(tmp_path / "m"), sc.trace(1.0), (0.25, 0.25))
    r = run(tmp_path / "m", "--png-dir", tmp_path / "missing", "--png-pixel-um", 1, "--voxel-size-um", 1, "--out-dir", tmp_path / "o")
    assert r.returncode == 2 and "error" in r.stderr
    r = run(tmp_path / "m", "--png-dir", tmp_path, "--png-pixel-um", 1, "--voxel-size-um", 1, "--symmetry", 3, "--out-dir", tmp_path / "o")
    assert r.returncode == 2


def test_surface_mesh_with_no_valid_point_is_refused(world):
    sc, V, _ = world
    from ssc_io import build_mesh
    bad = build_mesh("bad", np.full((6, 6), -1.0), np.full((6, 6), -1.0), np.full((6, 6), -1.0), {})
    with pytest.raises(InputError):
        tj.run(bad, V, tj.Params(), [], "surface")


def test_sparse_volume_without_heights_is_refused(tmp_path, world):
    sc, V, vol = world
    from PIL import Image
    d = tmp_path / "png"; d.mkdir()
    Image.fromarray(vol[80]).save(d / "00080.png")
    from ssc_io import PngVolume
    m = pc.mesh_of(sc, 1.0)
    with pytest.raises(InputError):
        tj.run(m, PngVolume(str(d), 1.0, 1.0), tj.Params(), [], "auto")
    rep = tj.run(m, PngVolume(str(d), 1.0, 1.0), tj.Params(), [80], "auto")
    assert rep["mode"] == "section"


# ---------------------------------------------------------------------------------------------------- real samples: smoke only
DATA = ROOT / "testdata"
SAMPLES = [("pherc_paris4_45um", 45.532, "2073,2600,3128"), ("pherc_paris4_7p91um", 7.91, "2644,5729,8814")]


@pytest.mark.parametrize("name,um,heights", SAMPLES)
@pytest.mark.parametrize("mesh", ["20260623164704-w116-117.tifxyz", "20260623165230-w118-119.tifxyz"])
def test_real_sample_smoke(tmp_path, name, um, heights, mesh):
    """Runs and writes its report; the numbers are reported in docs/texture_judge/RESULTS.md, not asserted here."""
    d = DATA / name
    if not (d / mesh).is_dir():
        pytest.skip("sample not present")
    out = tmp_path / "o"
    p = subprocess.run([sys.executable, str(TJ), str(d / mesh), "--png-dir", str(d / "slices"), "--png-pixel-um", str(um),
                        "--voxel-size-um", str(um), "--heights", heights, "--out-dir", str(out)], capture_output=True, text=True, timeout=600)
    assert p.returncode in (0, 1, 4), p.stderr[-800:]
    rep = json.loads((out / "texture_judge.json").read_text())
    assert rep["mode"] == "section" and len(rep["cut_lines"]) == 3
    assert (out / "texture_judge.txt").exists()
