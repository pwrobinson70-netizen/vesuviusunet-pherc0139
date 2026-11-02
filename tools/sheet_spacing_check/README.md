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
   otherwise). Points are ordered by column and split into *runs* where columns are not
   consecutive or the gap exceeds `--max-gap-vox`.
2. **Pair distance.** For each point of A, the in-plane (x, y) distance to the nearest point of
   B's line (B's line is resampled to `--densify-step-vox` first).
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
   fraction (ratio > 1.5), `b_missing_fraction` (see below), median ratio, CT pitch, mesh-derived pitch, and a mismatch flag if
   they differ by more than `--pitch-flag-frac` (25%) of the CT pitch. Fractions are over A's cut points.
   Shared/skipped are raw (not smoothed). Mesh-derived pitch = median of the pair distances
   (so for a "shared" pair it is ~0 and the flag fires, which is intended).

**Area.** A's columns are the persistent identity across heights. A column is clean at a height
if one of its cut points is smoothed-clean. A column passes if it is clean at >= N of the M
heights (`--min-clean-heights`, default ceil(M/2)). Area = sum over passing columns of the area
sampled at all heights, where each cut point contributes arc length x band thickness /
sqrt(1 - nz^2) (nz = z-component of the surface normal; clamped by `--area-min-cos`). Band
thickness = height spacing (`--band-height-vox` to override; required for one height). Converted
to cm^2 with the voxel size from `meta.json` (`voxelsize`, `voxel_size`, ...) or
`--voxel-size-um`. Also reported: the total sampled area for context.

**Missing B trace.** An A point is `b_missing`, not `skipped`, when B has no cut point within
+/- `--missing-cols` (1) grid columns of it **and** its nearest B point is farther than
`ratio_max` pitches. These points are not clean and are excluded from shared/skipped, so a hole or
early end in B is not mistaken for a skipped sheet. Points near the edge of a hole are still
measured against the nearest B point.

**Pixel convention.** A CT pixel at level L covers `2^L` voxels; voxel coordinates map to pixels as
`(v - (s-1)/2) / s` (s = voxels per pixel) and the slice index is `floor(z / s)`.

## Constants
Every constant above is a CLI flag with its default shown by `--help` and is echoed in the
JSON report under `params`.

## Limits and deviations to know about
- **Area does not use `meta.json` scale for the geometry.** It uses the measured mesh geometry
  (arc length, tilt), which is exact for irregular grids. `scale` is only cross-checked against
  the measured column spacing (a warning is emitted if off by >25%). This is a deliberate
  deviation from "use scale"; say if you want the scale-based version.
- The area is the area of *sampled bands* around the chosen heights, not of the whole surface.
- If a point has no CT pitch (< 3 peaks) the height's median CT pitch is used (fraction reported
  as `pitch_fallback_fraction`). If no pitch exists at all, the points are counted as `no_pitch`
  and are not clean.
- Invalid cells: a cell is no-data if **any** of x, y, z equals `--invalid-value`; the count is
  reported as a warning. Cut points next to a hole use the nearest finite surface normal in the
  same run for the area tilt factor; points with none use factor 1 and are counted in a warning.
- Not handled yet: a height outside the CT volume aborts the run rather than being reported
  uncovered; single-point runs contribute no area; closed rings are two runs at the seam; PNG slices
  are read twice per height.
- Heights outside a mesh's z range: that mesh has zero cut points; A points (if any) count as not
  clean, `uncovered_a/b` are set and `uncovered_fraction` is reported. The height still counts in M.
- Multiple crossings in one column are all kept, but the run logic assumes about one crossing per
  column; strongly folded meshes give fragmented runs and noisier tangents and smoothing.
- Cut lines of neighbouring sheets that pass between A and B (shared/skipped) are detected only
  through distance/pitch; the tool cannot tell which sheet a point belongs to.
- The pitch is the median over a +/- `--profile-halflen-vox` window, not a purely local value, so
  a neighbour that departs from that window median by more than about 1.5x (or below 0.5x) is
  flagged even if it is truly adjacent. The pitch estimate is also noisy in compressed regions. Otsu on a tile dominated by background or by papyrus gives a poor threshold.
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
