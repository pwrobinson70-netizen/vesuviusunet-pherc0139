# tifxyz-repair

[![tests](https://github.com/Nieuwlaar/tifxyz-repair/actions/workflows/tests.yml/badge.svg)](https://github.com/Nieuwlaar/tifxyz-repair/actions/workflows/tests.yml)

**106 of the 4,922 human-verified patches feeding PHercParis4 spiral fitting carry stale `meta.json` bounding boxes, and bbox z-range filtering silently drops them from the [Vesuvius Challenge](https://scrollprize.org)'s flagship spiral-fit inputs ([villa #1272](https://github.com/ScrollPrize/villa/issues/1272)). This tool closes that bug end to end.**

- **Detect:** re-derives every patch's true bbox by replaying VC3D's loader semantics exactly, and independently reproduces the issue reporter's counts: 106/4,922 stale, 59 on z, worst offender 654 voxels adrift.
- **Repair:** `tifxyz-repair fix` rewrites a whole corpus in place, safely (atomic writes, `--dry-run`, backups). Maintainers don't even need to run it: [`audit/corrected_bboxes.json`](audit/corrected_bboxes.json) ships ready-to-apply boxes for every flagged patch.
- **Prevent:** the companion upstream fix, [villa PR #1285](https://github.com/ScrollPrize/villa/pull/1285), makes `QuadSurface` recompute the bbox at save time, with a regression test that fails without it.

Full-corpus audits establish the blast radius: all **40,782** published unverified patches and all **817** published segment meshes across 7 scrolls validate clean, so the corruption is confined to the verified/re-optimization pipeline — exactly where the most human labeling effort is at stake.

`tifxyz` is the grid-topology mesh format used by [VC3D](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer) and the whole Vesuvius segmentation pipeline: a directory of `x.tif`/`y.tif`/`z.tif` float32 coordinate grids plus a `meta.json` sidecar. Stale metadata in that sidecar is invisible until a downstream filter quietly throws away good data.

> **Related work.** [`aviad12g/tifxyz-doctor`](https://github.com/aviad12g/tifxyz-doctor) came first and is a good read-only diagnostic for the same format (metadata census, Python/C++ reader differential, sentinel-package detection). Worth using. This tool covers the other half: repairing the stale-bbox data loss, and fixing the cause upstream in VC3D.

## What it does

| Capability | Detail |
|---|---|
| **Detect stale bboxes** | Re-derives each patch's true bbox from the coordinate grids, reproducing VC3D's full loader validity rules (`z<=0`, `mask.tif`, `x==-1`; see Semantics below) and diffs it against `meta.json`. bbox-based filters (e.g. z-range selection of spiral-fit inputs) **silently drop valid patches** when the stored box is wrong. |
| **Repair them** | `fix` recomputes and rewrites the bbox in place. Atomic write (`meta.json.tmp` + rename, like VC3D), `--dry-run`, automatic `meta.json.bak`, or `--strip-bbox` to erase it instead (mirroring `vc_tifxyz_trim`). Only the `bbox` field is ever touched. |
| **Fix the root cause** | Companion villa PR makes `QuadSurface` recompute the bbox at save time, so the corruption stops being produced (see below). |
| **Guard neighboring failures** | zero/negative voxelsize (the [villa #1226](https://github.com/ScrollPrize/villa/issues/1226) class), NaN/Inf coordinates, `partial-sentinel` vertices (`y == -1` on a point the loader still keeps), malformed bboxes, grid shape/dtype/decoding errors. |
| **Deep geometry inspection** | `inspect`: interior holes, grid-spacing distortion, sheet-switch/merger suspects, normal flips, with defect-map PNGs and a VC3D point-collection export. |

All CPU-only, no GPU required. A full validate pass runs at ~1,000 patches/minute on a 16-core machine.

## Install

```bash
pip install "tifxyz-repair[deep] @ git+https://github.com/Nieuwlaar/tifxyz-repair"
# or from a checkout:
pip install -e ".[deep]"
```

Python ≥ 3.10. Core dependencies: `numpy`, `tifffile`, `imagecodecs`. The `[deep]` extra adds `scipy` + `matplotlib` for `inspect`.

## Usage

### Repair stale bboxes (the headline)

```bash
tifxyz-repair fix verified_patches/ --dry-run   # show what would change
tifxyz-repair fix verified_patches/             # recompute + write (keeps meta.json.bak)
tifxyz-repair fix patch/ --strip-bbox           # or remove bbox (mirrors vc_tifxyz_trim; VC3D recomputes lazily)
```

`fix` only ever modifies the `bbox` field; every other field is preserved (values and key order) and the file is re-serialized in VC3D's canonical writer format (indent 4, trailing newline) — so for VC3D-written files only the bbox bytes change.

### Validate one patch (or a whole tree)

```bash
tifxyz-repair validate path/to/segment.tifxyz
tifxyz-repair validate path/to/patches_dir/        # recurses
tifxyz-repair validate path/to/patch --json        # machine-readable
```

Exit code `0` = clean, `1` = at least one error-severity finding.

```
[  error] verified_patches/same_wrap002986_lasagna
    ✗ bbox-stale: stored bbox is stale: max drift 654.3 voxels, 25.6% of valid vertices outside the stored box (villa #1272)
```

### Audit a whole corpus in parallel

```bash
tifxyz-repair report verified_patches/ --workers 14 --csv audit.csv --out audit.md
```

### Deep geometry inspection

```bash
tifxyz-repair inspect segment.tifxyz --png-dir defect_maps/
```

![defect map of a real flagged patch](audit/same_wrap002986_lasagna.png)

*(`same_wrap002986_lasagna`, the worst offender named in villa #1272: 654-voxel stale bbox, 25.6% of valid vertices outside it.)*

#### Visualize findings in VC3D

```bash
tifxyz-repair inspect segment.tifxyz --export-pointset defects.json
```

Exports the flagged locations (sheet-switch suspects, interior-hole borders, worst stretched cells) as a VC3D point-collection JSON (`vc_pointcollections_json_version` `"1"`, the same format `vc_calc_surface_metrics` consumes; schema documented in [`deep.py`](src/tifxyz_repair/deep.py)). In VC3D, hit **Load** in the Points panel and pick `defects.json`: each patch shows up as `defect_switch_*` / `defect_hole_*` / `defect_stretch_*` collections overlaid at the flagged voxel positions. [`audit/demo_pointset_auto_grown_20260429215626691_sel_20260512_102916_79.json`](audit/demo_pointset_auto_grown_20260429215626691_sel_20260512_102916_79.json) is a ready-made example.

## The upstream fix

The root cause of #1272 is that `QuadSurface::bbox()` caches the box loaded from `meta.json` and only recomputes when unset, so a grid modified after load (during re-optimization, say) saves its pre-modification bbox. The companion villa PR (`1272-bbox-recompute-on-save`) resets that cache in the save path so the bbox is always recomputed from the grid actually being written, with a regression test that fails without the fix. `tifxyz-repair fix` is the cure for already-published data; the PR is the prevention.

## Use as a library

```python
from tifxyz_repair.core import load_patch, compute_bbox
from tifxyz_repair.checks import validate_patch, worst_severity

patch = load_patch("segment.tifxyz")
findings = validate_patch(patch)          # list of {check, severity, message, ...}
assert worst_severity(findings) != "error"
low, high = compute_bbox(patch)           # ground-truth bbox, full loader semantics
```

For maintainers of the affected `spiral-input` corpus: [`audit/corrected_bboxes.json`](audit/corrected_bboxes.json) contains ready-to-apply recomputed bboxes for all 137 flagged patches, so there's nothing to run.

## Semantics: matching VC3D exactly

The reference implementation for this format is C++ (`QuadSurface.cpp` in villa). Getting validity right is the whole ballgame. Replay only part of it and you get false positives, and a repair tool acting on a false positive corrupts correct data. So this reproduces the loader, not just `bbox()`:

- **Validity.** A vertex is invalid if any of these holds, in the order the loader applies them (`load_quad_from_tifxyz_impl`):
  1. `z <= 0`, which makes the loader rewrite the point to `(-1, -1, -1)` (the comment in the source reads *"Invalidate by z<=0"*). Watch the IEEE detail: `NaN <= 0` is false, so a NaN `z` stays valid. This matches that behaviour and reports it through `nan-vertices` instead.
  2. `mask.tif` present and channel 0 below 255. When the mask is an integer-multiple upscale of the grid, every mask pixel maps onto grid cell `(src // scale)`, so a vertex survives only if *all* pixels of its block pass — the loader walks pixels, not blocks.
  3. `x == -1`, the test `QuadSurface::bbox()` itself performs.

  Testing only rule 3 against the raw TIFFs counts points VC3D discards, inflating the extent. That is exactly how v0.1.0 of this tool produced 7 false positives; see [`audit/`](audit/) and the regression tests in `TestLoaderSemantics`.
- **bbox**: `[[min_x, min_y, min_z], [max_x, max_y, max_z]]` over valid vertices only.
- **meta.json writing**: indent 4, trailing newline, atomic temp-file + rename, byte-compatible with VC3D's writer.

## Real-world results

Run against the published PHercParis4 `spiral-input` verified-patch corpus (the inputs to whole-scroll spiral fitting; synced 2026-07-30), `tifxyz-repair` **independently reproduces villa #1272's figures exactly**.

Using the issue's own definition, valid vertices lying outside the recorded box, **106 of 4,922 patch directories are stale on some axis and 59 of them on z**. That matches the counts [@Nicodol reported](https://github.com/ScrollPrize/villa/issues/1272) from an independent implementation. The worst offender is the same one the issue names, `same_wrap002986_lasagna`, at 654 voxels of drift with 25.6% of its valid vertices outside the stored box (the issue reports 24.5% measured on z alone).

Counting drift in either direction raises this to 130 of 4,922. That includes boxes which over-cover: they lose no vertices, but they make bbox-based spatial queries match patches they shouldn't. Ten patches drift by more than 10,000 voxels: four under-covering, six over-covering. A further 289 snapshots under `verified_patches/backups/` bring the audited total to 5,211 patches and 137 flagged.

The *unverified* corpus is also clean: all **40,782** published unverified patch directories validate with zero findings ([`audit/unverified_audit.md`](audit/unverified_audit.md)), independently reproducing the issue's own full scan (0/40,782) and pointing at the verification and re-optimization pipeline as the source rather than patch generation.

By contrast, all **817 published segment meshes across 7 scrolls** (PHerc 139, 172, 343P, 500P2, 814, 1667, Paris 4) carry correct bboxes, which scopes this corruption to the patch and re-optimization pipeline rather than the finished flatboi output. (That check is bbox-integrity only; for *geometric* validation of published segments see [joe-carr-data/windcheck](https://github.com/joe-carr-data/windcheck), which certifies self-intersections and reaches different conclusions about segment quality on a different axis.)

A corpus-wide deep-geometry pass ([`audit/deep_audit.md`](audit/deep_audit.md)) additionally flags, among the 4,917 ordinary patches, 42 with sheet-switch/merger suspects, 615 with interior holes, and 510 with >1% stretched edges, while keeping long band surfaces separate, since their self-proximity is ordinary winding clearance. See [`audit/`](audit/) for the full reports and CSV.

## License

MIT
