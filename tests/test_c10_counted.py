"""Tests for scripts/c10_counted_fable_28102026.py.

The script executes at import time (top-level code reading sys.argv), so it is
run as a subprocess against synthetic log files, exactly as on the pod.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "c10_counted_fable_28102026.py"
BOXES = (("h042", "f042"), ("h043", "f043"), ("h044", "f044"), ("h047", "f047"))


def write_log(path, aucs, junk=True):
    lines = []
    if junk:
        lines += ["starting run", "Epoch 0: loss=1.0 no auc here"]
    lines += ["Epoch %d: loss=0.5 val_AUC=%.3f" % (i, a) for i, a in enumerate(aucs)]
    path.write_text("\n".join(lines) + "\n")


def make_run(path, n, tail_len, head, tail):
    """n epochs: `head` everywhere except the last `tail_len`, which are `tail`."""
    return [head] * (n - tail_len) + [tail] * tail_len


def build(tmp_path, c10_tails, c8_tails, c10_len=60, c8_len=240):
    for (h, f), t10, t8 in zip(BOXES, c10_tails, c8_tails):
        # head values differ wildly so a wrong window length would change the result
        write_log(tmp_path / ("c10_train_%s_28102026.log" % h), make_run(None, c10_len, 5, 0.1, t10))
        write_log(tmp_path / ("c8_train_%s_27102026.log" % f), make_run(None, c8_len, 20, 0.9, t8))


def run(tmp_path):
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    return r.stdout


def test_finer_is_better(tmp_path):
    build(tmp_path, [0.80] * 4, [0.70] * 4)
    out = run(tmp_path)
    assert "boxes up >= 0.03: 4/4 -> FINER IS BETTER (gate met)" in out
    assert "diff +0.100" in out


def test_big_mean_but_only_two_boxes_up_is_not_better(tmp_path):
    build(tmp_path, [0.90, 0.90, 0.70, 0.70], [0.70] * 4)  # mean +0.10, up 2/4
    out = run(tmp_path)
    assert "boxes up >= 0.03: 2/4 -> NO CLEAR DIFFERENCE" in out


def test_three_of_four_up_is_enough(tmp_path):
    build(tmp_path, [0.90, 0.90, 0.90, 0.60], [0.70] * 4)  # mean +0.10, up 3/4
    assert "FINER IS BETTER" in run(tmp_path)


def test_finer_is_worse(tmp_path):
    build(tmp_path, [0.60] * 4, [0.70] * 4)
    out = run(tmp_path)
    assert "FINER IS WORSE" in out
    assert "diff -0.100" in out


def test_no_clear_difference(tmp_path):
    build(tmp_path, [0.71] * 4, [0.70] * 4)
    assert "-> NO CLEAR DIFFERENCE" in run(tmp_path)


def test_windows_are_last_5_and_last_20(tmp_path):
    build(tmp_path, [0.80] * 4, [0.70] * 4)
    out = run(tmp_path)
    row = [l for l in out.splitlines() if l.startswith("h042")][0]
    assert "0.800" in row and "0.700" in row
    # descriptive last-20 of C10 = 15 head (0.1) + 5 tail (0.8) -> 0.275
    assert row.rstrip().endswith("0.275")


def test_short_c10_run_gives_no_verdict(tmp_path):
    build(tmp_path, [0.80] * 4, [0.70] * 4)
    write_log(tmp_path / "c10_train_h043_28102026.log", [0.8] * 59)
    out = run(tmp_path)
    assert "h043  INCOMPLETE: C10 59 of 60 epochs, C8 240 of 240 epochs" in out
    assert "COUNTED: not available" in out
    assert "FINER" not in out


def test_missing_c8_log_gives_no_verdict(tmp_path):
    build(tmp_path, [0.80] * 4, [0.70] * 4)
    (tmp_path / "c8_train_f047_27102026.log").unlink()
    out = run(tmp_path)
    assert "h047  INCOMPLETE: C10 60 of 60 epochs, C8 0 of 240 epochs" in out
    assert "COUNTED: not available" in out


def test_empty_directory_gives_no_verdict(tmp_path):
    out = run(tmp_path)
    assert out.count("INCOMPLETE") == 4
    assert "COUNTED: not available" in out


def test_overlong_run_is_rejected(tmp_path):
    build(tmp_path, [0.80] * 4, [0.70] * 4, c10_len=61)
    assert "COUNTED: not available" in run(tmp_path)
