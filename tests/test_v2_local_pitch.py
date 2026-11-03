"""Brief 15 part B: local sheet spacing and confidence.

Written BEFORE the code (each test was run red against the previous behaviour, see the PR description).
Evidence for the real-data tests: tools/realdata_run/RESULTS.md (PR #17), finding F3 / "Pitch measurement".
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("tifffile")

ROOT = Path(__file__).resolve().parent.parent
for d in ("common", "sheet_spacing_check", "sheet_switch_finder", "trace_auditor", "umbilicus_finder", "phantom_scroll", "realdata_run"):
    sys.path.insert(0, str(ROOT / "tools" / d))

DATA = ROOT / "testdata" / "pherc_paris4_45um"
needs_data = pytest.mark.skipif(not DATA.is_dir(), reason="testdata/pherc_paris4_45um not present")


# ------------------------------------------------------------------ the shared module
def _sheet_tile(spacing_of_y, h=240, w=60, noise=0.02, seed=0, sig=1.6):
    """Horizontal sheets (Gaussian ridges) whose spacing is spacing_of_y(y); returns tile and the sheet positions."""
    pos, y = [], 20.0
    while y < h - 10:
        pos.append(y)
        y += spacing_of_y(y)
    img = np.zeros((h, w))
    yy = np.arange(h)[:, None]
    for c in pos:
        img += np.exp(-(yy - c) ** 2 / (2 * sig ** 2))
    return img + np.random.default_rng(seed).normal(0, noise, img.shape), np.array(pos)


def _points(ys, x=30.0):
    xy = np.stack([np.full(len(ys), x), np.asarray(ys, float)], axis=1)
    nrm = np.tile([0.0, 1.0], (len(ys), 1))
    return xy, nrm


def test_module_regular_sheets():
    import local_pitch as lp
    tile, pos = _sheet_tile(lambda y: 12.0)
    xy, nrm = _points([80, 110, 140])
    r = lp.local_pitch(tile, (0, 0), xy, nrm, 1.0, np.zeros(3, int), lp.PitchParams())
    assert np.allclose(r.pitch, 12.0, rtol=0.05)
    assert (r.confidence > 0.6).all()
    assert (r.n_peaks >= 3).all()


def test_module_follows_a_spacing_that_changes_along_the_normal():
    """Spacing 8 near the top growing to 24 at the bottom (3x): the pitch at a point is the spacing THERE."""
    import local_pitch as lp
    tile, pos = _sheet_tile(lambda y: 8.0 + 16.0 * (y - 20) / 210.0, h=260)
    gaps = np.diff(pos)
    mids = (pos[:-1] + pos[1:]) / 2
    xy, nrm = _points([60.0, 200.0])
    r = lp.local_pitch(tile, (0, 0), xy, nrm, 1.0, np.zeros(2, int), lp.PitchParams(window_pitches=2.5))
    true = [np.interp(y, mids, gaps) for y in (60.0, 200.0)]
    assert r.pitch[0] == pytest.approx(true[0], rel=0.2)
    assert r.pitch[1] == pytest.approx(true[1], rel=0.2)
    assert r.pitch[1] > 1.6 * r.pitch[0]


def test_module_confidence_low_for_noise_and_for_too_few_sheets():
    import local_pitch as lp
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 1, (240, 60))
    ys = np.linspace(80, 160, 40)
    xy, nrm = _points(ys)
    r = lp.local_pitch(noise, (0, 0), xy, nrm, 1.0, np.zeros(len(ys), int), lp.PitchParams())
    assert r.confidence.mean() < 0.25 and (r.confidence > 0.5).mean() < 0.1      # statistics over 40 points (one point can be a fluke)
    tile, pos = _sheet_tile(lambda y: 60.0, h=100)                         # exactly two sheets (y = 20, 80) in the whole tile
    assert len(pos) == 2
    xy, nrm = _points([40, 55, 70])
    r2 = lp.local_pitch(tile, (0, 0), xy, nrm, 1.0, np.zeros(3, int), lp.PitchParams())
    assert (r2.confidence == 0).all() and (r2.n_peaks < 3).all()


def test_module_irregular_sheets_have_lower_confidence_than_regular_ones():
    import local_pitch as lp
    rng = np.random.default_rng(3)
    jit = rng.uniform(0.55, 1.6, 400)
    k = {"i": 0}

    def sp(y):
        k["i"] += 1
        return 12.0 * jit[k["i"]]
    t_irr, _ = _sheet_tile(sp)
    t_reg, _ = _sheet_tile(lambda y: 12.0)
    xy, nrm = _points([110, 130, 150])
    run = np.zeros(3, int)
    c_irr = lp.local_pitch(t_irr, (0, 0), xy, nrm, 1.0, run, lp.PitchParams()).confidence.mean()
    c_reg = lp.local_pitch(t_reg, (0, 0), xy, nrm, 1.0, run, lp.PitchParams()).confidence.mean()
    assert c_irr < c_reg - 0.2


# ------------------------------------------------------------------ sheet_spacing_check
@pytest.fixture(scope="module")
def real_pair(tmp_path_factory):
    from pad_meshes import pad_pair
    import ssc_io
    a = next(DATA.glob("*w116-117.tifxyz"))
    b = next(DATA.glob("*w118-119.tifxyz"))
    out = tmp_path_factory.mktemp("pad")
    (pa, pb), _ = pad_pair(str(a), str(b), str(out))
    return ssc_io.load_mesh(pa), ssc_io.load_mesh(pb)


@needs_data
@pytest.mark.parametrize("z", [2073, 2600, 3128])
def test_ssc_real_data_pitch_matches_the_independent_measurement(real_pair, z):
    """PR #17 F3: at defaults the CT pitch came out 14-17 voxels, the independent measurement along the normals is
    9.0-9.5 (peak gaps at prominence 0.05: 9.5-10.5). The default must now land in 8.5-11.5; --global-pitch is the old value."""
    import sheet_spacing_check as S
    import ssc_io
    A, B = real_pair
    vol = ssc_io.PngVolume(str(DATA / "slices"), 45.532, 45.532)
    res, pts, ov = S.analyse_height(A, B, vol, float(z), S.Params())
    assert 8.5 <= res["ct_pitch_vox"] <= 11.5, res["ct_pitch_vox"]
    old, _, _ = S.analyse_height(A, B, vol, float(z), S.Params(global_pitch=True))
    assert 13.5 <= old["ct_pitch_vox"] <= 18.0, old["ct_pitch_vox"]


@needs_data
def test_ssc_real_data_reports_low_pitch_confidence(real_pair):
    """The real periodicity is weak and broad (autocorrelation second lobe < 0.1): the tool must say so."""
    import sheet_spacing_check as S
    import ssc_io
    A, B = real_pair
    vol = ssc_io.PngVolume(str(DATA / "slices"), 45.532, 45.532)
    res, _, _ = S.analyse_height(A, B, vol, 2600.0, S.Params())
    assert 0.0 <= res["pitch_confidence_mean"] < 0.6


# ------------------------------------------------------------------ --global-pitch reproduces the old behaviour
OLD_REFERENCE = {   # sheet_spacing_check 0.1.1 (scratch-base) on the phantom below, recorded before the change
    24.0: dict(ct_pitch_vox=13.75, clean_fraction=0.9696969696969697, shared_fraction=0.030303030303030304, median_ratio=0.9694442806067123),
    32.0: dict(ct_pitch_vox=13.875, clean_fraction=0.9696969696969697, shared_fraction=0.030303030303030304, median_ratio=0.9587552393607022),
    40.0: dict(ct_pitch_vox=13.75, clean_fraction=0.9696969696969697, shared_fraction=0.030303030303030304, median_ratio=0.968926973957182),
}


def _small_pair(tmp_path, **kw):
    import phantom_scroll as ps
    import ssc_io
    base = dict(shape=(64, 112, 112), turns=3, r0=9.0, pitch=15.0, thickness=5.0, grid_step=3.0, noise=0.03)
    base.update(kw)
    sc = ps.Scroll(ps.Params(**base))
    vol, lab = sc.render()
    for k in (1, 2):
        ps.write_tifxyz(str(tmp_path / f"t{k}"), sc.turn_surface(k), (1 / 3, 1 / 3))
    return ssc_io.load_mesh(str(tmp_path / "t1")), ssc_io.load_mesh(str(tmp_path / "t2")), ssc_io.ArrayVolume(vol), sc


def test_ssc_global_pitch_reproduces_the_old_numbers(tmp_path):
    import sheet_spacing_check as S
    A, B, V, _ = _small_pair(tmp_path, squash=0.7, warp_amp=3.0, warp_wavelength=50.0, irregular=0.08, seed=2)
    for z, ref in OLD_REFERENCE.items():
        res, _, _ = S.analyse_height(A, B, V, z, S.Params(global_pitch=True))
        for k, v in ref.items():
            assert res[k] == pytest.approx(v, rel=1e-9), (z, k)
        assert res["pitch_mode"] == "global"


def test_ssc_local_mode_true_pair_still_clean_on_the_same_phantom(tmp_path):
    import sheet_spacing_check as S
    A, B, V, _ = _small_pair(tmp_path, squash=0.7, warp_amp=3.0, warp_wavelength=50.0, irregular=0.08, seed=2)
    for z in OLD_REFERENCE:
        res, _, _ = S.analyse_height(A, B, V, z, S.Params())
        assert res["pitch_mode"] == "local" and res["clean_fraction"] >= 0.9, (z, res["clean_fraction"])
        assert res["ct_pitch_vox"] == pytest.approx(OLD_REFERENCE[z]["ct_pitch_vox"], rel=0.15)


def test_ssc_cli_global_pitch_flag(tmp_path):
    import sheet_spacing_check as S
    ap = S.build_parser()
    a = ap.parse_args(["a", "b", "--png-dir", "x", "--heights", "1", "--global-pitch"])
    assert a.global_pitch is True and ap.parse_args(["a", "b", "--png-dir", "x", "--heights", "1"]).global_pitch is False


# ------------------------------------------------------------------ sheet_switch_finder: steps in LOCAL pitches
def _spacing_phantom(ratio=3.0):
    import phantom_scroll as ps
    import ssc_io
    p = ps.Params(shape=(64, 112, 112), turns=4, r0=9.0, pitch=15.0, thickness=3.0, grid_step=3.0, noise=0.02,
                  spacing_ratio=ratio, seed=1)
    sc = ps.Scroll(p)
    vol, lab = sc.render()
    return sc, ssc_io.ArrayVolume(vol)


def _planted(sc, tmp_path, col, name):
    import phantom_scroll as ps
    import ssc_io
    xyz, t = ps.switch_trace(sc, dict(turn=1, col=col, delta=1.0, width=0, row0=0))
    ps.write_tifxyz(str(tmp_path / name), xyz, (1 / 3, 1 / 3))
    return ssc_io.load_mesh(str(tmp_path / name))


@pytest.fixture(scope="module")
def spacing_world(tmp_path_factory):
    sc, vol = _spacing_phantom()
    tmp = tmp_path_factory.mktemp("sw")
    phis = np.arange(sc.n_cols()) * 2 * np.pi / sc.n_cols()
    f = sc.spacing_factor(phis, sc.zc)
    cols = dict(compressed=int(np.argmin(f)), wide=int(np.argmax(f)))
    return sc, vol, {k: (c, _planted(sc, tmp, c, k)) for k, c in cols.items()}, f


@pytest.mark.parametrize("which", ["compressed", "wide"])
def test_ssf_step_is_one_local_pitch_wherever_the_spacing_is(spacing_world, which):
    """Spacing varies 3x round the turn. A planted +1 sheet switch is one LOCAL pitch whether the sheets are crushed or wide;
    in units of one pitch per height it is 0.35 (missed) in the crushed sector and 1.6 (confidence 0) in the wide one."""
    import sheet_switch_finder as F
    sc, vol, planted, f = spacing_world
    col, mesh = planted[which]
    rec, sw, st = F.analyse_height(mesh, vol, 32.0, F.Params(vertical=0))
    near = [s for s in sw if abs(s["col"] - col) <= 3]
    assert len(near) == 1, [(s["col"], s["step"]) for s in sw]
    assert near[0]["step"] == pytest.approx(1.0, abs=0.2) and near[0]["confidence"] >= 0.3
    assert near[0]["direction"] == "outward" and near[0]["n_sheets"] == 1


def test_ssf_global_pitch_is_the_old_behaviour(spacing_world):
    """--global-pitch: one pitch per height; the same two planted switches are missed / mis-measured (recorded from 0.1.0)."""
    import sheet_switch_finder as F
    sc, vol, planted, f = spacing_world
    col, mesh = planted["compressed"]
    rec, sw, st = F.analyse_height(mesh, vol, 32.0, F.Params(vertical=0, global_pitch=True))
    assert rec["pitch_mode"] == "global" and not [s for s in sw if abs(s["col"] - col) <= 3]       # missed
    col, mesh = planted["wide"]
    rec, sw, st = F.analyse_height(mesh, vol, 32.0, F.Params(vertical=0, global_pitch=True))
    near = [s for s in sw if abs(s["col"] - col) <= 3]
    assert len(near) == 1 and near[0]["step"] == pytest.approx(1.59, abs=0.05) and near[0]["confidence"] < 0.05


def test_ssf_true_trace_has_no_switch_when_the_spacing_varies(spacing_world, tmp_path):
    import phantom_scroll as ps
    import sheet_switch_finder as F
    import ssc_io
    sc, vol, planted, f = spacing_world
    ps.write_tifxyz(str(tmp_path / "t1"), sc.turn_surface(1), (1 / 3, 1 / 3))
    rec, sw, st = F.analyse_height(ssc_io.load_mesh(str(tmp_path / "t1")), vol, 32.0, F.Params(vertical=0))
    assert not [s for s in sw if s["confidence"] >= 0.3]


@needs_data
@pytest.mark.xfail(strict=False, reason="PR #17 finding 5 NOT fixed by local pitch: on the real broken copy the finder reports a "
                                         "break-specific entry (z=2600 col 123, step 2.35) but at confidence 0.0, below the 0.3 that counts")
def test_ssf_real_break_is_flagged_and_the_original_is_not(tmp_path):
    import glob
    import sheet_switch_finder as F
    import ssc_io
    from task6_break import make_broken
    bro, _ = make_broken(str(tmp_path), 120, 9.5)
    orig = ssc_io.load_mesh(glob.glob(str(DATA / "*w116-117.tifxyz"))[0])
    vol = ssc_io.PngVolume(str(DATA / "slices"), 45.532, 45.532)
    hit_b, hit_o = [], []
    for z in (2073.0, 2600.0, 3128.0):
        for mesh, hits in ((ssc_io.load_mesh(bro), hit_b), (orig, hit_o)):
            rec, sw, st = F.analyse_height(mesh, vol, z, F.Params(vertical=0))
            hits += [s for s in sw if abs(s["col"] - 120) <= 6 and s["confidence"] >= 0.3]
    assert hit_b and not hit_o


# ------------------------------------------------------------------ trace_auditor: confidence, NOT JUDGED, judged fraction
def _truth_centre(sc):
    import trace_auditor as ta
    cl = sc.centre_line()                                   # rows (z, y, x) of the deformed axis
    return ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf)


def _audit(meshes, vol, centre, heights, **kw):
    import trace_auditor as ta
    p = ta.Params(**kw)
    return ta.audit(meshes, vol, heights, centre, p, ta.ssf.Params(vertical=1), ta.ssc.Params())


def _check(trace, name):
    return next(c for c in trace["checks"] if c["check"] == name)


def test_auditor_judged_fraction_and_pass_on_a_clean_phantom_trace(tmp_path):
    A, B, vol, sc = _small_pair(tmp_path, seed=3)
    rep = _audit([A], vol, _truth_centre(sc), [24.0, 32.0, 40.0])
    t = rep["traces"][0]
    assert t["judged_fraction"] >= 0.9, t.get("judged_fraction")
    assert t["verdict"] == "PASS", t["reasons"]


def test_auditor_still_fails_a_planted_switch_in_a_judged_region(tmp_path):
    import phantom_scroll as ps
    import ssc_io
    A, B, vol, sc = _small_pair(tmp_path, seed=3)
    xyz, _ = ps.switch_trace(sc, dict(turn=1, col=int(0.4 * sc.n_cols()), delta=1.0, width=0, row0=0))
    ps.write_tifxyz(str(tmp_path / "sw"), xyz, (1 / 3, 1 / 3))
    rep = _audit([ssc_io.load_mesh(str(tmp_path / "sw"))], vol, _truth_centre(sc), [24.0, 32.0, 40.0])
    t = rep["traces"][0]
    assert t["verdict"] == "FAIL" and _check(t, "switch_finder")["status"] == "FAIL"
    assert t["judged_fraction"] >= 0.8


def test_auditor_does_not_judge_a_crushed_region_and_says_how_much_it_judged(tmp_path):
    """Spacing varies 3x and sheets overlap in the compressed sector: the local pitch there is not measurable. The true trace
    must not be FAILed (or PASSed) on ground that was not judged."""
    A, B, vol, sc = _small_pair(tmp_path, seed=3, spacing_ratio=3.0, squash=0.6, thickness=4.5)
    rep = _audit([A], vol, _truth_centre(sc), [24.0, 32.0, 40.0])
    t = rep["traces"][0]
    assert 0.0 <= t["judged_fraction"] < 0.9
    assert t["verdict"] != "FAIL", t["reasons"]


@needs_data
def test_auditor_real_unbroken_mesh_is_not_judged_not_failed():
    """PR #17 finding 6 / P5: the auditor FAILED everything, the unbroken original included (112 radius 'jumps', 5 switches),
    at pitch 17 vox and a centre from a LOW-confidence finder. The real periodicity is weak: the pitch is not trustworthy there
    and a FAIL carries no information. Expected now: NOT JUDGED with a small judged fraction; --global-pitch is the old FAIL."""
    import glob
    import json
    import trace_auditor as ta
    import ssc_io
    A = ssc_io.load_mesh(glob.glob(str(DATA / "*w116-117.tifxyz"))[0])
    vol = ssc_io.PngVolume(str(DATA / "slices"), 45.532, 45.532)
    cp = json.load(open(ROOT / "tools" / "realdata_run" / "out" / "umbilicus_estimated.json"))["control_points"]
    centre = ta.Centre(*(np.array([c[k] for c in cp], float) for k in ("z", "y", "x")), "estimated", np.inf)
    heights = [2073.0, 2600.0, 3128.0]
    new = _audit([A], vol, centre, heights)["traces"][0]
    assert new["verdict"] == "NOT JUDGED" and new["judged_fraction"] < 0.25, (new["verdict"], new["judged_fraction"])
    old = _audit([A], vol, centre, heights, global_pitch=True)["traces"][0]
    assert old["verdict"] == "FAIL"


# ------------------------------------------------------------------ umbilicus_finder: wider structure-tensor window where coherence is low
def _noisy_rings(noise_right=1.5, n=400, cx=205.0, cy=190.0, seed=0):
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(xx - cx, yy - cy)
    d = (r - 60 + 6.0) % 12.0 - 6.0
    img = np.exp(-d ** 2 / (2 * 1.6 ** 2)) * (r < 170) * (r > 40)
    rng = np.random.default_rng(seed)
    noise = np.where(xx > cx, rng.normal(0, noise_right, img.shape), rng.normal(0, 0.3, img.shape))
    return img + noise, xx > cx, (cx, cy)


def test_uf_widening_raises_coherence_only_where_it_was_low():
    import umbilicus_finder as uf
    img, right, _ = _noisy_rings(2.5)
    p = uf.Params()
    nx0, ny0, c0, e0 = uf.structure_tensor(img, p.sigma_grad, p.sigma_int)
    nx1, ny1, c1, e1 = uf.structure_tensor_adaptive(img, p.sigma_grad, p.sigma_int, p.coherence_min, 2.0, 2)
    ok = c0 >= p.coherence_min
    assert (c1[ok] == c0[ok]).all() and (nx1[ok] == nx0[ok]).all()           # untouched where the base window was already coherent
    low = ~ok
    assert c1[low].mean() > c0[low].mean() + 0.05                              # raised where it was low
    assert (c1 >= c0).all()                                                    # and never lowered


def test_uf_widen_flag_is_off_by_default_and_changes_nothing_then():
    import umbilicus_finder as uf
    img, right, (cx, cy) = _noisy_rings(1.5)
    base = uf.analyse_slice(img, uf.Params(target_px=400, pitch_vox=12.0))
    off = uf.analyse_slice(img, uf.Params(target_px=400, pitch_vox=12.0, widen_low_coherence=False))
    assert (base.cx, base.cy, base.n_votes) == (off.cx, off.cy, off.n_votes)
    assert uf.Params().widen_low_coherence is False
    a = uf.build_parser().parse_args(["in", "--out-dir", "o", "--widen-low-coherence"])
    assert a.widen_low_coherence is True and uf.build_parser().parse_args(["in", "--out-dir", "o"]).widen_low_coherence is False


def test_uf_widening_keeps_votes_and_does_not_move_the_centre_on_noisy_rings():
    import umbilicus_finder as uf
    img, right, (cx, cy) = _noisy_rings(1.5)
    off = uf.analyse_slice(img, uf.Params(target_px=400, pitch_vox=12.0))
    on = uf.analyse_slice(img, uf.Params(target_px=400, pitch_vox=12.0, widen_low_coherence=True))
    assert on.n_votes >= off.n_votes
    assert np.hypot(on.cx - cx, on.cy - cy) <= np.hypot(off.cx - cx, off.cy - cy) + 0.5
