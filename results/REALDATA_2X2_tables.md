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

### Part C: does the surface prediction alone separate originals from broken copies?

Score = ON-PREDICTED-SHEET fraction per trace (low = suspicious). AUC = P(an original scores higher than a broken copy), ties 1/2.

| comparison | AUC | n originals | n broken |
|---|---|---|---|
| originals vs ALL broken | 0.938 | 40 | 160 |
| originals vs shift-half | 0.997 | 40 | 40 |
| originals vs shift-full | 0.949 | 40 | 40 |
| originals vs switch-mid | 0.827 | 40 | 40 |
| originals vs scramble | 0.978 | 40 | 40 |

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

