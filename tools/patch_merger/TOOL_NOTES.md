# patch_merger: notes

## What exists (step 0, 3 Nov 2026)

- `tools/upstream/` (brief 11, branch `tool/upstream-advance`): **does not exist** on origin; nothing to read.
- ThaumatoAnakalyptor `mesh_merger.py` (GPL-3; now at `ScrollPrize/villa`, `deprecated/thaumato-anakalyptor/ThaumatoAnakalyptor/`).
  Read only as a description of the approach, from the module's imports, function names and the Thaumato README. **No code was
  copied or ported; this tool was written from the brief.** What it is, as far as the public description says: it merges
  two or more *triangle meshes* (OBJ) in a given stitching order. For vertices of one mesh it finds the closest triangles of
  the other, keeps only those relations whose *winding-angle* (angle about the umbilicus) agrees, aligns the meshes,
  nudges vertices of the overlap towards each other, and adds stitching triangles along the boundary.
  (Thaumato's own README adds that the patches it merges come from a 3D instance segmentation + random-walk
  stitching, and that "better sheet stitching" is open work.)

## How this differs

| | Thaumato `mesh_merger` | `patch_merger` |
|---|---|---|
| Surface type | triangle meshes, vertex/triangle lists | tifxyz quad grids (VC3D format, `docs/FORMATS.md`); output is again one regular tifxyz grid |
| Same-sheet test | closest triangle + winding-angle agreement | distance < 0.5 pitch **and** both patches on a CT peak **and** same whole-sheet offset about the centre line (trace_auditor's pair logic), all per overlap, each reported |
| Refusal | not a feature of the description | an overlap that fails is refused with a reason; a patch with a switch is cut and the far side dropped |
| Join | stitching triangles along the boundary | no stitching: both surfaces are resampled on one grid and blended by distance-to-border weights; a gap wider than `--max-gap-pitch` is never bridged |
| Output | merged mesh | one tifxyz per connected component + seam report (JSON/text) + overlay |
| Deps | open3d, igl, GPU-free but heavy | numpy, scipy, tifffile, pillow (+ zarr for volumes) |

## Design decisions that are easy to get wrong

- **Windings of one spiral are one sheet.** A scroll is one continuous spiral. Patches that cross the angular seam, or
  chain round the scroll, are *correctly* merged into one long strip; the number of components is therefore not "number of
  turns". The scorer measures continuity along the spiral parameter, not a per-turn label (see the PR).
- **Candidates are wider than the same-sheet distance** (`--candidate-pitch` 1.5 vs `--overlap-pitch` 0.5): otherwise an
  adjacent winding (one pitch away) would never show up as an overlap and could not be refused with a reason.
- **Candidates whose nearest neighbour is within `--edge-cells` of the other segment's border are ignored**: they are the
  same sheet running on past the edge, not an overlap. Candidates are grouped into connected clusters; a cluster that is
  not mostly within 0.5 pitch is a mismatch (a patch that touches the *next* winding elsewhere does not poison a good overlap).
- **The unit of decision is a segment, not a patch.** Cuts (long grid steps, or a radius jump about the centre line) split a
  patch; the part that is anchored by an accepted overlap stays, other parts of that patch are dropped as the far side.
  Cuts run the full length of the grid line (a switch that exists at only some heights is cut at all of them): conservative.
- **Charts.** Patches have unrelated grids (different step, flipped, shifted). An affine map of each accepted partner into
  the first patch's grid is fitted to the overlap (each correspondence refined inside the cell along the local tangents);
  maps are composed along a spanning tree. Error accumulates along long chains; the overlap residual is a flag.

## Not done / not verified

- No real scroll data was used (and none may be, beyond `testdata/pherc_paris4_45um`, which has no multi-patch overlaps).
- The on-sheet test is a peak-along-normal test; on merged or crushed sheets a wrong sheet can also have a peak there.
- Overlap quality is judged on the surface; a leak that stays within half a pitch of a good patch is invisible by design.
