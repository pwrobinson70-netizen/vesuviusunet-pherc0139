# judge_panel

Two panels live in this folder. `panel_v2.py` (`vun-panel2`) is the one to use: on held-out verified Scroll 1 patches it is the only panel with a measured real-data 2x2 (`docs/PANEL_V2.md`). `judge_panel.py` (`vun-panel`) is the earlier all-judges report from Brief 23, kept for its side-by-side disagreement listing.

Contents: 1. `judge_panel.py` / `vun-panel` (every judge side by side; Judges, Regions and verdicts, Agreement table); 2. `panel_v2.py` / `vun-panel2` (files, Reproduce).

## 1. judge_panel.py (`vun-panel`): every judge on one trace, side by side

One command that runs every available judge on one trace (and optionally a neighbour) and writes a panel report: per region, each judge's
verdict, a panel verdict, and the disagreements listed explicitly. Needs the requirements of the tools it runs (numpy, scipy, tifffile, pillow, zarr).

```bash
python tools/judge_panel/judge_panel.py trace.tifxyz [neighbour.tifxyz] --zarr volume.zarr --umbilicus centre.json --heights 60,80,100 --out-dir out/
```

### Judges

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

### Regions and verdicts

A region is one cut-line height and `--region-cols` (default 16) grid columns. Every judge is mapped onto the same regions: the texture judge by the
cut-line points of its windows (a BREAK belongs to the region holding its centre; BLURRED majority = FAIL; >= half ON-SHEET-TEXTURED = PASS), the finder and auditor by
the column of each switch / jump, height-level judges on every region of their height.

* region **PASS** only if every judge that could judge says PASS; **FAIL** if the judges that could judge say FAIL and none says PASS; **NOT JUDGED** if none could judge,
  or if the judges are **split** (some PASS, some FAIL): the split is listed as "X says FAIL (...); Y, Z say PASS". The brief's wording was "FAIL if any says FAIL";
  a split is the one place this reading differs, because a case where judges disagree must be reported NOT JUDGED with the disagreement. Neither is a PASS. `--on-disagreement fail` gives the strict reading.
* trace: **FAIL** if any region or any whole-trace judge is FAIL; else **NOT JUDGED** if any region is split or nothing could be judged; else **PASS**.
* exit code 0 PASS, 1 FAIL, 2 bad input, 4 NOT JUDGED. Output: `panel.json`, `panel.txt`, and each judge's own output below `--out-dir`.

### Agreement table

`agreement_table.py` runs the texture judge and the auditor on every phantom preset (true trace, planted switch, trace in the gap, trace on the wrong sheet) and on the real samples
and writes the 2 x 2 table (texture judge vs auditor, NOT JUDGED on the side) plus a truth-labelled score per judge (`agreement.md`, `agreement.json`). The result is in the pull request and in `docs/texture_judge/RESULTS.md`.
Reproduce: `python tools/judge_panel/agreement_table.py --out-dir out/ --size 128 [--broken-dir DIR]`.

## 2. panel_v2.py (`vun-panel2`): the prediction-first panel

AI-assisted (Claude Code and Claude), human-directed. Public data only: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0. Results and the reading of them: `docs/PANEL_V2.md`.

| file | what |
|---|---|
| `panel_v2.py` (`vun-panel2`) | verdict = REQUIRED vote (surface-prediction ON-PREDICTED-SHEET fraction >= T) + ADVISORY CT votes (trace_auditor local-pitch, trace_auditor `--global-pitch`, sheet_switch_finder) that can fail a trace only if 2 of 3 agree. `--batch GT NEG --out raw.csv` writes the raw votes of the 40 originals + 160 broken copies. |
| `densify_tree.py` | densified copies (1 voxel cells) of a ground-truth sample and its broken copies (inputs untouched; slices and predictions are symlinked) |
| `evaluate_v2.py` | chooses T on the tune set only (Youden J of the full panel), reports the held-out 2x2, per-kind detection, misses, AUC |
| `densify_effect.py` | NOT JUDGED and CT 2x2 on coarse vs densified traces |

### Reproduce the held-out 2x2

    vun-negatives testdata/pherc_paris4_groundtruth results/negatives                     # set A copies (committed)
    vun-negatives testdata/pherc_paris4_groundtruth_b results/negatives_b                 # set B copies, same script and default seed (committed)
    python tools/judge_panel/densify_tree.py testdata/pherc_paris4_groundtruth results/negatives /tmp/dense_a
    python tools/judge_panel/densify_tree.py testdata/pherc_paris4_groundtruth_b results/negatives_b /tmp/dense_b
    vun-panel2 --batch /tmp/dense_a/gt /tmp/dense_a/neg --out results/panel_v2_raw_set_a.csv
    vun-panel2 --batch /tmp/dense_b/gt /tmp/dense_b/neg --out results/panel_v2_raw_set_b.csv
    python tools/judge_panel/evaluate_v2.py --tune results/panel_v2_raw_set_a.csv --heldout results/panel_v2_raw_set_b.csv --out-dir results

Densified traces make the CT checks count 20x more cut-line points per voxel; `vun-panel2` therefore multiplies their point-count parameters by the
densify factor it finds in the trace's `meta.json` (`--point-scale` overrides). Without that the switch finder fails 38 of 40 verified patches.
