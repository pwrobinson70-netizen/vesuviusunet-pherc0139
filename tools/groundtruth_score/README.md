# groundtruth_score: score the tools against verified Scroll 1 ground truth

AI-assisted (Claude Code and Claude), human-directed. Data: PHerc. Paris 4 (Scroll 1), Vesuvius Challenge open data, CC BY-NC 4.0.

```bash
pip install -e .
vun-groundtruth testdata/pherc_paris4_groundtruth --out results                       # Part A (default)
vun-groundtruth testdata/pherc_paris4_groundtruth --out results --parts B,C --l4-slices /path/to/l4_cache   # centre + windings
```

Inputs: `testdata/pherc_paris4_groundtruth` (40 human-verified patches with their own CT slices and surface predictions,
`umbilicus_9p6um.json`, `abs_winding.json`). Every patch is a correct trace, so a checker should PASS it.

## Part A: patches (`groundtruth_score.py`)
Per patch, at its three heights, on its own `slices/` as the CT (9.6 um PNGs, same grid as the mesh):

| What | How |
|---|---|
| `trace_auditor`, default mode | `--umbilicus` = the published 9.6 um centre line shifted by the window origin (a 700 x 150 px crop cannot give its own centre) |
| global-pitch mode | main's auditor has no `--global-pitch`; the closest equivalent is `--pitch-vox` = median of the default run's per-height pitch estimates (one pitch for the whole patch). `--alt-root CHECKOUT` also runs the auditor of a checkout that has `--global-pitch` (origin/tool/surface-agreement) in its default and global-pitch modes |
| `sheet_switch_finder` | standalone run with its own defaults: switches found, and those with confidence >= 0.3 (the auditor's FAIL line) |
| `sheet_spacing_check` | compares two traces; a verified patch has no neighbour, so only the CT pitch estimate (its `ct_pitches`, reported by the switch finder) is recorded. The pair verdict is not applicable |
| `surface_agreement` | `--surface-root CHECKOUT` of origin/tool/surface-agreement; per patch with `surfpred/` and `slices/`; ON rate = ON-PREDICTED-SHEET points / judged points |

Output: `results/groundtruth_patches.csv` (one row per patch and mode: verdict, FAIL and NOT JUDGED reasons, pitch per height,
number of winding jumps, switches, judged heights, surface-agreement counts) and `.md` (counts, Wilson 95% interval of FAIL/N,
reasons grouped). `--audit-args '--min-switch-confidence 0.5'` passes flags to the auditor; `--sweep 'flag=v1,v2;flag2=v'` changes one
flag at a time and writes `<stem>_threshold_sweep.csv/.md`.

Verdicts are PASS / FAIL / NOT JUDGED (a check could not be run). The false-alarm rate is FAIL/N. NOT JUDGED is not a pass.

## Part B: centre line (`centre_l4.py`, `fetch_l4_slices.py`)
`umbilicus_finder.analyse_slice` on full level-4 (38.4 um) slices; error against the published line (z, x, y divided by 4,
linear in z). Slices are fetched from the public zarr by HTTP range requests (the level is uncompressed, so one z-plane is 256 x 16 KiB).
Heights: 15 evenly spread over the z range of the published file, plus the 5 heights that carry absolute-winding annotations.

## Part C: windings (`winding_l4.py`)
`winding_sweep.ray_crossings` (the step that numbers sheet crossings outward from the centre) on the level-4 slab at each annotated
height, one ray per annotated point through that point; the crossing nearest in radius is the sweep's sheet for that point.
`--set pitch_vox=6` etc. override sweep parameters (diagnostic runs).

## Phantom check of a threshold change (`phantom_threshold_check.py`)
Runs the unchanged `tools/trace_auditor/score_on_phantoms.py` suite with `trace_auditor.Params` fields overridden:
`python tools/groundtruth_score/phantom_threshold_check.py --set min_switch_confidence=0.5`. PHANTOM numbers, not real data.

## Limits
Forty patches of one scroll, 3 heights each, narrow windows (about 8 degrees round the centre): conclusions about the winding-number checks
come from three patches at most. The published centre line is used, so centre-finding errors are not part of Part A.

## Rebuilding a ground-truth sample (`fetch_groundtruth.py`)
`python tools/groundtruth_score/fetch_groundtruth.py --offset 32 --out testdata/pherc_paris4_groundtruth_b [--verify-against DIR]` rebuilds a verified-patch
sample from the public bucket with retries and resume; a patch is only ever left on disk with all 11 files. Offset 53 = set A (seed 20261104), 32 = set B
(seed 20261105); `--verify-against` rebuilds the patches an existing sample already holds and compares meshes, meta and every PNG pixel. Needs `imagecodecs`
(some source TIFFs are LZW) and `requests`.
# groundtruth_score: how often do our checks accept a broken trace, and reject a verified one?

AI-assisted (Claude Code and Claude), human-directed. Public data only: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0.

| file | what |
|---|---|
| `make_negatives.py` (`vun-negatives`) | four deliberately broken copies of each of the 40 verified patches: `shift-half`, `shift-full`, `switch-mid`, `scramble`. Refuses to run unless the README.md in the ground-truth folder says "PHerc. Paris 4". Fixed seed; writes `manifest.csv` (pitch, signed shift in voxels per patch). |
| `score.py` | the minimal scorer: runs the panel (trace_auditor default and `--global-pitch`, sheet_switch_finder, sheet_spacing_check, surface_agreement) on the 40 originals and the 160 copies; one CSV row per case. |
| `analyse.py` | 2x2 per tool and for the panel, Wilson intervals, per-kind detection, threshold study, AUC of the surface prediction. |
| `validity.py` | do the copies sit where they were meant to (CT-peak fraction)? |

    vun-negatives testdata/pherc_paris4_groundtruth results/negatives
    python tools/groundtruth_score/score.py testdata/pherc_paris4_groundtruth results/negatives --out results/groundtruth_panel_scores.csv
    python tools/groundtruth_score/analyse.py results/groundtruth_panel_scores.csv --sweeps results/threshold_study --out-dir results

Results and the numbers behind them: `docs/REALDATA_2X2.md`. Outputs under `results/` are derived and regenerable (about 25 s for the scoring on 4 cores).
