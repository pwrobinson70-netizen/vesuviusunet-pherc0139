# calibration: where are the trace-checking tools reliable?

Replaces guessed constants with measured operating ranges, on `tools/phantom_scroll` phantoms (synthetic, exact truth).
Results: `docs/OPERATING_RANGE.md`, curves in `docs/calibration/`, raw numbers in `tools/calibration/results/`.

```bash
pip install -r tools/calibration/requirements.txt
python tools/calibration/run_grid.py --jobs 4                 # grid -> results/grid.csv (about 2 h on 4 cores; resumable)
python tools/calibration/sweep_thresholds.py --jobs 4         # one threshold at a time -> results/sweeps.csv
python tools/calibration/report.py                            # PNGs + docs/OPERATING_RANGE.md + results/proposed_defaults.md
```

Grid flags (all of them, no hidden constants): `--seeds 0-19 --steps 2,5,10,20 --pitches 8,15,30,60 --deforms round,mild,crushed,merged
--size 192 --cache DIR --jobs N --fresh --auditor-centre estimated|truth`. Verdict thresholds of the standalone tools
(`min_conf`, `min_clean`, `col_tol`, `centre_tol_pitch`) are fields of `calib.Cfg`. Every tool threshold is swept over the
values listed in `sweep_thresholds.SWEEPS` (edit the list or restrict with `--only ssf.k_points`).

## Phantom construction per cell
Sheet FWHM = 0.27 x pitch (min 2 vox), r0 = clip(0.5 x pitch, 6, 14), 4 turns. Deformations are the presets of
`phantom_scroll/benchmark.py` (`crushed` = its `bad`); the squeeze of `merged` sits between sheets 1 and 2 if they fit,
else 0 and 1. The tested sheets are 1..3 (A = sheet 1) when sheets 1..3 fit in the slice, else 0..2 (pitch >= 30 at 192^3);
any trace with fewer than 30% valid grid cells is skipped. Planted faults: three switches (hard hop outward, a ramp
inward 16 vox wide, a hard hop outward) and the bad pairs skipped / shared / off-sheet of phantom_scroll.

## CSV
One row per tool run: `seed, grid_step, pitch, deform, size, tool, kind (true|bad), case, expected, verdict,
verdict_correct, clean_fraction, recall, false_switches, centre_err, col_err, valid_frac, runtime_s, extra (JSON)`.
`recall` is the share of the 5 heights at which a planted switch was found (switch finder) or the share of OK slices
(umbilicus finder, whose `verdict_correct` is the share of slices whose OK / LOW flag was right). `centre_err` is the mean
distance of the smoothed centre line to the truth (voxels). `col_err`: median column error of found switches.

## Limits
Phantoms are idealised (see phantom_scroll README). The 0.95 criterion is on balanced correctness over this case mix;
it says nothing about real scrolls. Pitch 60 at 192^3 tests only the first sheets. Deleting `cache/` is harmless.
