# windcheck engine (upstream: joe-carr-data/windcheck, MIT) + our CT-aware check

**Who wrote what.** `engines/selfcross.cpp` and `tests/test_selfcross.py` are Josep Carreras' work (GitHub joe-carr-data/windcheck, MIT; `LICENSE` is theirs;
commit and the list of what we did not take in `ATTRIBUTION.md`), copied unchanged. `ct_aware_check.py`, `phantom_defects.py`, `score_on_phantoms.py` are ours.

Upstream's engine answers one question exactly: do the triangles of a tifxyz trace pass through each other? (Proximity is ambiguous in a crushed
scroll, crossing is not.) It knows nothing about the CT. We add the CT question, "is the trace on a sheet at all?", and combine them into one verdict.

```
python ct_aware_check.py TRACE.tifxyz --zarr VOL.zarr --pitch-vox 22     # or --npy VOL.npy
python score_on_phantoms.py --size 128                                    # before/after table on a folded phantom with planted defects
python tools/trace_auditor/trace_auditor.py A.tifxyz --zarr VOL.zarr --out-dir OUT --windcheck [--wc-max-off-fraction 0.1 ...]   # one more verdict
```

| Check | What | Flags (defaults in `--help`; with trace_auditor prefix `--wc-`) |
|---|---|---|
| self_intersection | upstream engine, both quad diagonals; FAIL at >= N transverse pairs that both diagonals confirm; coplanar and grazing are reported, never failed | `--min-crossings 1`, `--any-diagonal`, `--exclude 2`, `--max-edge 60`, `--cell 40`, `--threads` |
| off_sheet | CT sampled along the normal at every k-th vertex; on a sheet if the nearest bright ridge is within 0.2 pitch; FAIL if > 10% of judged vertices are off, or if any 6x6-sample window is >= 50% off; NOT JUDGED where the profile is bright everywhere | `--pitch-vox` (trace_auditor: measured), `--stride`, `--half-range-pitches`, `--off-tol-pitches`, `--min-contrast`, `--solid-frac`, `--max-off-fraction`, `--block*`, `--min-judged-fraction` |

**Requires** a C++ compiler (g++ or clang++) for the engine, built automatically into `engines/selfcross` (git-ignored); without one the check is NOT JUDGED, never PASS.
CPU only. Bright sheets on a darker background assumed.

**Limits, stated plainly.** The off-sheet check cannot tell the right sheet from a wrong one (a trace on a neighbouring sheet is on a sheet): that stays
with trace_auditor's winding checks. Crossings and off-sheet vertices are evidence of a defect, not proof of a tracing error. All thresholds are defaults chosen on
synthetic phantoms (see BENCHMARK.md for what was and was not tuned); none has been calibrated on real scroll data. The sample meshes of this repository have no CT
volume here beyond three PNG slices, so the real-data behaviour of the off-sheet check is unverified.
