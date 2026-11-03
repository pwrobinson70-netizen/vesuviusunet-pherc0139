# Attribution: tifxyz-repair

| | |
|---|---|
| Upstream project | tifxyz-repair |
| Repository | https://github.com/Nieuwlaar/tifxyz-repair |
| GitHub owner | Nieuwlaar |
| Author as in `LICENSE` | "tifxyz-repair contributors" (Copyright (c) 2026); `pyproject.toml` lists the author as "Nieuwlaar" |
| Licence | MIT, `LICENSE` in this folder is the upstream file, byte for byte |
| Commit taken | `4d6c98d95b71aa94dfed9398fbfe592419e62763` ("segments_audit: update unverified-patch count ...") |

## What came from upstream, unchanged (byte-identical copies)

- `tifxyz_repair/` — the package (`core.py`, `checks.py`, `repair.py`, `deep.py`, `report.py`, `cli.py`, `__init__.py`): loader with VC3D validity
  semantics, validation checks, stale-`bbox` detection and repair, `inspect`.
- `upstream_tests/test_repair.py` — upstream's test file, 39 tests, kept passing.
- `UPSTREAM_README.md`, `UPSTREAM_pyproject.toml` — upstream's `README.md` and `pyproject.toml`, renamed only so they do not collide with ours.
- Not copied: upstream's `audit/` folder (data and reports), `.github/`.

## What we added (our code, separate files; MIT like the rest of this repository)

- `geometric_repair.py` — infill of invalid vertices from neighbours, scale re-measurement, bbox recompute after infill, `mask.tif` generation,
  a hold-out benchmark. It *imports* upstream's `load_patch` and `compute_bbox`; it does not modify them.
- `benchmark_infill.py`, `BENCHMARK.md` — before/after numbers.
- `upstream_tests/conftest.py` — three lines that make the vendored package importable for its tests.
- `README.md` (ours), `requirements.txt`, `ATTRIBUTION.md`.
- `tests/test_geometric_repair.py` (in the repository's `tests/`).

Upstream only repairs the `bbox` field of `meta.json`; everything above that touches vertices, `scale` or `mask.tif` is ours.
