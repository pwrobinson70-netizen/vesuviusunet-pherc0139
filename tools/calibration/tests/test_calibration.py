"""Calibration harness: a tiny grid runs end to end quickly and writes the CSV with the expected columns."""
import csv
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("tifffile")
pytest.importorskip("zarr")
pytest.importorskip("scipy")

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import calib  # noqa: E402
import run_grid  # noqa: E402


def test_tiny_grid_end_to_end(tmp_path):
    out = tmp_path / "grid.csv"
    t0 = time.time()
    failed = run_grid.run([0, 1], [5.0], [15.0], ["round"], 96, str(tmp_path / "cache"), str(out), jobs=2, log=lambda m: None)
    assert not failed
    assert time.time() - t0 < 60
    with open(out, newline="") as fh:
        rd = csv.DictReader(fh)
        assert rd.fieldnames == calib.COLUMNS
        rows = list(rd)
    assert {r["seed"] for r in rows} == {"0", "1"}
    assert {r["tool"] for r in rows} == {"sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor"}
    assert {r["kind"] for r in rows} >= {"true", "bad"}
    assert all(r["verdict_correct"] != "" for r in rows)
    assert (tmp_path / "cache").is_dir() and len(list((tmp_path / "cache").glob("*.npz"))) == 2


def test_resume_skips_finished_tasks(tmp_path):
    out = str(tmp_path / "g.csv")
    args = ([0], [5.0], [15.0], ["round"], 96, str(tmp_path / "c"), out)
    run_grid.run(*args, jobs=1, log=lambda m: None)
    n = sum(1 for _ in open(out))
    run_grid.run(*args, jobs=1, log=lambda m: None)
    assert sum(1 for _ in open(out)) == n


def test_geometry_and_cache_roundtrip(tmp_path):
    ph = calib.Phantom(0, 15, "merged", 64, str(tmp_path))
    again = calib.Phantom(0, 15, "merged", 64, str(tmp_path))
    assert (ph.vol == again.vol).all()
    r0, thick, base = calib.geometry(60, 192)
    assert base == 0 and thick > 10 and r0 <= 14


def test_report_choice_prefers_plateau_over_spike():
    pytest.importorskip("matplotlib")
    import report
    curve = [(1, 0.5, 0, 0, 1), (2, 1.0, 0, 0, 1), (3, 0.6, 0, 0, 1), (4, 0.9, 0, 0, 1), (5, 0.9, 0, 0, 1), (6, 0.9, 0, 0, 1)]
    i, lo, hi, _ = report.choose(curve, default=1)
    assert curve[i][0] == 5 and (lo, hi) == (4.0, 6.0)
