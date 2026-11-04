"""Tests for tools/judge_panel: every judge on one trace, aligned to the same cut lines and column windows."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("scipy")
pytest.importorskip("tifffile")
pytest.importorskip("zarr")

ROOT = Path(__file__).resolve().parent.parent
for d in ("texture_judge", "judge_panel", "phantom_scroll", "sheet_spacing_check"):
    sys.path.insert(0, str(ROOT / "tools" / d))

import judge_panel as jp  # noqa: E402
import phantom_cases as pc  # noqa: E402
from ssc_io import InputError  # noqa: E402

JP = ROOT / "tools" / "judge_panel" / "judge_panel.py"
HEIGHTS = [60.0, 80.0, 100.0]


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    d = tmp_path_factory.mktemp("panel")
    sc, paths, p = pc.build_on_disk(d / "ph", "round", 160)
    return sc, paths, d


def panel(case, name, neighbour=None, sub=None, p=None):
    sc, paths, d = case
    rep, res = jp.run_panel(paths[name], paths[neighbour] if neighbour else None, dict(zarr=paths["volume"]), HEIGHTS,
                            str(d / (sub or name)), p or jp.Params(), umbilicus=paths["umbilicus"])
    return rep, res


def test_unanimous_pass_on_a_true_round_trace(case):
    rep, _ = panel(case, "true")
    assert rep["panel_verdict"] == jp.PASS
    assert rep["region_counts"][jp.FAIL] == 0 and rep["region_counts"][jp.NJ] == 0 and rep["region_counts"][jp.PASS] > 10
    assert rep["disagreements"] == []
    judges = set(rep["judge_summary"])
    assert {"texture_judge", "sheet_switch_finder", "auditor:switch_finder", "auditor:winding_jumps"} <= judges
    for r in rep["regions"]:                                       # every judge that could judge said PASS in every region
        assert all(v["verdict"] in (jp.PASS, jp.NJ) for v in r["judges"].values())
    assert rep["trace_level"]["auditor:windcheck"]["verdict"] == jp.PASS        # tools/upstream/windcheck is part of the panel
    assert rep["judge_verdicts"] == dict(texture_judge="PASS", auditor="PASS")


def test_neighbour_adds_the_spacing_judges(case):
    rep, _ = panel(case, "true", neighbour="neighbour", sub="pair")
    assert {"sheet_spacing_check", "auditor:winding_offset"} <= set(rep["judge_summary"])
    assert rep["panel_verdict"] == jp.PASS


def test_planted_switch_fails_and_both_judges_name_it(case):
    sc, paths, d = case
    rep, _ = panel(case, "switch")
    assert rep["panel_verdict"] == jp.FAIL
    col = sc.n_cols() // 2
    hit = [r for r in rep["regions"] if r["col0"] <= col < r["col1"]]
    assert len(hit) == len(HEIGHTS)
    for r in hit:
        assert r["panel"] == jp.FAIL, r
        assert r["judges"]["texture_judge"]["verdict"] == jp.FAIL and "BREAK" in r["judges"]["texture_judge"]["detail"]
        assert r["judges"]["sheet_switch_finder"]["verdict"] == jp.FAIL and "switch" in r["judges"]["sheet_switch_finder"]["detail"]
        assert r["judges"]["auditor:switch_finder"]["verdict"] == jp.FAIL
    assert rep["judge_verdicts"] == dict(texture_judge="FAIL", auditor="FAIL")


def test_disagreement_is_reported_as_not_judged_with_the_text(case):
    """A trace shifted into the gap: the texture judge says FAIL (BLURRED), the winding-jump judge says PASS (it sees no jump)."""
    rep, _ = panel(case, "gap")
    split = [r for r in rep["regions"] if r["disagreement"]]
    assert split, "expected regions where the judges disagree"
    for r in split:
        assert r["panel"] == jp.NJ
        t = r["disagreement"][0]
        assert "texture_judge says FAIL" in t and "say" in t and "PASS" in t
    assert any("texture_judge says FAIL" in d for d in rep["disagreements"])
    assert rep["trace_level"]["auditor:windcheck"]["verdict"] == jp.FAIL           # off-sheet is caught by windcheck, so the trace still fails
    assert rep["panel_verdict"] == jp.FAIL
    # the literal reading: a split is a FAIL
    rep2, _ = panel(case, "gap", sub="gap_strict", p=jp.Params(on_disagreement="fail"))
    assert all(r["panel"] == jp.FAIL for r in rep2["regions"] if r["disagreement"])


def test_wrong_sheet_trace_is_a_known_limit(case):
    """Consistent on the wrong sheet: every judge, texture and peak based, passes it. Documented limit."""
    rep, _ = panel(case, "wrong_sheet")
    assert rep["panel_verdict"] == jp.PASS


def test_deterministic(case):
    a, _ = panel(case, "switch", sub="d1")
    b, _ = panel(case, "switch", sub="d2")
    for r in (a, b):
        r.pop("tool_version", None)
    assert json.dumps(a, sort_keys=True, default=float) == json.dumps(b, sort_keys=True, default=float)


def test_regions_are_the_same_cut_lines_and_columns_for_every_judge(case):
    rep, _ = panel(case, "true", sub="align")
    for r in rep["regions"]:
        assert r["z"] in HEIGHTS and r["col1"] - r["col0"] <= jp.Params().region_cols
    assert {r["z"] for r in rep["regions"]} == set(HEIGHTS)


# ---------------------------------------------------------------------------------------------------- combine() rules, no volume needed
V = lambda x: dict(verdict=x, detail=x.lower())      # noqa: E731


def test_combine_rules():
    p = jp.Params()
    assert jp.combine({"a": V("PASS"), "b": V("PASS")}, p) == ("PASS", [])
    assert jp.combine({"a": V("PASS"), "b": V("NOT JUDGED")}, p) == ("PASS", [])          # only judges that could judge count
    assert jp.combine({"a": V("FAIL"), "b": V("NOT JUDGED")}, p) == ("FAIL", [])
    assert jp.combine({"a": V("FAIL"), "b": V("FAIL")}, p) == ("FAIL", [])
    assert jp.combine({"a": V("NOT JUDGED"), "b": V("NOT JUDGED")}, p) == ("NOT JUDGED", [])
    v, d = jp.combine({"x": V("FAIL"), "y": V("PASS")}, p)
    assert v == "NOT JUDGED" and "x says FAIL" in d[0] and "y says PASS" in d[0]
    assert jp.combine({"x": V("FAIL"), "y": V("PASS")}, jp.Params(on_disagreement="fail"))[0] == "FAIL"


def test_every_threshold_is_a_flag():
    import dataclasses
    flags = {a.dest for a in jp.build_parser()._actions}
    for f in dataclasses.fields(jp.Params):
        assert f.name in flags


# ---------------------------------------------------------------------------------------------------- bad inputs
def test_bad_inputs(tmp_path, case):
    sc, paths, d = case
    def run(*a):
        return subprocess.run([sys.executable, str(JP), *map(str, a)], capture_output=True, text=True)
    assert run().returncode == 2
    assert run(tmp_path / "nope", "--zarr", paths["volume"], "--heights", "60", "--out-dir", tmp_path / "o").returncode == 2
    assert run(paths["true"], "--zarr", paths["volume"], "--heights", "", "--out-dir", tmp_path / "o").returncode == 2
    assert run(paths["true"], "--zarr", paths["volume"], "--heights", "x,y", "--out-dir", tmp_path / "o").returncode == 2
    assert run(paths["true"], "--zarr", paths["volume"], "--heights", "60", "--on-disagreement", "maybe", "--out-dir", tmp_path / "o").returncode == 2
    with pytest.raises(InputError):
        jp.run_panel(str(tmp_path / "nope"), None, dict(zarr=paths["volume"]), [60.0], str(tmp_path / "o"), jp.Params())


def test_cli_writes_report_and_exit_code(tmp_path, case):
    sc, paths, d = case
    p = subprocess.run([sys.executable, str(JP), paths["switch"], "--zarr", paths["volume"], "--umbilicus", paths["umbilicus"],
                        "--heights", "60,80,100", "--out-dir", str(tmp_path / "o")], capture_output=True, text=True)
    assert p.returncode == 1, p.stderr[-500:]
    rep = json.loads((tmp_path / "o" / "panel.json").read_text())
    assert rep["panel_verdict"] == "FAIL" and (tmp_path / "o" / "panel.txt").read_text().startswith("judge_panel")


def test_windcheck_off_is_reported_as_not_judged(case):
    rep, _ = jp.run_panel(case[1]["true"], None, dict(zarr=case[1]["volume"]), HEIGHTS, str(case[2] / "nowc"), jp.Params(),
                          umbilicus=case[1]["umbilicus"], windcheck=False)
    assert rep["trace_level"]["auditor:windcheck"]["verdict"] == jp.NJ
