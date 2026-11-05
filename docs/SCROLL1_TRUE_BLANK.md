# Scroll 1 true-blank test: rule, fixed before any label pixel is read

Question: the letter test's blank window (`docs/SCROLL1_LETTER_TEST.md`) agreed with the published ink picture at r 0.301, where
the rule needed under 0.2. Was that faint ink in a window that was only the LOWEST-ink window, or do two ink models on the same
scan always agree about that much on bare papyrus? This test answers it on papyrus that people checked and labelled as empty.

Written 5 Nov 2026, committed before `scripts/pick_trueblank_scroll1.py` reads any label pixel. Public data, CC BY-NC 4.0;
numbers only, no image (Scroll 1 terms).

## Data

The 8 Scroll 1 segments with hand labels on the 2.4 um grid of volume 20260411134726, in this order: 20230702185753,
20230929220926, 20231007101619, 20231012184424, 20231016151002, 20231031143852, 20231106155351, 20231210121321.
Labels: `ink-labels/2.4um-volume-20260411134726/20260918/{inklabels,supervision}.zarr` (OME-Zarr v3; level 0 is exactly the size
of each segment's published 2.4 um ink picture, checked from the metadata on 5 Nov).

## Window choice (from the labels only, at OME level 4 = 38.4 um)

- Candidates: 2 x 2 cm squares on a 2 mm grid, fully inside the label array.
- Checked share = fraction inside `supervision` > 0; ink share = fraction inside `inklabels` > 0.
- **True blank:** checked share >= 0.95 and ink share = 0; of those, the one farthest from any labelled ink.
- **Label-ink window (positive control):** the highest ink share among windows with checked share >= 0.95.
- Segments are taken in the order above until 3 have both; each gives one true blank and one label-ink window.
- Output: one window CSV per segment, recorded before scoring.

## Measurement

`scripts/letter_test_c1_scroll1.py` with its committed settings, unchanged: our ink picture from the published 3-D ink zarr
(level 1, offsets -2..+2) along the segment's 2.4 um trace, against the segment's published 2.4 um ink picture, Pearson r and
top-10% IoU over the window. Traces: original and shift-full only (`--kinds shift-full`; the scramble is not needed for this
question and costs about 8 GB per window).

## Readout (fixed now)

1. **Validity:** a label-ink window is valid if its r(original) >= 0.5 and >= 2 x its shift-full r. Fewer than 2 valid of 3:
   INCONCLUSIVE, nothing below is concluded.
2. **Primary number:** the median r(original) over the true blanks.
   - **Under 0.2:** checked-empty papyrus gives little agreement, so the letter test's blank (0.301) most likely held faint ink;
     the absolute blank condition stands for future tests.
   - **0.2 or more:** two ink models on the same scan agree at 0.2 or more on papyrus people checked and found empty; the
     absolute blank condition was too tight for this comparison, and future tests use a relative blank condition.
3. The letter test's official result (FAIL on the blank condition) is not changed by this test either way.

## Limits

- Hand labels mark ink people were confident about; "checked and empty" is not proof that no ink exists there.
- The published ink model may have been trained on these labels, which can raise its agreement with them; it does not change
  what the blank windows measure (agreement between two model outputs where neither labels show ink).
- One scroll, up to 3 segments.

AI-assisted (Claude Code and Claude), human-directed.
