"""Tests for tools/sheet_tracer on phantom_scroll phantoms (synthetic only; no real scan data)."""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("zarr")

ROOT = Path(__file__).resolve().parent.parent
for d in ("sheet_tracer", "phantom_scroll"):
    sys.path.insert(0, str(ROOT / "tools" / d))

import benchmark as bm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import sheet_tracer as st  # noqa: E402
from ssc_io import load_mesh  # noqa: E402

SIZE, STEP = 192, 3.0
PARAMS = st.Params(step_vox=STEP, max_rows=41, max_cols=41)


@pytest.fixture(scope="module")
def ph():
    out = {}
    for name in ("round", "merged"):
        sc = ps.Scroll(bm.make_params(name, SIZE, 0))
        vol, lab = sc.render()
        out[name] = (sc, vol, lab)
    return out


def seed_on(sc, k):
    tr = sc.turn_surface(k)
    return tr[tr.shape[0] // 2, tr.shape[1] // 2]          # mid angle: away from the angle seam


def on_turn_fraction(res, lab, k):
    pts = res["points"][res["accepted"]]
    ix = np.rint(pts[:, ::-1]).astype(int)
    return float(np.mean(lab[ix[:, 0], ix[:, 1], ix[:, 2]] == k))


@pytest.mark.parametrize("k", [1, 2])
def test_round_phantom_stays_on_its_turn(ph, k):
    sc, vol, lab = ph["round"]
    res = st.trace(vol, seed_on(sc, k), PARAMS)
    assert res["accepted"].sum() > 800
    assert on_turn_fraction(res, lab, k) >= 0.95


def test_merged_phantom_reports_leak(ph):
    sc, vol, lab = ph["merged"]
    for k in (1, 2):
        res = st.trace(vol, seed_on(sc, k), PARAMS)
        f = on_turn_fraction(res, lab, k)
        print(f"merged phantom, seed on turn {k}: {100 * f:.1f}% of {res['accepted'].sum()} points on turn {k}, "
              f"{100 * (1 - f):.1f}% leaked")
        assert res["accepted"].sum() > 200 and f > 0.5          # a floor, not a claim: the number is the report


def test_deterministic_outputs(ph, tmp_path):
    sc, vol, _ = ph["round"]
    seed = seed_on(sc, 1)
    files = []
    for i in range(2):
        res = st.trace(vol, seed, PARAMS)
        o = tmp_path / f"o{i}"
        st.write_outputs(str(o), res, PARAMS, seed)
        files.append({n: (o / n).read_bytes() for n in ("x.tif", "y.tif", "z.tif", "growth_log.json")})
    assert files[0] == files[1]


def test_output_is_valid_tifxyz_and_log_is_complete(ph, tmp_path):
    sc, vol, _ = ph["round"]
    seed = seed_on(sc, 1)
    p = st.Params(step_vox=STEP, max_rows=41, max_cols=41, max_normal_turn_deg=2.0)   # forces rejections
    res = st.trace(vol, seed, p)
    st.write_outputs(str(tmp_path / "t"), res, p, seed)
    m = load_mesh(str(tmp_path / "t"))
    assert m.valid.sum() == res["accepted"].sum() and m.scale == (1 / STEP, 1 / STEP)
    meta = json.loads((tmp_path / "t" / "meta.json").read_text())
    assert meta["format"] == "tifxyz" and meta["type"] == "seg"
    log = json.loads((tmp_path / "t" / "growth_log.json").read_text())
    assert log["rejections"] and all(r["reason"] in {"no_peak", "normal_turn", "self_intersection", "volume_edge",
                                                     "step_stretch", "bad_normal"} for r in log["rejections"])
    assert Counter(r["reason"] for r in log["rejections"])["normal_turn"] > 0
    assert log["summary"]["n_rejections"] == len(log["rejections"])


def test_seed_in_gap_stops_immediately(ph):
    sc, vol, _ = ph["round"]
    tr = sc.trace(1.5)                                      # half way between turn 1 and turn 2
    gap = tr[tr.shape[0] // 2, tr.shape[1] // 2]
    with pytest.raises(st.SeedError, match="gap"):
        st.trace(vol, gap, PARAMS)


def test_seed_outside_volume(ph):
    _, vol, _ = ph["round"]
    with pytest.raises(st.SeedError, match="outside"):
        st.trace(vol, [-5, 10, 10], PARAMS)


def test_cli_exit_codes(ph, tmp_path):
    sc, vol, _ = ph["round"]
    np.save(tmp_path / "v.npy", vol)
    gap = sc.trace(1.5)[40, 30]
    assert st.main(["--npy", str(tmp_path / "v.npy"), "--seed", *map(str, gap), "--out", str(tmp_path / "g")]) == 3
    s = seed_on(sc, 1)
    assert st.main(["--npy", str(tmp_path / "v.npy"), "--seed", *map(str, s), "--out", str(tmp_path / "ok"),
                    "--step-vox", "3", "--max-rows", "21", "--max-cols", "21"]) == 0
    assert (tmp_path / "ok" / "x.tif").exists()
