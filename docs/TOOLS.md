# Tools

Seven command-line tools for checking traced papyrus surfaces and for running an ink model over one, plus a
synthetic scroll ("phantom") with known truth to test them on. CPU only. Install from the repository root:

```bash
pip install -e .            # or: pip install .      (numpy scipy tifffile pillow zarr)
pip install -e ".[ink]"     # adds torch, needed only for vun-ink
```

Each `vun-*` command is a thin wrapper that calls the `main()` of the script in `tools/<name>/`; the
scripts still run directly (`python tools/<name>/<name>.py`). `vun-<tool> --help` lists every flag. Every
threshold is a flag with a documented default; the long descriptions are in each tool's own README.

Shared input conventions: a **tifxyz** mesh is a folder with `x.tif y.tif z.tif meta.json` (float32 grids,
level-0 voxel coordinates, `-1` = no data; `docs/FORMATS.md`); a CT volume is an OME-Zarr (`--zarr`,
`--zarr-level`) or a PNG slice folder (`--png-dir`).

| Command | Script | Question it answers |
|---|---|---|
| `vun-umbilicus` | `tools/umbilicus_finder` | Where is the scroll's centre line, and how sure is that? |
| `vun-spacing` | `tools/sheet_spacing_check` | Are two traces that should be adjacent turns one sheet apart? |
| `vun-switch` | `tools/sheet_switch_finder` | Does one trace jump onto a neighbouring sheet, and where? |
| `vun-audit` | `tools/trace_auditor` | One verdict (PASS / FAIL / NOT JUDGED) per trace, combining the checks |
| `vun-phantom` | `tools/phantom_scroll` | Make a synthetic scroll with exact truth to test any of the above |
| `vun-ink` | `tools/ink_infer` | Ink-probability picture of one traced segment from a trained checkpoint |
| `vun-merge` | `tools/patch_merger` | Merge overlapping tifxyz patches, but only where the overlap is provably one sheet |
| `vun-sweep` | `tools/winding_sweep` | Every layer of a z band: centre, ray crossings, one patch + audit verdict per winding |
| `vun-groundtruth` | `tools/groundtruth_score` | How often do the checkers raise a false alarm on human-verified real traces, and how far off is the centre line? |
| `vun-sweep` | `tools/winding_sweep` | Every layer of a z band: centre, ray crossings, one patch + audit verdict per winding |
| `vun-merge` | `tools/patch_merger` | Merge overlapping tifxyz patches, but only where the overlap is provably one sheet |

## vun-umbilicus
- **Input:** OME-Zarr / 3-D zarr / PNG folder; z range in level-0 voxels (`--z-start --z-stop --z-step`).
- **Output** (`--out-dir`): `umbilicus.csv` (smoothed centre per z, confidence 0-1, OK/LOW), `umbilicus_summary.json`,
  `umbilicus_villa.json` (villa `control_points` JSON, OK points only), optional overlays.
- **Limits:** every LOW point is one the method does not trust; exit 2 on bad input, 3 if no slice gave a centre.
  Error grows with deformation (see benchmark). Not a replacement for looking at the result.

## vun-spacing
- **Input:** two tifxyz meshes with identical grid shape (A = reference), a CT volume, `--heights`.
- **Output:** `--out-json`, `--out-txt`, optional overlays: per height the fraction of A points whose distance to B
  is 0.5-1.5 CT pitches and both on-sheet ("clean"), split into shared / skipped / off-sheet / uncovered.
- **Limits:** needs a measurable CT sheet pitch (at least `--min-peaks` peaks); the on-sheet test is Otsu-based and can
  accept a bright gap on a badly crushed scroll.

## vun-switch
- **Input:** one tifxyz mesh, CT volume, `--heights`.
- **Output:** list of switches (row, column, direction, confidence), JSON/text/overlays.
- **Limits:** tracks one sheet along the cut line; loses it where sheets merge (a documented false-switch source on
  touching sheets). `--transpose` reports row/col of the transposed grid. See `docs/REVIEW_ROUND1.md`.

## vun-audit
- **Input:** one trace, or two (A reference, B proposed neighbour); CT volume; optional `--umbilicus` file.
- **Output:** `audit.json`, `audit.txt`, optional PNGs. Exit 0 all PASS, 1 any FAIL, 4 NOT JUDGED, 2 bad input.
- **Runs:** switch finder, a winding-number radius-jump check, spacing check (needs identical grid shapes), winding offset.
- **Limits:** false FAILs on true traces seen on the badly crushed and merged phantoms (see below).

## vun-phantom
- **Input:** `--out DIR`, `--size` and ~25 generator flags (turns, pitch, thickness, squash, warp, merge, ink, ...), seed.
- **Output:** OME-Zarr volume, true surfaces as tifxyz, centre line, winding labels, ink mask, planted bad traces
  (`--bad-switch`, `--bad-pairs`), `truth.json`. Deterministic for a given seed and flags.
- **Limits:** a smooth idealisation; no delamination, tears, ring artefacts; ink is a uniform brightening.

## vun-ink
- **Input:** tifxyz mesh, OME-Zarr CT, a checkpoint written by this repository's training code (`model/args/contract`),
  `--out-dir`; the layer count, patch size and depth aggregation come from the checkpoint.
- **Output:** `ink_prob.npy` (float16), `ink_prob.png`, `valid_mask.png`, `run.json`. Resumable (`--work-dir --resume`).
- **Limits:** a picture, not a score. Transfer of any checkpoint to another scan, energy or resolution is unvalidated;
  0 in the map means "no ink" *or* "no data" (use `valid_mask.png`); pixel pitch must equal the training pitch.
  Exits 2 with a message if no patch has enough valid pixels.

## Phantom benchmark numbers (256^3, seed 0, one phantom per row; details in `tools/phantom_scroll/BENCHMARK.md`)

| phantom | switches found / true | recall (trace x height) | false switches on true turns | centre error mean / max (vox) | umbilicus OK slices | spacing clean: true pairs | skipped | shared | off-sheet |
|---|---|---|---|---|---|---|---|---|---|
| round | 3 / 3 | 1.00 | 0 | 0.4 / 0.5 | 30 / 30 | 0.97 | 0.05 | 0.00 | 0.00 |
| mild | 3 / 3 | 1.00 | 0 | 2.3 / 4.1 | 30 / 30 | 0.97 | 0.04 | 0.00 | 0.00 |
| bad (crushed) | 3 / 3 | 0.73 | 0 | 4.7 / 8.7 | 14 / 30 | 0.96 | 0.12 | 0.00 | 0.30 |
| merged | 3 / 3 | 0.93 | 0 | 2.4 / 4.7 | 30 / 30 | 0.96 | 0.07 | 0.00 | 0.00 |

`vun-audit` on the same phantoms (centre = `vun-umbilicus` estimate; 7 true traces, 6 bad traces each):

| phantom | true traces PASS / FAIL | bad traces FAIL / PASS |
|---|---|---|
| round | 7 / 0 | 6 / 0 |
| mild | 7 / 0 | 6 / 0 |
| bad (crushed) | 7 / 0 | 6 / 0 |
| merged | 5 / 2 | 6 / 0 |

With the exact deformed axis as centre, the crushed phantom also gets 2 false FAILs on true traces (5 / 2).
The merged-phantom false FAILs are the switch finder following the neighbour where sheets touch.

`vun-ink` on phantoms (tiny 188k-parameter model trained on other phantoms; test phantom, true surface):
AUC 0.986, F0.5 0.83 at a val-chosen threshold; on a trace with a planted switch the letters vanish after the
switch (AUC 0.55, F0.5 0). These numbers come from PR #12 (`tool/ink-e2e`, `docs/ink_e2e/RESULTS.md`) and are
**not part of this branch**.

All benchmark numbers are from one seed, one pitch and one grid step on synthetic data. They show where the
tools can fail, not how often, and say nothing about any real scan.

## vun-merge
- **Input:** tifxyz patches (or folders of them, e.g. `winding_sweep` output) of one volume; `--zarr`/`--npy` volume and
  `--umbilicus` centre line (otherwise estimated) for the on-sheet and winding checks; `--pitch-vox` or measured.
- **Output** (`--out-dir`): one `component_NNN.tifxyz` per connected group of accepted overlaps, `seam_report.json` /
  `seam_report.txt` (every overlap and cut, accepted or refused, with the reason), `overlay.png`.
- **Limits:** a check that cannot be run (no volume, no centre) refuses the overlap unless `--allow-unjudged`; overlaps
  are judged on the surface, so a leak that stays within half a pitch of a good patch is not seen. Synthetic evidence only.

## vun-groundtruth
- **Input:** `testdata/pherc_paris4_groundtruth` (40 human-verified patches with CT slices and surface predictions, published centre line, absolute winding numbers; CC BY-NC 4.0). Parts B and C also need level-4 slices (`--l4-slices`, fetched from the public zarr if missing).
- **Output** (`--out`, default `results/`): `groundtruth_patches.csv/.md` (per patch and mode: verdict, reasons, pitch, jumps, switches; PASS / FAIL / NOT JUDGED counts and the false-alarm rate with a Wilson 95% interval), `centre_error_l4.csv/.md`, `winding_agreement_l4.csv/.md`; `--sweep` adds a one-flag-at-a-time threshold table.
- **Runs:** `vun-audit` (default and one-pitch mode), `vun-switch`, the CT pitch estimate of `vun-spacing`, optionally `surface_agreement`; `vun-umbilicus` on full slices; the ray-crossing step of `vun-sweep`.
- **Limits:** every patch is a correct trace, so the FAIL rate is a false-alarm rate, but 40 narrow patches of one scroll say nothing about missed errors. The published centre line is used for Part A. NOT JUDGED is not a pass: the winding checks need about 60 degrees of arc round the centre and these patches span about 8. Numbers: `docs/REALDATA_GROUNDTRUTH.md`.
## surface_agreement (`vun-surface`)
Does a tifxyz trace lie on a sheet of the organisers' machine-made surface prediction, and does that agree with our CT-peak judge?
Per point: prediction value, offset to the nearest prediction ridge, ON-PREDICTED-SHEET / OFF / NOT JUDGED; per height a 2x2 table
(ours x prediction) with the disagreeing points; overlays. See `tools/surface_agreement/README.md`.

## negatives (`vun-negatives`)
Four deliberately broken copies of each verified PHerc. Paris 4 (Scroll 1) patch, to measure the DETECTION rate of the checkers on real data (the
false-alarm rate is measured on the originals): `shift-half` (every valid point moved half a local sheet pitch along the in-plane normal),
`shift-full` (one pitch), `switch-mid` (right half of the columns moved one pitch) and `scramble` (the z values shuffled among the valid cells).
The pitch is measured on the CT slice at the patch's middle height. Fixed seed; refuses to run unless the ground-truth folder's README says
"PHerc. Paris 4". `vun-negatives testdata/pherc_paris4_groundtruth results/negatives` writes `OUT/<patch>/<kind>/` tifxyz folders and `manifest.csv`.
Scoring, the 2x2 and the threshold study: `tools/groundtruth_score/README.md`, `docs/REALDATA_2X2.md`.

## vun-densify
- **Input:** one tifxyz folder; `--spacing` target cell spacing in voxels (default 1; the grid spacing is `1/scale`, e.g. scale 0.05 = 20 voxels).
- **Output:** a new tifxyz folder: x/y/z bilinearly interpolated by an integer factor per axis, `mask.tif`, `meta.json` with `scale` multiplied by the factor and a `densify_note`.
- **Rules:** never interpolates across invalid cells (a new node is valid only if every coarse corner with weight is valid); never coarsens; the input is never touched.
- **Limits:** adds no information (a chord of a circle of radius R over a span s is off by s^2/(8R) voxels). It does not lengthen the arc a patch spans, so the winding-jump check stays NOT JUDGED on patches (`docs/PANEL_V2.md`).

## vun-panel2 (`tools/judge_panel`)
- **Input:** a (densified) tifxyz trace, `--pred-png-dir` (surface prediction PNGs), `--ct-png-dir`, `--heights`, optional `--umbilicus`, `--threshold T`.
- **Output:** PASS / FAIL / NOT JUDGED with the required vote and the three advisory votes; `--batch` writes raw votes for a ground-truth sample and its broken copies.
- **Rule:** FAIL if the surface-prediction ON-PREDICTED-SHEET fraction is below T (default 0.415, chosen on the first 40 patches + 160 copies only), or if 2 of the 3 advisory CT checks FAIL; CT checks alone cannot fail a trace.
- **Limits:** the prediction may have been used to build the verified patches (circular); half-broken traces (`switch-mid`) are caught about half the time; the CT votes added nothing on 400 cases. See `docs/PANEL_V2.md`.

## vun-umbilicus-pred (`tools/umbilicus_finder/umbilicus_from_pred.py`)
- **Input:** `--z` heights (or `--z-csv`) on the 38.4 um grid; reads the public m7 prediction zarr over HTTP, choosing the level from its multiscale metadata (level 2 of that zarr).
- **Output:** per height the estimated centre (y, x) and, with `--compare umbilicus_9p6um.json`, the error against the published line. Two estimators: `hole` (enclosed background component of the closed prediction) and `ring` (most circular innermost ring).
- **Limits:** needs network; 20 heights of one scroll; mean error 100 voxels (3.9 mm), no better than `vun-umbilicus` on average (`docs/PANEL_V2.md`).

﻿# Tools

Seven command-line tools for checking traced papyrus surfaces and for running an ink model over one, plus a
synthetic scroll ("phantom") with known truth to test them on. CPU only. Install from the repository root:

```bash
pip install -e .            # or: pip install .      (numpy scipy tifffile pillow zarr)
pip install -e ".[ink]"     # adds torch, needed only for vun-ink
```

Each `vun-*` command is a thin wrapper that calls the `main()` of the script in `tools/<name>/`; the
scripts still run directly (`python tools/<name>/<name>.py`). `vun-<tool> --help` lists every flag. Every
threshold is a flag with a documented default; the long descriptions are in each tool's own README.

Shared input conventions: a **tifxyz** mesh is a folder with `x.tif y.tif z.tif meta.json` (float32 grids,
level-0 voxel coordinates, `-1` = no data; `docs/FORMATS.md`); a CT volume is an OME-Zarr (`--zarr`,
`--zarr-level`) or a PNG slice folder (`--png-dir`).

| Command | Script | Question it answers |
|---|---|---|
| `vun-umbilicus` | `tools/umbilicus_finder` | Where is the scroll's centre line, and how sure is that? |
| `vun-spacing` | `tools/sheet_spacing_check` | Are two traces that should be adjacent turns one sheet apart? |
| `vun-switch` | `tools/sheet_switch_finder` | Does one trace jump onto a neighbouring sheet, and where? |
| `vun-audit` | `tools/trace_auditor` | One verdict (PASS / FAIL / NOT JUDGED) per trace, combining the checks |
| `vun-phantom` | `tools/phantom_scroll` | Make a synthetic scroll with exact truth to test any of the above |
| `vun-ink` | `tools/ink_infer` | Ink-probability picture of one traced segment from a trained checkpoint |
| `vun-merge` | `tools/patch_merger` | Merge overlapping tifxyz patches, but only where the overlap is provably one sheet |
| `vun-sweep` | `tools/winding_sweep` | Every layer of a z band: centre, ray crossings, one patch + audit verdict per winding |
| `vun-sweep` | `tools/winding_sweep` | Every layer of a z band: centre, ray crossings, one patch + audit verdict per winding |
| `vun-merge` | `tools/patch_merger` | Merge overlapping tifxyz patches, but only where the overlap is provably one sheet |

## vun-umbilicus
- **Input:** OME-Zarr / 3-D zarr / PNG folder; z range in level-0 voxels (`--z-start --z-stop --z-step`).
- **Output** (`--out-dir`): `umbilicus.csv` (smoothed centre per z, confidence 0-1, OK/LOW), `umbilicus_summary.json`,
  `umbilicus_villa.json` (villa `control_points` JSON, OK points only), optional overlays.
- **Limits:** every LOW point is one the method does not trust; exit 2 on bad input, 3 if no slice gave a centre.
  Error grows with deformation (see benchmark). Not a replacement for looking at the result.

## vun-spacing
- **Input:** two tifxyz meshes with identical grid shape (A = reference), a CT volume, `--heights`.
- **Output:** `--out-json`, `--out-txt`, optional overlays: per height the fraction of A points whose distance to B
  is 0.5-1.5 CT pitches and both on-sheet ("clean"), split into shared / skipped / off-sheet / uncovered.
- **Limits:** needs a measurable CT sheet pitch (at least `--min-peaks` peaks); the on-sheet test is Otsu-based and can
  accept a bright gap on a badly crushed scroll.

## vun-switch
- **Input:** one tifxyz mesh, CT volume, `--heights`.
- **Output:** list of switches (row, column, direction, confidence), JSON/text/overlays.
- **Limits:** tracks one sheet along the cut line; loses it where sheets merge (a documented false-switch source on
  touching sheets). `--transpose` reports row/col of the transposed grid. See `docs/REVIEW_ROUND1.md`.

## vun-audit
- **Input:** one trace, or two (A reference, B proposed neighbour); CT volume; optional `--umbilicus` file.
- **Output:** `audit.json`, `audit.txt`, optional PNGs. Exit 0 all PASS, 1 any FAIL, 4 NOT JUDGED, 2 bad input.
- **Runs:** switch finder, a winding-number radius-jump check, spacing check (needs identical grid shapes), winding offset.
- **Limits:** false FAILs on true traces seen on the badly crushed and merged phantoms (see below).

## vun-phantom
- **Input:** `--out DIR`, `--size` and ~25 generator flags (turns, pitch, thickness, squash, warp, merge, ink, ...), seed.
- **Output:** OME-Zarr volume, true surfaces as tifxyz, centre line, winding labels, ink mask, planted bad traces
  (`--bad-switch`, `--bad-pairs`), `truth.json`. Deterministic for a given seed and flags.
- **Limits:** a smooth idealisation; no delamination, tears, ring artefacts; ink is a uniform brightening.

## vun-ink
- **Input:** tifxyz mesh, OME-Zarr CT, a checkpoint written by this repository's training code (`model/args/contract`),
  `--out-dir`; the layer count, patch size and depth aggregation come from the checkpoint.
- **Output:** `ink_prob.npy` (float16), `ink_prob.png`, `valid_mask.png`, `run.json`. Resumable (`--work-dir --resume`).
- **Limits:** a picture, not a score. Transfer of any checkpoint to another scan, energy or resolution is unvalidated;
  0 in the map means "no ink" *or* "no data" (use `valid_mask.png`); pixel pitch must equal the training pitch.
  Exits 2 with a message if no patch has enough valid pixels.

## Phantom benchmark numbers (256^3, seed 0, one phantom per row; details in `tools/phantom_scroll/BENCHMARK.md`)

| phantom | switches found / true | recall (trace x height) | false switches on true turns | centre error mean / max (vox) | umbilicus OK slices | spacing clean: true pairs | skipped | shared | off-sheet |
|---|---|---|---|---|---|---|---|---|---|
| round | 3 / 3 | 1.00 | 0 | 0.4 / 0.5 | 30 / 30 | 0.97 | 0.05 | 0.00 | 0.00 |
| mild | 3 / 3 | 1.00 | 0 | 2.3 / 4.1 | 30 / 30 | 0.97 | 0.04 | 0.00 | 0.00 |
| bad (crushed) | 3 / 3 | 0.73 | 0 | 4.7 / 8.7 | 14 / 30 | 0.96 | 0.12 | 0.00 | 0.30 |
| merged | 3 / 3 | 0.93 | 0 | 2.4 / 4.7 | 30 / 30 | 0.96 | 0.07 | 0.00 | 0.00 |

`vun-audit` on the same phantoms (centre = `vun-umbilicus` estimate; 7 true traces, 6 bad traces each):

| phantom | true traces PASS / FAIL | bad traces FAIL / PASS |
|---|---|---|
| round | 7 / 0 | 6 / 0 |
| mild | 7 / 0 | 6 / 0 |
| bad (crushed) | 7 / 0 | 6 / 0 |
| merged | 5 / 2 | 6 / 0 |

With the exact deformed axis as centre, the crushed phantom also gets 2 false FAILs on true traces (5 / 2).
The merged-phantom false FAILs are the switch finder following the neighbour where sheets touch.

`vun-ink` on phantoms (tiny 188k-parameter model trained on other phantoms; test phantom, true surface):
AUC 0.986, F0.5 0.83 at a val-chosen threshold; on a trace with a planted switch the letters vanish after the
switch (AUC 0.55, F0.5 0). These numbers come from PR #12 (`tool/ink-e2e`, `docs/ink_e2e/RESULTS.md`) and are
**not part of this branch**.

All benchmark numbers are from one seed, one pitch and one grid step on synthetic data. They show where the
tools can fail, not how often, and say nothing about any real scan.

## vun-merge
- **Input:** tifxyz patches (or folders of them, e.g. `winding_sweep` output) of one volume; `--zarr`/`--npy` volume and
  `--umbilicus` centre line (otherwise estimated) for the on-sheet and winding checks; `--pitch-vox` or measured.
- **Output** (`--out-dir`): one `component_NNN.tifxyz` per connected group of accepted overlaps, `seam_report.json` /
  `seam_report.txt` (every overlap and cut, accepted or refused, with the reason), `overlay.png`.
- **Limits:** a check that cannot be run (no volume, no centre) refuses the overlap unless `--allow-unjudged`; overlaps
  are judged on the surface, so a leak that stays within half a pitch of a good patch is not seen. Synthetic evidence only.

## surface_agreement (`vun-surface`)
Does a tifxyz trace lie on a sheet of the organisers' machine-made surface prediction, and does that agree with our CT-peak judge?
Per point: prediction value, offset to the nearest prediction ridge, ON-PREDICTED-SHEET / OFF / NOT JUDGED; per height a 2x2 table
(ours x prediction) with the disagreeing points; overlays. See `tools/surface_agreement/README.md`.

## negatives (`vun-negatives`)
Four deliberately broken copies of each verified PHerc. Paris 4 (Scroll 1) patch, to measure the DETECTION rate of the checkers on real data (the
false-alarm rate is measured on the originals): `shift-half` (every valid point moved half a local sheet pitch along the in-plane normal),
`shift-full` (one pitch), `switch-mid` (right half of the columns moved one pitch) and `scramble` (the z values shuffled among the valid cells).
The pitch is measured on the CT slice at the patch's middle height. Fixed seed; refuses to run unless the ground-truth folder's README says
"PHerc. Paris 4". `vun-negatives testdata/pherc_paris4_groundtruth results/negatives` writes `OUT/<patch>/<kind>/` tifxyz folders and `manifest.csv`.
Scoring, the 2x2 and the threshold study: `tools/groundtruth_score/README.md`, `docs/REALDATA_2X2.md`.

ï»¿# Tools

Seven command-line tools for checking traced papyrus surfaces and for running an ink model over one, plus a
synthetic scroll ("phantom") with known truth to test them on. CPU only. Install from the repository root:

```bash
pip install -e .            # or: pip install .      (numpy scipy tifffile pillow zarr)
pip install -e ".[ink]"     # adds torch, needed only for vun-ink
```

Each `vun-*` command is a thin wrapper that calls the `main()` of the script in `tools/<name>/`; the
scripts still run directly (`python tools/<name>/<name>.py`). `vun-<tool> --help` lists every flag. Every
threshold is a flag with a documented default; the long descriptions are in each tool's own README.

Shared input conventions: a **tifxyz** mesh is a folder with `x.tif y.tif z.tif meta.json` (float32 grids,
level-0 voxel coordinates, `-1` = no data; `docs/FORMATS.md`); a CT volume is an OME-Zarr (`--zarr`,
`--zarr-level`) or a PNG slice folder (`--png-dir`).

| Command | Script | Question it answers |
|---|---|---|
| `vun-umbilicus` | `tools/umbilicus_finder` | Where is the scroll's centre line, and how sure is that? |
| `vun-spacing` | `tools/sheet_spacing_check` | Are two traces that should be adjacent turns one sheet apart? |
| `vun-switch` | `tools/sheet_switch_finder` | Does one trace jump onto a neighbouring sheet, and where? |
| `vun-audit` | `tools/trace_auditor` | One verdict (PASS / FAIL / NOT JUDGED) per trace, combining the checks |
| `vun-phantom` | `tools/phantom_scroll` | Make a synthetic scroll with exact truth to test any of the above |
| `vun-ink` | `tools/ink_infer` | Ink-probability picture of one traced segment from a trained checkpoint |
| `vun-merge` | `tools/patch_merger` | Merge overlapping tifxyz patches, but only where the overlap is provably one sheet |
| `vun-sweep` | `tools/winding_sweep` | Every layer of a z band: centre, ray crossings, one patch + audit verdict per winding |
| `vun-groundtruth` | `tools/groundtruth_score` | How often do the checkers raise a false alarm on human-verified real traces, and how far off is the centre line? |
| `vun-sweep` | `tools/winding_sweep` | Every layer of a z band: centre, ray crossings, one patch + audit verdict per winding |
| `vun-merge` | `tools/patch_merger` | Merge overlapping tifxyz patches, but only where the overlap is provably one sheet |

## vun-umbilicus
- **Input:** OME-Zarr / 3-D zarr / PNG folder; z range in level-0 voxels (`--z-start --z-stop --z-step`).
- **Output** (`--out-dir`): `umbilicus.csv` (smoothed centre per z, confidence 0-1, OK/LOW), `umbilicus_summary.json`,
  `umbilicus_villa.json` (villa `control_points` JSON, OK points only), optional overlays.
- **Limits:** every LOW point is one the method does not trust; exit 2 on bad input, 3 if no slice gave a centre.
  Error grows with deformation (see benchmark). Not a replacement for looking at the result.

## vun-spacing
- **Input:** two tifxyz meshes with identical grid shape (A = reference), a CT volume, `--heights`.
- **Output:** `--out-json`, `--out-txt`, optional overlays: per height the fraction of A points whose distance to B
  is 0.5-1.5 CT pitches and both on-sheet ("clean"), split into shared / skipped / off-sheet / uncovered.
- **Limits:** needs a measurable CT sheet pitch (at least `--min-peaks` peaks); the on-sheet test is Otsu-based and can
  accept a bright gap on a badly crushed scroll.

## vun-switch
- **Input:** one tifxyz mesh, CT volume, `--heights`.
- **Output:** list of switches (row, column, direction, confidence), JSON/text/overlays.
- **Limits:** tracks one sheet along the cut line; loses it where sheets merge (a documented false-switch source on
  touching sheets). `--transpose` reports row/col of the transposed grid. See `docs/REVIEW_ROUND1.md`.

## vun-audit
- **Input:** one trace, or two (A reference, B proposed neighbour); CT volume; optional `--umbilicus` file.
- **Output:** `audit.json`, `audit.txt`, optional PNGs. Exit 0 all PASS, 1 any FAIL, 4 NOT JUDGED, 2 bad input.
- **Runs:** switch finder, a winding-number radius-jump check, spacing check (needs identical grid shapes), winding offset.
- **Limits:** false FAILs on true traces seen on the badly crushed and merged phantoms (see below).

## vun-phantom
- **Input:** `--out DIR`, `--size` and ~25 generator flags (turns, pitch, thickness, squash, warp, merge, ink, ...), seed.
- **Output:** OME-Zarr volume, true surfaces as tifxyz, centre line, winding labels, ink mask, planted bad traces
  (`--bad-switch`, `--bad-pairs`), `truth.json`. Deterministic for a given seed and flags.
- **Limits:** a smooth idealisation; no delamination, tears, ring artefacts; ink is a uniform brightening.

## vun-ink
- **Input:** tifxyz mesh, OME-Zarr CT, a checkpoint written by this repository's training code (`model/args/contract`),
  `--out-dir`; the layer count, patch size and depth aggregation come from the checkpoint.
- **Output:** `ink_prob.npy` (float16), `ink_prob.png`, `valid_mask.png`, `run.json`. Resumable (`--work-dir --resume`).
- **Limits:** a picture, not a score. Transfer of any checkpoint to another scan, energy or resolution is unvalidated;
  0 in the map means "no ink" *or* "no data" (use `valid_mask.png`); pixel pitch must equal the training pitch.
  Exits 2 with a message if no patch has enough valid pixels.

## Phantom benchmark numbers (256^3, seed 0, one phantom per row; details in `tools/phantom_scroll/BENCHMARK.md`)

| phantom | switches found / true | recall (trace x height) | false switches on true turns | centre error mean / max (vox) | umbilicus OK slices | spacing clean: true pairs | skipped | shared | off-sheet |
|---|---|---|---|---|---|---|---|---|---|
| round | 3 / 3 | 1.00 | 0 | 0.4 / 0.5 | 30 / 30 | 0.97 | 0.05 | 0.00 | 0.00 |
| mild | 3 / 3 | 1.00 | 0 | 2.3 / 4.1 | 30 / 30 | 0.97 | 0.04 | 0.00 | 0.00 |
| bad (crushed) | 3 / 3 | 0.73 | 0 | 4.7 / 8.7 | 14 / 30 | 0.96 | 0.12 | 0.00 | 0.30 |
| merged | 3 / 3 | 0.93 | 0 | 2.4 / 4.7 | 30 / 30 | 0.96 | 0.07 | 0.00 | 0.00 |

`vun-audit` on the same phantoms (centre = `vun-umbilicus` estimate; 7 true traces, 6 bad traces each):

| phantom | true traces PASS / FAIL | bad traces FAIL / PASS |
|---|---|---|
| round | 7 / 0 | 6 / 0 |
| mild | 7 / 0 | 6 / 0 |
| bad (crushed) | 7 / 0 | 6 / 0 |
| merged | 5 / 2 | 6 / 0 |

With the exact deformed axis as centre, the crushed phantom also gets 2 false FAILs on true traces (5 / 2).
The merged-phantom false FAILs are the switch finder following the neighbour where sheets touch.

`vun-ink` on phantoms (tiny 188k-parameter model trained on other phantoms; test phantom, true surface):
AUC 0.986, F0.5 0.83 at a val-chosen threshold; on a trace with a planted switch the letters vanish after the
switch (AUC 0.55, F0.5 0). These numbers come from PR #12 (`tool/ink-e2e`, `docs/ink_e2e/RESULTS.md`) and are
**not part of this branch**.

All benchmark numbers are from one seed, one pitch and one grid step on synthetic data. They show where the
tools can fail, not how often, and say nothing about any real scan.

## vun-merge
- **Input:** tifxyz patches (or folders of them, e.g. `winding_sweep` output) of one volume; `--zarr`/`--npy` volume and
  `--umbilicus` centre line (otherwise estimated) for the on-sheet and winding checks; `--pitch-vox` or measured.
- **Output** (`--out-dir`): one `component_NNN.tifxyz` per connected group of accepted overlaps, `seam_report.json` /
  `seam_report.txt` (every overlap and cut, accepted or refused, with the reason), `overlay.png`.
- **Limits:** a check that cannot be run (no volume, no centre) refuses the overlap unless `--allow-unjudged`; overlaps
  are judged on the surface, so a leak that stays within half a pitch of a good patch is not seen. Synthetic evidence only.

## vun-groundtruth
- **Input:** `testdata/pherc_paris4_groundtruth` (40 human-verified patches with CT slices and surface predictions, published centre line, absolute winding numbers; CC BY-NC 4.0). Parts B and C also need level-4 slices (`--l4-slices`, fetched from the public zarr if missing).
- **Output** (`--out`, default `results/`): `groundtruth_patches.csv/.md` (per patch and mode: verdict, reasons, pitch, jumps, switches; PASS / FAIL / NOT JUDGED counts and the false-alarm rate with a Wilson 95% interval), `centre_error_l4.csv/.md`, `winding_agreement_l4.csv/.md`; `--sweep` adds a one-flag-at-a-time threshold table.
- **Runs:** `vun-audit` (default and one-pitch mode), `vun-switch`, the CT pitch estimate of `vun-spacing`, optionally `surface_agreement`; `vun-umbilicus` on full slices; the ray-crossing step of `vun-sweep`.
- **Limits:** every patch is a correct trace, so the FAIL rate is a false-alarm rate, but 40 narrow patches of one scroll say nothing about missed errors. The published centre line is used for Part A. NOT JUDGED is not a pass: the winding checks need about 60 degrees of arc round the centre and these patches span about 8. Numbers: `docs/REALDATA_GROUNDTRUTH.md`.
## surface_agreement (`vun-surface`)
Does a tifxyz trace lie on a sheet of the organisers' machine-made surface prediction, and does that agree with our CT-peak judge?
Per point: prediction value, offset to the nearest prediction ridge, ON-PREDICTED-SHEET / OFF / NOT JUDGED; per height a 2x2 table
(ours x prediction) with the disagreeing points; overlays. See `tools/surface_agreement/README.md`.
