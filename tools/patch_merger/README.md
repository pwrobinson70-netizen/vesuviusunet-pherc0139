# patch_merger: merge tifxyz patches, only where the overlap is provably one sheet

```bash
pip install -r tools/patch_merger/requirements.txt
python tools/patch_merger/patch_merger.py sweep_a030/patches sweep_a120/patches --out-dir merged/ \
    --zarr volume.zarr [--umbilicus centre.json] [--pitch-vox 11] [--scale 0.5]
# or, after pip install .:  vun-merge ...      (--npy vol.npy also works)
```

Input: tifxyz directories, or directories holding tifxyz directories (e.g. `winding_sweep`'s `patches/`), all of one volume
(level-0 voxel coordinates, `docs/FORMATS.md`). The method is the module docstring; in short:

1. **Cut** each patch where it switches sheet (a grid line of long steps, or a radius jump about the centre line); keep
   what is on either side as *segments*.
2. **Find overlaps** between segments of different patches (bounding box, then point distance).
3. **Gate** each overlap: same sheet (distance < `--overlap-pitch` x pitch), both on a CT peak, same whole-sheet offset about
   the centre line, and the two grids can be registered. A check that cannot run refuses the overlap (`--allow-unjudged` to relax).
4. **Merge** accepted overlaps into connected components; resample each component onto one regular grid
   (spacing `1/--scale` voxels), blending overlaps by distance-to-border weights. Invalid points stay `-1`.
5. **Report** every overlap and every cut, accepted or refused, with the reason.

## Output (`--out-dir`)

- `component_NNN.tifxyz/`: `x.tif y.tif z.tif meta.json` (VC3D format; meta has `scale`, `bbox`, `area_vx2`,
  `source_patches`, `source_segments`, `n_bridged_nodes`, and `area_cm2` with `--voxel-um`).
- `seam_report.json` / `seam_report.txt`: per patch the cuts and segments (kept / dropped, why); per overlap `status`,
  `reason`, counts, each check's result (`shared_sheet`, `on_sheet`, `winding`), centroid, registration; per component the
  members, area and grid; a summary with refusal counts by reason.
- `overlay.png`: x-y projection, inputs coloured by patch (left), merged components (right); overlaps marked green
  (accepted) or red (refused) with their number in the report.

Refusal reasons: `shared-sheet mismatch` (distance or winding offset), `off-sheet`, `not judged` (no volume / centre line),
`registration`. A segment cut off from an anchored part of its patch is `dropped: far side of ...`.

## Flags

Every threshold is a flag; `--help` lists them with defaults. Pitch: `--pitch-vox`, `--n-pitch-heights`. Cuts:
`--max-edge-stretch --cut-fraction --cut-margin --min-segment-points`. Overlap: `--overlap-pitch --candidate-pitch
--edge-cells --min-overlap-points --min-same-fraction`. Gate: `--on-sheet-pitch --on-sheet-halfwidth-pitch
--on-sheet-contrast --on-sheet-fraction --max-check-points --winding-heights --winding-tol --winding-fraction
--allow-unjudged --max-register-residual`. Output: `--scale --max-gap-pitch --max-grid-cells --voxel-um`. Centre line:
`--umbilicus --umbilicus-format --umbilicus-scale --no-centre`; the winding-jump detector's thresholds are
`--audit-wn-*` (trace_auditor's). Exit code 0 done, 2 bad input.

## Scoring

`python tools/patch_merger/score_on_phantoms.py --size 192` (see its docstring and the pull request): runs `winding_sweep`
at four ray angles on each phantom preset, merges everything, and compares with the truth.

## Limits

- Phantom evidence only. No real scroll has been merged.
- A scroll is one spiral: a correct merge of patches that chain round the scroll is one long strip, not one component per turn.
- Registration is affine per overlap and composed along a spanning tree; error grows along long chains (the residual is reported).
- Overlap is judged on the surface and on the CT peak; a leak that stays within half a pitch of a good patch is not seen.
- Cuts are made along whole grid lines. The far side of a cut is dropped only if another part of the same patch is anchored.
