"""umbilicus_from_pred: level choice from the zarr metadata and the two estimators on a synthetic plane (no network)."""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "umbilicus_finder"))
import umbilicus_from_pred as up  # noqa: E402


def test_level_is_chosen_from_the_metadata_not_assumed():
    # the real zarr: level 0 is 9.6 um, so 38.4 um is level 2 (not level 4)
    levels = [dict(path=str(i), um=9.6 * 2 ** i, shape=[1, 1, 1], chunks=[1, 1, 1]) for i in range(6)]
    assert up.pick_level(levels, 38.4)["path"] == "2"
    assert up.pick_level(levels, 40.0)["path"] == "2"
    assert up.pick_level(levels, 9.6)["path"] == "0"


def spiral_plane(n=400, c=(210, 190), pitch=14, hole=12):
    yy, xx = np.mgrid[:n, :n]
    r = np.hypot(yy - c[0], xx - c[1])
    th = np.arctan2(yy - c[0], xx - c[1])
    s = (r - hole - th / (2 * np.pi) * pitch) % pitch
    plane = np.zeros((n, n), np.uint8)
    plane[(s < 4) & (r > hole) & (r < 170)] = 255
    return plane


def test_hole_and_ring_find_the_centre_of_a_clean_spiral():
    p = spiral_plane()
    for name in ("hole", "ring"):
        cy, cx, _ = up.METHODS[name](p)
        assert np.hypot(cy - 210, cx - 190) < 12, name


def test_empty_plane_gives_no_estimate():
    z = np.zeros((300, 300), np.uint8)
    assert up.centre_hole(z) is None and up.centre_ring(z) is None
