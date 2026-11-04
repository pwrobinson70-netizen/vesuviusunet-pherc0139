# Attribution: windcheck

| | |
|---|---|
| Upstream project | windcheck ("Cross-winding consistency checking and repair for Herculaneum scroll segmentations") |
| Repository | https://github.com/joe-carr-data/windcheck |
| GitHub owner | joe-carr-data |
| Author as in `LICENSE` | Josep Carreras (Copyright (c) 2026) |
| Licence | MIT, `LICENSE` in this folder is the upstream file, byte for byte |
| Commit taken | `2b0fb2f3d305d3727dcb24a8eaa73c3c8ce5c3ce` |

## What came from upstream, unchanged (byte-identical copies)

- `engines/selfcross.cpp` — the exact self-intersection census (triangle/triangle interval test, TRANSVERSE / COPLANAR / GRAZING, adjacency
  excluded by grid index, `maxedge` filter, both quad diagonals).
- `tests/test_selfcross.py` — upstream's test of that engine (11 tests, builds its own WCAT atlases), kept passing.
- `UPSTREAM_README.md`, `UPSTREAM_pyproject.toml` — upstream's `README.md` and `pyproject.toml`, renamed only.
- Not copied: the rest of `src/windcheck/` (tifxyz and zarr readers, repair/excise, pipeline, certificates, the CLI), `bench/`, `docs/`, `data/`, `out/`,
  `case-studies/` (about 41k lines including results). We did not read all of it; the choice was to take the one component the new check needs.

## What we added (our code, separate files; MIT like the rest of this repository)

- `ct_aware_check.py` — runs upstream's engine on a trace (both diagonals) and adds a CT-aware off-sheet check (profile along the surface normal,
  nearest bright ridge); one verdict. `build_engine()` compiles upstream's `selfcross.cpp` with g++/clang++ if the binary is missing.
- `phantom_defects.py`, `score_on_phantoms.py`, `BENCHMARK.md` — planted cut and crossing on a phantom_scroll v2 folded sheet, and the before/after table.
- `tests/conftest.py` — builds the engine before upstream's test is collected.
- `README.md` (ours), `requirements.txt`, `ATTRIBUTION.md`, `.gitignore` (the compiled engine).
- `tests/test_windcheck_ct.py` (in the repository's `tests/`), and a `windcheck` verdict hook plus `--windcheck` / `--wc-*` flags in
  `tools/trace_auditor/trace_auditor.py` (off by default).

The off-sheet idea is related to upstream's `ct_check.py` ("missed-sheet signature"), which we did not use and did not copy; ours is a different, simpler test.
