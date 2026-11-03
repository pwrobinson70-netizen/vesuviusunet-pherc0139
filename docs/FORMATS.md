# On-disk formats: VC3D / villa tifxyz surfaces and umbilicus files

Read from the public `ScrollPrize/villa` repository, commit `21d58da8e765014f4a3253b8048642ee377fcd6b`
(main on 3 Nov 2026). Paths are relative to the repo root; `QS` = `volume-cartographer/core/src/QuadSurface.cpp`.
Nothing here was run against real scan data. Where villa code and its comments disagree, the code is
quoted. Tests that build files this way: `tests/test_vc3d_formats.py`, writers in `tests/vc3d_writers.py`.

## 1. tifxyz surface (a directory)

| File | Content |
|---|---|
| `x.tif`, `y.tif`, `z.tif` | one file per coordinate; the grid of surface points, **XYZ in level-0 volume voxels** |
| `meta.json` | scale, bbox, uuid, format, type (+ optional `tags`, `components`, ...) |
| `mask.tif` (optional) | per-vertex validity |
| other optional | `winding.tif`, `overlapping.json`, `generations.tif`, ... (not used by our tools) |

**Data layout.** The points are a `cv::Mat_<cv::Vec3f>`; the writer `cv::split`s it and writes three
single-channel files (`QS:2241-2250`, `writeDataToDirectory`): `x.tif` = channel 0 = **x**, `y.tif` =
channel 1 = **y**, `z.tif` = channel 2 = **z**. Each is `CV_32FC1` -> 32 bit, `SAMPLEFORMAT_IEEEFP`
(`volume-cartographer/core/src/Tiff.cpp:27`), **float32**, shape **(H, W) = (rows, cols)**, written
untiled and uncompressed (`writeTiff(..., tileW=0, tileH=0, COMPRESSION_NONE)`). Axis order of a pixel
`(row r, col c)`: point `(x, y, z) = (x.tif[r,c], y.tif[r,c], z.tif[r,c])`. Rows are the grid "v"
direction and columns the grid "u" direction. The reader also accepts tiled files and uint/int/float
8-64 bit samples, converting to float32 (`QS:2659-2680`, `read_band_into` at `QS:2758-2766`). A
volume array is indexed `[z, y, x]` but the surface is stored as **x, y, z**; the Python
`spiral-fitting/tifxyz.py:403` stacks `[z, y, x]` after loading, so a Python user sees reversed order.

**Invalid points.** The marker is the triple **(-1, -1, -1)** in all three files.
- `QS:330-334` `isValidPointSample`: invalid if any component is `-1.0f` or non-finite.
- `QS:2768-2774`: after loading, any vertex failing the store rule is rewritten to `(-1,-1,-1)`.
- The object-store rule (`vc_object_store/include/vc_object_store/geometry/Geometry.hpp:80-85`,
  `validSurfacePoint`) is stricter: any component not finite or `== -1`, **and `z > 0` required**.
- Quirk: `QuadSurface::bbox()` (`QS:2572-2587`) and `bbox_of_valid_points` (`QS:2989-3010`) test only
  `x != -1`.

**`mask.tif`** (`QS:2776-2840`): optional, 8/16/32-bit int or float, one channel. A vertex is valid if
mask `>= 255`; `0` means invalid. The mask may be a whole multiple of the grid size (each vertex is
valid only if every mask pixel it covers is `>= 255`; `vc_object_store/src/spatial/SurfaceGrid.hpp:25-28`).
Masked-out vertices **keep their real coordinates** in x/y/z. (`spiral-fitting/tifxyz.py:383-405` sets
`zyxs[mask == 0] = -1` for exactly this reason.)

**`meta.json`** (written at `QS:2454-2476`, `QS:2415` `saveWithUuid`):

| Key | Value |
|---|---|
| `scale` | `[sx, sy]`, **grid cells per voxel**; `sx` for columns (u, x-direction of the grid), `sy` for rows. Grid spacing in voxels = `1/scale`. Required: the loader throws "Missing or invalid surface scale" unless it is an array of >= 2 finite numbers > 0 (`QS:361-392`). Nominal size in voxels = `cols/sx`, `rows/sy` (`QS:1130-1134`). |
| `bbox` | `[[xmin, ymin, zmin], [xmax, ymax, zmax]]` of the valid points, **XYZ order** (`QS:2461-2467`; `rect_from_json`, `QS:983-987`). `spiral-fitting/tifxyz.py:357-364` warns that "producers have emitted multiple bbox axis orders" and does not trust it; so do we (no tool reads `bbox`). |
| `format` | `"tifxyz"` |
| `type` | `"seg"` |
| `uuid` | string |
| optional | `tags` (object, keys are tags), `components` (list of `[a, b]`), `area_cm2`, `area_vx2`, `source`, ... |

`spiral-fitting/tifxyz.py:431-465` (`save_tifxyz`) writes `scale = [1/step, 1/step]`, `bbox` from the
valid points reversed from zyx to xyz, `area_vx2`, `area_cm2`, `format`, `type`, `uuid`, `source`, and
x/y/z via PIL as float32. No voxel-size key is part of the tifxyz meta; our readers look for
`voxelsize`-style keys that VC3D does not write (harmless: they fall back to `None`).

## 2. Umbilicus (scroll centre line)

Three encodings exist in villa; all give ordered control points of the centre line in level-0 voxels.

1. **JSON `control_points`** (read by `spiral-fitting/umbilicus.py:25-33`, `json_umbilicus_z_to_yx`):
   `{"control_points": [{"z":.., "y":.., "x":..}, ...]}`, sorted by `z`, linearly interpolated and
   extrapolated; optional `coordinate_scale`/`downsample_factor` multiplies coordinates. The C++
   store reader also accepts it (`vc_object_store/src/UmbilicusFile.cpp:125-166`, `readJsonFile`):
   a bare array of `[z, y, x]` triples, or an object with `points` or `control_points` holding either
   `[z, y, x]` arrays or `{z, y, x}` objects; optional `metadata` with `voxelsize_um`, `volume`,
   `volume_width`, `volume_height`, `volume_slices` (a complete positive triplet, or a voxel size,
   states the frame the points are in).
   **Our `umbilicus_finder` writes this one** (`uf_io.write_villa_json`).
2. **Native store file** (`vc_object_store/src/formats/GeometryOutput.cpp:66-75`,
   `formats/UmbilicusInput.cpp`): `{"vc_umbilicus_json_version": "1", "points": [{"x":..,"y":..,"z":..}], "uuid":.., ...}`
   (object keys, so no order ambiguity). We neither read nor write it.
3. **Text.** Two different conventions, both integer-ish "a, b, c" per line:
   - villa **"thaumato"** text (`spiral-fitting/umbilicus.py:6-13`): `np.asarray(rows)[:, [2, 0, 1]] - 500`,
     then `zs = col[:,2]`, `xys = col[:,:2]`, flipped to `yx`. Working it through, each line is
     **`y, z, x`, each with +500 added**. (The `+500` is a Thaumato offset that is not documented
     in villa.) Our `tools/umbilicus_finder/TOOL_NOTES.md` says "`x,y,z`"; that is wrong, see mismatch M4.
   - store text import (`UmbilicusFile.cpp:45-77`): **`z, y, x`** per line, no offset, `#` comments and
     blank lines skipped.

## 3. What our readers assume, and the result of the check

| Reader | Assumption | Verdict |
|---|---|---|
| `ssc_io.load_mesh` (`tools/sheet_spacing_check/ssc_io.py:42-94`) | x/y/z.tif -> separate (H, W) arrays; invalid = non-finite or any coordinate `== -1`; scale = `(scale[0], scale[1])` = (columns, rows) | axis order, dtype, scale, sentinel and partial sentinel **match** (tested, tiled and untiled) |
| `ink_infer/surface.py` `load_mesh`/`resample_mesh` (`:19-96`) | `P[r,c] = (x,y,z)`; `scale[0]` <-> columns, `scale[1]` <-> rows; step = `1/scale` | **match** (tested with anisotropic scale and non-square grid) |
| `uf_io.write_villa_json` (`tools/umbilicus_finder/uf_io.py:195-206`) | `{"control_points": [{z,y,x}]}` sorted by z | **matches** villa readers (1) |
| umbilicus *readers* | none exist in our tools | gap, not a mismatch (Part D adds one) |

### Mismatches (carried into Part B as bugs)

- **M1 / BUG-A1: `mask.tif` is ignored** by `ssc_io.load_mesh` and `ink_infer/surface.load_mesh`.
  VC3D marks cells invalid with a mask while x/y/z keep real values, so our tools treat masked-out
  cells as valid surface. (`tests/test_vc3d_formats.py`: two strict xfails.)
- **M2 (RISK): `z <= 0` and the store rule.** The store's `validSurfacePoint` requires `z > 0`; core VC3D
  (`isValidPointSample`) and our readers do not. A point with `z == 0` is valid for us and invalid for
  the store. Documented only; core VC3D is the reference for files written by VC3D.
- **M3 (RISK): silent scale fallback.** VC3D throws on a missing/invalid `scale`. `ssc_io` quietly sets
  `scale=None` (the measured spacing is used instead; the spacing tool just skips its cross-check);
  `ink_infer` raises only when `resample_mesh` is called.
- **M4 (doc): `TOOL_NOTES.md` thaumato order** says `x,y,z`; the villa code is `y, z, x` + 500.
- **M5 (doc): `meta.json` voxel size.** We look for `voxelsize`/`voxel_size*` keys; tifxyz does not carry one
  (only `area_cm2`/`area_vx2`, which fix it indirectly). `--voxel-size-um` must be given when it matters.
