# benchmark_ci: many-seed benchmark with confidence intervals

Measurement only; no tool is changed and no threshold is swept (that is `tools/calibration`).

```bash
python tools/benchmark_ci/run.py --seeds 0-19 --sizes 192            # 80 jobs, ~25 min on 4 cores; resumable (cache in results/_cache)
python tools/benchmark_ci/run.py --seeds 0-4 --sizes 128,256         # size sensitivity, merged into the same CSV
python tools/benchmark_ci/summarise.py tools/benchmark_ci/results/runs.csv --md docs/BENCHMARK_CI.md --png-dir docs/benchmark_ci
```

`run.py`: one job per (size, deformation round/mild/crushed/merged, seed). Builds the phantom once, then runs
`phantom_scroll/benchmark.py` (switch finder, umbilicus finder, spacing check), `trace_auditor/score_on_phantoms.py`
(verdicts on true and bad traces, estimated centre by default) and `sheet_tracer/score_on_phantoms.py` (3 patches, exact centre).
One CSV row per job in `results/runs.csv`; a failed job is recorded with status `error`, never dropped (exit code 1).
`summarise.py`: mean, median, 95% bootstrap CI of the mean (1000 resamples), min, max, n per metric and deformation; flags metrics
whose CI contains the auditor's pass threshold (spacing `min_clean_fraction` 0.8) and counts single runs on the wrong side of it.
Needs numpy; matplotlib only for the PNGs.
