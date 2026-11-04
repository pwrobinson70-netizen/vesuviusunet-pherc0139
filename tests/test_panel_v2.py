"""panel_v2 (vun-panel2): the decision rule, and four cases of the TUNE set pinned (two originals, two broken copies).

The cases are the first two patches of the first ground-truth set in name order. For each, the verdict recorded in results/panel_v2_raw_set_a.csv
(docs/PANEL_V2.md) is pinned. Anything the panel gets wrong (a false alarm on an original, a miss on a broken copy) is xfail(strict=True) asserting
the correct behaviour: when a fix makes it right the test XPASSes, strict mode fails, and the fixer removes the marker.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parent.parent
GT = ROOT / "testdata" / "pherc_paris4_groundtruth"
NEG = ROOT / "results" / "negatives"
sys.path.insert(0, str(ROOT))
for d in ("judge_panel", "groundtruth_score"):
    sys.path.insert(0, str(ROOT / "tools" / d))
import panel_v2 as pv  # noqa: E402

P1 = "band-seed10017187-20260729-201008-211.tifxyz"
P2 = "band-seed1028766-20260730-001347-463.tifxyz"


def _row(f, n=100, ad="PASS", ag="PASS", sw="PASS"):
    return dict(surface_on_fraction=f, surface_judged=n, audit_default=ad, audit_global=ag, switch=sw)


# ------------------------------------------------------------------ the rule (no data needed)
def test_required_vote_decides():
    T = pv.DEFAULT_T
    assert pv.decide(_row(T + 0.01), T)[0] == "PASS"
    assert pv.decide(_row(T), T)[0] == "PASS"                    # "at or above T" passes
    assert pv.decide(_row(T - 0.01), T)[0] == "FAIL"


def test_one_advisory_fail_cannot_fail_a_trace_two_can():
    T = pv.DEFAULT_T
    assert pv.decide(_row(0.9, sw="FAIL"), T)[0] == "PASS"
    assert pv.decide(_row(0.9, ag="FAIL"), T)[0] == "PASS"
    v, req, nf, why = pv.decide(_row(0.9, ag="FAIL", sw="FAIL"), T)
    assert (v, req, nf) == ("FAIL", "PASS", 2) and "advisory" in why
    assert pv.decide(_row(0.9, ag="FAIL", sw="FAIL"), T, advisory_k=3)[0] == "PASS"


def test_not_judged_and_error_are_no_vote():
    T = pv.DEFAULT_T
    assert pv.decide(_row(0.9, ad="NOT JUDGED", ag="NOT JUDGED", sw="ERROR"), T)[0] == "PASS"
    assert pv.decide(_row(None, n=0), T)[0] == "NOT JUDGED"
    assert pv.decide(_row(0.9, n=3), T)[0] == "NOT JUDGED"        # fewer than 10 judged points
    assert pv.decide(_row(None, n=0, ag="FAIL", sw="FAIL"), T)[0] == "FAIL"   # two advisory fails still fail it


def test_default_threshold_is_the_recorded_tune_set_choice():
    assert pv.DEFAULT_T == pytest.approx(0.415)


# ------------------------------------------------------------------ four pinned cases of the tune set
pytestmark_data = pytest.mark.skipif(not (GT / "patches" / P1).is_dir() or not (NEG / P1).is_dir(), reason="ground-truth sample / results/negatives not present")


def _dense(src, tmp, name):
    from vun_tools.densify import densify_dir
    dst = Path(tmp) / name
    densify_dir(str(src), str(dst), 1.0)
    return str(dst)


def _verdict(patch, kind):
    import score as gscore
    pd = GT / "patches" / patch
    w = json.loads((pd / "mesh.tifxyz" / "meta.json").read_text())["window"]
    with tempfile.TemporaryDirectory(prefix="pv2t_") as tmp:
        umb = str(Path(tmp) / "umb.json")
        gscore.shifted_umbilicus(str(GT), w, umb)
        src = pd / "mesh.tifxyz" if kind == "original" else NEG / patch / kind
        mesh = _dense(src, tmp, "m.tifxyz")
        row = pv.collect(dict(patch=patch, kind=kind, mesh=mesh, ct=str(pd / "slices"), pred=str(pd / "surfpred"), umb=umb, heights=w["heights"]))
    return pv.decide(row, pv.DEFAULT_T), row


# recorded 6 Nov 2026, results/panel_v2_raw_set_a.csv: (surface on-sheet fraction, advisory votes (audit_default, audit_global, switch))
@pytestmark_data
def test_original_2_passes():
    (v, req, nf, _), row = _verdict(P2, "original")
    assert v == "PASS" and req == "PASS" and nf == 0
    assert float(row["surface_on_fraction"]) == pytest.approx(0.752, abs=0.01)


@pytestmark_data
@pytest.mark.xfail(strict=True, reason="false alarm on a verified patch: required vote passes (0.735) but trace_auditor --global-pitch and the switch finder both FAIL, "
                                       "so the advisory 2-of-3 rule fails it (docs/PANEL_V2.md); correct behaviour: PASS")
def test_original_1_is_not_a_false_alarm():
    (v, req, nf, _), row = _verdict(P1, "original")
    assert req == "PASS" and float(row["surface_on_fraction"]) == pytest.approx(0.735, abs=0.01)     # the required vote is right ...
    assert v == "PASS"                                                                              # ... the advisory rule overrules it


@pytestmark_data
def test_switch_mid_copy_of_patch_1_is_caught():
    (v, req, nf, _), row = _verdict(P1, "switch-mid")
    assert v == "FAIL" and req == "FAIL"
    assert float(row["surface_on_fraction"]) == pytest.approx(0.322, abs=0.01)


@pytestmark_data
def test_shift_full_copy_of_patch_2_is_caught():
    (v, req, nf, _), row = _verdict(P2, "shift-full")
    assert v == "FAIL" and req == "FAIL"
    assert float(row["surface_on_fraction"]) == pytest.approx(0.265, abs=0.01)
