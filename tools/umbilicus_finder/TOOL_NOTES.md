# TOOL_NOTES

- **What:** `umbilicus_finder`: estimates the scroll centre line (umbilicus) per z from structure-tensor
  sheet normals (closed-form least squares + Tukey/Huber re-weighting), with per-slice confidence
  (inlier votes, angular coverage, median residual in pitches) and a LOW flag; confidence-weighted
  running median + smoothing spline along z. CPU-only, MIT. Code, README (method, constants, limits),
  `requirements.txt` in this folder; tests in `tests/test_umbilicus_finder.py`.
- **Existing files untouched.** New files only. They are not listed in `SHA256SUMS.txt`.

## Step 0: what already exists (checked 2 Nov 2026)

Partial check: the sandbox could read github.com pages through a fetch tool but **not**
scrollprize.org, `dl.ash2txt.org`, or the GitHub API/code search (blocked by the network policy), so
this is not a full survey. Discord/forum tools, `volume-cartographer/` internals and the deprecated
`thaumato-anakalyptor/` were not opened.

- **`ScrollPrize/villa`, `spiral-fitting/umbilicus.py`**: a *loader*, not an estimator. It reads
  - JSON `{"control_points": [{"z":.., "y":.., "x":..}, ...]}`, sorted by z; or
  - a "thaumato" text file: one integer triple per line that the code reads as `y, z, x` with 500
    added to each (`[:, [2, 0, 1]] - 500`; corrected in review round 1, this line used to say `x,y,z`;
    see docs/FORMATS.md),
  and builds a linear `z -> (y, x)` interpolator (`interp1d`, extrapolating) with an optional
  `coordinate_scale` / `downsample_factor`. Units/resolution are whatever the caller uses.
  `fit_spiral.py` / `flatten_spiral_checkpoint.py` consume `umbilicus.json` (`--umbilicus`) as a
  separate, fixed input; the README says the checkpoint does not embed it. Nothing found says how the
  control points are made (they appear to be placed by hand).
- No automatic umbilicus estimator and no confidence measure was found in the pages that could be read.
  The curated-datasets page reportedly mentions a "fitted umbilicus" shipped with some data; it could
  not be opened, so where it comes from is unknown.
- This was **not** judged to be a mature automatic tool doing the same job, so the build went ahead.
  If one exists in material we could not read (e.g. inside `volume-cartographer`), compare before merging.

**How this tool differs:** it *produces* the centre line from the CT, and says per height how much to
trust it (coverage, residual, votes, flag, reason), instead of reading a hand-made one. It exports the
villa JSON (OK points only by default), so its output can feed the same consumers; this was
**not** tested against their code, only against the format as read.

## Tests

Synthetic only (see README "Tests"). Beyond the brief's list: odd-reflection median at the ends (a
truncated window pulled a linear drift ~3.6 voxels inward at z=0 in the first version; fixed),
JSON `NaN` -> `null`, wedge-shaped scroll (low coverage), downsample and level-scale half-voxel
convention, OME-Zarr level-1 and PNG-stack CLI runs.

## Not done / decisions to review

- **No real-data demonstration.** The data host was unreachable from the sandbox, so only synthetic
  slices were run (`demo_synthetic.py`). Defaults are untuned for real scans. No real scroll, and no
  scroll with restricted access, was used or mentioned.
- Mask: plain Otsu by default, as briefed. `--otsu-classes 3` (lowest threshold of 3-class Otsu) is an
  option for a case much denser than papyrus; I first made it the default on a guess, found plain Otsu
  passes the blob/ring test too, and reverted. Untested on real data.
- Pitch is estimated from the data (autocorrelation along normals) because the brief asks for a
  residual in pitches but gives no pitch input; `--pitch-vox` overrides.
- Confidence is a heuristic product of three factors, not a calibrated probability.
- Villa export: JSON only. The thaumato text export was skipped because its offset convention is unclear.
- z in outputs is the true level-0 centre of the sampled slice, `(i + 0.5) * s - 0.5`, not `i * s`.
