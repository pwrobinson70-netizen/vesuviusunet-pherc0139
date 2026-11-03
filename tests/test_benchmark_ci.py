"""benchmark_ci: a tiny real run (2 seeds, 96^3) writes the CSV with the expected columns in under 90 s; summarise.py gives known
means / CI widths on a fixture CSV."""
import csv
import importlib.util
import os
import sys
import time

import numpy as np
import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
BC = os.path.join(ROOT, "tools", "benchmark_ci")


def _load(name):
    # a normal import (not importlib-by-path): run.py's multiprocessing "spawn" workers must be able to import the module by name
    if BC not in sys.path:
        sys.path.insert(0, BC)
    return importlib.import_module(name)


def test_small_run_writes_csv(tmp_path):
    pytest.importorskip("scipy")
    pytest.importorskip("tifffile")
    pytest.importorskip("zarr")
    run = _load("run")
    out = tmp_path / "runs.csv"
    t0 = time.time()
    rc = run.main(["--seeds", "0-1", "--sizes", "96", "--out", str(out), "--work", str(tmp_path / "cache")])
    elapsed = time.time() - t0
    assert rc == 0
    assert elapsed < 90, f"2-seed 96^3 run took {elapsed:.0f}s"
    with open(out, newline="") as fh:
        rd = csv.DictReader(fh)
        assert rd.fieldnames == run.COLUMNS
        rows = list(rd)
    assert len(rows) == 8                                              # 4 deformations x 2 seeds
    assert {r["deformation"] for r in rows} == {"round", "mild", "crushed", "merged"}
    assert all(r["status"] == "ok" for r in rows)
    for c in ("switch_recall_trace_height", "centre_mean_err", "clean_true", "aud_true_pass_rate", "tr_on_turn_before_mean"):
        assert all(r[c] != "" for r in rows), c
    assert all(0.0 <= float(r["clean_true"]) <= 1.0 for r in rows)


def _fixture(path):
    run = _load("run")
    vals = list(range(1, 11))                                          # round: 1..10 -> mean 5.5, median 5.5, min 1, max 10
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=run.COLUMNS, restval="")
        w.writeheader()
        for i, v in enumerate(vals):
            w.writerow(dict(size=192, deformation="round", seed=i, status="ok", centre_mean_err=v, clean_true=0.7 + 0.02 * i))
            w.writerow(dict(size=192, deformation="mild", seed=i, status="ok", centre_mean_err=3.0, clean_true=0.95))


def test_summarise_known_values(tmp_path):
    s = _load("summarise")
    p = tmp_path / "fx.csv"
    _fixture(p)
    rows = s.read_rows(str(p))
    st = s.stats(s.column(rows, "centre_mean_err", 192, "round"))
    assert (st["n"], st["min"], st["max"]) == (10, 1.0, 10.0)
    assert st["mean"] == pytest.approx(5.5) and st["median"] == pytest.approx(5.5)
    # bootstrap CI of the mean: sd/sqrt(n) = 2.872/sqrt(10) = 0.908 -> 95% half width ~ 1.78 (percentile bootstrap, +-0.25)
    assert st["hi"] - st["lo"] == pytest.approx(2 * 1.96 * 0.908, abs=0.5)
    assert st["lo"] < 5.5 < st["hi"] and 1.0 <= st["lo"] and st["hi"] <= 10.0
    assert s.stats(s.column(rows, "centre_mean_err", 192, "round")) == st      # fixed rng seed: reproducible
    const = s.stats(s.column(rows, "centre_mean_err", 192, "mild"))
    assert const["mean"] == 3.0 and const["lo"] == const["hi"] == 3.0          # zero-width CI
    assert s.stats([]) is None


def test_summarise_report_and_flag(tmp_path):
    s = _load("summarise")
    p = tmp_path / "fx.csv"
    _fixture(p)
    md = tmp_path / "r.md"
    assert s.main([str(p), "--md", str(md), "--sensitivity-sizes", "192"]) == 0
    text = md.read_text()
    assert "| Centre error, mean | round | 10 | 5.500 | 5.500 |" in text
    # clean_true: round runs 0.70..0.88 (mean 0.79, CI contains 0.8 -> flagged); mild constant 0.95 (not flagged)
    assert "**Spacing clean fraction, true pairs, round**" in text
    assert "**Spacing clean fraction, true pairs, mild**" not in text


def test_png_per_metric(tmp_path):
    pytest.importorskip("matplotlib")
    s = _load("summarise")
    p = tmp_path / "fx.csv"
    _fixture(p)
    assert s.main([str(p), "--md", str(tmp_path / "r.md"), "--png-dir", str(tmp_path / "png"), "--sensitivity-sizes", "192"]) == 0
    assert (tmp_path / "png" / "centre_mean_err.png").is_file()
