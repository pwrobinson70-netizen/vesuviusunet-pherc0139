# sheet_tracer: seed-grown single-sheet surface patch

```bash
pip install -r tools/sheet_tracer/requirements.txt
python tools/sheet_tracer/sheet_tracer.py --zarr volume.zarr --seed X Y Z --out patch/ \
    [--max-rows 129 --max-cols 129 --step-vox 4 --max-normal-turn-deg 30 ...]
```

Grows a patch from a seed voxel (XYZ, level-0 voxels) outward over one sheet and writes it as tifxyz
(`docs/FORMATS.md`) plus `growth_log.json`. CPU only, deterministic (same volume, seed and flags give byte-identical
x/y/z.tif and log). Exit code 0 ok, 2 bad input, 3 seed rejected. The full method is the module docstring
(`sheet_tracer.py`); in short: structure-tensor normal, step along the two in-sheet tangents by `--step-vox`,
snap to the nearest bright-sheet peak along the normal within +/- `--snap-pitch` x CT pitch, breadth-first rings.

Pitch is measured at the seed by `sheet_spacing_check.ct_pitches` (imported), or `--pitch-vox`.

## Thresholds (all flags; `--help` lists them with defaults)

| Flag | Default | Meaning |
|---|---|---|
| `--pitch-vox` | measured | CT sheet pitch; unit of the next three |
| `--snap-pitch` | 0.5 | snap window +/- x pitch |
| `--guard-pitch` | 0.5 | self-intersection distance x pitch |
| `--guard-grid-radius` | ceil(guard/step)+1 | grid Chebyshev radius around a cell that is exempt from the guard ("different row/col" = outside this radius) |
| `--step-vox` / `--step-pitch-frac` | 0.2 x pitch | arc length between grid points; meta `scale` = 1/step |
| `--max-normal-turn-deg` | 30 | reject if the normal turns more than this from an accepted neighbour |
| `--max-step-stretch` | 2.0 | extra guard: reject if the snapped point is further than this x step from a neighbour |
| `--max-rows`, `--max-cols` | 129 | growth window (seed in the middle) |
| `--peak-prominence` | 0.25 | peak prominence needed, fraction of the volume contrast (p0.5 to p99.5) |
| `--sigma-smooth`, `--sigma-grad`, `--sigma-tensor` | 1, 1.5, 3 | voxels |
| `--seed-snap-pitch`, `--seed-min-coherence` | 0.25, 0.3 | the seed must be this close to a peak and on a planar structure tensor |
| `--edge-margin` | 2 | voxels from the volume border where growth stops |

## Limits

- The scroll axis must be roughly z (rows follow z). A closed scroll turn is ONE continuous spiral sheet: a patch
  wider than one circumference winds on to the next turn by design. Limit `--max-cols` if you want one turn.
- On touching or merged sheets the tracer cannot know which sheet it is on; it can leak (numbers in the pull request).
- The whole volume level is held in memory (plus three gradient volumes). Use a lower level or crop for big scrolls.
- `no_peak`, `normal_turn` and `self_intersection` reject a point for good unless it gains a neighbour; holes can
  remain inside a patch. `growth_log.json` says where and why.
- Synthetic evidence only.
