# Benchmark on phantoms (256^3, seed 0, `python tools/phantom_scroll/benchmark.py --size 256`)

Phantoms: **round** (no deformation), **mild** (squash 0.85, warp 3 vox, irregular 0.05, tilt), **bad**
(squash 0.55, warp 7 vox, irregular 0.12, tilt), **merged** (squash 0.8, warp 3, one local squeeze that
makes turns 1 and 2 touch). 4 turns, pitch 22 vox, sheet FWHM 6 vox, grid step 4 vox, noise 0.04. Heights:
25/40/50/60/75% of z. Three bad traces per phantom (outward hard hop on turn 1, inward 4-column ramp on
turn 2, outward hard hop on turn 0); a switch is FOUND if a horizontal switch with the right direction lies
within 3 columns (+ half the ramp width) of the true column at >= 1 height.

| phantom | switches found / true | recall (trace x height) | col err (med) | false sw. on true turns | false sw. on bad traces | centre err mean / max (vox) | umb. OK slices | clean: true pairs | clean: skipped | clean: shared | clean: off-sheet |
|---|---|---|---|---|---|---|---|---|---|---|---|
| round | 3 / 3 | 1.00 | 0.0 | 0 | 0 | 0.4 / 0.5 | 30 / 30 | 0.97 | 0.05 | 0.00 | 0.00 |
| mild | 3 / 3 | 1.00 | 0.0 | 0 | 0 | 2.3 / 4.1 | 30 / 30 | 0.97 | 0.04 | 0.00 | 0.00 |
| bad | 3 / 3 | 0.73 | 0.0 | 0 | 1 | 4.7 / 8.7 | 14 / 30 | 0.96 | 0.12 | 0.00 | 0.30 |
| merged | 3 / 3 | 0.93 | 0.0 | 0 | 0 | 2.4 / 4.7 | 30 / 30 | 0.96 | 0.07 | 0.00 | 0.00 |

Reading it (honestly):
- **sheet_switch_finder** finds every planted switch at the right column (median error 0 columns) on all four
  phantoms, with no false switch on any true turn. Per (trace, height) recall falls to 0.73 on the badly crushed
  phantom (it loses the sheet at some heights) and there is one extra switch on a bad trace there.
- **umbilicus_finder**: centre error grows with the deformation (0.4 -> 2.3 -> 4.7 vox mean, 8.7 max on the badly
  crushed one) and only 14 of 30 slices are flagged OK there. The truth is the *deformed axis*; with a non-affine
  warp the point of concentricity of the sheets is not exactly that point, so part of the error on mild/bad/merged is
  definitional (the warp amplitude is 3-7 voxels). Treat the "bad" number as an upper bound on the tool's error.
- **sheet_spacing_check**: true adjacent pairs are 0.96-0.97 clean on all four. A skipped sheet, a shared sheet and a
  mesh in the dark gap are rejected (clean <= 0.12) except the dark-gap pair on the badly crushed phantom, which is still
  0.30 clean (the on-sheet test is Otsu-based and the dark gap there is brighter).
- Not run: `ink_infer` (needs torch and a checkpoint).
- One seed, one grid step, one pitch: this says where the tools can fail, not how often.
