"""Real VC3D output: the two public PHerc. Paris 4 (Scroll 1, CC BY-NC) tifxyz meshes in testdata/.

Small on purpose: it only checks that the readers load real files and that shape / dtype / validity
facts measured on 3 Nov 2026 still hold (see tools/realdata_run/RESULTS.md). No tool behaviour is tested here.
"""
import json
from pathlib import Path

import numpy as np
import pytest
import tifffile

from ssc_io import load_mesh

DATA = Path(__file__).resolve().parent.parent / "testdata" / "pherc_paris4_45um"
MESHES = {  # directory -> (rows, cols, invalid cells)
    "20260623164704-w116-117.tifxyz": (130, 354, 6451),
    "20260623165230-w118-119.tifxyz": (129, 357, 6161),
}

pytestmark = pytest.mark.skipif(not DATA.is_dir(), reason="testdata/pherc_paris4_45um not present")


@pytest.mark.parametrize("name", sorted(MESHES))
def test_real_tifxyz_loads(name):
    rows, cols, n_bad = MESHES[name]
    d = DATA / name
    for ax in "xyz":                                   # on disk: float32, (rows, cols), untiled
        a = tifffile.imread(d / f"{ax}.tif")
        assert a.dtype == np.float32 and a.shape == (rows, cols)
    m = load_mesh(d)
    assert m.shape == (rows, cols)
    assert m.x.dtype == np.float64                      # converted by ssc_io
    assert m.n_invalid == n_bad == int((~m.valid).sum())
    frac_valid = m.valid.mean()
    assert 0.8 < frac_valid < 0.9                       # ~86 % of cells hold a point
    for a in (m.x, m.y, m.z):                           # valid cells finite, invalid cells NaN
        assert np.isfinite(a[m.valid]).all() and np.isnan(a[~m.valid]).all()
    assert m.scale == pytest.approx((0.05, 0.05), rel=1e-6)
    # meta.json bbox is XYZ order and equals the valid-point extent
    bbox = np.array(json.loads((d / "meta.json").read_text())["bbox"])
    ext = np.array([[np.nanmin(m.x), np.nanmin(m.y), np.nanmin(m.z)], [np.nanmax(m.x), np.nanmax(m.y), np.nanmax(m.z)]])
    assert np.allclose(ext, bbox, atol=0.01)
    # grid step is 1/scale = 20 voxels; rows run along z
    assert np.nanmedian(np.hypot(np.diff(m.x, axis=1), np.diff(m.y, axis=1), np.diff(m.z, axis=1))) == pytest.approx(20, rel=0.05)
    assert np.nanmean(np.abs(np.diff(m.z, axis=0))) > 5 * np.nanmean(np.abs(np.diff(m.z, axis=1)))


def test_real_pair_shapes_differ():
    """Documents finding F1: adjacent real meshes do NOT share a grid shape (sheet_spacing_check requires it)."""
    a, b = (load_mesh(DATA / n).shape for n in sorted(MESHES))
    assert a != b
