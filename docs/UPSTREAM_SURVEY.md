# Upstream survey (Brief 11) — DRAFT, INCOMPLETE

**Status: draft pushed early on request. Licences, sizes and README claims below were read on 3 Nov 2026. The main code of each repo has NOT yet been read, so the "gain" column and the picks are provisional.** Nothing here has been run.

| Repo | Pinned commit | Licence (LICENSE file) | Code size | Tests | CPU? (per README) | What it does well (per README) | Likely gain on our phantom benchmark (unverified) |
|---|---|---|---|---|---|---|---|
| [joe-carr-data/windcheck](https://github.com/joe-carr-data/windcheck) | `2b0fb2f` | MIT, "Josep Carreras" — may build on, keep LICENSE + attribution | ~41.5k lines (incl. bench/results) | yes (26 test-named files) | not stated; mesh geometry, so probably | self-intersection census of tifxyz traces; benchmark packaging; checked against the official `vc_tifxyz_selfcross` | add a CT-aware off-sheet check next to intersection; run as one more `trace_auditor` verdict |
| [Nieuwlaar/tifxyz-repair](https://github.com/Nieuwlaar/tifxyz-repair) | `4d6c98d` | MIT, "tifxyz-repair contributors" | ~1.8k lines | yes (2 test-named files) | yes (CPU-only stated) | stale-bbox detect/fix, VC3D loader semantics, safe atomic writes, `inspect` for holes/spacing/flips | geometric repair (infill invalid points, recompute scale/bbox, make mask.tif); VC3D-format tests from docs/FORMATS.md |
| [spencerdavis-tx/vesuvius-automesh](https://github.com/spencerdavis-tx/vesuvius-automesh) | `09482fa` | MIT, "Spencer Davis" | ~4.6k lines | none found by filename | yes ("zero GPU" stated) | QC-gated surface harvest, per-window QC records | swap its gate for `trace_auditor` and score the harvest on phantoms |
| [TAUIL-Abd-Elilah/spiral-winding-audit](https://github.com/TAUIL-Abd-Elilah/spiral-winding-audit) | `c9a845a` | MIT, "TAUIL Abd Elilah" | ~5.4k lines | yes (7 test-named files) | `ct-inputs` stated to run on CPU | per-node winding audit and repair, single-sheet pieces; reports its own negative result on CT ray counting | our `umbilicus_finder` centre + winding-number check as detector; score on stacked-winding phantoms |
| [WillStevens/scrollreading](https://github.com/WillStevens/scrollreading) | `db12d00` | **GPL-3.0** — vendor nothing; external call or re-implement from README only | ~72k lines (C/C++/CUDA/Python) | no suite (scripts named test_*) | has CUDA parts; CPU status unchecked | flood-fill surface extraction | not planned: GPL and size |
| [Jinhojeong/vesuvius-unmerge](https://github.com/Jinhojeong/vesuvius-unmerge) | `179ebe7` | MIT, "Jinho Jeong" | ~390 lines | none found | not stated (numpy/scipy solve) | splits fused sheet instances; flags rather than guesses; README says it refines existing labels, does not bootstrap | score on our merged phantom; small enough to wrap cheaply |

Note: LICENSE copyright holders differ from GitHub owners in places (windcheck, tifxyz-repair). `ATTRIBUTION.md` files will name both.

## Provisional picks (to be confirmed after reading the code)

1. **tifxyz-repair** — permissive, small, tests exist, repair work overlaps our review-round fixes.
2. **windcheck** — permissive, fits `trace_auditor` as an extra verdict; vendor only the needed core, not 41k lines of results.
3. **spiral-winding-audit** — permissive, matches our umbilicus/winding-number tools.

Fallback/cheap fourth: **vesuvius-unmerge**. **automesh**: lower priority. **scrollreading**: excluded (GPL-3.0).

## Not yet done

- Reading each repo's main code; running their tests; confirming CPU-only.
- Replacing "likely gain" with measured before/after on the phantom set.
- Final ranking by (licence) x (gain to trace-quality judging).


## Brief 22 outcome (3 Nov 2026): what was done, and how much was actually read

Picks confirmed: **tifxyz-repair** (PR from `tool/upstream-advance`) and **windcheck** (PR from `tool/upstream-windcheck`, stacked on the first). Code under `tools/upstream/<name>/`, each with the
upstream `LICENSE` unchanged, an `ATTRIBUTION.md` (author as in LICENSE, GitHub owner, repo, commit sha, what we changed) and a README that says what came from whom.

| Repo | Read before use | Taken (unchanged) | Ours | Measured result |
|---|---|---|---|---|
| tifxyz-repair `4d6c98d` | `core.py`, `repair.py`, `checks.py` (signatures), `pyproject.toml`, the test file's imports; not `deep.py` / `report.py` / `cli.py` line by line | the whole package + its 39 tests | `geometric_repair.py`: infill from neighbours, scale re-measure, bbox after infill, `mask.tif`; `benchmark_infill.py` | 6451 / 6161 invalid vertices -> 3850 / 3595 (13-14% -> 8%); hold-out RMS 7.0 vox vs 21.5 for nearest-copy (outer ring) |
| windcheck `2b0fb2f` | `engines/selfcross.cpp` header and CLI, `tests/test_selfcross.py`, heads of `check.py` and `ct_check.py`, `pyproject.toml`; the other ~17k lines of Python were not read | `engines/selfcross.cpp`, its 11 tests | `ct_aware_check.py` (engine call + off-sheet), `phantom_defects.py`, `score_on_phantoms.py`, `trace_auditor --windcheck` | folded phantom with planted cut and crossings: correct verdicts 4/7 -> 6/7 (128), 3/7 -> 6/7 (256); see `tools/upstream/windcheck/BENCHMARK.md` |

Not done: spiral-winding-audit, vesuvius-automesh, vesuvius-unmerge (not picked: Brief 22 says exactly two); scrollreading is GPL-3.0 and was not touched. The "likely gain" column
of the draft table above is superseded for the two picks by the measured numbers; for the other four it is still unverified.
