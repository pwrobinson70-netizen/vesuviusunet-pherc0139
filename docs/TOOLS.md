# Tools

Six command-line tools for checking traced papyrus surfaces and for running an ink model over one, plus a
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
| `vun-sweep` | `tools/winding_sweep` | Every layer of a z band: centre, ray crossings, one patch + audit verdict per winding |

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
