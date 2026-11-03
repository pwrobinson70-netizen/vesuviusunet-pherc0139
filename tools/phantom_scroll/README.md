# phantom_scroll: a synthetic rolled scroll with known ground truth

Small synthetic CT volumes (default 256^3) of a rolled papyrus scroll, plus the exact truth for everything
a trace-checking tool is asked about. CPU only, seeded, deterministic (same flags and seed -> byte-identical
files). Nothing here is real scan data and nothing is calibrated to any real scroll: use it to find out
whether a tool can fail, not to claim it works.

```bash
pip install -r tools/phantom_scroll/requirements.txt
python tools/phantom_scroll/phantom_scroll.py --out ph --size 256 --turns 4 \
    --squash 0.7 --warp-amp 6 --merge-strength 0.8 --ink \
    --bad-switch turn=1,col=40,delta=1 --bad-switch turn=2,col=90,delta=-1,width=4 --bad-pairs
python tools/phantom_scroll/benchmark.py --size 256 --json bench.json      # all tools, scored table
```

## Model

The scroll axis is z. In each xy plane the sheet is an Archimedean spiral `r = r0 + pitch * (w + phi / 2 pi)`
(`--irregular` adds a smooth wobble of that fraction of the pitch; it must be < 0.30, above which neighbouring turns cross and the tool refuses); sheet `k` is winding `w = k`,
`k = 0 .. turns-1`. Sheet profile: Gaussian, FWHM `--thickness`; brightness texture (`--texture`), white
noise (`--noise`). Deformation `T`, applied to **everything**: axis drift (`--tilt`), affine squash about the
axis (`--squash`, `--squash-angle`), a smooth non-rigid warp (`--warp-amp`, `--warp-wavelength`; a few random
sinusoids, small z component) and an optional local radial **squeeze** (`--merge-strength`, `--merge-turn`,
`--merge-phi`, `--merge-z`, `--merge-sigma`) that pulls neighbouring sheets together until they touch
(sheet thickness stays fixed, the pitch there shrinks to `1 - strength` of normal; at 0.8 with a 6-voxel
sheet and a 22-voxel pitch the gap closes). The volume is rendered by inverting `T` (fixed point, error
< 0.01 voxel, tested); the truth is pushed through the forward `T`, so it is exact for the volume.

## Outputs (`--out DIR`)

| Path | Content |
|---|---|
| `volume.zarr` | OME-Zarr (zarr_format 2, level 0 uint8 and level 1 half size, scale transforms 1 / 2); `--no-zarr` to skip |
| `volume_png/00000.png ...` | with `--png`: one 8-bit PNG per z slice |
| `surfaces/turn_NN/` | true surface of turn NN as **tifxyz** exactly as VC3D writes it (docs/FORMATS.md): `x.tif y.tif z.tif` float32 (rows, cols) with rows along z and columns along the angle, `(-1,-1,-1)` where the surface leaves the volume, `meta.json` with `scale = [1/grid_step, 1/grid_step]`, `bbox`, `format`, `type`, `uuid`. All surfaces share one grid shape |
| `centreline.csv`, `centreline_villa.json` | true axis `z,y,x` per slice (CSV) and `{"control_points": [{z,y,x}]}` (villa umbilicus JSON) |
| `winding.npy` | int16 `(z, y, x)`: turn index of the nearest sheet inside the scroll, `-1` outside |
| `ink_mask.png` | with `--ink`: letter mask on the grid of turn `--ink-turn` (same shape as that tifxyz); the voxels of that sheet under the mask are `--ink-delta` brighter |
| `bad/switch_NN/` | with `--bad-switch SPEC`: a trace that follows `turn` and from column `col` (rows >= `row0`; linear ramp over `width` columns) follows `turn + delta` |
| `bad/pair_{adjacent,skipped,shared,off_sheet}/` | with `--bad-pairs`: B traces for A = `surfaces/turn_01`: turn 2 (clean), turn 3 (skipped sheet, ratio 2), turn 1.15 (shared, ratio 0.15), turn 2.42 (in the dark gap, ratio 1.42) |
| `truth.json` | all parameters, grid size, switch records (trace, turn, column, direction, ...), pair records with the expected verdict, ink record |

## Benchmark

`benchmark.py` builds four phantoms (round, mild, bad = badly crushed, merged) with three known switches
each and scores `sheet_switch_finder`, `umbilicus_finder` and `sheet_spacing_check` against the truth. It
does not run `ink_infer` (needs torch and a checkpoint). The table and what it shows are in the pull
request that added it; rerun it to reproduce (about 4 minutes at 256^3).

## Limits

- The phantom is a smooth, noise-free-ish idealisation. Real scrolls have delamination, tears, dust,
  non-uniform sheet thickness and brightness, ring artefacts; none of that is here.
- The squeeze thins the sheet's *distance* profile with the stretch, an approximation; the surfaces are exact,
  the thickness of a merged sheet is not.
- Ink is a uniform relative brightening of the sheet under the mask, not a model of any real ink.
- The winding label is the nearest sheet by the undeformed winding coordinate; in a merged region the two
  neighbouring sheets share voxels and the label switches at the mid-gap.
