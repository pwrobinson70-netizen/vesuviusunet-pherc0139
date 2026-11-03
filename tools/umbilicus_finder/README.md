# umbilicus_finder

Estimates a scroll's centre line (umbilicus) through a CT volume, one point per requested z, with an
honest per-slice confidence. Built for crushed scrolls where the centre is too hard to pick by eye.
CPU only, MIT licence (repository `LICENSE`). Not a replacement for looking at the result: every LOW
point is a place where the method itself says it does not trust the number.

## Usage

```
cd tools/umbilicus_finder
pip install -r requirements.txt
python umbilicus_finder.py SCROLL.zarr --level 4 --z-start 1000 --z-stop 9000 --z-step 200 \
       --out-dir out --overlays
python umbilicus_finder.py slices_png/ --pixel-um 31.64 --voxel-um 7.91 --out-dir out
python demo_synthetic.py demo_out      # synthetic drifting + crushed spiral, no data needed
```

**Input.** An OME-Zarr group (any `--level`; the scale to level 0 is read from the OME `scale`
transforms, else 2^level) or a bare 3-D zarr array (give `--xy-scale` / `--z-scale` if it is not
level 0), or a directory of slice PNGs sorted by name (in-plane scale from `--xy-scale` or
`--pixel-um / --voxel-um`; `--z-scale` defaults to the same). **z range** is in level-0 voxels
(`--z-start`, `--z-stop` exclusive, `--z-step`); a range outside the volume is an error (exit 2),
not silently clipped. Several requested z that fall on the same level slice are merged.

**Coordinates.** All outputs are level-0 voxels, (z, y, x). A level voxel `i` with scale `s` has its
centre at `(i + 0.5) * s - 0.5` in level-0 voxels; the same convention is used for z and for the
downsampling inside the tool, so a coarse level is not offset by half a coarse voxel.

## Output (`--out-dir`)

| file | content |
|---|---|
| `umbilicus.csv` | `z,y,x,confidence,flag` = the **smoothed** line, confidence in 0-1, flag `OK`/`LOW`; then `raw_y,raw_x` (unsmoothed per-slice estimate), `departure_vox`, `n_votes`, `n_inliers`, `coverage_deg`, `residual_pitch`, `reason` |
| `umbilicus_summary.json` | counts, estimated pitch, where the smoothed line departs from the raw estimate, LOW z ranges with reasons, all parameter values |
| `umbilicus_villa.json` | ScrollPrize/villa umbilicus JSON, see below |
| `overlays/overlay_z*.png` | with `--overlays`: slice, voting normals (red inlier, blue outlier) drawn from the voting pixel to the foot of the perpendicular from the centre, centre as a green cross |

**Export format.** `ScrollPrize/villa` has `spiral-fitting/umbilicus.py`, which *reads* a JSON
`{"control_points": [{"z":..,"y":..,"x":..}, ...]}` (sorted by z, linearly interpolated and
extrapolated) or a "thaumato" text file. `umbilicus_villa.json` is exactly that JSON, in level-0 voxel
units, **OK points only** (`--export-all` adds LOW ones). We did not run their code; see `TOOL_NOTES.md`.

Exit codes: 0 ok, 2 bad input, 3 no slice produced a centre.

## Method

1. **Mask.** Block-mean downsample so the long side is about `--target-px`; Gaussian smooth;
   Otsu threshold; keep the connected component with the most papyrus pixels; binary closing; fill
   holes. `--otsu-classes 3` instead uses the lowest threshold of a 3-class Otsu (air | papyrus |
   denser), meant for a case much denser than the papyrus; it passes the synthetic tests but has no
   advantage over plain Otsu there and has not been tried on real data. Choosing the component by pixel count *before* hole filling
   stops a thin case ring that encloses the scroll from winning on its filled area.
2. **Sheet normals.** Structure tensor of the (smoothed) image, `--sigma-grad` for the derivative
   and `--sigma-int` for the integration. Its dominant eigenvector is the local gradient direction
   = sheet normal. Keep mask pixels with coherence `(l1-l2)/(l1+l2) >= --coherence-min` and enough
   gradient energy. Vote weight = coherence * min(energy / median energy, cap).
3. **Centre.** Each vote defines a normal line through its pixel. In a rolled scroll these pass near
   the centre. The centre `c` minimises `sum w_i |(I - n_i n_i^T)(c - p_i)|^2`, which is the 2x2
   linear system `(sum w P_i) c = sum w P_i p_i` (closed form). Then `--robust-iters` rounds of
   Tukey (default) or Huber re-weighting on the perpendicular distances, with a median-based scale.
4. **Confidence per slice.** Inlier votes (robust weight >= `--inlier-weight`), **angular coverage**
   (azimuth of inlier votes around the centre, 10-degree bins that hold enough votes, 0-360), and the
   **median perpendicular residual in pitches**. The pitch is estimated from the data: the mean
   autocorrelation of intensity profiles taken along the vote normals (shape independent, so it
   also works on a squashed scroll); the median over slices is used for all slices, or give
   `--pitch-vox`. `confidence = votes_factor * coverage_factor * residual_factor` with
   `votes_factor = min(1, inliers / votes_full)`, `coverage_factor = min(1, coverage / coverage_full)`,
   `residual_factor = 1 / (1 + (residual_pitch / max_residual_pitch)^2)`.
   **LOW** if coverage < 180 deg, or residual > 1 pitch, or too few inlier votes, or confidence < 0.3,
   or no pitch could be found, or no scroll / no usable votes. The `reason` column says which.
   For reference: an ideal Archimedean spiral has a residual of about 1/(2 pi) = 0.16 pitch even
   with a perfect centre (the normals are tilted), and a 2:1 ellipse gives about 2.5 pitches.
5. **Along z.** Confidence-weighted running median (`--median-window`, odd reflection at the ends so
   a linear drift is not biased), then a smoothing spline (`--spline-degree`) weighted by
   `sqrt(confidence) / --spline-sigma-vox`, smoothing factor = number of points. LOW slices keep a
   small weight (`--min-weight`) so they are pulled onto the line rather than pulling it. Where the
   smoothed line is more than `--departure-vox` from the raw estimate, the z range is reported in the
   JSON summary, and the distance is in the `departure_vox` column.

## Constants (every one is a CLI flag)

| flag | default | meaning |
|---|---|---|
| `--target-px` | `1000` | downsample (block mean) so the longer side is about this many px |
| `--otsu-classes` | `2` | 2 = Otsu; 3 = 3-class Otsu using its lowest threshold (for a case much denser than papyrus; untested on real data) |
| `--mask-sigma` | `2.0` | Gaussian sigma (ds px) before thresholding |
| `--close-radius` | `2` | binary closing radius (ds px) before fill-holes; 0 = off |
| `--sigma-grad` | `1.5` | gradient Gaussian sigma (ds px) |
| `--sigma-int` | `4.0` | tensor integration Gaussian sigma (ds px) |
| `--coherence-min` | `0.4` | keep pixels with structure-tensor coherence >= this |
| `--energy-min-frac` | `0.1` | keep pixels with gradient energy >= this fraction of the in-mask 95th percentile |
| `--energy-cap` | `3.0` | vote weight = coherence * min(energy / median energy, cap) |
| `--robust` | `tukey` | re-weighting: tukey or huber |
| `--robust-iters` | `8` | re-weighting iterations |
| `--tukey-c` | `4.685` | Tukey cutoff in robust scales |
| `--huber-k` | `1.345` | Huber knee in robust scales |
| `--min-scale-px` | `0.25` | floor for the robust residual scale (ds px) |
| `--inlier-weight` | `0.5` | a vote is an inlier if its robust weight >= this |
| `--min-votes` | `300` | LOW if fewer inlier votes than this |
| `--votes-full` | `3000` | inlier votes at which the votes factor reaches 1 |
| `--min-coverage-deg` | `180.0` | LOW if angular coverage of inlier votes is below this (deg) |
| `--coverage-full-deg` | `300.0` | coverage at which the coverage factor reaches 1 (deg) |
| `--coverage-bin-deg` | `10.0` | azimuth bin width for coverage (deg) |
| `--coverage-bin-min-frac` | `0.005` | a bin counts as covered with >= this fraction of inlier votes (and >= 3) |
| `--max-residual-pitch` | `1.0` | LOW if median perpendicular residual exceeds this many pitches; factor is 0.5 at this value |
| `--min-confidence` | `0.3` | LOW if confidence is below this |
| `--pitch-vox` | `0.0` | sheet pitch in level-0 voxels; 0 = estimate from the data |
| `--pitch-search-px` | `40.0` | half-length of the normal-direction profiles used to estimate pitch (ds px) |
| `--pitch-samples` | `1500` | votes sampled for the pitch estimate |
| `--pitch-min-peak` | `0.1` | minimum autocorrelation peak accepted as the pitch |
| `--median-window` | `5` | weighted running-median window (samples, odd) |
| `--spline-sigma-vox` | `3.0` | assumed per-slice centre noise (level-0 voxels) for the smoothing spline |
| `--spline-degree` | `3` | smoothing spline degree (1-5) |
| `--min-weight` | `0.02` | floor on the confidence used as spline / median weight |
| `--departure-vox` | `10.0` | report z ranges where the smoothed line is further than this from the raw estimate (level-0 voxels) |
| `--seed` | `0` | random seed (vote sub-sampling) |

Sigmas, radii, `--target-px` and `--pitch-search-px` are in downsampled-image pixels; `--spline-sigma-vox`,
`--departure-vox` and `--pitch-vox` are in level-0 voxels. The defaults were tuned on the synthetic
slices only (pitch 12-20 px at 400-1900 px across). Real scans have not been tried; on real data
expect to adjust `--sigma-int` (about half a pitch or more) and `--target-px` (so that one pitch is
roughly 8-25 downsampled pixels).

## Limits

- **2-D per slice, no tracking along the scroll.** A slice that is dominated by something other than
  the scroll's own layers (end of the scroll, large tears, delamination) gives a wrong centre; the
  coverage/residual flags catch many of these but not all.
- **Crushed / flattened regions.** Sheet normals of an ellipse do not meet at one point. The tool
  still returns the least-squares point (about 1.4 px off in the 2:1 synthetic case) but flags it LOW.
  The residual measure is a symptom detector, not a calibrated error bar.
- **The confidence number is a heuristic product**, not a probability. Use the flag and the reasons.
- **The mask assumes a single Otsu split separates scroll from air.** A case that is *less* dense than the
  papyrus, or that touches the scroll, is not handled. The component with most papyrus pixels is
  assumed to be the scroll.
- **A hollow core or a gap at the centre** is fine, but if the scroll has several lobes (two rolls)
  there is no single centre and the result is meaningless.
- **Spline ends.** The first and last points are the least constrained; a long LOW run at an end is
  extrapolated by the spline and can be several voxels off (demo: up to ~5 voxels at the end of the
  crushed run, all flagged LOW).
- **Pitch estimation** needs a periodic sheet pattern within `--pitch-search-px`; if it fails for
  all slices the flag is LOW with reason `no_pitch` (give `--pitch-vox`).
- Anisotropic in-plane voxels are not supported (one `--xy-scale`).

## Demonstration (synthetic only)

Real data could not be downloaded from the build sandbox (the data host was blocked by the network
policy), so there is no real-scan demonstration; see `TOOL_NOTES.md`. `demo_synthetic.py` makes a 24-slice
volume (400 x 480) with a spiral whose centre drifts by (+3, -2) px per slice and which is squashed
progressively from z = 12 (ratio about 3:1 at z = 23). Result with default settings:

- z 0-12: flag OK, confidence 0.97 -> 0.65, centre within 1.5 voxels of the true drift.
- z 13-23: flag LOW (`high_residual`, residual 1.25 -> 3.8 pitches, confidence 0.38 -> 0.05); the raw
  estimate is still within about 3 voxels of the truth here, probably because the squash is symmetric about
  the centre, which real crushing usually is not.
- Estimated pitch 12.0 voxels (true 12).

## Tests

`python -m pytest -q` from the repository root (`tests/test_umbilicus_finder.py`, synthetic only):
round spiral within 2 px; other pitch; downsampled slice and level-scale coordinate convention;
linear drift recovered (slope within 5 %); 2:1 ellipse returns a centre with lower confidence and
LOW; off-centre bright blob and case ring ignored; empty / constant / noise / NaN / tiny slices
LOW without a crash; low-coverage wedge LOW; bad slice down-weighted in z and reported as a
departure; bad paths, wrong shapes, z range outside the volume; every `Params` field is a CLI flag;
end-to-end CLI on OME-Zarr level 1 and on a PNG stack.
