# groundtruth_score: how often do our checks accept a broken trace, and reject a verified one?

AI-assisted (Claude Code and Claude), human-directed. Public data only: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0.

| file | what |
|---|---|
| `make_negatives.py` (`vun-negatives`) | four deliberately broken copies of each of the 40 verified patches: `shift-half`, `shift-full`, `switch-mid`, `scramble`. Refuses to run unless the README.md in the ground-truth folder says "PHerc. Paris 4". Fixed seed; writes `manifest.csv` (pitch, signed shift in voxels per patch). |
| `score.py` | the minimal scorer: runs the panel (trace_auditor default and `--global-pitch`, sheet_switch_finder, sheet_spacing_check, surface_agreement) on the 40 originals and the 160 copies; one CSV row per case. |
| `analyse.py` | 2x2 per tool and for the panel, Wilson intervals, per-kind detection, threshold study, AUC of the surface prediction. |
| `validity.py` | do the copies sit where they were meant to (CT-peak fraction)? |

    vun-negatives testdata/pherc_paris4_groundtruth results/negatives
    python tools/groundtruth_score/score.py testdata/pherc_paris4_groundtruth results/negatives --out results/groundtruth_panel_scores.csv
    python tools/groundtruth_score/analyse.py results/groundtruth_panel_scores.csv --sweeps results/threshold_study --out-dir results

Results and the numbers behind them: `docs/REALDATA_2X2.md`. Outputs under `results/` are derived and regenerable (about 25 s for the scoring on 4 cores).
