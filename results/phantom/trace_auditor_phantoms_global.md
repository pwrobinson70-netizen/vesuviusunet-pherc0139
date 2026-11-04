| phantom | centre | true traces: PASS / FAIL / NOT JUDGED | bad traces: FAIL / PASS / NOT JUDGED | FAILs fired by (bad traces) |
|---|---|---|---|---|
| round | estimated (8 OK of 8 slices) | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| mild | estimated (8 OK of 8 slices) | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| bad | estimated (4 OK of 8 slices) | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 3 |
| merged | estimated (8 OK of 8 slices) | 5 / 2 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 4, winding_jumps 3, winding_offset 2 |


round (estimated (8 OK of 8 slices))
  ok  [true] turn 0 alone                               PASS       
  ok  [true] turn 1 alone                               PASS       
  ok  [true] turn 2 alone                               PASS       
  ok  [true] turn 3 alone                               PASS       
  ok  [true] turn 1 vs turn 0                           PASS       
  ok  [true] turn 2 vs turn 1                           PASS       
  ok  [true] turn 3 vs turn 2                           PASS       
  ok  [bad ] switch +1 at col 29 (turn 1)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch -1 at col 53 (turn 2)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch +1 at col 67 (turn 0)               FAIL       switch_finder,winding_jumps
  ok  [bad ] pair skipped (B vs turn 1)                 FAIL       spacing,winding_offset
  ok  [bad ] pair shared (B vs turn 1)                  FAIL       spacing,winding_offset
  ok  [bad ] pair off_sheet (B vs turn 1)               FAIL       spacing

mild (estimated (8 OK of 8 slices))
  ok  [true] turn 0 alone                               PASS       
  ok  [true] turn 1 alone                               PASS       
  ok  [true] turn 2 alone                               PASS       
  ok  [true] turn 3 alone                               PASS       
  ok  [true] turn 1 vs turn 0                           PASS       
  ok  [true] turn 2 vs turn 1                           PASS       
  ok  [true] turn 3 vs turn 2                           PASS       
  ok  [bad ] switch +1 at col 29 (turn 1)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch -1 at col 53 (turn 2)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch +1 at col 67 (turn 0)               FAIL       switch_finder,winding_jumps
  ok  [bad ] pair skipped (B vs turn 1)                 FAIL       spacing,winding_offset
  ok  [bad ] pair shared (B vs turn 1)                  FAIL       spacing,winding_offset
  ok  [bad ] pair off_sheet (B vs turn 1)               FAIL       spacing

bad (estimated (4 OK of 8 slices))
  ok  [true] turn 0 alone                               PASS       
  ok  [true] turn 1 alone                               PASS       
  ok  [true] turn 2 alone                               PASS       
  ok  [true] turn 3 alone                               PASS       
  ok  [true] turn 1 vs turn 0                           PASS       
  ok  [true] turn 2 vs turn 1                           PASS       
  ok  [true] turn 3 vs turn 2                           PASS       
  ok  [bad ] switch +1 at col 29 (turn 1)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch -1 at col 53 (turn 2)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch +1 at col 67 (turn 0)               FAIL       switch_finder,winding_jumps
  ok  [bad ] pair skipped (B vs turn 1)                 FAIL       spacing,winding_offset
  ok  [bad ] pair shared (B vs turn 1)                  FAIL       spacing,winding_offset
  ok  [bad ] pair off_sheet (B vs turn 1)               FAIL       spacing,winding_offset

merged (estimated (8 OK of 8 slices))
  ok  [true] turn 0 alone                               PASS       
  XX  [true] turn 1 alone                               FAIL       switch_finder
  ok  [true] turn 2 alone                               PASS       
  ok  [true] turn 3 alone                               PASS       
  XX  [true] turn 1 vs turn 0                           FAIL       switch_finder
  ok  [true] turn 2 vs turn 1                           PASS       
  ok  [true] turn 3 vs turn 2                           PASS       
  ok  [bad ] switch +1 at col 29 (turn 1)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch -1 at col 53 (turn 2)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch +1 at col 67 (turn 0)               FAIL       switch_finder,winding_jumps
  ok  [bad ] pair skipped (B vs turn 1)                 FAIL       spacing,winding_offset
  ok  [bad ] pair shared (B vs turn 1)                  FAIL       spacing,switch_finder,winding_offset
  ok  [bad ] pair off_sheet (B vs turn 1)               FAIL       spacing

