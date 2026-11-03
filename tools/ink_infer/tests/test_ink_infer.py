"""ink_infer tests -- synthetic data only (no scan data, no labels, no real checkpoints).

Covers: geometry (a painted spot must land at the right grid position, under unit / anisotropic
mesh scale, a coarser output step, OME level 1, and normal flipping), mesh holes, stitching,
the intensity rule, a tiny random-weight checkpoint through the CLI, and resume.
"""
import json
import os

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("zarr")
pytest.importorskip("tifffile")

import ink_infer as ii                       # noqa: E402
import surface as sf                         # noqa: E402
from helpers import (make_ct, tiny_checkpoint, write_plane_mesh, write_zarr)  # noqa: E402

Z0, Y0, X0 = 20, 10, 10          # plane height and origin of the synthetic mesh (level-0 voxels)


class StubModel:
    """Purely local 'model': logit = 20*max_over_depth(x) - 10. Lets tests locate a painted spot
    exactly, independent of any learned weights."""
    def ink_logits_2d(self, x):
        return x.amax(dim=2) * 20.0 - 10.0


def surface_for(mesh_dir, step):
    return sf.resample_mesh(sf.load_mesh(mesh_dir), step)


def infer(vol, surf, model=None, *, depth=15, patch=32, stride=16, step=1.0, **kw):
    kw.setdefault("batch_size", 2)
    kw.setdefault("log", lambda *_: None)
    return ii.run_inference(model or StubModel(), vol, surf, depth=depth, patch=patch, stride=stride,
                            layer_step_vox=step, **kw)


def peak(prob):
    return tuple(int(i) for i in np.unravel_index(np.argmax(prob), prob.shape))


# =================================================================== geometry
def test_spot_lands_at_right_grid_position(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 30, X0 + 45), half=0)
    prob, _, _ = infer(sf.CTVolume(ct), surface_for(mesh, 1.0))
    assert prob.shape == (64, 64)
    assert peak(prob) == (30, 45)                      # row = y - Y0, col = x - X0
    assert (prob > 0.5).sum() == 1                     # one pixel, not a smear


def test_spot_position_not_transposed_on_non_square_mesh(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 40, 70, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 7, X0 + 60), half=0)
    prob, surf, _ = infer(sf.CTVolume(ct), surface_for(mesh, 1.0))
    assert surf.shape == (40, 70) and prob.shape == (40, 70)
    assert peak(prob) == (7, 60)


def test_anisotropic_mesh_scale_maps_x_to_columns_y_to_rows(tmp_path):
    # scale = [sx, sy]: grid cells are 1/sx voxels in x and 1/sy voxels in y (here 2 vox and 0.5 vox).
    mesh = write_plane_mesh(tmp_path / "m", 129, 33, z0=Z0, scale=(0.5, 2.0), x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 12, X0 + 50), half=0)
    surf = surface_for(mesh, 1.0)
    assert surf.shape == (65, 65)                      # 64 voxels span in both directions, 1 vox/px
    assert np.allclose(surf.P[0, 0], [X0, Y0, Z0]) and np.allclose(surf.P[12, 50], [X0 + 50, Y0 + 12, Z0])
    prob, _, _ = infer(sf.CTVolume(ct), surf)
    assert peak(prob) == (12, 50)


def test_coarser_output_step(tmp_path):
    # scan 1.62 um/vox, output pitch 3.24 um -> 2 voxels per output pixel (and per layer).
    mesh = write_plane_mesh(tmp_path / "m", 129, 129, z0=Z0, x0=X0, y0=Y0, voxel_um=1.62)
    step = 3.24 / 1.62
    ct = make_ct((40, 150, 150), spot=(Z0, Y0 + 2 * 21, X0 + 2 * 33), half=0)
    surf = surface_for(mesh, step)
    assert surf.shape == (65, 65)
    prob, _, _ = infer(sf.CTVolume(ct), surf, step=step)
    assert peak(prob) == (21, 33)


def test_ome_level1_pixel_centre_convention(tmp_path):
    # level-1 pixel i covers level-0 voxels 2i and 2i+1, so its centre is level-0 coordinate 2i+0.5.
    l0 = np.zeros((16, 16, 16), np.uint8)
    l0[6:8, 8:10, 10:12] = 200                          # exactly level-1 pixel (z=3, y=4, x=5)
    l1 = l0.reshape(8, 2, 8, 2, 8, 2).mean(axis=(1, 3, 5)).astype(np.uint8)
    vol = sf.CTVolume(l1, level=1)
    c = lambda x, y, z: np.array([[x, y, z]], float)    # noqa: E731
    assert vol.sample(c(11.0 - 0.5, 9.0 - 0.5, 7.0 - 0.5))[0] == pytest.approx(200 / 255, abs=1e-6)
    assert vol.sample(c(10.5 + 2, 8.5, 6.5))[0] == pytest.approx(0.0, abs=1e-6)       # next pixel over
    assert vol.sample(c(10.5 + 1, 8.5, 6.5))[0] == pytest.approx(100 / 255, abs=1e-6)  # halfway
    # level 0: identity
    assert sf.CTVolume(l0).sample(c(10, 8, 6))[0] == pytest.approx(200 / 255, abs=1e-6)


def test_spot_lands_at_right_position_from_zarr_level1(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    l0 = make_ct((40, 96, 96), spot=(Z0, Y0 + 30, X0 + 45), half=1)
    l0[Z0 - 1:Z0 + 2, Y0 + 29:Y0 + 32, X0 + 44:X0 + 47] = 255
    l1 = l0.reshape(20, 2, 48, 2, 48, 2).mean(axis=(1, 3, 5)).astype(np.uint8)
    z = write_zarr(tmp_path / "ct.zarr", [l0, l1])
    prob, _, _ = infer(sf.CTVolume.open_zarr(z, level=1), surface_for(mesh, 1.0))
    r, c = peak(prob)
    assert abs(r - 30) <= 1 and abs(c - 45) <= 1       # blurred by the 2x downsample: +-1 px


def test_layers_run_along_the_normal_and_flip_reverses(tmp_path):
    # Documented convention: normal = cross(d/drow, d/dcol). For this planar mesh (x<->col, y<->row)
    # that is -z, so layer d samples z = Z0 - offset[d].
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), spot=(Z0 + 3, Y0 + 30, X0 + 45), half=0)
    vol, offs = sf.CTVolume(ct), sf.layer_offsets(15, 1.0)
    np.testing.assert_allclose(offs, np.arange(-7, 8))
    for flip, layer in ((False, 7 - 3), (True, 7 + 3)):
        surf = sf.resample_mesh(sf.load_mesh(mesh), 1.0, flip_normal=flip)
        assert np.allclose(surf.N[10, 10], [0, 0, 1 if flip else -1])
        patch, valid = sf.extract_patch(vol, surf, 16, 32, 32, offs)
        d, r, c = np.unravel_index(np.argmax(patch), patch.shape)
        assert (d, r + 16, c + 32) == (layer, 30, 45) and valid.all()


def test_curved_mesh_normals_and_sampling(tmp_path):
    # Cylinder-ish sheet: z = Z0 + 0.1*(col)^... -> check unit normals and that the spot is found
    # on the tilted surface, 2 voxels along its normal.
    import tifffile
    rows = cols = 64
    r, c = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    x, y = (X0 + c).astype(np.float32), (Y0 + r).astype(np.float32)
    z = (Z0 + 0.5 * c).astype(np.float32)              # 26.6 degree tilt about the y axis
    d = tmp_path / "tilt"
    d.mkdir()
    for n, a in (("x", x), ("y", y), ("z", z)):
        tifffile.imwrite(d / f"{n}.tif", a)
    (d / "meta.json").write_text(json.dumps({"scale": [1, 1], "voxelsize": 3.24}))
    surf = surface_for(d, 1.0)
    assert np.allclose(np.linalg.norm(surf.N[5:-5, 5:-5], axis=-1), 1.0)
    nrm = surf.N[30, 30]
    assert np.allclose(nrm, np.array([0.5, 0, -1]) / np.hypot(0.5, 1), atol=1e-6)
    ct = np.zeros((70, 96, 96), np.uint8)
    p = np.array([X0 + 40, Y0 + 20, Z0 + 20.0])         # surface point at (row 20, col 40)
    q = p + 2 * surf.N[20, 40]                           # +2 voxels along the normal
    qi = np.rint(q[::-1]).astype(int)
    ct[tuple(qi)] = 255
    vol = sf.CTVolume(ct)
    patch, _ = sf.extract_patch(vol, surf, 8, 24, 32, sf.layer_offsets(15, 1.0))
    d_, r_, c_ = np.unravel_index(np.argmax(patch), patch.shape)
    assert abs((r_ + 8) - 20) <= 1 and abs((c_ + 24) - 40) <= 1 and abs(d_ - (7 + 2)) <= 1


def test_sampling_outside_volume_is_zero_not_error():
    vol = sf.CTVolume(np.full((10, 10, 10), 255, np.uint8))
    pts = np.array([[-50.0, 5, 5], [5, 5, 500], [np.nan, 5, 5], [5, 5, 5]])
    out = vol.sample(pts)
    assert out[0] == 0 and out[1] == 0 and out[2] == 0 and out[3] == pytest.approx(1.0)
    assert vol.sample(np.full((2, 2, 3), 1e6)).max() == 0


def test_normalisation_follows_dtype():
    assert sf.CTVolume(np.full((4, 4, 4), 255, np.uint8)).sample(np.array([[1.0, 1, 1]]))[0] == pytest.approx(1.0)
    assert sf.CTVolume(np.full((4, 4, 4), 65535, np.uint16)).sample(np.array([[1.0, 1, 1]]))[0] == pytest.approx(1.0)
    assert sf.CTVolume(np.full((4, 4, 4), 128, np.uint8), norm_max=256).sample(np.array([[1.0, 1, 1]]))[0] == pytest.approx(0.5)


# ===================================================================== mesh
def test_holes_are_invalid_and_stay_zero(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0, holes=[(20, 30, 20, 30)])
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 25, X0 + 25), half=1)    # spot sits inside the hole
    surf = surface_for(mesh, 1.0)
    assert not surf.valid[20:30, 20:30].any() and surf.valid[0, 0]
    assert surf.valid[10, 10]
    prob, _, _ = infer(sf.CTVolume(ct), surf)
    assert prob[~surf.valid].max() == 0.0
    assert not np.isnan(prob).any()


def test_hole_does_not_shift_neighbouring_pixels(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0, holes=[(40, 50, 5, 15)])
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 30, X0 + 45), half=0)
    prob, _, _ = infer(sf.CTVolume(ct), surface_for(mesh, 1.0))
    assert peak(prob) == (30, 45)


def test_mesh_errors_are_input_errors(tmp_path):
    with pytest.raises(sf.InputError):
        sf.load_mesh(tmp_path / "nope")
    (tmp_path / "e").mkdir()
    with pytest.raises(sf.InputError, match="missing x.tif"):
        sf.load_mesh(tmp_path / "e")
    m = write_plane_mesh(tmp_path / "noscale", 8, 8, z0=0)
    os.remove(m + "/meta.json")
    with pytest.raises(sf.InputError, match="scale"):
        sf.resample_mesh(sf.load_mesh(m), 1.0)
    tiny = write_plane_mesh(tmp_path / "tiny", 1, 1, z0=0)
    with pytest.raises(sf.InputError, match="too small"):
        sf.resample_mesh(sf.load_mesh(tiny), 1.0)
    with pytest.raises(sf.InputError):
        sf.CTVolume(np.zeros((4, 4)))
    with pytest.raises(sf.InputError):
        sf.CTVolume.open_zarr(tmp_path / "missing.zarr")


def test_small_segment_is_padded_with_invalid_pixels(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 12, 12, z0=Z0, x0=X0, y0=Y0)
    s = sf.pad_surface(surface_for(mesh, 1.0), 32)
    assert s.shape == (32, 32) and s.valid[:12, :12].all() and not s.valid[12:].any()
    ct = make_ct((40, 96, 96), spot=(Z0, Y0 + 3, X0 + 4), half=0)
    prob, surf, _ = infer(sf.CTVolume(ct), surface_for(mesh, 1.0))
    assert prob.shape == (32, 32) and peak(prob) == (3, 4) and surf.shape == (32, 32)


# ================================================================= stitching
def test_patch_grid_covers_everything():
    for n in (1, 31, 32, 33, 47, 48, 100, 129):
        g = ii.patch_grid(n, 32, 16)
        cover = np.zeros(n, bool)
        for s in g:
            cover[s:s + 32] = True
        assert cover.all() and g[-1] + 32 >= n and g == sorted(set(g))


@pytest.mark.parametrize("blend", ["hann", "mean"])
def test_tiling_is_seamless(tmp_path, blend):
    # The stub is per-pixel, so any tiling/blend must give the same answer as one big patch.
    mesh = write_plane_mesh(tmp_path / "m", 70, 83, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 112), half=0)
    rng = np.random.default_rng(1)
    ct[Z0 - 6:Z0 + 7, Y0:Y0 + 70, X0:X0 + 83] = rng.integers(0, 255, (13, 70, 83), dtype=np.uint8)
    vol, surf = sf.CTVolume(ct), surface_for(mesh, 1.0)
    a, _, _ = infer(vol, surf, patch=32, stride=16, blend=blend)
    b, _, _ = infer(vol, surf, patch=96, stride=96, blend=blend)
    c, _, _ = infer(vol, surf, patch=40, stride=24, blend=blend, batch_size=3, workers=1)
    assert a.shape == c.shape == (70, 83) and b.shape == (96, 96)      # b: padded to one 96 patch
    np.testing.assert_allclose(a, b[:70, :83], atol=1e-5)
    np.testing.assert_allclose(c, b[:70, :83], atol=1e-5)
    assert (a > 0).all()                       # border pixels are not left untiled


def test_blend_windows():
    assert ii.blend_window(32, "mean").min() == 1.0
    h = ii.blend_window(32, "hann")
    assert h.shape == (32, 32) and h.min() > 0 and h.max() == 1.0 and h[16, 16] > h[0, 0]


def test_tta_runs_and_matches_for_symmetric_model(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 40, 40, z0=Z0, x0=X0, y0=Y0)
    vol, surf = sf.CTVolume(make_ct((40, 64, 64), spot=(Z0, Y0 + 10, X0 + 10), half=0)), surface_for(mesh, 1.0)
    a, _, _ = infer(vol, surf)
    b, _, _ = infer(vol, surf, tta=True)
    np.testing.assert_allclose(a, b, atol=1e-5)          # a per-pixel model is flip-equivariant


# =========================================================== intensity rule
def test_intensity_rule():
    s = np.linspace(0.1, 0.5, 1000)
    sc, off, note = ii.intensity_rule(s, 0.1, 0.5)
    assert (sc, off) == (1.0, 0.0) and "unchanged" in note
    sc, off, note = ii.intensity_rule(s, 0.1, 0.5 * 2.5)    # ref p99 far above sample p99 -> rescale
    assert "rescaled" in note
    mapped = np.percentile(s, [1, 99]) * sc + off
    np.testing.assert_allclose(mapped, [0.1, 1.25], atol=1e-6)
    assert ii.intensity_rule(s, None, None)[2] == "no intensity rule"
    assert ii.intensity_rule(np.array([]), 0.1, 0.5)[2] == "no intensity rule"


# ======================================================= checkpoint + the CLI
@pytest.fixture()
def scene(tmp_path):
    mesh = write_plane_mesh(tmp_path / "mesh", 48, 48, z0=Z0, x0=X0, y0=Y0)
    rng = np.random.default_rng(0)
    ct = rng.integers(0, 120, (40, 80, 80), dtype=np.uint8)
    ct[Z0, Y0 + 20:Y0 + 24, X0 + 10:X0 + 40] = 255
    zarr_path = write_zarr(tmp_path / "ct.zarr", [ct])
    ckpt = tiny_checkpoint(str(tmp_path / "tiny.pt"))
    return dict(tmp=tmp_path, mesh=mesh, zarr=zarr_path, ckpt=ckpt)


def cli(scene, out, *extra, ckpt=None):
    return ii.main([scene["mesh"], "--zarr", scene["zarr"], "--checkpoint", ckpt or scene["ckpt"],
                    "--out-dir", str(scene["tmp"] / out), "--device", "cpu", "--batch-size", "2",
                    "--workers", "1", *extra])


def outputs(scene, out):
    d = scene["tmp"] / out
    return np.load(d / "ink_prob.npy"), json.load(open(d / "run.json"))


def test_tiny_random_checkpoint_end_to_end(scene):
    assert cli(scene, "o1", "--save-every", "1", "--threshold", "0.5") == 0
    prob, run = outputs(scene, "o1")
    d = scene["tmp"] / "o1"
    for f in ("ink_prob.npy", "ink_prob.png", "valid_mask.png", "ink_binary.png", "run.json", "work/state.npz"):
        assert (d / f).is_file(), f
    assert prob.dtype == np.float16 and prob.shape == (48, 48)       # patch 32 < 48: no padding
    assert np.isfinite(prob).all() and 0.0 <= prob.min() and prob.max() <= 1.0
    assert prob.std() > 0                                              # not a constant map
    assert run["config"]["depth"] == 16 and run["config"]["patch"] == 32 and run["config"]["step"] == 1.0
    assert run["config"]["ckpt"] == ii.sha256_file(scene["ckpt"])
    assert any("picture, not a score" in n for n in run["notes"])
    from PIL import Image
    assert Image.open(d / "ink_prob.png").size == (48, 48)


def test_inference_is_deterministic(scene):
    cli(scene, "a")
    cli(scene, "b", "--workers", "2", "--batch-size", "3")
    np.testing.assert_allclose(outputs(scene, "a")[0].astype(np.float32),
                               outputs(scene, "b")[0].astype(np.float32), atol=2e-3)   # fp16 + batch order


def test_dataparallel_prefix_and_topk_contract(scene):
    ck = tiny_checkpoint(str(scene["tmp"] / "k.pt"), aggregation="topk_mean", topk=4, wrap_module=True)
    model, _, con = ii.build_model(ii.load_checkpoint(ck))
    assert (model.aggregation, model.topk) == ("topk_mean", 4) and con["topk"] == 4
    assert cli(scene, "k", ckpt=ck) == 0
    # a topk_mean model must NOT equal the max model with the same seed: the contract is honoured
    cli(scene, "m")
    assert not np.allclose(outputs(scene, "k")[0], outputs(scene, "m")[0])


def test_checkpoint_errors(scene, capsys):
    assert cli(scene, "x", ckpt=str(scene["tmp"] / "none.pt")) == 2
    bad = scene["tmp"] / "bad.pt"
    torch.save({"args": {}}, bad)
    assert cli(scene, "x", ckpt=str(bad)) == 2
    assert "no 'model'" in capsys.readouterr().err
    import argparse
    pk = scene["tmp"] / "pickled.pt"
    ck = torch.load(scene["ckpt"], weights_only=True)
    ck["args"] = argparse.Namespace(**ck["args"])                     # needs pickle to load
    torch.save(ck, pk)
    assert cli(scene, "x", ckpt=str(pk)) == 2
    assert "--trust-checkpoint" in capsys.readouterr().err


def test_pickled_checkpoint_loads_only_with_trust(scene):
    import argparse
    ck = torch.load(scene["ckpt"], weights_only=True)
    ck["args"] = argparse.Namespace(**ck["args"])
    pk = scene["tmp"] / "pickled.pt"
    torch.save(ck, pk)
    with pytest.raises(sf.InputError, match="trust-checkpoint"):
        ii.load_checkpoint(str(pk))
    assert ii.load_checkpoint(str(pk), trust=True)["model"]


def test_cli_input_errors(scene, capsys):
    bad_mesh = scene["tmp"] / "nomesh"
    assert ii.main([str(bad_mesh), "--zarr", scene["zarr"], "--checkpoint", scene["ckpt"],
                    "--out-dir", str(scene["tmp"] / "e")]) == 2
    assert ii.main([scene["mesh"], "--zarr", str(scene["tmp"] / "no.zarr"), "--checkpoint", scene["ckpt"],
                    "--out-dir", str(scene["tmp"] / "e")]) == 2
    os.remove(scene["mesh"] + "/meta.json")                           # no scale, no voxel size
    assert ii.main([scene["mesh"], "--zarr", scene["zarr"], "--checkpoint", scene["ckpt"],
                    "--out-dir", str(scene["tmp"] / "e")]) == 2
    assert "voxel size" in capsys.readouterr().err
    assert cli(scene, "e", "--scan-voxel-um", "3.24") == 2            # voxel given, scale still missing
    assert cli(scene, "ok", "--scan-voxel-um", "3.24", "--mesh-scale", "1", "1") == 0


def test_pitch_mismatch_warns(scene, capsys):
    assert cli(scene, "w", "--out-pitch-um", "6.48", "--scan-voxel-um", "3.24") == 0
    assert "training pitch" in capsys.readouterr().err
    assert outputs(scene, "w")[0].shape[0] < 48 + 1


# ================================================================== resume
class Boom(RuntimeError):
    pass


class FlakyStub(StubModel):
    def __init__(self, fail_after):
        self.n, self.fail_after = 0, fail_after

    def ink_logits_2d(self, x):
        self.n += 1
        if self.n > self.fail_after:
            raise Boom("simulated interruption")
        return super().ink_logits_2d(x)


def test_resume_matches_uninterrupted_run(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 70, 83, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 112), half=0)
    ct[Z0 - 6:Z0 + 7, Y0:Y0 + 70, X0:X0 + 83] = np.random.default_rng(3).integers(0, 255, (13, 70, 83), dtype=np.uint8)
    vol, surf = sf.CTVolume(ct), surface_for(mesh, 1.0)
    cfg = {"k": 1}
    ref, _, st = infer(vol, surf, patch=32, stride=16, config=cfg)
    n = st["patches"]
    assert n > 6

    wd = str(tmp_path / "work")
    msgs = []
    with pytest.raises(Boom):
        infer(vol, surf, FlakyStub(fail_after=3), work_dir=wd, save_every=1, config=cfg)     # batch_size 2
    z = np.load(os.path.join(wd, "state.npz"))
    assert int(z["done"]) == 6 and not os.path.exists(os.path.join(wd, "state.npz.tmp.npz"))

    out, _, st2 = infer(vol, surf, work_dir=wd, resume=True, save_every=1, config=cfg, log=msgs.append)
    assert any(f"resumed: 6/{n}" in m for m in msgs)
    np.testing.assert_allclose(out, ref, atol=1e-6)
    assert int(np.load(os.path.join(wd, "state.npz"))["done"]) == n

    # resuming an already-finished state does no model calls and returns the same map
    out2, _, _ = infer(vol, surf, FlakyStub(fail_after=0), work_dir=wd, resume=True, config=cfg)
    np.testing.assert_allclose(out2, ref, atol=1e-6)


def test_resume_with_odd_progress_and_batch_sizes(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    ct = make_ct((40, 96, 96), half=0)
    ct[Z0, Y0:Y0 + 64, X0:X0 + 64] = np.random.default_rng(5).integers(0, 255, (64, 64), dtype=np.uint8)
    vol, surf = sf.CTVolume(ct), surface_for(mesh, 1.0)
    ref, _, st = infer(vol, surf, config={})
    wd = str(tmp_path / "w")
    with pytest.raises(Boom):
        infer(vol, surf, FlakyStub(fail_after=2), batch_size=4, work_dir=wd, save_every=1, config={})
    assert int(np.load(os.path.join(wd, "state.npz"))["done"]) == 8
    out, _, _ = infer(vol, surf, batch_size=4, work_dir=wd, resume=True, config={})
    np.testing.assert_allclose(out, ref, atol=1e-6)


def test_resume_refuses_changed_settings(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    vol, surf = sf.CTVolume(make_ct((40, 96, 96), half=0)), surface_for(mesh, 1.0)
    wd = str(tmp_path / "w")
    infer(vol, surf, work_dir=wd, config={"flip": False})
    with pytest.raises(sf.InputError, match="different settings"):
        infer(vol, surf, work_dir=wd, resume=True, config={"flip": True})


def test_without_resume_flag_state_is_ignored_and_overwritten(tmp_path):
    mesh = write_plane_mesh(tmp_path / "m", 64, 64, z0=Z0, x0=X0, y0=Y0)
    vol, surf = sf.CTVolume(make_ct((40, 96, 96), spot=(Z0, Y0 + 5, X0 + 5), half=0)), surface_for(mesh, 1.0)
    wd = str(tmp_path / "w")
    a, _, _ = infer(vol, surf, work_dir=wd, config={})
    b, _, _ = infer(vol, surf, work_dir=wd, config={})            # no resume: must not double-count
    np.testing.assert_allclose(a, b, atol=1e-6)


def test_cli_resume_after_real_interruption(scene, monkeypatch):
    from vesuvius_unet.model import UNet3D
    assert cli(scene, "ref") == 0
    real, calls = UNet3D.ink_logits_2d, {"n": 0}

    def flaky(self, x):
        calls["n"] += 1
        if calls["n"] > 2:
            raise Boom("simulated pod preemption")
        return real(self, x)

    monkeypatch.setattr(UNet3D, "ink_logits_2d", flaky)
    with pytest.raises(Boom):
        cli(scene, "res", "--save-every", "1", "--batch-size", "1")
    assert not (scene["tmp"] / "res" / "ink_prob.npy").exists()          # no half-written output
    assert int(np.load(scene["tmp"] / "res" / "work" / "state.npz")["done"]) == 2
    monkeypatch.setattr(UNet3D, "ink_logits_2d", real)
    assert cli(scene, "res", "--resume", "--save-every", "1", "--batch-size", "1") == 0
    np.testing.assert_allclose(outputs(scene, "res")[0].astype(np.float32),
                               outputs(scene, "ref")[0].astype(np.float32), atol=2e-3)


def test_cli_resume_refuses_other_checkpoint_or_flip(scene, capsys):
    cli(scene, "r", "--save-every", "1")
    other = tiny_checkpoint(str(scene["tmp"] / "other.pt"), seed=7)
    assert cli(scene, "r", "--resume", ckpt=other) == 2
    assert "different settings" in capsys.readouterr().err
    assert cli(scene, "r", "--resume", "--flip-normal") == 2
    assert cli(scene, "r", "--resume", "--min-valid-frac", "0.5") == 2
    assert cli(scene, "r", "--resume", "--norm-max", "100") == 2
    assert cli(scene, "r", "--resume") == 0
