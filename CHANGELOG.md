# Changelog

## 0.1.0 (unreleased)
- `tools/groundtruth_score` (`vun-negatives`): four deliberately broken copies (shift-half, shift-full, switch-mid, scramble) of the 40 verified Scroll 1 patches, a minimal panel scorer, and the real-data 2x2 (false alarms x detection) in `docs/REALDATA_2X2.md`. AI-assisted (Claude Code and Claude), human-directed.
- `tools/surface_agreement` (`vun-surface`): a second opinion from a learned surface prediction. Per trace point: prediction value, offset to the nearest prediction ridge, ON-PREDICTED-SHEET / OFF / NOT JUDGED; per-height 2x2 table against our CT-peak verdict with the disagreeing points listed; overlay PNGs; `fake_prediction.py` and `break_trace.py` helpers.
- `vun-audit --vc3d-folder PROJECT [--volume VOL]`: audits every tifxyz patch of a VC3D project folder and writes `verdict.json` / `verdict.txt` into each patch folder plus `verdict_summary.txt/.csv` at the root; nothing else is written (`tools/trace_auditor/vc3d_handoff.py`).
- Windows: CI job on `windows-latest`, `.gitattributes`, `scripts/judge_patch.ps1`, `docs/WINDOWS.md`.
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
