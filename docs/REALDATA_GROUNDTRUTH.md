# Real-data ground truth: scoring our tools on verified Scroll 1 patches

**AI-assisted (Claude Code and Claude), human-directed.** Brief 25, 4 Nov 2026. Public data only: PHerc. Paris 4 (Scroll 1),
Vesuvius Challenge open data, CC BY-NC 4.0. Code: `tools/groundtruth_score` (`vun-groundtruth`). Every number below comes from a CSV in
`results/` (named in each table). Numbers marked **PHANTOM** are synthetic-scroll numbers, not real data.

## The three numbers

| | Result | Source |
|---|---|---|
| **1. False-alarm rate** (`vun-audit`, default mode, 40 human-verified correct patches, 3 heights each) | **7 FAIL / 40 = 17.5 %** (Wilson 95 %: 8.7 - 31.9 %). **0 PASS**, 33 NOT JUDGED | `results/groundtruth_patches.csv` (mode `default`) |
| **2. Centre error** (`vun-umbilicus` on 20 full level-4 slices vs the published centre line) | **mean 101.4 voxels (3.89 mm), worst 262.6 voxels (10.08 mm)**, median 88.8; confidence flag **LOW on all 20** | `results/centre_error_l4.csv` |
| **3. Winding agreement** (our sweep's ray-crossing index vs 59 annotated absolute windings, level 4) | **0 / 54 raw; 8 / 54 = 14.8 % after removing one constant per height**; typical error **6 windings** (mean 9.35, worst 27) | `results/winding_agreement_l4.csv` |

How to read them. (1) Every patch is a correct trace, so each FAIL is a false alarm, but **no patch is PASS**: 33 of 40 are NOT JUDGED
because the winding-jump check needs 60 degrees of arc round the centre and a verified patch spans about 8. A PASS rate of 0 / 40 is the honest
headline next to the 17.5 % false-alarm rate. (2) The tool itself says LOW on every slice; the error is real (overlay check below), not a
coordinate mix-up. (3) At level 4 the sweep finds 0.14 - 0.27 crossings per annotated winding, so it cannot be right; the format matched,
the resolution does not.

Tests: before any change 320 passed, 3 skipped, 14 xfailed, 2 xpassed (7 min 40 s). After (adding `tests/test_groundtruth.py`): 357 passed, 3 skipped, 21 xfailed, 2 xpassed (6 min 36 s), i.e. +37 passed and +7 strict xfails (one per recorded FAIL); no other test changed.

## Part A: the 40 patches

Setup. `testdata/pherc_paris4_groundtruth` (README lists 40; the folder also holds 14 stray 3-file folders that are not in the README and are
ignored). For each patch: its own `slices/` (CT level 2, 9.6 um) as the CT, heights from `meta.json`, centre line = `umbilicus_9p6um.json`
shifted by the window origin (a 700 x 150 px crop cannot give its own centre, so centre errors are **not** part of Part A).

### Verdicts (`results/groundtruth_patches.csv`, `.md`)

| mode | PASS | FAIL | NOT JUDGED | FAIL / 40 (Wilson 95 %) |
|---|---|---|---|---|
| `vun-audit` default | 0 | 7 | 33 | 17.5 % (8.7 - 31.9) |
| one pitch per patch (`--pitch-vox` = median of the default run's pitches, 12.8 voxels) | 0 | 9 | 31 | 22.5 % (12.3 - 37.5) |
| auditor of `origin/tool/surface-agreement`, default (confidence-gated local pitch) | 0 | 0 | 40 | 0 % (0 - 8.8); all NOT JUDGED: "only #% of the cut line has a trusted local pitch" |
| same auditor, `--global-pitch` | 0 | 7 | 33 | 17.5 % (8.7 - 31.9), same as main default |

Main's auditor has no `--global-pitch` flag (it exists on the surface-agreement branch), so "global-pitch mode" on main is `--pitch-vox`,
one pitch for the whole patch. Three patches that are NOT JUDGED by default become FAIL with one pitch.

### FAIL reasons, default mode (7 patches)

| check that FAILed | patches | detail |
|---|---|---|
| `switch_finder` | 5 | one switch each, confidence 0.31 - 0.49 (threshold 0.3), step 0.84 - 1.16 pitch (2 vertical inward, 2 horizontal inward, 1 vertical outward) |
| `winding_jumps` | 2 | 3 radius jumps each: -0.64, -1.02, -0.91 and -0.79, -2.63, +1.31 pitch (the only patches with arcs long enough at some height) |

### NOT JUDGED reasons, default mode (33 patches)
All 33: `winding_jumps: run of # points / # deg is too short` (needs 12 points and 60 degrees; runs are about 18 - 21 points and 6 - 8 degrees).
Only 3 of 40 patches have any height where the winding check was judged. The switch finder judged all three heights on 34 patches, two on 6.

### Other tools on the same patches
- `sheet_switch_finder` standalone (its own defaults, CSV columns `ssf_switches_*`): 38 switches over 40 patches, 5 with confidence >= 0.3, one in each of the 5 switch FAIL patches. All 38 are on correct traces.
- CT pitch (`sheet_spacing_check.ct_pitches`, columns `pitch_h1..3`): 120 estimates, median 12.6 voxels (121 um), range 9.4 - 28.5.
- `sheet_spacing_check` proper compares two traces; one verified patch has no neighbour, so its pair verdict was **not run**. Only the pitch estimate above is reported.
- `surface_agreement` (run from a checkout of `origin/tool/surface-agreement`, commit `0bf61a3`, with `surfpred/` as the prediction and `slices/` as the CT): **ON rate 1314 / 1949 judged points = 67.4 %**; per patch median 73 %, 10 of 40 patches at or above the 80 % PASS line; height verdicts PASS 38 / FAIL 62 / NOT JUDGED 20 of 120. Our CT-peak judge and the prediction agree on 965 / 1949 = 49.5 % of compared points. On correct traces the prediction judge fails 62 of 120 patch-heights, so it is no better a checker here than the auditor is. Columns `sa_*`.

### Which single threshold change helps (`results/groundtruth_patches_threshold_sweep.csv`)
One trace_auditor flag changed at a time, default mode, all 40 patches:

| change | PASS | FAIL | NOT JUDGED |
|---|---|---|---|
| (default) | 0 | 7 | 33 |
| `--min-switch-confidence` 0.4 / **0.5** / 0.6 | 0 / 0 / 0 | 4 / **2** / 2 | 36 / 38 / 38 |
| `--wn-min-span-deg` 30 / 10 / 5 / 3 | 0 / 0 / 1 / 1 | 7 / 20 / 29 / 31 | 33 / 20 / 10 / 8 |
| `--wn-jump-pitch` 1.0 / 1.5 / 2.0 / **3.0** | 0 / 1 / 1 / **2** | 7 / 6 / 6 / 5 | 33 / 33 / 33 / 33 |
| `--wn-min-points` 10 / 8 | 1 / 1 | 7 / 7 | 32 / 32 |
| `--ssf-k-points` 8 | 0 | 6 | 34 |

- **Most FAIL -> PASS: `--wn-jump-pitch 3.0`**, 2 patches (the two winding-jump FAILs). Nothing turns more than 2 into PASS.
- **Most FAIL removed: `--min-switch-confidence 0.5`**, 5 of 7 FAILs go away but into NOT JUDGED, not PASS.
- Judging the narrow patches (`--wn-min-span-deg` 3 - 10) does not help: it replaces NOT JUDGED with 20 - 31 new FAILs, so the winding-jump check is itself unreliable on short arcs.

Phantom check of both candidate changes (**PHANTOM**, 256^3, seed 0, estimated centre; `results/phantom_threshold_check.csv`; the unchanged suite is `tools/trace_auditor/score_on_phantoms.py`):

| setting | true traces PASS / FAIL (round, mild, bad, merged) | bad traces FAIL (each of 6) | bad traces caught by the switch finder | bad traces caught by winding_jumps |
|---|---|---|---|---|
| baseline | 7/0, 7/0, 7/0, 5/2 | 6, 6, 6, 6 | 3, 3, 3, 4 | 3, 3, 3, 3 |
| `min_switch_confidence` 0.5 | 7/0, 7/0, 7/0, 5/2 | 6, 6, 6, 6 | 3, **2, 2**, 4 | 3, 3, 3, 3 |
| `wn_jump_pitch` 3.0 | 7/0, 7/0, 7/0, 5/2 | 6, 6, 6, 6 | 3, 3, 3, 4 | **0, 0, 0, 0** |

The phantom verdict counts do not change under either setting, but the verdicts hide a cost: `wn_jump_pitch 3.0` stops the winding-jump check
catching any planted bad trace (12 catches become 0; the other checks still catch them), and `min_switch_confidence 0.5` makes the switch
finder miss one planted switch on each of the mild and bad phantoms. **No threshold change is recommended from this evidence**: the two patches
that `wn-jump-pitch 3.0` rescues are two patches, and the structural problem is the 60-degree arc requirement, which no threshold fixes
without making the check fire on noise.

## Part B: centre line (`results/centre_error_l4.csv`, `.md`)
Method. Full level-4 slices (38.4 um, 2044 x 2044) read from group 4 of the public zarr by HTTP range requests (the level is uncompressed, so one z-plane
is 256 x 16 KiB). 20 heights: 15 evenly spread over the z range of the published file (level-4 z 417 - 4284) plus the 5 heights that carry winding annotations.
`umbilicus_finder.analyse_slice` with default parameters, raw per-slice centre (no smoothing: 20 slices over 3 800 slices of range). Published line =
`umbilicus_9p6um.json` divided by 4 in x, y, z, linear in z.

| | voxels (level 4) | micrometres |
|---|---|---|
| mean error | 101.4 | 3 890 |
| median | 88.8 | 3 410 |
| worst (z4 = 417) | 262.6 | 10 080 |
| best (z4 = 2074) | 18.5 | 712 |

Flag: **LOW on all 20** (reason `no_pitch`: no sheet pitch could be estimated from the level-4 slice, so confidence is 0 and the tool says it does not
trust itself). The finder is least wrong around z4 2074 - 2115 (18 - 24 voxels) and worst at the low-z end (z4 417: 263 voxels); see the CSV for every height. A two-slice overlay of the
published and estimated centres showed both inside the scroll and the published one in the visually plausible place, so the error is the tool's, not
a coordinate error: the cross-section at level 4 is far from concentric rings (folded, crushed), which the structure-tensor voting assumes.
Not run: smoothing, other `--target-px`, finer levels.

The 20 slices total 17.8 MB (8-bit PNG, lossless-recompressed), over the 15 MB limit, so they are **not in the PR**. Refetch:

```bash
python tools/groundtruth_score/fetch_l4_slices.py --out SLICES --z $(python - <<'EOF'
import csv; print(",".join(r["z_level4"] for r in csv.DictReader(open("results/centre_l4_slices_sha256.csv"))))
EOF
)
vun-groundtruth testdata/pherc_paris4_groundtruth --parts B,C --l4-slices SLICES    # missing slices are fetched automatically
```
`results/centre_l4_slices_sha256.csv` gives the PNG-byte hash and a hash of the decoded pixels of each slice; compare the pixel hash after refetching
(PNG bytes can differ between library versions). Part C also reads 4 neighbouring slices (z4 +/- 2) around each annotated height, fetched the same way and not hashed.

## Part C: winding numbers (`results/winding_agreement_l4.csv`, `.md`)
**`abs_winding.json` structure.** A VC3D point-collection file, `vc_pointcollections_json_version: 1`, `collections` keyed by id "1" - "6"; each collection has
`name`, `color`, `metadata.winding_is_absolute: true`, optional `autoFillMode/autoFillConstant`, and `points` keyed by point id, each point
`{p: [x, y, z], wind_a: <absolute winding number>, creation_time}` in 9.6 um voxels (x, y in the slice plane, z the slice). Contents: 59 points. `correction1`: 48 points at z = 15694,
windings 16 - 63, along one near-horizontal line (x 4135 -> 3025, y about 4861 - 4970; about 13 degrees of angle round the centre). `col4`: 8 points at z = 8459, windings 35 - 42.
`col1`, `col2`, `col5`: one point each (z 15976, 14268, 10673; windings 10, 33, 37). `col3`: empty. That makes **5 annotated heights**, which are the 5 sweep heights used.

Method. At each annotated height, from the published centre, one ray per annotated point through that point; `winding_sweep.ray_crossings` on the level-4 slab (5 slices, defaults)
numbers the crossings outward from 0; the crossing nearest in radius to the point (within 0.5 of its local pitch) is the sweep's sheet for that point. 54 of 59 points match a crossing.
`winding_sweep` numbers from the innermost crossing it sees, so it equals the absolute number only up to a constant per ray: (a) raw agreement is 0 / 54, (b) the implied constants
(absolute - sweep) range 9 - 47, and (c) after removing the most common constant per height 8 / 54 = 14.8 % agree, median error 6, mean 9.35, worst 27 windings. Single-point heights agree with
themselves trivially, so (c) is carried by the 48- and 8-point rays.

| z level-4 | points | matched | most common offset | points at it | median / max error after removing it |
|---|---|---|---|---|---|
| 2115 | 8 | 7 | +28 | 2 | 2.0 / 4 |
| 2668 | 1 | 1 | +33 | 1 | 0 / 0 |
| 3567 | 1 | 1 | +29 | 1 | 0 / 0 |
| 3924 | 48 | 44 | +20 | 3 | 9.5 / 27 |
| 3994 | 1 | 1 | +9 | 1 | 0 / 0 |

Why. On the 48-point ray the annotators' sheets are 5.7 level-4 pixels apart (one winding per 5.7 px radially); the sweep measures a local pitch of 23 px and finds 0.27 crossings per
annotated winding (0.14 on the 8-point ray: 7.8 px per winding, pitch 21 px). At 38.4 um the sheet spacing (about 6 px) is near the resolution limit, the sweep's ray smoothing and
prominence threshold merge neighbours, and its pitch estimate locks onto coarser structure. Diagnostic (not a fix, uses the annotation spacing): forcing `pitch_vox = 6`,
`ray_sigma = 0.5`, `ray_prominence = 0.1` raises the crossings per winding to 0.65 - 0.71 and agreement to 12 / 57 = 21.1 %, median error 2 windings
(`results/winding_agreement_l4_diag_pitch6.csv`). Still wrong: some sheets are not seen at level 4. Not tried: level 2 (a full 8174 x 8174 slice is 67 MB per plane), a smaller step, more angles.

The file format lined up with the sweep output without conversion, so the stop-and-document clause of the brief was not triggered.

## What this does and does not show
- 40 correct traces from one scroll can measure false alarms, never missed errors (no bad traces were scored). A FAIL on a correct trace is a false alarm; a NOT JUDGED is neither.
- Patches are narrow (about 700 x 150 px, about 8 degrees round the centre), so the winding-based checks are mostly silent here; the switch finder produces 5 of the 7 FAILs.
- Part A used the published centre; Part B shows our own centre finder would not have been good enough to substitute for it on this scroll at level 4.
- One resolution (level 4) for Parts B and C. Results at other levels are not implied.
- The 14 stray patch folders (3 files each, not in the README) were not scored.

## Reproduce
```bash
pip install -e ".[test]"
vun-groundtruth testdata/pherc_paris4_groundtruth --out results --alt-root CHECKOUT --surface-root CHECKOUT      # Part A (CHECKOUT = origin/tool/surface-agreement)
vun-groundtruth testdata/pherc_paris4_groundtruth --out results --parts B,C --l4-slices SLICES                     # Parts B, C
vun-groundtruth testdata/pherc_paris4_groundtruth --out results --fast --sweep 'min-switch-confidence=0.4,0.5,0.6;wn-min-span-deg=3,5,10,30;wn-jump-pitch=1.0,1.5,2.0,3.0;wn-min-points=10,8;ssf-k-points=8'
python tools/groundtruth_score/phantom_threshold_check.py --set min_switch_confidence=0.5 --json out.json
python tools/groundtruth_score/winding_l4.py testdata/pherc_paris4_groundtruth --slices-dir SLICES --out results --set pitch_vox=6 --set ray_sigma=0.5 --set ray_prominence=0.1 --stem winding_agreement_l4_diag_pitch6
```
`tests/test_groundtruth.py` pins the 40 recorded Part A verdicts; each of the 7 FAILs is a strict xfail asserting "not FAIL", so a change that fixes one fails the suite until the marker is removed.


## Re-scored after v2 (PRs 28-30)

**AI-assisted (Claude Code and Claude), human-directed.** Brief 28. Same scorer (`vun-groundtruth`, unchanged), same 40 patches, same
published centre line, re-run on this branch merged with `origin/main` (7593b7c: confidence-gated local pitch, NOT JUDGED regions, crush map).
No threshold or tool behaviour was changed. Source: `results/groundtruth_patches.csv` / `.md` (regenerated; the earlier CSV is in git history).
The original numbers above are kept as the "before" column.

| `vun-audit`, 40 verified patches | FAIL | NOT JUDGED | PASS | FAIL / 40 (Wilson 95 %) |
|---|---|---|---|---|
| **Before** (old main, one pitch per height) | 7 | 33 | 0 | 17.5 % (8.7 - 31.9) |
| **After** (v2 default, local pitch with confidence) | **0** | **40** | **0** | **0 % (0 - 8.8)** |
| After, `--global-pitch` (the pre-v2 pitch handling, now a flag) | 7 | 33 | 0 | 17.5 % (8.7 - 31.9) |
| After, `--pitch-vox` (one pitch per patch) | 7 | 33 | 0 | 17.5 % (8.7 - 31.9); was 9 FAIL / 31 NOT JUDGED (22.5 %) before |

What changed, in plain words: **the false alarms went to zero only because the auditor now abstains, not because it now passes.** All 40
patches are NOT JUDGED and none is PASS; every one carries the reason "only #% of the cut line has a trusted local pitch" (the 7 patches
that used to FAIL included). On these narrow windows the CT gives no local pitch the tool trusts, so it declines to judge instead of
guessing, which is the intended v2 behaviour but means that on this data the auditor currently says nothing useful about a correct trace.
The same 7 patches still FAIL for the same reasons when the old pitch handling is forced with `--global-pitch`, so nothing about those
traces or checks was fixed. The upper end of the interval (8.8 %) is the width of "no FAIL in 40", not evidence of a good checker; a
PASS rate of 0 / 40 is still the number to read next to it. The `surface_agreement` side result is unchanged (ON rate 1314 / 1949 = 67.4 %).

Tests pinned to the new CSV: the 7 former strict xfails are now pinned as NOT JUDGED and no FAIL remains (`FAILS` is empty; its
strict-xfail test stays in place for any future FAIL).
