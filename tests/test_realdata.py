"""Permanent regression check on real public data: PHerc. Paris 4 (Scroll 1, CC BY-NC), testdata/pherc_paris4_45um.

Every expected value below was recorded by brief 14 and is written up in tools/realdata_run/RESULTS.md (3 Nov 2026);
the section is named in a comment next to each constant. These tests pin what the tools DO on real data today.
Where RESULTS.md reports a tool misbehaving, the test states what correct behaviour would be and is marked
xfail(strict=True) with the finding id (F1..F5 from RESULTS.md; R14-2..R14-6 are the numbered items of its
"What did not work" list; P1..P9 its proposed follow-ups). When a fix lands the test XPASSes, strict mode turns that
into a failure, and the fixer removes the marker. See docs/REALDATA_STATUS.md.

The tools are run through their command lines in subprocesses (about 2 s each, about 30 s for the module), exactly as
a user would, with no tool default changed. Only flags RESULTS.md lists under "Flags and workarounds" are passed.
"""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("scipy")
pytest.importorskip("PIL")
import tifffile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "testdata" / "pherc_paris4_45um"
TOOLS = ROOT / "tools"
SLICES = DATA / "slices"
A_DIR = DATA / "20260623164704-w116-117.tifxyz"
B_DIR = DATA / "20260623165230-w118-119.tifxyz"

pytestmark = pytest.mark.skipif(not DATA.is_dir(), reason="testdata/pherc_paris4_45um not present")

sys.path.insert(0, str(TOOLS / "sheet_spacing_check"))
from ssc_io import load_mesh  # noqa: E402

VOX_UM = 45.532
HEIGHTS = (2073, 2600, 3128)
HEIGHTS_ARG = ",".join(str(h) for h in HEIGHTS)

# ---- recorded values ---------------------------------------------------------------------------------------------
# RESULTS.md "Task 1: format" table, and bbox from each mesh's meta.json (XYZ order; equals the valid-point extent).
MESH_FACTS = {
    "w116-117": dict(path=A_DIR, shape=(130, 354), n_invalid=6451,
                     bbox=[[605.1956787109375, 576.6908569335938, 1543.5128173828125],
                           [1859.7052001953125, 1824.4010009765625, 3655.55224609375]]),
    "w118-119": dict(path=B_DIR, shape=(129, 357), n_invalid=6161,
                     bbox=[[599.1924438476563, 571.7454223632813, 1545.0213623046875],
                           [1861.308349609375, 1824.8028564453125, 3655.0166015625]]),
}
VOLUME_SHAPE_YX = (2264, 2264)   # slice PNGs, testdata README ("shape [4071, 2264, 2264]")

# RESULTS.md "Task 2": umbilicus_finder --pitch-vox 8, slice index 0/1/2 = z 2073/2600/3128 (F2). (x, y) in voxels.
UMB_CENTRES = [(1160.94, 1021.93), (1150.36, 1075.80), (1150.36, 1204.61)]
UMB_TOL_PX = 3.0
UMB_BY_EYE_X_2600 = 1205.0       # "By eye ... about x 1205, y 1076" (RESULTS.md Task 2)
UMB_BY_EYE_TOL_PX = 25.0

# RESULTS.md "Task 3" table (defaults, padded copies): ct_pitch, clean, shared, skipped per height.
SPACING = {
    2073: dict(ct_pitch=17.0, clean=0.164, shared=0.798, skipped=0.000),
    2600: dict(ct_pitch=17.0, clean=0.088, shared=0.874, skipped=0.006),
    3128: dict(ct_pitch=14.0, clean=0.253, shared=0.661, skipped=0.012),
}
FRAC_TOL = 0.05                  # brief 18: fractions within 0.05
PITCH_REL_TOL = 0.10             # brief 18: pitch within 10 percent
MEASURED_PITCH_VOX = 9.5         # RESULTS.md "Pitch measurement": about 9.5 voxels (+-2)

# RESULTS.md "Task 4": switches with confidence >= 0.3 at default settings: (kind, z, col).
CONF_MIN = 0.3
SWITCHES_CONF = {
    "w116-117": {("horizontal", 2600, 283), ("horizontal", 2600, 292), ("horizontal", 2600, 325),
                 ("vertical", 2600, 287), ("vertical", 2600, 321)},
    "w118-119": {("horizontal", 2073, 81), ("horizontal", 2073, 87), ("horizontal", 2600, 45)},
}
SWITCH_TOTALS = {"w116-117": 34, "w118-119": 25}   # all switches, H + V
SWITCH_TOTAL_TOL = 2

# RESULTS.md "Task 5": auditor, estimated centre; verdict FAIL, switch_finder FAIL, winding_jumps FAIL on both meshes.
# Jump counts: RESULTS.md recorded 112 / 115 with trace_auditor from main b6c8782. fix/review-round2 (A1/A2: window
# cut at the line ends, bend-aware step) is merged into this branch and now gives 136 / 129 on the same inputs;
# verdicts and per-check statuses are unchanged. The test pins the post-round-2 counts (re-measured 3 Nov 2026).
AUDIT_JUMPS = {"w116-117": 136, "w118-119": 129}
AUDIT_JUMP_TOL = 5
AUDIT_CHECKS_A = {"switch_finder": "FAIL", "winding_jumps": "FAIL"}

# RESULTS.md "Task 6": every valid point with column > 120 moved radially outward by one pitch (9.5 voxels).
BREAK_COL = 120
BREAK_SHIFT_VOX = MEASURED_PITCH_VOX
BREAK_WINDOW = 8                 # "flagged at col 112-128"


# ---- helpers -----------------------------------------------------------------------------------------------------
def run_tool(tool, script, *args, ok_codes=(0, 1)):
    cmd = [sys.executable, str(TOOLS / tool / script), *[str(a) for a in args]]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert p.returncode in ok_codes, f"{' '.join(cmd)}\nrc={p.returncode}\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}"
    return p


PNG_ARGS = ["--png-dir", SLICES, "--png-pixel-um", VOX_UM, "--voxel-size-um", VOX_UM, "--heights", HEIGHTS_ARG]


def write_mesh(outdir, name, grids, meta_src):
    d = Path(outdir) / name
    d.mkdir(parents=True, exist_ok=True)
    for ax in "xyz":
        tifffile.imwrite(d / f"{ax}.tif", grids[ax].astype(np.float32))
    shutil.copy(Path(meta_src) / "meta.json", d / "meta.json")
    return d


def read_grids(d):
    return {ax: tifffile.imread(Path(d) / f"{ax}.tif").astype(np.float64) for ax in "xyz"}


@pytest.fixture(scope="module")
def centre_file(tmp_path_factory):
    """The finder's own (LOW) centres, relabelled to true z, as RESULTS.md Task 5 did (umbilicus_estimated.json)."""
    p = tmp_path_factory.mktemp("centre") / "umbilicus_estimated.json"
    p.write_text(json.dumps({"control_points": [{"z": z, "y": y, "x": x} for z, (x, y) in zip(HEIGHTS, UMB_CENTRES)]}))
    return p


@pytest.fixture(scope="module")
def padded_pair(tmp_path_factory):
    """RESULTS.md Task 3 workaround: pad both meshes with -1 to a common grid (F1)."""
    out = tmp_path_factory.mktemp("padded")
    ga, gb = read_grids(A_DIR), read_grids(B_DIR)
    h = max(ga["x"].shape[0], gb["x"].shape[0])
    w = max(ga["x"].shape[1], gb["x"].shape[1])
    dirs = []
    for src, g in ((A_DIR, ga), (B_DIR, gb)):
        padded = {}
        for ax in "xyz":
            q = np.full((h, w), -1.0)
            q[: g[ax].shape[0], : g[ax].shape[1]] = g[ax]
            padded[ax] = q
        dirs.append(write_mesh(out, src.name, padded, src))
    return dirs


@pytest.fixture(scope="module")
def broken_mesh(tmp_path_factory, centre_file):
    """Deliberately broken copy of w116-117: columns > BREAK_COL shifted outward by one pitch (built from the real mesh)."""
    cp = json.loads(centre_file.read_text())["control_points"]
    zs = np.array([c["z"] for c in cp], float)
    g = read_grids(A_DIR)
    valid = ~((g["x"] == -1) | (g["y"] == -1) | (g["z"] == -1))
    m = valid & (np.arange(g["x"].shape[1])[None, :] > BREAK_COL)
    cx = np.interp(g["z"][m], zs, [c["x"] for c in cp])
    cy = np.interp(g["z"][m], zs, [c["y"] for c in cp])
    dx, dy = g["x"][m] - cx, g["y"][m] - cy
    r = np.hypot(dx, dy)
    g["x"][m] += BREAK_SHIFT_VOX * dx / r
    g["y"][m] += BREAK_SHIFT_VOX * dy / r
    return write_mesh(tmp_path_factory.mktemp("broken"), A_DIR.name.replace("w116-117", "w116-117-BROKEN"), g, A_DIR)


@pytest.fixture(scope="module")
def spacing(padded_pair, tmp_path_factory):
    out = tmp_path_factory.mktemp("spacing") / "ssc.json"
    run_tool("sheet_spacing_check", "sheet_spacing_check.py", *padded_pair, *PNG_ARGS, "--global-pitch", "--out-json", out)
    return json.loads(out.read_text())["result"]["heights"]


def switch_run(mesh, tmp_path_factory, *extra):
    out = tmp_path_factory.mktemp("switch") / "sw.json"
    run_tool("sheet_switch_finder", "sheet_switch_finder.py", mesh, *PNG_ARGS, "--global-pitch", *extra, "--out-json", out)
    return json.loads(out.read_text())["result"]


@pytest.fixture(scope="module")
def switches(tmp_path_factory):
    return {k: switch_run(v["path"], tmp_path_factory) for k, v in MESH_FACTS.items()}


@pytest.fixture(scope="module")
def switches_broken(broken_mesh, tmp_path_factory):
    return switch_run(broken_mesh, tmp_path_factory)


def audit_run(mesh, centre_file, tmp_path_factory):
    out = tmp_path_factory.mktemp("audit")
    run_tool("trace_auditor", "trace_auditor.py", mesh, *PNG_ARGS, "--global-pitch", "--umbilicus", centre_file, "--out-dir", out)
    return json.loads((out / "audit.json").read_text())["result"]["traces"][0]


@pytest.fixture(scope="module")
def audits(centre_file, tmp_path_factory):
    return {k: audit_run(v["path"], centre_file, tmp_path_factory) for k, v in MESH_FACTS.items()}


@pytest.fixture(scope="module")
def audit_broken(broken_mesh, centre_file, tmp_path_factory):
    return audit_run(broken_mesh, centre_file, tmp_path_factory)


def umbilicus_rows(tmp_path_factory, *extra):
    out = tmp_path_factory.mktemp("uf")
    run_tool("umbilicus_finder", "umbilicus_finder.py", SLICES, "--pixel-um", VOX_UM, "--voxel-um", VOX_UM,
             "--z-start", 0, "--z-stop", 3, "--z-step", 1, *extra, "--out-dir", out, "--export-all")
    with open(out / "umbilicus.csv", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def umbilicus(tmp_path_factory):
    return umbilicus_rows(tmp_path_factory, "--pitch-vox", 8)


@pytest.fixture(scope="module")
def umbilicus_default(tmp_path_factory):
    return umbilicus_rows(tmp_path_factory)


def near_break(sw):
    return [s for s in sw["switches"]
            if s["kind"] == "horizontal" and abs(s["col"] - BREAK_COL) <= BREAK_WINDOW and s["confidence"] >= CONF_MIN]


# ---- (1) both meshes load, with the recorded facts ---------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(MESH_FACTS))
def test_mesh_loads_with_recorded_facts(key):
    f = MESH_FACTS[key]
    rows, cols = f["shape"]
    for ax in "xyz":                                    # on disk (Task 1): float32, (rows, cols)
        a = tifffile.imread(f["path"] / f"{ax}.tif")
        assert a.dtype == np.float32 and a.shape == (rows, cols)
    m = load_mesh(f["path"])                            # ssc_io (Task 1): float64 (rows, cols)
    assert m.shape == (rows, cols)
    assert m.x.dtype == m.y.dtype == m.z.dtype == np.float64
    assert m.n_invalid == f["n_invalid"] == int((~m.valid).sum())
    for a in (m.x, m.y, m.z):
        assert np.isfinite(a[m.valid]).all() and np.isnan(a[~m.valid]).all()
    ext = np.array([[np.nanmin(m.x), np.nanmin(m.y), np.nanmin(m.z)], [np.nanmax(m.x), np.nanmax(m.y), np.nanmax(m.z)]])
    assert np.allclose(ext, f["bbox"], atol=0.01)       # XYZ order, equals meta.json
    meta = json.loads((f["path"] / "meta.json").read_text())
    assert np.allclose(meta["bbox"], f["bbox"], atol=1e-9)


def test_uf_io_loads_the_slices():
    """uf_io has no mesh loader (F2 note); 'loads with uf_io' means its volume loader on the slice PNGs."""
    sys.path.insert(0, str(TOOLS / "umbilicus_finder"))
    try:
        import uf_io
        vol = uf_io.PngVolume(SLICES, scale_xy=1.0)
        assert vol.shape == (3,) + VOLUME_SHAPE_YX
        sl = vol.read_slice(1)
        assert sl.dtype == np.uint8 and sl.shape == VOLUME_SHAPE_YX
    finally:
        sys.path.remove(str(TOOLS / "umbilicus_finder"))


@pytest.mark.xfail(strict=True, reason="F2: PngVolume uses the file-list index as z and ignores the z in the file name "
                                       "(slices 02073/02600/03128 come out as z 0/1/2)")
def test_png_slice_heights_come_from_file_names(tmp_path):
    out = tmp_path / "uf"
    run_tool("umbilicus_finder", "umbilicus_finder.py", SLICES, "--pixel-um", VOX_UM, "--voxel-um", VOX_UM,
             "--z-start", HEIGHTS[0], "--z-stop", HEIGHTS[-1] + 1, "--z-step", 527, "--pitch-vox", 8,
             "--out-dir", out, "--export-all")
    zs = [float(r["z"]) for r in csv.DictReader(open(out / "umbilicus.csv"))]
    assert zs == [float(h) for h in HEIGHTS]


# ---- (2) umbilicus_finder ----------------------------------------------------------------------------------------
def test_umbilicus_centres_and_confidence_class_as_recorded(umbilicus):
    assert len(umbilicus) == 3
    for r, (x, y) in zip(umbilicus, UMB_CENTRES):
        assert float(r["x"]) == pytest.approx(x, abs=UMB_TOL_PX)
        assert float(r["y"]) == pytest.approx(y, abs=UMB_TOL_PX)
        assert r["flag"] == "LOW" and r["reason"] == "high_residual"        # recorded class: all three LOW
        assert float(r["confidence"]) < 0.05


def test_umbilicus_default_reports_no_pitch_as_recorded(umbilicus_default):
    """Without --pitch-vox every slice is LOW with reason no_pitch (R14-2); the centres are unchanged."""
    assert [r["flag"] for r in umbilicus_default] == ["LOW"] * 3
    assert [r["reason"] for r in umbilicus_default] == ["no_pitch"] * 3
    for r, (x, y) in zip(umbilicus_default, UMB_CENTRES):
        assert float(r["x"]) == pytest.approx(x, abs=UMB_TOL_PX) and float(r["y"]) == pytest.approx(y, abs=UMB_TOL_PX)


@pytest.mark.xfail(strict=True, reason="R14-2 / P4: default pitch search finds no pitch and no slice reaches OK")
def test_umbilicus_default_finds_a_pitch_and_an_ok_slice(umbilicus_default):
    assert any(r["flag"] == "OK" for r in umbilicus_default)
    assert all(r["reason"] != "no_pitch" for r in umbilicus_default)


@pytest.mark.xfail(strict=True, reason="R14-2 / P4: z=2600 centre is about 55 px (2.5 mm) from the whorl centre read by eye")
def test_umbilicus_centre_matches_by_eye_at_2600(umbilicus):
    assert float(umbilicus[1]["x"]) == pytest.approx(UMB_BY_EYE_X_2600, abs=UMB_BY_EYE_TOL_PX)


# ---- (3) sheet_spacing_check -------------------------------------------------------------------------------------
@pytest.mark.parametrize("i,z", list(enumerate(HEIGHTS)))
def test_spacing_fractions_and_ct_pitch_as_recorded(spacing, i, z):
    h, rec = spacing[i], SPACING[z]
    assert h["z"] == z
    assert h["clean_fraction"] == pytest.approx(rec["clean"], abs=FRAC_TOL)
    assert h["shared_fraction"] == pytest.approx(rec["shared"], abs=FRAC_TOL)
    assert h["skipped_fraction"] == pytest.approx(rec["skipped"], abs=FRAC_TOL)
    assert h["ct_pitch_vox"] == pytest.approx(rec["ct_pitch"], rel=PITCH_REL_TOL)
    assert h["pitch_mismatch_flag"] is True          # recorded: PITCH-MISMATCH at every height


@pytest.mark.xfail(strict=True, reason="R14-3 / P3: tool CT pitch is 14-17 voxels, independently measured pitch is 9.5 (+-2)")
@pytest.mark.parametrize("i", range(3))
def test_spacing_ct_pitch_matches_independent_measurement(spacing, i):
    assert spacing[i]["ct_pitch_vox"] == pytest.approx(MEASURED_PITCH_VOX, rel=PITCH_REL_TOL)


@pytest.mark.xfail(strict=True, reason="F1 / P1: adjacent real meshes have different grid shapes and the tool refuses them")
def test_spacing_accepts_the_real_pair_as_it_is(tmp_path):
    run_tool("sheet_spacing_check", "sheet_spacing_check.py", A_DIR, B_DIR, *PNG_ARGS, "--global-pitch",
             "--out-json", tmp_path / "x.json", ok_codes=(0,))
    assert (tmp_path / "x.json").exists()


# ---- (4) sheet_switch_finder -------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(MESH_FACTS))
def test_switch_finder_reports_recorded_switches(switches, key):
    sw = switches[key]["switches"]
    got = {(s["kind"], int(s["height"]), int(s["col"])) for s in sw if s["confidence"] >= CONF_MIN}
    assert got == SWITCHES_CONF[key]
    assert abs(len(sw) - SWITCH_TOTALS[key]) <= SWITCH_TOTAL_TOL


# ---- (5) deliberately broken copy: must be flagged by the switch finder AND the auditor --------------------------
def test_broken_copy_is_built_as_intended(broken_mesh):
    a, b = load_mesh(A_DIR), load_mesh(broken_mesh)
    assert a.shape == b.shape and (a.valid == b.valid).all()
    d = np.hypot(b.x - a.x, b.y - a.y)
    v = a.valid
    cols = np.broadcast_to(np.arange(a.shape[1]), a.shape)
    assert np.allclose(d[v & (cols <= BREAK_COL)], 0, atol=1e-3)
    assert np.allclose(d[v & (cols > BREAK_COL)], BREAK_SHIFT_VOX, atol=1e-2)     # exactly one pitch outward
    assert np.allclose(b.z[v], a.z[v], atol=1e-3)


@pytest.mark.xfail(strict=True, reason="R14-5: the switch finder does not flag the break (no confidence >= 0.3 switch at cols 112-128)")
def test_switch_finder_flags_the_broken_copy(switches_broken):
    assert near_break(switches_broken)


@pytest.mark.xfail(strict=True, reason="R14-6 / P5: auditor FAILs the unbroken original too, so its verdict does not flag the break")
def test_auditor_verdict_separates_broken_from_original(audits, audit_broken):
    assert audit_broken["verdict"] == "FAIL"
    assert audits["w116-117"]["verdict"] == "PASS"


# ---- (6) trace_auditor verdicts on the real meshes ---------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(MESH_FACTS))
def test_auditor_verdicts_as_recorded(audits, key):
    t = audits[key]
    assert t["verdict"] == "FAIL"
    status = {c["check"]: c["status"] for c in t["checks"]}
    for check, want in AUDIT_CHECKS_A.items():
        assert status[check] == want
    n_jumps = sum(1 for z in [r for r in t["reasons"] if r.startswith("winding_jumps")]
                  for _ in z.split("radius jumps")[1:])
    assert n_jumps == pytest.approx(AUDIT_JUMPS[key], abs=AUDIT_JUMP_TOL)


@pytest.mark.xfail(strict=True, reason="R14-6 / P5: winding_jumps FAILs the unbroken originals with over 100 jumps each "
                                       "(centre is LOW, scroll is not concentric; 112-115 before round 2, 129-136 after); a FAIL carries no information")
@pytest.mark.parametrize("key", sorted(MESH_FACTS))
def test_auditor_does_not_fail_on_untouched_traces_for_unreliable_centre(audits, key):
    status = {c["check"]: c["status"] for c in audits[key]["checks"]}
    assert status["winding_jumps"] != "FAIL"
