# Real-data 2x2: false alarms on verified patches x detection of broken ones (PHerc. Paris 4, Scroll 1)

AI-assisted (Claude Code and Claude), human-directed. Public data only: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0 (`testdata/pherc_paris4_groundtruth`).
Brief 26. Everything here is regenerable: `vun-negatives`, then `tools/groundtruth_score/score.py` and `analyse.py` (see `tools/groundtruth_score/README.md`);
per-case verdicts are in `results/groundtruth_panel_scores.csv`.

## What was measured
- **Originals (should PASS):** the 40 human-verified patches. A FAIL here is a false alarm.
- **Broken copies (should FAIL):** 4 per patch, 160 in all, made by `vun-negatives` (`results/negatives/`, manifest `results/negatives/manifest.csv` with the signed shift per patch).
  `shift-half`: every valid point moved half the local sheet pitch along the in-plane sheet normal; `shift-full`: one pitch; `switch-mid`: right half of the columns moved one pitch;
  `scramble`: z values shuffled among the valid cells. Pitch measured on the CT slice at the middle height (7.0 to 15.0 voxels, median 8.75; every patch measurable, no fallback). Sign of the shift drawn per patch from seed 20261104 (19 of 40 positive). These copy the kinds of control published by earlier ink-detection winners (off-sheet shift, scrambled depth, decoy).
- **Panel:** trace_auditor (default, local pitch), trace_auditor `--global-pitch`, sheet_switch_finder; a trace is FAIL if any of them fails it. surface_agreement (the organisers' m7 surface prediction) is reported separately and as "panel + surface". All tools at their defaults (switch confidence 0.3, surface pass fraction 0.8), centre line = the spiral dataset's umbilicus shifted to the patch window.
- **Brief 25 was not on origin** (no `origin/tool/groundtruth-score`), so the false-alarm rate was measured here with this minimal scorer on the same 40 patches; it is the "original" column below. If Brief 25's numbers differ, the difference is in the scorer, not the data.
- sheet_spacing_check needs two meshes; a single patch has no neighbour. Run against itself it flags PITCH-MISMATCH on every case (mesh pitch 0) including all 40 originals, so it carries no information and is **excluded from the panel** (shown for completeness).
- FAIL is the positive call. PASS and NOT JUDGED both count as "not detected". Intervals are Wilson 95%.

## Headline
- The CT-based panel is no better than a coin that mostly says nothing: it fails **18.1% [12.9, 24.8] of broken copies and 22.5% [12.3, 37.5] of verified originals**. Detection is not above the false-alarm rate.
- trace_auditor at its defaults returned NOT JUDGED on all 200 cases (e.g. 18 to 21 cut-line points and 6 to 8 degrees per height on the first patch, too short for the winding check; on all 200 cases its pitch-confidence check also finds under 50% of the cut line with a trusted local pitch). It detects 0/160 and falsely alarms on 0/40 because it never judges.
- **Not caught by any CT tool:** scramble 40/40 uncaught; shift-full 33/40 uncaught; shift-half 31/40; switch-mid 27/40. Every uncaught case is a gap for the next tool.
- The surface prediction fails 158/160 broken copies (98.8%) but also 30/40 originals (75%) at its default threshold.

## 2x2 tables
### 2x2 per tool and for the panel (rows: truth; FAIL = the tool calls the trace broken)

| tool | broken: not FAIL | broken: FAIL | original: not FAIL | original: FAIL | detection rate (160 broken) [Wilson 95%] | false-alarm rate (40 verified) [Wilson 95%] |
|---|---|---|---|---|---|---|
| trace_auditor (default, local pitch) | 160 | 0 | 40 | 0 | 0/160 = 0.0% [0.0, 2.3] | 0/40 = 0.0% [0.0, 8.8] |
| trace_auditor --global-pitch | 138 | 22 | 33 | 7 | 22/160 = 13.8% [9.3, 19.9] | 7/40 = 17.5% [8.7, 31.9] |
| sheet_switch_finder | 151 | 9 | 36 | 4 | 9/160 = 5.6% [3.0, 10.3] | 4/40 = 10.0% [4.0, 23.1] |
| sheet_spacing_check (self-pair; degenerate) | 0 | 160 | 0 | 40 | 160/160 = 100.0% [97.7, 100.0] | 40/40 = 100.0% [91.2, 100.0] |
| surface_agreement (m7 prediction) | 2 | 158 | 10 | 30 | 158/160 = 98.8% [95.6, 99.7] | 30/40 = 75.0% [59.8, 85.8] |
| **PANEL (any of trace_auditor default, trace_auditor --global-pitch, sheet_switch_finder)** | 131 | 29 | 31 | 9 | 29/160 = 18.1% [12.9, 24.8] | 9/40 = 22.5% [12.3, 37.5] |
| **PANEL + surface_agreement** | 0 | 160 | 8 | 32 | 160/160 = 100.0% [97.7, 100.0] | 32/40 = 80.0% [65.2, 89.5] |

NOT JUDGED counts (a NOT JUDGED verdict is neither FAIL nor PASS; it counts as not detected above):

| tool | original | shift-half | shift-full | switch-mid | scramble |
|---|---|---|---|---|---|
| trace_auditor (default, local pitch) | 40 | 40 | 40 | 40 | 40 |
| trace_auditor --global-pitch | 33 | 34 | 34 | 30 | 40 |
| sheet_switch_finder | 0 | 0 | 0 | 0 | 0 |
| sheet_spacing_check (self-pair; degenerate) | 0 | 0 | 0 | 0 | 0 |
| surface_agreement (m7 prediction) | 0 | 0 | 0 | 0 | 0 |

## Detection by kind
### Detection by kind (fraction FAILED, 40 patches per kind; Wilson 95% interval)

| unit | shift-half | shift-full | switch-mid | scramble | false alarms on originals |
|---|---|---|---|---|---|
| trace_auditor (default, local pitch) | 0/40 = 0.0% [0.0, 8.8] | 0/40 = 0.0% [0.0, 8.8] | 0/40 = 0.0% [0.0, 8.8] | 0/40 = 0.0% [0.0, 8.8] | 0/40 = 0.0% [0.0, 8.8] |
| trace_auditor --global-pitch | 6/40 = 15.0% [7.1, 29.1] | 6/40 = 15.0% [7.1, 29.1] | 10/40 = 25.0% [14.2, 40.2] | 0/40 = 0.0% [0.0, 8.8] | 7/40 = 17.5% [8.7, 31.9] |
| sheet_switch_finder | 3/40 = 7.5% [2.6, 19.9] | 1/40 = 2.5% [0.4, 12.9] | 5/40 = 12.5% [5.5, 26.1] | 0/40 = 0.0% [0.0, 8.8] | 4/40 = 10.0% [4.0, 23.1] |
| sheet_spacing_check (self-pair; degenerate) | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] |
| surface_agreement (m7 prediction) | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] | 38/40 = 95.0% [83.5, 98.6] | 40/40 = 100.0% [91.2, 100.0] | 30/40 = 75.0% [59.8, 85.8] |
| **PANEL (any of trace_auditor default, trace_auditor --global-pitch, sheet_switch_finder)** | 9/40 = 22.5% [12.3, 37.5] | 7/40 = 17.5% [8.7, 31.9] | 13/40 = 32.5% [20.1, 48.0] | 0/40 = 0.0% [0.0, 8.8] | 9/40 = 22.5% [12.3, 37.5] |
| **PANEL + surface_agreement** | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] | 40/40 = 100.0% [91.2, 100.0] | 32/40 = 80.0% [65.2, 89.5] |

### Which tool caught it (number of the 40 broken copies of each kind each tool FAILED; 'only' = no other panel tool failed it)

| kind | trace_auditor (default, local pitch) | trace_auditor --global-pitch | sheet_switch_finder | surface_agreement (m7 prediction) | caught by none of the CT tools | caught by nothing (incl. surface) |
|---|---|---|---|---|---|---|
| shift-half | 0 (0 only) | 6 (0 only) | 3 (0 only) | 40 (31 only) | 31/40 | 0/40 |
| shift-full | 0 (0 only) | 6 (0 only) | 1 (0 only) | 40 (33 only) | 33/40 | 0/40 |
| switch-mid | 0 (0 only) | 10 (0 only) | 5 (1 only) | 38 (27 only) | 27/40 | 0/40 |
| scramble | 0 (0 only) | 0 (0 only) | 0 (0 only) | 40 (40 only) | 40/40 | 0/40 |

## Threshold study (CT panel)
### Threshold study (panel = trace_auditor default + --global-pitch + sheet_switch_finder)

Before (all defaults): false alarms 9/40 = 22.5% [12.3, 37.5], detection 29/160 = 18.1% [12.9, 24.8].

| knob | value | false alarms on 40 originals | detection on 160 broken | detection shift-half / shift-full / switch-mid / scramble |
|---|---|---|---|---|
| switchconf | 0 | 40/40 | 160/160 | 40 / 40 / 40 / 40 |
| switchconf | 0.05 | 20/40 | 54/160 | 17 / 18 / 19 / 0 |
| switchconf | 0.1 | 17/40 | 47/160 | 17 / 14 / 16 / 0 |
| switchconf | 0.15 | 15/40 | 42/160 | 15 / 12 / 15 / 0 |
| switchconf | 0.2 | 12/40 | 39/160 | 14 / 11 / 14 / 0 |
| switchconf | 0.25 | 10/40 | 34/160 | 11 / 9 / 14 / 0 |
| switchconf | 0.3 | 9/40 | 29/160 | 9 / 7 / 13 / 0 |
| switchconf | 0.4 | 5/40 | 17/160 | 7 / 3 / 7 / 0 |
| switchconf | 0.5 | 2/40 | 11/160 | 4 / 3 / 4 / 0 |
| switchconf | 0.7 | 2/40 | 7/160 | 2 / 2 / 3 / 0 |
| wnjump | 0.3 | 9/40 | 29/160 | 9 / 7 / 13 / 0 |
| wnjump | 0.4 | 9/40 | 29/160 | 9 / 7 / 13 / 0 |
| wnjump | 0.5 | 9/40 | 29/160 | 9 / 7 / 13 / 0 |
| wnjump | 0.6 | 9/40 | 29/160 | 9 / 7 / 13 / 0 |
| wnjump | 0.8 | 9/40 | 28/160 | 9 / 7 / 12 / 0 |
| wnjump | 1 | 9/40 | 27/160 | 8 / 7 / 12 / 0 |

Best single setting with false alarms held at or below the default's 9/40: **switchconf = 0.3**: false alarms 9/40 = 22.5% [12.3, 37.5], detection 29/160 = 18.1% [12.9, 24.8].

Two-fold check (choose the setting on half the patches, apply it to the other half; false alarms on the choosing half held at the default's rate there):

| fold | chosen on | setting | held-out false alarms | held-out detection |
|---|---|---|---|---|
| 0 | 20 patches | switchconf = 0.3 | 4/20 = 20.0% [8.1, 41.6] | 10/80 = 12.5% [6.9, 21.5] |
| 1 | 20 patches | switchconf = 0.2 | 8/20 = 40.0% [21.9, 61.3] | 23/80 = 28.8% [20.0, 39.5] |

**Reading.** Holding the false-alarm count at the default's 9/40, no setting of either swept knob detects more than the default (switch confidence 0.3: 29/160). Lowering the switch confidence buys detection only by raising false alarms at least as fast (0.2: 12/40 false alarms for 39/160; 0.05: 20/40 for 54/160; 0: everything fails). The winding-jump threshold changes almost nothing. The "optimum" is therefore the default and the numbers before and after are identical: false alarms 9/40 = 22.5%, detection 29/160 = 18.1%. The two-fold check agrees only loosely (the half-selected settings differ), which is what a flat curve looks like. The threshold is not the problem; the checks do not see these breakages on patches this small.

### Phantom suite with that setting (PHANTOM data, not real: synthetic concentric-ring scroll, `tools/trace_auditor/score_on_phantoms.py`, seed 0, size 256)
The chosen setting equals the default, so the counts are unchanged from the default run (`results/phantom/trace_auditor_phantoms_default.md`, `..._global.md`):

| phantom | mode | true traces PASS / FAIL / NOT JUDGED | bad traces FAIL / PASS / NOT JUDGED |
|---|---|---|---|
| round | default | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) |
| mild | default | 7 / 0 / 0 | 6 / 0 / 0 |
| bad | default | 0 / 0 / 7 | 5 / 0 / 1 |
| merged | default | 5 / 2 / 0 | 6 / 0 / 0 |
| bad | `--global-pitch` | 7 / 0 / 0 | 6 / 0 / 0 |

On the phantoms the same tools catch every broken trace (6/6, 6/6, 5/6, 6/6). On the real patches they catch 18%. The phantom has a regular pitch, long cut lines and clean contrast; the real patches do not.

## Surface prediction (Part C)
### Part C: does the surface prediction alone separate originals from broken copies?

Score = ON-PREDICTED-SHEET fraction per trace (low = suspicious). AUC = P(an original scores higher than a broken copy), ties 1/2.

| comparison | AUC | n originals | n broken |
|---|---|---|---|
| originals vs ALL broken | 0.938 | 40 | 160 |
| originals vs shift-half | 0.997 | 40 | 40 |
| originals vs shift-full | 0.949 | 40 | 40 |
| originals vs switch-mid | 0.827 | 40 | 40 |
| originals vs scramble | 0.978 | 40 | 40 |

Reading: the m7 prediction on its own separates originals from broken copies well (AUC 0.938 over all 160; 0.997 for shift-half, 0.949 shift-full, 0.978 scramble, 0.827 switch-mid, the weakest because half of each trace is unchanged). That is a far better separator than anything in the CT panel. At the default pass fraction 0.8 it rejects 75% of the verified originals, so as shipped it cannot be added to the panel (panel + surface: 32/40 false alarms, 160/160 detection). The threshold matters:

### Surface threshold (offline, from the stored ON-PREDICTED-SHEET fractions)

| pass_on_fraction | surface alone: false alarms | surface alone: detection | panel + surface: false alarms | panel + surface: detection |
|---|---|---|---|---|
| 0.8 | 30/40 | 158/160 | 32/40 | 160/160 |
| 0.7 | 17/40 | 156/160 | 21/40 | 159/160 |
| 0.6 | 12/40 | 153/160 | 18/40 | 156/160 |
| 0.5 | 8/40 | 146/160 | 16/40 | 150/160 |
| 0.4 | 4/40 | 133/160 | 13/40 | 141/160 |
| 0.3 | 2/40 | 114/160 | 11/40 | 126/160 |
| 0.25 | 1/40 | 103/160 | 10/40 | 115/160 |
| 0.2 | 1/40 | 89/160 | 10/40 | 104/160 |
| 0.15 | 0/40 | 69/160 | 9/40 | 86/160 |
| 0.1 | 0/40 | 56/160 | 9/40 | 76/160 |

Best surface setting with panel + surface false alarms held at or below the CT panel's 9/40: **pass_on_fraction = 0.15**: false alarms 9/40 = 22.5% [12.3, 37.5], detection 86/160 = 53.8% [46.0, 61.3] (CT panel alone: 29/160 = 18.1% [12.9, 24.8]).

Two-fold check for the surface setting (chosen on one half of the patches, applied to the other):

| fold | setting | held-out false alarms | held-out detection |
|---|---|---|---|
| 0 | pass_on_fraction = 0.35 | 7/20 = 35.0% [18.1, 56.7] | 66/80 = 82.5% [72.7, 89.3] |
| 1 | pass_on_fraction = 0.15 | 5/20 = 25.0% [11.2, 46.9] | 40/80 = 50.0% [39.3, 60.7] |

Reading: holding false alarms at the CT panel's own 9/40, adding the surface prediction at pass_on_fraction 0.15 raises detection from 29/160 to 86/160 (53.8% [46.0, 61.3]). Tuned in-sample on the same 40 patches; the two-fold check gives 82.5% / 50.0% detection at 35% / 25% false alarms, so the setting is not stable and these numbers are optimistic. Surface-alone numbers in the table above (e.g. 0.3: 2/40 false alarms, 114/160 detection) are the better trade, since the CT panel's own false alarms are what set the floor in "panel + surface".

**Phantom check of the surface setting (PHANTOM data, `results/phantom/surface_agreement_phantom.json`, fake blurred-sheet prediction):** true trace ON fraction 1.00; half-pitch shift 0.00 (FAIL at 0.8 and at 0.15); one-pitch shift 1.00 (not caught at either: it lies on the next sheet, as intended); half-pitch switch-mid 0.42 (FAIL at 0.8, **missed at 0.15**); one-pitch switch-mid 1.00 (not caught). So lowering the threshold to 0.15 costs the phantom its partial-trace detection.

## Are the broken copies what they claim to be?
`results/groundtruth_negatives_validity.csv` (`validity.py`): mean fraction of points within 2 voxels of a CT sheet peak (label_drift's measure): original 0.49, shift-half 0.30, shift-full 0.33, switch-mid 0.39, scramble 0.31.
Only about half of the points of a verified patch sit on a CT peak by this strict measure, and a one-pitch shift keeps about two thirds of that, a little above the half-pitch shift. So `shift-full` does not land on a neighbouring CT sheet for every point: real sheets are not exactly periodic and the pitch is a patch-scale estimate. The copies are "moved by one measured pitch", which is the stated construction, but on the phantom a one-pitch shift is invisible to the surface prediction (ON 1.00) while on real data it is rejected 40/40. Treat shift-full detection numbers as detection of a one-pitch displacement, not strictly of a clean sheet switch.

## Caveats
- 40 patches, each small (100 to 1087 valid points, median 200; 3 heights). Intervals are wide; the CT-panel false-alarm interval is [12.3, 37.5]%.
- The surface prediction may have been used when the spiral dataset's patches were built (not checked), so agreement of the originals with it could be partly circular. Its AUC is not independent evidence.
- Threshold choices are in-sample.
- `tests/test_surface_agreement.py::test_real_sample_smoke` already fails on this branch before any change (point counts 156... vs 628...); it is the only failure in the suite and is not touched here.
- Shifted points can leave the patch's slice window; those points are then not judged by the CT tools.

## Gaps for the next tool
1. Scramble (z shuffled): no CT tool fires, 0/40. A trace whose z is not monotone along the row direction is trivially detectable geometrically; no check looks at it.
2. A uniform one-pitch shift (shift-full): 7/40 caught by the CT panel, indistinguishable from the false-alarm rate. Needs an independent reference of where the sheet should be (the surface prediction, or a winding-number anchor), not a local check.
3. Half-pitch shift: 9/40, same.
4. Judgement itself: trace_auditor is NOT JUDGED on 100% of patch-sized traces. A verdict path that works on 20-point cut lines is needed before it can detect anything on patches.
5. The false alarms: 9/40 verified patches are failed by the CT panel. 12 of the 29 broken copies the panel fails belong to those same 9 patches, so part of the "detection" is a patch the tool dislikes anyway, not a response to the breakage.

## Test suite
Before: 451 passed, 1 failed (`test_real_sample_smoke`, pre-existing), 3 skipped, 15 xfailed, 2 xpassed. After: 458 passed, 1 failed (same), 3 skipped, 16 xfailed, 2 xpassed (`tests/test_groundtruth_negatives.py`: 7 pass, 1 strict xfail for the uncaught scramble).
