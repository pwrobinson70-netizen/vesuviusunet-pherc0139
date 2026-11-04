"""Real-data ground truth: the 40 human-verified PHerc. Paris 4 (Scroll 1) patches, scored with trace_auditor (default mode).

Every patch in testdata/pherc_paris4_groundtruth is a CORRECT trace, so a checker should PASS it. The verdicts below were
recorded by brief 25 (results/groundtruth_patches.csv, mode "default", published centre line, the patch's own CT slices):

* every recorded FAIL is a false alarm: its test asserts the correct behaviour (not FAIL) and is xfail(strict=True).
  When a change turns a FAIL into NOT JUDGED or PASS the test XPASSes, strict mode fails the suite, and whoever made the
  change removes the marker and updates PINNED: that is the "what did it fix" signal.
* every recorded NOT JUDGED is pinned as NOT JUDGED (the winding-jump check needs 60 degrees of angle round the centre;
  a 700 px wide patch spans about 8): a change that makes one judgeable shows up here too. Not a claim that NOT JUDGED is right.

No patch is PASS today. Data: Vesuvius Challenge open data, CC BY-NC 4.0. See docs/REALDATA_GROUNDTRUTH.md.
"""
import csv
import os
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "testdata" / "pherc_paris4_groundtruth"
sys.path.insert(0, str(ROOT / "tools" / "groundtruth_score"))
import groundtruth_score as gs  # noqa: E402

pytestmark = pytest.mark.skipif(not (DATA / "patches").is_dir(), reason="ground-truth sample not present")

# recorded verdict per patch (brief 25, trace_auditor default thresholds)
PINNED = {
    "band-seed10017187-20260729-201008-211": "NOT JUDGED",
    "band-seed1028766-20260730-001347-463": "NOT JUDGED",
    "band-seed10512761-20260729-185302-714": "NOT JUDGED",
    "band-seed10615701-20260729-175123-564": "NOT JUDGED",
    "band-seed10838035-20260729-202140-756": "NOT JUDGED",
    "band-seed10941716-20260729-173756-873": "NOT JUDGED",
    "band-seed11419335-20260729-164656-105": "NOT JUDGED",
    "band-seed11609951-20260729-182322-096": "NOT JUDGED",
    "band-seed1180640-20260729-222113-516": "NOT JUDGED",
    "band-seed12103508-20260729-172739-714": "NOT JUDGED",
    "band-seed12303143-20260729-210804-059": "NOT JUDGED",
    "band-seed12704141-20260729-224947-867": "NOT JUDGED",
    "band-seed13037713-20260729-203705-670": "NOT JUDGED",
    "band-seed13218168-20260729-171531-582": "FAIL",
    "band-seed13364832-20260730-003410-414": "NOT JUDGED",
    "band-seed13533491-20260729-192123-040": "NOT JUDGED",
    "band-seed137103-20260730-002044-926": "NOT JUDGED",
    "band-seed1465356-20260729-160318-515": "FAIL",
    "band-seed14835206-20260730-004421-495": "NOT JUDGED",
    "band-seed15003009-20260729-170439-478": "NOT JUDGED",
    "band-seed15125391-20260729-232214-248": "NOT JUDGED",
    "band-seed15372108-20260729-164533-879": "NOT JUDGED",
    "band-seed15606684-20260729-231335-303": "NOT JUDGED",
    "band-seed15735188-20260729-184532-462": "NOT JUDGED",
    "band-seed15994369-20260729-225834-292": "NOT JUDGED",
    "band-seed1610817-20260730-003341-010": "FAIL",
    "band-seed16244965-20260729-170817-903": "NOT JUDGED",
    "band-seed16658040-20260729-213207-684": "NOT JUDGED",
    "band-seed17109446-20260729-173351-228": "FAIL",
    "band-seed17221198-20260729-221919-905": "NOT JUDGED",
    "band-seed17356252-20260729-210651-427": "NOT JUDGED",
    "band-seed17485725-20260729-182356-729": "NOT JUDGED",
    "band-seed17615994-20260729-232636-238": "NOT JUDGED",
    "band-seed17901491-20260729-174732-720": "NOT JUDGED",
    "band-seed18235570-20260729-173250-735": "FAIL",
    "band-seed18384563-20260729-185435-336": "NOT JUDGED",
    "band-seed18550190-20260729-194900-743": "FAIL",
    "band-seed18725348-20260729-204113-740": "NOT JUDGED",
    "band-seed18913366-20260729-212627-871": "NOT JUDGED",
    "band-seed1910856-20260729-194126-099": "FAIL",
}
FAILS = sorted(k for k, v in PINNED.items() if v == "FAIL")
OTHERS = sorted(k for k, v in PINNED.items() if v != "FAIL")


@pytest.fixture(scope="module")
def patches():
    return {p["name"].replace(".tifxyz", ""): p for p in gs.list_patches(str(DATA))}


@pytest.fixture(scope="module")
def tmp():
    with tempfile.TemporaryDirectory(prefix="gt_test_") as d:
        yield d


def _verdict(patch, tmp):
    umb = gs.shifted_umbilicus(str(DATA), patch["window"], os.path.join(tmp, patch["name"] + "_umb.json"))
    aud = os.path.join(gs.tools_root(), "trace_auditor", "trace_auditor.py")
    r = gs.audit_patch(aud, patch, umb, [], os.path.join(tmp), patch["name"][:40])
    return r["verdict"], r


def test_pinned_covers_exactly_the_forty_patches(patches):
    assert len(PINNED) == 40
    assert set(PINNED) == set(patches)


def test_recorded_csv_matches_pinned():
    p = ROOT / "results" / "groundtruth_patches.csv"
    if not p.is_file():
        pytest.skip("results/groundtruth_patches.csv not present")
    rows = [r for r in csv.DictReader(open(p)) if r["mode"] == "default"]
    assert {r["patch"]: r["verdict"] for r in rows} == PINNED


@pytest.mark.parametrize("name", FAILS)
@pytest.mark.xfail(strict=True, reason="false alarm on a human-verified correct trace (brief 25); correct behaviour: not FAIL")
def test_verified_patch_is_not_a_false_alarm(name, patches, tmp):
    v, r = _verdict(patches[name], tmp)
    assert v != "FAIL", r["fail_reasons"]


@pytest.mark.parametrize("name", OTHERS)
def test_verified_patch_verdict_is_pinned(name, patches, tmp):
    v, r = _verdict(patches[name], tmp)
    assert v != "FAIL", r["fail_reasons"]            # a new false alarm
    assert v == PINNED[name], f"verdict changed {PINNED[name]} -> {v}: update PINNED and docs/REALDATA_GROUNDTRUTH.md"


def test_wilson_interval():
    lo, hi = gs.wilson(7, 40)
    assert 0.087 < lo < 0.089 and 0.318 < hi < 0.320       # 7/40: 8.8-31.9 %
    assert gs.wilson(0, 40)[0] == 0.0
    assert gs.wilson(0, 0)[0] != gs.wilson(0, 0)[0]         # nan for n = 0


def test_umbilicus_is_shifted_by_the_window_origin(patches, tmp):
    import json
    p = next(iter(patches.values()))
    out = gs.shifted_umbilicus(str(DATA), p["window"], os.path.join(tmp, "u.json"))
    a = json.load(open(DATA / "umbilicus_9p6um.json"))["control_points"][0]
    b = json.load(open(out))["control_points"][0]
    assert (a["x"] - b["x"], a["y"] - b["y"], a["z"] - b["z"]) == (p["window"]["x0"], p["window"]["y0"], 0)
