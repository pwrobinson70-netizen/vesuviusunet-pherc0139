# ink_infer

Runs a trained VesuviusUNET 3-D U-Net checkpoint over one traced segment and writes an
ink-probability **picture** of it.

```
tifxyz mesh (x.tif y.tif z.tif meta.json) + CT volume (OME-Zarr)
  -> resample the mesh to one output pixel per `--out-pitch-um`
  -> sample D layers along the surface normal, centred on the surface
  -> tiled 3-D U-Net inference, depth-aggregated by the checkpoint's own contract
  -> stitched map: ink_prob.npy (float16), ink_prob.png, valid_mask.png, run.json
```

## Use

Install PyTorch for your platform first, then `pip install -r requirements.txt`.

```bash
python tools/ink_infer/ink_infer.py PATH/TO/segment.tifxyz \
    --zarr PATH/TO/volume.zarr --zarr-level 0 \
    --checkpoint PATH/TO/checkpoint.pt \
    --out-dir out/segment
```

Everything is read from the checkpoint's own `args` / `contract` (base channels, aggregation,
top-k, depth, patch size), never from defaults. `run.json` records the checkpoint hash and every
setting that affects the picture. Add `--work-dir` / `--resume` for long runs (see "Resume").
`python tools/ink_infer/ink_infer.py --help` lists the rest.

## Limits (read before you trust a picture)

**What the output is.** A picture of what the network responds to. No labels are used and no score
is computed. It is not a measure of accuracy and not a detection of letters.

**What the checkpoints can support.** In this repository the only transfer result is w045 at
AUC 0.81, measured against the team's ink-prediction map (`new_canon`), not against human labels.
The check against public human labels stopped at its own alignment gate (C11) and was never scored.
The native 9.362 µm / 113 keV render did not learn (AUC 0.59), so pictures made from that render
should be treated as noise until shown otherwise. Applying a PHerc0139 checkpoint to any other
scroll, scan energy or resolution is **unvalidated**.

**Pitch.** `--out-pitch-um` (default 3.24) is both the output pixel size and the layer spacing.
The default is the training pitch named in `scripts/scroll_segment_convert_fable_27102026_rev6.py`.
It has not been checked here against any particular checkpoint; confirm it against the run that
produced yours. The tool warns if you change it, but the model has not seen other scales.

**Not the training pipeline.** Training data went through the converter's zoom. ink_infer instead
samples trilinearly along the surface. The two are not bit-identical and the difference has not
been measured against a trained model.

**Normal direction.** Layer order follows `cross(d/drow, d/dcol)` of the mesh (for a planar mesh
with x along columns and y along rows that is −z). Nothing in the tool knows which side of the
sheet carries the ink or how the training segments were oriented. Run once with and once without
`--flip-normal` and compare by eye. A map that only appears in one orientation is the more
believable one; a map that appears in both is not evidence of anything.

**Intensity.** Input is divided by the dtype maximum (uint8 /255, uint16 /65535, same as
`vesuvius_unet/dataset.py`) and clipped to [0, 1]. The optional `--ref-p1/--ref-p99` rule applies
the converter's mechanical rescale; it is off unless you give a reference, and the tool cannot
tell you whether your scan needs it.

**Coverage.** Pixels that touch a no-data mesh cell (or lie outside the CT volume) are invalid and
written as 0. In the map, 0 therefore means "no data" as well as "no ink"; use `valid_mask.png` to
tell them apart. Segments smaller than one patch are padded with invalid pixels, so the output can
be larger than the mesh. The mesh is read as-is: no check for self-intersection or folds.

**Resume.**
- State (`work/state.npz`) holds the full accumulators and a patch counter, saved atomically every
  `--save-every` batches. An interrupted run loses at most that many batches.
- `--resume` is refused (exit 2) if the saved settings differ from the new ones: checkpoint hash,
  depth, patch, stride, step, flip, blend, TTA, intensity rescale, voxel size, mesh scale,
  `--norm-max`, `--min-valid-frac`.
- It does **not** detect that the mesh or zarr *contents* changed (only their paths are recorded),
  and it does not hash the work dir. Use a fresh `--work-dir` after editing inputs.
- Without `--resume`, an existing state file is overwritten, not continued.
- A resumed run matches an uninterrupted one to float tolerance on CPU. Bit-identical output on GPU
  is not promised.

**Resources.** The whole resampled surface (positions + normals, float64) and two float32
accumulators are held in memory; a very large segment needs RAM accordingly.

**Data policy.** The tool does not check where your data came from. Use public data only. Nothing
in this folder ships scan data, labels or checkpoints.

## Tests

```bash
python -m pytest -p no:cacheprovider tools/ink_infer/tests -v
```

Synthetic data only, CPU only, a few seconds. `test_surface.py` needs no torch (geometry only);
`test_ink_infer.py` calls `pytest.importorskip("torch")` first and is skipped where torch is
absent. The repo CI runs only `tests/` and does not install torch, so it does not run these.


- a painted single-voxel spot must land at the right output pixel (row = y, column = x) for a
  plain mesh, a non-square mesh, an anisotropic mesh scale, a 2-voxel output step, an OME level-1
  volume, and a tilted mesh; `--flip-normal` must reverse the layer order;
- no-data holes stay invalid and zero and do not shift neighbours; small segments are padded;
- tiling and blending reproduce a single-patch run; every pixel is covered;
- a tiny random-weight checkpoint (plain, `module.`-prefixed, top-k) runs through the CLI, is
  deterministic, and respects its stored contract; pickled checkpoints load only with
  `--trust-checkpoint`;
- resume after a simulated crash (stub model and real CLI) equals an uninterrupted run, and is
  refused when settings change.

What the tests do **not** show: that any real checkpoint produces meaningful ink maps, that the
orientation or pitch is right for your data, CUDA/AMP behaviour, or zarr 2.x (tested with zarr 3).
Geometry is checked with a stub model that reports the brightest layer, because a random-weight
network cannot localise a spot.

## End to end on phantoms (synthetic; says nothing about real scans)

`phantom_e2e.py` trains a tiny model (UNet3D `base_channels=3`, 188,350 parameters, depth 16, patch 32,
about 10 CPU minutes) on patches sampled on the true surface of a phantom's ink turn, then runs this tool
(`ink_infer.main`, the real CLI path) on a validation phantom, a test phantom's true surface and a test
trace with a planted sheet switch, and scores the maps against the known letter mask. Results, commands
and limits: `docs/ink_e2e/RESULTS.md`. The 0.77 MB checkpoint is `phantom_ckpt/tiny.pt`; it knows nothing
about real scans and must not be used on them.

R3 (`docs/REVIEW_ROUND1.md`): if no patch has at least `--min-valid-frac` valid pixels the tool now exits 2
with an explanation instead of writing an all-black map.
