# Review round 1: the four tools, read as a sceptic

Scope: `tools/sheet_spacing_check` (+ `ssc_io.py`), `tools/sheet_switch_finder`, `tools/umbilicus_finder`
(+ `uf_io.py`), `tools/ink_infer` (+ `surface.py`). Every line was read; file:line below refer to `main` at
`e08ebfc` (the state before this PR). Reviewer and author are the same model family, so this is a second
read, not an independent human audit. No real scan data was available: every "BUG" below is shown on
synthetic data built to be realistic in the one respect that matters (grid step, sheet pitch, mask file).

Findings: **BUG** = wrong result, **RISK** = right in the tested regime, silently wrong or unusable
outside it, **NIT** = cosmetic or negligible. Tests: `tests/test_review_round1.py` (written first; the
commit before the fixes is red). "Fixed" means the failing test now passes.

## Summary

| Id | Sev | Tool | Status |
|---|---|---|---|
| B1 | BUG | sheet_spacing_check | fixed |
| B3 | BUG | ssc_io, ink_infer/surface | fixed (this is Part A's BUG-A1 / M1) |
| B2 | RISK | sheet_spacing_check | fixed (now a warning) |
| B4 | RISK | ssc_io, ink_infer/surface | fixed (now refuses) |
| B5 | RISK | umbilicus_finder | fixed (now a warning) |
| R1 | RISK | sheet_switch_finder | not fixed, documented limit; strict xfail test |
| R2 | RISK | sheet_switch_finder | not fixed; strict xfail test |
| R3 | RISK | ink_infer | FIXED in tool/ink-e2e: InputError (exit 2) when no patch is valid; tests first |
| R4 | RISK | ssc_io / surface | not fixed: decision needed (z > 0 rule) |
| R5 | RISK | sheet_switch_finder | not fixed: documentation |
| N1-N6 | NIT | various | not fixed |

## Fixed

### B1 (BUG) `sheet_spacing_check.py:93`: `max_gap_vox = 20` is an absolute length
`brk = (np.diff(c) != 1) | (step > p.max_gap_vox)` cuts the cut line wherever consecutive points are more
than 20 voxels apart. A VC3D tifxyz with `scale = 0.05` has 20 voxels per cell, so the normal
point-to-point step is about 20 and slightly more on a curved sheet: every point becomes a one-point run,
`normals()` returns NaN for runs shorter than 2, no CT pitch is measured, and every point is "no pitch"
and not clean. Result: `clean_fraction = 0` for a perfectly good pair of sheets. The synthetic tests used
0.9-voxel steps and never saw it. Measured (cylinders R=100, pitch 12):

| grid step (vox) | 1 | 8 | 16 | 20 | 24 | 30 |
|---|---|---|---|---|---|---|
| clean fraction before | 1.0 | 1.0 | 1.0 | **0.0** | **0.0** | **0.0** |

Test: `test_B1_coarse_grid_is_not_split_into_single_point_runs[20.0|24.0|30.0]`; control
`test_B1_a_real_jump_still_splits_a_fine_grid`.
Fix: the gap is `max(max_gap_vox, 3 x median consecutive step)`, so `max_gap_vox` is now a floor. Behaviour on
fine grids is unchanged (all 126 earlier tests pass).

### B3 (BUG) `ssc_io.py:42-94`, `surface.py:19-58`: `mask.tif` is ignored
VC3D marks cells invalid with `mask.tif` (valid iff the mask value is >= 255; the mask may be a whole
multiple of the grid) while x/y/z keep real coordinates (docs/FORMATS.md section 1). Our readers treat
those cells as good surface. Tests: `test_B3_*` (five). Fix: both readers read `mask.tif` when present,
treat < 255 as invalid, accept integer multiples, raise `InputError` on an incompatible shape. A directory
without `mask.tif` is unchanged. (VC3D itself silently ignores an incompatible mask; we refuse, because
this is a QA tool and a corrupt directory should be loud.)

### B2 (RISK) `sheet_spacing_check.py:158-183, 260`: an unmeasurable CT pitch is only a `null`
`ct_pitches` needs `min_peaks = 3` peaks inside +/- `profile_halflen_vox = 60` voxels. With a sheet pitch of
about 60 voxels or more it never finds them: measured pitch 12, 24, 36, 48 fine; 60 and 80 -> `ct_pitch_vox
= None`, `clean = 0`. At 3.24 um voxels (the training pitch) a 200 um sheet spacing is 60 voxels, so this
matters. The result row says `n/a` but the top-level `warnings` was empty. Test:
`test_B2_unmeasurable_pitch_is_a_warning`. Fix: a warning naming the heights and `--profile-halflen-vox`.
Not changed: the default itself (needs real data to choose).

### B4 (RISK) `ssc_io.py:135-150`, `surface.py:127-137`: Zarr level = 2**L on every axis, silently
`umbilicus_finder` reads the OME scale transforms; the other two tools assume 2**L. A pyramid that halves
x/y but not z gives the wrong slice with no message. Tests: `test_B4_*`. Fix: if the OME metadata is
present and disagrees with 2**L on any axis, raise `InputError`. No OME metadata: legacy behaviour.

### B5 (RISK) `umbilicus_finder.py:494-502`: zero OK slices exits 0 with an empty export
If no slice is OK (e.g. the pitch cannot be estimated, so every slice is LOW) the command prints
"0 OK" but exits 0 and writes `{"control_points": []}`, which villa's reader cannot interpolate. Test:
`test_B5_empty_villa_export_is_reported`. Fix: a warning on stderr (exit code unchanged: it is documented).

## Not fixed (and why)

### R1 (RISK) `sheet_switch_finder.py:289`: no switch is found in the first or last K = 5 points of a run
`detect_steps` needs K points on both sides. A closed ring is not joined round its seam. Documented in the
tool README ("Limits"). A fix needs a wrap-around join and a different persistence rule on short ends: a
design change, not a patch. Test: `test_R1_switch_at_the_start_of_the_line_is_found` (strict xfail).

### R2 (RISK) `sheet_switch_finder.py:244`: the 0.5-pitch tracking gate fails on a coarse grid
At grid step 30 vox and pitch 12 vox, half the line is lost (tracked 0.52), the hop is missed, and there is
no warning. Up to step 20 it works (hop found, one switch, in the probe). The gate and `max_gap_pitches`
are in pitches but the grid step is in voxels. Fixing it properly means tracking across larger jumps or
interpolating the line, which changes the algorithm. Test:
`test_R2_hop_on_a_coarse_grid_is_found_or_warned` (strict xfail; it also passes if a warning is added, which
would be the cheap fix and is left to the owner of the tool).

### R3 (RISK) `ink_infer.py:112-113, 170`: no patch with >= `min_valid_frac` valid pixels -> an all-black map
`coords` can be empty; the loop does nothing; `prob` is all zeros, exit 0, the output is a picture of
"no ink". An `InputError` would be the fix. Not done: it needs torch to run `run_inference`, and torch is
not installed here or in CI, so there is no failing test to write first.

### R4 (RISK) the `z > 0` rule
The object store's `validSurfacePoint` requires `z > 0`; VC3D core and our readers accept `z == 0`
(docs/FORMATS.md M2). A decision, not a bug: say which reference you want.

### R5 (RISK) `sheet_switch_finder.py` `--transpose`: `row` and `col` in the report refer to the transposed grid
A user cannot map them back to the file without knowing it. Documentation fix only.

## NIT (not fixed)
- N1 `ssc_io.slice_index_for` floors `z / sc` (`ssc_io.py:100`); `uf_io.level0_to_slice_index` rounds a
  centre-based expression (`uf_io.py:25`). Same slice for integer z, different for fractional z on level > 0.
- N2 `sheet_switch_finder.py:263` uses Python `round` (banker's) in `confidence`; `sheets_for` (`:274`) uses
  `floor(a + .5)`. At exactly x.5 they pick different integers; confidence is 0 there anyway.
- N3 `sheet_spacing_check.py:299` `heights_bands`: duplicate heights give a zero-width band (area 0 at that height).
- N4 `sheet_switch_finder.py:158`: `tilt_window` is not validated odd; an even value shifts the median.
- N5 `uf_io.py:98`: one OME scale is used for both x and y (assumes isotropic in-plane).
- N6 `ssc_io.py:57` (and `surface.py:30`): an invalid `scale` is silently `None` (VC3D throws). `ink_infer` raises
  later, `ssc` only skips its cross-check.

## Read and found sound (no finding)
Axis order and (row, col) / (x, y) handling in `cut_line`, `cut_rows`, `to_px`, `CTVolume.sample`
(tested with off-centre, non-square geometry); voxel <-> pixel conventions (`(i + 0.5) s - 0.5`, identical in
all three tools); area units (`(voxel_um * 1e-4)^2` cm^2, `1 / sqrt(1 - nz^2)` band factor); the structure
tensor / closed-form centre / Tukey re-weighting in `umbilicus_finder` (units in downsampled pixels are
converted with `f * scale_xy` everywhere); spline weights (`w = sqrt(conf) / sigma`, `s = n`); `patch_grid`
and the resume state in `ink_infer`; NaN propagation from invalid cells through `resample_mesh` (the invalid
zone is at most one output pixel wider than the interpolation support, which is conservative).
