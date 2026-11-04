# texture_judge: the eye test, automated

Every other judge here (spacing, switch finder, auditor, winding, crush map) starts from bright-peak detection along the surface normal. If
that is wrong they are all wrong together. `texture_judge` judges from a **different signal**: the papyrus fibre texture on the rendered
surface, which is what a person checks by eye in a VC3D surface render. CPU only, deterministic, no extra packages beyond numpy, scipy,
tifffile, pillow (zarr for OME-Zarr input).

```bash
pip install -r tools/texture_judge/requirements.txt
python tools/texture_judge/texture_judge.py trace.tifxyz --zarr volume.zarr --heights 60,80,100 --out-dir out/
python tools/texture_judge/texture_judge.py trace.tifxyz --png-dir slices --png-pixel-um 45.532 --voxel-size-um 45.532 --heights 2073,2600 --out-dir out/
```

## What it does

1. **Render** (`--mode surface`, needs a real 3-D volume: OME-Zarr or a dense stack of PNGs). The CT is sampled trilinearly on the tifxyz
   surface and at `+k` and `-k` voxels along the local normal (`--k`, default 2, so layers 0, +2, -2), one flat image per layer in grid
   coordinates (rows x cols) like a VC3D surface render, `--pixel-vox` voxels per pixel (default 1: the grid is much coarser than the fibres).
   Invalid grid cells and points outside the volume are NaN. PNGs: `surface_k+0.png`, `surface_k+2.png`, `surface_k-2.png`.
2. **Fibre field.** Structure tensor of the surface layer: Gaussian derivatives at `--grad-sigma`, orientation = the dominant direction, coherence
   = |sum| / energy over a window. `--symmetry 2` (default) is the classic tensor (orientation mod 180, differences 0-90 deg). Two
   perpendicular families of equal strength cancel in the classic tensor; `--symmetry 4` uses the fourth-order tensor (orientation mod 90,
   differences 0-45) for that case. `fibre_orientation.png` shows hue = orientation, brightness = coherence.
3. **Continuity**, per window (`--window` pixels square, default 32):
   (a) orientation discontinuity = angular difference of the windows' dominant orientations, wrapped to 0-90 deg;
   (b) texture presence = coherence (`--min-coherence`) and local contrast, the std of the smoothed render in the window, volume scaled to 0..1 (`--min-contrast`);
   (c) layer agreement = correlation of the surface render with the +k and -k renders (`--min-agreement`; the smaller of the two): a surface in the middle of a sheet correlates with both, one on the edge or in the gap does not.
4. **Verdict** per window: `ON-SHEET-TEXTURED` (coherence, contrast and agreement all above their flags); `BREAK` (orientation jump above
   `--max-jump-deg` held over `--break-run` textured windows on each side, with at most `--break-gap` non-textured windows between: the window that
   straddles the jump is marked, or both neighbours when there is none); `BLURRED` (coherence AND contrast both low = off papyrus, or the layers disagree);
   `NOT JUDGED` (fewer than `--min-valid-fraction` of the pixels valid, or one of coherence / contrast low and the other not).
   Also per cut line at `--heights` (the same cut lines the other tools use), with a list of BREAK locations (grid row/col and voxel xyz), and
   `overlay.png` with the windows tinted by verdict and the breaks in red. Fractions of each verdict are in `texture_judge.json`.

Exit code: 0 no BREAK and BLURRED <= `--max-blurred-fraction` of the judged windows; 1 otherwise; 2 bad input; 4 fewer than `--min-judged-fraction` judged.
Every threshold is a flag (`--help`); the defaults were set on the phantom, NOT on real data.

## Sparse volumes: `--mode section`

The real test samples hold three slice PNGs. A surface render needs the volume around the surface, so there only the cut line at each slice
height can be rendered, as a **straightened cross-section**: the slice sampled at offsets `-h..+h` (`--section-halfwidth`, default 12 voxels) along the
in-plane normal, one column per `--pixel-vox` of arc length along the cut line (`section_z*.png`). The `+-k` layers are the same section shifted by `k`.
`--mode auto` (default) picks section when the surface's z range holds fewer than `--min-slices` slices; `--heights` is then required.

## Limits (read before trusting a PASS or a FAIL)

* A trace that starts on the **wrong sheet and stays on it** is not flagged: a continuity judge cannot know which sheet was wanted (same limit as the switch finder). Tested and documented.
* The texture judge is only as independent as its render. The render uses the same mesh, so a mesh that is off the sheet everywhere is seen (BLURRED), but it samples the volume at the mesh position and does not search for a peak.
* **Section mode has no fibre direction relative to the sheet frame**: the straightened section shows the band of the sheet and the streaks along it, so every sheet looks alike and a jump from one sheet to the next does not change the orientation. On the real samples it therefore cannot see a sheet switch; see `docs/texture_judge/RESULTS.md` for what it does report.
* Orientation is mod 180 (or mod 90): a 90 deg change of fibre direction is invisible with `--symmetry 4`.
* Defaults for a real scan are unknown: real papyrus has weaker, scale-dependent texture than the phantom's stripes. Calibrate `--grad-sigma`, `--window`, `--min-coherence`, `--min-contrast` on traces a human has judged before relying on it.

## Tests and pictures

`tests/test_texture_judge.py`: true round textured phantom trace >= 95% ON-SHEET-TEXTURED of the judged windows and no BREAK; planted switch -> BREAK within
3 windows of the planted column; trace shifted into the gap -> BLURRED; trace on the wrong sheet -> no BREAK (the known limit); determinism; bad inputs; real
samples as a smoke test (numbers reported, not asserted). `phantom_cases.py` builds the cases (shared with `tools/judge_panel`). `realdata_report.py`
re-creates `docs/texture_judge/` (numbers and the first pictures of real papyrus texture through this pipeline).
