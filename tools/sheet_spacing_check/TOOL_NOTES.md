# TOOL_NOTES

- **What:** `sheet_spacing_check`: flags shared / skipped / off-sheet places between two
  tifxyz meshes that should be adjacent scroll turns. CPU-only, MIT.
- **Where:** `tools/sheet_spacing_check/` (code, README, own `requirements.txt`); tests in `tests/`.
- **Existing files untouched.** The repo's `requirements.txt` and `SHA256SUMS.txt` are unchanged;
  the new files are not listed in `SHA256SUMS.txt`, so extend that list separately if you want them covered.
- **Tests:** synthetic only: clean ~1.0 at one pitch, shared ~1.0 for the same mesh, skipped ~1.0 at
  two pitches, dark-gap mesh fails on-sheet, bad paths, mismatched grids, height outside z range,
  and an end-to-end CLI run over zarr and PNG input.
- **Not done:** no real-data demonstration; adjacency of public segment pairs was not confirmed.
  No First Letters scroll was used or mentioned.
- **Decisions to review:** area uses measured mesh geometry, with `meta.json` scale only cross-checked;
  per-point missing CT pitch falls back to the height median; mesh-derived pitch = median pair distance.
