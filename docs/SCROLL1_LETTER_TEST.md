# Scroll 1 letter test (brief 30 Part C, stage C1): FAIL on the blank condition

**FAIL.** All 3 letter windows meet the letter condition (r 0.590, 0.640, 0.700 against the published ink picture, each at
least 4x its best broken copy), but the blank window does not: r 0.301 where the rule needed under 0.2 (or IoU 0.145 where it
needed under 0.1). The rule was fixed before any real data; a FAIL is reported, not retuned. Source: `results/scroll1_letter_test_c1.csv`.

PHerc. Paris 4 (Scroll 1), public data, CC BY-NC 4.0. Numbers only: no image of the ink is in this repository (Scroll 1 terms:
no transcription and no full-resolution text images until 25 June 2027). Windows: `docs/SCROLL1_LETTER_WINDOWS.md`, committed
before scoring (PR #40). Script: `scripts/letter_test_c1_scroll1.py`.

## What was compared

- **Ours:** `vun-ink-sample` on the published 3-D ink prediction
  (`representations/predictions/ink-3d/20260411134726-ink3d-20260926084000-student-v12A-25000-c7766be9-L1.zarr`, level 1 = 9.6 um),
  along the segment's own 2.4 um trace (`20260623142658-on-20260411134726-2.4um.tifxyz`), max over normal offsets -2..+2 at level 1 (+-19 um).
- **Reference:** the segment's published 2-D ink picture
  (`...-2.4um-...-20260411134726-20260417190342-new_canon_autoresearch_recipe-tile256-stride128.tif`), averaged 4 x 4 to the same 9.6 um grid.
  The trace grid is exactly 20 picture pixels per cell in both directions (checked in every run).
- **Broken copies** (`tools/groundtruth_score/make_negatives.py`, seed 20261104): shift-full and shift-half by the median CT pitch of the
  40 verified patches (8.75 voxels at 9.6 um = 35 voxels at 2.4 um), and scramble.
- **Agreement:** Pearson r over the whole 2 x 2 cm window (4,338,889 pixels, 100% covered in every case), and IoU of each image's top 10%.

## Readout rule and its one amendment

Fixed in brief 30 before data: PASS if in at least 2 of 3 letter windows r(original) >= 0.5 AND >= 2 x the best broken copy AND panel_v2
accepts the original and rejects 2 of 3 copies; and the blank window has r < 0.2 or IoU < 0.1.

**Amendment (Pedro, 5 Nov 2026, before any real data):** "best broken copy" = the better of shift-full and scramble; shift-half is
reported as a diagnostic only. Reason: on a planted test the half-shifted copy kept the real signal (r 0.97), because half a Scroll 1
sheet gap (about 42 um) is barely wider than half a sheet plus the sampling depth.

## Results

| Window | r original | r shift-full | r scramble | best broken | ratio | letter / blank condition | r shift-half (diagnostic) |
|---|---|---|---|---|---|---|---|
| letter1 | 0.590 | 0.048 | 0.031 | 0.048 | 12.3x | met | 0.292 |
| letter2 | 0.640 | 0.154 | 0.022 | 0.154 | 4.2x | met | 0.388 |
| letter3 | 0.700 | 0.093 | 0.031 | 0.093 | 7.5x | met | 0.476 |
| blank | 0.301 (IoU 0.145) | 0.070 | 0.019 | 0.070 | - | **not met** (needed r < 0.2 or IoU < 0.1) | 0.174 |

IoU of the top 10% (original): letter1 0.422, letter2 0.447, letter3 0.480, blank 0.145.

**panel_v2** (stage C2) was not run: the blank condition already decides the outcome.

## Reproducibility

Three runs of the same script: laptop A (letter1, blank; all copies), a RunPod CPU pod (letter2, letter3; killed by its memory limit
during letter3's scramble), laptop B (letter2, letter3; original and shift-full only) and laptop C (letter3 scramble). Laptop B
reproduced the pod to all three decimals on every shared number (letter2 0.640 / 0.154, letter3 0.700 / 0.093), and laptop C
reproduced letter3's original (0.700) a third time. Downloads: laptop A 19.45 GB, laptop B 2.56 GB, laptop C 8.98 GB;
the scrambled copies cost about 8 GB each because a scrambled trace spans much more of the 3-D volume.

## What it means

- Where the published picture shows dense ink, reading the published 3-D ink volume along our trace reproduces it (r 0.59-0.70), and
  moving the trace one sheet drops agreement 4-12x. The chain from trace to ink image works, and it depends on being on the right sheet.
- In the lowest-ink window the two images still agree at r 0.30 (broken copies 0.07). Both are ink-model outputs on the same CT, so they
  share papyrus structure as well as ink; the blank condition assumed that shared background would be near zero, and it is not.
- Shift-half keeps 49-68% of the original r (diagnostic), as the planted test predicted.

## Limits

- One segment, one scroll, 2 x 2 cm windows chosen by highest model output; the reference is a model output, not hand labels, and the
  3-D model may have been trained on this scroll.
- Correlation is not legibility: no letter was read or counted (Scroll 1 terms).
- The sign of the shift is drawn per window in run order, so it depends on which windows run together (here -35 for every window);
  the script now draws it from the window name (same PR).

## Proposal for the next test (not applied here)

Replace the absolute blank condition with a relative one: the blank window's r at most half the median letter-window r, AND each
letter window's r above the blank's by at least 0.2. This was written AFTER seeing these numbers, so it cannot be scored on these
windows; it applies only to new windows (another segment or scroll), fixed before their data are read. For Pedro to decide.

AI-assisted (Claude Code and Claude), human-directed.
