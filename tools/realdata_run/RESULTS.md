# Brief 14: first run on real public scan data (3 Nov 2026)

Data: `testdata/pherc_paris4_45um/` only (PHerc. Paris 4, Scroll 1, CC BY-NC; two tifxyz meshes `w116-117`, `w118-119`
and three slices z = 2073, 2600, 3128; 45.532 um voxels). CPU only. **No tool default was changed and no tool file
was edited.** Where a tool needed something to run, it is listed under "Flags and workarounds". Commands: `run_all.sh`.
Raw outputs: `out/`. Overlays: `docs/realdata/`.

Base: `main` (b6c8782). `tool/ink-e2e` and `chore/release-0.1` were already in `main`; only
`testdata/pherc-paris4-45um` was merged.

## Honest summary

**What worked.**
- Both real meshes load with `ssc_io` and match `docs/FORMATS.md` on layout, dtype, sentinel, scale and bbox order.
- `sheet_spacing_check`, `sheet_switch_finder` and `trace_auditor` all ran to completion and wrote reports and overlays.
- The tools' own reporting was honest in several places: `umbilicus_finder` marked every slice LOW, and the spacing
  tool flagged PITCH-MISMATCH on every height.

**What did not work.**
1. **The adjacent real meshes cannot be fed to `sheet_spacing_check` as they are.** Their grids differ (130x354 vs 129x357) and the tool
   refuses unequal shapes (`sheet_spacing_check.py:321`). `trace_auditor` degrades this to NOT JUDGED.
   I ran it on padded temp copies.
2. **`umbilicus_finder` gave no usable centre.** All 3 slices LOW (residual 9-17 pitches). The default pitch search finds no pitch (`no_pitch`),
   so `--pitch-vox 8` was needed just to get a number. Only the z=3128 estimate visibly sits on the whorl; at z=2073 the
   slice has no clear whorl.
3. **The CT pitch estimate is about 1.5-1.8x too large at defaults** (14-17 vs 9-10 voxels measured independently), so
   every pitch-relative threshold downstream is off.
4. **The meshes are about 3.5 voxels apart, about a third of the CT pitch.** On the four curves (A's two turns, B's two turns) the
   measured spacing is roughly equal steps of 3.5 voxels across a 10-voxel stack. `sheet_spacing_check` therefore says
   66-87 % "shared" and 9-25 % clean. I cannot tell from this sample whether that is a tool failure or the data's truth
   (see "What the phantoms got wrong").
5. **The switch finder was blind to the deliberate break** (Task 6) and reports 25-34 switches per mesh on the unbroken traces,
   mostly low confidence.
6. **The auditor FAILs everything**, including the unbroken originals, with 112-142 winding "jumps" per trace. A FAIL here carries no information.

**Thresholds that look wrong at this resolution** (all are existing defaults; evidence below):
`sheet_spacing_check --peak-prominence-frac 0.25` (gives 14-17 voxels; 0.05 gives 9.5-10.5), `umbilicus_finder --pitch-min-peak 0.1`
(real autocorrelation second lobe is below 0.1), `umbilicus_finder --target-px 1000` (puts one pitch at about 3.5 ds px; README asks for 8-25),
`trace_auditor --wn-jump-pitch 0.6` (about 110+ jumps per trace on a non-concentric scroll), `--min-switch-confidence 0.3`.

**No fixes in this PR.** Proposed follow-ups are at the end, each with its evidence.

## Flags and workarounds (everything non-default is listed here)

| Task | What | Why |
|---|---|---|
| 2 | `umbilicus_finder ... --pitch-vox 8 --export-all`, `--pixel-um 45.532 --voxel-um 45.532`, `--z-start 0 --z-stop 3 --z-step 1` | default finds no pitch; z = slice index for a PNG directory (see F2), results relabelled 2073/2600/3128 |
| 3 | meshes padded with `-1` to 130x357 in a temp dir (`pad_meshes.py`) | grid shapes differ (F1); `--png-dir`, `--png-pixel-um 45.532`, `--voxel-size-um 45.532` |
| 3 | sensitivity run `--peak-prominence-frac 0.05` | evidence only, not used for the headline numbers |
| 4 | none beyond `--png-dir/--png-pixel-um/--voxel-size-um`; extra runs with `--pitch-vox 9.5` in Task 6 | |
| 5 | `--umbilicus out/umbilicus_estimated.json` (the finder's LOW output, relabelled to true z) | the finder gave no OK slice, so the auditor could not use its own |
| 6 | `--pitch-vox 9.5` in the second variant | measured pitch (below) |

## Task 1: format

Script `task1_format.py`, output `out/task1_format.txt`.

| | w116-117 | w118-119 |
|---|---|---|
| x/y/z.tif on disk | float32, (130, 354), untiled, uncompressed | float32, (129, 357), untiled, uncompressed |
| `ssc_io` arrays | float64 (130, 354) | float64 (129, 357) |
| invalid cells | 6451 / 46020 (14.0 %) | 6161 / 46053 (13.4 %) |
| sentinel pattern | all three = -1 in every invalid cell, **0 partial** | same |
| non-finite values | 0 | 0 |
| `z <= 0` cells | 6451 (= the sentinel cells, so M2 does not bite here) | 6161 |
| `mask.tif` | absent (M1 not exercised) | absent |
| bbox computed vs `meta.json` | identical (max abs diff 0.0), **XYZ order** | identical |
| `scale` | [0.05, 0.05] | [0.05, 0.05] |
| measured step along columns / rows | 19.83 / 19.92 vox (1/scale = 20) | 19.84 / 19.91 |
| z varies along | rows (mean abs dz 18.1 per row vs 2.9 per column) | 18.2 vs 2.9 |
| `meta.json` keys | `area_vx2, bbox, format, scale, type, uuid` | same |

Does `docs/FORMATS.md` hold on real VC3D output? **Yes** for axis order, dtype, shape (rows, cols), the (-1,-1,-1) sentinel,
the scale pair, the bbox order and z along rows. Findings:

- **F1 (blocker for the pair).** Two adjacent real meshes have different grid shapes. The "identical grid shape" requirement
  (`tools/sheet_spacing_check/sheet_spacing_check.py:321`, README "Inputs") does not hold for real traces. Same-column
  distance between A and B is a median 36 voxels (p90 67), so columns are not aligned either (`out/task3_align.txt`).
- **F2.** `uf_io.py` has no mesh loader at all; "load with `uf_io`" means its volume loader. `PngVolume` (`uf_io.py:118-125`) sorts the files and
  uses the **list index as z**; the 5-digit z in the file name is ignored, unlike `ssc_io` (`--png-pattern {z:05d}.png`). With 3 files the
  heights come out as 0, 1, 2 and the overlays are named `overlay_z000000.0.png`.
- **F3.** `meta.json` has no voxel size (M5 confirmed). `uuid` is the literal string `"out"` in both files (not a uuid, not the folder name).
- **F4.** `docs/FORMATS.md` line 4 ("Nothing here was run against real scan data") is now stale. M1 (mask) and M2 (`z > 0`) were not
  exercised by these files.

Test added: `tests/test_real_vc3d_meshes.py` (shape, dtype, finite fraction, bbox, step, rows-along-z, and that the shapes differ).

## Task 2: centre line

`umbilicus_finder`, three slices, `--pitch-vox 8`; overlays `docs/realdata/umbilicus_z02073.png` etc.
(`overlay` labels read z=0,1,2: finding F2). Data `out/umbilicus/`.

| z | centre x, y (px = voxels) | confidence | flag | reason | residual (pitches) | coverage |
|---|---|---|---|---|---|---|
| 2073 | 1160.9, 1021.9 | 0.003 | LOW | high_residual | 17.1 | 360 deg |
| 2600 | 1150.4, 1075.8 | 0.009 | LOW | high_residual | 10.7 | 360 deg |
| 3128 | 1150.4, 1204.6 | 0.007 | LOW | high_residual | 12.1 | 360 deg |

- Without `--pitch-vox` every slice is LOW with reason `no_pitch` and the centres are x 1161/1150/1150, y 1022/1076/1205 (the same numbers; the pitch only changes the flag).
- Variants tried (all LOW): `--sigma-int 6` (y 1009/1072/1207); `--target-px 2264 --sigma-int 6` (x 1171/1140/1140, y 1025/1090/1206);
  `--target-px 2264 --sigma-int 10 --coherence-min 0.6` (residual 9.2-12.8). None reach OK.
- By eye (z=2600 slice, centre of the whorl) the centre is about x 1205, y 1076. The finder's y agrees, x is about 55 px
  (2.5 mm) off. At z=3128 the green cross sits on the visible whorl. At z=2073 the scroll is flattened with no clear whorl,
  and the finder's point is arbitrary. The centre is not x/y-stable between heights (y moves 183 px between z=2073 and z=3128), which a
  tilted or squashed scroll could do, but I cannot separate that from estimator error.
- Why it fails (hypothesis, not tested further): the mask is the whole scroll including a long, nearly flat outer wrap whose normals do not meet at one point
  (visible on the overlays as red lines fanning out from the outer layers).

## Pitch measurement (needed for Tasks 2-6; `measure_pitch.py`, `measure_pitch_normals.py`, `out/pitch_measurement.json`)

| method | result |
|---|---|
| radial profiles about the rough centre, peak gaps (r 30-160 px) | median **8.0** vox, IQR 6-10.5 (stable for 3 trial centres) |
| profiles along the mesh normals, +-40 vox, first autocorrelation peak | **9.0-9.5** vox (IQR 7.5-11.5), both meshes, all heights |
| same, peak-gap median at prominence 0.15 | 9.0-10.0 vox (IQR 7-14) |
| `sheet_spacing_check` `ct_pitches` at defaults | **14.0-17.0** vox |
| same, `--peak-prominence-frac 0.10` / `0.05` | 11-12 / 9.5-10.5 |
| same, `--profile-halflen-vox 30` + prominence 0.10 | 10-10.5 |
| power spectrum along normals | broad; 8-20 vox holds 58-60 % of 2.5-30 vox power, 4-6 vox 11 %, no sharp line |

Measured pitch near the meshes: **about 9.5 voxels (0.43 mm)**, inside the brief's 7-10 range, but the periodicity is weak and broad
(autocorrelation second lobe below 0.1), so treat +-2 voxels as the honest spread. Inside the scroll (near the whorl) it is about 8.

## Task 3: spacing check (A = w116-117, B = w118-119)

Defaults, padded copies, `out/spacing/default.{json,txt}`, overlays `docs/realdata/spacing_default/`.

| z | A points | CT pitch | mesh pitch | clean | shared | skipped | uncovered | off-sheet (A / B) | flag |
|---|---|---|---|---|---|---|---|---|---|
| 2073 | 347 | 17.0 | 5.18 | 16.4 % | 79.8 % | 0.0 % | 0.0 % | 4.0 % / 5.2 % | PITCH-MISMATCH |
| 2600 | 340 | 17.0 | 4.64 | 8.8 % | 87.4 % | 0.6 % | 0.0 % | 18.8 % / 19.7 % | PITCH-MISMATCH |
| 3128 | 336 | 14.0 | 5.69 | 25.3 % | 66.1 % | 1.2 % | 0.0 % | 23.8 % / 25.0 % | PITCH-MISMATCH |

(off-sheet = 1 - `onsheet_fraction`.) Area clean at >= 2 of 3 heights: 27.5 cm^2 of 240.5 cm^2 sampled.

Sensitivity only, `--peak-prominence-frac 0.05` (CT pitch 10.5 / 10.0 / 9.5): clean 50.4 / 37.6 / 47.0 %, shared 50.4 / 53.5 / 40.8 %,
skipped 2.3 / 1.8 / 3.0 %, still PITCH-MISMATCH; area 100.3 cm^2.

**Two windings per mesh.** Each cut line is one run of 336-350 points that goes **1.99 turns** round the centre (monotonic fraction 0.97-1.00), i.e.
the two windings of a mesh are one continuous spiral line. The tool does not split them: it sees one run, and the nearest-B distance of a point
is taken to the nearest point of **either** of B's turns. The "uncovered" rule is column-based (`--b-missing-cols`) but the columns of A and B are
not aligned (F1), so it reports 0 % uncovered even though 37-47 % of A points have their nearest B point more than 5 columns away
(typically about half the grid, i.e. B's other turn; `out/task3_align.txt`).
Splitting per winding is needed for this to be interpretable.

**Where the four turns sit** (`task3_stack.py`; the split at the middle column is approximate: the radius ranges overlap because the scroll is not round): signed offset along A's
normal, medians over z = 2073 / 2600 / 3128:

| from A turn 1 | A2 -3.3 / -3.7 / -4.0 | B2 +3.6 / +3.2 / +3.7 | B1 +7.1 / +6.7 / +7.7 |
|---|---|---|---|
| from A turn 2 | A1 +3.3 / +3.6 / +4.1 | B2 +6.8 / +6.4 / +7.8 | B1 +10.7 / +10.0 / +11.7 |

So the stack is A2, A1, B2, B1 at about 0, 3.5, 7, 10.5 voxels: four curves in roughly one measured CT pitch. If the pitch is 9.5, w116-117 and w118-119 are not on
separate neighbouring sheets by this measure. I did not resolve what "w116-117" means in terms of surfaces, and the raw CT profiles
(plotted for six points at z=2600) show about 10-voxel waves with finer bumps of 4-5 voxels, so a true sheet pitch near 4-5 voxels
cannot be ruled out either. This data does not settle it.

## Task 4: switch finder

Defaults, each mesh alone, `out/switch/*.json|txt`, overlays `docs/realdata/switch_*/`.
Pitch used by the tool: 17.0 / 17.0 / 14.25 (A), 17.25 / 17.0 / 14.0 (B).

| mesh | z | tracked | off-sheet | lost | switches (H+V) | conf >= 0.3 | conf >= 0.5 |
|---|---|---|---|---|---|---|---|
| w116-117 | 2073 | 49.3 % | 3.2 % | 47.6 % | 7 | 0 | 0 |
| | 2600 | 55.6 % | 18.2 % | 26.2 % | 10 + 3 | 5 | 1 |
| | 3128 | 48.2 % | 22.6 % | 29.2 % | 8 + 6 | 0 | 0 |
| w118-119 | 2073 | 49.4 % | 6.9 % | 43.7 % | 9 | 2 | 1 |
| | 2600 | 45.8 % | 17.8 % | 36.4 % | 9 | 1 | 0 |
| | 3128 | 41.8 % | 23.7 % | 34.5 % | 6 + 1 | 0 | 0 |

34 switches on w116-117 (14 flagged "double"), 25 on w118-119 (11 double). Positions (xyz, row, col, direction, step, confidence)
are in `out/switch/*.txt`; the highest-confidence ones are w116-117 z=2600 col 325 (outward +1.10, 0.56), col 292 (outward +1.02, 0.47),
col 283 (inward -0.85, 0.32); w118-119 z=2073 col 81 (inward -1.01, 0.52). Steps are in tool-pitch units (17 vox), so +1.0 means 17 voxels, not 9.5.
Between 42 and 56 % of each line is tracked at all. **I have not checked any of these by hand against the CT**; a "switch" here is only what the tool reports.
F5: the overlay is an upscaled image (3870x3543) with a 1-pixel line, so the offset-coloured cut line is almost invisible and only the switch rings
can be seen (`docs/realdata/switch_w116-117/overlay_z002600.png`).

## Task 5: auditor (pair, estimated centre, `out/audit/`)

Pair run `pair_default` (exit 1), plus each mesh alone (`A_alone`, `B_alone`; same verdicts for the single-trace checks).

**w116-117 (A): FAIL**
- `switch_finder` FAIL: 5 switches of confidence >= 0.3 (z=2600 cols 283, 292, 325; vertical cols 287, 321).
- `winding_jumps` FAIL: 112 radius jumps (z=2073: 31, incl. -13.07 pitch at col 126 and -11.46 at col 299; z=2600: 38; z=3128: 43; sizes 0.6 to 13.1 pitches), full list in `out/audit/pair_default/audit.txt`.

**w118-119 (B): FAIL**
- `switch_finder` FAIL: 3 switches (z=2073 cols 81, 87; z=2600 col 45, +3.14 pitch).
- `winding_jumps` FAIL: 115 jumps (z=2073: 39, z=2600: 35, z=3128: 41; sizes 0.62 to 13.2 pitches, e.g. -13.2 at col 128 and -13.0 at col 302 at z=2073).
- `spacing` **NOT JUDGED**: "grid shapes differ ... the meshes must be traced on the same grid" (F1).
- `winding_offset` FAIL: B is +0.36 / +0.32 / +0.41 pitch from the nearest A sheet (whole sheets 0), only 29 / 22 / 39 % of points adjacent.

The same sort of reasons appear on both meshes, and no jump is smaller than 0.6 pitch (the threshold).
The `winding_jumps` and `winding_offset` checks use the (LOW, wrong-by-tens-of-pixels) centre and, internally, the tool's 17-voxel pitch.
Several of the huge jumps (-13 pitch) sit at the same angles (68 deg, 303 deg, 355 deg) in both meshes and both turns, which looks
like the centre or the non-concentric shape, not a trace error.

## Task 6: deliberately broken copy

`task6_break.py`: every valid point with grid column > 120 moved radially outward in xy by 9.5 voxels (the measured pitch) from the estimated centre (interpolated in z), written to a temp dir (not committed).
Check: at cols <= 120 the cut line is unchanged, at cols > 120 it is shifted by exactly 9.5 voxels, and the in-plane step across col 120 to 121 grows
from 27.1 / 19.4 / 20.2 to 36.5 / 25.6 / 22.8 voxels (z = 2073 / 2600 / 3128).

| tool | setting | original | broken copy | flagged at col 112-128? |
|---|---|---|---|---|
| switch finder | default (pitch about 17) | 34 switches, 5 with conf >= 0.3 | 31, 1 with conf >= 0.3 | **No.** Near col 120 only conf 0.00 vertical "inward" switches (z=3128); the original has the same kind of entry |
| switch finder | `--pitch-vox 9.5` | 11 switches, 1 with conf >= 0.3 | 10, 0 with conf >= 0.3 | **No.** z=2600 col ~120: an inward -1.56 and an outward +2.76, both conf 0.00 (the original also has +2.83, 0.00) |
| auditor | default | FAIL | FAIL (1 switch conf >= 0.3, 116 jumps) | verdict identical; jump list near col 120: original (2073: +3.28 at col 120, 3128: +0.93 at col 119), broken adds (2600: +0.89 at col 121) |
| auditor | `--pitch-vox 9.5` | FAIL | FAIL (switch_finder NOT JUDGED, 138 jumps) | jump +1.79 at z=2600 col 121 in the broken copy vs +0.79 in the original |

**Answer: the switch finder did not flag the break. The auditor "flagged" it only in the sense that it FAILs the unbroken original too.**
The only break-specific signal is one winding jump of +0.9 to +1.8 pitch at z=2600 col 121 among 110-140 other jumps. Not a detection.

## What the phantoms got wrong about reality

1. **Concentric, round, one sheet per turn.** The real slice is a flattened, faulted, non-concentric roll with a long outer wrap. The structure-tensor centre and everything
   that unwraps about it (`winding_jumps`, `winding_offset`) fail (Tasks 2 and 5).
2. **Contrast.** The phantoms (as built for the tests) have clear dark gaps between sheets; real profiles are about 10-voxel waves with 4-5 voxel texture and no sharp periodicity. Prominence-based peak
   counting then drops or splits sheets (14-17 vs 9.5-10), and autocorrelation peaks are below the 0.1 acceptance level.
3. **Mesh sampling.** Real VC3D grids are 20 voxels per cell (scale 0.05), about two sheets per cell, so a cut line has one point every 20 voxels (336-350 points per height); the switch finder's K = 5 points is 100 voxels of line, which is more than 10 pitches.
4. **Same grid on both meshes.** Real traces of adjacent windings come as independent grids of different size and column origin (F1).
5. **Two windings in one mesh.** Phantom meshes were one turn per mesh; real ones are one continuous 2-turn spiral, which the cut-line, nearest-B and column logic do not model.
6. **Holes.** 13-14 % of real cells are invalid (I did not re-check how many the phantoms had).
7. **Metadata.** No voxel size, `uuid = "out"`, no mask, PNG slices named by z not indexed (F2).

## Proposed follow-ups (not done here)

| # | Proposal | Evidence |
|---|---|---|
| P1 | Let `sheet_spacing_check` accept different grid shapes, or pair meshes spatially rather than by column; document it | F1, `sheet_spacing_check.py:321`; same-column distance 36 vox; 37-47 % nearest-B at other turn |
| P2 | Split a multi-winding cut line per turn (by unwrapped angle about the centre) before the A to B pairing | 1.99 turns, one run; stack A2/A1/B2/B1 |
| P3 | Re-tune `peak_prominence_frac` (about 0.05-0.10) or estimate the pitch by autocorrelation; add a warning when CT and mesh pitch differ by more than 1.5x | 14-17 vs 9-10.5 voxels; 3 heights, both meshes |
| P4 | `umbilicus_finder`: lower `--pitch-min-peak`, and a documented `--target-px` rule so a pitch is 8-25 ds px; a PNG option that reads z from the file name; optionally ignore the outer wrap | no_pitch at default, 0/3 OK, F2 |
| P5 | `trace_auditor`: do not use `winding_jumps` unless the centre is OK; or report the jump count as unreliable; add a no-trace reference | 112-142 jumps per trace, original and broken alike |
| P6 | Switch finder: draw the overlay line at a visible width; report points per switch in the JSON | F5 |
| P7 | Check by hand whether w116-117 and w118-119 really sit on separate neighbouring sheets, and what the winding labels mean | stack at 3.5 voxel spacing within one pitch |
| P8 | Update `docs/FORMATS.md` (real data now run; no voxel size; `uuid` = "out") | F3, F4 |
| P9 | A mask-bearing real mesh to exercise M1; a z <= 0 case for M2 | not covered by this sample |

## Limits of this run

Three slices and two meshes, one volume. All centre/pitch conclusions rest on 3 heights. The "broken" test used one column and one shift size. No result here was
confirmed by hand beyond the zoom crops and six normal profiles I looked at. The by-eye centre is read off a downscaled image.
