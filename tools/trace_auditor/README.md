# trace_auditor: one command, one verdict per trace

```bash
pip install -r tools/trace_auditor/requirements.txt          # numpy scipy tifffile pillow zarr
python tools/trace_auditor/trace_auditor.py TRACE_A [TRACE_B] --zarr volume.zarr \
    [--umbilicus centre.json] --out-dir audit/ [--heights 3000,3500,4000] [--png]
```

`TRACE_A`, `TRACE_B`: tifxyz folders (docs/FORMATS.md). With one trace it audits that trace. With two, **A is
the reference** (assumed right) and **B is the proposed neighbour**: B gets the extra pair checks. Output in
`--out-dir`: `audit.json` (everything, with the parameters used), `audit.txt` (the text below) and, with
`--png`, `png/winding_<trace>_z<height>.png` (radius against unwrapped angle, jumps ringed in red).

```
turn_02: FAIL
    [PASS      ] switch_finder: no switch at 5 judged heights
    [PASS      ] winding_jumps: no radius jump at 4 judged heights
    [FAIL      ] spacing: clean 4% (shared 0%, skipped 96%, B missing 0%) over 5 heights
    [FAIL      ] winding_offset: z=14: B is +1.97 pitch from the nearest A sheet (whole sheets: +2), ...
```

**Exit code:** 0 all PASS, 1 any FAIL, 4 no FAIL but at least one NOT JUDGED, 2 bad input.

## What it runs

1. **Centre line.** `--umbilicus FILE` (villa `control_points` JSON, native `vc_umbilicus` JSON, `z, y, x` text with
   `--umbilicus-format zyx-text`, villa "thaumato" text with `--umbilicus-format thaumato`; coordinates in level-0
   voxels, `--umbilicus-scale` multiplies them), or else `umbilicus_finder` on the volume (OK slices only, every
   `--centre-z-step` voxels). A height is judged only if the centre line covers it and an OK slice is within
   `--centre-max-gap` x z step.
2. **sheet_switch_finder** on every trace (horizontal and vertical test). FAIL if any switch has confidence
   >= `--min-switch-confidence`. A height counts as judged only if the finder tracked >= `--min-tracked-fraction`
   of the cut line; if more than `--max-unjudged-height-fraction` of the heights are unjudged and there is no
   switch, the check is NOT JUDGED.
3. **Winding-number check** on every trace (new). At each height the cut line is unwrapped to (angle, radius) about
   the centre at that height. Within one turn the radius must change smoothly with the angle; the tool measures
   the step as `mean radius over the next --wn-window-deg degrees - mean radius over the previous --wn-window-deg`
   minus the local spiral slope (median dr/dangle of both windows) times the angle between the windows. A step of at
   least `--wn-jump-pitch` x the local CT pitch (the per-point sheet spacing of `sheet_spacing_check`, gaps filled and
   smoothed over 15 points; or `--pitch-vox`) is a jump = a sheet switch (about one pitch
   for a switch to the neighbouring sheet). A run is judged only with at least `--wn-min-points` points spanning
   `--wn-min-span-deg` degrees whose angle runs one way (`--wn-monotonic`). Jumps => FAIL; too few judged heights =>
   NOT JUDGED.
4. **sheet_spacing_check** (B against A, same grid shape needed, else that check is NOT JUDGED). FAIL if the mean
   clean fraction over the heights is below `--min-clean-fraction`.
5. **Winding offset of B against A** (new). For every B point the nearest A sheet at the same angle is found (A may
   be several turns); the radial offset in pitches is B's *winding-number difference*. An adjacent sheet is
   `--wn-pair-lo` to `--wn-pair-hi` local pitches away (about 1); about 0 is a shared sheet, about 2 means B lies on the
   sheet **after** the neighbour. FAIL if fewer than `--wn-pair-frac` of B's points are adjacent. This is what
   catches a trace that **starts on the wrong sheet and stays there**: it has no switch and no jump, so checks 2
   and 3 pass it (the switch finder's anchor limit), but its offset from the reference is 2 (or 0), not 1.
   `--expect-side outward|inward` additionally fixes the side.

**Verdict per trace:** FAIL if any check FAILs (all reasons are listed); else NOT JUDGED if any check could not be
judged; else PASS. A trace is never PASS because a check was skipped.

## Thresholds (every one is a flag; defaults)

| Flag | Default | Meaning |
|---|---|---|
| `--heights` | auto | comma-separated z (voxels); otherwise `--n-heights` heights over the common z range |
| `--n-heights` | 5 | number of automatic heights |
| `--height-margin` | 0.10 | fraction of the common z range trimmed at each end for automatic heights |
| `--centre-z-step` | 32 | z step of the centre estimate (voxels) |
| `--centre-max-gap` | 1.5 | a height is judged only if an OK centre slice is within this x `--centre-z-step` |
| `--umbilicus-scale` | 1.0 | multiplier for the coordinates of a given umbilicus file |
| `--min-switch-confidence` | 0.3 | a switch of at least this confidence makes the trace FAIL |
| `--min-tracked-fraction` | 0.6 | a height is judged by the switch finder only if this much of the line was tracked |
| `--max-unjudged-height-fraction` | 0.5 | more unjudged heights than this make a check NOT JUDGED |
| `--wn-jump-pitch` | 0.6 | radius step (CT pitches) that counts as a jump |
| `--wn-window-deg` | 20 | angle window on each side of a candidate step |
| `--wn-window-min-points` | 3 | points each window needs |
| `--wn-slope-mismatch` | 1.0 | where the two windows' own slopes differ by more than this x the jump threshold (over half a window) the step is the offset of two separately fitted lines (a bend is not a step) |
| `--wn-min-points` | 12 | points a cut-line run needs |
| `--wn-min-span-deg` | 60 | angle a run must span |
| `--wn-monotonic` | 0.95 | fraction of steps that must run the same way in angle |
| `--wn-pair-lo`, `--wn-pair-hi` | 0.5, 1.5 (as sheet_spacing_check) | |offset| of B from the nearest A sheet, in pitches, for "adjacent" |
| `--wn-pair-frac` | 0.8 | fraction of B points that must be adjacent |
| `--min-clean-fraction` | 0.8 | mean `sheet_spacing_check` clean fraction B needs |
| `--expect-side` | either | `either`, `outward` or `inward` |
| `--pitch-vox` | measured | override the CT pitch (voxels) for all checks |

The constants of the three tools underneath are flags too: `--ssf-<name>` (sheet_switch_finder), `--ssc-<name>`
(sheet_spacing_check) and `--uf-<name>` (umbilicus_finder), e.g. `--ssf-k-points 8`; see `--help` and those
tools' READMEs. Volume input as in `sheet_spacing_check`: `--zarr`/`--zarr-level` or `--png-dir` with
`--png-pixel-um` and a voxel size. `--transpose` for grids with z along the columns.

## Limits (read before trusting a PASS)

- A PASS means these checks found nothing, not that the trace is right. It is not a judgement of the ink or of
  where the trace is relative to anything but the CT and the reference.
- One trace on its own cannot be told from a trace that lies on the wrong sheet throughout: the offset check needs
  a reference A that is right. If A is wrong, B can pass against it.
- Windows are cut at the ends of a run (a step needs `--wn-window-min-points` points on each side), so a jump
  within the last 20 degrees is tested, with less evidence (REVIEW_ROUND2 A2); the switch finder's end zones are
  unchanged. A closed ring is cut at its seam.
- A trace that slides from one sheet to a TOUCHING one (sheets 3 voxels apart where a CT pitch is 20) has no step
  of the size of a pitch and passes every check here (REVIEW_ROUND2 A3, strict xfail test). Where sheets merge, a
  PASS means nothing.
- The winding checks need the centre line. A bad centre (or a scroll whose cross-section is far from concentric
  rings, e.g. tears) gives jumps or offsets that are not switches; look at the PNGs.
- The winding offset measures geometry only. A B that is exactly one pitch from A but in a dark gap passes it;
  the spacing and switch checks are what catch that.
- On a badly crushed scroll the true sheet spacing varies by 2x or more round a turn (squash plus warp); the local
  pitch is a noisy estimate of it, so a genuine neighbour can fall outside `--wn-pair-lo..hi` at some angles (one
  false FAIL in 7 true traces on the "bad" phantom, see the pull request). Widen the range or read the PNGs.
- Pitch comes from the CT at each height (`sheet_spacing_check` rules; fails when sheets are more than about 60
  voxels apart, see docs/REVIEW_ROUND1.md B2): then the winding checks at that height are NOT JUDGED unless
  `--pitch-vox` is given.
- Synthetic evidence only (concentric rings in the tests, phantoms in the pull request); nothing here has seen a
  real scroll.

## v0.2: local-pitch confidence, NOT JUDGED regions, judged fraction

Evidence: `tools/realdata_run/RESULTS.md` (PR #17), findings 3, 5 and 6 / proposal P5: on real data the pitch came out 14-17 vox
against 9-10.5 measured, and the auditor FAILed everything, the unbroken originals included (112-142 radius "jumps" per trace), so a
FAIL carried no information. The real periodicity is weak (autocorrelation second lobe < 0.1) and the local-pitch confidence
(`tools/common/local_pitch.py`: peaks x regularity x autocorrelation at the pitch) is accordingly low there.

- A *region* is `--region-points` consecutive cut-line points of one run. Its confidence is the median of the per-point local-pitch
  confidence. Below `--min-pitch-confidence` the region is **NOT JUDGED**: switches (switch_finder) and radius jumps
  (winding_jumps) that lie in it are not counted (the reason text says how many were left out), B points in it are left out of
  winding_offset, and a pair height whose mean confidence is below it is left out of the spacing check.
- PASS / FAIL therefore refer to judged regions only. Every trace reports `judged_fraction` (also in `audit.json`, per height and in
  the text report). A trace with no FAIL whose judged fraction is below `--min-judged-fraction` is **NOT JUDGED** (check
  `pitch_confidence`): a PASS would mean nothing. A FAIL in a judged region stands whatever the fraction.
- `--min-pitch-confidence` 0.3, `--region-points` 15 and `--min-judged-fraction` 0.5 are **judgement calls** (docs/OPERATING_RANGE.md
  gives no confidence threshold). Evidence for 0.3: share of 15-point regions with confidence >= 0.3 on the cut lines of turns 1-2
  of 192^3 phantoms (5 heights): round 1.00, mild 1.00, folded / delaminated / torn / gappy 1.00, merged 0.94, crushed 0.50,
  crushed-hard 0.07; real PHerc. Paris 4 meshes 0.00. 0.2 to 0.5 gives the same picture; no held-out set.
- `--global-pitch` is the old behaviour (no confidence, every region judged, the old pitch estimator); it is also forwarded to
  `--ssf-global-pitch` and `--ssc-global-pitch`.

| flag | default | meaning |
|---|---|---|
| `--global-pitch` | off | old pitch handling, no NOT JUDGED regions |
| `--min-pitch-confidence` | 0.3 | a region below this median local-pitch confidence is NOT JUDGED |
| `--region-points` | 15 | region length in cut-line points |
| `--min-judged-fraction` | 0.5 | PASS needs this fraction of the cut line judged, else NOT JUDGED |
