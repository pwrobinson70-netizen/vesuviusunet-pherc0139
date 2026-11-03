# winding_sweep: every layer of a band, one command

```bash
pip install -r tools/winding_sweep/requirements.txt          # numpy scipy tifffile pillow zarr (+ the sibling tools in this repo)
python tools/winding_sweep/winding_sweep.py --zarr volume.zarr --z-lo 1000 --z-hi 1200 --out-dir sweep/ \
    [--height 1100] [--angle 30 --n-angles 4] [--workers 8] [--umbilicus centre.json]
# or, after pip install .:  vun-sweep ...      (--npy vol.npy also works)
```

Given a CT volume and a z band, it finds every sheet crossing along a ray from the scroll centre, numbers them outward
(winding numbers), grows one patch per crossing with `sheet_tracer`, audits every patch with `trace_auditor`, and writes
a manifest. CPU only, deterministic, no learned model. Only the band is read into memory.

| Step | What | Tools reused (imported, not copied) |
|---|---|---|
| 1 | centre line over the band (+ `--centre-margin`), or `--umbilicus FILE` | `umbilicus_finder`, `trace_auditor.Centre` |
| 2 | ray at `--height` (default band middle), `--angle` degrees from +x towards +y; mean of +/- `--ray-z-halfwidth` slices; every peak with prominence >= `--ray-prominence` x range and spacing >= `--ray-min-sep-pitch` x pitch is a crossing; numbered outward from `--first-winding` | pitch: `sheet_spacing_check.ct_pitches` (or `--pitch-vox`) |
| 3 | one seed per crossing, on the ray, at the ray height | |
| 4 | patch per seed, in parallel (`--workers`, 0 = all CPUs). Window: columns <= `--circumference-fraction` (0.9) x 2 pi r / step so it cannot run onto the next turn; rows <= band height; and `--max-rows` / `--max-cols`. Local pitch = mean gap to the neighbouring crossings | `sheet_tracer` |
| 5 | audit every patch alone, same centre line | `trace_auditor.audit` |
| 6 | manifest + summary + overlay | |

`--n-angles K` repeats the ray at K evenly spaced angles and reports which windings were found at every angle
(`windings_found_at_every_angle`) and, per patch, at how many (`found_at_angles`, `consistent`). A missing or extra
crossing at one angle (merged or crushed sheets) shifts the numbering outward of it on that ray; the consistency list
is how you see it. Patches are grown from the first angle only.

## Output (`--out-dir`)

- `patches/winding_NNN/`: tifxyz in VC3D format (`x.tif y.tif z.tif meta.json`, full-volume voxels, XYZ; meta carries
  `winding` and the verdict) and `growth_log.json`. The uuid in `meta.json` is derived from the output path.
- `overlay_z<height>.png`: the slice, the ray, the crossings and every patch's cut line, coloured by winding number (mod 10).
- `manifest.json` / `manifest.csv`: per patch `winding, seed_x/y/z, radius, pitch, patch, verdict, judged_fraction, area_vx2,
  grid_rows/cols, stop_reason, found_at_angles, consistent, reasons` (json adds the auditor's per-check statuses).
- `summary.json` / `summary.txt`: crossings per angle, consistency, verdict counts, total area, wall time, all parameters.

**Verdicts:** `PASS` / `FAIL` / `NOT JUDGED` are the auditor's own; `NO PATCH` means `sheet_tracer` rejected the seed.
`judged_fraction` = (heights where the winding check was judged + heights where the switch finder followed the patch)
/ (2 x heights). **Exit code:** 0 every patch PASS, 1 any FAIL, 4 no FAIL but some NOT JUDGED / NO PATCH, 2 bad input
(including a band outside the volume), 3 no sheet crossing found.

## Flags

Every threshold is a flag; `--help` lists them. Sweep: `--height --angle --n-angles --first-winding --ray-* --pitch-vox
--max-rows --max-cols --circumference-fraction --workers --centre-* --min-consistency`. Sub-tools: `--tracer-*`
(sheet_tracer Params except pitch/rows/cols), `--audit-*` (trace_auditor Params, e.g. `--audit-n-heights`),
`--ssf-*` (switch finder), `--uf-*` (umbilicus_finder).

## Limits

- Winding numbers are relative to the innermost crossing the ray sees (`--first-winding`). If a merged or crushed
  region hides a sheet on the ray, every number outward of it is off by one on that ray: use `--n-angles`.
- The ray is straight; the centre is the umbilicus at the ray height. A strongly off-centre or non-round scroll still works
  (peaks, not radii), but a ray that runs along a sheet for a long stretch will see it as one crossing.
- The loaded band is the whole volume for the tracer, so patches stop at the band edge; give a band at least as tall as
  the patch you want. Everything is in voxels of the level loaded (`--zarr-level`).
- One height per run. Synthetic evidence only (see the pull request for the phantom table); no real scroll has been swept.
