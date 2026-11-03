"""Tests for tools/trace_repair on phantom_scroll traces with planted switches (synthetic only)."""
import filecmp
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("zarr")

ROOT = Path(__file__).resolve().parent.parent
for d in ("trace_repair", "trace_auditor", "phantom_scroll"):
    sys.path.insert(0, str(ROOT / "tools" / d))

import benchmark as bm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import trace_auditor as ta  # noqa: E402
import trace_repair as tr  # noqa: E402
from ssc_io import ArrayVolume, load_mesh  # noqa: E402

SIZE = 192


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("rep")
    p = bm.make_params("round", SIZE, 0)
    sc = ps.Scroll(p)
    vol, _ = sc.render()
    np.save(d / "v.npy", vol)
    cl = sc.centre_line()
    centre = ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf)
    H = [float(round(f * (p.nz - 1))) for f in (0.25, 0.4, 0.5, 0.6, 0.75)]
    return dict(dir=d, sc=sc, p=p, vol=ArrayVolume(vol), centre=centre, H=H)


def audit(env, mesh):
    ssf_p, ssc_p = ta.ssf.Params(vertical=1), ta.ssc.Params(band_height_vox=env["H"][1] - env["H"][0])
    rep = ta.audit([mesh], env["vol"], env["H"], env["centre"], ta.Params(), ssf_p, ssc_p)
    rep.pop("polar")
    return rep


def plant(env, name, w):
    path = env["dir"] / name
    ps.write_tifxyz(str(path), env["sc"].trace(w), (1 / env["p"].grid_step,) * 2)
    return path


def run_repair(env, path):
    rep = audit(env, load_mesh(str(path)))
    verdict = rep["traces"][0]["verdict"]
    (env["dir"] / f"{path.name}.json").write_text(json.dumps(dict(result=rep), default=float))
    out = env["dir"] / f"{path.name}_fixed"
    rc = tr.main([str(path), "--audit", str(env["dir"] / f"{path.name}.json"), "--npy", str(env["dir"] / "v.npy"), "--out", str(out)])
    assert rc == 0
    return verdict, out, audit(env, load_mesh(str(out)))["traces"][0]["verdict"]


def fraction_on(env, out, target, anchor_col=0):
    """Fraction of valid points whose CONTINUOUS winding coordinate is within 0.35 of `target`.
    phi is unwrapped along each row, so a trace that follows its sheet past the angle seam (a spiral sheet
    continues as the next 'turn' there) is not mislabelled."""
    m = load_mesh(str(out))
    sc, p = env["sc"], env["p"]
    pts = np.stack([m.x, m.y, m.z], -1)
    q = sc.inverse(pts.reshape(-1, 3).T[::-1])
    rel = np.stack([q[2], q[1]]) - sc.axis(q[0])
    _, phi, r = sc.winding(rel)
    phi, r = phi.reshape(m.valid.shape), r.reshape(m.valid.shape)
    u = np.full(m.valid.shape, np.nan)
    for i in range(phi.shape[0]):
        v = m.valid[i]
        ph = np.unwrap(phi[i, v])
        k = int(np.flatnonzero(np.flatnonzero(v) == anchor_col)[0])      # the anchor column is on the true sheet
        ph = ph + 2 * np.pi * np.round((phi[i, v][k] - ph[k]) / (2 * np.pi))
        u[i, v] = (r[i, v] - p.r0) / p.pitch - ph / (2 * np.pi)
    ok = np.abs(u - np.asarray(target)) < 0.35
    return float(np.mean(ok[m.valid]))


def ramp(env, turn, steps):
    """w grid: `turn` plus sum of delta * (col >= c) for (c, delta) in steps."""
    nr, nc = env["sc"].n_rows(), env["sc"].n_cols()
    c = np.arange(nc)[None, :] * np.ones((nr, 1))
    w = np.full((nr, nc), float(turn))
    for col, delta in steps:
        w += delta * (c >= int(nc * col))
    return w


@pytest.mark.parametrize("name,steps", [("single", [(0.30, 1.0)]), ("inward", [(0.45, -1.0)]),
                                        ("double_out_back", [(0.30, 1.0), (0.60, -1.0)]),
                                        ("double_hop", [(0.30, 2.0)])])
def test_planted_switches_fail_then_pass_after_repair(env, name, steps):
    w = ramp(env, 1 if name != "inward" else 2, steps)
    path = plant(env, name, w)
    before, out, after = run_repair(env, path)
    assert before == ta.FAIL
    assert after == ta.PASS
    base = float(w[0, 0])
    assert fraction_on(env, out, np.full_like(w, base)) >= 0.9
    s = json.loads((out / "repair_summary.json").read_text())
    assert s["repaired"] and s["n_moved_over_half_voxel"] > 0
    assert (path / "x.tif").exists() and filecmp.cmp(path / "x.tif", env["dir"] / name / "x.tif", shallow=False)  # input untouched


def test_clean_trace_is_byte_identical(env):
    path = plant(env, "clean", np.full((env["sc"].n_rows(), env["sc"].n_cols()), 1.0))
    before, out, after = run_repair(env, path)
    assert before == ta.PASS and after == ta.PASS
    for f in ("x.tif", "y.tif", "z.tif", "meta.json"):
        assert (path / f).read_bytes() == (out / f).read_bytes()
    assert not json.loads((out / "repair_summary.json").read_text())["repaired"]


def test_refuses_to_overwrite(env):
    path = env["dir"] / "clean"
    rc = tr.main([str(path), "--audit", str(env["dir"] / "clean.json"), "--npy", str(env["dir"] / "v.npy"), "--out", str(path)])
    assert rc == 2


def test_origin_cell_repairs_the_far_side(env):
    """Mirrored case: the trace is right on the high-column side and hops onto the wrong sheet towards low columns."""
    w = ramp(env, 1, [(0.0, 1.0), (0.7, -1.0)])           # w = 2 for cols < 0.7 nc, 1 beyond
    path = plant(env, "mirror", w)
    rep = audit(env, load_mesh(str(path)))
    assert rep["traces"][0]["verdict"] == ta.FAIL
    (env["dir"] / "mirror.json").write_text(json.dumps(dict(result=rep), default=float))
    out = env["dir"] / "mirror_fixed"
    nr, nc = w.shape
    assert tr.main([str(path), "--audit", str(env["dir"] / "mirror.json"), "--npy", str(env["dir"] / "v.npy"), "--out", str(out),
                    "--origin-cell", str(nr // 2), str(nc - 1)]) == 0
    assert audit(env, load_mesh(str(out)))["traces"][0]["verdict"] == ta.PASS
    assert fraction_on(env, out, np.ones_like(w), anchor_col=nc - 1) >= 0.9
