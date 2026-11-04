**Held-out 2x2 of panel_v2 (T = 0.415 fixed on the first set, reported on the second set `testdata/pherc_paris4_groundtruth_b`): broken copies 135 FAIL / 25 not FAIL; verified originals 2 FAIL / 38 not FAIL, i.e. detection 135/160 = 84.4% [Wilson 95%: 78.0, 89.2], false alarms 2/40 = 5.0% [1.4, 16.5].**

# panel_v2: a prediction-first judge panel, short-patch CT checks, centre from the prediction

AI-assisted (Claude Code and Claude), human-directed. Brief 27, 4 Nov 2026. Public data only: PHerc. Paris 4 (Scroll 1), Vesuvius Challenge open data, CC BY-NC 4.0.
Every number comes from a CSV in `results/` (named in each section). Code: `vun_tools/densify.py` (`vun-densify`), `tools/judge_panel` (`vun-panel2`),
`tools/umbilicus_finder/umbilicus_from_pred.py` (`vun-umbilicus-pred`). Problem statement: `docs/REALDATA_GROUNDTRUTH.md`, `docs/REALDATA_2X2.md`.

## Summary
1. **The prediction is the panel.** The surface-prediction vote alone gives, on the held-out set, 84.4% detection at 5.0% false alarms. The CT checks add nothing: on the 400 cases of both sets the advisory 2-of-3 rule caught 0 copies the required vote had missed and, on the tune set, added 2 false alarms (6/40 against 4/40 for the required vote alone).
2. **Densifying does not fix the CT checks.** It makes them fire on almost everything (unscaled) or puts them back where they were (point-count parameters rescaled). The reason is not grid spacing: a verified patch spans about 8 degrees of arc and the winding-jump check needs 60.
3. **The centre from the prediction is no better than the CT centre on average** (mean 100.5 voxels against Brief 25's 101.4); the worst case improves from 263 to 181 voxels. Not good enough to substitute for the published line.
4. **Not caught on held-out data:** half of the `switch-mid` copies (20/40), 3/40 `shift-full`, 2/40 `scramble`.

## Data and rules fixed beforehand
- **Tune set:** `testdata/pherc_paris4_groundtruth` (seed 20261104): 40 originals + 160 copies (`results/negatives`, Brief 26). **Held-out set:** `testdata/pherc_paris4_groundtruth_b` (seed 20261105, a different 40 patches, present on origin): its 160 copies were built with the same `make_negatives.py` and its default seed 20261104 (`results/negatives_b`, `manifest.csv`; one patch took the fallback median pitch because its own was unmeasurable). `results/panel_v2_raw_set_b.csv` was produced only after T was fixed.
- **Verdict (`panel_v2.decide`):** REQUIRED vote = surface_agreement ON-PREDICTED-SHEET fraction over all points of the three heights >= T (fewer than 10 judged points: no vote). ADVISORY votes = trace_auditor (local pitch), trace_auditor `--global-pitch`, sheet_switch_finder, run on the densified trace; they never fail a trace alone, only when at least 2 of the 3 FAIL. NOT JUDGED and errors are no vote.
- **T:** grid 0.00 to 1.00 step 0.01 on the tune set, maximising Youden's J (detection minus false-alarm rate) of the full panel; ties: median of the plateau. Result **T = 0.415** (J = 0.7125, plateau 0.41 to 0.42; `results/panel_v2_threshold_study.csv`). The old surface check passed at 0.8; verified patches have a median ON fraction of 0.79 on set B, which is why 0.8 rejected 75% of them.

## Part B: held-out 2x2 (`results/panel_v2_2x2.csv`, `panel_v2_by_kind.csv`, `panel_v2_tables.md`)
### Held-out set (T fixed on the tune set)
| system | broken: not FAIL | broken: FAIL | original: not FAIL | original: FAIL | detection [Wilson 95%] | false alarm [Wilson 95%] |
|---|---|---|---|---|---|---|
| **panel_v2** | 25 | 135 | 38 | 2 | 135/160 = 84.4% [78.0, 89.2] | 2/40 = 5.0% [1.4, 16.5] |
| required vote alone | 25 | 135 | 38 | 2 | 135/160 = 84.4% [78.0, 89.2] | 2/40 = 5.0% [1.4, 16.5] |
| advisory CT votes alone (2 of 3) | 156 | 4 | 40 | 0 | 4/160 = 2.5% [1.0, 6.3] | 0/40 = 0.0% [0.0, 8.8] |
| CT panel of Brief 26 (any of 3) | 146 | 14 | 34 | 6 | 14/160 = 8.8% [5.3, 14.2] | 6/40 = 15.0% [7.1, 29.1] |

Detection by breakage kind, held-out (40 copies per kind):

| system | shift-half | shift-full | switch-mid | scramble |
|---|---|---|---|---|
| panel_v2 | 40/40 = 100% [91.2, 100] | 37/40 = 92.5% [80.1, 97.4] | **20/40 = 50.0% [35.2, 64.8]** | 38/40 = 95.0% [83.5, 98.6] |
| advisory CT votes alone (2 of 3) | 1/40 | 2/40 | 1/40 | 0/40 |

AUC of the on-sheet fraction, original vs broken: held-out 0.936 (shift-half 0.973, shift-full 0.951, switch-mid 0.875, scramble 0.947); tune set 0.946.

### Tune set, for reference (tuned-and-reported-on-the-same-data, optimistic)
panel_v2: 138/160 = 86.2% [80.1, 90.7] detection, 6/40 = 15.0% [7.1, 29.1] false alarms; required vote alone 138/160 and 4/40. Held-out false alarms are lower than tune false alarms by chance as much as by anything else: 40 patches, intervals overlap.

### What the panel still misses on the held-out set (`results/panel_v2_heldout_misses.csv`; 25 copies)
| kind | missed | why |
|---|---|---|
| switch-mid | 20/40 | half of each trace is unchanged, so its ON fraction stays at 0.44 to 0.80 (median of the misses about 0.58) against T = 0.415. A fraction over the whole trace cannot see a half-trace break; a per-column or per-segment vote would. |
| shift-full | 3/40 | ON fractions 0.49, 0.51, 0.62: a one-pitch shift that lands on a neighbouring predicted sheet for most points (the copies are "moved one measured pitch", not guaranteed to leave the sheet; see `docs/REALDATA_2X2.md`, validity). |
| scramble | 2/40 | ON fractions 0.49 and 0.60: patches that are almost flat in z, so shuffling z barely moves them. No geometric (z-monotonicity) check exists yet. |
| shift-half | 0/40 | |
False alarms on originals: 2 patches with ON fraction 0.043 and 0.000. One of them (0.043) is also a missed `shift-full` patch: its shifted copy scores 0.62, higher than the original, so the verified trace and the prediction disagree there and the copy moved onto the predicted sheet. With a median ON fraction of 0.79 for good patches, a patch at 0.00 means the prediction and the human-verified trace disagree entirely; either one may be wrong there, and this tool cannot tell which.

## Part A: densify (`vun-densify`)
Tests (`tests/test_densify.py`, 6): a cylinder phantom of radius 300 sampled at 20-voxel cells is densified to 1 voxel and lies within 0.5 voxel of the analytic surface (max 0.17 expected from the chord); coarse nodes are kept exactly; no value is made up across invalid cells; CLI writes `scale` x factor and a `densify_note`.

Effect on the tune set (200 cases; `results/panel_v2_densify_effect.csv`, `panel_v2_densify_scores_set_a.csv`, `panel_v2_densify_brief25_patches.csv`, `panel_v2_densify_brief26_2x2.csv`):

| variant | trace_auditor default: NOT JUDGED of 200 / FAIL on originals / FAIL on copies | trace_auditor `--global-pitch` | sheet_switch_finder FAIL orig / copies | CT panel (any of 3): false alarms / detection |
|---|---|---|---|---|
| coarse (Brief 26) | 200 / 0 / 0 | NJ 171 / 7 / 22 | 4 / 9 | 9/40 = 22.5% / 29/160 = 18.1% |
| densified, CT parameters unchanged | 160 / 10 / 30 | NJ 26 / 36 / 137 | 38 / 135 | 39/40 = 97.5% / 152/160 = 95.0% |
| densified, CT point-count parameters x20 | 198 / 1 / 1 | NJ 184 / 4 / 12 | 8 / 7 | 11/40 = 27.5% / 16/160 = 10.0% |

Brief 25 scorer on the 40 densified originals (`vun-groundtruth`, default mode): 0 PASS / 10 FAIL / 30 NOT JUDGED (coarse: 0 / 7 / 33); one-pitch mode 0 / 36 / 4 (coarse 0 / 9 / 31). `winding_jumps` is still NOT JUDGED on 29 of the 30.

**Reading.** NOT JUDGED drops only because checks that were silent now fire, on everything: with the CT parameters unchanged the panel fails 39/40 verified patches and 95% of the copies, which is no information. The switch finder's `k_points`, `max_lost_points` and the auditor's `wn_min_points` count cut-line points, and a 1-voxel grid has about 20 times as many. With those scaled by 20 (what `vun-panel2` does automatically for a trace carrying a `densify_note`) the checks fall back to the coarse numbers: detection 10% is below the 27.5% false-alarm rate. **Densifying alone does not fix the auditor, and the cause is the 60-degree arc requirement (a patch spans about 8 degrees), which no grid spacing changes. Per the brief, the auditor was not tuned further.**

## Part C: centre from the prediction (`results/centre_from_pred_*.csv`)
**The zarr's levels are not the brief's.** Read from `.zattrs`/`.zarray`: level 0 of the prediction zarr is the 9.6 um grid (18946 x 8174 x 8174; the "L2" in its name is the scan level it was computed on), so the level near 38 um is **level 2** (4737 x 2044 x 2044, 38.4 um), the same grid as Brief 25's level-4 CT slices. Level 4 of this zarr is 153.6 um. The tool picks the level from the metadata.
Estimators: `hole` (enclosed background component of the closed prediction nearest the body centroid) and `ring` (candidate centre where the first-hit radius of the innermost ring is most constant; minimising the plain mean radius is degenerate). Chosen on 5 heights that are NOT among the 20 (z4 = 600, 1500, 2400, 3100, 3800; `centre_from_pred_selection_*.csv`): hole mean error 78.4 voxels, ring 213.2, so `hole`. Evaluated on the 20 heights of `results/centre_l4_slices_sha256.csv`:

| | mean error | median | worst |
|---|---|---|---|
| **hole (chosen), prediction level 2, 38.4 um** | **100.5 voxels = 3.86 mm** | 102.7 | **180.5 voxels = 6.93 mm** (z4 = 4284) |
| ring | 143.8 voxels = 5.52 mm | 100.0 | 392.5 voxels = 15.07 mm |
| Brief 25 `vun-umbilicus` (CT, flagged LOW on all 20) | 101.4 voxels = 3.89 mm | 88.8 | 262.6 voxels = 10.08 mm |

Reading: the means are equal within noise. The worst case is better (181 against 263 voxels) but the hole found is often a small gap between sheets, not the umbilicus; the error grows toward the high-z end (z4 3731 to 4284: 123 to 181 voxels). `ring` is within 10 voxels at 4 heights and over 190 voxels at 9, so it is not robust. Neither estimator reports a confidence, so unlike `vun-umbilicus` it cannot say when it is wrong. The CT-slice and prediction-based centres are not independent evidence about the same error (both sit on a crushed cross-section where a ring model does not hold). Not tried: smoothing along z, a spiral fit, fusing the two.

## Caveats
- The organisers' prediction may have been used when the verified patches were built (not checked), so agreement of originals with it could be partly circular; its AUC is not independent evidence about correctness. T was tuned in-sample on set A; set B is an independent draw from the same scroll, so the held-out numbers say nothing about other scrolls.
- Intervals are wide (40 originals per set). The 2 vs 6 false alarms between held-out and tune sets are not distinguishable.
- Broken copies are synthetic and uniform (shift by one measured pitch, shuffled z); real tracer errors are not these.
- The advisory CT votes are reported but unproven: 0 net detections. Dropping them would give the same held-out table and fewer tune false alarms; they are kept only because the brief asked for them.
- The densified CT scores use factor-20 point scaling chosen by us (one try), not tuned on data.

## Test suite
Baseline after merging PRs 31, 32, 33 and the second data set (before any change here): **495 passed, 8 failed, 3 skipped, 16 xfailed, 2 xpassed** (358 s). The 8 failures: `tests/test_surface_agreement.py::test_real_sample_smoke` (already failing in Brief 26) and 7 `tests/test_groundtruth.py::test_verified_patch_is_not_a_false_alarm[...]` which are strict xfails that now XPASS: PR 31's local-pitch auditor returns NOT JUDGED on all 40 patches, so the 7 recorded false alarms no longer FAIL. They are not fixed, only hidden by NOT JUDGED; I left those tests as they are for the owner to decide (remove the markers or pin the new behaviour).
After (this branch): **511 passed, 8 failed (the same 8), 3 skipped, 17 xfailed, 2 xpassed** (286 s): +16 passed, +1 strict xfail, no other change.
New tests: `tests/test_densify.py` (6), `tests/test_panel_v2.py` (4 rule tests + 2 originals and 2 broken copies pinned; one strict xfail: tune-set original 1 is a false alarm because the advisory rule overrules a passing required vote), `tests/test_umbilicus_from_pred.py` (3, offline).

## Reproduce
See `tools/judge_panel/README.md`. Part C: `vun-umbilicus-pred --z-csv results/centre_l4_slices_sha256.csv --method hole --compare testdata/pherc_paris4_groundtruth/umbilicus_9p6um.json --out-csv out.csv` (network; about 1 minute on 4 cores).
