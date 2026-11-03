# November write-up (DRAFT)

Status: draft for the author to edit. It describes software and a synthetic benchmark. It makes **no claim
about real scan data**, and none of the numbers below were measured on any real scroll.

## 1. What was built

Six command-line tools (installable with `pip install -e .`, see `docs/TOOLS.md`), CPU only:

| Tool | Purpose |
|---|---|
| `umbilicus_finder` | centre line of a scroll through a CT volume, with a per-slice confidence |
| `sheet_spacing_check` | are two traces that should be adjacent turns one sheet apart? |
| `sheet_switch_finder` | does one trace jump onto a neighbouring sheet? |
| `trace_auditor` | one PASS / FAIL / NOT JUDGED verdict per trace from the checks above plus a winding-number test |
| `phantom_scroll` | synthetic rolled scroll with exact ground truth and planted bad traces |
| `ink_infer` | tiled 3-D U-Net inference along a traced surface, producing an ink-probability picture |

Supporting work: a tifxyz / umbilicus format check against the VC3D and villa conventions (`docs/FORMATS.md`),
a review round with five fixed bugs (`docs/REVIEW_ROUND1.md`), checksums for the frozen earlier scripts, and
tests (several hundred, synthetic data only).

## 2. Method, per tool

- **umbilicus_finder.** For each requested slice, edge pixels vote for a centre along their local normal; a
  robust fit keeps the inliers; the per-slice estimates are smoothed along z; confidence comes from vote
  coverage and residual, and points the method does not trust are flagged LOW.
- **sheet_spacing_check.** Cuts both meshes at a height, measures the CT sheet pitch from intensity peaks along
  the local normal, and calls a point clean if the distance to the other trace is 0.5-1.5 pitches and both points
  are on bright papyrus (Otsu). Failures are labelled shared, skipped, off-sheet or uncovered.
- **sheet_switch_finder.** Tracks one sheet along the cut line by continuity (not by nearness to the mesh), takes
  the signed offset between mesh and tracked sheet in pitches, and reports a persistent step of about one pitch.
- **trace_auditor.** Runs the switch finder, a winding-number check (radius against unwrapped angle about the
  centre line; a jump of about one pitch is a switch), the spacing check and a whole-sheet winding offset between
  two traces. NOT JUDGED is reported rather than a guess when the centre line or the CT pitch is missing.
- **phantom_scroll.** Archimedean spiral sheets with Gaussian profile, texture and noise, a deformation applied to
  everything (squash, smooth warp, local squeeze that makes sheets touch), rendered by inverting the deformation;
  truth is pushed through the forward deformation. Planted switches and bad pairs have known locations.
- **ink_infer.** Resamples a tifxyz mesh to one pixel per training pitch, samples layers along the normal,
  runs the checkpoint's own architecture and depth aggregation in overlapping tiles, stitches with a window.
  It computes no accuracy by itself: it is a picture, not a score.

## 3. Benchmarks (phantoms, 256^3, seed 0)

Tool benchmark (`tools/phantom_scroll/BENCHMARK.md`):

| phantom | switches found / true | recall | false switches on true turns | umbilicus error mean / max (vox) | spacing clean, true pairs | skipped | shared | off-sheet |
|---|---|---|---|---|---|---|---|---|
| round | 3 / 3 | 1.00 | 0 | 0.4 / 0.5 | 0.97 | 0.05 | 0.00 | 0.00 |
| mild | 3 / 3 | 1.00 | 0 | 2.3 / 4.1 | 0.97 | 0.04 | 0.00 | 0.00 |
| bad (crushed) | 3 / 3 | 0.73 | 0 | 4.7 / 8.7 | 0.96 | 0.12 | 0.00 | 0.30 |
| merged | 3 / 3 | 0.93 | 0 | 2.4 / 4.7 | 0.96 | 0.07 | 0.00 | 0.00 |

Audit verdicts (`tools/trace_auditor/SCORING.md`, centre estimated from the volume):

| phantom | true traces PASS / FAIL | bad traces FAIL / PASS |
|---|---|---|
| round | 7 / 0 | 6 / 0 |
| mild | 7 / 0 | 6 / 0 |
| bad (crushed) | 7 / 0 | 6 / 0 |
| merged | 5 / 2 | 6 / 0 |

Ink end to end (PR #12, not on this branch; 192^3 phantoms, ink = +20% brightness, tiny 188k-parameter model
trained on two other phantoms): test true surface AUC 0.986, F0.5 0.83 at a threshold chosen on a validation
phantom (a predict-everything baseline scores 0.024). On a trace with a planted switch the letters disappear
after the switch (AUC 0.55, F0.5 0.00) while the part before it matches the true trace.

## 4. Honest limits

- Everything above is synthetic. The phantom is smooth; real scrolls have delamination, tears, dust, uneven sheet
  thickness and brightness, ring artefacts, none of which are modelled. Passing the benchmark does not show a tool
  works on a scan; failing it shows a tool can fail.
- One seed, one pitch, one grid step per row; no confidence intervals.
- umbilicus error is partly definitional on warped phantoms (truth is the deformed axis), so the crushed-phantom
  number is an upper bound on the tool's error.
- The auditor false-FAILs true traces on the crushed phantom (spacing varies about 2x round a turn, read as a
  step) and on the merged phantom (the switch finder follows the neighbour where sheets touch), and it passes
  nothing it cannot judge.
- The dark-gap trace on the crushed phantom is still 30% "clean" in the spacing check.
- The ink test uses a uniform brightening as "ink"; the model most likely learned brightness, not letter shapes;
  the test letters occur in the training words; the off-sheet degradation depends on a window of +-8 voxels.
- `ink_infer` writes a picture, not a score. Its transfer to any real scan, energy or resolution is unvalidated, and
  it ships no real checkpoint.
- Not measured: runtime or memory on full-size scans, GPU behaviour, zarr 2.x (tests ran on zarr 3), Windows.

## 5. Reproduce

```bash
pip install -e ".[test]"
python -m pytest -q
sha256sum -c SHA256SUMS.txt
python tools/phantom_scroll/benchmark.py --size 256 --json bench.json      # about 4 minutes
python tools/trace_auditor/score_on_phantoms.py --size 256 --centre estimated
```
