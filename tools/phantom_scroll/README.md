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

## Harder phantoms (v0.2) - folds, delamination, tears, gaps, a local-spacing field

All OFF by default (no flag = v0.1 output, byte for byte; `tests/test_phantom_v2.py::test_defaults_unchanged`). Each feature
modifies ONE sheet (`turn`) in a window centred at angle `phi` (degrees) and height `z` (voxels, `-1` = middle):

| flag | what it does | truth surface `surfaces/turn_NN` |
|---|---|---|
| `--fold turn=2,phi=200,z=-1,len=44,zlen=90,amount=2.8,h=9` | the sheet doubles back on itself (an S-shaped pleat, up to three layers across the fold); `amount` > 1 makes it double back (the arc shift is `amount * 2 len/(2 pi)`), `h` = radial separation of the layers | follows the folded sheet (the cut line goes backwards in angle) |
| `--delam turn=2,phi=120,z=-1,len=80,zlen=110,h=8` | the sheet splits into two thin layers (0.6 x thickness) `h` voxels apart | the MID plane (no bright sheet there where the gap is wider than the thickness) |
| `--tear turn=2,phi=250,z=-1,len=60,zlen=90,gap=10,off=6` | the sheet ends, `gap` voxels are missing, and it restarts `off` voxels radially offset, relaxing back over `len/2` | piece 1, the missing stretch interpolated linearly, piece 2 |
| `--gap turn=2,phi=150,z=-1,len=56,zlen=70` | a segment of the sheet is missing (brightness removed where the window is > 0.6) | unchanged: the surface is still there, the sheet is not |
| `--spacing-ratio R` | the local sheet spacing is compressed by a smooth factor between `1/R` and `1` (angle, slowly with z), so within a slice the largest spacing is `R` times the smallest (2.5 = "up to 2.5x") | follows it |

`--preset NAME` starts from `round`, `mild`, `crushed` (= the v0.1 `bad`, which stays), `merged`, `folded`, `delaminated`, `torn`,
`gappy` or `crushed-hard` (squash 0.5, warp 8, irregular 0.15, spacing ratio 2.5); explicit flags beat the preset. Lengths in
the preset feature specs are for size 256 and scale with `--size`. Windows must stay 8 degrees away from the angle-0 seam and
radial sizes below 0.45 pitch (otherwise the nearest-sheet label is ambiguous); a violation is an error (exit 2).

**Ground truth.** `winding.npy` labels every voxel with its sheet: a folded / delaminated / torn sheet keeps its label on all
its layers and pieces, and a gap keeps its label. `severity.npy` (float32, same shape; written when a v0.2 feature or the spacing
field is on, or with `--severity`): per voxel inside the scroll the larger of (a) the feature window, a cos^2 bump that is
exactly 0 outside the window and 1 at its centre, and (b) `|ln s| / ln 4` clipped to 1, where `s` is the TRUE local radial stretch
of the whole deformation map (squash, warp, squeeze, spacing field; measured by finite differences of the forward map). So 0 =
untouched (an undeformed phantom has an all-zero map), 1 = the local spacing changed by a factor 4 or the centre of a
feature. It is 0 outside the scroll.

Limits of the v0.2 features: all radial/arc sizes are in the undeformed frame (the squash etc. then act on them); the arc
coordinate of a feature uses the sheet radius at the window centre; a feature of 0.45 pitch at most; the folded layers of
a thick sheet (> layer separation) merge into one blob; none of it is a physical model of papyrus.

## Anisotropic fibre texture (v0.3) - for judges that look at texture, not at peaks

`--fibre A` (default `0` = off: the volume, labels and `truth.json` are byte for byte the v0.2 output; `tests/test_texture_judge.py` pins hashes
taken from `main`) multiplies the sheet brightness by `1 + A * f`, where `f` is two perpendicular families of stripes **in the sheet** (the
directions are along the spiral and along z): family 1 with amplitude 1 and family 2 with amplitude `--fibre-cross` (default 0.5, so there is a
dominant direction as on real papyrus; 1 = balanced). `--fibre-period` is the stripe period in voxels (default 5; the render needs >= 2 pixels per period),
`--fibre-angle` the orientation of family 1 at the start of the spiral (degrees from the arc direction) and `--fibre-drift` the number of degrees the
orientation turns per full turn of the spiral (default 40, applied in 12 steps per turn: a smooth drift of a stripe phase field cannot keep a constant
period, so the drift is stepped). The pattern is a function of the position along the spiral, so it is continuous across the angle-0 seam and rides
along with every deformation. Two neighbouring sheets therefore differ by `--fibre-drift` degrees at the same angle: a planted switch shows as an
orientation jump of about that size. The old isotropic `--texture` stays as it was (turn it down, e.g. `--texture 0.1`, when testing fibre judges).
Not a model of real papyrus fibres: a stripe pattern with a known orientation, nothing more.

## Benchmark

`benchmark.py` builds four phantoms by default (round, mild, bad = badly crushed, merged; `--phantoms` takes any preset name, see above) with three known switches
each and scores `sheet_switch_finder`, `umbilicus_finder` and `sheet_spacing_check` against the truth. It
does not run `ink_infer` (needs torch and a checkpoint). The table and what it shows are in the pull
request that added it; rerun it to reproduce (about 4 minutes at 256^3).

## Limits

- The phantom is a smooth, noise-free-ish idealisation. Real scrolls have dust, non-uniform sheet thickness and
  brightness, ring artefacts, and delamination / tears / folds of every shape; v0.2 has idealised local versions of the
  last three (above), nothing else.
- The squeeze thins the sheet's *distance* profile with the stretch, an approximation; the surfaces are exact,
  the thickness of a merged sheet is not.
- Ink is a uniform relative brightening of the sheet under the mask, not a model of any real ink.
- The winding label is the nearest sheet by the undeformed winding coordinate; in a merged region the two
  neighbouring sheets share voxels and the label switches at the mid-gap.
