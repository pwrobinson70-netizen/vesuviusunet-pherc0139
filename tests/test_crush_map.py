"""Brief 15 part C: tools/crush_map on phantom_scroll phantoms (synthetic only; the true severity map is phantom_scroll's severity.npy)."""
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("tifffile")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parent.parent
for d in ("common", "crush_map", "phantom_scroll", "trace_auditor", "sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder"):
    sys.path.insert(0, str(ROOT / "tools" / d))
sys.path.insert(0, str(ROOT / "tests"))

import crush_map as cm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

SIZE = 192
ZS = (50, 96, 140)


def _slices(name, seed=0, size=SIZE, zs=ZS):
    """Rendered slices (0..255), the winding labels and the TRUE severity of a preset (single slices only: cheap)."""
    sc = ps.Scroll(ps.make_params(name, size, seed))
    out = []
    for z in zs:
        v, lab, sev = sc.render_slab(z, z + 1, severity=True)
        out.append((np.rint(v[0] * 255.0), lab[0], sev[0]))
    return out


def _cells(name, seed=0, p=None):
    """(estimated severity, true severity) over the map cells that have an estimate and lie inside the scroll."""
    p = p or cm.Params()
    g = p.grid_step_px
    est, tru = [], []
    for img, lab, sev in _slices(name, seed):
        m = cm.slice_maps(img, 1.0, p)
        ii, jj = np.mgrid[g // 2:img.shape[0]:g, g // 2:img.shape[1]:g]
        ok = np.isfinite(m["severity"]) & (lab[ii, jj] >= 0)
        est.append(m["severity"][ok])
        tru.append(sev[ii, jj][ok])
    return np.concatenate(est), np.concatenate(tru)


@pytest.fixture(scope="module")
def cells():
    return {n: _cells(n) for n in ("round", "mild", "crushed", "crushed-hard")}


def test_severity_correlates_with_the_true_severity_on_crushed_hard(cells):
    est, tru = cells["crushed-hard"]
    assert len(est) > 300 and tru.std() > 0.1
    rho = spearmanr(est, tru)[0]
    assert rho > 0.7, rho
    assert abs(est.mean() - tru.mean()) < 0.15                      # and it is on the same scale, not just the same ranking


def test_severity_is_near_zero_on_the_round_phantom(cells):
    est, tru = cells["round"]
    assert tru.max() == 0.0
    assert est.mean() < 0.05 and np.percentile(est, 95) < 0.15


def test_severity_orders_the_presets_by_how_crushed_they_are(cells):
    means = [cells[n][0].mean() for n in ("round", "mild", "crushed", "crushed-hard")]
    assert means == sorted(means) and means[-1] > 3 * means[1]


def test_crushed_phantom_also_correlates(cells):
    est, tru = cells["crushed"]
    assert spearmanr(est, tru)[0] > 0.6


def test_maps_have_the_stated_ranges_and_the_pitch_is_the_local_spacing():
    img, lab, sev = _slices("crushed-hard", zs=(96,))[0]
    m = cm.slice_maps(img, 1.0, cm.Params())
    shape = m["severity"].shape
    for k in cm.MAPS:
        assert m[k].shape == shape
    s = m["severity"][np.isfinite(m["severity"])]
    assert s.min() >= 0 and s.max() <= 1
    c = m["coherence"][np.isfinite(m["coherence"])]
    assert c.min() >= 0 and c.max() <= 1
    pit = m["pitch"][np.isfinite(m["pitch"])]
    assert len(pit) > 100 and 2.0 < np.median(pit) < 20.0          # nominal pitch is 16.5 voxels, compressed down to ~3
    assert np.nanmax(m["variability"]) > 0


# ---------------------------------------------------------------- outputs, reader, CLI
@pytest.fixture(scope="module")
def small_png_phantom(tmp_path_factory):
    d = tmp_path_factory.mktemp("png")
    p = ps.make_params("crushed", 96, 0)
    sc = ps.Scroll(p)
    vol, lab = sc.render()
    ps.write_pngs(str(d), vol)
    return d, vol


def test_cli_writes_png_npz_and_summary(small_png_phantom, tmp_path):
    d, vol = small_png_phantom
    out = tmp_path / "o"
    rc = cm.main(["--png-dir", str(d), "--png-pixel-um", "1", "--voxel-size-um", "1", "--heights", "30,48,66", "--out-dir", str(out),
                  "--write-zarr", "--grid-step-px", "3"])
    assert rc == 0
    z = np.load(out / "crush_map.npz")
    assert list(z["heights"]) == [30, 48, 66]
    for k in cm.MAPS:
        assert z[k].ndim == 3 and z[k].shape[0] == 3
    meta = json.loads(str(z["meta"]))
    assert meta["grid_step_px"] == 3 and meta["ct_scale"] == 1.0
    assert len(list(out.glob("crush_z*.png"))) == 3
    rows = json.loads((out / "summary.json").read_text())["heights"]
    assert [r["z"] for r in rows] == [30, 48, 66] and all(r["severity_mean"] is not None for r in rows)
    assert (out / "summary.csv").read_text().splitlines()[0].startswith("z,n_cells,pitch_p10")
    assert (out / "crush_map.zarr").is_dir()


def test_crush_map_reader_looks_up_cells_and_heights(tmp_path):
    h, n, g = 3, 20, 4
    sev = np.zeros((h, n, n))
    sev[1, 5, 7] = 0.9                                              # cell (i=5, j=7) of the middle height
    meta = json.dumps(dict(grid_step_px=g, ct_scale=1.0))
    np.savez_compressed(tmp_path / "m.npz", heights=np.array([10.0, 20.0, 30.0]), meta=meta, severity=sev, pitch=sev + 1,
                        variability=sev, coherence=sev, confidence=sev, density=sev)
    m = cm.CrushMap(str(tmp_path / "m.npz"))
    xy = np.array([[7 * g + g // 2, 5 * g + g // 2], [3.0, 3.0]])   # (x, y) voxels; ct_scale 1: pixel = voxel
    assert m.at(20.0, xy).tolist() == [0.9, 0.0]
    assert m.at(21.0, xy)[0] == 0.9                                 # nearest height
    assert m.at(100.0, xy).tolist() == [pytest.approx(np.nan, nan_ok=True)] * 2 or np.isnan(m.at(100.0, xy)).all()
    assert m.at(20.0, xy, "pitch")[0] == pytest.approx(1.9)


def test_every_parameter_is_a_flag_and_in_the_readme():
    flags = {s for a in cm.build_parser()._actions for s in a.option_strings}
    readme = (ROOT / "tools" / "crush_map" / "README.md").read_text() + (ROOT / "tools" / "crush_map" / "crush_map.py").read_text()
    for f in dataclasses.fields(cm.Params):
        flag = "--" + f.name.replace("_", "-")
        assert flag in flags, flag
        assert flag in readme, flag


def test_bad_parameters_are_rejected():
    with pytest.raises(cm.InputError):
        cm.Params(full_factor=1.0).validate()
    with pytest.raises(cm.InputError):
        cm.Params(var_window=4).validate()


# ---------------------------------------------------------------- trace_auditor --crush-map
def _write_map(path, heights, value, shape=(30, 30), g=4):
    h = len(heights)
    sev = np.full((h,) + shape, value)
    np.savez_compressed(path, heights=np.asarray(heights, float), meta=json.dumps(dict(grid_step_px=g, ct_scale=1.0)),
                        severity=sev, pitch=sev, variability=sev, coherence=sev, confidence=sev, density=sev)


def test_auditor_crush_map_sets_not_judged_regions(tmp_path):
    from test_v2_local_pitch import _audit, _small_pair, _truth_centre
    A, B, vol, sc = _small_pair(tmp_path, seed=3)
    heights = [24.0, 32.0, 40.0]
    centre = _truth_centre(sc)
    base = _audit([A], vol, centre, heights)["traces"][0]
    assert base["verdict"] == "PASS" and base["judged_fraction"] >= 0.9
    _write_map(tmp_path / "zero.npz", heights, 0.0)
    same = _audit([A], vol, centre, heights, crush_map=str(tmp_path / "zero.npz"))["traces"][0]
    assert same["verdict"] == "PASS" and same["judged_fraction"] == pytest.approx(base["judged_fraction"])
    _write_map(tmp_path / "crushed.npz", heights, 1.0)
    t = _audit([A], vol, centre, heights, crush_map=str(tmp_path / "crushed.npz"))["traces"][0]
    assert t["judged_fraction"] == 0.0 and t["verdict"] == "NOT JUDGED", (t["verdict"], t["reasons"])
    # a threshold above 1 can never veto
    t2 = _audit([A], vol, centre, heights, crush_map=str(tmp_path / "crushed.npz"), max_crush_severity=1.5)["traces"][0]
    assert t2["verdict"] == "PASS"


def test_auditor_crush_map_flag_is_in_the_cli():
    import trace_auditor as ta
    a = ta.build_parser().parse_args(["a", "--zarr", "v", "--out-dir", "o", "--crush-map", "x.npz", "--max-crush-severity", "0.7"])
    assert a.crush_map == "x.npz" and a.max_crush_severity == 0.7
