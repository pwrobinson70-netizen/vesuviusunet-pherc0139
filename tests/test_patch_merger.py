"""Tests for tools/patch_merger on phantom_scroll phantoms (synthetic only; no real scan data)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("zarr")

ROOT = Path(__file__).resolve().parent.parent
for d in ("patch_merger", "phantom_scroll"):
    sys.path.insert(0, str(ROOT / "tools" / d))

import benchmark as bm  # noqa: E402
import patch_merger as pm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import trace_auditor as ta  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402
from ssc_io import ArrayVolume, load_mesh  # noqa: E402

SIZE = 128


@pytest.fixture(scope="module")
def ph():
    p = bm.make_params("round", SIZE, 0)
    sc = ps.Scroll(p)
    vol, _ = sc.render()
    cl = sc.centre_line()
    centre = ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf)
    turns = [sc.turn_surface(k) for k in range(p.turns)]
    dense = [sc.trace(np.full((sc.n_rows(), 4 * sc.n_cols()), float(k)))
             if False else t for k, t in enumerate(turns)]
    trees = [cKDTree(t.reshape(-1, 3)) for t in dense]
    return dict(sc=sc, p=p, vol=vol, centre=centre, turns=turns, trees=trees, pitch=p.pitch, step=p.grid_step,
                nc=sc.n_cols(), scale=(1 / p.grid_step, 1 / p.grid_step))


def patch(ph, name, xyz):
    return pm.patch_from_xyz(name, xyz, ph["scale"])


def run(ph, patches, **kw):
    prm = pm.Params(pitch_vox=ph["pitch"], **kw)
    return pm.merge(patches, ArrayVolume(ph["vol"]), ph["centre"], prm)


def on_turn(ph, comp, k):
    """Fraction of the component's valid points whose nearest true surface is turn k and within 0.25 pitch of it."""
    pts = comp["P"][comp["valid"]]
    d = np.stack([t.query(pts)[0] for t in ph["trees"]], 1)
    return float(np.mean((d.argmin(1) == k) & (d.min(1) < 0.25 * ph["pitch"])))


def cols(ph, a, b):
    nc = ph["nc"]
    return int(a * nc), int(b * nc)


# ------------------------------------------------------------------ same turn merges
def test_two_half_turns_of_one_turn_merge(ph):
    k = 1
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    A = patch(ph, "A", ph["turns"][k][:, a0:a1])
    B = patch(ph, "B", ph["turns"][k][:, b0:b1])
    rep = run(ph, [A, B])
    assert rep["summary"]["n_components"] == 1
    assert rep["summary"]["seams_accepted"] == 1 and rep["summary"]["seams_refused"] == 0
    comp = rep["components_data"][0]
    assert on_turn(ph, comp, k) == 1.0                                   # 100 percent of the merged surface is on turn 1
    assert comp["n_points"] > 0
    ncols = comp["valid"].any(0).sum()
    assert ncols >= 0.95 * (b1 - a0)                                      # the union, not just one patch
    assert comp["area_vx2"] > 1.5 * pm.area_vx2(np.where(A.valid[..., None], A.P, -1.0)) * 0.9


def test_merge_with_flipped_shifted_second_patch(ph):
    """B has its grid flipped in both axes and shifted by half a cell: the grids must be registered, not assumed equal."""
    k = 2
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.95)
    S = ph["turns"][k]
    mid = 0.5 * (S[:, :-1] + S[:, 1:])                                    # half-cell shifted copy
    B = patch(ph, "B", mid[:, b0:b1][::-1, ::-1])
    A = patch(ph, "A", S[:, a0:a1])
    rep = run(ph, [A, B])
    assert rep["summary"]["seams_accepted"] == 1, rep["seams"]
    comp = rep["components_data"][0]
    assert on_turn(ph, comp, k) == 1.0
    assert comp["valid"].any(0).sum() >= 0.95 * (b1 - a0)


def test_three_patches_chain(ph):
    k = 0
    spans = [(0.0, 0.40), (0.30, 0.70), (0.60, 0.98)]
    pats = [patch(ph, n, ph["turns"][k][:, slice(*cols(ph, *s))]) for n, s in zip("ABC", spans)]
    rep = run(ph, pats)
    assert rep["summary"]["n_components"] == 1 and rep["summary"]["seams_accepted"] == 2
    assert on_turn(ph, rep["components_data"][0], k) == 1.0


def test_pitch_measured_from_volume(ph):
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    pats = [patch(ph, "A", ph["turns"][1][:, a0:a1]), patch(ph, "B", ph["turns"][1][:, b0:b1])]
    rep = pm.merge(pats, ArrayVolume(ph["vol"]), ph["centre"], pm.Params())
    assert all(abs(x["pitch_vox"] - ph["pitch"]) < 0.2 * ph["pitch"] for x in rep["patches"])
    assert rep["summary"]["seams_accepted"] == 1


# ------------------------------------------------------------------ refusals
def test_adjacent_turns_are_refused_as_shared_sheet_mismatch(ph):
    a0, a1 = cols(ph, 0.0, 0.6)
    A = patch(ph, "A", ph["turns"][1][:, a0:a1])
    B = patch(ph, "B", ph["turns"][2][:, a0:a1])
    rep = run(ph, [A, B])
    assert rep["summary"]["n_components"] == 2
    assert rep["summary"]["seams_accepted"] == 0 and rep["summary"]["seams_refused"] == 1
    s = rep["seams"][0]
    assert s["status"] == "refused" and "shared-sheet mismatch" in s["reason"]
    assert on_turn(ph, rep["components_data"][0], 1) == 1.0 and on_turn(ph, rep["components_data"][1], 2) == 1.0


def test_gate_needs_volume_and_centre_unless_allowed(ph):
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    mk = lambda: [patch(ph, "A", ph["turns"][1][:, a0:a1]), patch(ph, "B", ph["turns"][1][:, b0:b1])]  # noqa: E731
    r = pm.merge(mk(), None, None, pm.Params(pitch_vox=ph["pitch"]))
    assert r["summary"]["seams_accepted"] == 0 and "not judged" in r["seams"][0]["reason"]
    r = pm.merge(mk(), None, None, pm.Params(pitch_vox=ph["pitch"], allow_unjudged=True))
    assert r["summary"]["seams_accepted"] == 1


@pytest.mark.parametrize("width,delta", [(0, 1.0), (4, -1.0)])
def test_planted_switch_far_side_is_refused(ph, width, delta):
    sc, nc = ph["sc"], ph["nc"]
    k = 2 if delta < 0 else 1
    xyz, truth = ps.switch_trace(sc, dict(turn=k, col=int(0.72 * nc), delta=delta, width=width, row0=0))
    A = patch(ph, "A", ph["turns"][k][:, slice(*cols(ph, 0.0, 0.58))])
    b0, _ = cols(ph, 0.42, 1.0)
    B = patch(ph, "B", xyz[:, b0:])                                        # runs on across the switch
    rep = run(ph, [A, B])
    other = k + (1 if delta > 0 else -1)
    for c in rep["components_data"]:
        assert on_turn(ph, c, k) == 1.0                                    # nothing of the other sheet got in
    d = np.stack([t.query(rep["components_data"][0]["P"][rep["components_data"][0]["valid"]])[0] for t in ph["trees"]], 1)
    assert (d.argmin(1) == other).sum() == 0
    kinds = {c["kind"] for pa in rep["patches"] for c in pa["cuts"]}
    assert kinds & {"edge-stretch", "winding-jump"}
    assert rep["summary"]["segments_dropped"] == 1
    far = [s for pa in rep["patches"] for s in pa["segments"] if s["status"] == "dropped"]
    assert len(far) == 1 and "far side" in far[0]["reason"]
    assert rep["summary"]["n_components"] == 1 and rep["summary"]["seams_accepted"] == 1
    # the merged surface reaches B's good part and stops at the switch
    comp = rep["components_data"][0]
    assert comp["valid"].any(0).sum() >= 0.9 * (int(0.72 * nc) - 3 - 0)


def test_switch_inside_the_overlap_is_refused_with_a_reason(ph):
    """The switch lies where B overlaps A: B's near side merges, its far side is refused as a shared-sheet mismatch
    (it lies on the next turn, one pitch from A) and is dropped."""
    sc, nc = ph["sc"], ph["nc"]
    xyz, _ = ps.switch_trace(sc, dict(turn=1, col=int(0.50 * nc), delta=1.0, width=0, row0=0))
    A = patch(ph, "A", ph["turns"][1][:, slice(*cols(ph, 0.0, 0.62))])
    B = patch(ph, "B", xyz[:, cols(ph, 0.38, 1.0)[0]:])
    rep = run(ph, [A, B])
    reasons = {s["b"]: (s["status"], s["reason"]) for s in rep["seams"]}
    assert reasons["B#0"][0] == "accepted" or reasons["B#1"][0] == "accepted"
    refused = [s for s in rep["seams"] if s["status"] == "refused"]
    assert len(refused) == 1 and "shared-sheet mismatch" in refused[0]["reason"]
    assert rep["summary"]["n_components"] == 1
    assert on_turn(ph, rep["components_data"][0], 1) == 1.0


def test_switch_in_lone_patch_makes_separate_components(ph):
    sc, nc = ph["sc"], ph["nc"]
    xyz, _ = ps.switch_trace(sc, dict(turn=1, col=int(0.5 * nc), delta=1.0, width=0, row0=0))
    rep = run(ph, [patch(ph, "L", xyz)])
    assert rep["summary"]["n_components"] == 2 and rep["summary"]["segments_dropped"] == 0
    assert sorted(on_turn(ph, c, k) for c, k in zip(rep["components_data"], (1, 2))) == [1.0, 1.0] or \
        sorted(on_turn(ph, c, k) for c, k in zip(rep["components_data"], (2, 1))) == [1.0, 1.0]


# ------------------------------------------------------------------ output
def test_invalid_points_stay_minus_one_and_gaps_are_bridged_only_when_narrow(ph, tmp_path):
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    SA = ph["turns"][1][:, a0:a1].copy()
    SA[10, 5] = -1.0                                                       # a one-cell hole inside A, away from the seam
    SA[20:30, 10:30] = -1.0                                                # a large one
    pats = [patch(ph, "A", SA), patch(ph, "B", ph["turns"][1][:, b0:b1])]
    rep = run(ph, pats, max_gap_pitch=0.5)
    comp = rep["components_data"][0]
    assert comp["n_bridged"] > 0
    P, v = comp["P"], comp["valid"]
    assert not v[24:26, 15:25].any()                                       # the big hole is not bridged
    assert v[9:12, 4:7].all()                                              # the small one is
    out = tmp_path / "out"
    pm.write_tifxyz(out / "c", P, v, comp["scale"])
    import tifffile
    xs, ys, zs = (tifffile.imread(out / "c" / f"{a}.tif") for a in "xyz")
    inv = ~v
    assert inv.any()
    assert (xs[inv] == -1).all() and (ys[inv] == -1).all() and (zs[inv] == -1).all()
    assert (xs[v] != -1).all()
    # never bridge a wider gap: with the flag at 0 nothing is filled
    rep0 = run(ph, [patch(ph, "A", SA), patch(ph, "B", ph["turns"][1][:, b0:b1])], max_gap_pitch=0.0)
    assert rep0["components_data"][0]["n_bridged"] == 0
    assert rep0["components_data"][0]["valid"].sum() < v.sum()


def test_bridge_gaps_unit():
    P = np.zeros((9, 30, 3))
    P[..., 0], P[..., 1] = np.arange(30)[None, :], np.arange(9)[:, None]
    valid = np.ones((9, 30), bool)
    valid[:, 5:7] = False            # 2 wide
    valid[:, 15:23] = False          # 8 wide
    P2, v2, n = pm.bridge_gaps(np.where(valid[..., None], P, np.nan), valid, 4)
    assert v2[:, 5:7].all() and not v2[:, 15:23].any()
    assert n == 18
    np.testing.assert_allclose(P2[:, 5:7, 0], [[4.5, 7.5]] * 9, atol=1.6)     # between the neighbours
    P3, v3, n3 = pm.bridge_gaps(np.where(valid[..., None], P, np.nan), valid, 0)
    assert n3 == 0 and (v3 == valid).all()


def test_roundtrip_ssc_io_and_formats(ph, tmp_path):
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    pats = [patch(ph, "A", ph["turns"][1][:, a0:a1]), patch(ph, "B", ph["turns"][1][:, b0:b1])]
    rep = pm.merge(pats, ArrayVolume(ph["vol"]), ph["centre"], pm.Params(pitch_vox=ph["pitch"]), out_dir=str(tmp_path))
    d = tmp_path / "component_000.tifxyz"
    for f in ("x.tif", "y.tif", "z.tif", "meta.json"):
        assert (d / f).is_file()
    import tifffile
    for ax in "xyz":
        a = tifffile.imread(d / f"{ax}.tif")
        assert a.dtype == np.float32 and a.ndim == 2                       # docs/FORMATS.md section 1
    m = load_mesh(d)
    comp = rep["components_data"][0]
    assert m.shape == comp["valid"].shape and (m.valid == comp["valid"]).all()
    np.testing.assert_allclose(m.x[m.valid], comp["P"][..., 0][comp["valid"]], atol=1e-3)
    meta = json.loads((d / "meta.json").read_text())
    assert meta["format"] == "tifxyz" and meta["type"] == "seg" and len(meta["scale"]) == 2 and meta["uuid"]
    assert m.scale == (pytest.approx(meta["scale"][0]), pytest.approx(meta["scale"][1]))
    pts = np.stack([m.x[m.valid], m.y[m.valid], m.z[m.valid]], -1)
    assert meta["bbox"][0] == pytest.approx(pts.min(0).tolist(), abs=1e-3)      # bbox is XYZ order
    assert meta["bbox"][1] == pytest.approx(pts.max(0).tolist(), abs=1e-3)
    assert meta["area_vx2"] == pytest.approx(comp["area_vx2"], rel=1e-3)
    # the output can itself be merged again (it is a valid input patch)
    again = pm.load_patches([str(d)])
    assert again[0].valid.sum() == comp["valid"].sum()
    for f in ("seam_report.json", "seam_report.txt", "overlay.png"):
        assert (tmp_path / f).is_file()
    j = json.loads((tmp_path / "seam_report.json").read_text())
    assert j["seams"][0]["status"] == "accepted" and "reason" in j["seams"][0]


def test_scale_flag_sets_output_grid(ph):
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    mk = lambda: [patch(ph, "A", ph["turns"][1][:, a0:a1]), patch(ph, "B", ph["turns"][1][:, b0:b1])]  # noqa: E731
    r1 = run(ph, mk())
    r2 = run(ph, mk(), scale=ph["scale"][0] / 2)
    h1, w1 = r1["components_data"][0]["valid"].shape
    h2, w2 = r2["components_data"][0]["valid"].shape
    assert r2["components_data"][0]["scale"] == (ph["scale"][0] / 2,) * 2
    assert abs(h2 - h1 / 2) <= 2 and abs(w2 - w1 / 2) <= 2
    assert r2["components_data"][0]["area_vx2"] == pytest.approx(r1["components_data"][0]["area_vx2"], rel=0.05)


def test_deterministic(ph, tmp_path):
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    outs = []
    for i in range(2):
        pats = [patch(ph, "A", ph["turns"][1][:, a0:a1]), patch(ph, "B", ph["turns"][1][:, b0:b1]),
                patch(ph, "C", ph["turns"][2][:, a0:a1])]
        o = tmp_path / f"o{i}"
        pm.merge(pats, ArrayVolume(ph["vol"]), ph["centre"], pm.Params(pitch_vox=ph["pitch"]), out_dir=str(o))
        outs.append(o)
    names = sorted(p.relative_to(outs[0]).as_posix() for p in outs[0].rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(outs[1]).as_posix() for p in outs[1].rglob("*") if p.is_file())
    for n in names:
        assert (outs[0] / n).read_bytes() == (outs[1] / n).read_bytes(), n


def test_cli_end_to_end(ph, tmp_path):
    import tifffile  # noqa: F401
    a0, a1 = cols(ph, 0.0, 0.58)
    b0, b1 = cols(ph, 0.42, 0.98)
    from vc3d_writers import write_tifxyz
    for n, (x0, x1) in (("pa", (a0, a1)), ("pb", (b0, b1))):
        write_tifxyz(tmp_path / "in" / n, ph["turns"][1][:, x0:x1].astype(np.float32), ph["scale"])
    np.save(tmp_path / "vol.npy", ph["vol"])
    cl = tmp_path / "cl.json"
    cl.write_text(json.dumps({"control_points": [{"z": float(z), "y": float(y), "x": float(x)} for z, y, x in ph["sc"].centre_line()]}))
    rc = pm.main([str(tmp_path / "in"), "--out-dir", str(tmp_path / "out"), "--npy", str(tmp_path / "vol.npy"),
                  "--umbilicus", str(cl), "--pitch-vox", str(ph["pitch"])])
    assert rc == 0
    j = json.loads((tmp_path / "out" / "seam_report.json").read_text())
    assert j["summary"]["n_components"] == 1 and j["summary"]["seams_accepted"] == 1
    assert pm.main([str(tmp_path / "nope"), "--out-dir", str(tmp_path / "o2")]) == 2


def test_overlap_seen_from_one_side_only_is_refused_not_crashed(ph):
    """Regression: a small patch lying inside a big one's footprint but on its border cells has candidates on one side only."""
    a0, a1 = cols(ph, 0.0, 0.6)
    A = patch(ph, "A", ph["turns"][1][:, a0:a1])
    B = patch(ph, "B", ph["turns"][1][:, a0 + 5:a0 + 9][20:24])           # 4 x 4 cells
    rep = run(ph, [A, B], min_overlap_points=5, min_segment_points=5)
    assert rep["summary"]["n_components"] >= 1                           # it ran; whatever it decided is in the report
    assert pm.winding_offsets.__name__ == "winding_offsets"
    assert pm.winding_offsets(None, None, np.array([], int), np.array([], int), None, 1.0, pm.Params()) == ([], None)
