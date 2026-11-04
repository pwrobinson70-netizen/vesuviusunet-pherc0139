# November write-up (DRAFT)

**AI-assisted (Claude Code and Claude), human-directed.** Status: draft for the author to edit. Updated 4 Nov 2026 (Brief 29) to include the
real-data results now on main. Public data only: PHerc. Paris 4 (Scroll 1) and PHerc. 0139, CC BY-NC 4.0. Sections 2, 3 and 6 are still
synthetic-phantom results; section 7 is the first real-data ground truth. Every number is quoted from a file on main, and the file is named beside it.

## Summary

On 40 verified Scroll 1 patches that panel_v2 never saw, it flagged 135 of 160 deliberately broken copies (84.4 percent, Wilson 95 percent interval 78.0 to 89.2) and raised 2 false alarms on the 40 correct originals (5.0 percent, 1.4 to 16.5), with its one threshold fixed beforehand on a separate set of 40 (`docs/PANEL_V2.md`).
That verdict comes from the organisers' surface prediction; the CT-only checks add nothing to it (`docs/PANEL_V2.md`).
Used alone on these short real patches, the CT-only checks abstain: the trace auditor says NOT JUDGED on 40 of 40 verified patches under v2 defaults, because a verified patch spans about 8 degrees of arc and the winding checks need about 60 (`docs/REALDATA_GROUNDTRUTH.md`), and densifying the traces does not change that (`docs/PANEL_V2.md`).
Before v2 they did not abstain: the old pitch handling raised 7 false alarms in 40 (auditor, `docs/REALDATA_GROUNDTRUTH.md`) and the three-tool CT panel raised 9 in 40 while catching 18.1 percent of broken copies, which is no better than chance because it is below that panel's own 22.5 percent false-alarm rate (`docs/REALDATA_2X2.md`).
The panel still misses half of the copies where only half the trace is broken (20 of 40 `switch-mid`), plus 3 of 40 `shift-full` and 2 of 40 `scramble` (`docs/PANEL_V2.md`).
The breakages are synthetic edits of real traces, not real tracing errors, and everything is one scroll with 40 patches per set, so the intervals are wide.
Our own centre-line estimates (mean error about 100 voxels at 38.4 um) and winding numbers (no agreement at level 4) are not good enough to replace the published ones (section 7e, 7f).

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

## 3. Benchmarks on synthetic phantoms (256^3, seed 0)

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

Rewritten 4 Nov 2026 against the real-data results of section 7. Marked **[kept]**, **[corrected]** or **[new]**.

- **[corrected]** Sections 2, 3 and 6 are synthetic. The phantom is smooth; real scrolls have delamination, tears, dust, uneven sheet
  thickness and brightness, ring artefacts, none of which are modelled. The real data now shows what that costs: on the phantoms the
  same checks catch every broken trace (6/6, 6/6, 5/6, 6/6), on real patches the CT panel caught 18% and the auditor abstained on all
  of them (`docs/REALDATA_2X2.md`). Passing the benchmark did not show a tool works on a scan.
  (The first draft said that nothing had been measured on real data; section 7 now is.)
- **[corrected]** The first draft's "one seed, one pitch, one grid step per row; no confidence intervals" holds only for the section 3 tables.
  Section 6 gives 20 seeds with bootstrap intervals at 192^3; still one pitch per phantom family and phantom seeds that only vary texture, warp and
  wobble. Section 7 intervals are Wilson 95% on 40 patches (or 160 copies).
- **[kept]** umbilicus error is partly definitional on warped phantoms (truth is the deformed axis), so the crushed-phantom
  number is an upper bound on the tool's error.
- **[kept]** The auditor false-FAILs true traces on the crushed phantom (spacing varies about 2x round a turn, read as a
  step) and on the merged phantom (the switch finder follows the neighbour where sheets touch), and it passes
  nothing it cannot judge. Section 6 shows this is not a one-seed accident. On real patches it passes nothing either: 0 PASS in 40 (`docs/REALDATA_GROUNDTRUTH.md`).
- **[kept]** The dark-gap trace on the crushed phantom is still 30% "clean" in the spacing check.
- **[kept]** The ink test uses a uniform brightening as "ink"; the model most likely learned brightness, not letter shapes;
  the test letters occur in the training words; the off-sheet degradation depends on a window of +-8 voxels.
- **[kept]** `ink_infer` writes a picture, not a score. Its transfer to any real scan, energy or resolution is unvalidated, and
  it ships no real checkpoint. Nothing in section 7 involves ink.
- **[corrected]** "Not measured: runtime or memory on full-size scans, GPU behaviour, zarr 2.x (tests ran on zarr 3), Windows." Still not measured:
  runtime or memory on full-size scans, GPU behaviour, zarr 2.x. Windows now has a CI job and a script (`CHANGELOG.md`, `docs/WINDOWS.md`); I did not check that job's results, so no Windows claim is made here.
- **[new]** The threshold T = 0.415 rests on one tune set of 40 patches (plus their 160 copies); it was chosen by Youden's J with a plateau of 0.41 to 0.42 (`docs/PANEL_V2.md`).
- **[new]** The held-out set is also only 40 patches, so the intervals are wide: detection 78.0 to 89.2%, false alarms 1.4 to 16.5%. Held-out false alarms (2/40) against tune false alarms (6/40) are not distinguishable (`docs/PANEL_V2.md`).
- **[new]** The broken copies are synthetic breakages of real traces (shifts by one measured pitch, a shuffled z), not real tracing errors (`docs/PANEL_V2.md`).
  They are also not exactly what they claim: only 0.49 of a verified patch's points lie within 2 voxels of a CT sheet peak, and the one-pitch shift keeps 0.33, a little above the half-pitch shift's 0.30, so `shift-full` is a one-pitch displacement, not strictly a clean sheet switch (`results/groundtruth_negatives_validity.csv` as quoted in `docs/REALDATA_2X2.md`).
- **[new]** All real-data results are on one scroll (PHerc. Paris 4) at 9.6 um (the centre and winding work on its 38.4 um level 4). Nothing here says how any tool behaves on another scroll, resolution or energy (`docs/PANEL_V2.md`, `docs/REALDATA_GROUNDTRUTH.md`).
- **[new]** The surface prediction is the organisers' m7 model, so panel_v2 inherits its errors. The 2 false alarms are patches with on-sheet fractions 0.043 and 0.000, where the prediction and the human-verified trace disagree entirely and the tool cannot tell which is wrong. The prediction may also have been used when the verified patches were built (not checked), so the agreement of the originals with it could be partly circular and its AUC is not independent evidence (`docs/PANEL_V2.md`).
- **[new]** The CT-only checks do not work on short real patches: the auditor is NOT JUDGED on 40 of 40 under v2 defaults. The false-alarm rate of 0 percent there (0 to 8.8 percent) comes from abstaining, not from passing; NOT JUDGED is not a pass (`docs/REALDATA_GROUNDTRUTH.md`).
- **[new]** The winding-number checks need about 60 degrees of arc and a verified patch spans about 8; only 3 of 40 patches had any height where it was judged before v2, so conclusions about that check come from three patches at most (`docs/REALDATA_GROUNDTRUTH.md`).
- **[new]** The advisory CT votes in panel_v2 are unproven: 0 net detections. Dropping them would give the same held-out table (`docs/PANEL_V2.md`).
- **[new]** Whole-trace on-sheet fraction cannot see a half-trace break (20 of 40 `switch-mid` missed). Neither does any geometric z-monotonicity check exist for `scramble` (`docs/PANEL_V2.md`).
- **[new]** Threshold sweeps on real data are in-sample, and the surface threshold chosen in the two-fold check was not stable (`docs/REALDATA_2X2.md`).
- **[new]** The centre-line and winding results are on 20 heights and 5 annotated heights of one scroll at one level (`docs/REALDATA_GROUNDTRUTH.md`).

## 5. Reproduce

```bash
pip install -e ".[test]"
python -m pytest -q
sha256sum -c SHA256SUMS.txt
python tools/phantom_scroll/benchmark.py --size 256 --json bench.json      # about 4 minutes
python tools/trace_auditor/score_on_phantoms.py --size 256 --centre estimated
```

## 6. Many-seed benchmark with confidence intervals (added 3 Nov 2026)

Section 4 says "one seed ... no confidence intervals". `tools/benchmark_ci` reruns the same tools at their current defaults on 20 phantom seeds (0-19) at 192^3 for each deformation and reports the mean with a 95% percentile-bootstrap CI over seeds (1000 resamples). Phantom seeds only vary texture, warp and wobble of a synthetic scroll; the CI says how far a single-seed number moves with that, not how a real scroll behaves. Full tables, per-metric plots and the per-run CSV: `docs/BENCHMARK_CI.md`, `docs/benchmark_ci/`, `tools/benchmark_ci/results/runs.csv`.

Mean [95% CI]:

| metric (192^3, 20 seeds) | round | mild | crushed | merged |
|---|---|---|---|---|
| switch recall | 1.000 [1.000, 1.000] | 0.983 [0.957, 1.000] | 0.843 [0.793, 0.890] | 0.900 [0.867, 0.927] |
| false switches / 4 true turns | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.200 [0.100, 2.600] | 0.000 [0.000, 0.000] |
| centre err mean (vox) | 0.344 [0.339, 0.349] | 2.020 [1.825, 2.248] | 5.923 [5.096, 6.836] | 2.219 [2.035, 2.418] |
| clean frac, true pairs | 0.973 [0.973, 0.973] | 0.973 [0.972, 0.973] | 0.940 [0.912, 0.960] | 0.961 [0.958, 0.964] |
| clean frac, skipped | 0.051 [0.051, 0.052] | 0.041 [0.039, 0.042] | 0.207 [0.168, 0.252] | 0.082 [0.073, 0.091] |
| clean frac, off-sheet | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.396 [0.350, 0.439] | 0.010 [0.005, 0.015] |
| auditor PASS on true | 1.000 [1.000, 1.000] | 0.936 [0.907, 0.964] | 0.279 [0.150, 0.421] | 0.679 [0.636, 0.714] |
| auditor FAIL on bad | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.992 [0.975, 1.000] | 1.000 [1.000, 1.000] |
| tracer on-turn | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.972 [0.932, 0.999] | 0.978 [0.973, 0.981] |
| tracer auditor PASS | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.900 [0.817, 0.967] | 0.933 [0.867, 0.983] |

- Round and mild: the quoted numbers are stable across seeds (CI widths of a few thousandths for the spacing fractions and recall).
- Crushed is where single-seed numbers mislead: centre error 5.9 voxels [5.1, 6.8] (range 2.9 to 10.5 over seeds), false switches on true turns 1.2 [0.1, 2.6] with a worst seed of 11, true-pair clean fraction down to 0.748 in one run (below the auditor's 0.8), and the auditor passes only 28% of true traces [15%, 42%].
- The auditor's false-FAIL on true traces (crushed, merged) is therefore not a one-seed accident; its FAIL rate on the planted bad traces is 99% to 100% in every deformation.
- No CI of a mean contains the auditor's 0.8 clean-fraction threshold, but one crushed run does fall below it.
- Size matters (seeds 0-4 at 128^3 / 192^3 / 256^3, wide CIs): the off-sheet clean fraction on the merged phantom falls from 0.18 to 0.01 to 0.00 and on crushed from 0.62 to 0.34 to 0.19; the auditor's PASS rate on true crushed traces rises from 0.00 to 0.26 to 0.37. Numbers quoted at one size do not transfer.
- Not covered: the threshold sweeps (tools/calibration), real scans, anything but these four deformations.

## 7. Real-data results on verified ground truth (added 4 Nov 2026)

All numbers in this section are quoted from `docs/REALDATA_GROUNDTRUTH.md`, `docs/REALDATA_2X2.md` and `docs/PANEL_V2.md` and the CSVs under `results/`
they cite; the file is named beside each. Public data only: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0. Intervals are Wilson 95% unless stated.
FAIL is the positive call ("this trace is broken"). NOT JUDGED means the tool declined to answer; it is neither a pass nor a detection.

### 7a. The data

- **Two independent sets of 40 human-verified patches** from the organisers' public spiral dataset (40 of 22563 each, every 141st folder, then the first 40 with a window under 768 px and at least 100 valid cells; `testdata/pherc_paris4_groundtruth/README.md`, `testdata/pherc_paris4_groundtruth_b/README.md`).
  Set A (the tune set): seed 20261104. Set B (held out): seed 20261105, a different 40 patches. Every patch is a human-verified correct trace, so a checker should PASS it.
- Per patch: the mesh, CT slices at three heights (level 2 of the 2.4 um scan, 9.6 um, 8-bit) and the m7 surface-prediction window at the same heights. Windows are small: about 700 x 150 px and about 8 degrees round the centre for set A (`docs/REALDATA_GROUNDTRUTH.md`); 100 to 1087 valid points per patch, median 200 (`docs/REALDATA_2X2.md`).
- Also in each folder: the published centre line (`umbilicus_9p6um.json`) and, for set A, 59 absolute winding annotations (`abs_winding.json`). 14 stray patch folders not listed in the README were ignored (`docs/REALDATA_GROUNDTRUTH.md`).
- **Broken copies:** 4 per patch, 160 per set, made by `vun-negatives` with the same default seed 20261104 for both sets (`docs/PANEL_V2.md`): `shift-half` (points moved half a measured sheet pitch), `shift-full` (one pitch), `switch-mid` (right half of the columns moved one pitch), `scramble` (z shuffled). One patch of set B took the fallback median pitch because its own was unmeasurable (`docs/PANEL_V2.md`).

### 7b. False alarms and abstention, before and after v2 (`docs/REALDATA_GROUNDTRUTH.md`, `results/groundtruth_patches.csv`)

40 verified patches, 3 heights each, the auditor with the published centre line shifted to the window.

| `vun-audit`, 40 verified patches | PASS | FAIL | NOT JUDGED | FAIL / 40 (Wilson 95%) |
|---|---|---|---|---|
| **Before v2** (old main, one pitch per height) | 0 | 7 | 33 | 17.5% (8.7 to 31.9) |
| **After v2** (default, confidence-gated local pitch) | 0 | **0** | **40** | **0% (0 to 8.8)** |
| After, `--global-pitch` (the pre-v2 pitch handling, now a flag) | 0 | 7 | 33 | 17.5% (8.7 to 31.9) |
| Before, `--pitch-vox` (one pitch per patch) | 0 | 9 | 31 | 22.5% (12.3 to 37.5) |
| After, `--pitch-vox` | 0 | 7 | 33 | 17.5% (8.7 to 31.9) |

- **The false alarms went to zero only because the auditor now abstains, not because it now passes.** All 40 patches are NOT JUDGED with the reason "only #% of the cut line has a trusted local pitch". The same 7 patches still FAIL for the same reasons when the old pitch handling is forced with `--global-pitch`, so nothing about those traces or checks was fixed.
- **Why the CT checks abstain:** before v2, 33 of 40 were NOT JUDGED because the winding-jump check needs 12 points and 60 degrees and the runs are about 18 to 21 points and 6 to 8 degrees. Only 3 of 40 patches had any height where it was judged. Of the 7 old FAILs, 5 were `switch_finder` (confidence 0.31 to 0.49 against a 0.3 threshold) and 2 were `winding_jumps`.
- **Densifying does not change it** (`docs/PANEL_V2.md`): with the CT parameters unchanged, the CT panel fails 39/40 originals and 152/160 copies (no information); with the point-count parameters rescaled by 20 it falls back to 11/40 = 27.5% false alarms and 16/160 = 10.0% detection. The cause is the 60-degree arc requirement, which no grid spacing changes.
- **No threshold change is recommended** (`docs/REALDATA_GROUNDTRUTH.md`): `--wn-jump-pitch 3.0` rescues 2 patches but, on the phantoms, stops the winding-jump check catching any of the planted bad traces (12 catches become 0); `--min-switch-confidence 0.5` removes 5 of 7 FAILs but into NOT JUDGED, not PASS.
- **Side result** (`surface_agreement` at its old 0.8 pass line): ON rate 1314 / 1949 judged points = 67.4%; 10 of 40 patches at or above 0.8; unchanged by v2 (`docs/REALDATA_GROUNDTRUTH.md`).
- **Where the two sources need care.** `docs/REALDATA_GROUNDTRUTH.md` "before" is old main; `docs/REALDATA_2X2.md` says its own "before" run was already on code carrying the v2 pitch handling, so its 18.1% / 22.5% figures come from a panel that includes the `--global-pitch` run (the pre-v2 handling) and the switch finder, with the default auditor at NOT JUDGED on all 200 cases. Both are quoted as written. Neither file carries a time stamp finer than the day (both 4 Nov 2026, both "Re-scored after v2", Brief 28); I have not ranked them.

### 7c. The 2x2 on 160 deliberately broken copies (`docs/REALDATA_2X2.md`, `results/groundtruth_panel_scores.csv`), set A, v2 and pre-v2 handling both in the panel

| tool | detection, 160 broken [Wilson 95%] | false alarms, 40 verified [Wilson 95%] |
|---|---|---|
| trace_auditor (default, local pitch) | 0/160 = 0.0% [0.0, 2.3] | 0/40 = 0.0% [0.0, 8.8] |
| trace_auditor `--global-pitch` | 22/160 = 13.8% [9.3, 19.9] | 7/40 = 17.5% [8.7, 31.9] |
| sheet_switch_finder | 9/160 = 5.6% [3.0, 10.3] | 4/40 = 10.0% [4.0, 23.1] |
| surface_agreement at the old 0.8 pass line | 158/160 = 98.8% [95.6, 99.7] | 30/40 = 75.0% [59.8, 85.8] |
| **CT panel** (any of auditor default, auditor `--global-pitch`, switch finder) | **29/160 = 18.1% [12.9, 24.8]** | **9/40 = 22.5% [12.3, 37.5]** |
| CT panel + surface_agreement at 0.8 | 160/160 = 100.0% [97.7, 100.0] | 32/40 = 80.0% [65.2, 89.5] |

(`sheet_spacing_check` needs two meshes; run against itself it fails everything, so it is excluded, as in the source.)

Detection per breakage kind, fraction FAILED of 40 copies per kind (`docs/REALDATA_2X2.md`):

| unit | shift-half | shift-full | switch-mid | scramble | false alarms on originals |
|---|---|---|---|---|---|
| trace_auditor (default) | 0/40 | 0/40 | 0/40 | 0/40 | 0/40 |
| trace_auditor `--global-pitch` | 6/40 | 6/40 | 10/40 | 0/40 | 7/40 |
| sheet_switch_finder | 3/40 | 1/40 | 5/40 | 0/40 | 4/40 |
| surface_agreement (0.8) | 40/40 | 40/40 | 38/40 | 40/40 | 30/40 |
| **CT panel** | 9/40 | 7/40 | 13/40 | 0/40 | 9/40 |

- Caught by no CT tool: `scramble` 40/40, `shift-full` 33/40, `shift-half` 31/40, `switch-mid` 27/40 (`docs/REALDATA_2X2.md`).
- The CT panel's detection (18.1%) is not above its false-alarm rate (22.5%): it is a coin that mostly says nothing. Holding false alarms at 9/40, no setting of the two swept knobs detects more than the default (`docs/REALDATA_2X2.md`, threshold study).
- The surface prediction on its own separates originals from copies well: AUC 0.938 over all 160 copies (0.997 `shift-half`, 0.949 `shift-full`, 0.978 `scramble`, 0.827 `switch-mid`; `docs/REALDATA_2X2.md`). Its shipped 0.8 line rejects 75% of verified originals, which is why panel_v2 has its own threshold.
- On the CT panel the same tools gave 29/160 detection and 9/40 false alarms on set A, but 14/160 = 8.8% [5.3, 14.2] and 6/40 = 15.0% [7.1, 29.1] on set B (`docs/PANEL_V2.md`): the two sets differ, and intervals overlap.
- After v2 the table above did not move (`docs/REALDATA_2X2.md`, "Nothing moved").

### 7d. panel_v2: tune and held-out (`docs/PANEL_V2.md`, `results/panel_v2_2x2.csv`, `panel_v2_by_kind.csv`)

**Rule.** REQUIRED vote: the surface-prediction ON-PREDICTED-SHEET fraction over all points of the three heights is at least T (fewer than 10 judged points: no vote). ADVISORY votes: auditor (local pitch), auditor `--global-pitch`, switch finder, on the densified trace; they fail a trace only when at least 2 of 3 agree. **T = 0.415**, chosen only on set A by Youden's J on a 0.00 to 1.00 grid in steps of 0.01 (J = 0.7125, plateau 0.41 to 0.42; `results/panel_v2_threshold_study.csv`) before set B was scored.

Held-out set B, T fixed on set A:

| system | detection [Wilson 95%] | false alarms [Wilson 95%] |
|---|---|---|
| **panel_v2** | **135/160 = 84.4% [78.0, 89.2]** | **2/40 = 5.0% [1.4, 16.5]** |
| required (prediction) vote alone | 135/160 = 84.4% [78.0, 89.2] | 2/40 = 5.0% [1.4, 16.5] |
| advisory CT votes alone (2 of 3) | 4/160 = 2.5% [1.0, 6.3] | 0/40 = 0.0% [0.0, 8.8] |
| CT panel of the 2x2 above (any of 3), on set B | 14/160 = 8.8% [5.3, 14.2] | 6/40 = 15.0% [7.1, 29.1] |

Tune set A, reported on the data it was tuned on (optimistic): panel_v2 138/160 = 86.2% [80.1, 90.7], 6/40 = 15.0% [7.1, 29.1] false alarms; required vote alone 138/160 and 4/40.
AUC of the on-sheet fraction, original vs broken: held-out 0.936, tune 0.946.

Per kind, held-out (40 copies each; `docs/PANEL_V2.md`):

| system | shift-half | shift-full | switch-mid | scramble |
|---|---|---|---|---|
| panel_v2 | 40/40 = 100% [91.2, 100] | 37/40 = 92.5% [80.1, 97.4] | **20/40 = 50.0% [35.2, 64.8]** | 38/40 = 95.0% [83.5, 98.6] |
| advisory CT votes alone | 1/40 | 2/40 | 1/40 | 0/40 |

**What it still misses (25 of 160, `results/panel_v2_heldout_misses.csv`):**

| kind | missed | why (`docs/PANEL_V2.md`) |
|---|---|---|
| switch-mid | 20/40 | half the trace is unchanged, so the whole-trace fraction stays 0.44 to 0.80 (median of the misses about 0.58) against T = 0.415; a per-column or per-segment vote would see it |
| shift-full | 3/40 | fractions 0.49, 0.51, 0.62: a one-pitch shift that lands on a neighbouring predicted sheet for most points |
| scramble | 2/40 | fractions 0.49 and 0.60: patches almost flat in z, so shuffling barely moves them; no z-monotonicity check exists |
| shift-half | 0/40 | |

**The CT advisory votes added nothing:** on the 400 cases of both sets the advisory 2-of-3 rule caught 0 copies the required vote had missed and, on the tune set, added 2 false alarms (6/40 against 4/40 for the required vote alone; `docs/PANEL_V2.md`).
The 2 held-out false alarms are patches with fractions 0.043 and 0.000 (median for good patches 0.79); one of them is also a missed `shift-full`, whose copy scores 0.62, higher than the original.

### 7e. Centre line against the published umbilicus (`docs/REALDATA_GROUNDTRUTH.md`, `docs/PANEL_V2.md`)

20 heights of the 38.4 um grid (Brief 25's "level 4" CT slices; the same grid is "level 2" of the prediction zarr, `docs/PANEL_V2.md`).

| estimator | mean error | median | worst | source |
|---|---|---|---|---|
| CT finder (`vun-umbilicus`, flagged **LOW on all 20**) | 101.4 voxels = 3.89 mm | 88.8 | 262.6 voxels = 10.08 mm (z4 = 417) | `docs/REALDATA_GROUNDTRUTH.md`, `results/centre_error_l4.csv` |
| from the prediction, `hole` (`vun-umbilicus-pred`) | 100.5 voxels = 3.86 mm | 102.7 | 180.5 voxels = 6.93 mm (z4 = 4284) | `docs/PANEL_V2.md`, `results/centre_from_pred_*.csv` |
| from the prediction, `ring` | 143.8 voxels = 5.52 mm | 100.0 | 392.5 voxels = 15.07 mm | `docs/PANEL_V2.md` |

Neither estimator is good enough to replace the published line. The means are equal within noise; the worst case improves from 263 to 181 voxels, but the `hole` found is often a small gap between sheets, not the umbilicus, and it reports no confidence. The CT finder's flag was `no_pitch` (no sheet pitch could be estimated at that level), so it did say it did not trust itself; the error is real, not a coordinate mix-up (overlay check, `docs/REALDATA_GROUNDTRUTH.md`). Both sit on a crushed cross-section where a ring model does not hold. Method for `hole` vs `ring` was chosen on 5 other heights (hole 78.4 voxels mean, ring 213.2).

### 7f. Winding numbers (`docs/REALDATA_GROUNDTRUTH.md`, `results/winding_agreement_l4.csv`)

Our sweep's ray-crossing index against 59 annotated absolute windings at 5 heights, level 4 (38.4 um): 54 of the 59 points match a crossing.

| | agreement |
|---|---|
| raw | 0 / 54 |
| after removing the most common constant offset per height | 8 / 54 = 14.8%; median error 6, mean 9.35, worst 27 windings |
| diagnostic with the annotation spacing forced in (`pitch_vox = 6`, `ray_sigma = 0.5`, `ray_prominence = 0.1`; `results/winding_agreement_l4_diag_pitch6.csv`) | 12 / 57 = 21.1%, median error 2 windings |

(The diagnostic row is quoted with the denominator the source gives, 57; the main rows use 54. I have not reconciled them.)

**Why there is no agreement at level 4:** on the 48-point ray the annotators' sheets are 5.7 level-4 pixels apart; the sweep measures a local pitch of 23 px and finds 0.27 crossings per annotated winding (0.14 on the 8-point ray). At 38.4 um the sheet spacing, about 6 px, is near the resolution limit, the sweep's ray smoothing and prominence threshold merge neighbours, and its pitch estimate locks onto coarser structure. Forcing the right pitch raises crossings per winding to 0.65 to 0.71 but still leaves sheets unseen. Level 2 (67 MB per plane) and smaller steps were not tried. The file format lined up with the sweep output without conversion.

