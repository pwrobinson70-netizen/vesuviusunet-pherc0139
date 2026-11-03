"""Tests for phantom_scroll v0.2: folds, delamination, tears, gaps, a local-spacing field, severity map, presets.

Every new feature is OFF by default; test_defaults_unchanged pins that. Small phantoms only (64 x 112 x 112)."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "phantom_scroll"))

import phantom_scroll as ps  # noqa: E402
from scipy.ndimage import map_coordinates  # noqa: E402

SHAPE = (64, 112, 112)
BASE = dict(shape=SHAPE, turns=3, r0=9.0, pitch=15.0, thickness=5.0, grid_step=3.0, noise=0.03)
FEATS = {
    "fold": dict(kind="fold", turn=1, phi=180.0, z=32.0, len=30.0, zlen=36.0, amount=3.0, h=6.5),
    "delam": dict(kind="delam", turn=1, phi=180.0, z=32.0, len=30.0, zlen=36.0, h=7.0),
    "tear": dict(kind="tear", turn=1, phi=180.0, z=32.0, len=30.0, zlen=36.0, gap=8.0, off=5.0),
    "gap": dict(kind="gap", turn=1, phi=180.0, z=32.0, len=30.0, zlen=36.0),
}


def params(**kw):
    d = dict(BASE)
    d.update(kw)
    return ps.Params(**d)


def feat_params(kind, **kw):
    return params(features=(FEATS[kind],), **kw)


def vals(vol, xyz):
    ok = xyz[..., 0] != -1
    pts = xyz[ok]
    return map_coordinates(vol.astype(np.float32) / 255.0, [pts[:, 2], pts[:, 1], pts[:, 0]], order=1), ok


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    res = {}
    for kind in FEATS:
        out = tmp_path_factory.mktemp(kind)
        sc, vol, lab, truth = ps.build(feat_params(kind), str(out), zarr=False)
        res[kind] = (out, sc, vol, lab, np.load(out / "severity.npy"))
    return res


# ---------------------------------------------------------------- defaults unchanged
def test_defaults_unchanged(tmp_path):
    """No v0.2 flag: no severity file, no feature, spacing factor exactly 1, severity (if forced) all zero for an undeformed phantom."""
    p = params()
    assert p.features == () and p.spacing_ratio == 1.0
    sc, vol, lab, truth = ps.build(p, str(tmp_path / "a"), zarr=False)
    assert not (tmp_path / "a" / "severity.npy").exists()
    assert (sc.spacing_factor(np.linspace(0, 6, 7), 10.0) == 1.0).all()
    # forcing the severity map on an undeformed, feature-free phantom gives an all-zero map and the same volume
    sc2, vol2, lab2, _ = ps.build(p, str(tmp_path / "b"), zarr=False, severity=True)
    sev = np.load(tmp_path / "b" / "severity.npy")
    assert (vol2 == vol).all() and (lab2 == lab).all()
    assert sev.shape == vol.shape and sev.dtype == np.float32 and sev.max() == 0.0


def test_old_presets_keep_their_parameters():
    pytest.importorskip("zarr")
    for d in ("sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder"):
        sys.path.insert(0, str(ROOT / "tools" / d))
    import benchmark as bm  # noqa: E402  (tools/phantom_scroll/benchmark.py)
    assert bm.PRESETS["bad"] == dict(squash=0.55, squash_angle=30.0, warp_amp=7.0, irregular=0.12, tilt=(0.10, -0.08))
    assert bm.PRESETS["mild"]["squash"] == 0.85 and bm.PRESETS["round"] == {}
    a, b = ps.make_params("crushed", 96, 3), ps.make_params("bad", 96, 3)
    assert a == b
    assert ps.make_params("merged", 100, 0).merge_sigma == pytest.approx(9.0)


@pytest.mark.parametrize("name", ["round", "mild", "crushed", "merged", "folded", "delaminated", "torn", "gappy", "crushed-hard"])
def test_every_preset_builds_and_renders_a_slice(name):
    p = ps.make_params(name, 64, 0)
    sc = ps.Scroll(p)
    v, lab, sev = sc.render_slab(32, 33, severity=True)
    assert v.shape == (1, 64, 64) and lab.shape == (1, 64, 64) and sev.shape == (1, 64, 64)
    assert 0.0 <= sev.min() and sev.max() <= 1.0
    assert (lab >= 0).any()


def test_unknown_preset_and_bad_specs():
    with pytest.raises(ValueError):
        ps.make_params("nope")
    with pytest.raises(ValueError):
        ps.parse_feature("wrinkle", "turn=1")
    with pytest.raises(ValueError):
        ps.parse_feature("fold", "bogus=1")
    with pytest.raises(ValueError):                                   # window too close to the angle-0 seam
        ps.Scroll(params(features=(dict(FEATS["fold"], phi=350.0),)))
    with pytest.raises(ValueError):                                   # radial size above 0.45 pitch
        ps.Scroll(params(features=(dict(FEATS["tear"], off=9.0),)))
    with pytest.raises(ValueError):
        ps.Scroll(params(spacing_ratio=0.5))


# ---------------------------------------------------------------- shapes, determinism
@pytest.mark.parametrize("kind", list(FEATS))
def test_shapes_and_determinism(kind, built, tmp_path):
    out, sc, vol, lab, sev = built[kind]
    assert vol.shape == SHAPE and lab.shape == SHAPE and sev.shape == SHAPE
    assert sev.dtype == np.float32 and 0.0 <= sev.min() and sev.max() > 0.95
    sc2, vol2, lab2, _ = ps.build(feat_params(kind), str(tmp_path / "again"), zarr=False)
    assert (vol2 == vol).all() and (lab2 == lab).all()
    assert (np.load(tmp_path / "again" / "severity.npy") == sev).all()
    assert (sc2.turn_surface(1) == sc.turn_surface(1)).all()
    t = json.loads((out / "truth.json").read_text())
    assert t["params"]["features"][0]["kind"] == kind


def test_labels_unchanged_by_features(built):
    """A feature never changes which sheet a voxel belongs to: the winding volume equals the feature-free one wherever the nearest
    sheet is the same, which for features of < 0.45 pitch is everywhere inside the scroll."""
    base = ps.Scroll(params()).render()[1]
    for kind, (out, sc, vol, lab, sev) in built.items():
        assert (lab == base).mean() > 0.999, kind


# ---------------------------------------------------------------- severity map
@pytest.mark.parametrize("kind", list(FEATS))
def test_severity_zero_where_nothing_was_applied(kind, built):
    out, sc, vol, lab, sev = built[kind]
    f = FEATS[kind]
    zz = np.arange(SHAPE[0])[:, None, None] * np.ones(SHAPE)
    assert (sev[np.abs(zz - f["z"]) >= f["zlen"] / 2] == 0).all()        # outside the z window: exactly 0
    assert (sev[lab != 1] == 0).all()                                    # only the affected sheet (and not air) is marked
    assert (sev > 0).mean() < 0.05 and (sev > 0.5).any()
    # the maximum sits at the window centre
    z, y, x = np.unravel_index(np.argmax(sev), sev.shape)
    assert abs(z - f["z"]) <= 3


def test_severity_follows_squash_and_is_zero_for_untouched(tmp_path):
    sc = ps.Scroll(params(squash=0.5, squash_angle=0.0))
    v, lab, sev = sc.render_slab(32, 33, severity=True)
    s = sev[0]
    inside = lab[0] >= 0
    assert (s[~inside] == 0).all()
    # squash_angle 0: x is untouched, y compressed to 0.5 => severity ln(2)/ln(4) = 0.5 along +-y, 0 along +-x
    cy, cx = 55.5, 55.5
    ax = np.abs(np.arange(112) - 55.5)
    on_x = inside & (np.abs(np.arange(112)[:, None] - cy) < 2) & (ax[None, :] > 14)        # (away from the axis, where the radial direction is undefined)
    on_y = inside & (np.abs(np.arange(112)[None, :] - cx) < 2) & (ax[:, None] > 14)
    assert s[on_x].max() < 0.1
    assert s[on_y].max() == pytest.approx(0.5, abs=0.05)


# ---------------------------------------------------------------- truth sits on the sheets
@pytest.mark.parametrize("kind", ["fold", "tear", "gap", "delam"])
def test_truth_surfaces_sit_on_bright_sheets_where_untouched(kind, built):
    out, sc, vol, lab, sev = built[kind]
    papyrus = 0.8
    for k in range(3):
        xyz = sc.turn_surface(k)
        v, ok = vals(vol, xyz)
        s, _ = vals(np.rint(sev * 255).astype(np.uint8), xyz)               # severity at the same points (x 1)
        untouched = s < 1e-3
        assert untouched.sum() > 100
        assert v[untouched].mean() > 0.85 * papyrus, (kind, k, v[untouched].mean())
        assert np.percentile(v[untouched], 5) > 0.55 * papyrus


def test_fold_truth_is_bright_inside_the_window_and_doubles_back(built):
    out, sc, vol, lab, sev = built["fold"]
    xyz = sc.turn_surface(1)
    v, ok = vals(vol, xyz)
    row = int(round(FEATS["fold"]["z"] / BASE["grid_step"]))
    r = xyz[row]
    cx, cy = (SHAPE[2] / 2 - 0.5), (SHAPE[1] / 2 - 0.5)
    ang = np.unwrap(np.arctan2(r[:, 1] - cy, r[:, 0] - cx))
    assert (np.diff(ang) < 0).any(), "the cut line of a folded sheet must go backwards in angle somewhere"
    vv = map_coordinates(vol.astype(np.float32) / 255.0, [np.full(len(r), FEATS["fold"]["z"]), r[:, 1], r[:, 0]], order=1)
    assert np.median(vv[np.abs(np.diff(ang, prepend=ang[0])) > 0]) > 0.5          # the folded sheet is real and bright
    # a pleat puts MORE sheet into the same place: papyrus mass in a box around the fold exceeds the unfolded phantom's
    thin = dict(thickness=2.5)
    vol_f = ps.Scroll(feat_params("fold", **thin)).render()[0].astype(float) / 255.0
    vol_0 = ps.Scroll(params(**thin)).render()[0].astype(float) / 255.0
    R0 = 9.0 + 15.0 * 1.5
    bx, by = cx + R0 * math.cos(ang0 := math.radians(FEATS["fold"]["phi"])), cy + R0 * math.sin(ang0)
    z0 = int(FEATS["fold"]["z"])
    sl = (slice(z0 - 3, z0 + 4), slice(int(by) - 18, int(by) + 19), slice(int(bx) - 18, int(bx) + 19))
    mass = lambda v: (v[sl] - 0.06).clip(0).sum()
    assert mass(vol_f) > 1.04 * mass(vol_0)
    far = (slice(z0 - 3, z0 + 4), slice(0, 112), slice(70, 112))                # nothing changed far from the fold
    assert np.allclose(vol_f[far], vol_0[far], atol=0.0)


def test_delam_has_two_layers_and_gap_has_none(built):
    from scipy.signal import find_peaks
    cx = cy = SHAPE[2] / 2 - 0.5
    f = FEATS["delam"]
    ang0 = math.radians(f["phi"])
    rr = np.arange(14, 50, 0.25)

    def profile(vol, z=f["z"]):
        px, py = cx + rr * np.cos(ang0), cy + rr * np.sin(ang0)
        return map_coordinates(vol.astype(np.float32) / 255.0, [np.full(rr.shape, z), py, px], order=1)

    vol_d = built["delam"][2]
    vol_0 = ps.Scroll(params()).render()[0]
    pk_d, _ = find_peaks(profile(vol_d), prominence=0.25)
    pk_0, _ = find_peaks(profile(vol_0), prominence=0.25)
    assert len(pk_d) == len(pk_0) + 1                                        # exactly one sheet became two layers
    # the gap phantom: the sheet is missing at the window centre, present far from it
    vol_g = built["gap"][2]
    xyz = built["gap"][1].turn_surface(1)
    row_in = int(round(FEATS["gap"]["z"] / BASE["grid_step"]))
    col_in = int(round(FEATS["gap"]["phi"] / 360 * xyz.shape[1]))
    p_in = xyz[row_in, col_in]
    v_in = map_coordinates(vol_g.astype(np.float32) / 255.0, [[p_in[2]], [p_in[1]], [p_in[0]]], order=1)[0]
    assert v_in < 0.35 * 0.8
    p_out = xyz[row_in, int(round(0.7 * xyz.shape[1]))]
    assert map_coordinates(vol_g.astype(np.float32) / 255.0, [[p_out[2]], [p_out[1]], [p_out[0]]], order=1)[0] > 0.5


def test_tear_leaves_a_missing_stretch_and_an_offset(built):
    out, sc, vol, lab, sev = built["tear"]
    xyz = sc.turn_surface(1)
    ref = ps.Scroll(params()).turn_surface(1)
    row = int(round(FEATS["tear"]["z"] / BASE["grid_step"]))
    d = np.linalg.norm(xyz[row] - ref[row], axis=1)
    assert d.max() == pytest.approx(FEATS["tear"]["off"], abs=1.0)              # the restart is offset by `off`
    nc = xyz.shape[1]
    c0 = int(round(FEATS["tear"]["phi"] / 360 * nc))
    v = map_coordinates(vol.astype(np.float32) / 255.0, [np.full(nc, FEATS["tear"]["z"]), xyz[row][:, 1], xyz[row][:, 0]], order=1)
    assert v[c0 - 12] > 0.5 * 0.8 and v[c0 + 8] > 0.5 * 0.8                      # both ends are real sheet
    assert v[c0 - 1: c0 + 2].min() < 0.4 * 0.8                                  # the missing stretch is dark


# ---------------------------------------------------------------- local spacing field
def test_spacing_field_range_and_truth_spacing():
    p = params(spacing_ratio=2.5)
    sc = ps.Scroll(p)
    phi = np.linspace(0, 2 * math.pi, 2001)
    f = sc.spacing_factor(phi, sc.zc)
    assert f.max() / f.min() == pytest.approx(2.5, rel=1e-3)
    assert f.max() <= 1.0 + 1e-9 and f.min() >= 1 / 2.5 - 1e-9
    # the spacing between truth traces of neighbouring turns varies by the same factor within one slice
    a, b = sc.turn_surface(1), sc.turn_surface(2)
    row = a.shape[0] // 2
    ok = (a[row, :, 0] != -1) & (b[row, :, 0] != -1)
    d = np.linalg.norm(a[row][ok] - b[row][ok], axis=1)
    assert d.max() / d.min() == pytest.approx(2.5, rel=0.25)
    assert d.max() / d.min() > 1.9


def test_spacing_field_forward_inverse_round_trip():
    sc = ps.Scroll(params(spacing_ratio=2.5, squash=0.7, warp_amp=3.0, warp_wavelength=50.0))
    rng = np.random.default_rng(0)
    q = np.stack([rng.uniform(10, 50, 200), rng.uniform(30, 80, 200), rng.uniform(30, 80, 200)])
    assert np.abs(sc.inverse(sc.forward(q)) - q).max() < 1e-3


def test_spacing_field_truth_on_sheets_and_severity(tmp_path):
    p = params(spacing_ratio=2.5, thickness=3.0)
    sc, vol, lab, truth = ps.build(p, str(tmp_path), zarr=False)
    sev = np.load(tmp_path / "severity.npy")
    for k in range(3):
        v, ok = vals(vol, sc.turn_surface(k))
        assert v.mean() > 0.7 * 0.8
    assert sev.max() > 0.5                                                  # ln(2.5)/ln(4) = 0.66 at the strongest compression
    assert (sev[lab < 0] == 0).all()


# ---------------------------------------------------------------- CLI
def test_cli_flags_and_preset(tmp_path, capsys):
    rc = ps.main(["--out", str(tmp_path / "o"), "--shape", "48", "96", "96", "--turns", "3", "--r0", "8", "--pitch", "14",
                  "--no-zarr", "--fold", "turn=1,phi=180,z=24,len=24,zlen=30", "--gap", "turn=2,phi=100,z=24,len=20,zlen=24",
                  "--spacing-ratio", "1.5"])
    assert rc == 0
    t = json.loads((tmp_path / "o" / "truth.json").read_text())
    assert [f["kind"] for f in t["params"]["features"]] == ["fold", "gap"] and t["params"]["spacing_ratio"] == 1.5
    assert (tmp_path / "o" / "severity.npy").exists()
    assert ps.main(["--out", str(tmp_path / "p"), "--preset", "folded", "--size", "48", "--no-zarr"]) == 0
    t = json.loads((tmp_path / "p" / "truth.json").read_text())
    assert len(t["params"]["features"]) == 2 and t["params"]["squash"] == 0.85
    assert ps.main(["--out", str(tmp_path / "q"), "--fold", "turn=1,phi=355,z=24", "--shape", "48", "96", "96", "--no-zarr"]) == 2
    assert ps.main(["--out", str(tmp_path / "r"), "--preset", "round", "--size", "48", "--no-zarr", "--severity"]) == 0
    assert np.load(tmp_path / "r" / "severity.npy").max() == 0.0
