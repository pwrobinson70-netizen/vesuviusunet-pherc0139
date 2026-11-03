"""Tests for tools/upstream/tifxyz_repair/geometric_repair.py (ours; upstream's own tests live in that folder's upstream_tests/)."""
import json
import os
import sys

import numpy as np
import pytest

tifffile = pytest.importorskip("tifffile")
pytest.importorskip("scipy")
ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "upstream", "tifxyz_repair"))
import geometric_repair as g  # noqa: E402
from tifxyz_repair.checks import validate_patch  # noqa: E402
from tifxyz_repair.core import load_patch  # noqa: E402

SAMPLE = os.path.join(ROOT, "testdata", "pherc_paris4_45um")


def write(d, P, scale=(0.05, 0.05), bbox="auto", mask=None):
    os.makedirs(d, exist_ok=True)
    for i, n in enumerate("xyz"):
        tifffile.imwrite(os.path.join(d, n + ".tif"), P[..., i].astype(np.float32))
    ok = ~(P == -1).any(-1)
    if bbox == "auto":
        bbox = [P[ok].min(0).tolist(), P[ok].max(0).tolist()]
    meta = {"format": "tifxyz", "type": "seg", "uuid": "t", "scale": list(scale)}
    if bbox is not None:
        meta["bbox"] = bbox
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"))
    if mask is not None:
        tifffile.imwrite(os.path.join(d, "mask.tif"), mask.astype(np.uint8))
    return str(d)


def plane(h=24, w=30, step=20.0):
    r, c = np.mgrid[0:h, 0:w].astype(np.float32)
    return np.stack([100 + c * step, 200 + r * step * 0.9 + c * 3, 500 + 0.3 * r * step], -1)


def test_interior_hole_and_edge_are_filled_exactly_on_a_plane(tmp_path):
    P = plane()
    truth = P.copy()
    P[8:11, 10:13] = -1                    # interior 3x3 hole
    P[:, :3] = -1                          # left edge, 3 columns
    d = write(tmp_path / "s", P)
    pa = load_patch(d)
    P2, v2, filled, meta, rep = g.repair(pa, g.Params())
    assert filled.sum() == 9 + 3 * 24 and v2.all()
    assert np.abs(P2 - truth).max() < 1e-2
    assert rep["invalid_after"] == 0


def test_depth_limit_and_off(tmp_path):
    P = plane()
    P[:, :6] = -1
    pa = load_patch(write(tmp_path / "s", P))
    _, v, f, _, _ = g.repair(pa, g.Params(max_rings=2))
    assert f.sum() == 2 * 24 and v[:, 4:].all() and not v[:, :4].any()      # only the 2 rings next to valid data
    _, v0, f0, _, _ = g.repair(pa, g.Params(max_rings=0))
    assert f0.sum() == 0 and (~v0).sum() == 6 * 24


def test_crease_fit_is_rejected(tmp_path):
    P = plane()
    P[12:, :, 2] += 400.0                  # a step of 20 grid-spacings: no plane fits across it
    P[12, 10:14] = -1
    pa = load_patch(write(tmp_path / "s", P))
    _, v, f, _, _ = g.repair(pa, g.Params(max_residual_frac=0.5))
    assert f.sum() == 0
    _, v, f, _, _ = g.repair(pa, g.Params(max_residual_frac=1e9))
    assert f.sum() == 4                    # the same cells ARE filled when the residual test is switched off (flag works)


def test_partial_sentinel_mask_and_z_nonpositive_are_invalid(tmp_path):
    P = plane()
    P[2, 2, 1] = -1                        # only y == -1 (FORMATS.md: any component)
    P[3, 3, 2] = 0                         # z <= 0 (loader rule)
    mask = np.full(P.shape[:2], 255, np.uint8)
    mask[4, 4] = 0                         # masked out; coordinates stay real
    pa = load_patch(write(tmp_path / "s", P, bbox=None, mask=mask))
    v = g.valid_vertices(pa)
    assert not v[2, 2] and not v[3, 3] and not v[4, 4] and v.sum() == v.size - 3
    P2, v2, f, meta, _ = g.repair(pa, g.Params(max_rings=0))
    assert (P2[2, 2] == -1).all() and (P2[4, 4] == -1).all()       # normalised to the (-1,-1,-1) marker
    ok = v2
    assert np.allclose(meta["bbox"][0], P2[ok].min(0)) and np.allclose(meta["bbox"][1], P2[ok].max(0))


def test_stale_bbox_recomputed_and_scale_rule(tmp_path):
    P = plane()
    d = write(tmp_path / "s", P, scale=(0.1, 0.1), bbox=[[0, 0, 0], [1, 1, 1]])
    pa = load_patch(d)
    _, _, _, meta, rep = g.repair(pa, g.Params())
    assert meta["scale"] == [0.1, 0.1] and not rep["scale"]["rewritten"]       # reported, not rewritten, by default
    assert "differs" in rep["scale"]["note"]
    assert meta["bbox"][1][0] > 500                                         # bbox no longer the stale [[0..],[1..]]
    _, _, _, meta2, rep2 = g.repair(pa, g.Params(fix_scale=True))
    assert rep2["scale"]["rewritten"] and abs(meta2["scale"][0] - 1 / 20.0) < 1e-3
    assert abs(meta2["scale"][1] - 1 / (np.median(np.linalg.norm(np.diff(P, axis=0), axis=-1)))) < 1e-4


def test_written_surface_roundtrips_through_upstream_loader(tmp_path):
    P = plane()
    P[5:9, 5:9] = -1
    P[:, -5:] = -1
    d = write(tmp_path / "s", P)
    pa = load_patch(d)
    P2, v2, f, meta, _ = g.repair(pa, g.Params())
    out = str(tmp_path / "out")
    g.write_patch(out, P2, v2, f, meta, g.Params())
    q = load_patch(out)
    assert q.mask is not None and q.mask.dtype == np.uint8 and q.mask.shape == v2.shape
    assert set(np.unique(q.mask)) <= {0, 255}
    assert (q.valid == v2).all()                                          # upstream's (VC3D-semantics) validity == ours
    assert not [x for x in validate_patch(q) if x["severity"] == "error"]
    assert q.x.dtype == np.float32
    assert json.load(open(os.path.join(out, "meta.json")))["repair"]["infilled_vertices"] == int(f.sum())


def test_cli_flags(tmp_path, capsys):
    d = write(tmp_path / "s", plane())
    assert g.main([d]) == 2                                              # nothing to do and no --dry-run
    assert g.main([d, "--dry-run"]) == 0 and not (tmp_path / "s" / "mask.tif").exists()
    out = str(tmp_path / "o")
    assert g.main([d, "--out", out, "--max-rings", "1", "--fit-radius", "3", "--min-neighbours", "8"]) == 0
    assert g.main([d, "--out", out]) == 2                                # refuses a non-empty directory
    assert g.main([d, "--in-place"]) == 0 and (tmp_path / "s" / "x.tif.bak").exists() and (tmp_path / "s" / "mask.tif").exists()
    assert g.main([str(tmp_path / "nothing"), "--dry-run"]) == 2


@pytest.mark.skipif(not os.path.isdir(SAMPLE), reason="public sample not present")
@pytest.mark.parametrize("name", ["20260623164704-w116-117", "20260623165230-w118-119"])
def test_real_sample_meshes(name, tmp_path):
    pa = load_patch(os.path.join(SAMPLE, name + ".tifxyz"))
    P, v = pa.points(), g.valid_vertices(pa)
    assert 5000 < (~v).sum() < 8000                                      # ~6k invalid points each (brief)
    P2, v2, f, meta, rep = g.repair(pa, g.Params())
    assert rep["invalid_after"] < rep["invalid_before"] - 1500 and f.sum() == rep["infilled"]
    assert abs(rep["spacing_voxels"]["columns"] - 20) < 1 and "agrees" in rep["scale"]["note"]
    assert (P2[v] == P[v]).all()                                         # valid vertices are never touched
    out = str(tmp_path / "o")
    g.write_patch(out, P2, v2, f, meta, g.Params())
    assert (load_patch(out).valid == v2).all()
    # hold-out: hide the outermost valid ring, estimate it back, compare with the real coordinates
    h = g.holdout(P, v, 1, g.Params())
    assert h["fill_rate"] > 0.9
    assert h["ours"]["rms"] < 0.5 * h["nearest_copy"]["rms"]
    assert h["ours"]["rms"] < g.grid_spacing(P, v)[0][0]                 # better than one grid step RMS
