"""Tests for tools/label_drift on tools/phantom_scroll phantoms (synthetic; the one real-data test is a smoke test only)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("zarr")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parent.parent
for sub in ("phantom_scroll", "label_drift"):
    sys.path.insert(0, str(ROOT / "tools" / sub))

import label_drift as ld  # noqa: E402
import phantom_scroll as ps  # noqa: E402
from ssc_io import ArrayVolume, InputError, build_mesh, load_mesh  # noqa: E402

PITCH, THICK, STEP = 15.0, 5.0, 3.0
P = ld.Params()


@pytest.fixture(scope="module")
def ph(tmp_path_factory):
    out = tmp_path_factory.mktemp("ld_phantom")
    p = ps.Params(shape=(64, 112, 112), turns=3, r0=9.0, pitch=PITCH, thickness=THICK, grid_step=STEP, noise=0.03, ink=True)
    sc, vol, lab, truth = ps.build(p, str(out))
    return out, sc, vol


def mesh_of(xyz):
    xyz = np.asarray(xyz, float)
    return build_mesh("t", xyz[..., 0], xyz[..., 1], xyz[..., 2], {"scale": [1 / STEP, 1 / STEP]})


def rect(sc, r0, r1, c0, c1):
    m = np.zeros((sc.n_rows(), sc.n_cols()), np.uint8)
    m[r0:r1, c0:c1] = 1
    return m


def two_labels(sc):
    return rect(sc, 6, 16, 8, 24) | (rect(sc, 6, 16, 40, 56) * 2)


def table(ph, w, label, **kw):
    out, sc, vol = ph
    _, _, tab = ld.run(mesh_of(sc.trace(w)), label, ArrayVolume(vol), ld.Params(**kw))
    return tab


def normals_independent(xyz):
    """Unit d/drow x d/dcol, computed here with np.gradient (independent of the tool's own code)."""
    g0, g1 = np.gradient(xyz, axis=0), np.gradient(xyz, axis=1)
    n = np.cross(g0, g1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


# ------------------------------------------------------------------ reuse
def test_reuses_the_shared_pitch_code_and_the_spacing_tool():
    assert Path(ld.lpm.__file__).resolve() == (ROOT / "tools" / "common" / "local_pitch.py").resolve()
    assert Path(ld.ssc.__file__).resolve().parent.name == "sheet_spacing_check"
    # defaults of the shared settings are the spacing tool's
    d = ld.ssc.Params()
    assert (P.onsheet_radius_px, P.pitch_prominence_frac, P.peak_prominence_frac) == (
        d.onsheet_radius_px, d.pitch_prominence_frac, d.peak_prominence_frac)


# ------------------------------------------------------------------ the three phantom cases
def test_label_on_the_true_surface_reads_ok_with_zero_drift(ph):
    _, sc, _ = ph
    tab = table(ph, 1.0, two_labels(sc))
    assert [t["verdict"] for t in tab] == ["OK", "OK"]
    for t in tab:
        assert t["n_measured"] == t["n_pixels"] == 160
        assert abs(t["mean_drift_pitch"]) < 0.05 and t["max_abs_drift_pitch"] < 0.1
        assert t["off_sheet_fraction"] == 0.0
        assert abs(t["median_pitch_vox"] - PITCH) < 1.0
        assert abs(t["mean_thickness_vox"] - THICK) < 0.5          # sheet FWHM of the phantom, smoothing removed


@pytest.mark.parametrize("w, sign", [(1.3, +1), (0.7, -1)])
def test_shifted_surface_reads_shifted_with_the_right_offset(ph, w, sign):
    _, sc, _ = ph
    true, shifted = sc.trace(1.0), sc.trace(w)
    # the offset the tool should recommend = minus the shift of the surface along the normal, in pitches
    n = normals_independent(true)
    expected = -np.sum((shifted - true) * n, axis=-1) / PITCH
    label = two_labels(sc)
    _, _, tab = ld.run(mesh_of(shifted), label, ArrayVolume(ph[2]), P)
    for t, v in zip(tab, (1, 2)):
        assert t["verdict"] == "SHIFTED"
        e = np.median(expected[label == v])
        assert abs(e) == pytest.approx(0.3, abs=0.02)
        assert abs(t["recommended_offset_pitch"] - e) < 0.1
        assert abs(t["recommended_offset_vox"] - e * PITCH) < 0.1 * PITCH
        assert np.sign(t["recommended_offset_pitch"]) == np.sign(e)


def test_label_beyond_a_planted_switch_reads_off_sheet(ph):
    _, sc, _ = ph
    # the trace follows turn 1 up to column 32, then drifts half a pitch into the gap between sheets
    xyz, _ = ps.switch_trace(sc, ps.parse_switch("turn=1,col=32,delta=0.5"))
    label = two_labels(sc)                                # component 1: cols 8-23 (before), 2: cols 40-55 (beyond)
    _, _, tab = ld.run(mesh_of(xyz), label, ArrayVolume(ph[2]), P)
    assert tab[0]["verdict"] == "OK" and tab[0]["off_sheet_fraction"] == 0.0
    assert tab[1]["verdict"] == "OFF-SHEET" and tab[1]["off_sheet_fraction"] > 0.9
    assert abs(tab[1]["recommended_offset_pitch"]) > 0.4


def test_label_spanning_the_switch_reads_mixed(ph):
    _, sc, _ = ph
    xyz, _ = ps.switch_trace(sc, ps.parse_switch("turn=1,col=32,delta=0.5"))
    label = rect(sc, 6, 16, 16, 44)                      # 16 columns before the switch, 12 beyond
    _, _, tab = ld.run(mesh_of(xyz), label, ArrayVolume(ph[2]), P)
    assert tab[0]["verdict"] == "MIXED"
    assert 0.2 < tab[0]["off_sheet_fraction"] < 0.5


def test_known_limit_a_whole_sheet_switch_is_not_a_drift(ph):
    """A trace that jumps a whole sheet lies ON a sheet: drift ~0, OK. Finding that is sheet_switch_finder's job."""
    _, sc, _ = ph
    xyz, _ = ps.switch_trace(sc, ps.parse_switch("turn=1,col=32,delta=1"))
    _, _, tab = ld.run(mesh_of(xyz), two_labels(sc), ArrayVolume(ph[2]), P)
    assert tab[1]["verdict"] == "OK" and abs(tab[1]["mean_drift_pitch"]) < 0.05


# ------------------------------------------------------------------ the corrected surface
def run_cli(args):
    return ld.main([str(a) for a in args])


def test_corrected_surface_lands_on_the_sheet_and_passes_trace_auditor(ph, tmp_path):
    out, sc, vol = ph
    shifted = tmp_path / "shifted"
    ps.write_tifxyz(str(shifted), sc.trace(1.3), (1 / STEP, 1 / STEP))
    full = (np.isfinite(load_mesh(shifted).z)).astype(np.uint8)
    lab = tmp_path / "all.npy"
    np.save(lab, full)
    before = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in shifted.iterdir()}
    fixed = tmp_path / "fixed"
    rc = run_cli([shifted, lab, "--zarr", out / "volume.zarr", "--out-dir", tmp_path / "o", "--write-corrected", fixed])
    assert rc == 0
    assert {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in shifted.iterdir()} == before   # input untouched
    a, b = load_mesh(fixed), load_mesh(out / "surfaces" / "turn_01")
    ok = a.valid & b.valid
    err = np.hypot(a.x - b.x, a.y - b.y)[ok]
    assert np.median(err) < 0.1 * PITCH and np.percentile(err, 90) < 0.2 * PITCH
    assert json.loads((fixed / "meta.json").read_text())["label_drift"]["nodes_moved"] > 0

    def audit(d):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "trace_auditor" / "trace_auditor.py"), str(d), "--zarr",
                            str(out / "volume.zarr"), "--umbilicus", str(out / "centreline_villa.json"), "--out-dir",
                            str(tmp_path / ("aud_" + d.name))], capture_output=True, text=True)
        return r.returncode, r.stdout

    assert audit(fixed)[0] == 0, audit(fixed)[1]            # PASS
    assert audit(shifted)[0] != 0                           # the uncorrected shifted trace is NOT JUDGED
    # after correction the label reads OK
    rc = run_cli([fixed, lab, "--zarr", out / "volume.zarr", "--out-dir", tmp_path / "o2"])
    assert rc == 0 and "OK" in (tmp_path / "o2" / "summary.txt").read_text().split("verdicts:")[1]


def test_write_corrected_never_overwrites(ph, tmp_path, capsys):
    out, sc, _ = ph
    surf = out / "surfaces" / "turn_01"
    lab = tmp_path / "l.npy"
    np.save(lab, rect(sc, 6, 16, 8, 24))
    base = [surf, lab, "--zarr", out / "volume.zarr", "--out-dir", tmp_path / "o"]
    assert run_cli(base + ["--write-corrected", surf]) == 2                        # the input folder itself
    full = tmp_path / "full"
    full.mkdir()
    (full / "keep.txt").write_text("x")
    assert run_cli(base + ["--write-corrected", full]) == 2                        # a non-empty folder
    assert (full / "keep.txt").read_text() == "x" and not (full / "x.tif").exists()
    assert "error:" in capsys.readouterr().err


# ------------------------------------------------------------------ outputs and determinism
def test_outputs_and_determinism(ph, tmp_path):
    out, sc, _ = ph
    surf = out / "surfaces" / "turn_01"
    lab = tmp_path / "l.npy"
    np.save(lab, two_labels(sc))
    for k in ("a", "b"):
        assert run_cli([surf, lab, "--zarr", out / "volume.zarr", "--out-dir", tmp_path / k, "--png-scale", 3]) == 0
    a, b = tmp_path / "a", tmp_path / "b"
    assert sorted(f.name for f in a.iterdir()) == ["components.csv", "drift.npz", "drift.png", "report.json", "summary.txt"]
    for f in ("components.csv", "drift.png", "report.json", "summary.txt"):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f
    na, nb = np.load(a / "drift.npz"), np.load(b / "drift.npz")          # (zip members carry timestamps: compare arrays)
    assert sorted(na.files) == sorted(nb.files)
    for k in na.files:
        np.testing.assert_array_equal(na[k], nb[k])
    assert na["drift_vox"].shape == (sc.n_rows(), sc.n_cols())
    from PIL import Image
    assert Image.open(a / "drift.png").size == (3 * sc.n_cols(), 3 * sc.n_rows())
    rep = json.loads((a / "report.json").read_text())
    assert rep["params"]["ok_pitch"] == 0.1 and len(rep["components"]) == 2
    assert not any(str(tmp_path) in line for line in (a / "report.json").read_text().splitlines())   # no absolute paths
    assert "recommended offset" in (a / "summary.txt").read_text()


# ------------------------------------------------------------------ bad inputs
def test_bad_inputs(ph, tmp_path, capsys):
    out, sc, vol = ph
    surf, zarr = out / "surfaces" / "turn_01", out / "volume.zarr"
    ok = tmp_path / "ok.npy"
    np.save(ok, rect(sc, 6, 16, 8, 24))
    base = lambda lab, *x: [surf, lab, "--zarr", zarr, "--out-dir", tmp_path / "o", *x]   # noqa: E731
    wrong = tmp_path / "wrong.npy"
    np.save(wrong, np.ones((5, 5), np.uint8))
    empty = tmp_path / "empty.npy"
    np.save(empty, np.zeros((sc.n_rows(), sc.n_cols()), np.uint8))
    cube = tmp_path / "cube.npy"
    np.save(cube, np.ones((4, 5, 6), np.uint8))
    garbage = tmp_path / "g.png"
    garbage.write_bytes(b"not a png")
    for args in (base(wrong), base(empty), base(cube), base(garbage), base(tmp_path / "missing.npy"),
                 [tmp_path / "nosurf", ok, "--zarr", zarr, "--out-dir", tmp_path / "o"],
                 [surf, ok, "--zarr", tmp_path / "nozarr", "--out-dir", tmp_path / "o"],
                 base(ok, "--connectivity", 6), base(ok, "--ok-pitch", -1), base(ok, "--profile-halflen-vox", 0),
                 base(ok, "--max-shift-pitch", 0.01), base(ok, "--off-sheet-frac", 2), base(ok, "--max-nz2", 0)):
        capsys.readouterr()
        assert run_cli(args) == 2, args
        assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):                                   # neither --zarr nor --png-dir
        run_cli([surf, ok, "--out-dir", tmp_path / "o"])
    with pytest.raises(InputError):                                   # volume that does not reach the surface
        ld.run(mesh_of(sc.trace(1.0)), rect(sc, 6, 16, 8, 24), ArrayVolume(vol[:2]), P)


def test_nan_and_float_labels_and_min_value(ph):
    out, sc, vol = ph
    lab = rect(sc, 6, 16, 8, 24).astype(float) * 0.9
    lab[7, 9] = np.nan
    m = mesh_of(sc.trace(1.0))
    _, res, tab = ld.run(m, lab, ArrayVolume(vol), ld.Params(label_min_value=0.5))
    assert tab[0]["n_pixels"] == 159
    with pytest.raises(InputError):                    # nothing is above 0.95
        ld.run(m, lab, ArrayVolume(vol), ld.Params(label_min_value=0.95))


def test_components_connectivity_and_min_size(ph):
    out, sc, vol = ph
    m = mesh_of(sc.trace(1.0))
    lab = np.zeros((sc.n_rows(), sc.n_cols()), np.uint8)
    lab[6:12, 8:16] = 1
    lab[12:14, 16:18] = 1                          # touches the first blob diagonally only
    lab[3, 40] = 1                                 # a single pixel
    _, res8, t8 = ld.run(m, lab, ArrayVolume(vol), ld.Params(connectivity=8))
    _, res4, t4 = ld.run(m, lab, ArrayVolume(vol), ld.Params(connectivity=4))
    assert [t["n_pixels"] for t in t8] == [1, 52] and [t["n_pixels"] for t in t4] == [1, 48, 4]  # numbered in row-major order
    _, res, t = ld.run(m, lab, ArrayVolume(vol), ld.Params(min_component_px=5))
    assert len(t) == 1 and res["summary"]["n_components_dropped_small"] == 1
    assert t8[0]["verdict"] == "NO-DATA"       # 1 pixel < --min-measured


def test_unmeasurable_nodes_are_counted_not_guessed(ph):
    out, sc, vol = ph
    lab = rect(sc, 6, 16, 8, 24)
    xyz = np.array(sc.trace(1.0), float)
    xyz[..., 0] += 0.5 * (xyz[..., 2] - 32)                       # skew: the normals tilt by up to nz^2 ~ 0.2 along the grid
    m = mesh_of(xyz)
    n = ld.surface_normals(m)
    assert 0.1 < np.nanmax(n[6:16, 8:24, 2] ** 2) < 0.25
    _, res, tab = ld.run(m, lab, ArrayVolume(vol), ld.Params(max_nz2=0.1))
    s = res["summary"]
    assert s["n_labelled_tilted"] == int((n[6:16, 8:24, 2] ** 2 > 0.1).sum()) > 0
    assert s["n_measured"] + s["n_labelled_tilted"] + s["n_labelled_no_peak"] + s["n_labelled_invalid"] == s["n_labelled"]
    m = mesh_of(sc.trace(1.0))
    m.valid[6:10, 8:24] = False
    m.x[~m.valid] = m.y[~m.valid] = m.z[~m.valid] = np.nan
    _, res, tab = ld.run(m, lab, ArrayVolume(vol), P)
    assert res["summary"]["n_labelled_invalid"] == 64


def test_verdict_rules():
    v = lambda n, med, sp, off: ld.verdict_for(n, med, sp, off, P)   # noqa: E731
    assert v(50, 0.02, 0.02, 0.0) == "OK"
    assert v(50, 0.25, 0.03, 0.4) == "SHIFTED"
    assert v(50, -0.25, 0.03, 0.9) == "SHIFTED"
    assert v(50, 0.48, 0.03, 1.0) == "OFF-SHEET"
    assert v(50, 0.02, 0.02, 0.7) == "OFF-SHEET"                       # centred but nothing bright there
    assert v(50, 0.05, 0.40, 0.3) == "MIXED"
    assert v(50, 0.05, 0.40, 0.05) == "MIXED"
    assert v(3, 0.0, 0.0, 0.0) == "NO-DATA" and v(50, float("nan"), 0, 0) == "NO-DATA"


# ------------------------------------------------------------------ sparse slices (--z-snap-vox) and the real sample
def test_z_snap_uses_the_nearest_available_slice(ph, tmp_path):
    out, sc, vol = ph
    from PIL import Image
    d = tmp_path / "png"
    d.mkdir()
    for z in (20, 40):                                 # only two slices exist
        Image.fromarray(vol[z]).save(d / f"{z:05d}.png")
    surf, lab = out / "surfaces" / "turn_01", tmp_path / "l.npy"
    np.save(lab, rect(sc, 5, 17, 8, 24))               # rows 5..16 = z 15..48
    common = [surf, lab, "--png-dir", d, "--png-pixel-um", 1, "--voxel-size-um", 1]
    assert run_cli(common + ["--out-dir", tmp_path / "s0"]) == 2          # no label node sits exactly on slice 20 or 40
    assert run_cli(common + ["--z-snap-vox", 6, "--out-dir", tmp_path / "s6"]) == 0
    r6 = json.loads((tmp_path / "s6" / "report.json").read_text())["result"]["summary"]
    assert 0 < r6["n_measured"] < r6["n_labelled"] and r6["n_labelled_no_slice"] > 0
    d6 = np.load(tmp_path / "s6" / "drift.npz")
    assert set(np.unique(d6["slice_index"][d6["measured"]])) == {20, 40}


REAL = ROOT / "testdata" / "pherc_paris4_45um"


@pytest.mark.skipif(not (REAL / "slices" / "02600.png").exists(), reason="real sample not present")
def test_real_sample_smoke_with_a_synthetic_disc(tmp_path):
    """Demonstration only: a disc of labelled pixels on Scroll 1 (public sample). Checks that it runs and reports, not values."""
    yy, xx = np.mgrid[0:130, 0:354]
    lab = tmp_path / "disc.npy"
    np.save(lab, (((yy - 65) ** 2 + (xx - 177) ** 2) <= 25 ** 2).astype(np.uint8))
    rc = run_cli([REAL / "20260623164704-w116-117.tifxyz", lab, "--png-dir", REAL / "slices", "--png-pixel-um", 45.532,
                  "--voxel-size-um", 45.532, "--z-snap-vox", 20, "--out-dir", tmp_path / "o"])
    assert rc == 0
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    assert rep["result"]["summary"]["n_measured"] > 50 and rep["components"][0]["verdict"] in ld.VERDICTS
