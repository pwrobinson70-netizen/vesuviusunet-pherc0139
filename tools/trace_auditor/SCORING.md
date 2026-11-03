# trace_auditor scored on phantom_scroll phantoms (256^3, seed 0)

`python tools/trace_auditor/score_on_phantoms.py --size 256 --centre estimated|truth` (needs
`tools/phantom_scroll` from PR "Part C"). Same four phantoms as `phantom_scroll/benchmark.py`
(round, mild, bad = badly crushed, merged = sheets 1 and 2 touching), 4 turns, pitch 22 vox, 5 heights.
**True** traces (expected PASS): each true turn alone (4) and B of each true adjacent pair (3).
**Bad** traces (expected FAIL): three traces with a planted switch alone (3) and B of the pairs
(turn 1, skipped sheet / shared sheet / in the dark gap), i.e. a trace on the wrong sheet from its first point (3).

## Centre = umbilicus_finder on the volume (the realistic one-command case)
| phantom | centre | true traces: PASS / FAIL / NOT JUDGED | bad traces: FAIL / PASS / NOT JUDGED | FAILs fired by (bad traces) |
|---|---|---|---|---|
| round | estimated (8 OK of 8 slices) | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| mild | estimated (8 OK of 8 slices) | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| bad | estimated (4 OK of 8 slices) | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 3 |
| merged | estimated (8 OK of 8 slices) | 5 / 2 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 4, winding_jumps 3, winding_offset 2 |

## Centre = the exact deformed axis (isolates the checks from the centre estimate)
| phantom | centre | true traces: PASS / FAIL / NOT JUDGED | bad traces: FAIL / PASS / NOT JUDGED | FAILs fired by (bad traces) |
|---|---|---|---|---|
| round | truth | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| mild | truth | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| bad | truth | 5 / 2 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 4, winding_offset 3 |
| merged | truth | 5 / 2 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 4, winding_jumps 3, winding_offset 2 |

False FAILs on true traces (centre = truth): bad: turn 3 alone and turn 3 vs turn 2 (`winding_jumps`: the local
sheet spacing varies by ~2x round a turn there and the jump test reads a stretch as a step); merged: turn 1 alone
and turn 1 vs turn 0 (`switch_finder`: where sheets 1 and 2 touch the finder follows the neighbour = a false switch).
With the estimated centre the badly crushed phantom has only 4 of 8 slices OK, so fewer heights are judged there
and the two winding false FAILs do not appear; that is less coverage, not better accuracy.

What the new checks add: a trace on the wrong sheet from its first point (skipped / shared pair) has no switch and no
jump, the switch finder and the jump check pass it; it is failed by the spacing check and by the winding offset.
The dark-gap trace is failed by the spacing check on all four phantoms (plus the winding offset on the badly crushed one);
the winding offset alone cannot tell a gap from a sheet. Every
planted switch is failed by BOTH the switch finder and the winding-jump check (3 of 3 on every phantom).

Not shown: how often these verdicts hold on other seeds, grid steps, pitches or on any real scroll.
