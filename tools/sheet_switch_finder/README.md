# sheet_switch_finder

Takes **one** traced papyrus surface (a tifxyz mesh) and the CT volume and reports the places where
the trace **jumps from its own sheet onto a neighbouring sheet** (a *sheet switch*), so a human can fix
those spots instead of re-checking the whole mesh. CPU-only. MIT licence, as in the repo.

```
pip install -r tools/sheet_switch_finder/requirements.txt
python tools/sheet_switch_finder/sheet_switch_finder.py MESH --zarr volume.zarr \
    --heights 3000,3500,4000 --out-json switches.json --out-txt switches.txt --overlay-dir overlays/
python -m pytest tests -q
```

Inputs are those of `tools/sheet_spacing_check` (tifxyz folder with `x.tif y.tif z.tif meta.json`,
`-1` = no data; OME-Zarr via `--zarr` / `--zarr-level`, or `--png-dir` + `--png-pixel-um`; `--transpose`).
The mesh and CT readers, the cut line, the normals, the CT pitch and the on-sheet test are **imported**
from `tools/sheet_spacing_check/` (`ssc_io.py`, `sheet_spacing_check.py`), not copied, and that folder
is not modified.

## Method (every constant is a CLI flag; `--help` shows the defaults, the JSON echoes them under `params`)

For each requested height z:

1. **Cut line.** The mesh cut line of `sheet_spacing_check` (grid crossings of z, interpolated along
   grid columns). Runs are split at non-consecutive columns and at gaps above `--max-gap-pitches` (3.5
   pitches; `sheet_spacing_check` uses a fixed 20 voxels, which would cut a one-sheet jump on a
   coarse scan, so it is pitch-relative here).
2. **Peaks on the normal.** The CT is sampled along the local normal of the line (tangent from
   `--tangent-halfwidth` points each side), **+/- `--sample-pitches` (3) CT pitches**, every
   `--profile-step-px`, Gaussian-smoothed; bright-sheet peaks by `scipy.signal.find_peaks`
   (`--peak-prominence-frac`, `--peak-min-distance-px`), refined by a parabola. **CT pitch** = the median
   peak spacing along the line, measured exactly as in `sheet_spacing_check` (`ct_pitches`;
   `--profile-halflen-vox`, `--min-peaks`), median over the line at that height. `--pitch-vox` overrides.
   The normal is oriented **outward**: away from `--centre-x/--centre-y`, default the centroid of the cut
   line (right for a ring or an arc of one; for a nearly straight line give the centre, or use
   `--orientation grid` for the raw normal).
3. **Track one sheet.** Start at the peak nearest the mesh at the first on-sheet point of a run. At each
   next point pick the peak nearest the previously tracked position (continuity), *not* the one nearest
   the mesh. Nearest is measured across the sheet, and a peak further than `--track-max-jump-pitch`
   (0.5 pitch) is refused (the point is *lost*). Tracking restarts (at the peak nearest the mesh) after
   `--max-lost-points` (10) lost points or `--max-offsheet-bridge` (10) consecutive off-sheet points.
4. **Signed offset** = (mesh position - tracked sheet position) / pitch along the outward normal.
   Positive: the mesh sits outward of the sheet being tracked.
5. **Switch.** A step in the offset of `--step-min` 0.6 to `--step-max` 1.4 pitches (about +1 or -1),
   after a running median of `--median-window` (5) points, that **stays for at least `--k-points` (5)
   points on both sides**. Concretely, between consecutive tracked on-sheet points i-1 and i: the median
   of the K points after minus the median of the K points before is the step, and all K points on each
   side must lie on their own side of the midpoint level. Reported with direction (`outward` = the mesh
   hopped outward relative to the CT sheet, `inward`) and the size. A step above `--step-max` up to
   `--multi-step-max` (3.5) is reported too, with `n_sheets` = rounded size (at least 2) and
   `double_switch: true` ("double/multi switch"). The reported position is the middle of the gap between the
   last point before and the first after (normally the first point on the new sheet). Confidence in 0..1 =
   (1 - |size - whole number| / `--conf-int-tol` 0.4) x (1 - (mean abs deviation of the two sides) /
   `--conf-flat-tol` 0.3), each factor clipped at 0.
6. **Vertical test** (`--vertical 0` switches it off). For each grid column, the offset at consecutive
   requested heights is compared (first tracked on-sheet cut point of the column). The step between the two
   heights is median-smoothed across neighbouring columns and the same size window applies; a stretch of
   at least K consecutive columns with a step of one sign is one **vertical** switch (heights
   `height_from` -> `height_to`, `col_start`..`col_end`, `n_columns`, position at the middle column at the upper height).
7. **Off-sheet.** A point is on-sheet by the `sheet_spacing_check` test (CT maximum within
   `--onsheet-radius-px` of the point above Otsu's threshold of the tile; then the same running median).
   Off-sheet points are reported as off-sheet, never as switches, and are left out of the step test. A mesh
   that dips into a dark gap and comes back to the same sheet therefore gives no switch.

Also guarded against bad normals: where the mesh crosses sheets at a steep angle its normal tilts and
sampling along it inflates the offset, so normals more than `--max-tilt-deg` (25) from the running median
normal (`--tilt-window` 31) are not used (those points count as *lost*), and normals are not taken across a
hard jump of more than `--normal-break-factor` (4) times the usual point spacing.

## Output
- **JSON** (`--out-json`): `inputs`, `params`, and `result` with `heights` (per height: points, CT pitch,
  `fraction_tracked`, `fraction_off_sheet`, `fraction_lost`, switch counts), `switches` and `summary`. A switch
  record has `kind` (`horizontal`/`vertical`), `height`, `row` (fractional grid row), `col`, `x`, `y`, `z` (voxels),
  `direction`, `step` (pitches, signed), `n_sheets`, `double_switch`, `confidence`, `line_index`, and for
  horizontal ones `index_before/after`; for vertical ones `height_from`, `height_to`, `col_start`, `col_end`, `n_columns`.
- **Text summary** (`--out-txt`, also printed): switches per height, fraction of the line tracked, fraction off-sheet,
  fraction lost, and the list of switches.
- **Overlay PNGs** (`--overlay-dir`, one per height): the CT slice with the cut line coloured by offset
  (green 0, red positive/outward, blue negative/inward, white off-sheet, yellow lost) and a ring at each switch
  (cyan horizontal, magenta vertical).

## Limits to know about
- **Offsets are relative to each height's own anchor.** The track starts at the sheet nearest the mesh at the
  first on-sheet point, so a switch that moves the *whole* line (including the anchor), or a mesh that is on the
  wrong sheet from its very first point, has offset 0 and is **not found**. Only changes along the line (or between
  heights, for part of it) are.
- A switch hidden inside a stretch of more than `--max-offsheet-bridge` off-sheet points (or `--max-lost-points`
  lost points) is not found: the track restarts afterwards. Raise the flags to bridge longer gaps.
- A switch within K tracked points of a run end (or of a seam of a closed ring; runs are not joined round the seam)
  cannot satisfy "stays K points on both sides". Two switches closer than about 2K points to each other cancel
  or are missed; an excursion shorter than K points is not a switch (by design).
- A switch is only seen if the peaks both sheets give lie inside +/- 3 pitches (hops of up to about 3 sheets).
- Normals at a hop between sheets are poor; those points are dropped (shown yellow). Strong white noise in the
  mesh also drops normals (the tracked fraction falls), which is reported, not hidden.
- Direction depends on the orientation of the normal (see step 2); check it on a ring before trusting it on a
  straight piece.
- The vertical test needs two requested heights and tracked points in the same grid column at both; with several
  crossings in one column only the first is used. It cannot distinguish a patch that is on the wrong sheet at one
  height from one on the wrong sheet at the other (the horizontal edges at each height tell you which).
- Pitch is one median per height; a strongly varying pitch (compressed or stretched layers) can push a true
  neighbour outside the 0.5-pitch continuity gate or give offsets that are not whole numbers (low confidence).
- Fractional heights are floored to a slice (as in `sheet_spacing_check`); use integer heights. A height outside
  the CT volume aborts the run; a height outside the mesh z range is reported with a note and skipped.
- Sheets are assumed roughly parallel to the z axis (as in `sheet_spacing_check`).

## Demonstration
**Synthetic only.** The tests (`tests/test_sheet_switch_finder.py`) build concentric sheets and meshes that hop
by a known number of sheets at a known column. No real scan data is included or downloaded, no public trace with a
documented switch was confirmed, and no First Letters scroll was used. Do not treat output on real data as evidence
until it has been checked by hand on spots found in a documented trace.

## v0.2: steps in LOCAL pitches

Evidence: PR #17 finding 5 (the finder reported steps in units of a 17 voxel pitch where 9.5 was measured) and the crushed
phantoms (spacing varies up to 3x round one turn). The offset of the mesh from the tracked sheet, the track gate and the step test
now use the local pitch at each point (`tools/common/local_pitch.py`, measured on the tilt-filtered normals, running median over
`--pitch-smooth-points` = 9 points along the run, because beside a hop the profile straddles two sheets and reads about 2x). On a
phantom with a 3x spacing field a planted +1 sheet switch is 1.0 pitch in both the crushed and the wide sector; with one pitch per height
it was missed (0.35) or read 1.59 with confidence 0. `--global-pitch` restores the old behaviour (identical output). NOT fixed:
the deliberate real-data break of PR #17 task 6 is still not flagged at confidence >= 0.3 (a break-specific entry appears at z=2600
col 123 with confidence 0.0; `tests/test_v2_local_pitch.py::test_ssf_real_break_is_flagged_and_the_original_is_not`, xfail).

| flag | default | meaning |
|---|---|---|
| `--global-pitch` | off | one CT pitch per height (old) |
| `--pitch-prominence-frac`, `--pitch-window-pitches`, `--pitch-cv-max`, `--pitch-ac-full`, `--min-pitch-confidence` | as `sheet_spacing_check` | local pitch estimator (see there) |
| `--pitch-smooth-points` | 9 | running median of the local pitch along each run (odd; 1 = off) |
