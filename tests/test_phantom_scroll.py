"""Tests for tools/phantom_scroll: shapes, determinism, truth really sits on the rendered sheets, bad traces."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("zarr")
pytest.importorskip("scipy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "phantom_scroll"))

import phantom_scroll as ps  # noqa: E402
import ssc_io  # noqa: E402
from scipy.ndimage import map_coordinates  # noqa: E402

SHAPE = (64, 112, 112)
BASE = dict(shape=SHAPE, turns=3, r0=9.0, pitch=15.0, thickness=5.0, grid_step=3.0, noise=0.03)


def params(**kw):
    d = dict(BASE)
    d.update(kw)
    return ps.Params(**d)


HARD = dict(squash=0.7, warp_amp=4.0, warp_wavelength=60.0, irregular=0.1, tilt=(0.08, -0.05),
            merge_strength=0.8, merge_turn=1.5, merge_phi=90.0, merge_sigma=11.0, ink=True)


@pytest.fixture(scope="module")
def round_ph(tmp_path_factory):
    out = tmp_path_factory.mktemp("round")
    return out, ps.build(params(), str(out), bad_switches=[ps.parse_switch("turn=1,col=40,delta=1")], bad_pairs=True)


@pytest.fixture(scope="module")
def hard_ph(tmp_path_factory):
    out = tmp_path_factory.mktemp("hard")
    return out, ps.build(params(**HARD), str(out))


def on_surface(vol, xyz):
    ok = xyz[..., 0] != -1
    pts = xyz[ok]
    return map_coordinates(vol.astype(np.float32), [pts[:, 2], pts[:, 1], pts[:, 0]], order=1)


# ----------------------------------------------------------------------------- shapes and files
def test_shapes_and_files(round_ph):
    out, (sc, vol, lab, truth) = round_ph
    assert vol.shape == SHAPE and vol.dtype == np.uint8
    assert lab.shape == SHAPE and lab.dtype == np.int16 and lab.min() == -1 and lab.max() == 2
    assert (np.load(out / "winding.npy") == lab).all()
    for k in range(3):
        m = ssc_io.load_mesh(out / "surfaces" / f"turn_{k:02d}")
        assert m.shape == (sc.n_rows(), sc.n_cols()) and m.scale == pytest.approx((1 / 3.0, 1 / 3.0))
    cl = np.loadtxt(out / "centreline.csv", delimiter=",", skiprows=1)
    assert cl.shape == (SHAPE[0], 3)
    villa = json.loads((out / "centreline_villa.json").read_text())["control_points"]
    assert len(villa) == SHAPE[0] and set(villa[0]) == {"z", "y", "x"}
    assert truth["n_turns"] == 3 and (out / "truth.json").exists()


def test_tifxyz_is_vc3d_layout(round_ph):
    """x/y/z.tif are float32 (rows, cols), xyz order, invalid = (-1,-1,-1), meta has the VC3D keys."""
    import tifffile
    out, (sc, *_rest) = round_ph
    d = out / "surfaces" / "turn_01"
    x, y, z = (tifffile.imread(d / f"{a}.tif") for a in "xyz")
    assert x.dtype == y.dtype == z.dtype == np.float32 and x.shape == (sc.n_rows(), sc.n_cols())
    meta = json.loads((d / "meta.json").read_text())
    assert {"bbox", "format", "scale", "type", "uuid"} <= set(meta) and meta["format"] == "tifxyz"
    ok = x != -1
    assert ((y != -1) == ok).all() and ((z != -1) == ok).all()
    # rows follow z: z grows down the rows, and x/y circle round along the columns
    assert (np.diff(z[:, 0]) > 0).all()
    c = np.array(sc.p.centre0[::-1])
    r = np.hypot(x[10] - c[0], y[10] - c[1])
    # turn 1 is the spiral r0 + pitch * (1 + phi / 2 pi) = 24 .. 39 voxels from the axis (undeformed phantom)
    assert r.min() == pytest.approx(24.0, abs=0.01) and r.max() == pytest.approx(39.0 - 15.0 / sc.n_cols(), abs=0.01)
    assert truth_bbox_ok(meta, x, y, z, ok)


def truth_bbox_ok(meta, x, y, z, ok):
    lo, hi = np.array(meta["bbox"][0]), np.array(meta["bbox"][1])
    pts = np.stack([x[ok], y[ok], z[ok]], 1)
    return np.allclose(lo, pts.min(0)) and np.allclose(hi, pts.max(0))


def test_zarr_and_png_outputs(tmp_path):
    ps.build(params(), str(tmp_path), zarr=True, png=True)
    v0, v1 = ssc_io.ZarrVolume(tmp_path / "volume.zarr", 0), ssc_io.ZarrVolume(tmp_path / "volume.zarr", 1)
    assert v0.data.shape == SHAPE and v1.data.shape == tuple(s // 2 for s in SHAPE) and v1.ct_scale == 2.0
    from PIL import Image
    assert len(list((tmp_path / "volume_png").glob("*.png"))) == SHAPE[0]
    assert np.asarray(Image.open(tmp_path / "volume_png" / "00010.png")).shape == SHAPE[1:]
    assert (np.asarray(v0.data[10]) == np.asarray(Image.open(tmp_path / "volume_png" / "00010.png"))).all()


# ----------------------------------------------------------------------------- determinism
def test_deterministic_and_seed_matters(tmp_path):
    a = ps.build(params(**HARD), str(tmp_path / "a"), zarr=False)
    b = ps.build(params(**HARD), str(tmp_path / "b"), zarr=False)
    c = ps.build(params(seed=1, **{k: v for k, v in HARD.items()}), str(tmp_path / "c"), zarr=False)
    assert (a[1] == b[1]).all() and (a[2] == b[2]).all()
    for f in ("surfaces/turn_00/x.tif", "surfaces/turn_02/z.tif", "centreline.csv", "truth.json", "ink_mask.png"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f
    assert not (a[1] == c[1]).all()


# ----------------------------------------------------------------------------- truth sits on the sheets
@pytest.mark.parametrize("which", ["round_ph", "hard_ph"])
def test_true_surfaces_sit_on_bright_sheets(which, request):
    out, (sc, vol, lab, truth) = request.getfixturevalue(which)
    p = sc.p
    sheet, air = p.papyrus * 255, p.air * 255
    for k in range(p.turns):
        xyz = sc.turn_surface(k)
        assert (xyz[..., 0] != -1).mean() > 0.9                       # most of the grid is inside the volume
        v = on_surface(vol, xyz)
        assert v.mean() > 0.85 * sheet, (k, v.mean())
        assert np.percentile(v, 5) > 0.55 * sheet
        gap = on_surface(vol, sc.trace(k + 0.5))                      # half-way to the next turn: dark gap
        if which == "round_ph":
            assert gap.mean() < 0.35 * v.mean()
        # voxel labels agree with the turn index on the surface
        pts = np.rint(xyz[xyz[..., 0] != -1]).astype(int)
        assert (lab[pts[:, 2], pts[:, 1], pts[:, 0]] == k).mean() > 0.97


def test_forward_inverse_round_trip_and_centre_line():
    sc = ps.Scroll(params(**HARD))
    rng = np.random.default_rng(0)
    pt = np.stack([rng.uniform(4, 60, 500), rng.uniform(15, 95, 500), rng.uniform(15, 95, 500)])
    assert np.abs(sc.forward(sc.inverse(pt)) - pt).max() < 0.05
    # undeformed, untilted: the centre line is the straight axis
    c = ps.Scroll(params()).centre_line()
    assert np.allclose(c[:, 0], np.arange(SHAPE[0])) and np.allclose(c[:, 1], 55.5) and np.allclose(c[:, 2], 55.5)
    # tilt moves it linearly, squash about the axis does not move it
    t = ps.Scroll(params(tilt=(0.1, -0.2), squash=0.6)).centre_line()
    assert np.allclose(t[:, 1] - t[0, 1], 0.1 * np.arange(SHAPE[0]), atol=1e-6)
    assert np.allclose(t[:, 2] - t[0, 2], -0.2 * np.arange(SHAPE[0]), atol=1e-6)


def test_crushed_ellipse_and_merge(hard_ph):
    out, (sc, vol, lab, truth) = hard_ph
    a, b = sc.turn_surface(1), sc.turn_surface(2)
    # sheets 1 and 2 touch near the blob (blob radius = r0 + pitch*1.5 ~ between them) and stay a pitch apart elsewhere
    ok = (a[..., 0] != -1) & (b[..., 0] != -1)
    d = np.linalg.norm(a - b, axis=-1)[ok]
    assert d.min() < 0.45 * sc.p.pitch and np.median(d) > 0.7 * sc.p.pitch
    # the volume really is merged there: the dark gap between 1 and 2 is brighter than a normal gap
    gaps = sc.trace(1.5)
    g = map_coordinates(vol.astype(np.float32), [gaps[..., 2][gaps[..., 0] != -1], gaps[..., 1][gaps[..., 0] != -1],
                                                 gaps[..., 0][gaps[..., 0] != -1]], order=1)
    assert g.max() > 0.6 * sc.p.papyrus * 255 > np.median(g)


def test_ink_is_a_small_density_change_on_one_sheet(hard_ph):
    out, (sc, vol, lab, truth) = hard_ph
    mask = np.asarray(__import__("PIL.Image", fromlist=["Image"]).open(out / "ink_mask.png")) > 0
    assert mask.shape == (sc.n_rows(), sc.n_cols()) and 0.02 < mask.mean() < 0.5
    xyz = sc.turn_surface(truth["ink"]["turn"])
    ok = xyz[..., 0] != -1
    v = np.full(mask.shape, np.nan)
    v[ok] = on_surface(vol, xyz)
    on, off = np.nanmean(v[mask & ok]), np.nanmean(v[~mask & ok])
    assert 1.03 < on / off < 1.25                                       # delta 0.10, texture and noise on top
    other = np.full(mask.shape, np.nan)
    x2 = sc.turn_surface(0)
    ok2 = x2[..., 0] != -1
    other[ok2] = on_surface(vol, x2)
    assert abs(np.nanmean(other[mask & ok2]) / np.nanmean(other[~mask & ok2]) - 1) < 0.1   # other sheets: no ink


# ----------------------------------------------------------------------------- bad traces
def test_bad_switch_switches_exactly_where_stated(round_ph):
    out, (sc, vol, lab, truth) = round_ph
    (sw,) = truth["switches"]
    assert sw["col"] == 40 and sw["delta"] == 1 and sw["direction"] == "outward"
    m = ssc_io.load_mesh(out / sw["trace"])
    t1, t2 = sc.turn_surface(1), sc.turn_surface(2)
    xyz = np.stack([m.x, m.y, m.z], -1).astype(np.float32)
    c = sw["col"]
    ok = t1[..., 0] != -1
    assert np.allclose(xyz[:, :c][ok[:, :c]], t1[:, :c][ok[:, :c]], atol=1e-4)           # follows turn 1 before
    ok2 = t2[..., 0] != -1
    assert np.allclose(xyz[:, c:][ok2[:, c:]], t2[:, c:][ok2[:, c:]], atol=1e-4)         # turn 2 from the column on
    assert not np.allclose(t1[:, c:][ok2[:, c:]], t2[:, c:][ok2[:, c:]])


def test_bad_switch_ramp_row0_and_inward(tmp_path):
    sc = ps.Scroll(params())
    xyz, t = ps.switch_trace(sc, ps.parse_switch("turn=2,col=30,delta=-1,width=10,row0=8"))
    t2, t1 = sc.turn_surface(2), sc.turn_surface(1)
    assert t["direction"] == "inward" and t["centre_col"] == 35.0
    assert np.allclose(xyz[:8], t2[:8])                                  # rows before row0 never switch
    assert np.allclose(xyz[8:, :30], t2[8:, :30])                        # before the column: unchanged
    assert np.allclose(xyz[8:, 40:], t1[8:, 40:], atol=1e-4)             # after the ramp: the inner turn
    mid = np.linalg.norm(xyz[10:, 35] - t2[10:, 35], axis=-1)
    assert (mid > 1).all() and (mid < np.linalg.norm(t1[10:, 35] - t2[10:, 35], axis=-1)).all()


def test_bad_pairs_have_the_stated_spacing(round_ph):
    out, (sc, vol, lab, truth) = round_ph
    from scipy.spatial import cKDTree
    pitch = sc.p.pitch
    a = sc.turn_surface(1)
    ok = a[..., 0] != -1
    want = {"adjacent": 1.0, "skipped": 2.0, "shared": 0.15, "off_sheet": 1.42}
    expect = {p["name"]: p["expect"] for p in truth["pairs"]}
    assert expect == {"adjacent": "adjacent", "skipped": "skipped", "shared": "shared", "off_sheet": "off_sheet"}
    for name, ratio in want.items():
        m = ssc_io.load_mesh(out / "bad" / f"pair_{name}")
        b = np.stack([m.x, m.y, m.z], -1)[ok]
        b = b[np.isfinite(b).all(-1)]
        d, _ = cKDTree(b).query(a[ok][:: 7])
        assert np.median(d) == pytest.approx(ratio * pitch, rel=0.12), (name, np.median(d))
    off = on_surface(vol, ps.Scroll(params()).trace(2.42))
    assert off.mean() < 0.35 * on_surface(vol, a).mean()               # B really is in the dark gap


# ----------------------------------------------------------------------------- CLI
def test_cli(tmp_path, capsys):
    rc = ps.main(["--out", str(tmp_path / "o"), "--shape", "32", "80", "80", "--turns", "2", "--r0", "8", "--pitch", "14",
                  "--no-zarr", "--bad-switch", "turn=0,col=20,delta=1", "--bad-pairs", "--squash", "0.8"])
    assert rc == 0
    t = json.loads((tmp_path / "o" / "truth.json").read_text())
    assert t["params"]["squash"] == 0.8 and t["params"]["shape"] == [32, 80, 80] and len(t["pairs"]) == 4
    assert (tmp_path / "o" / "bad" / "switch_00" / "x.tif").exists()


# ----------------------------------------------------------------------------- benchmark
def test_benchmark_runs_and_scores_the_round_phantom(tmp_path, capsys):
    sys.path.insert(0, str(ROOT / "tools" / "phantom_scroll"))
    import benchmark
    out_json = tmp_path / "b.json"
    assert benchmark.main(["--size", "128", "--phantoms", "round", "--json", str(out_json)]) == 0
    md = capsys.readouterr().out
    assert md.startswith("| phantom |") and "| round |" in md
    r = json.loads(out_json.read_text())[0]
    assert r["switch"]["true"] == 3 and r["switch"]["found"] == 3 and r["switch"]["false_on_true_turns"] == 0
    assert r["centre"]["mean_err"] < 1.0
    assert r["spacing"]["true_mean"] > 0.8 and r["spacing"]["bad"]["shared"] < 0.2 and r["spacing"]["bad"]["skipped"] < 0.3
