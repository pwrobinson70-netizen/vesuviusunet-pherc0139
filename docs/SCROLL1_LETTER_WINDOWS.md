# Scroll 1 letter-test windows (brief 30 Part A), fixed before any scoring

PHerc. Paris 4 (Scroll 1), public data, CC BY-NC 4.0. This file and the two CSVs it names were committed
BEFORE any Part C scoring, so the windows could not be chosen to fit a result. Numbers and pixel corners
only: no image of the ink is in this repository (Scroll 1 terms: no transcription and no full-resolution
text images until 25 June 2027).

## Rule (fixed 5 Nov 2026, before the picture was sampled)

- **Source:** segment `20260623142658-w028-037` (windings 28 to 37, named readable on the data page), its
  published ink picture on the 2.4 um grid of volume `20260411134726`.
- **Letter windows:** the 3 non-overlapping 2 x 2 cm squares with the highest mean published ink, each at
  least 90% valid.
- **Blank window:** the 2 x 2 cm square with the lowest mean ink, at least 90% valid, at least 2 cm (gap)
  from every letter window.
- **Valid** = pixel value above 0 (the published picture is 0 outside the traced surface; 10.1% of sampled
  pixels were exactly 0).
- **Sampling:** every 3rd 1024 x 1024 tile in each direction (928 tiles, 89 MB, read by HTTP range requests),
  so window positions are on a 7.37 mm grid. Script: `scripts/pick_windows_scroll1.py`.

## Result (laptop run, 5 Nov 2026)

Ink picture: `PHercParis4-20260623142658-2.4um-0.22m-78keV-volume-20260411134726-20260417190342-new_canon_autoresearch_recipe-tile256-stride128.tif`,
797 MB, ETag `c04bac5c2b65b80ee9922b6486c7975f-96`, 176800 x 46400 px (42.4 x 11.1 cm).

| Window | Rows (px) | Columns (px) | Mean ink (0 to 1) | Valid share |
|---|---|---|---|---|
| letter1 | 33792-42125 | 36864-45197 | 0.4925 | 1.000 |
| letter2 | 6144-14477 | 138240-146573 | 0.4891 | 1.000 |
| letter3 | 3072-11405 | 73728-82061 | 0.4690 | 1.000 |
| blank | 30720-39053 | 125952-134285 | 0.1396 | 1.000 |

Across the 648 valid candidate windows the mean ink ran from 0.1396 to 0.4925 (median 0.2407). The blank
window is the lowest-ink window, not an ink-free one: the published picture is a model output with a
non-zero background on papyrus.

Files: `results/scroll1_letter_windows.csv` (the table above with file key, size and ETag) and
`results/scroll1_letter_windows_tiles_sha256.csv` (offset, size and sha256 of every tile read).

## Limits

- One segment, one published model output (not hand labels); "dense ink" here means high model output.
- Window positions are limited to the 7.37 mm sampling grid.
- Part C (scoring) has not been run.

AI-assisted (Claude Code and Claude), human-directed.
