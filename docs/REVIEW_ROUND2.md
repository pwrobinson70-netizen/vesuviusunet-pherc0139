# Review round 2: the four new tools (+ the phantom they all rest on), read as a sceptic

Scope: `tools/sheet_tracer`, `tools/trace_repair`, `tools/trace_auditor`, `tools/ink_infer` (the `phantom_e2e` path and
the R3 fix), `tools/phantom_scroll` (+ `benchmark.py`). Every line was read. file:line refer to `main` at `4e47fd4` plus
the two branches that main lacked when this review started (`tool/ink-e2e`, `chore/release-0.1`, merged locally; the PR says so).
Same caveat as round 1: reviewer and author are the same model family, so this is a second read, not an independent audit,
and every number is from SYNTHETIC phantoms. No real scan data was used.

Started from the three failures recorded in `tools/sheet_tracer/SCORE_RESULTS.json` (PR #16's description could not be read:
this session's GitHub API access did not cover it; the JSON holds the same rows and the `score_on_phantoms.py` rerun below reproduces them exactly):

| recorded | row | what the data show (this review) |
|---|---|---|
| false-alarm FAIL on a crushed patch that was 100% on-turn | `bad / t2-mid` | `winding_jumps`: "radius jumps -0.61 pitch at z=206, col 25". The trace never leaves its turn (max abs winding error 0.07 sheet). The radius at that column changes by **0.42 voxel** between neighbours; the estimator's "step" was -11.6 voxel, made of the sheet's own bend at the long axis of the squashed scroll (slope +60 to -35 voxel/rad within the 40-degree window). **A1.** |
| a 7% leak on the merged phantom that the auditor PASSED | `merged / t2-low` | 137 of 1947 points on the wrong turn (rows 27-47, cols 25-40). The radius is smooth there (steps of +-0.7 voxel per point): the trace slid from sheet 2 to the touching sheet 1, which is 3 voxels away, while the auditor works in units of the measured CT pitch (20 voxels). Nothing in the auditor can see it. **A3, not fixed.** |
| a repair that made a real leak worse | `merged / t1-mid` | the real leak is 22 points at rows 28-35, cols 0-5. The finder reported (false) vertical switches at col 24. The repair started its chain at row 31, i.e. inside the leak, carried the wrong sheet down the rows: 52 points moved a median 17.6 voxel, on-turn 99.1% -> 97.2%, and a new `winding_jumps` FAIL appeared. **R1.** |
| (same file) FAIL -> PASS with the truth unchanged | `merged / t2-mid`, `bad / t2-mid` | on-turn 100.0% -> 100.0% (99.96% -> 99.96%); the repair "fixed" a false alarm by nudging 24% of the points by 0.8 voxel (max 1.3). The PASS afterwards is no more evidence than the FAIL before. **R1.** |

Severity: **BUG** = wrong result, **RISK** = right in the tested regime, silently wrong or unusable outside it, **NIT** = cosmetic.
Tests: `tests/test_review_round2.py` (written first; each fix's tests were run red against the old code). `data_round2/*.npz` are
two real cut-line runs (theta, r, local pitch) taken from the phantom runs above, 41 and 36 points.

## Summary

| Id | Sev | Where | Status |
|---|---|---|---|
| A1 | BUG | trace_auditor.py `detect_jumps` | **fixed** |
| A2 | RISK | trace_auditor.py `detect_jumps` (end zones) | **fixed** (sheet_switch_finder's end zones, round 1 R1, still open) |
| A3 | RISK | trace_auditor, whole approach | not fixed; strict xfail test |
| A4 | RISK | trace_auditor.py:217 `local_pitch` | not fixed |
| A5 | RISK | trace_auditor.py:242-256 `winding_check_height` | not fixed |
| A6 | NIT | trace_auditor.py:299, 321, 360 | not fixed |
| R1 | BUG | trace_repair.py `repair` | **fixed** |
| R2 | BUG | trace_repair.py:78 `repair_axis` | **fixed** (counted and warned, not repaired) |
| R3 | RISK | trace_repair.py:177 | not fixed (one scalar pitch) |
| P1 | BUG | phantom_scroll.py:198 `winding` | **fixed** |
| P2 | NIT | phantom_scroll.py:51 comment | **fixed** (comment) |
| P3 | - | phantom_scroll.py | checked, not a bug: labels, ink location, seam |
| P4 | RISK | phantom_scroll.py:251 `n_cols` | not fixed |
| P5 | NIT | phantom_scroll.py:219 | not fixed |
| T1 | RISK | sheet_tracer.py:214, 230 | **fixed, opt-in** (`--axis-xy`) + warning |
| T2 | RISK | sheet_tracer.py:163 `measure_pitch` | not fixed |
| T3 | RISK | sheet_tracer.py snap window vs merged sheets | not fixed (same as A3) |
| T4 | NIT | sheet_tracer.py:258-264 | not fixed |
| I1 | RISK | ink_infer.py:113, 170-171 (R3 follow-up) | not fixed (no torch here) |
| I2 | NIT | phantom_e2e.py:66 | not fixed |
| I3 | NIT | phantom_e2e.py:76-79 | not fixed |
| I4 | NIT | phantom_e2e.py:192 | not fixed |

## Verdicts before / after (phantoms, 256^3, seed 0, centre = truth)

`python tools/sheet_tracer/score_on_phantoms.py --size 256`, 12 patches (the "before" rows reproduce `SCORE_RESULTS.json` exactly):

| phantom / seed | on-turn | verdict before -> after repair, BEFORE this PR | verdict before -> after repair, AFTER this PR |
|---|---|---|---|
| bad / t2-mid | 100% | FAIL (winding_jumps) -> PASS (nudged, 24% of points moved ~0.8 voxel) | **PASS**, no repair needed (A1) |
| merged / t1-mid | 99.1% | FAIL -> FAIL, on-turn **97.2%** (worse), new winding_jumps | FAIL -> FAIL, on-turn 99.1% unchanged, "not repaired: unconfirmed" (R1) |
| merged / t2-mid | 100% | FAIL -> PASS (nudge) | FAIL -> FAIL, "not repaired: unconfirmed" (R1): the false alarm stays visible |
| merged / t2-low | 93.0% | PASS (7% leak missed) | **PASS (7% leak still missed)**: A3 |
| the other 8 | 100% | PASS -> PASS | PASS -> PASS |

`python tools/trace_auditor/score_on_phantoms.py --size 256 --centre truth` (true turns and planted bad traces, per phantom):

| phantom | true traces PASS / FAIL, before | after | bad traces FAIL, before | after | winding_jumps fired on bad traces, before | after |
|---|---|---|---|---|---|---|
| round | 7 / 0 | 7 / 0 | 6 / 6 | 6 / 6 | 3 | 3 |
| mild | 7 / 0 | 7 / 0 | 6 / 6 | 6 / 6 | 3 | 3 |
| bad | 5 / **2** | **7 / 0** | 6 / 6 | 6 / 6 | 4 | 3 |
| merged | 5 / 2 | 5 / 2 | 6 / 6 | 6 / 6 | 3 | 3 |

The two false FAILs on the crushed phantom (turn 3 alone, turn 3 vs turn 2, `winding_jumps`; the known ones in `trace_auditor/SCORING.md`) are gone. The
fourth `winding_jumps` on `bad` was the "skipped sheet" pair, whose B is the true turn 3: the same false alarm. Every planted switch is still failed by both
the switch finder and the jump check (3 of 3 on every phantom). The merged phantom's two false FAILs are the switch finder's (touching sheets), not touched here.
`python tools/phantom_scroll/benchmark.py --size 256`: the table is identical before and after (phantom change P1 is invisible at the preset irregularities).

A first version of A1 (`--wn-slope-mismatch` 0.3) also removed the false alarms but silently lost the benchmark's planted 4-column ramp on the
round phantom (a ramp changes the slope inside the window itself). A sweep over every cut-line run of the 4 phantoms x (4 true turns + 3 planted traces) x 5 heights
(`mismatch` 0.3: ramp found at 0 of 5 heights; 0.6 / 1.0: 5 of 5, no false jump on any true trace; 1.5 and up: 1 false jump on `bad`) fixed the default at 1.0.
That sweep is on the same phantoms the numbers above come from: it is a choice of constant, not a validation.

## Fixed

### A1 (BUG) `trace_auditor.py:158-200` `detect_jumps`: curvature read as a step
The step at a gap was `mean(r after, 20 deg) - mean(r before, 20 deg) - slope * (angle between the window centres)`, the slope being the
median of the segment slopes of both windows. That assumes one slope across the 40 degrees. A sheet_tracer patch has 4-7 degrees per
point, so a window holds 3-5 points, and where the radius has a maximum (the long axis of a squashed ellipse) the slope changes
sign inside the window: the common-slope term is wrong by `(slope difference) x (half window)`, here 17 voxel. The existing test
(`test_squashed_ellipse_radius_variation_is_not_a_jump`) used 400 points over two turns (1.8 degrees per point) and could not see it.
Data (`tests/data_round2/crushed_run.npz`): reported step -11.63 voxel = -0.61 pitch (threshold 0.6, i.e. a flip with a 0.01 pitch nudge);
adjacent difference at the reported column 0.42 voxel.
Fix: where the two windows' own slopes differ by more than `--wn-slope-mismatch` (1.0) x threshold over half a window, the step is the
offset of two straight lines fitted separately to the two windows, evaluated at the gap. Elsewhere the old estimator is used (it
handles the 12-sample ramp of the benchmark, which a separate-line fit cannot). Measured on that run: clean max |gap| 0.29 pitch; planted
hops of 1 pitch at 8 positions x 2 signs: 0.75 to 1.25.
Tests: `test_A1_curvature_alone_is_not_a_jump_on_a_sparse_patch` (red before); controls: hops of one pitch at three positions x two signs on
the same curved run and a 4-column ramp are still found. All 27 `test_trace_auditor.py` tests pass.
Not claimed: that real sheets never bend faster than the windows resolve; the threshold constants are unchanged and were never tuned on real data.

### A2 (RISK) `trace_auditor.py:174-175`: first and last 20 degrees never tested
`if tc - win < t[0] or tc + win > t[-1]: continue`. On a 41-column patch (4 degrees a column) that is 5 columns each end, a quarter
of the line, and the patch periphery is where ring growth hops sheets. Windows are now cut at the ends of the run; a step needs
`--wn-window-min-points` (3) points on each side (so 2 or fewer points from an end are still untestable). Tests:
`test_A2_a_hop_near_the_end_of_a_short_run_is_found[4]` (red before) and the no-false-alarm control at both ends of the curved run.
`test_trace_auditor.py::test_step_inside_the_first_window_is_not_tested` asserted the old blind zone; it is replaced by
`..._is_tested_with_truncated_windows`. **That is a changed existing test, on purpose.** Round 1's R1 (the same blind zone in
`sheet_switch_finder`, K = 5 points) is untouched.

### R1 (BUG) `trace_repair.py:103-133` `repair`: acts on the whole trace, never checks it did anything where the audit said
Every point beyond the first reported line, in every row, is re-snapped, whether or not the report is true, and whether or not it is
where the leak is. Three consequences, all in `SCORE_RESULTS.json`: a false alarm is "repaired" by a nudge that flips the verdict (a
PASS that means nothing); a mislocated report starts the chain inside a leak and spreads it (97.2%); and the summary says
`repaired: true` either way.
Fix: after the re-snap, each switch is checked (`confirm_switches`): some point within `margin + 3` lines of the reported line (and
within `--confirm-orth` = 6 lines of where the audit saw it on the other axis, when it says: the finder gives the row of a horizontal
switch and the column of a vertical one; winding jumps give neither) must have moved by at least `--confirm-pitch` = 0.5 pitch. A real
hop is one pitch, so removing it moves points by about one pitch; a false alarm only nudges. Unconfirmed switches are dropped and the
repair re-run with the rest; with none confirmed the input is copied byte for byte, `repaired: false`, the reason and the largest move
seen are in `repair_summary.json` (`unconfirmed`), and the verdict is, correctly, not changed.
Tests: `test_R1a` (false alarm: output byte-identical), `test_R1b` (mislocated switch next to a 6x8 leak: on-turn 99.2% -> 41% before the
fix, unchanged after), `test_R1c` control (a real planted switch is still confirmed and repaired to >= 90% on-turn); the four planted-switch
cases of `test_trace_repair.py` still pass.
Not claimed: that 0.5 pitch is the right confirmation threshold on real data, or that a real hop is always one pitch (a double hop is two;
that passes the test). It cannot make a wrong audit right: when the audit is right about the existence of a leak but wrong about its place, the leak stays.

### R2 (BUG) `trace_repair.py:78`: cells behind a hole are "repaired" from their own wrong neighbour
`rows = valid[:, c] & valid[:, c-1]` used the ORIGINAL validity, so a cell after a hole in its row was predicted from the unrepaired,
wrong-sheet cell before it and stayed on the wrong sheet; nothing was counted. sheet_tracer patches have holes by design. Toy test
(`test_R2_...`): one hole in a 7 x 12 patch leaves 5 cells (row 3, cols 7-11) on the wrong sheet. Fix: a cell is repaired only if its
predecessor was reached; the others are left as they were, counted (`n_unreached` in the summary) and a warning goes to stderr. The
alternative (chain across the hole from the nearest valid cell in the row) was not done: it needs a choice of how far to trust a gap.

### P1 (BUG) `phantom_scroll.py:193-201` `Scroll.winding`: the irregular spiral is inverted by 6 fixed-point sweeps
The map contracts only while `2 pi |dr'| / pitch < 1`, with `|dr'| <= 0.522 x irregular x pitch`: irregular < 0.305. Max |w - w_true| (sheets), measured:

| irregular | 0.05 | 0.12 | 0.2 | 0.3 | 0.4 | 0.6 |
|---|---|---|---|---|---|---|
| before | 0 | 1e-4 | 3e-3 | 0.07 | **0.39** | **0.74** |

The winding number is the label of every voxel (`winding.npy`), the profile and brightness of the rendering and the truth every
benchmark scores against, so a wrong `w` is a wrong phantom with no message. The shipped presets use <= 0.12 (error 1e-4, the fixed point
was fine there); only user-chosen values were affected. Fix: Newton iteration (f' = -1 - 2 pi dr'/pitch < 0 for every accepted
value), and `ValueError` for `irregular >= 0.30`, where neighbouring turns cross (the CLI prints it, exit 2). Tests: round trip radius ->
winding to 1e-4 at 0.12, 0.2, 0.25, 0.29 (0.2 and up red before) and the refusal at 0.31, 0.4, 0.6.
Side effect: Newton and 6 sweeps differ by ~1e-4 sheet at the preset values, so the rendered phantoms are not bit-identical to before
(benchmark before/after in the PR).

### P2 (NIT) `phantom_scroll.py:51`: `squash_angle` comment said "direction that is compressed"
`A = R diag(1, s) R^T` leaves the direction `squash_angle` unchanged and compresses the PERPENDICULAR. Comment fixed; `test_P2` characterises it.

### T1 (RISK) `sheet_tracer.py:214, 230`: the handedness of the grid depends on where the seed is
The seed normal is signed "largest component positive"; the columns run along `n x t_row`, so on one side of the scroll they run
clockwise and on the other counter-clockwise. Measured on the round phantom, turn 1, four seeds: 36 deg CW, 126 deg CW, 216 deg CCW,
306 deg CCW. Two patches of the same sheet therefore have opposite surface-normal orientation as VC3D reads them, and the layer order
`ink_infer` reads along the normal (`--flip-normal` exists for exactly this) is front/back depending on the seed. The auditor and the
repair are sign-agnostic, so nothing in this repo broke; anything that merges patches or reads ink would.
Fix, opt-in: `--axis-xy X Y` orients every normal away from the axis (one handedness); without it nothing changes except a one-line warning
(it was silent). Tests: the old behaviour is characterised (`..._documented`), and four seeds with `--axis-xy` give one handedness.
Not done: guessing the axis. The tracer does not know it; the auditor's umbilicus file or `umbilicus_finder` does.

## Not fixed, and why

### A3 (RISK) a trace that slides onto a TOUCHING sheet is invisible
See the table at the top: `merged / t2-low`, radius steps <= 0.7 voxel per point while the trace crosses to the neighbouring sheet 3 voxels
away. Where two sheets merge the CT "pitch" the auditor measures is the spacing of the merged pair to the next sheet (14.5 -> 20.8 voxel
from one point to the next at the crossing; raw `ct_pitches`, no NaN), so a hop of the real local spacing is 0.15 of the threshold. Tried
on paper, not shipped: flag a ratio > 1.3 between neighbouring raw pitches as "sheets merge here, NOT JUDGED". It would make this case NOT JUDGED
(honest) but raw `ct_pitches` are noisy on real CT, the heuristic has seen no real data, and an NOT JUDGED at 1-2 of 5 heights
does not change a verdict (`max_unjudged_height_fraction` = 0.5). Strict xfail `test_A3_...` records it. README Limits says: where sheets merge, a PASS means nothing.

### A4 (RISK) `trace_auditor.py:217-218`: unmeasured pitch is interpolated and median-smoothed silently
`pp = np.interp(...)` from the nearest measured points, then a 15-point running median. A point with no CT pitch is judged with a
neighbour's pitch and nothing records which points were measured. In the data above no point was unmeasured (so this is not what
missed A3), but the threshold on an unresolved stretch is a guess. Fix needs a decision (how many unmeasured points make a window not judged).

### A5 (RISK) `trace_auditor.py:242-256`: short runs are skipped, a PASS does not say how much of the line it looked at
`winding_check_height` skips runs of < 12 points or < 60 degrees and reports PASS if any run was judged. In `merged / t2-low` at z=164 the
second run (cols 33-40, 8 points) holds part of the leak and was never examined; at z=136 cols 38-40 likewise. Fix: report the judged
fraction of cut-line points per height and make a height NOT JUDGED below a limit; the limit is a choice (not made here).

### A6 (NIT)
`auto_heights` uses Python `round` (ties to even) at x.5; `unj > fraction * len(heights)` lets a trace PASS with up to half its heights
unjudged (the message says "N judged heights"); the pair offset is O(points x segments) in Python.

### R3 (RISK) `trace_repair.py:177`: one scalar pitch for the whole repair
`pitch = a.pitch_vox or median(audit per-height pitch)`; the snap window (1.0 pitch) and the confirmation (0.5 pitch) use it. On a crushed
scroll (spacing varies 2x round a turn) the window is too wide where sheets are close: it can reach the neighbouring sheet. Not changed.

### P3 (checked, not a bug) labels, ink, seam
`winding.npy` at the voxel nearest every point of `surfaces/turn_k` equals `k` for 99.4-100% of points (the rest are rounding at the sheet
centre; all four presets, 128^3). The ink lands on the mask: mean brightness on / off the letters on turn 1 is 254 / 195 and the best of 91
(row, col) shifts tried in a probe (9 in `test_P3`) is (0, 0). At the angle seam the label of one physical sheet changes by one (sheet k ends where sheet k+1
begins, because `r = r0 + pitch (k + phi / 2 pi)`): by construction, and the scorers (`turn_fraction`, `fraction_on`) are seam-safe; anyone
using `winding.npy` as "sheet identity" across phi = 0 must know. The forward map `T` and its fixed-point inverse (checked by the round-1 tests to
0.01 voxel) are applied to the surfaces, the centre line and the render alike.

### P4 (RISK) `phantom_scroll.py:251` `n_cols` is angle-uniform, not arc-uniform
`n_cols = round(2 pi (r0 + pitch turns / 2) / grid_step)` columns for every turn: the arc step per column at 256^3 defaults is 1.9, 3.3, 4.7, 6.2
voxel on turns 0-3 against a nominal `grid_step` of 4 and a `meta.json` `scale` of 1/4 in both directions. Tools that use `scale` to turn grid
cells into voxels along columns (`ink_infer` via `resample_mesh`) see a letter mask 17% (turn 1) narrower than a pixel-for-pixel reading says; the end-to-end test
trains and tests on the same geometry, so its numbers are self-consistent, but the "1 voxel per pixel" in `phantom_e2e` is true along rows only. Changing it
would change every truth file; not done.

### P5 (NIT)
`render_slab:219` the signed distance `d = dw x pitch x stretch x aff` is first order: the rendered sheet thickness is not uniform where stretch and the
affine factor vary. The truth surfaces are exact; only the profile width is approximate.

### T2 (RISK) `sheet_tracer.py:163` `measure_pitch`
Pitch is measured in the seed's z slice along the in-slice normal, so a sheet inclined to the slice (`n_z != 0`) gives `pitch / sqrt(1 - n_z^2)`.
Sheets in these scrolls are close to vertical, so the effect is small; not tested, not changed.

### T3 (RISK) snap window versus touching sheets
`--snap-pitch 0.5` x 20 voxels = 10 voxels, wider than the 3-voxel gap of two touching sheets, so growth takes whichever merged peak is
nearest: the mechanism behind A3's leak, and documented in the README ("on touching or merged sheets the tracer cannot know").

### T4 (NIT) `sheet_tracer.py:258-264`
The stop-reason block assigns `stop` twice with overlapping conditions; the output is right in the cases tested (`max_rows_cols`, `ring_no_accepted`) and
the second assignment is partly dead. Left.

### I1 (RISK) `ink_infer.py:113, 170-171` R3 follow-up: the fix covers "no patch at all", not "some valid pixels in no patch"
`coords` keeps patches with >= `min_valid_frac` valid pixels. A valid island smaller than that fraction of a patch, far from other valid pixels, is
in no patch: `prob = 0` there, `valid_mask.png` still 1. Toy count (patch 32, stride 16, 5%): a 12-pixel island next to a 7 000-pixel block gives 12 valid pixels with
probability 0. The scorers (`phantom_e2e.score`) use `valid_mask`, so those pixels count as confident "no ink". Not fixed: `torch` is not installed in this
environment or in CI (every ink_infer test is `importorskip`), so there is no failing test to write and no way to run the change. The fix is one line
(`valid_mask = surf2.valid & (weight > 0)`, with `weight` returned by `run_inference`). The R3 fix itself reads correctly (the empty-list check is after
`pad_surface`, so a surface smaller than one patch is padded, not refused; the message names the flag to change).

### I2 (NIT) `phantom_e2e.py:66`
`surf.valid[:-a.patch, :-a.patch]` excludes the last valid start row/column (starts run 0 .. H - patch inclusive); a surface smaller than one patch gives an
empty list and an opaque `rng.integers(0)` error.

### I3 (NIT) `phantom_e2e.py:76-79`
`if rng.random() < ink_frac and lb.sum() == 0: continue` never terminates if no patch of any training phantom contains ink.

### I4 (NIT) `phantom_e2e.py:192`
`col_px = int(round(sw["col"] / scale_x))` uses Python `round` and is right only for `--out-pitch-um` = `--scan-voxel-um` (1 voxel per pixel), which
`run_ink_infer` hard-codes. The threshold protocol is honest: chosen on the val phantom (other seed AND letters), applied unchanged to the test phantom,
test-best value printed as reference only.

## Read and found sound (no finding)
`Tracer.normals_at` (axis order zyx -> xyz, ascending `eigh`, coherence), `inside` (x vs nx, y vs ny, z vs nz), `profile`/`snap` (parabolic offset
`0.5 (y0 - y2) / (y0 - 2 y1 + y2)`, window pad), `_tangents`/direction table (row = +z, col = n x t_row, consistent with `_orient`), the self-intersection
guard (`P[acc]` and `argwhere(acc)` share order), `crop`, `area_vx2`, `write_tifxyz`; `repair`'s flip arithmetic for `--origin-cell` (`C - o`, `C - 1 - max(lo)`);
`pair_offsets` seam handling (mod 2 pi, short way round); `phantom_scroll.trace` axis order (x = cos, y = sin), `-1` sentinel, `write_zarr` level 1;
`phantom_e2e` mask resampling rule (matches `surface.resample_mesh`) and F0.5.

## Not verified
Real scans (none used); torch code paths (`run_inference`, `phantom_e2e train/score`, the R3 tests): not run; the thresholds of A1/A2/R1
on anything but these phantoms; other phantom seeds, sizes, pitches and grid steps; PR #16's own text.
