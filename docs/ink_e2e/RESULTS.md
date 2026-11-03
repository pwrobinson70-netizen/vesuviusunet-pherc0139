# ink_infer end to end on phantoms

Synthetic data only (`tools/phantom_scroll`, 192^3, 4 turns, squash 0.8, warp 3, irregular 0.05, ink on turn 1,
**`--ink-delta 0.20`**: the sheet under the letters is 20% brighter; the generator default is 0.10, which I did
not try). CPU only. torch 2.15.0 (the default PyPI wheel; pytorch.org was not reachable from this sandbox, so
this is not the CPU-only wheel, but no GPU was used).

## Reproduce

```bash
G="--size 192 --turns 4 --squash 0.8 --warp-amp 3 --irregular 0.05 --ink --ink-delta 0.20"
python tools/phantom_scroll/phantom_scroll.py --out PH/train1 $G --seed 11 --ink-text INK
python tools/phantom_scroll/phantom_scroll.py --out PH/train2 $G --seed 12 --ink-text ROMA
python tools/phantom_scroll/phantom_scroll.py --out PH/val    $G --seed 13 --ink-text SUN
python tools/phantom_scroll/phantom_scroll.py --out PH/test   $G --seed 14 --ink-text OAK \
       --bad-switch turn=1,col=40,delta=1,width=0
python tools/ink_infer/phantom_e2e.py train --train PH/train1 PH/train2 --val PH/val \
       --out tools/ink_infer/phantom_ckpt/tiny.pt --minutes 12 --eval-every 50 --max-steps 4000
python tools/ink_infer/phantom_e2e.py score --ckpt tools/ink_infer/phantom_ckpt/tiny.pt \
       --val PH/val --test PH/test --work W --json result.json --png-dir docs/ink_e2e
```

Model: `UNet3D(base_channels=3)`, 188,350 parameters (< 200k), depth 16 layers 1 voxel apart, patch 32,
max-over-depth aggregation, BCE on valid pixels, AdamW 3e-3, batch 8, 4000 steps (10.4 min on 4 cores; log in
`train.log`). Half the training patches are forced to contain ink. The checkpoint with the lowest loss on a
fixed set of 64 val-phantom patches is kept (0.77 MB, committed). Inference is `ink_infer.main` with
`--scan-voxel-um 3.24 --out-pitch-um 3.24` (one pixel per voxel).

## Results (`result.json`)

| Map | AUC | F0.5 at val threshold (0.87) | note |
|---|---|---|---|
| val phantom ("SUN"), true surface | 0.9997 | 0.963 (best on val, that is how the threshold was picked) | also used for checkpoint selection |
| **test phantom ("OAK"), true surface** | **0.986** | **0.832** | test-best F0.5 0.878 (reference only); ink covers 1.9% of valid pixels; predict-everything F0.5 = 0.024 |
| test, BAD trace, whole map | n/a | 0.149 | trace follows turn 1, then hops to turn 2 at column 40 (px 160 of 385) |

Planted switch (switch at output column 160, 16 px either side excluded):

| Zone | trace | AUC | mean p on ink px | mean p off ink | F0.5 @0.87 |
|---|---|---|---|---|---|
| before the switch | true surface | 0.999 | 0.939 | 0.015 | 0.784 |
| before the switch | bad trace | 0.997 | 0.851 | 0.015 | 0.761 |
| after the switch | true surface | 0.977 | 0.856 | 0.035 | 0.795 |
| after the switch | bad trace | **0.547** | **0.004** | 0.045 | **0.000** |

Where the trace sits on the wrong sheet the letters disappear (p on ink 0.86 -> 0.004, AUC 0.98 -> 0.55,
about chance) and the map fills with speckle (sheet texture). Before the switch the bad trace matches the
true one up to a small loss. Maps: `ink_map_true_surface.png`, `ink_map_bad_trace.png`,
`truth_letter_mask.png`, and `panel_truth_true_bad.png` (truth | true surface | bad trace; red line = the
switch column, which also shows as a bright seam).

## What this does and does not show

- The pipeline (mesh resampling, normals, patch extraction, tiling, stitching, checkpoint contract) is
  consistent with a model trained on the same machinery: a localised brightness signal comes out at the right
  pixels, and an off-sheet trace is visible in the ink map. That is all.
- The "ink" is a uniform 20% brightening of the sheet. The model most likely learned "brighter than the
  neighbouring sheet texture", not letter shapes. It says nothing about real ink, which is faint and
  textured.
- The test letters (O, A, K) all occur in the training words (INK, ROMA); the text, seed and warp are new.
  Val and test are different phantoms, but val picked both the checkpoint and the threshold; the test
  numbers are from one phantom and one seed, no confidence interval.
- The off-sheet map degrades because the model sees only +-8 voxels around the trace; a hop of one
  pitch (22 voxels) puts the sheet outside its window. A smaller hop or a thicker window would look different.
- Not tested: real scans, other noise levels, other pitches, other normal orientation (ink here is
  symmetric about the sheet), a model with real depth contracts.
