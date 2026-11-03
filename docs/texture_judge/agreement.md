### Phantoms, all presets (true and bad traces)

36 traces. Rows: texture judge. Columns: trace_auditor.

| texture \ auditor | PASS | FAIL | NOT JUDGED |
|---|---|---|---|
| PASS | 11 | 0 | 0 |
| FAIL | 2 | 18 | 5 |
| NOT JUDGED | 0 | 0 | 0 |

Both judged: 31; agree 29, disagree 2.

Truth-labelled (good = true trace; bad = planted switch or trace in the gap; undetectable = starts on the wrong sheet):

| judge | truth | PASS | FAIL | NOT JUDGED |
|---|---|---|---|---|
| texture | good | 6 | 3 | 0 |
| texture | bad | 0 | 18 | 0 |
| texture | bad-undetectable | 5 | 4 | 0 |
| auditor | good | 7 | 0 | 2 |
| auditor | bad | 0 | 17 | 1 |
| auditor | bad-undetectable | 6 | 1 | 2 |

| source | preset / mesh | trace | truth | texture | auditor |
|---|---|---|---|---|---|
| phantom | round | true | good | PASS | PASS |
| phantom | round | switch | bad | FAIL | FAIL |
| phantom | round | gap | bad | FAIL | FAIL |
| phantom | round | wrong_sheet | bad-undetectable | PASS | PASS |
| phantom | mild | true | good | PASS | PASS |
| phantom | mild | switch | bad | FAIL | FAIL |
| phantom | mild | gap | bad | FAIL | FAIL |
| phantom | mild | wrong_sheet | bad-undetectable | PASS | PASS |
| phantom | crushed | true | good | FAIL | NOT JUDGED |
| phantom | crushed | switch | bad | FAIL | FAIL |
| phantom | crushed | gap | bad | FAIL | FAIL |
| phantom | crushed | wrong_sheet | bad-undetectable | FAIL | NOT JUDGED |
| phantom | merged | true | good | FAIL | PASS |
| phantom | merged | switch | bad | FAIL | FAIL |
| phantom | merged | gap | bad | FAIL | FAIL |
| phantom | merged | wrong_sheet | bad-undetectable | FAIL | FAIL |
| phantom | folded | true | good | PASS | PASS |
| phantom | folded | switch | bad | FAIL | FAIL |
| phantom | folded | gap | bad | FAIL | FAIL |
| phantom | folded | wrong_sheet | bad-undetectable | PASS | PASS |
| phantom | delaminated | true | good | PASS | PASS |
| phantom | delaminated | switch | bad | FAIL | FAIL |
| phantom | delaminated | gap | bad | FAIL | FAIL |
| phantom | delaminated | wrong_sheet | bad-undetectable | PASS | PASS |
| phantom | torn | true | good | PASS | PASS |
| phantom | torn | switch | bad | FAIL | FAIL |
| phantom | torn | gap | bad | FAIL | FAIL |
| phantom | torn | wrong_sheet | bad-undetectable | PASS | PASS |
| phantom | gappy | true | good | PASS | PASS |
| phantom | gappy | switch | bad | FAIL | FAIL |
| phantom | gappy | gap | bad | FAIL | FAIL |
| phantom | gappy | wrong_sheet | bad-undetectable | FAIL | PASS |
| phantom | crushed-hard | true | good | FAIL | NOT JUDGED |
| phantom | crushed-hard | switch | bad | FAIL | NOT JUDGED |
| phantom | crushed-hard | gap | bad | FAIL | FAIL |
| phantom | crushed-hard | wrong_sheet | bad-undetectable | FAIL | NOT JUDGED |

### Real samples

5 traces. Rows: texture judge. Columns: trace_auditor.

| texture \ auditor | PASS | FAIL | NOT JUDGED |
|---|---|---|---|
| PASS | 0 | 0 | 0 |
| FAIL | 0 | 2 | 3 |
| NOT JUDGED | 0 | 0 | 0 |

Both judged: 2; agree 2, disagree 0.

| source | preset / mesh | trace | truth | texture | auditor |
|---|---|---|---|---|---|
| pherc_paris4_45um | w116-117 | original | unknown | FAIL | NOT JUDGED |
| pherc_paris4_45um | w118-119 | original | unknown | FAIL | NOT JUDGED |
| pherc_paris4_7p91um | w116-117 | original | unknown | FAIL | FAIL |
| pherc_paris4_7p91um | w118-119 | original | unknown | FAIL | FAIL |
| pherc_paris4_45um | 20260623164704-w116-117-BROKEN.tifxyz | deliberately broken (col > 120 shifted 9.5 vox) | bad | FAIL | NOT JUDGED |
