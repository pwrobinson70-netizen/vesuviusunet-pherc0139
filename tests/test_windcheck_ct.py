"""Tests for tools/upstream/windcheck/ct_aware_check.py and its trace_auditor hook (ours; windcheck's own test is in tools/upstream/windcheck/tests/)."""
import os
import shutil
import sys

import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("tifffile")
ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
for d in ("upstream/windcheck", "sheet_spacing_check", "phantom_scroll", "trace_auditor"):
    sys.path.insert(0, os.path.join(ROOT, "tools", *d.split("/")))
import ct_aware_check as wc  # noqa: E402
import phantom_defects as pdef  # noqa: E402

HAVE_CXX = bool(wc.build_engine())
needs_engine = pytest.mark.skipif(not HAVE_CXX, reason="no C++ compiler to build windcheck's engine")
PITCH = 11.0


def slab_volume(n=64, zs=(20.0, 31.0, 42.0), sigma=1.5):
    z = np.arange(n, dtype=np.float32)[:, None, None]
    vol = np.full((n, n, n), 0.06, np.float32)
    for z0 in zs:
        vol += 0.74 * np.exp(-0.5 * ((z - z0) / sigma) ** 2)
    return (255 * vol).astype(np.float32)


def plane(z0, n=24, step=2.0, x0=8.0):
    r, c = np.mgrid[0:n, 0:n].astype(np.float32)
    return np.stack([x0 + c * step, x0 + r * step, np.full_like(c, z0)], -1), np.ones((n, n), bool)


def test_params_and_flags():
    p = wc.Params()
    assert p.pitch_vox is None and p.min_crossings == 1 and p.exclude == 2
    import argparse
    ap = argparse.ArgumentParser()
    wc.add_flags(ap)
    a = ap.parse_args(["--stride", "3", "--any-diagonal", "--pitch-vox", "11"])
    q = wc.params_from(a)
    assert q.stride == 3 and q.any_diagonal and q.pitch_vox == 11.0


def test_off_sheet_on_and_off_a_sheet():
    vol = slab_volume()
    P, v = plane(31.0)
    on = wc.off_sheet(P, v, vol, wc.Params(pitch_vox=PITCH))
    assert on["status"] == wc.PASS and on["off"] == 0
    P2, _ = plane(31.0 + 0.5 * PITCH)                     # midway between two sheets
    off = wc.off_sheet(P2, v, vol, wc.Params(pitch_vox=PITCH))
    assert off["status"] == wc.FAIL and off["off_fraction"] > 0.9
    near, _ = plane(31.0 + 1.0)                           # 1 voxel off, inside the 0.2-pitch tolerance (2.2 voxels)
    assert wc.off_sheet(near, v, vol, wc.Params(pitch_vox=PITCH))["status"] == wc.PASS
    assert wc.off_sheet(near, v, vol, wc.Params(pitch_vox=PITCH, off_tol_pitches=0.05))["status"] == wc.FAIL    # the tolerance is a flag
    assert wc.off_sheet(P, v, vol, wc.Params())["status"] == wc.NJ                                           # no pitch -> not judged


def test_off_sheet_local_defect_is_caught_by_the_block_rule():
    vol = slab_volume()
    P, v = plane(31.0, n=40, step=1.2, x0=8.0)
    P[10:22, 10:22, 2] += 0.5 * PITCH                      # a 12x12-cell patch halfway between sheets: ~9% of the grid
    r = wc.off_sheet(P, v, vol, wc.Params(pitch_vox=PITCH, max_off_fraction=0.5))
    assert r["status"] == wc.FAIL and r["worst_block_off_fraction"] >= 0.5
    r2 = wc.off_sheet(P, v, vol, wc.Params(pitch_vox=PITCH, max_off_fraction=0.5, block_off_fraction=1.1))
    assert r2["status"] == wc.PASS                         # block rule switched off by its flag


def test_off_sheet_solid_volume_is_not_judged_and_out_of_volume_too():
    vol = np.full((64, 64, 64), 200.0, np.float32)
    P, v = plane(31.0)
    assert wc.off_sheet(P, v, vol, wc.Params(pitch_vox=PITCH))["status"] == wc.NJ            # no contrast at all
    vol[:, :, :40] = 10.0                                                                      # air on one side, a solid block on the other
    P2, v2 = plane(31.0, x0=40.0, n=10)                                                        # trace inside the solid block (x >= 40)
    r = wc.off_sheet(P2, v2, vol, wc.Params(pitch_vox=PITCH))
    assert r["status"] == wc.NJ and r["judged"] == 0                                           # bright everywhere: no ridge to find
    P2, _ = plane(500.0)
    assert wc.off_sheet(P2, v, slab_volume(), wc.Params(pitch_vox=PITCH))["status"] == wc.NJ


def hairpin(gap, cross=False, arm=40, width=8, pitch=6.0, cap=10):
    cols = arm + cap + arm
    pts = np.zeros((width, cols, 3), np.float32)
    for j in range(width):
        y = j * pitch
        for i in range(arm):
            pts[j, i] = (i * pitch, y, 0.0)
        for k in range(cap):
            th = np.pi * k / (cap - 1)
            pts[j, arm + k] = (arm * pitch + np.sin(th) * gap * 0.5, y, gap * 0.5 * (1 - np.cos(th)))
        for i in range(arm):
            z = gap - 2.0 * gap * (i / max(1, arm - 1)) if cross else gap
            pts[j, arm + cap + i] = ((arm - 1 - i) * pitch, y, z)
    return pts, np.ones((width, cols), bool)


@needs_engine
def test_self_intersection_tight_fold_passes_and_crossing_fails():
    P, v = hairpin(3.0)
    assert wc.self_intersection(P, v, wc.Params())["status"] == wc.PASS            # tight but disjoint
    P, v = hairpin(6.0, cross=True)
    r = wc.self_intersection(P, v, wc.Params())
    assert r["status"] == wc.FAIL and min(r["transverse_by_diagonal"]) > 0
    assert wc.self_intersection(P, v, wc.Params(min_crossings=10 ** 9))["status"] == wc.PASS    # threshold is a flag
    flat, fv = plane(0.0, n=30, step=6.0)
    assert wc.self_intersection(flat, fv, wc.Params())["status"] == wc.PASS


def test_engine_missing_is_not_judged(monkeypatch):
    monkeypatch.setattr(wc, "build_engine", lambda path=None: None)
    P, v = plane(0.0)
    assert wc.self_intersection(P, v, wc.Params())["status"] == wc.NJ
    assert wc.check_trace(P, v, None, wc.Params())["verdict"] == wc.NJ


@needs_engine
def test_check_trace_verdict_combines_and_cli(tmp_path, capsys):
    vol = slab_volume()
    np.save(tmp_path / "v.npy", vol)
    P, v = plane(31.0)
    import phantom_scroll as ps
    ps.write_tifxyz(str(tmp_path / "t"), P, (0.5, 0.5))
    assert wc.main([str(tmp_path / "t"), "--npy", str(tmp_path / "v.npy"), "--pitch-vox", "11"]) == 0
    P2, _ = plane(36.5)
    ps.write_tifxyz(str(tmp_path / "t2"), P2, (0.5, 0.5))
    assert wc.main([str(tmp_path / "t2"), "--npy", str(tmp_path / "v.npy"), "--pitch-vox", "11", "--json", str(tmp_path / "o.json")]) == 1
    assert os.path.exists(tmp_path / "o.json")
    assert wc.main([str(tmp_path / "nothing")]) == 2


def test_trace_auditor_hook_is_off_by_default():
    import trace_auditor as ta
    assert ta.Params().windcheck is False
    ap = ta.build_parser()
    a = ap.parse_args(["x", "--zarr", "z", "--out-dir", "o", "--windcheck", "--wc-stride", "3", "--wc-min-crossings", "2"])
    assert a.windcheck and a.wc__stride == 3 and a.wc__min_crossings == 2
    assert ap.parse_args(["x", "--zarr", "z", "--out-dir", "o"]).wc__stride is None


@pytest.fixture(scope="module")
def folded(tmp_path_factory):
    import benchmark as bm
    import phantom_scroll as ps
    from ssc_io import load_mesh
    out = str(tmp_path_factory.mktemp("folded"))
    p = bm.make_params("folded", 96, 0)
    sc, vol, _l, _t = ps.build(p, out, zarr=False)
    turns = [load_mesh(os.path.join(out, "surfaces", f"turn_{k:02d}")) for k in range(p.turns)]
    return p, sc, vol, turns


@needs_engine
def test_planted_fold_phantom(folded):
    """True traces incl. the S-shaped pleat: no crossing, on a sheet.  Planted cut: off-sheet.  Planted crossing: self-intersection."""
    p, sc, vol, turns = folded
    wp = wc.Params(pitch_vox=p.pitch)
    for k, m in enumerate(turns):
        P, v = wc.mesh_arrays(m)
        r = wc.check_trace(P, v, vol, wp)
        assert r["verdict"] == wc.PASS, (k, [c["reason"] for c in r["checks"]])
    P, v = wc.mesh_arrays(turns[2])
    a, b = pdef.fold_window(P, v)
    assert 0 < a < b < P.shape[1]
    cut = wc.check_trace(pdef.cut(P, a, b), v, vol, wp)
    assert {c["check"]: c["status"] for c in cut["checks"]} == {"self_intersection": wc.PASS, "off_sheet": wc.FAIL}
    N = wc.normals(P, v)
    cr = wc.check_trace(pdef.cross(P, N, a, b, 0.75 * 8 * 96 / 128), v, vol, wp)
    assert {c["check"]: c["status"] for c in cr["checks"]}["self_intersection"] == wc.FAIL


@needs_engine
def test_auditor_adds_one_windcheck_verdict(folded):
    import trace_auditor as ta
    from ssc_io import ArrayVolume
    p, sc, vol, turns = folded
    cl = sc.centre_line()
    centre = ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf)
    heights = [float(round(f * (p.nz - 1))) for f in (0.25, 0.4, 0.5, 0.6, 0.75)]
    ssf_p, ssc_p = ta.ssf.Params(vertical=1), ta.ssc.Params(band_height_vox=float(heights[1] - heights[0]))
    av = ArrayVolume(vol)
    base = ta.audit([turns[2]], av, heights, centre, ta.Params(), ssf_p, ssc_p)["traces"][0]
    assert not [c for c in base["checks"] if c["check"] == "windcheck"]
    withw = ta.audit([turns[2]], av, heights, centre, ta.Params(windcheck=True), ssf_p, ssc_p, wc_p=wc.Params(pitch_vox=p.pitch))["traces"][0]
    w = [c for c in withw["checks"] if c["check"] == "windcheck"]
    assert len(w) == 1 and w[0]["status"] in (ta.PASS, ta.FAIL, ta.NJ) and len(w[0]["parts"]) == 2
    assert len(withw["checks"]) == len(base["checks"]) + 1
    # a planted crossing turns the verdict to FAIL through the windcheck check
    P, v = wc.mesh_arrays(turns[2])
    a, b = pdef.fold_window(P, v)
    Q = pdef.cross(P, wc.normals(P, v), a, b, 6.0)
    import types
    bad = types.SimpleNamespace(**{**vars(turns[2]), "x": Q[..., 0], "y": Q[..., 1], "z": Q[..., 2], "name": "bad"})
    badr = ta.audit([bad], av, heights, centre, ta.Params(windcheck=True), ssf_p, ssc_p, wc_p=wc.Params(pitch_vox=p.pitch))["traces"][0]
    assert [c for c in badr["checks"] if c["check"] == "windcheck"][0]["status"] == ta.FAIL and badr["verdict"] == ta.FAIL
