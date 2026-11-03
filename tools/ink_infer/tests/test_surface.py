"""surface.py geometry tests -- NO torch needed (these run wherever numpy/scipy/tifffile exist).

Synthetic data only: a planar tifxyz mesh and a CT with one painted spot.
"""
import os

import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("tifffile")

import surface as sf                                  # noqa: E402
from helpers import make_ct, write_plane_mesh         # noqa: E402

Z0, Y0, X0 = 20, 10, 10


def surf_for(mesh, step=1.0, **kw):
    return sf.resample_mesh(sf.load_mesh(mesh), step, **kw)


def spot_rc(vol, surf, offs=None, size=64):
    """(layer, row, col) of the brightest sample in the extracted patch."""
    offs = sf.layer_offsets(15, 1.0) if offs is None else offs
    patch, valid = sf.extract_patch(vol, surf, 0, 0, size, offs)
    return tuple(int(i) for i in np.unravel_index(np.argmax(patch), patch.shape)), valid


def test_spot_lands_at_right_grid_position(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 30, X0 + 45), half=0)
    (d, r, c), valid = spot_rc(sf.CTVolume(ct), surf_for(mesh))
    assert (r, c) == (30, 45) and d == 7 and valid.all()


def test_not_transposed_on_non_square_mesh(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 48, 80, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 12, X0 + 70), half=0)
    surf = surf_for(mesh)
    assert surf.shape == (48, 80)
    patch, _ = sf.extract_patch(sf.CTVolume(ct), surf, 0, 48, 32, sf.layer_offsets(15, 1.0))
    _, r, c = np.unravel_index(np.argmax(patch), patch.shape)
    assert (r, c + 48) == (12, 70)


def test_layers_follow_normal_and_flip_reverses(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), spot=(Z0 + 3, Y0 + 30, X0 + 45), half=0)
    vol, offs = sf.CTVolume(ct), sf.layer_offsets(15, 1.0)
    np.testing.assert_allclose(offs, np.arange(-7, 8))
    for flip, layer in ((False, 4), (True, 10)):
        surf = surf_for(mesh, flip_normal=flip)
        assert np.allclose(surf.N[10, 10], [0, 0, 1 if flip else -1])
        patch, _ = sf.extract_patch(vol, surf, 16, 32, 32, offs)
        d, r, c = np.unravel_index(np.argmax(patch), patch.shape)
        assert (d, r + 16, c + 32) == (layer, 30, 45)


def test_anisotropic_mesh_scale_output_pixels_are_step_voxels(tmp_path):
    # scale=(sx, sy): mesh cells are 1/sx vox in x and 1/sy vox in y, but the OUTPUT grid is
    # step voxels per pixel in both directions (x -> columns, y -> rows).
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0, scale=(2.0, 0.5))
    ct = make_ct((40, 140, 96), spot=(Z0, Y0 + 20, X0 + 10), half=0)
    surf = surf_for(mesh, 1.0)
    assert np.allclose(surf.P[20, 10], [X0 + 10, Y0 + 20, Z0])
    (d, r, c), _ = spot_rc(sf.CTVolume(ct), surf, size=32)
    assert (r, c) == (20, 10)


def test_coarser_output_step(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 129, 129, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 150, 150), spot=(Z0, Y0 + 42, X0 + 66), half=0)
    surf = surf_for(mesh, 2.0)                       # 2 voxels per output pixel
    assert surf.shape == (65, 65)
    (d, r, c), _ = spot_rc(sf.CTVolume(ct), surf, offs=sf.layer_offsets(15, 2.0))
    assert (r, c) == (21, 33)


def test_holes_invalid_and_do_not_shift_neighbours(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0, holes=[(40, 50, 5, 15)])
    surf = surf_for(mesh)
    assert not surf.valid[40:50, 5:15].any() and surf.valid[10, 10]
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 30, X0 + 45), half=0)
    (d, r, c), _ = spot_rc(sf.CTVolume(ct), surf)
    assert (r, c) == (30, 45)


def test_sampling_outside_volume_is_zero_not_error():
    vol = sf.CTVolume(np.full((10, 10, 10), 255, np.uint8))
    pts = np.array([[-50.0, 5, 5], [5, 5, 500], [np.nan, 5, 5], [5, 5, 5]])
    out = vol.sample(pts)
    assert out[0] == 0 and out[1] == 0 and out[2] == 0 and out[3] == pytest.approx(1.0)


def test_normalisation_follows_dtype():
    one = np.array([[1.0, 1, 1]])
    assert sf.CTVolume(np.full((4, 4, 4), 255, np.uint8)).sample(one)[0] == pytest.approx(1.0)
    assert sf.CTVolume(np.full((4, 4, 4), 65535, np.uint16)).sample(one)[0] == pytest.approx(1.0)


def test_mesh_errors_are_input_errors(tmp_path):
    with pytest.raises(sf.InputError):
        sf.load_mesh(tmp_path / "nope")
    m = write_plane_mesh(tmp_path / "noscale", 8, 8, z0=0)
    os.remove(m + "/meta.json")
    with pytest.raises(sf.InputError, match="scale"):
        sf.resample_mesh(sf.load_mesh(m), 1.0)
    with pytest.raises(sf.InputError):
        sf.CTVolume(np.zeros((4, 4)))


def test_small_segment_is_padded_with_invalid_pixels(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 12, 12, z0=Z0, x0=X0, y0=Y0)
    s = sf.pad_surface(surf_for(mesh), 32)
    assert s.shape == (32, 32) and s.valid[:12, :12].all() and not s.valid[12:].any()
