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
