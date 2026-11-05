"""Tests for tools/ink_sample: a planted 3-D ink volume read back onto the right trace (and not onto the next sheet)."""
import dataclasses
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("zarr")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "tools" / "phantom_scroll", ROOT / "tools" / "ink_sample", ROOT / "tools" / "ink_infer"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import phantom_scroll as ps  # noqa: E402
import ink_sample as isp  # noqa: E402
from surface import InputError, load_mesh, resample_mesh  # noqa: E402
from scipy.ndimage import map_coordinates  # noqa: E402

SIZE = 128


def iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


@pytest.fixture(scope="module")
def phantom(tmp_path_factory):
    """Phantom with planted ink + a 3-D ink zarr (255 where the ink brightened the sheet, else 0)."""
    out = str(tmp_path_factory.mktemp("ink_phantom"))
    p = ps.make_params("round", size=SIZE, seed=3)
    p = dataclasses.replace(p, ink=True, ink_turn=1, ink_text="IN", ink_delta=0.10)
    sc, vol, lab, truth = ps.build(p, out, zarr=True)
    mask = ps.ink_mask_image(p, sc.n_rows(), sc.n_cols())
    ink = np.zeros(p.shape, np.uint8)
    for z0 in range(0, p.shape[0], 32):
        z1 = min(p.shape[0], z0 + 32)
        with_ink, _ = sc.render_slab(z0, z1, mask)
        without, _ = sc.render_slab(z0, z1, None)
        ink[z0:z1] = np.where(np.abs(with_ink - without) > 1e-6, 255, 0).astype(np.uint8)
    assert ink.any(), "phantom produced no ink voxels"
    ps.write_zarr(os.path.join(out, "ink.zarr"), ink)
    return SimpleNamespace(root=out, p=p, truth=truth)


def surface_label(ph, step):
    """Planted ink label on the ink-turn surface grid at `step` (same rule as ink_infer/phantom_e2e.load_phantom)."""
    from PIL import Image
    t = ph.truth["ink"]["turn"]
    mesh = load_mesh(os.path.join(ph.root, "surfaces", f"turn_{t:02d}"))
    surf = resample_mesh(mesh, step)
    m = np.asarray(Image.open(os.path.join(ph.root, ph.truth["ink"]["mask"]))) > 0
    sx, sy = mesh.scale
    H, W = surf.shape
    rr, cc = np.meshgrid(np.arange(H) * step * sy, np.arange(W) * step * sx, indexing="ij")
    return map_coordinates(m.astype(np.float32), [rr, cc], order=0, mode="nearest") > 0.5, surf.valid


def args(ph, trace, out, **kw):
    a = isp.build_parser().parse_args(["--trace", trace, "--ink-zarr", os.path.join(ph.root, "ink.zarr"), "--out", out])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def run_on(ph, turn, out, **kw):
    a = args(ph, os.path.join(ph.root, "surfaces", f"turn_{turn:02d}"), out, **kw)
    mx, mn, surf = isp.run(a, log=lambda m: None)
    return mx, mn, surf, a


@pytest.mark.parametrize("level", [0, 1])
def test_right_trace_recovers_the_planted_ink(phantom, tmp_path, level):
    # Output pixels are placed on whole cells of the planted mask (grid_step voxels apart). At finer steps
    # half the pixels sit exactly between two mask cells, where the planted truth itself is ambiguous
    # (the renderer rounds half to even); measured: step 1 at level 0 gives IoU 0.77 overall but 1.0 on
    # the whole-cell pixels, so the shortfall is the label, not the sampler.
    t = phantom.truth["ink"]["turn"]
    step = max(float(2 ** level), phantom.p.grid_step)
    mx, mn, surf, a = run_on(phantom, t, str(tmp_path / f"L{level}"), level=level, step=step)
    lab, valid = surface_label(phantom, step)
    ok = valid & surf.valid
    pred = (np.nan_to_num(mx) > 0.5) & ok
    score = iou(pred, lab & ok)
    assert score >= 0.9, f"IoU {score:.3f} on the true ink trace at level {level}"
    assert np.isnan(mx[~surf.valid]).all()
    assert (np.nan_to_num(mn) <= np.nan_to_num(mx) + 1e-6).all()


@pytest.mark.parametrize("shift", [-1, 1])
def test_trace_one_sheet_away_does_not(phantom, tmp_path, shift):
    t = phantom.truth["ink"]["turn"]
    step = phantom.p.grid_step
    mx, _, surf, _ = run_on(phantom, t + shift, str(tmp_path / f"s{shift}"), step=step)
    lab, valid = surface_label(phantom, step)
    H, W = min(lab.shape[0], mx.shape[0]), min(lab.shape[1], mx.shape[1])    # neighbour turn grid can differ in width
    lab, valid = lab[:H, :W], valid[:H, :W]
    ok = valid & surf.valid[:H, :W]
    pred = (np.nan_to_num(mx[:H, :W]) > 0.5) & ok
    score = iou(pred, lab & ok)
    assert score <= 0.2, f"IoU {score:.3f} on a trace one sheet away ({shift:+d})"


def test_outputs_and_meta(phantom, tmp_path):
    import tifffile
    from PIL import Image
    out = str(tmp_path / "o")
    mx, mn, surf, a = run_on(phantom, phantom.truth["ink"]["turn"], out, thumb_max=64)
    for f in ("ink_max.tif", "ink_mean.tif", "ink_max_thumb.png", "meta.json"):
        assert os.path.isfile(os.path.join(out, f)), f
    r = tifffile.imread(os.path.join(out, "ink_max.tif"))
    assert r.dtype == np.float32 and r.shape == surf.shape
    np.testing.assert_array_equal(np.isnan(r), np.isnan(mx))
    th = Image.open(os.path.join(out, "ink_max_thumb.png"))
    assert max(th.size) <= 64
    meta = json.load(open(os.path.join(out, "meta.json")))
    assert meta["offsets_level0"] == [-4.0, 4.0, 9] and meta["level"] == 0


def test_offsets_scale_with_level():
    np.testing.assert_allclose(isp.normal_offsets(-4, 4, 0), np.arange(-4, 5))
    np.testing.assert_allclose(isp.normal_offsets(-4, 4, 2), np.arange(-4, 5) * 4.0)
    np.testing.assert_allclose(isp.normal_offsets(-1, 1, 1, 0.5), [-2, -1, 0, 1, 2])
    with pytest.raises(InputError):
        isp.normal_offsets(2, 1, 0)


def test_cli_reports_bad_input(tmp_path, capsys):
    rc = isp.main(["--trace", str(tmp_path / "nope"), "--ink-zarr", str(tmp_path / "nope.zarr"), "--out", str(tmp_path / "o")])
    assert rc == 2
    assert "ink_sample:" in capsys.readouterr().err


def test_offset_range_decides_what_is_read(phantom, tmp_path):
    """The neighbour trace sees the ink only once the offset range spans a whole sheet pitch: the range is not cosmetic."""
    t = phantom.truth["ink"]["turn"]
    reach = float(np.ceil(phantom.p.pitch + phantom.p.thickness))
    narrow, _, _, _ = run_on(phantom, t + 1, str(tmp_path / "n"), step=phantom.p.grid_step)
    wide, _, _, _ = run_on(phantom, t + 1, str(tmp_path / "w"), step=phantom.p.grid_step, lo=-reach, hi=reach)
    assert np.nanmax(narrow) < 0.5 <= np.nanmax(wide)


@pytest.fixture(scope="module")
def http_root(phantom):
    """Serve the phantom folder over plain HTTP on localhost (what the public bucket looks like to the reader)."""
    import functools
    import http.server
    import threading
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=phantom.root)
    h.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_http_reader_matches_local(phantom, http_root, tmp_path, monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    t = phantom.truth["ink"]["turn"]
    for level in (0, 1):
        loc, _, _, _ = run_on(phantom, t, str(tmp_path / f"loc{level}"), level=level)
        rem, _, _, _ = run_on(phantom, t, str(tmp_path / f"rem{level}"), level=level, ink_zarr=http_root + "/ink.zarr")
        np.testing.assert_array_equal(np.isnan(loc), np.isnan(rem))
        np.testing.assert_allclose(np.nan_to_num(loc), np.nan_to_num(rem), atol=1e-6)


def test_http_reader_zarr_v3_and_partial_edge_chunks(tmp_path, monkeypatch):
    import functools
    import http.server
    import threading
    import zarr
    import http_zarr
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (37, 50, 61)).astype(np.uint8)
    g = zarr.open_group(str(tmp_path / "v3.zarr"), mode="w", zarr_format=3)
    g.create_array("0", shape=a.shape, chunks=(16, 16, 32), dtype="u1")[...] = a
    g2 = zarr.open_group(str(tmp_path / "v2.zarr"), mode="w", zarr_format=2)
    g2.create_array("0", shape=a.shape, chunks=(16, 16, 32), dtype="u1")[...] = a
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    h.log_message = lambda *x, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        for name in ("v3.zarr", "v2.zarr"):
            arr, _ = http_zarr.open_level(f"{base}/{name}", 0)
            assert arr.shape == a.shape and arr.dtype == np.uint8
            np.testing.assert_array_equal(arr[3:35, 10:49, 20:61], a[3:35, 10:49, 20:61])
            np.testing.assert_array_equal(arr[0:37, 0:50, 0:61], a)
    finally:
        srv.shutdown()


def test_trace_offset_and_scale(phantom, tmp_path):
    """A trace written in a shifted, half-resolution frame lands back on the ink after --trace-offset/--trace-scale."""
    import shutil
    import tifffile
    t = phantom.truth["ink"]["turn"]
    src = os.path.join(phantom.root, "surfaces", f"turn_{t:02d}")
    dst = str(tmp_path / "moved")
    shutil.copytree(src, dst)
    off = np.array([5.0, -3.0, 2.0])
    for k, ax in enumerate("xyz"):
        g = tifffile.imread(os.path.join(src, f"{ax}.tif")).astype(np.float64)
        bad = g == -1
        g = g / 2.0 - off[k]                                # trace frame: half resolution, shifted
        g[bad] = -1
        tifffile.imwrite(os.path.join(dst, f"{ax}.tif"), g.astype(np.float32))
    meta = json.load(open(os.path.join(src, "meta.json")))
    meta["scale"] = [s * 2.0 for s in meta["scale"]]
    json.dump(meta, open(os.path.join(dst, "meta.json"), "w"))
    step = phantom.p.grid_step
    ref, _, _, _ = run_on(phantom, t, str(tmp_path / "ref"), step=step)
    a = args(phantom, dst, str(tmp_path / "o"), step=step, trace_offset=list(off), trace_scale=2.0)
    got, _, _ = isp.run(a, log=lambda m: None)
    np.testing.assert_allclose(np.nan_to_num(got), np.nan_to_num(ref), atol=1e-3)


def test_profile_peaks_on_the_trace(phantom, tmp_path):
    t = phantom.truth["ink"]["turn"]
    out = str(tmp_path / "p")
    run_on(phantom, t, out, profile=12.0)
    rows = [l.split(",") for l in open(os.path.join(out, "profile.csv")).read().splitlines()[1:]]
    off = np.array([float(r[0]) for r in rows])
    val = np.array([float(r[2]) for r in rows])
    assert len(off) == 25 and abs(off[np.argmax(val)]) <= 1
    assert val[np.abs(off) >= 8].max() < 0.25 * val.max()
    assert "profile" in json.load(open(os.path.join(out, "meta.json")))


def test_http_chunk_cache_is_bounded():
    import http_zarr
    c = http_zarr._LRU(3)
    for i in range(10):
        c[i] = i
    assert list(c) == [7, 8, 9]
    assert 8 in c and list(c) == [7, 9, 8]
    c[10] = 10
    assert list(c) == [9, 8, 10]
