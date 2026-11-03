# TOOL_NOTES

- **What:** `sheet_switch_finder`: for ONE tifxyz mesh plus the CT, lists the places where the trace hops
  to a neighbouring sheet (horizontal along each requested height, and vertical between heights), with
  direction, size in pitches, confidence, grid row/col and voxel x/y/z; text summary and optional overlays.
  CPU-only, MIT.
- **Where:** `tools/sheet_switch_finder/` (code, README with method/constants/limits, `requirements.txt`, a copy
  of the spacing tool's); tests in `tests/test_sheet_switch_finder.py`.
- **Reuse, no edits:** imports `ssc_io` and `sheet_spacing_check` (cut line, normals, CT pitch, Otsu on-sheet
  test). No existing file was changed (SHA256SUMS.txt, conftest, ci.yml, the spacing tool). The new files are not
  listed in `SHA256SUMS.txt`; extend it separately if you want them covered.
- **Tests (synthetic only):** one sheet = zero switches; outward hop = one switch at the index (+/-2), also
  as a hard jump; inward; inward-then-back = two opposite; two-sheet hop = step ~2, double flag; noise/wobble
  below 0.4 pitch = zero; dark gap (whole line, and a dip that returns) = off-sheet, not switches; vertical
  patch; bad paths, mismatched grids, bad parameters, heights outside the mesh z range / the CT; CLI end to end.
- **Decisions to review (method deviations or fillings-in):**
  1. Tracking continuity is measured *across* the sheet and a refused jump (> 0.5 pitch) = lost point; tracking
     restarts after 10 lost or 10 consecutive off-sheet points. Spec said only "nearest the previous position".
  2. Normals tilted > 25 deg from the running-median normal are dropped, and normals are not taken across a
     hard jump (4x the usual spacing). Without this a hop (a ramp through the gap) breaks the tracker.
  3. Run-splitting gap is 3.5 pitches (not the spacing tool's fixed 20 voxels), so a one-sheet jump is not cut.
  4. "Stays K points on both sides" is implemented as: all K median-smoothed points on each side lie on their own
     side of the midpoint level, and the K-medians differ by the step.
  5. Outward = away from the line's centroid (or `--centre-x/y`); `--orientation grid` for the raw normal.
  6. Offsets are relative to each height's own anchor (see README, limits): a whole-line shift is invisible.
  7. Vertical test = stretches of >= K columns with a step in the window between two requested heights.
- **Not done:** no real-data demonstration; no public trace with a known switch was confirmed. No First Letters
  scroll was used or mentioned.
- **Dependencies:** only the spacing tool's `requirements.txt` (numpy, scipy, tifffile, pillow, zarr) plus pytest.
