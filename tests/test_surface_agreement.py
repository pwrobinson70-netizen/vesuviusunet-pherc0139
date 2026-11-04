"""tools/surface_agreement on the concentric-ring phantom with a fake prediction (blurred sheet mask), plus a smoke test on the
real Scroll 1 window under testdata/pherc_paris4_surfpred."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "surface_agreement"))

import surface_agreement as sa  # noqa: E402
import fake_prediction as fp  # noqa: E402
from ssc_io import ArrayVolume, InputError, build_mesh  # noqa: E402
from test_sheet_spacing_check import CX, CY, NZ, PITCH, R0, cylinder, make_ct  # noqa: E402

HEIGHTS = [30.0, 50.0, 70.0]


@pytest.fixture(scope="module")
def vols():
    ct = make_ct(0.0)
    return ArrayVolume(fp.blurred_sheet_mask(ct)), ArrayVolume(ct)


def hop(r0, col, delta, n_cols=720):
    th = np.linspace(0, 2 * np.pi, n_cols, endpoint=False)
    r = r0 + delta * (np.arange(n_cols) >= col)
    z = np.arange(NZ, dtype=float)
    return build_mesh("hop", np.tile(CX + r * np.cos(th), (NZ, 1)), np.tile(CY + r * np.sin(th), (NZ, 1)),
                      np.tile(z[:, None], (1, n_cols)), {"scale": [0.5, 0.5]})


def go(mesh, vols, **kw):
    rep, rows = sa.run([mesh], vols[0], vols[1], HEIGHTS, sa.Params(**kw))
    return rep["traces"][0], rows[mesh.name]


def test_true_trace_is_on_the_predicted_sheet(vols):
    t, rows = go(cylinder(R0), vols)
    assert t["pred_on_fraction"] > 0.98 and t["pred_not_judged"] == 0
    assert all(h["pred_verdict"] == "PASS" for h in t["heights"])
    off = np.array([r["pred_offset_vox"] for r in rows])
    assert np.nanmax(np.abs(off)) < 1.0                                   # the ridge is where the sheet is
    assert min(r["pred_value"] for r in rows) > 200


def test_trace_half_a_pitch_off_is_off(vols):
    t, rows = go(cylinder(R0 + PITCH / 2), vols)
    assert t["pred_on_fraction"] < 0.02
    assert all(h["pred_verdict"] == "FAIL" for h in t["heights"])


def test_half_pitch_switch_is_off_beyond_the_switch_only(vols):
    col = 300
    t, rows = go(hop(R0, col, PITCH / 2), vols)
    before = [r for r in rows if r["col"] < col - 3]
    after = [r for r in rows if r["col"] > col + 3]
    assert before and after
    assert np.mean([r["pred_verdict"] == sa.ON for r in before]) > 0.98
    assert np.mean([r["pred_verdict"] == sa.OFF for r in after]) > 0.98


def test_whole_sheet_switch_is_invisible_to_a_prediction_but_not_to_the_ct_pitch_check(vols):
    """A jump of one pitch lands on the NEXT predicted sheet: 'on a sheet' stays true. Documented limitation of the prediction judge."""
    t, rows = go(hop(R0, 300, PITCH), vols)
    assert t["pred_on_fraction"] > 0.98


def test_2x2_is_near_diagonal_on_phantoms(vols):
    for r_off, diag in ((0.0, ("ours_on_pred_on",)), (PITCH / 2, ("ours_off_pred_off",))):
        t, _ = go(cylinder(R0 + r_off), vols)
        T = t["table_2x2"]
        assert sum(T[k] for k in diag) / sum(T.values()) > 0.97, (r_off, T)
        assert t["agreement_fraction"] > 0.97
    t, rows = go(hop(R0, 300, PITCH / 2), vols)                           # half off: ours and prediction both flip beyond the switch
    assert t["agreement_fraction"] > 0.9


def test_disagreements_are_listed_and_marked(vols):
    ct_shifted = ArrayVolume(make_ct(0.0)[:, :, :].copy())
    pred_shifted = ArrayVolume(np.roll(vols[0].data, 6, axis=1))          # prediction displaced by half a pitch in y: ours and its disagree
    rep, rows = sa.run([cylinder(R0)], pred_shifted, ct_shifted, HEIGHTS, sa.Params())
    r = rep["traces"][0]["heights"][1]
    assert r["n_disagree"] > 0 and len(r["disagreements"]) == min(r["n_disagree"], 200)
    assert {d["kind"] for d in r["disagreements"]} <= {"ours ON / prediction OFF", "ours OFF / prediction ON"}
    assert any(x["agreement"].startswith("ours") for x in rows["m"])


def test_deterministic(vols, tmp_path):
    a, ra = go(cylinder(R0), vols)
    b, rb = go(cylinder(R0), vols)
    assert json.dumps(a, default=float, sort_keys=True) == json.dumps(b, default=float, sort_keys=True)
    assert ra == rb or all(str(x) == str(y) for x, y in zip(ra, rb))


def test_no_prediction_slice_is_not_judged(vols):
    rep, rows = sa.run([cylinder(R0)], vols[0], None, [30.0, 5000.0], sa.Params())
    hs = rep["traces"][0]["heights"]
    assert hs[0]["pred_verdict"] == "PASS" and hs[1]["pred_verdict"] == "NOT JUDGED" and hs[1]["n_points"] == 0


def test_points_outside_the_image_are_not_judged(vols):
    m = cylinder(R0)
    shifted = build_mesh("far", m.x + 600.0, m.y, m.z, {"scale": [0.5, 0.5]})
    rep, rows = sa.run([shifted], vols[0], None, [50.0], sa.Params())
    assert rep["traces"][0]["pred_on"] + rep["traces"][0]["pred_off"] < len(rows["far"])
    assert any(r["pred_verdict"] == sa.NJ for r in rows["far"])


def test_bad_inputs(tmp_path, vols, capsys):
    with pytest.raises(InputError):
        sa.Params(on_tol_vox=0).validate()
    with pytest.raises(InputError):
        sa.Params(pass_on_fraction=1.5).validate()
    assert sa.main(["nope.tifxyz", "--pred-png-dir", str(tmp_path), "--out-dir", str(tmp_path / "o")]) == 2
    assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        sa.main(["x"])                                                    # prediction is required


def test_every_threshold_is_a_flag_and_in_the_readme():
    import dataclasses
    flags = {s for a in sa.build_parser()._actions for s in a.option_strings}
    readme = (ROOT / "tools" / "surface_agreement" / "README.md").read_text()
    for f in dataclasses.fields(sa.Params):
        flag = "--" + f.name.replace("_", "-")
        assert flag in flags and flag in readme, flag


# ------------------------------------------------------------------ real sample (Scroll 1, public)
SD = ROOT / "testdata" / "pherc_paris4_surfpred"


@pytest.mark.skipif(not (SD / "surfpred" / "09503.png").exists(), reason="surfpred sample not present")
def test_real_sample_smoke(tmp_path):
    a = next(SD.glob("*w116-117.tifxyz"))
    rc = sa.main([str(a), "--pred-png-dir", str(SD / "surfpred"), "--ct-png-dir", str(SD / "slices"), "--png-pixel-um", "9.6",
                  "--voxel-size-um", "9.6", "--heights", "9503,12001,14499", "--out-dir", str(tmp_path / "o"), "--png-scale", "1"])
    assert rc == 0
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    t = rep["traces"][0]
    assert [h["n_points"] for h in t["heights"]] == [156, 121, 105]
    for h in t["heights"]:
        T = h["table_2x2"]
        assert sum(T.values()) == h["n_compared"] <= h["n_points"]
        assert h["pred_on"] + h["pred_off"] + h["pred_not_judged"] == h["n_points"]
    T0 = t["heights"][0]["table_2x2"]
    assert T0["ours_on_pred_on"] == pytest.approx(31, abs=4) and T0["ours_off_pred_off"] == pytest.approx(75, abs=4)
    assert (tmp_path / "o" / "png").is_dir() and list((tmp_path / "o").glob("points_*.csv"))
    assert (tmp_path / "o" / "report.txt").read_text().startswith("surface_agreement")


def test_audit_context_on_a_phantom(vols, tmp_path):
    zarr = pytest.importorskip("zarr")
    from test_trace_auditor import _write_mesh
    z = zarr.open(str(tmp_path / "ct.zarr"), mode="w", shape=vols[1].data.shape, chunks=(1, 320, 256), dtype="f4")
    z[:] = vols[1].data
    z2 = zarr.open(str(tmp_path / "pred.zarr"), mode="w", shape=vols[0].data.shape, chunks=(1, 320, 256), dtype="f4")
    z2[:] = vols[0].data
    _write_mesh(tmp_path / "a", cylinder(R0))
    (tmp_path / "umb.json").write_text(json.dumps({"control_points": [{"z": float(k), "y": CY, "x": CX} for k in range(0, NZ, 10)]}))
    rc = sa.main([str(tmp_path / "a"), "--pred-zarr", str(tmp_path / "pred.zarr"), "--ct-zarr", str(tmp_path / "ct.zarr"), "--heights", "30,50,70",
                  "--audit", "--umbilicus", str(tmp_path / "umb.json"), "--out-dir", str(tmp_path / "o"), "--png-scale", "1"])
    assert rc == 0
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    assert rep["audit"]["ran"] and rep["audit"]["traces"][0]["verdict"] == "PASS"
    assert rep["traces"][0]["agreement_fraction"] > 0.97
    assert sa.main([str(tmp_path / "a"), "--pred-zarr", str(tmp_path / "pred.zarr"), "--audit", "--out-dir", str(tmp_path / "o2")]) == 2
