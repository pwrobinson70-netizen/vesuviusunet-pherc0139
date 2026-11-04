| phantom | centre | true traces: PASS / FAIL / NOT JUDGED | bad traces: FAIL / PASS / NOT JUDGED | FAILs fired by (bad traces) |
|---|---|---|---|---|
| round | truth | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| mild | truth | 6 / 1 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| crushed | truth | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| merged | truth | 5 / 2 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 4, winding_jumps 3, winding_offset 2 |
| crushed-hard | truth | 0 / 7 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 6, winding_jumps 3, winding_offset 3 |
| folded | truth | 6 / 1 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| delaminated | truth | 6 / 1 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| torn | truth | 6 / 1 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| gappy | truth | 6 / 1 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |


round (truth)
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

mild (truth)
  XX  [true] turn 0 alone                               FAIL       switch_finder
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

crushed (truth)
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

merged (truth)
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

crushed-hard (truth)
  XX  [true] turn 0 alone                               FAIL       switch_finder
  XX  [true] turn 1 alone                               FAIL       switch_finder
  XX  [true] turn 2 alone                               FAIL       switch_finder
  XX  [true] turn 3 alone                               FAIL       switch_finder
  XX  [true] turn 1 vs turn 0                           FAIL       spacing,switch_finder,winding_offset
  XX  [true] turn 2 vs turn 1                           FAIL       spacing,switch_finder,winding_offset
  XX  [true] turn 3 vs turn 2                           FAIL       spacing,switch_finder,winding_offset
  ok  [bad ] switch +1 at col 29 (turn 1)               FAIL       switch_finder,winding_jumps
  ok  [bad ] switch -1 at col 53 (turn 2)               FAIL       switch_finder
  ok  [bad ] switch +1 at col 67 (turn 0)               FAIL       switch_finder,winding_jumps
  ok  [bad ] pair skipped (B vs turn 1)                 FAIL       spacing,switch_finder,winding_offset
  ok  [bad ] pair shared (B vs turn 1)                  FAIL       spacing,switch_finder,winding_offset
  ok  [bad ] pair off_sheet (B vs turn 1)               FAIL       spacing,switch_finder,winding_jumps,winding_offset

folded (truth)
  XX  [true] turn 0 alone                               FAIL       switch_finder
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

delaminated (truth)
  XX  [true] turn 0 alone                               FAIL       switch_finder
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

torn (truth)
  XX  [true] turn 0 alone                               FAIL       switch_finder
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

gappy (truth)
  XX  [true] turn 0 alone                               FAIL       switch_finder
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

