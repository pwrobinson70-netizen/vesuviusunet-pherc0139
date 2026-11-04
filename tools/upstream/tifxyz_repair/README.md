# tifxyz_repair (upstream: Nieuwlaar/tifxyz-repair, MIT) + our geometric repair

**Who wrote what.** The `tifxyz_repair/` package and `upstream_tests/` are the work of Nieuwlaar / the tifxyz-repair contributors, copied unchanged
(MIT, `LICENSE` is theirs; commit and details in `ATTRIBUTION.md`). `geometric_repair.py`, `benchmark_infill.py` and `tests/test_geometric_repair.py` are ours.

Upstream validates tifxyz patches and repairs stale `bbox` metadata. We add the geometric repairs it does not do:

```
python geometric_repair.py PATCH.tifxyz --out FIXED.tifxyz        # new directory; x/y/z/mask.tif/infilled.tif/meta.json
python geometric_repair.py PATCH.tifxyz --dry-run                 # report only
python benchmark_infill.py testdata/pherc_paris4_45um/*.tifxyz    # before/after table (see BENCHMARK.md)
```

| Step | What | Flags (all defaults documented in `--help`) |
|---|---|---|
| infill | invalid vertices re-estimated by a plane fit to the original valid neighbours (grid coordinates), up to N rings away; edge cells are extrapolated | `--max-rings 3` (0 = off), `--fit-radius 2`, `--min-neighbours 6`, `--max-residual-frac 0.5` |
| scale | measured from the median spacing of valid neighbours; reported, rewritten only with `--fix-scale` | `--fix-scale`, `--scale-tolerance 0.02` |
| bbox | recomputed after infill with upstream's rule | none |
| mask | `mask.tif` uint8, 255 valid / 0 invalid (VC3D: `>= 255` valid), shape = grid; also `infilled.tif` marks invented vertices | `--mask-threshold 255` |

Formats follow `docs/FORMATS.md`: x/y/z float32 (H, W), invalid marker (-1,-1,-1) in all three, any component `== -1`, non-finite, `z <= 0` or mask `< 255` counts as invalid.
`--in-place` keeps `*.bak`; without `--out`, `--in-place` or `--dry-run` nothing runs.

**Limits, stated plainly.** Infill invents surface. On the public Scroll 1 sample meshes (about 6k invalid vertices each, 13-14% of the grid, mostly a ragged
boundary) it fills only the cells within 3 steps of valid data (about 2.6k of 6.4k) and leaves the rest invalid. The hold-out error (BENCHMARK.md) is about 7 voxels RMS
for the outermost ring (grid step about 20 voxels), growing to about 12 at three rings; those are extrapolations on a smooth patch and will be worse at folds
(fits with a large residual are refused, which is a heuristic, not a guarantee). Nothing here checks the result against CT.

Requirements: `requirements.txt` (numpy, tifffile, scipy). CPU only.
