# trace_repair: repair a tifxyz trace beyond a sheet switch

```bash
python tools/trace_auditor/trace_auditor.py trace/ --zarr volume.zarr --out-dir audit/
python tools/trace_repair/trace_repair.py trace/ --audit audit/audit.json --zarr volume.zarr --out trace_fixed/
python tools/trace_auditor/trace_auditor.py trace_fixed/ --zarr volume.zarr --out-dir audit2/   # judge it again
```

For each switch in the audit (switch_finder switches and winding-number jumps with confidence >= `--min-switch-confidence`)
every point beyond it in the growth direction is re-snapped onto the sheet tracked before the switch: predicted from the
repaired neighbour one step back (the original step with its component along the sheet normal removed), then snapped to
the nearest bright-sheet peak along the structure-tensor normal within +/- `--snap-pitch` (1.0) x pitch
(`sheet_tracer.Tracer`, imported). The chain runs along columns for horizontal switches / jumps and along rows for vertical
switches; `--origin low|high` says which grid side the trace was grown from. A double switch needs nothing special: the
chain starts before the first one. Snaps that disagree with the neighbouring lines' median offset by more than
`--outlier-pitch` (0.35) x pitch are replaced. `--out` must be a new directory; the input is never touched. With no switch to
repair the input files are copied byte for byte. `repair_summary.json` in `--out` is the diff summary (points moved,
max / median move, unsnapped points, outliers replaced).

A reported switch is repaired only if the repair CONFIRMS it (REVIEW_ROUND2 R1): some point within `--margin` + 3 lines of
the reported line (and within `--confirm-orth` (6) lines of where the audit saw it, when it says) must move by at least
`--confirm-pitch` (0.5) x pitch; a real hop is about 1 pitch, a false alarm or a mislocated report is only nudged. Unconfirmed
switches are left alone and listed in `repair_summary.json` (`unconfirmed`, with the largest move seen); with none
confirmed the input is copied byte for byte and the verdict is NOT changed. Before this, a false alarm was "repaired" by a
sub-voxel to 1-voxel nudge that flipped the verdict FAIL to PASS with the truth unchanged, and a mislocated report carried a
leak down the trace.

## Limits

- The growth side must be given (`--origin`); the audit does not know it. Wrong side = the wrong part is trusted.
- The repaired part keeps the original step LENGTH (arc length), not the original angular step: on a trace whose grid is
  angle-spaced rather than arc-spaced (the phantoms) the repaired points sit at the same places along the sheet only up to a
  growing shift; they are on the right sheet and continuous. Judge with the auditor, not by comparing grids.
- It repairs what the auditor reports. A switch the auditor misses (end zones, unjudged heights) is not repaired.
- Needs the volume in memory (same as sheet_tracer). Synthetic evidence only.
