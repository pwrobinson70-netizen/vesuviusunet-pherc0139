# judge_panel: the prediction-first panel (panel_v2)

AI-assisted (Claude Code and Claude), human-directed. Public data only: PHerc. Paris 4 (Scroll 1), CC BY-NC 4.0. Results and the reading of them: `docs/PANEL_V2.md`.

| file | what |
|---|---|
| `panel_v2.py` (`vun-panel2`) | verdict = REQUIRED vote (surface-prediction ON-PREDICTED-SHEET fraction >= T) + ADVISORY CT votes (trace_auditor local-pitch, trace_auditor `--global-pitch`, sheet_switch_finder) that can fail a trace only if 2 of 3 agree. `--batch GT NEG --out raw.csv` writes the raw votes of the 40 originals + 160 broken copies. |
| `densify_tree.py` | densified copies (1 voxel cells) of a ground-truth sample and its broken copies (inputs untouched; slices and predictions are symlinked) |
| `evaluate_v2.py` | chooses T on the tune set only (Youden J of the full panel), reports the held-out 2x2, per-kind detection, misses, AUC |
| `densify_effect.py` | NOT JUDGED and CT 2x2 on coarse vs densified traces |

    vun-negatives testdata/pherc_paris4_groundtruth results/negatives                     # set A copies (committed)
    vun-negatives testdata/pherc_paris4_groundtruth_b results/negatives_b                 # set B copies, same script and default seed (committed)
    python tools/judge_panel/densify_tree.py testdata/pherc_paris4_groundtruth results/negatives /tmp/dense_a
    python tools/judge_panel/densify_tree.py testdata/pherc_paris4_groundtruth_b results/negatives_b /tmp/dense_b
    vun-panel2 --batch /tmp/dense_a/gt /tmp/dense_a/neg --out results/panel_v2_raw_set_a.csv
    vun-panel2 --batch /tmp/dense_b/gt /tmp/dense_b/neg --out results/panel_v2_raw_set_b.csv
    python tools/judge_panel/evaluate_v2.py --tune results/panel_v2_raw_set_a.csv --heldout results/panel_v2_raw_set_b.csv --out-dir results

Densified traces make the CT checks count 20x more cut-line points per voxel; `vun-panel2` therefore multiplies their point-count parameters by the
densify factor it finds in the trace's `meta.json` (`--point-scale` overrides). Without that the switch finder fails 38 of 40 verified patches.
