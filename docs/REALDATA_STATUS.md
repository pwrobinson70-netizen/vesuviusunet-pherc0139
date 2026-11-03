# Real-data status of the tools

What each tool does on the one public real sample we have: PHerc. Paris 4, Scroll 1, 45.532 um, two tifxyz meshes
(`w116-117`, `w118-119`) and three slices (z = 2073, 2600, 3128), in `testdata/pherc_paris4_45um/` (CC BY-NC 4.0).
Source of every number: `tools/realdata_run/RESULTS.md` (brief 14, 3 Nov 2026). Enforced by `tests/test_realdata.py`,
which runs in CI (about 20 s). No tool was changed to produce this table.

How to read it: **yes** = does what it is for on this sample; **partly** = runs and the part that can be checked agrees,
but a documented limitation applies; **no** = runs but the result is not usable, or it refuses the input.
"Works" is judged against measured facts and the tool's own stated purpose. Nothing here was checked against ground truth
for the sheet-level questions (nobody has labelled the true sheet structure of this sample), see "Not established".

| Tool | Works on real data? | Evidence | Open finding ids (tests) |
|---|---|---|---|
| mesh readers (`ssc_io.load_mesh`) | **yes** | Both meshes load; shape (130, 354) / (129, 357), float32 on disk, float64 in memory, 6451 / 6161 invalid cells, bbox equals `meta.json` (XYZ). `test_mesh_loads_with_recorded_facts` | F3 (no voxel size, `uuid` = "out"), F4 (`FORMATS.md` stale), P8, P9 (mask and z <= 0 not exercised) |
| slice reader (`uf_io.PngVolume`) | **partly** | Loads the 3 PNGs, shape (3, 2264, 2264), uint8. But z is the list index, not the number in the file name. `test_uf_io_loads_the_slices`; xfail `test_png_slice_heights_come_from_file_names` | F2 |
| `umbilicus_finder` | **no** | All 3 slices LOW (residual 9-17 pitches), centres x 1161 / 1150 / 1150, y 1022 / 1076 / 1205. Default finds no pitch (`no_pitch`); `--pitch-vox 8` needed. Centre at z=2600 is about 55 px from the by-eye whorl centre. `test_umbilicus_centres_and_confidence_class_as_recorded`; xfail `test_umbilicus_default_finds_a_pitch_and_an_ok_slice`, `test_umbilicus_centre_matches_by_eye_at_2600` | R14-2, P4 |
| `sheet_spacing_check` | **partly** | Runs and reproduces the recorded clean / shared / skipped fractions (16 / 80 / 0, 9 / 87 / 1, 25 / 66 / 1 %) only on padded copies; refuses the real pair as it is. CT pitch 14-17 voxels against 9.5 measured independently, so PITCH-MISMATCH at all heights. Whether 66-87 % "shared" is true or a tool artefact is not known. `test_spacing_fractions_and_ct_pitch_as_recorded`; xfail `test_spacing_accepts_the_real_pair_as_it_is`, `test_spacing_ct_pitch_matches_independent_measurement` | F1, P1, P2, R14-3, P3, R14-4, P7 |
| `sheet_switch_finder` | **partly** | Runs, 34 / 25 switches reported, 5 / 3 with confidence >= 0.3 (positions pinned). Not hand-checked, so true or false alarms are unknown. Does not flag a deliberate one-pitch break. `test_switch_finder_reports_recorded_switches`; xfail `test_switch_finder_flags_the_broken_copy` | R14-5, P6, F5 |
| `trace_auditor` | **no** | Runs, writes reports. FAILs both unbroken meshes (`switch_finder` FAIL, `winding_jumps` FAIL with 136 / 129 jumps after round 2; 112 / 115 before), and gives the same FAIL for the broken copy, so the verdict carries no information. Spacing check NOT JUDGED for the pair (F1). `test_auditor_verdicts_as_recorded`; xfail `test_auditor_verdict_separates_broken_from_original`, `test_auditor_does_not_fail_on_untouched_traces_for_unreliable_centre` | R14-6, P5, F1 |
| `sheet_tracer`, `trace_repair`, `ink_infer`, `phantom_scroll` | **not run** | Brief 14 did not run them on real data; they have synthetic-phantom tests only. | none recorded |

## Finding ids

`F1`-`F5` and `P1`-`P9` are the ids used in `RESULTS.md`. `R14-2`...`R14-6` number the items of its "What did not work" list
(2 umbilicus gave no usable centre, 3 CT pitch 1.5-1.8x too large, 4 meshes about 3.5 voxels apart so 66-87 % "shared",
5 switch finder blind to the deliberate break, 6 auditor FAILs everything); item 1 is F1.

## How the xfail tests work

Each `xfail(strict=True)` test asserts the **correct** behaviour and carries the finding id in its reason. It is expected
to fail today. When a fix makes it pass, strict mode reports the XPASS as a failure; the person who fixed the tool then
deletes the marker and flips the matching row above. Tests that pin today's (possibly wrong) behaviour are separate
passing tests, so a fix that changes them must update the recorded constant and say why.

## Not established

- Whether the two meshes lie on separate neighbouring sheets (P7), so no test claims the spacing fractions are right, only
  that they are reproduced.
- Whether any reported switch is real: none was checked against the CT by hand.
- One volume, three heights, two meshes, one break position and size. Thresholds in the tests (3 px centre, 0.05
  fractions, 10 % pitch) are tolerances for numerical stability, not accuracy claims.
- The tool outputs in RESULTS.md were produced before `fix/review-round2` was merged. The one value that moved is the
  auditor jump count; verdicts and every other recorded value reproduced.
