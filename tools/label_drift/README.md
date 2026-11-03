# label_drift: do the labels sit on the papyrus?

Ink labels are drawn on a flattened surface. If that surface is a little off the true sheet, the label is too, and a
model trained on it learns the wrong depth. `label_drift` measures that, per labelled pixel, from a tifxyz surface, a CT
volume and a label image in the surface grid (an ink mask, or any label).

```bash
pip install -r tools/label_drift/requirements.txt
python tools/label_drift/label_drift.py SURFACE.tifxyz LABEL.png --zarr volume.zarr --out-dir drift/ \
    [--write-corrected fixed.tifxyz]          # or --png-dir slices/ --png-pixel-um 45.532 --voxel-size-um 45.532
```

`LABEL`: PNG / TIFF / NPY, same (rows, cols) as the surface grid; a pixel is labelled if it is `> --label-min-value`
(default 0). Output in `--out-dir`: `drift.png`, `drift.npz`, `components.csv`, `report.json`, `summary.txt` (also printed).
Exit code 0 on success (whatever the verdicts), 2 on bad input. CPU only; same input and flags give identical files
(`drift.npz` is identical in content; zip members carry timestamps).

## What is measured (every labelled pixel = one grid node)

1. **Drift.** The CT slice of the node (`floor(z / ct_scale)`) is sampled along the **in-plane normal** (the horizontal
   part of the 3-D surface normal `d/drow x d/dcol`) over +-`--profile-halflen-vox`, smoothed and detrended with the shared code of
   `tools/common/local_pitch.py`; the sheet peaks are found with `--peak-prominence-frac` (as in the spacing tool) and refined
   to sub-sample by a parabola. **Drift = signed position (voxels) of the peak nearest to the surface point; positive = the
   peak lies along +normal.** In local pitches: divided by the local pitch of `local_pitch.py` at that node (the
   component's median pitch where it cannot be estimated, e.g. confidence below `--min-pitch-confidence`).
   The distance is in the slice plane, so it is the true normal distance times `1/sqrt(1 - nz^2)`; nodes with `nz^2 >
   --max-nz2` (default 0.5) are not measured.
2. **On-sheet.** The same test as `sheet_spacing_check`: the CT tile (cut line of the mesh + labelled points + the same padding)
   is thresholded with Otsu, and the point is on-sheet if the maximum within `--onsheet-radius-px` is above it.
   Note it is a property of the *labelled point*, not of the peak.
3. **Thickness.** FWHM of the nearest peak (width at half its prominence, on the smoothed profile) with the profile smoothing
   removed in quadrature (`--thickness-raw` keeps it). It is a measure of the CT, not the label; on blurred scans it is the blur.

Pixels that cannot be measured are counted by reason, never filled: invalid grid cell, surface too tilted, no CT slice
(`--z-snap-vox` allows the nearest available slice up to that far in z; the node is then sampled in a slice that is not its own,
an approximation that is only reasonable when the sheet is close to vertical), no peak in range.

## Verdict per component (connected labelled pixels, `--connectivity`)

`med` = median drift in pitches, `spread` = 1.4826 MAD of the drift in pitches, `off` = off-sheet fraction of measured pixels.

| verdict | rule (defaults) |
|---|---|
| NO-DATA | fewer than `--min-measured` (5) measured pixels |
| OK | `spread <= 0.15` (`--consistent-spread-pitch`), `abs(med) <= 0.10` (`--ok-pitch`), `off <= 0.20` (`--mixed-off-frac`) |
| SHIFTED | `spread <= 0.15` and `0.10 < abs(med) <= 0.40` (`--max-shift-pitch`): a consistent offset; **recommended offset** = `med` |
| OFF-SHEET | else, if `off >= 0.50` (`--off-sheet-frac`) or `abs(med) > 0.40` (the label sits in the gap between sheets) |
| MIXED | everything else (part of the component is fine, part is not, or the offset varies) |

SHIFTED deliberately ignores the off-sheet fraction: a label 0.3 pitch off a thin sheet is usually also "off-sheet" by the
Otsu test, and the point of the verdict is that one offset fixes it. The component table has, for every component: pixels,
valid, measured, bounding box, mean / median / max-abs drift (voxels and pitches), spread, off-sheet fraction, mean
thickness, median pitch, and the **recommended normal offset** (voxels and pitches): *the move of the surface along the
normal that re-centres the label* (equal to the median drift, whatever the verdict; only SHIFTED and OK say it is safe).

## Outputs

* `drift.png` (`--png-scale`): label grid; red = peak along +normal, blue = along -normal, white = 0, colour scale +-`--png-range-pitch`;
  off-sheet pixels darker; magenta = labelled but not measured; grey = unlabelled.
* `drift.npz`: `drift_vox`, `drift_pitch`, `pitch_vox`, `pitch_confidence`, `thickness_vox`, `onsheet` (1 / 0, -1 not measured),
  `component` (0 = none), `measured`, `slice_index`, all in label-grid space (NaN = not measured).
* `--write-corrected DIR`: a tifxyz copy where each labelled, measured node with `abs(drift) <= --correct-max-pitch` (0.5) is moved
  to its nearest peak (along the in-plane normal, z unchanged). **Never overwrites**: it refuses the input folder and any
  non-empty folder. Only labelled nodes move, so an unlabelled neighbour is left where it was (the surface gets a step at the
  label edge when the offset is large); to move the whole surface, label every node. The meta.json gains a `label_drift` entry.

## Limits (read these)

* A trace that jumps a **whole** sheet lies on a sheet: drift ~0, verdict OK. That is `sheet_switch_finder` / `trace_auditor`'s job.
  A trace that drifts partway into the gap reads OFF-SHEET.
* The nearest peak is the nearest *detected* peak: where sheets are crushed together or faint, "nearest" may be the wrong sheet,
  and a drift larger than about half a pitch is not a measurement of a shift. On real data the peak prominence matters
  (`--peak-prominence-frac`, see PR #17 for the same effect on the pitch).
* In-plane normals: needs steep surfaces (scroll sheets are near vertical). Orientation is the grid's, so the sign is only
  meaningful together with the tifxyz orientation.
* The thresholds were set on phantoms (`tools/phantom_scroll`), not calibrated on real labels.
