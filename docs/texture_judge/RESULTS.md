# texture_judge and judge_panel: results (3 Nov 2026)

Everything here is reproducible: `python tools/texture_judge/realdata_report.py` (real samples, numbers in `results.json`, pictures in this folder) and
`python tools/judge_panel/agreement_table.py --out-dir out --size 128 --broken-dir DIR` (`agreement.md` / `agreement.json`). Defaults were set on the phantom,
not on real data. Only the two public Scroll 1 samples (`testdata/pherc_paris4_45um`, `testdata/pherc_paris4_7p91um`) were used.

## Real data: what the texture judge sees

Each real sample holds three slice PNGs, so the judge runs in **section mode** (a straightened cross-section of the slice along the cut line, +-12 voxels),
not as a surface render. Pictures (first pictures of real papyrus texture through this pipeline; each strip is cut into 800-column chunks stacked
top to bottom, raw above, window verdicts tinted below: green ON-SHEET-TEXTURED, orange BLURRED, red BREAK, grey NOT JUDGED; the black stretches are
outside the scanned/masked volume): `45um_w116-117_z{2073,2600,3128}.png`, `7p91um_w116-117_z{2644,5729,8814}.png`, and the broken copy
`45um_w116-117_BROKEN_z*.png`.

| mesh (windows, all heights) | ON-SHEET-TEXTURED | BREAK | BLURRED | NOT JUDGED |
|---|---|---|---|---|
| 45 um w116-117 (652) | 322 | 9 | 272 | 49 |
| 45 um w118-119 (659) | 331 | 15 | 265 | 48 |
| 7.91 um w116-117 (400) | 124 | 19 | 199 | 58 |
| 7.91 um w118-119 (395) | 103 | 9 | 214 | 69 |
| 45 um w116-117, deliberately broken (659) | 316 | 16 | 271 | 56 |

Roughly 40-55% of the windows are BLURRED, many of them where the cut line leaves the scanned (black) region or runs through low-texture material. The
real samples are not judged clean by this tool: that is a statement about the current defaults and the sparse input, not about the meshes.

### The deliberate break (PR #17 finding 5): NOT caught

`tools/realdata_run/task6_break.py` moves every point with grid column > 120 radially outward by 9.5 voxels (one pitch). Grid columns 108-132, cut-line points:

| height | original | broken copy |
|---|---|---|
| 2073 | 14 ON, 6 BREAK, 5 NJ (BREAK centres at col 119.3, 122.8, 128.9) | 14 ON, 6 BREAK, 5 NJ (centres 119.3, 122.4, 129.0) |
| 2600 | 20 ON, 3 BLURRED, 2 NJ, no BREAK | 19 ON, 2 BLURRED, 4 NJ, no BREAK |
| 3128 | 12 ON, 13 BLURRED, no BREAK | 8 ON, 17 BLURRED, no BREAK |

The judge reports the same orientation breaks near col 119-129 at z = 2073 on the **unbroken** original and on the broken copy, and nothing specific at 2600 / 3128.
So the texture judge does **not** catch the break the peak-based tools missed, and its BREAKs on the originals are not evidence of anything: with a
section of this height every sheet looks alike (see Limits in `tools/texture_judge/README.md`), so a one-pitch shift changes where the band sits in the strip
but not an orientation. Whether a full surface render (a dense volume) would catch it is **not tested**: no dense real volume was available.

## Agreement with the peak-based auditor (2 x 2)

Phantoms (9 presets x {true trace, planted switch, trace in the gap, trace that starts on the wrong sheet}, 128^3, 3 heights, `trace_auditor` with `--windcheck`):

| texture \ auditor | PASS | FAIL | NOT JUDGED |
|---|---|---|---|
| PASS | 11 | 0 | 0 |
| FAIL | 2 | 18 | 5 |
| NOT JUDGED | 0 | 0 | 0 |

36 traces; both judged 31, agree 29. Against the truth label:

| judge | true trace (should PASS) | planted switch + gap (should FAIL) | wrong sheet (undetectable) |
|---|---|---|---|
| texture | 6 PASS, **3 FAIL** | 18 FAIL | 5 PASS, 4 FAIL |
| auditor | 7 PASS, 2 NOT JUDGED | 17 FAIL, 1 NOT JUDGED | 6 PASS, 1 FAIL, 2 NOT JUDGED |

The texture judge fails 3 true traces (crushed, merged, crushed-hard presets) and flags 4 wrong-sheet traces; the auditor never FAILs a true trace but gives up (NOT JUDGED) on the
crushed presets. Why the texture judge fails the crushed presets was not established (most windows there are BLURRED; a finer render, `--pixel-vox 0.5`, did not change it).

Real samples (heights as in `tools/realdata_run`; after merging `fix/v2-local-pitch` the auditor reports NOT JUDGED on the 45 um meshes: local pitch confidence too low):

| texture \ auditor | PASS | FAIL | NOT JUDGED |
|---|---|---|---|
| PASS | 0 | 0 | 0 |
| FAIL | 0 | 2 | 3 |
| NOT JUDGED | 0 | 0 | 0 |

`FAIL / FAIL` = the two 7.91 um meshes; `FAIL / NOT JUDGED` = the two 45 um meshes and the broken copy. No real trace gets a PASS from either judge.
Full per-trace rows: `agreement.md`.
