# sheet_spacing_check

Checks whether two traced papyrus surfaces (tifxyz meshes) that should be **adjacent turns** of a
scroll stay about one papyrus sheet apart. It flags places where they collapse onto the same
sheet (**shared**), skip a sheet (**skipped**), or leave the papyrus (**off-sheet**).
CPU-only. MIT licence, as in the repo.

```
pip install -r tools/sheet_spacing_check/requirements.txt
python tools/sheet_spacing_check/sheet_spacing_check.py MESH_A MESH_B \
    --zarr volume.zarr --heights 3000,3500,4000 --out-json report.json --out-txt report.txt \
    --overlay-dir overlays/
python -m pytest tests -q
```

Inputs: two tifxyz folders (`x.tif y.tif z.tif meta.json`, coordinates in level-0 volume voxels,
`-1` = no data) with **identical grid shape**; a CT volume (`--zarr` OME-Zarr, `--zarr-level`
default 0, or `--png-dir` with `--png-pixel-um`, `--png-pattern`); a list of z heights.
Mesh A is the reference; swap the arguments to get the B-to-A view.

## Method

For each height z:

1. **Cut line.** For each mesh, the points where the grid crosses z, linearly interpolated
   between consecutive rows of each grid column (z must vary along columns; use `--transpose`
   otherwise; it swaps the grids and the `meta.json` scale pair). A grid cell is invalid if
   **any** of x/y/z equals the no-data value (`--invalid-value`) or is non-finite; the number of
   invalid cells is reported as a warning. Points are ordered by column and split into *runs* where columns are not
   consecutive or the gap exceeds `--max-gap-vox`.
2. **Pair distance.** For each point of A, the in-plane (x, y) distance to the nearest point of
   B's line (B's line is resampled to `--densify-step-vox` first). An A point with **no B cut point within
   `--b-missing-cols` (5) grid columns** (a hole in B, or B ends/leaves the height) is
   **uncovered**: it is reported in `uncovered_fraction`, never as skipped/shared, and is not clean.
3. **CT sheet pitch.** At each point, the CT is sampled along the local in-plane normal
   (tangent from `--tangent-halfwidth` points each side, within the run), +/- `--profile-halflen-vox`,
   every `--profile-step-px`, Gaussian-smoothed (`--profile-sigma-px`). Bright peaks
   (`scipy.signal.find_peaks`, prominence >= `--peak-prominence-frac` of the profile range,
   spacing >= `--peak-min-distance-px`) give the pitch = median peak spacing, needing at least
   `--min-peaks` peaks. The height's **CT pitch** is the median over the points of both lines.
4. **Pair-clean.** distance / pitch in [`--ratio-min` 0.5, `--ratio-max` 1.5] **and** both points
   on-sheet. A's pitch at its own point is used for the ratio. On-sheet = the CT maximum within
   `--onsheet-radius-px` (2) of the point exceeds Otsu's threshold (`--otsu-bins`) computed on the
   slice tile (the bounding box of both lines plus profile length plus `--tile-pad-px`).
   B's point is its nearest point to the A point.
5. **Smoothing.** Running median of `--median-window` (5) pair-clean flags along each run.
6. **Report** per height: clean fraction (smoothed), shared fraction (ratio < 0.5), skipped
   fraction (ratio > 1.5), median ratio, CT pitch, mesh-derived pitch, and a mismatch flag if
   they differ by more than `--pitch-flag-frac` (25%) of the CT pitch. Fractions are over A's cut points.
   Shared/skipped are raw (not smoothed). Mesh-derived pitch = median of the pair distances
   (so for a "shared" pair it is ~0 and the flag fires, which is intended).

**Area.** A's columns are the persistent identity across heights. A column is clean at a height
if one of its cut points is smoothed-clean. A column passes if it is clean at >= N of the M
heights (`--min-clean-heights`, default ceil(M/2)). Area = sum over passing columns of the area
sampled at all heights, where each cut point contributes arc length x band thickness /
sqrt(1 - nz^2) (nz = z-component of the surface normal; clamped by `--area-min-cos`).
Points whose normal is undefined (next to holes) are **excluded** from the area, cannot make a
column clean, and are counted in `area.excluded_nan_normal_points` / `excluded_nan_normal_arc_vox`
(plus a warning). Band
thickness = height spacing (`--band-height-vox` to override; required for one height). Converted
to cm^2 with the voxel size from `meta.json` (`voxelsize`, `voxel_size`, ...) or
`--voxel-size-um`. Also reported: the total sampled area for context.

## Constants
Every constant above is a CLI flag with its default shown by `--help` and is echoed in the
JSON report under `params`.

## CT coordinate convention
Mesh coordinates are level-0 voxels. For a CT level with `ct_scale` = `sc` voxels per pixel
(`2**level` for zarr; `--png-pixel-um / voxel size` for PNG), pixel/slice `k` covers voxels
`[k*sc, k*sc + sc - 1]`: slice index = `floor(z / sc)`, pixel coordinate = `(x - (sc-1)/2) / sc`
(pixel centres at integers). At `sc = 1` this is the identity.

## Limits and deviations to know about
- **A and B must share column indexing.** "Uncovered" is decided from grid columns: an A point is
  uncovered when B has no cut point within `--b-missing-cols` columns of A's column. If B's
  columns are offset from A's (same shape, but traced starting elsewhere round the ring) and B
  has holes, some points are mislabelled: spatially covered points can be reported as uncovered,
  and points inside the hole as skipped. Both count as not clean, so this costs area but never
  gives a false pass.
- **A height outside the CT volume aborts the whole run** (an input error), unlike a height
  outside a mesh's z range, which is reported as uncovered.
- **Single-point runs give no area.** A run of one cut point has zero arc length.
- **A closed ring is split at its seam.** The first and last columns are separate runs, so the
  running median does not wrap round the seam.
- **PNG slices are read twice per height** (once to get the shape, once for the tile), and a whole
  slice is read each time; zarr reads only the tile.
- **Fractional heights are floored to a slice.** `slice = floor(z / sc)`, so z = 49.6 at scale 1
  uses slice 49 although the nearest voxel centre is 50. Use integer heights.
- **Pitch tolerance.** The pitch is the median over a +/-`--profile-halflen-vox` window, not a
  strictly local value. Treat the ratio window as roughly "within 1.5x of the window-median
  pitch"; a sharper local compression or stretch than that can push a true neighbour outside it.
- **Area does not use `meta.json` scale for the geometry.** It uses the measured mesh geometry
  (arc length, tilt), which is exact for irregular grids. `scale` is only cross-checked against
  the measured column spacing (a warning is emitted if off by >25%). This is a deliberate
  deviation from "use scale"; say if you want the scale-based version.
- The area is the area of *sampled bands* around the chosen heights, not of the whole surface.
- If a point has no CT pitch (< 3 peaks) the height's median CT pitch is used (fraction reported
  as `pitch_fallback_fraction`). If no pitch exists at all, the points are counted as `no_pitch`
  and are not clean.
- Heights outside a mesh's z range: that mesh has zero cut points; A points (if any) count as not
  clean, `uncovered_a/b` are set and `uncovered_fraction` is reported. The height still counts in M.
- Multiple crossings in one column are all kept, but the run logic assumes about one crossing per
  column; strongly folded meshes give fragmented runs and noisier tangents and smoothing.
- Cut lines of neighbouring sheets that pass between A and B (shared/skipped) are detected only
  through distance/pitch; the tool cannot tell which sheet a point belongs to.
- The pitch is estimated from a short 1-D profile; in noisy or compressed regions it is
  noisy. Otsu on a tile dominated by background or by papyrus gives a poor threshold.
- Distances are in-plane only; the z-direction is ignored.
- Needs a roughly vertical sheet orientation (axis ~ z); sheets lying near-horizontal give long,
  ill-defined cut lines.
- Memory: a PNG slice is read whole; zarr reads only the tile.

## Demonstration
**Synthetic only.** The tests build concentric cylindrical sheets and cylinder meshes
at known offsets (see `tests/`). I did **not** confirm a documented adjacent pair of public
segments (for example a PHerc0139 or PHerc0172 pair), so no real-data run is claimed and no scan
data is included or downloaded. Do not use this tool's output on real data as evidence until such
a pair has been checked.

## v0.2: local pitch per point, with a confidence

Evidence: `tools/realdata_run/RESULTS.md` (PR #17) finding 3 / P3: at the old defaults the CT pitch came out 14-17 voxels on the real
PHerc. Paris 4 slices, 1.5-1.8x the 9-10.5 measured independently along the mesh normals. The pitch is now measured per cut-line
point by `tools/common/local_pitch.py`: pass 1 finds the peaks of the normal profile (prominence `--pitch-prominence-frac` of
the profile range), pass 2 keeps the peaks within `--pitch-window-pitches` pass-1 pitches of the point and takes the median gap;
the confidence (0..1) is `min(1, gaps / 4)` x `max(0, 1 - cv / --pitch-cv-max)` x `min(1, autocorrelation at the pitch /
--pitch-ac-full)`. Points with fewer than `--min-peaks` local peaks have confidence 0. NaN pitches take the nearest measured one
on the same run. `--global-pitch` restores the old estimator exactly (peak prominence `--peak-prominence-frac`, 0.25, height
median as the fallback). Result fields added per height: `pitch_mode`, `pitch_confidence_mean`, `pitch_local_p10`,
`pitch_local_p90`.

| flag | default | meaning |
|---|---|---|
| `--global-pitch` | off | old pitch estimator and fallback |
| `--pitch-prominence-frac` | 0.05 | local pitch: min peak prominence / profile range (0.05-0.10 gave 9.5-12 vox on real data, 0.25 gave 14-17) |
| `--pitch-window-pitches` | 3.0 | local pitch: peaks within this many pitches of the point |
| `--pitch-cv-max` | 0.5 | confidence 0 at this robust scatter of the local gaps |
| `--pitch-ac-full` | 0.5 | confidence 1 at this autocorrelation at the pitch |
| `--pitch-smooth-points` | 1 | running median of pitch / confidence along each run (odd; 1 = off) |
| `--min-pitch-confidence` | 0.0 | points below this have no pitch (counted "no pitch", not clean) |

Limit: on the real data the confidence is low (mean about 0.1) because the periodicity is weak and broad; the pitch is then a
best guess within +-2 voxels, not a measurement.
