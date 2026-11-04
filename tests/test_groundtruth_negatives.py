"""Deliberately broken copies of verified PHerc. Paris 4 (Scroll 1) patches: regeneration is deterministic and the panel's verdicts are pinned.

Two cases of patch band-seed10838035-20260729-202140-756 are regenerated from testdata/pherc_paris4_groundtruth with the fixed seed and compared
byte-for-byte (as arrays) with the committed results/negatives; the panel (tools/groundtruth_score/score.py) is run on them and the verdicts
recorded in results/groundtruth_panel_scores.csv (docs/REALDATA_2X2.md) are pinned. What the CT panel does NOT catch is an
xfail(strict=True): when a fix makes the panel catch it, the test XPASSes, strict mode fails, and the fixer removes the marker.
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("PIL")
import tifffile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GT = ROOT / "testdata" / "pherc_paris4_groundtruth"
NEG = ROOT / "results" / "negatives"
PATCH = "band-seed10838035-20260729-202140-756.tifxyz"
sys.path.insert(0, str(ROOT / "tools" / "groundtruth_score"))

pytestmark = pytest.mark.skipif(not (GT / "patches" / PATCH).is_dir() or not (NEG / PATCH).is_dir(),
                                reason="ground-truth sample or results/negatives not present")

import make_negatives as mn  # noqa: E402
import score  # noqa: E402

# recorded 6 Nov 2026 (results/groundtruth_panel_scores.csv): kind -> (audit_default, audit_global, switch, surface)
RECORDED = {
    "switch-mid": ("NOT JUDGED", "FAIL", "FAIL", "FAIL"),
    "scramble": ("NOT JUDGED", "NOT JUDGED", "PASS", "FAIL"),
}
CT_TOOLS = ("audit_default", "audit_global", "switch")


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    out = tmp_path_factory.mktemp("neg")
    mn.run(str(GT), str(out), seed=mn.DEFAULT_SEED, only=[PATCH], kinds=("switch-mid", "scramble"))
    return out


def test_regeneration_is_deterministic_and_matches_the_committed_copies(regenerated):
    for kind in ("switch-mid", "scramble"):
        for a in "xyz":
            new = tifffile.imread(regenerated / PATCH / kind / f"{a}.tif")
            old = tifffile.imread(NEG / PATCH / kind / f"{a}.tif")
            assert new.shape == old.shape and np.array_equal(new, old), (kind, a)
        assert np.array_equal(tifffile.imread(regenerated / PATCH / kind / "mask.tif"), tifffile.imread(NEG / PATCH / kind / "mask.tif"))


def test_the_breakage_is_what_it_says(regenerated):
    src = GT / "patches" / PATCH / "mesh.tifxyz"
    o = {a: tifffile.imread(src / f"{a}.tif").astype(float) for a in "xyz"}
    valid = tifffile.imread(src / "mask.tif") > 0
    W = valid.shape[1]
    sm = {a: tifffile.imread(regenerated / PATCH / "switch-mid" / f"{a}.tif").astype(float) for a in "xyz"}
    d = np.hypot(sm["x"] - o["x"], sm["y"] - o["y"])
    assert np.allclose(sm["z"][valid], o["z"][valid])
    assert d[:, : W // 2].max() == 0.0                                  # left half unchanged
    with open(NEG / "manifest.csv") as fh:
        import csv
        row = next(r for r in csv.DictReader(fh) if r["patch"] == PATCH)
    shift = abs(float(row["shift_switch_mid_vox"]))
    assert np.allclose(d[:, W // 2:][valid[:, W // 2:]], shift, atol=1e-3)   # right half moved by exactly one pitch in the plane
    sc = {a: tifffile.imread(regenerated / PATCH / "scramble" / f"{a}.tif").astype(float) for a in "xyz"}
    assert np.array_equal(sc["x"], o["x"]) and np.array_equal(np.sort(sc["z"][valid]), np.sort(o["z"][valid]))
    assert not np.array_equal(sc["z"][valid], o["z"][valid])


def test_refuses_a_folder_whose_readme_does_not_say_paris_4(tmp_path):
    (tmp_path / "README.md").write_text("some other scroll\n")
    with pytest.raises(SystemExit):
        mn.run(str(tmp_path), str(tmp_path / "out"))
    (tmp_path / "README.md").unlink()
    with pytest.raises(SystemExit):
        mn.run(str(tmp_path), str(tmp_path / "out"))


@pytest.fixture(scope="module")
def verdicts(regenerated):
    out = {}
    w = json.loads((GT / "patches" / PATCH / "mesh.tifxyz" / "meta.json").read_text())["window"]
    umb = regenerated / "umb.json"
    score.shifted_umbilicus(str(GT), w, str(umb))
    for kind in RECORDED:
        job = dict(patch=PATCH, kind=kind, mesh=str(regenerated / PATCH / kind), ct=str(GT / "patches" / PATCH / "slices"),
                   pred=str(GT / "patches" / PATCH / "surfpred"), umb=str(umb), heights=w["heights"], min_conf=0.3, pass_on=0.8, wn_jump=0.6)
        out[kind] = score.score_case(job)
    return out


@pytest.mark.parametrize("kind", sorted(RECORDED))
def test_recorded_verdicts(verdicts, kind):
    r = verdicts[kind]
    assert (r["audit_default"], r["audit_global"], r["switch"], r["surface"]) == RECORDED[kind]


def test_switch_mid_is_caught_by_the_ct_panel(verdicts):
    r = verdicts["switch-mid"]
    assert any(r[t] == "FAIL" for t in CT_TOOLS)


@pytest.mark.xfail(strict=True, reason="gap: a scrambled-z trace is not caught by any CT tool in the panel (0/40 on the Scroll 1 sample, "
                                       "docs/REALDATA_2X2.md); only the surface prediction fails it")
def test_scramble_is_caught_by_the_ct_panel(verdicts):
    r = verdicts["scramble"]
    assert any(r[t] == "FAIL" for t in CT_TOOLS)


def test_scramble_is_caught_by_the_surface_prediction_only(verdicts):
    assert verdicts["scramble"]["surface"] == "FAIL"
