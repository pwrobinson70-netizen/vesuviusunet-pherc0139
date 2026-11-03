# crush_map: where is the scroll crushed, and where can the trace tools not be trusted?

```bash
pip install -r tools/crush_map/requirements.txt
python tools/crush_map/crush_map.py --zarr VOL.zarr --heights 500,1000,1500 --out-dir OUT          # or: vun-crush ...
python tools/crush_map/crush_map.py --png-dir SLICES --png-pixel-um 45.532 --voxel-size-um 45.532 --heights 2073,2600,3128 --out-dir OUT
python tools/trace_auditor/trace_auditor.py A.tifxyz --zarr VOL.zarr --umbilicus U.json --crush-map OUT/crush_map.npz --out-dir AUD
```

For every height, a map over the slice (cells of `--grid-step-px` CT pixels):

| map | what |
|---|---|
| `pitch` | local sheet spacing in voxels: `tools/common/local_pitch.py` along the structure-tensor normal (NaN where the coherence is below `--coherence-min` or nothing can be measured) |
| `variability` | robust scatter of ln(pitch) over a `--var-window` x `--var-window` block of cells |
| `coherence` | structure-tensor coherence of the sheet normals, 0..1 |
| `confidence` | local-pitch confidence, 0..1 (peaks x regularity x autocorrelation at the pitch) |
| `density` | local papyrus fill fraction (above-Otsu mask in the filled scroll region, Gaussian window `--density-sigma-px`) |
| `severity` | **0..1 estimate of how crushed the sheets are**: the mean of `ln(phi / phi_ref) / ln F` (density term) and `ln(pitch_ref / pitch) / ln F` (spacing term), `F` = `--full-factor` (4), clipped to 0..1; a cell without a measurable pitch keeps its density term. `phi_ref` / `pitch_ref` = a percentile (`--density-ref-percentile` 20, `--pitch-ref-percentile` 75) of the least crushed part of the same slice |

Outputs in `--out-dir`: `crush_map.npz` (all maps stacked over the heights, plus `heights` and a JSON `meta`), `crush_zNNNNNN.png`
per height (CT | pitch | variability | coherence | severity), `summary.csv` and `summary.json` per height (pitch p10 / median / p90,
variability, coherence, confidence, mean and p90 severity, fraction of cells with severity >= 0.5, the two reference values),
and with `--write-zarr` a `crush_map.zarr`. `trace_auditor --crush-map` reads the npz (`CrushMap.at(z, xy)`).

## Every flag

| flag | default | meaning |
|---|---|---|
| `--grid-step-px` | 4 | map cell size (CT pixels) |
| `--coherence-min` | 0.25 | cells below this normal coherence get no pitch |
| `--sigma-grad` | 1.5 | structure tensor: gradient sigma (CT px) |
| `--sigma-int` | 4.0 | structure tensor: integration sigma (CT px) |
| `--region-close-px` | 12 | scroll region = Otsu foreground, closed by this radius, hole-filled (CT px) |
| `--density-sigma-px` | 8.0 | papyrus fill fraction: Gaussian window sigma (CT px) |
| `--density-ref-percentile` | 20.0 | phi_ref: this percentile of the fill fraction inside the region (the least crushed part) |
| `--pitch-ref-percentile` | 75.0 | pitch_ref: this percentile of the confident pitches (the least crushed part) |
| `--pitch-ref-min-confidence` | 0.3 | pitches below this confidence do not enter pitch_ref |
| `--full-factor` | 4.0 | spacing change at which severity reaches 1 |
| `--var-window` | 5 | variability window (cells, odd) |
| `--edge-margin-px` | 8 | cells this close to the region border get no severity (the window is cut by the border) |
| `--pitch-half-len-vox` | 40.0 | local pitch: normal profile half-length (voxels) |
| `--pitch-prominence-frac` | 0.05 | local pitch: min peak prominence / profile range |
| `--pitch-window-pitches` | 3.0 | local pitch: use peaks within this many pitches of the point |
| `--pitch-cv-max` | 0.5 | local pitch: confidence 0 at this robust scatter of the local gaps |
| `--pitch-ac-full` | 0.5 | local pitch: confidence 1 at this autocorrelation at the pitch |
| `--min-peaks` | 3 | local pitch: peaks needed for a pitch |
| `--profile-step-px` | 0.5 | local pitch: profile sample step (CT px) |
| `--profile-sigma-px` | 1.0 | local pitch: profile smoothing sigma (CT px) |
| `--peak-min-distance-px` | 3.0 | local pitch: min spacing between peaks (CT px) |

Input / output flags: `--zarr` or `--png-dir` (+ `--png-pixel-um`, `--voxel-size-um`, `--png-pattern`), `--zarr-level`, `--heights` or `--z-start` / `--z-stop` / `--z-step`, `--out-dir`, `--no-png`, `--write-zarr`.

## How well does it work (synthetic phantoms only)

`phantom_scroll` writes the TRUE per-voxel deformation severity (`severity.npy`: the larger of the feature window and |ln s| / ln 4,
s = the true local radial stretch). Spearman correlation of the estimate with it over the map cells inside the scroll
(192^3 phantoms, 3 slices each): see the pull request description for the table (seed 0 and held-out seeds); the test requires
> 0.7 on `crushed-hard` and a mean below 0.05 on `round`.

## Limits

- The density term assumes sheets of about constant thickness. Real scans have dust, varying thickness and brightness; there it
  also tracks thickness, and nothing here has been checked on real data.
- The scroll region is the Otsu foreground closed by `--region-close-px` (12 CT px) and hole-filled: sheets further apart than twice
  that are not bridged, a very wide pitch needs a larger value.
- `severity` measures a change of spacing relative to the least crushed part of the SAME slice. A slice that is crushed everywhere
  reads low; a slice with several scrolls or a case ring will not work.
- The cells next to the region border (`--edge-margin-px`) get no severity (the density window is cut by the border).
- The thresholds (`--coherence-min`, percentiles, `--full-factor`, the mean of the two terms) are judgement calls tuned on seed 0
  of the synthetic phantoms.
