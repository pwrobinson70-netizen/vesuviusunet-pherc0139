"""Regression tests for REVIEW_ROUND2 (docs/REVIEW_ROUND2.md). Written BEFORE the fixes (the commit before is red).

Synthetic data only. Finding ids (A1.. auditor, R1.. repair, P1.. phantom, T1.. tracer) match the review document.
Strict xfail = a documented finding that is NOT fixed; the test turns red the day somebody fixes it.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("zarr")

ROOT = Path(__file__).resolve().parent.parent
for d in ("trace_repair", "trace_auditor", "phantom_scroll", "sheet_tracer"):
    sys.path.insert(0, str(ROOT / "tools" / d))
DATA = Path(__file__).resolve().parent / "data_round2"

import phantom_scroll as ps  # noqa: E402
import sheet_tracer as st  # noqa: E402
import trace_auditor as ta  # noqa: E402
import trace_repair as tr  # noqa: E402
from ssc_io import load_mesh  # noqa: E402
from test_trace_repair import SIZE, audit, env, fraction_on, plant, ramp  # noqa: E402,F401  (env is a fixture)

P = ta.Params()


def run_data(name):
    z = np.load(DATA / f"{name}.npz")
    return z["theta"], z["r"], z["pitch"], z["col"]


# =============================================================================================
# A1 (BUG) trace_auditor.detect_jumps: the step is the difference of two 20-degree window MEANS minus a
# median-slope term. On a patch with only ~4 degrees per point (a sheet_tracer patch) the window holds 5 points
# and curvature of r(theta) alone makes a "step". Real data: phantom 'bad' (squash 0.55), sheet_tracer patch
# grown from turn 2, height z=206: the trace is 100% on its turn (|w - 2| <= 0.07 everywhere) and the adjacent
# points differ by 0.42 voxel at the reported column, yet the old code reported "radius jumps -0.61 pitch".
def test_A1_curvature_alone_is_not_a_jump_on_a_sparse_patch():
    th, r, pit, col = run_data("crushed_run")
    assert abs(r[25] - r[24]) < 1.0                                 # no discontinuity at the reported column
    assert ta.detect_jumps(th, r, pit, P) == []


@pytest.mark.parametrize("at", [14, 20, 27])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_A1_control_a_real_hop_on_the_same_curved_patch_is_still_found(at, sign):
    th, r, pit, col = run_data("crushed_run")
    r = r + sign * pit * (np.arange(len(r)) >= at)                  # a full local pitch, hard hop
    out = ta.detect_jumps(th, r, pit, P)
    assert len(out) == 1 and abs(out[0]["index"] - at) <= 1
    assert (out[0]["step"] > 0) == (sign > 0)


def test_A1_control_a_ramped_hop_on_the_same_patch_is_still_found():
    th, r, pit, col = run_data("crushed_run")
    ramp_ = np.clip((np.arange(len(r)) - 18) / 4.0, 0, 1)           # 4-column ramp, as in the benchmark
    out = ta.detect_jumps(th, r + pit * ramp_, pit, P)
    assert len(out) == 1


# A2 (RISK -> fixed) detect_jumps: the first and last 20 degrees of every run are not tested. A sheet_tracer patch is
# ~40 columns x 4 degrees = 160 degrees, so 40 of 160 degrees (a quarter, and exactly where ring growth hops
# sheets: at the periphery) are blind. REVIEW_ROUND1 R1 is the same blind zone in sheet_switch_finder.
@pytest.mark.parametrize("at", [4, 5, 35, 36])
def test_A2_a_hop_near_the_end_of_a_short_run_is_found(at):
    n = 41
    th = np.linspace(0.0, math.radians(160), n)
    r = 60.0 + 20.0 * th / (2 * math.pi)
    out = ta.detect_jumps(th, r + 20.0 * (np.arange(n) >= at), 20.0, P)
    assert len(out) == 1 and abs(out[0]["index"] - at) <= 1


def test_A2_smooth_curved_patch_has_no_false_jump_at_its_ends():
    th, r, pit, col = run_data("crushed_run")
    assert ta.detect_jumps(th, r, pit, P) == []
    assert ta.detect_jumps(th[::-1], r[::-1], pit[::-1], P) == []


# A3 (RISK, NOT fixed) a trace that slides from one sheet to a TOUCHING neighbour (phantom 'merged', sheets 1 and 2
# 3 voxels apart at the blob) has no radial step of the size of a CT pitch (20 voxels): the radius is smooth to
# +-0.7 voxel per point while 7% of the patch is on the wrong turn. The auditor judges in units of the measured CT
# pitch, and where two sheets merge the CT pitch is the spacing of the merged pair to the next one. Nothing in the
# auditor can see this; see docs/REVIEW_ROUND2.md A3 for what was tried.
@pytest.mark.xfail(strict=True, reason="A3: sub-pitch slide across touching sheets is invisible to the jump test")
def test_A3_slide_across_touching_sheets_is_reported():
    th, r, pit, col = run_data("merged_leak_run")
    out = ta.detect_jumps(th, r, pit, P)
    assert any(24 <= col[o["index"]] <= 27 for o in out)


# =============================================================================================
# R1 (BUG) trace_repair: a repair acts on every point beyond the first reported line, whether or not the report is
# true or correctly placed, and never checks that it did anything at the reported place. Two failures recorded in
# tools/sheet_tracer/SCORE_RESULTS.json:
#   (a) false alarm: audit FAIL, truth unchanged (on-turn 100% -> 100%), the re-snap nudged 24% of the points by
#       ~0.8 voxel and the verdict flipped FAIL -> PASS: a PASS bought by a nudge, not by a repair;
#   (b) mislocated report: a leak at columns 0-5, a (false) vertical switch reported at column 24; the chain
#       started inside the leak, carried it down the rows, 52 points moved ~18 voxels, on-turn 99.1% -> 97.2%.
def audit_json(env, name, check):
    doc = dict(result=dict(traces=[dict(name=name, checks=[check], heights=[dict(z=96.0, pitch=env["p"].pitch)])]))
    path = env["dir"] / f"{name}_audit.json"
    path.write_text(json.dumps(doc))
    return path


def repair_cli(env, trace, audit_path, *extra):
    out = env["dir"] / f"{trace.name}_fixed"
    rc = tr.main([str(trace), "--audit", str(audit_path), "--npy", str(env["dir"] / "v.npy"), "--out", str(out), *extra])
    assert rc == 0
    return out, json.loads((out / "repair_summary.json").read_text())


def test_R1a_an_unconfirmed_switch_leaves_the_trace_byte_identical(env):
    path = plant(env, "r1a", np.full((env["sc"].n_rows(), env["sc"].n_cols()), 1.0))      # on turn 1 everywhere
    ap = audit_json(env, "r1a", dict(check="winding_jumps", status="FAIL", jumps=[dict(col=20, step_pitches=-0.7, z=96.0)]))
    out, s = repair_cli(env, path, ap)
    assert not s["repaired"]
    assert s["unconfirmed"] and s["unconfirmed"][0]["line"] == 20
    for f in ("x.tif", "y.tif", "z.tif", "meta.json"):
        assert (path / f).read_bytes() == (out / f).read_bytes()


def test_R1b_a_mislocated_vertical_switch_does_not_carry_a_leak_down_the_trace(env):
    nr, nc = env["sc"].n_rows(), env["sc"].n_cols()
    w = np.full((nr, nc), 1.0)
    w[20:28, 0:6] = 2.0                                              # a small leak onto the next sheet, columns 0-5
    path = plant(env, "r1b", w)
    before = fraction_on(env, path, np.full_like(w, 1.0))
    sw = dict(kind="vertical", col=30, row=25.4, confidence=0.7, direction="inward", height=96.0)
    ap = audit_json(env, "r1b", dict(check="switch_finder", status="FAIL", switches=[sw]))
    out, s = repair_cli(env, path, ap)
    assert fraction_on(env, out, np.full_like(w, 1.0)) >= before - 1e-9
    assert not s["repaired"] and s["unconfirmed"]


def test_R1c_a_real_switch_is_still_confirmed_and_repaired(env):
    w = ramp(env, 1, [(0.30, 1.0)])
    path = plant(env, "r1c", w)
    rep = audit(env, load_mesh(str(path)))
    assert rep["traces"][0]["verdict"] == ta.FAIL
    (env["dir"] / "r1c.json").write_text(json.dumps(dict(result=rep), default=float))
    out, s = repair_cli(env, path, env["dir"] / "r1c.json")
    assert s["repaired"] and s["confirmed"] and not s["unconfirmed"]
    assert fraction_on(env, out, np.full_like(w, 1.0)) >= 0.9


# R2 (BUG) trace_repair.repair_axis: a cell is repaired from its predecessor along the chain, but "has a predecessor" was
# tested on the ORIGINAL validity, so the cells after a hole in a row were snapped from their own unrepaired (wrong-sheet)
# neighbour: they stay on the wrong sheet and nothing says so. sheet_tracer patches are full of holes (rejected cells).
def test_R2_cells_behind_a_hole_are_counted_not_silently_left_on_the_wrong_sheet():
    import types
    R, C = 7, 12
    P_ = np.zeros((R, C, 3))
    P_[..., 0], P_[..., 1], P_[..., 2] = np.arange(C)[None, :], np.arange(R)[:, None], 50.0
    P_[:, 6:, 2] += 20.0                                           # from column 6 on every point is 20 along the normal too far
    P_[3, 6] = -1                                                  # one hole in row 3

    class Tz:                                                      # normals along z, snap = identity: isolates the bookkeeping
        def normals_at(self, q):
            n = np.zeros((len(q), 3))
            n[:, 2] = 1
            return n, np.ones(len(q))

        def snap(self, q, n, w):
            return q.copy(), np.zeros(len(q)), np.ones(len(q), bool), np.zeros(len(q))

    out = tr.repair_axis(P_, 6, Tz(), 10.0, types.SimpleNamespace(snap_pitch=1.0, outlier_pitch=0.35))
    assert out["unreached"] == 5                                   # row 3, columns 7..11
    assert np.all(P_[3, 7:, 2] == 70.0)                            # ... left as they were, and said so
    assert np.all(P_[np.arange(R) != 3, 6:, 2] == 50.0)            # every other cell was brought back


# =============================================================================================
# P1 (BUG) phantom_scroll.Scroll.winding(): the angle-dependent spiral irregularity is inverted by 6 fixed-point
# sweeps. The map contracts only if 2 pi dr'/dpsi / pitch < 1 with dr' <= 0.52 * irregular * pitch * ... i.e.
# irregular < ~0.3, and at 0.2-0.3 six sweeps are not enough. The winding number (winding.npy, the rendering,
# the label of every voxel) is then wrong by up to 0.4 of a sheet at irregular=0.4 with no message.
@pytest.mark.parametrize("irr", [0.12, 0.2, 0.25, 0.29])
def test_P1_winding_inverts_radius_for_every_accepted_irregularity(irr):
    sc = ps.Scroll(ps.Params(shape=(32, 128, 128), irregular=irr))
    phi = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    for w0 in (0.0, 1.0, 2.0, 3.0):
        rad = sc.radius(w0, phi)
        w, _, _ = sc.winding(np.stack([rad * np.cos(phi), rad * np.sin(phi)]))
        assert np.abs(w - w0).max() < 1e-4


@pytest.mark.parametrize("irr", [0.31, 0.4, 0.6])
def test_P1_irregularity_that_makes_the_spiral_fold_is_refused(irr):
    with pytest.raises(ValueError, match="irregular"):
        ps.Scroll(ps.Params(shape=(32, 128, 128), irregular=irr))


# P2 (NIT, comment only) Params.squash_angle says "direction that is compressed". The map A = R diag(1, s) R^T leaves
# the direction squash_angle unchanged and compresses the PERPENDICULAR. Characterisation test (passes before and after).
def test_P2_squash_compresses_the_direction_perpendicular_to_squash_angle():
    sc = ps.Scroll(ps.Params(shape=(32, 64, 64), squash=0.5, squash_angle=30.0))
    a = math.radians(30.0)
    along = sc.A @ np.array([math.cos(a), math.sin(a)])
    perp = sc.A @ np.array([-math.sin(a), math.cos(a)])
    assert np.linalg.norm(along) == pytest.approx(1.0) and np.linalg.norm(perp) == pytest.approx(0.5)


# P3 (checked, not a bug) winding.npy at the true surface of turn k is k (to voxel rounding), and the ink mask lands on
# the surface where meta/truth say (rows = z of the undeformed frame, cols = angle).
def test_P3_surface_voxels_carry_their_own_turn_label_and_ink_sits_on_the_mask():
    from scipy.ndimage import map_coordinates
    p = ps.Params(shape=(96, 96, 96), turns=3, r0=14.0, pitch=16.0, thickness=5.0, grid_step=3.0, squash=0.8, warp_amp=3.0,
                  irregular=0.05, ink=True, ink_turn=1, ink_delta=0.5, noise=0.0, texture=0.0)
    sc = ps.Scroll(p)
    mask = ps.ink_mask_image(p, sc.n_rows(), sc.n_cols())
    vol, lab = sc.render(ink_mask=mask)
    for k in range(p.turns):
        xyz = sc.turn_surface(k)
        ok = xyz[..., 0] != -1
        i = np.clip(np.rint(xyz[..., ::-1]).astype(int), 0, 95)
        assert (lab[i[..., 0], i[..., 1], i[..., 2]][ok] == k).mean() > 0.97
    xyz = sc.turn_surface(1)
    ok = xyz[..., 0] != -1
    v = map_coordinates(vol.astype(float), [xyz[..., 2], xyz[..., 1], xyz[..., 0]], order=1)
    gain = {}
    for dr in (-2, 0, 2):
        for dc in (-4, 0, 4):
            m = np.roll(np.roll(mask, dr, 0), dc, 1) > 0
            gain[(dr, dc)] = v[m & ok].mean() - v[~m & ok].mean()
    assert max(gain, key=gain.get) == (0, 0)


# =============================================================================================
# T1 (RISK -> fixed, opt-in) sheet_tracer: the orientation of the seed normal is "largest component positive", so the
# direction in which the columns run (clockwise or counter-clockwise round the scroll) depends on where the seed
# is. Two patches of the same sheet have opposite grid handedness, so the surface normal VC3D derives, and the
# layer order ink_infer reads along it, flips from patch to patch. Fix: --axis-xy X Y orients every normal away
# from the axis. Without it the tool now says so on stderr.
@pytest.fixture(scope="module")
def tr_scene():
    from test_sheet_tracer import SIZE as S
    import benchmark as bm
    p = bm.make_params("round", S, 0)
    sc = ps.Scroll(p)
    vol, _ = sc.render()
    return p, sc, vol, st.Tracer(vol, st.Params())


def column_sense(sc, vol, T, p, frac, **kw):
    tru = sc.turn_surface(1)
    nr, nc = tru.shape[:2]
    seed = tru[nr // 2, int(frac * nc)]
    res = st.trace(vol, seed, st.Params(step_vox=p.grid_step, max_rows=11, max_cols=11, **kw), tracer=T)
    P_, (r0, c0) = res["points"], res["seed_cell"]
    cen = sc.centre_line()[vol.shape[0] // 2]
    a = P_[r0, c0 + 3, :2] - P_[r0, c0 - 3, :2]
    rad = P_[r0, c0, :2] - np.array([cen[2], cen[1]])
    return np.sign(rad[0] * a[1] - rad[1] * a[0])


def test_T1_default_handedness_depends_on_the_seed_position_documented(tr_scene):
    p, sc, vol, T = tr_scene
    senses = {column_sense(sc, vol, T, p, f) for f in (0.1, 0.6)}
    assert senses == {1.0, -1.0}                  # characterisation of the old behaviour: it is the thing --axis-xy cures


def test_T1_axis_xy_gives_every_patch_the_same_handedness(tr_scene):
    p, sc, vol, T = tr_scene
    cen = sc.centre_line()[vol.shape[0] // 2]
    kw = dict(axis_xy=(float(cen[2]), float(cen[1])))
    senses = {column_sense(sc, vol, T, p, f, **kw) for f in (0.1, 0.35, 0.6, 0.85)}
    assert len(senses) == 1
