# Changelog

## 0.1.0 (unreleased)
- `tools/texture_judge` (`vun-texture`): fibre-texture continuity judge (surface render at 0 / +-k voxels, structure-tensor orientation + coherence, orientation jumps, texture presence, layer agreement; ON-SHEET-TEXTURED / BREAK / BLURRED / NOT JUDGED per window and per cut line). `tools/judge_panel` (`vun-panel`): every judge on one trace aligned to the same cut lines and column windows, panel verdict and explicit disagreements, plus an agreement table (texture judge vs auditor). `phantom_scroll`: optional anisotropic fibre texture (`--fibre`, default off, old output byte-identical).
- `tools/label_drift` (`vun-drift`): per-pixel signed distance of a label on a tifxyz surface to the nearest CT sheet peak, on-sheet test, sheet thickness, per-component verdicts (OK / SHIFTED / OFF-SHEET / MIXED), drift map, optional corrected surface.
- `patch_merger` / `vun-merge`: gated merge of overlapping tifxyz patches with a seam report (`tools/patch_merger`).
- `tools/winding_sweep` (`vun-sweep`): umbilicus -> ray crossings -> one sheet_tracer patch per winding -> trace_auditor verdict -> manifest.
- Packaging: `pyproject.toml` with console scripts `vun-spacing`, `vun-switch`, `vun-umbilicus`, `vun-audit`,
  `vun-phantom`, `vun-ink` (thin wrappers in `vun_tools/cli.py`; no existing file moved or renamed).
- Docs: `docs/TOOLS.md`, `docs/NOVEMBER_WRITEUP_DRAFT.md`, `CITATION.cff`.
- Tools collected from earlier branches: `sheet_spacing_check`, `sheet_switch_finder`, `umbilicus_finder`,
  `ink_infer`, `trace_auditor`, `phantom_scroll` (with benchmark), the tifxyz/umbilicus format check
  (`docs/FORMATS.md`) and the round-1 review fixes (`docs/REVIEW_ROUND1.md`).
- Not in this release: the ink end-to-end phantom test and the R3 fix (PR #12, `tool/ink-e2e`).
