| phantom | centre | true traces: PASS / FAIL / NOT JUDGED | bad traces: FAIL / PASS / NOT JUDGED | FAILs fired by (bad traces) |
|---|---|---|---|---|
| round | truth | 7 / 0 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| mild | truth | 6 / 1 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 3, winding_jumps 3, winding_offset 2 |
| crushed | truth | 4 / 1 / 2 (of 7) | 5 / 0 / 1 (of 6) | spacing 3, switch_finder 2, winding_jumps 2, winding_offset 3 |
| merged | truth | 5 / 2 / 0 (of 7) | 6 / 0 / 0 (of 6) | spacing 3, switch_finder 4, winding_jumps 3, winding_offset 2 |
| crushed-hard | truth | 0 / 5 / 2 (of 7) | 3 / 0 / 3 (of 6) | switch_finder 2, winding_offset 3 |
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
  XX  [true] turn 0 alone                               FAIL       switch_finder
  XX  [true] turn 1 alone                               NOT JUDGED 
  ok  [true] turn 2 alone                               PASS       
  ok  [true] turn 3 alone                               PASS       
  XX  [true] turn 1 vs turn 0                           NOT JUDGED 
  ok  [true] turn 2 vs turn 1                           PASS       
  ok  [true] turn 3 vs turn 2                           PASS       
  ok  [bad ] switch +1 at col 29 (turn 1)               FAIL       switch_finder,winding_jumps
  XX  [bad ] switch -1 at col 53 (turn 2)               NOT JUDGED 
  ok  [bad ] switch +1 at col 67 (turn 0)               FAIL       switch_finder,winding_jumps
  ok  [bad ] pair skipped (B vs turn 1)                 FAIL       spacing,winding_offset
  ok  [bad ] pair shared (B vs turn 1)                  FAIL       spacing,winding_offset
  ok  [bad ] pair off_sheet (B vs turn 1)               FAIL       spacing,winding_offset

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
  XX  [true] turn 0 alone                               NOT JUDGED 
  XX  [true] turn 1 alone                               NOT JUDGED 
  XX  [true] turn 2 alone                               FAIL       switch_finder
  XX  [true] turn 3 alone                               FAIL       switch_finder
  XX  [true] turn 1 vs turn 0                           FAIL       winding_offset
  XX  [true] turn 2 vs turn 1                           FAIL       switch_finder
  XX  [true] turn 3 vs turn 2                           FAIL       switch_finder,winding_offset
  XX  [bad ] switch +1 at col 29 (turn 1)               NOT JUDGED 
  XX  [bad ] switch -1 at col 53 (turn 2)               NOT JUDGED 
  XX  [bad ] switch +1 at col 67 (turn 0)               NOT JUDGED 
  ok  [bad ] pair skipped (B vs turn 1)                 FAIL       switch_finder,winding_offset
  ok  [bad ] pair shared (B vs turn 1)                  FAIL       winding_offset
  ok  [bad ] pair off_sheet (B vs turn 1)               FAIL       switch_finder,winding_offset

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

