"""Regression tests for the PR #1 review: off-centre scroll, z-varying CT, scale handling,
run splitting, ratio edges, and the area / input-handling fixes. Synthetic data only."""
import numpy as np
import pytest

import sheet_spacing_check as ssc
from ssc_io import ArrayVolume, build_mesh

PITCH = 12.0
CX, CY = 200.0, 330.0                       # deliberately off-centre and x != y
NZ, NY, NX = 100, 640, 512
R0 = 100.0


def sheets_img(r, shift=0.0):
    img = np.full(r.shape, 20.0)
    for rc in np.arange(16.0, 400.0, PITCH):
        img = np.maximum(img, 20 + 180 * np.exp(-((r - rc - shift) ** 2) / (2 * 1.5 ** 2)))
    return img.astype(np.float32)


@pytest.fixture(scope="module")
def ct():
    yy, xx = np.mgrid[0:NY, 0:NX]
    img = sheets_img(np.hypot(xx - CX, yy - CY))   # sheets at 16 + 12 k  (100 = 16 + 7*12)
    return np.broadcast_to(img, (NZ, NY, NX)).copy()


def cyl(radius, n_cols=720, swap_xy=False, cx=CX, cy=CY):
    th = np.linspace(0, 2 * np.pi, n_cols, endpoint=False)
    x = np.tile(cx + radius * np.cos(th), (NZ, 1))
    y = np.tile(cy + radius * np.sin(th), (NZ, 1))
    z = np.tile(np.arange(NZ, dtype=float)[:, None], (1, n_cols))
    if swap_xy:
        x, y = y, x
    return build_mesh("m", x, y, z, {"scale": [0.5, 0.5], "voxelsize": 10.0})


def run(a, b, vol, heights=(30.0, 50.0, 70.0), **kw):
    if len(heights) < 2:
        kw.setdefault("band_height_vox", 10.0)
    return ssc.run_check(a, b, vol, list(heights), ssc.Params(**kw), voxel_um=10.0)


def test_off_centre_scroll_clean_and_swapped_xy_is_not(ct):
    vol = ArrayVolume(ct)
    good = run(cyl(R0), cyl(R0 + PITCH), vol)
    bad = run(cyl(R0, swap_xy=True), cyl(R0 + PITCH, swap_xy=True), vol)
    for g, b in zip(good["heights"], bad["heights"]):
        assert g["clean_fraction"] > 0.98
        assert b["clean_fraction"] < 0.5          # swapped mesh x/y vs the CT: must fail


def test_half_resolution_volume_agrees_with_full(ct):
    half = ct.reshape(NZ // 2, 2, NY // 2, 2, NX // 2, 2).mean(axis=(1, 3, 5)).astype(np.float32)
    full = run(cyl(R0), cyl(R0 + PITCH), ArrayVolume(ct))
    low = run(cyl(R0), cyl(R0 + PITCH), ArrayVolume(half, ct_scale=2))
    for f, h in zip(full["heights"], low["heights"]):
        assert h["clean_fraction"] > 0.95
        assert h["ct_pitch_vox"] == pytest.approx(f["ct_pitch_vox"], rel=0.1)
        assert h["median_ratio"] == pytest.approx(f["median_ratio"], abs=0.1)


def test_slice_index_floors_not_rounds():
    v = ArrayVolume(np.zeros((10, 4, 4)), ct_scale=2)
    assert [v.slice_index(z) for z in (0, 1, 2, 3, 5, 7)] == [0, 0, 1, 1, 2, 3]


# ---- cone whose sheets move with z: z axis, slice index, area tilt factor -----------------
S = 1.0                                          # cone slope: radius grows by S per z


class ConeVolume(ArrayVolume):
    """Sheets at radius 100 + S*z + 12 k in slice z, generated lazily (no big array)."""

    def __init__(self):
        self.ct_scale, self.shape_yx, self.data = 1.0, (640, 640), np.zeros((NZ, 1, 1))

    def tile(self, z, x0, y0, x1, y1):
        zi = self.slice_index(z)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        return sheets_img(np.hypot(xx - 300.0, yy - 300.0), shift=S * zi)   # sheets: 16 + 12 j + S z (100 = 16 + 7*12)


def cone(r_at_0, n_cols=720):
    th = np.linspace(0, 2 * np.pi, n_cols, endpoint=False)
    zz = np.arange(NZ, dtype=float)[:, None]
    rad = r_at_0 + S * zz
    return build_mesh("cone", 300 + rad * np.cos(th), 300 + rad * np.sin(th),
                      np.tile(zz, (1, n_cols)), {"voxelsize": 10.0})


def test_cone_over_z_varying_ct_is_clean_with_correct_tilted_area():
    heights = [20.0, 40.0, 60.0]
    res = run(cone(100.0), cone(100.0 + PITCH), ConeVolume(), heights)
    for h in res["heights"]:
        assert h["clean_fraction"] > 0.98
        assert h["ct_pitch_vox"] == pytest.approx(PITCH, rel=0.05)
    expected = sum(2 * np.pi * (100 + S * z) * 20.0 * np.sqrt(1 + S ** 2) for z in heights) * 1e-6
    assert res["area"]["clean_area_cm2"] == pytest.approx(expected, rel=0.03)


def test_wrong_slice_would_fail_on_cone():
    class Shifted(ConeVolume):
        def tile(self, z, *a):
            return super().tile(z + 4, *a)       # CT slice off by 4: sheets 4 px away
    res = run(cone(100.0), cone(100.0 + PITCH), Shifted(), [20.0, 40.0, 60.0])
    assert all(h["clean_fraction"] < 0.5 for h in res["heights"])


# ---- B1: tilt factor kept when only A has cut points ----------------------------------------
def test_area_keeps_tilt_when_b_is_uncovered():
    b = cone(100.0 + PITCH)
    b.z[:] += 1000                                # B out of range at the chosen height
    res = run(cone(100.0), b, ConeVolume(), [50.0], band_height_vox=10.0)
    expected = 2 * np.pi * (100 + S * 50) * 10.0 * np.sqrt(1 + S ** 2) * 1e-6
    assert res["heights"][0]["uncovered_b"]
    assert res["area"]["sampled_area_cm2"] == pytest.approx(expected, rel=0.01)


# ---- run splitting: median must not cross runs ----------------------------------------------
def test_isolated_one_point_run_keeps_its_own_flag(ct):
    a, b = cyl(R0), cyl(R0 + PITCH)
    for g in (a.x, a.y, a.z):
        g[:, [131, 133]] = np.nan                 # column 132 becomes a run of one point
    a.valid[:, [131, 133]] = False
    th = np.linspace(0, 2 * np.pi, 720, endpoint=False)[132]
    a.x[:, 132], a.y[:, 132] = CX + (R0 + PITCH) * np.cos(th), CY + (R0 + PITCH) * np.sin(th)  # on B
    res = run(a, b, ArrayVolume(ct), [50.0])["heights"][0]
    assert res["n_points_a"] == 718
    assert res["clean_fraction"] == pytest.approx(717 / 718)      # only the pinned point fails
    assert res["shared_fraction"] == pytest.approx(1 / 718)


# ---- ratio edges --------------------------------------------------------------------------
@pytest.mark.parametrize("off,shared,skipped", [(5.4, 1, 0), (6.6, 0, 0), (17.4, 0, 0), (18.6, 0, 1)])
def test_ratio_edges(ct, off, shared, skipped):
    h = run(cyl(R0), cyl(R0 + off), ArrayVolume(ct), [50.0])["heights"][0]
    assert h["median_ratio"] == pytest.approx(off / PITCH, abs=0.02)
    assert h["shared_fraction"] == pytest.approx(shared, abs=0.01)
    assert h["skipped_fraction"] == pytest.approx(skipped, abs=0.01)


# ---- R3: missing B trace is not 'skipped' -----------------------------------------------------
def test_hole_in_b_is_reported_as_missing_not_skipped(ct):
    b = cyl(R0 + PITCH)
    b.valid[:, 300:421] = False
    for g in (b.x, b.y, b.z):
        g[:, 300:421] = np.nan
    h = run(cyl(R0), b, ArrayVolume(ct), [50.0])["heights"][0]
    # only A points farther than 1.5 pitches from any B point count as missing: the deep part
    # of the 121-column hole, not its edges (those are still measured against the edge of B)
    assert 0.11 < h["b_missing_fraction"] < 0.14
    assert h["skipped_fraction"] == 0.0
    assert h["clean_fraction"] > 0.8


# ---- R1 / R2 / R4 / N2 -------------------------------------------------------------------
def test_transpose_swaps_meta_scale():
    g = np.arange(24, dtype=float).reshape(4, 6)
    m = build_mesh("t", g, g, g, {"scale": [0.1, 0.5]}, transpose=True)
    assert m.shape == (6, 4) and m.scale == (0.5, 0.1)


def test_partial_sentinel_marks_cell_invalid_and_input_not_mutated():
    x = np.arange(12, dtype=float).reshape(3, 4) + 5
    z = x.copy()
    z[1, 2] = -1                                  # only z carries the sentinel
    z0 = z.copy()
    m = build_mesh("p", x, x.copy(), z)
    assert not m.valid[1, 2] and m.n_invalid == 1
    assert np.array_equal(z, z0)                  # caller's array untouched


def test_nan_normals_next_to_a_hole_take_nearest_finite_value():
    m = cone(100.0)
    m.valid[51, 100] = False
    for g in (m.x, m.y, m.z):
        g[51, 100] = np.nan
    line = ssc.cut_line(m, 52.5, ssc.Params())   # rows 52-53: row 52's gradient touches the hole
    i = int(np.flatnonzero(line.col == 100)[0])
    assert np.isfinite(line.nz2).all()
    assert line.nz2[i] == pytest.approx(S ** 2 / (1 + S ** 2), abs=0.01)


def test_invalid_cells_warning_in_report(ct):
    a = cyl(R0)
    a = build_mesh("a", np.where(np.arange(NZ)[:, None] == 5, -1.0, a.x), a.y, a.z)
    assert a.n_invalid == 720
    r = run(a, cyl(R0 + PITCH), ArrayVolume(ct), [50.0])
    assert any("no-data" in w for w in r["warnings"])


def test_pixel_centre_convention():
    from ssc_io import to_px
    # level-1 pixel i covers voxels 2i and 2i+1, centre at voxel 2i + 0.5
    assert to_px([[0.5, 2.5]], 2.0)[0].tolist() == [0.0, 1.0]
    assert to_px([[7.0, 3.0]], 1.0)[0].tolist() == [7.0, 3.0]
    assert to_px([[1.5, 1.5]], 4.0)[0].tolist() == [0.0, 0.0]
