# judge_panel: every judge on one trace, side by side

One command that runs every available judge on one trace (and optionally a neighbour) and writes a panel report: per region, each judge's
verdict, a panel verdict, and the disagreements listed explicitly. Needs the requirements of the tools it runs (numpy, scipy, tifffile, pillow, zarr).

```bash
python tools/judge_panel/judge_panel.py trace.tifxyz [neighbour.tifxyz] --zarr volume.zarr --umbilicus centre.json --heights 60,80,100 --out-dir out/
```

## Judges

| column | what | level |
|---|---|---|
| `texture_judge` | fibre texture continuity (`tools/texture_judge`), a different signal from all the others | column window |
| `sheet_switch_finder` | stand-alone run | column window |
| `auditor:switch_finder`, `auditor:winding_jumps` | sub-checks of `trace_auditor` | column window |
| `sheet_spacing_check`, `auditor:winding_offset` | only with a neighbour | whole height |
| `auditor:windcheck` | `tools/upstream/windcheck` (self-intersection + off-sheet), run through the auditor's `--windcheck` when the folder exists (`--no-windcheck` to skip; off-sheet needs a zarr volume) | whole trace |
| `auditor:pitch_confidence` | the auditor's "a PASS would mean nothing here" guard | whole trace |

The auditor's own `switch_finder` and the stand-alone finder share code; both are shown on purpose. `label_drift` is not part of the panel.
Judges run through their own command lines (so they behave exactly as run alone); `--auditor-args`, `--finder-args`, `--spacing-args`, `--texture-args` pass extra flags.

## Regions and verdicts

A region is one cut-line height and `--region-cols` (default 16) grid columns. Every judge is mapped onto the same regions: the texture judge by the
cut-line points of its windows (a BREAK belongs to the region holding its centre; BLURRED majority = FAIL; >= half ON-SHEET-TEXTURED = PASS), the finder and auditor by
the column of each switch / jump, height-level judges on every region of their height.

* region **PASS** only if every judge that could judge says PASS; **FAIL** if the judges that could judge say FAIL and none says PASS; **NOT JUDGED** if none could judge,
  or if the judges are **split** (some PASS, some FAIL): the split is listed as "X says FAIL (...); Y, Z say PASS". The brief's wording was "FAIL if any says FAIL";
  a split is the one place this reading differs, because a case where judges disagree must be reported NOT JUDGED with the disagreement. Neither is a PASS. `--on-disagreement fail` gives the strict reading.
* trace: **FAIL** if any region or any whole-trace judge is FAIL; else **NOT JUDGED** if any region is split or nothing could be judged; else **PASS**.
* exit code 0 PASS, 1 FAIL, 2 bad input, 4 NOT JUDGED. Output: `panel.json`, `panel.txt`, and each judge's own output below `--out-dir`.

## Agreement table

`agreement_table.py` runs the texture judge and the auditor on every phantom preset (true trace, planted switch, trace in the gap, trace on the wrong sheet) and on the real samples
and writes the 2 x 2 table (texture judge vs auditor, NOT JUDGED on the side) plus a truth-labelled score per judge (`agreement.md`, `agreement.json`). The result is in the pull request and in `docs/texture_judge/RESULTS.md`.
Reproduce: `python tools/judge_panel/agreement_table.py --out-dir out/ --size 128 [--broken-dir DIR]`.
