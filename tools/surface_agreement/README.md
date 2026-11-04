# surface_agreement: a second opinion from a learned surface prediction

The organisers publish a machine-made prediction of where the papyrus is (0..255, higher = more papyrus-like). This tool asks whether a
tifxyz trace lies on a sheet of that prediction, and compares the answer, point by point, with our own CT-peak judge.

    python tools/surface_agreement/surface_agreement.py TRACE [TRACE ...] \
        --pred-png-dir PRED_PNGS | --pred-zarr PRED.zarr  [--ct-png-dir CT_PNGS | --ct-zarr CT.zarr] \
        [--png-pixel-um UM --voxel-size-um UM] [--heights 9503,12001] --out-dir OUT [--audit [--umbilicus FILE]]
    (installed: `vun-surface ...`)

The prediction and the CT must be on the same grid as the trace (the sample in `testdata/pherc_paris4_surfpred` is). PNG stacks
use the slice-file convention of the other tools (`{z:05d}.png`, `--png-pattern`).

## What it measures
At each height the trace is cut by the plane z = height (the cut line `sheet_spacing_check` uses). At every cut-line point the prediction is
sampled along the in-plane normal from -k to +k voxels (`--half-len-vox`, sign: + along the normal = the cut-line tangent rotated by +90 deg):

| per point | meaning |
|---|---|
| `pred_value` | prediction at the trace point (0..255) |
| `pred_offset_vox` | signed distance to the nearest prediction **ridge** (local maximum of the profile smoothed by `--sigma-px`, at least `--ridge-prominence` above its surroundings; the middle of a band, also for a binary mask) |
| verdict | `ON-PREDICTED-SHEET` if value >= `--on-value-min` and a ridge within `--on-tol-vox`; `OFF` otherwise; `NOT JUDGED` = no prediction data (slice missing, point outside the image, no usable normal) |

Per height and overall: counts, the ON fraction of the judged points, and a height verdict PASS (ON fraction >= `--pass-on-fraction`) / FAIL /
NOT JUDGED (fewer than `--min-judged-points`).

## The agreement (needs a CT)
Our peak-based verdict for the same point is the measure of `tools/label_drift`: signed distance to the nearest CT sheet peak
(`--ct-prominence-frac`); `ON-CT-PEAK` within `--ct-on-tol-vox`, else `OFF`, `NOT JUDGED` where the CT has no peak or no data. Per height a
2 x 2 table (ours x prediction) counts the compared points; the disagreeing points are listed (`report.json`, `disagreements`, at most
`--max-listed` per height; all of them in `points_<trace>.csv`, column `agreement`). `--audit` adds the trace_auditor verdict (and the
spacing check for two traces) as context; it needs a centre line (`--umbilicus`, else it estimates one and may say NOT JUDGED).

## Output
`report.json`, `report.txt`, `points_<trace>.csv`, and in `png/` per trace and height: `*_on_prediction.png` (trace points on the prediction:
green ON, red OFF, yellow NOT JUDGED) and `*_disagreement_on_ct.png` (on the CT: magenta = ours ON / prediction OFF, cyan = ours OFF /
prediction ON, white = agree, grey = not compared). `--png-scale` magnifies, `--png-margin-px` sets the crop.

## Thresholds (every one is a flag; defaults)
| flag | default | |
|---|---|---|
| `--half-len-vox` | 30 | k: profile reach each side of the trace (voxels) |
| `--step-px` | 0.5 | profile sample step (pixels) |
| `--sigma-px` | 1.5 | profile smoothing before ridges are found (pixels) |
| `--ridge-prominence` | 64 | min ridge prominence (0..255 units) |
| `--on-value-min` | 128 | min prediction value at the trace point for ON |
| `--on-tol-vox` | 3 | max distance to the nearest ridge for ON |
| `--pred-max` | 255 | the value meaning "certainly papyrus" (rescaled to 255) |
| `--ct-on-tol-vox` | 2 | our verdict: max distance to the nearest CT peak |
| `--ct-prominence-frac` | 0.10 | CT peak prominence / profile range |
| `--pass-on-fraction` | 0.8 | height PASS needs this ON fraction |
| `--min-judged-points` | 10 | fewer judged points = NOT JUDGED |
| `--n-heights`, `--height-margin` | 5, 0.10 | automatic heights (when `--heights` is absent) |
| `--png-scale`, `--png-margin-px`, `--max-listed` | 3, 20, 200 | overlays and listing |

Pick `--on-tol-vox` and `--ct-on-tol-vox` well under half the sheet pitch: at half a pitch every point is "near a sheet" and the test says nothing.
Helpers: `fake_prediction.py` (blurred sheet mask of a phantom CT, used by the tests) and `break_trace.py` (shift all nodes beyond a column
by S voxels along the normal, the deliberate break).

## Limits (read before trusting an ON)
* A prediction says "there is a sheet here", not "this is the sheet we want". A trace that jumps by exactly one pitch to the neighbouring
  sheet stays ON at every point; only the winding-offset / spacing checks of `trace_auditor` can see that (tested: `test_whole_sheet_switch_is_invisible...`).
* The prediction can have artefacts (the real sample has saturated blocks in the masked area outside the scroll); a point there has no ridge and is OFF.
* In-plane only: the profile runs along the in-plane part of the normal at the cut height; a steeply tilted surface is sampled obliquely.
* Not calibrated against human judgement: the defaults are a first guess (see the PR for what they do on the one real window).
