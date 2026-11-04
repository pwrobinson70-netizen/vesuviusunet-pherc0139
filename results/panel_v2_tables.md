T chosen on the tune set: 0.415 (Youden J 0.713; plateau 0.41 .. 0.42, 2 grid points).

### TUNE set (first 40 + 160): tuned-and-reported-on-the-same-data (T = 0.415)

| system | broken: not FAIL | broken: FAIL | original: not FAIL | original: FAIL | detection (broken FAILed) [Wilson 95%] | false alarm (originals FAILed) [Wilson 95%] |
|---|---|---|---|---|---|---|
| panel_v2 (required surface vote at T + advisory 2-of-3) | 22 | 138 | 34 | 6 | 138/160 = 86.2% [80.1, 90.7] | 6/40 = 15.0% [7.1, 29.1] |
| required vote alone (surface on-sheet fraction at T) | 22 | 138 | 36 | 4 | 138/160 = 86.2% [80.1, 90.7] | 4/40 = 10.0% [4.0, 23.1] |
| advisory CT votes alone, 2 of 3 fail | 157 | 3 | 38 | 2 | 3/160 = 1.9% [0.6, 5.4] | 2/40 = 5.0% [1.4, 16.5] |
| CT panel as in brief 26 (any of 3 fails) | 144 | 16 | 29 | 11 | 16/160 = 10.0% [6.2, 15.6] | 11/40 = 27.5% [16.1, 42.8] |

Detection by breakage kind (40 copies per kind):

| system | shift-half | shift-full | switch-mid | scramble | false alarms |
|---|---|---|---|---|---|
| panel_v2 (required surface vote at T + advisory 2-of-3) | 40/40 = 100.0% [91.2, 100.0] | 36/40 = 90.0% [76.9, 96.0] | 22/40 = 55.0% [39.8, 69.3] | 40/40 = 100.0% [91.2, 100.0] | 6/40 = 15.0% [7.1, 29.1] |
| required vote alone (surface on-sheet fraction at T) | 40/40 = 100.0% [91.2, 100.0] | 36/40 = 90.0% [76.9, 96.0] | 22/40 = 55.0% [39.8, 69.3] | 40/40 = 100.0% [91.2, 100.0] | 4/40 = 10.0% [4.0, 23.1] |
| advisory CT votes alone, 2 of 3 fail | 0/40 = 0.0% [0.0, 8.8] | 0/40 = 0.0% [0.0, 8.8] | 3/40 = 7.5% [2.6, 19.9] | 0/40 = 0.0% [0.0, 8.8] | 2/40 = 5.0% [1.4, 16.5] |
| CT panel as in brief 26 (any of 3 fails) | 4/40 = 10.0% [4.0, 23.1] | 4/40 = 10.0% [4.0, 23.1] | 8/40 = 20.0% [10.5, 34.8] | 0/40 = 0.0% [0.0, 8.8] | 11/40 = 27.5% [16.1, 42.8] |

NOT JUDGED (panel_v2): original 0, shift-half 0, shift-full 0, switch-mid 0, scramble 0

AUC of the on-sheet fraction (original vs broken): all broken 0.946, shift-half 0.997, shift-full 0.959, switch-mid 0.835, scramble 0.994

### HELD-OUT set (second 40 + 160): T fixed on the tune set (T = 0.415)

| system | broken: not FAIL | broken: FAIL | original: not FAIL | original: FAIL | detection (broken FAILed) [Wilson 95%] | false alarm (originals FAILed) [Wilson 95%] |
|---|---|---|---|---|---|---|
| panel_v2 (required surface vote at T + advisory 2-of-3) | 25 | 135 | 38 | 2 | 135/160 = 84.4% [78.0, 89.2] | 2/40 = 5.0% [1.4, 16.5] |
| required vote alone (surface on-sheet fraction at T) | 25 | 135 | 38 | 2 | 135/160 = 84.4% [78.0, 89.2] | 2/40 = 5.0% [1.4, 16.5] |
| advisory CT votes alone, 2 of 3 fail | 156 | 4 | 40 | 0 | 4/160 = 2.5% [1.0, 6.3] | 0/40 = 0.0% [0.0, 8.8] |
| CT panel as in brief 26 (any of 3 fails) | 146 | 14 | 34 | 6 | 14/160 = 8.8% [5.3, 14.2] | 6/40 = 15.0% [7.1, 29.1] |

Detection by breakage kind (40 copies per kind):

| system | shift-half | shift-full | switch-mid | scramble | false alarms |
|---|---|---|---|---|---|
| panel_v2 (required surface vote at T + advisory 2-of-3) | 40/40 = 100.0% [91.2, 100.0] | 37/40 = 92.5% [80.1, 97.4] | 20/40 = 50.0% [35.2, 64.8] | 38/40 = 95.0% [83.5, 98.6] | 2/40 = 5.0% [1.4, 16.5] |
| required vote alone (surface on-sheet fraction at T) | 40/40 = 100.0% [91.2, 100.0] | 37/40 = 92.5% [80.1, 97.4] | 20/40 = 50.0% [35.2, 64.8] | 38/40 = 95.0% [83.5, 98.6] | 2/40 = 5.0% [1.4, 16.5] |
| advisory CT votes alone, 2 of 3 fail | 1/40 = 2.5% [0.4, 12.9] | 2/40 = 5.0% [1.4, 16.5] | 1/40 = 2.5% [0.4, 12.9] | 0/40 = 0.0% [0.0, 8.8] | 0/40 = 0.0% [0.0, 8.8] |
| CT panel as in brief 26 (any of 3 fails) | 5/40 = 12.5% [5.5, 26.1] | 3/40 = 7.5% [2.6, 19.9] | 6/40 = 15.0% [7.1, 29.1] | 0/40 = 0.0% [0.0, 8.8] | 6/40 = 15.0% [7.1, 29.1] |

NOT JUDGED (panel_v2): original 0, shift-half 0, shift-full 0, switch-mid 0, scramble 0

AUC of the on-sheet fraction (original vs broken): all broken 0.936, shift-half 0.973, shift-full 0.951, switch-mid 0.875, scramble 0.947

