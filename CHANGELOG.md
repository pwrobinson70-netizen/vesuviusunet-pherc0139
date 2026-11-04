# Changelog

## 0.1.0 (unreleased)
- `groundtruth_score` / `vun-groundtruth` (brief 25): scores `trace_auditor`, `sheet_switch_finder`, the CT pitch estimate, `umbilicus_finder` and `winding_sweep` against the 40 human-verified PHerc. Paris 4 (Scroll 1) patches, the published centre line and the absolute winding annotations; first real-data false-alarm rate and centre error (`docs/REALDATA_GROUNDTRUTH.md`, `results/`, `tests/test_groundtruth.py`). AI-assisted (Claude Code and Claude), human-directed.
- `patch_merger` / `vun-merge`: gated merge of overlapping tifxyz patches with a seam report (`tools/patch_merger`).
- `tools/winding_sweep` (`vun-sweep`): umbilicus -> ray crossings -> one sheet_tracer patch per winding -> trace_auditor verdict -> manifest.
- Packaging: `pyproject.toml` with console scripts `vun-spacing`, `vun-switch`, `vun-umbilicus`, `vun-audit`,
  `vun-phantom`, `vun-ink` (thin wrappers in `vun_tools/cli.py`; no existing file moved or renamed).
- Docs: `docs/TOOLS.md`, `docs/NOVEMBER_WRITEUP_DRAFT.md`, `CITATION.cff`.
- Tools collected from earlier branches: `sheet_spacing_check`, `sheet_switch_finder`, `umbilicus_finder`,
  `ink_infer`, `trace_auditor`, `phantom_scroll` (with benchmark), the tifxyz/umbilicus format check
  (`docs/FORMATS.md`) and the round-1 review fixes (`docs/REVIEW_ROUND1.md`).
- Not in this release: the ink end-to-end phantom test and the R3 fix (PR #12, `tool/ink-e2e`).
