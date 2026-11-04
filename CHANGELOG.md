# Changelog

## 0.1.0 (unreleased)
- `vun-densify` (`vun_tools/densify.py`, brief 27 part A): bilinear densification of tifxyz grids to a target cell spacing, never across invalid cells; `scale` updated, `densify_note` in meta.json; phantom tests. Densifying alone does not fix the CT checks (`docs/PANEL_V2.md`). AI-assisted (Claude Code and Claude), human-directed.
- `tools/judge_panel` (`vun-panel2`, brief 27 part B): prediction-first panel: required vote = surface-prediction on-sheet fraction >= T (0.415, chosen on the tune set only), advisory CT votes that fail a trace only if 2 of 3 agree; held-out 2x2 on the second verified set (`testdata/pherc_paris4_groundtruth_b`, `results/negatives_b`), results `results/panel_v2_*.csv`, `docs/PANEL_V2.md`. AI-assisted (Claude Code and Claude), human-directed.
- `tools/umbilicus_finder/umbilicus_from_pred.py` (`vun-umbilicus-pred`, brief 27 part C): centre from the m7 prediction fetched from the public zarr; compared with the published line on Brief 25's 20 heights (`results/centre_from_pred_*.csv`).
- `groundtruth_score` / `vun-groundtruth` (brief 25): scores `trace_auditor`, `sheet_switch_finder`, the CT pitch estimate, `umbilicus_finder` and `winding_sweep` against the 40 human-verified PHerc. Paris 4 (Scroll 1) patches, the published centre line and the absolute winding annotations; first real-data false-alarm rate and centre error (`docs/REALDATA_GROUNDTRUTH.md`, `results/`, `tests/test_groundtruth.py`). AI-assisted (Claude Code and Claude), human-directed.
- `tools/groundtruth_score` (`vun-negatives`): four deliberately broken copies (shift-half, shift-full, switch-mid, scramble) of the 40 verified Scroll 1 patches, a minimal panel scorer, and the real-data 2x2 (false alarms x detection) in `docs/REALDATA_2X2.md`. AI-assisted (Claude Code and Claude), human-directed.
- `tools/surface_agreement` (`vun-surface`): a second opinion from a learned surface prediction. Per trace point: prediction value, offset to the nearest prediction ridge, ON-PREDICTED-SHEET / OFF / NOT JUDGED; per-height 2x2 table against our CT-peak verdict with the disagreeing points listed; overlay PNGs; `fake_prediction.py` and `break_trace.py` helpers.
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
﻿# Changelog

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
ï»¿# Changelog

## 0.1.0 (unreleased)
- `groundtruth_score` / `vun-groundtruth` (brief 25): scores `trace_auditor`, `sheet_switch_finder`, the CT pitch estimate, `umbilicus_finder` and `winding_sweep` against the 40 human-verified PHerc. Paris 4 (Scroll 1) patches, the published centre line and the absolute winding annotations; first real-data false-alarm rate and centre error (`docs/REALDATA_GROUNDTRUTH.md`, `results/`, `tests/test_groundtruth.py`). AI-assisted (Claude Code and Claude), human-directed.
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
