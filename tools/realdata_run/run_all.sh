#!/usr/bin/env bash
# Commands used for Brief 14 (3 Nov 2026). Run from the repo root. No tool default was changed.
set -u
SL=testdata/pherc_paris4_45um/slices; O=tools/realdata_run/out; T=${TMPDIR:-/tmp}/realdata_tmp; mkdir -p $O $T
A=$(ls -d testdata/pherc_paris4_45um/*w116-117.tifxyz); B=$(ls -d testdata/pherc_paris4_45um/*w118-119.tifxyz)
python tools/realdata_run/task1_format.py > $O/task1_format.txt
# 2. umbilicus_finder: PNG dir -> slice INDEX is used as z (0,1,2); relabel 2073,2600,3128 afterwards.
#    --pitch-vox 8 passed because the default pitch search finds none (no_pitch). Measured: measure_pitch.py
python tools/umbilicus_finder/umbilicus_finder.py testdata/pherc_paris4_45um/slices --pixel-um 45.532 --voxel-um 45.532 \
   --z-start 0 --z-stop 3 --z-step 1 --pitch-vox 8 --out-dir $T/uf --overlays --export-all
# 3. spacing: grids differ in shape (130x354 vs 129x357) -> padded temp copies (flag-less workaround)
python tools/realdata_run/pad_meshes.py $T/pad
python tools/sheet_spacing_check/sheet_spacing_check.py $T/pad/*w116-117.tifxyz $T/pad/*w118-119.tifxyz --png-dir $SL \
   --png-pixel-um 45.532 --voxel-size-um 45.532 --heights 2073,2600,3128 --out-json $O/spacing/default.json \
   --out-txt $O/spacing/default.txt --overlay-dir docs/realdata/spacing_default
# sensitivity only: add --peak-prominence-frac 0.05
python tools/realdata_run/measure_pitch_normals.py; python tools/realdata_run/task3_align.py; python tools/realdata_run/task3_stack.py
# 4. switch finder, each mesh alone, defaults
for m in $A $B; do python tools/sheet_switch_finder/sheet_switch_finder.py $m --png-dir $SL --png-pixel-um 45.532 \
   --voxel-size-um 45.532 --heights 2073,2600,3128 --out-json $O/switch/$(basename $m).json --overlay-dir docs/realdata/switch_$(basename $m); done
# 5. auditor, estimated centre file (umbilicus_estimated.json = LOW finder output relabelled to true z)
python tools/trace_auditor/trace_auditor.py $A $B --png-dir $SL --png-pixel-um 45.532 --voxel-size-um 45.532 \
   --heights 2073,2600,3128 --umbilicus $O/umbilicus_estimated.json --png --out-dir $O/audit/pair_default
# 6. broken copy (temp dir, not committed), N=120, pitch 9.5
(cd tools/realdata_run && python task6_break.py $T/broken 120 9.5)
