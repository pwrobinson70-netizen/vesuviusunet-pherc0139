#!/usr/bin/env bash
# c9_night_fable_27102026.sh  (rev1c, [fable], 27 Oct 2026: zarr() basename fix as c8 rev1c; rev1b, [fable], 27 Oct 2026; rev1b = Sonnet 374 b: branch A runs the C8 R1 same-surface check on w045
#   (new render vs the C7 9.362 w045 box) before scoring; not SAME SURFACE -> recorded, scoring skipped, archive + stop) -- OVERNIGHT FOLLOW-UP chosen by the two evening results (DIAGNOSTIC after C7).
# Called by c8 rev1b's night hook ("auto") on the C8 pod when /workspace/c9_night_GO exists. Reads:
#   C8  /workspace/c8_summary_27102026.txt   -> "LEARNS" | "DOES NOT" | "INDETERMINATE" (pre-registered gate, relay 361)
#   C7S /workspace/c7s_summary_27102026.txt  -> per shift "SHIFT HELPS" | "no evidence" (relay 357)
# DECISION (fixed in relay 367 before either result is known):
#   A  C8 LEARNS        -> TRANSFER: convert w045 + the title at the same 2.399-L2 render (same converter args, R = 4), prep with C8's
#                          L/S, score the 4-model C8 ensemble ONCE with c4_maps rev4c --members C8 --score. Gate: ensemble papyrus AUC on
#                          w045 >= 0.70 = "TRANSFERS"; < 0.62 = "does not transfer"; else indeterminate. Title = descriptive.
#                          (w045's labels were looked at in C7 - this is the first look with a model of the new render; labelled so.)
#   C  otherwise        -> SLAB: the same 4 boxes at 2.399-L2 with C7's physical slab: layers [22,86) (64 layers, 154 um) kept, every 2nd
#                          used (32 layers, 4.8 um step), own L/S, 240 ep, depth 32; readout/gate exactly as C8 (own-box val AUC, last 20 ep;
#                          LEARNS >= 0.70 and >= 3/4 boxes >= 0.65; DOES NOT < 0.62).
#   The C7S verdict does not change the branch (its follow-up needs a day plan); it is copied into the c9 summary for the record.
#   C8 summary missing or incomplete -> do nothing (the c8 hook then stops the pod).
#   bash /workspace/c9_night_fable_27102026.sh decide    read-only: prints the branch it would take
#   bash /workspace/c9_night_fable_27102026.sh auto      runs the branch, writes c9_summary_27102026.txt, archive, then STOPS THE POD
#   bash /workspace/c9_night_fable_27102026.sh status
set -uo pipefail
W=/workspace; PROJ=$W/VesuviusUNET; SELF=$(readlink -f "$0")
CONV=$W/scroll_segment_convert_fable_27102026_rev6.py; PREP=$W/segprep_c5_fable_25102026_rev2.py; MAPS=$W/c4_maps_fable_27102026_rev4c.py
C8SUM=$W/c8_summary_27102026.txt; C7SSUM=$W/c7s_summary_27102026.txt; SUM=$W/c9_summary_27102026.txt; DAY=27102026; EP=240
B="https://vesuvius-challenge-open-data.s3.amazonaws.com"; LEVEL=2; SEGVOX=9.596; LABVOX=2.399; ZL=109
BASE="--patch_size 64 --stride 64 --depth 32 --base_channels 8 --batch_size 8 --gpus 0 --num_workers 4 --no_amp --aggregation max --loss bce_dice --seed 42 --lr 0.0003 --epochs $EP"
SEGS=(
  "042|20260206000000-w042_2026020613|2537 2537 4535 4535"
  "043|20260112000000-w043_2026011217|2537 3122 4535 5120"
  "044|20260115000000-w044_2026011522|2341 3024 4339 5022"
  "047|20260206000001-w047_2026020613|683 488 2681 2486"
)
W045="20260126000000-w045_2026012619|1171 2146 3169 4144"      # rint(C7 w045 box 1200 2200 3248 4248 x 9.362/9.596), 1998 square
TITLE="20260422000000-title_2026042222_zmid_flatboi"            # whole sheet: box = full level-2 extent, read from its .zarray
log(){ echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"; }
fail(){ log "STOPPED: $*"; exit 1; }
one(){ local n; n=$(ls -d $1 2>/dev/null | wc -l); [ "$n" -ge 1 ] || { echo "STOPPED: no folder matches $1" >&2; exit 1; }; ls -d $1 | sort | tail -1; }
zarr(){ curl -s "$B/?prefix=PHerc0139/segments/$1/surface-volumes/&delimiter=/" | grep -o '<Prefix>[^<]*2\.399um[^<]*\.zarr/' | sed 's/<Prefix>//; s#/$##; s#.*/##' | head -1; }
inkurl(){ local k; k=$(curl -s "$B/?prefix=PHerc0139/segments/$1/ink-detection/&delimiter=/" | grep -o '<Key>[^<]*2\.399um[^<]*new_canon[^<]*</Key>' | sed 's/<\/\?Key>//g')
  [ "$(echo "$k" | grep -c .)" = 1 ] || { echo "STOPPED: expected one 2.399 new_canon map for $1, got: $k" >&2; exit 1; }; echo "$B/$k"; }
convert(){ # $1 tag $2 seg $3 box $4 L0 $5 L1
  local z url; z=$(zarr "$2"); [ -n "$z" ] || fail "no 2.399 zarr for $2"; url=$(inkurl "$2") || exit 1
  python3 -I "$CONV" --base_url "$B/PHerc0139/segments/$2/surface-volumes/$z" --level $LEVEL --box $3 --native --layers $ZL --native_layers $4 $5 \
    --seg_vox $SEGVOX --label_tif "$url" --label_downsample --label_vox $LABVOX --tag "$1" --out_root "$PROJ" --go 2>&1 \
    | grep -E "zarr level|NATIVE|downsampled|registration|WARNING|STOPPED|written|ink share|error|Error" | cut -c1-200
  one "data_seg_${1}_*_native" > /dev/null || fail "conversion of $1 wrote nothing"; }
r1(){ # $1 new folder $2 old (9.362) folder $3 tag -> prints the R1 line (same code as c8 r1)
  python3 - "$1" "$2" "$3" <<'PY'
import sys, glob, numpy as np, tifffile
from scipy.ndimage import zoom, gaussian_filter
from scipy.signal import fftconvolve
new, old, tag = sys.argv[1:4]
def mean_mid(d, n=8):
    t = sorted(glob.glob(d + "/[0-9][0-9].tif")); m = len(t) // 2
    return np.mean([tifffile.imread(f).astype(np.float32) for f in t[m - n // 2:m + n // 2]], axis=0)
a = mean_mid(new); b = zoom(mean_mid(old), 9.362 / 9.596, order=1)
h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1]); a, b = a[:h, :w], b[:h, :w]
hp = lambda x: (lambda y: (y - y.mean()) / (y.std() + 1e-6))(gaussian_filter(x, 2) - gaussian_filter(x, 16))
A, Bb = hp(a), hp(b); M = 24; Ac = A[M:-M, M:-M]
r = fftconvolve(Bb, Ac[::-1, ::-1], mode="valid") / Ac.size
i = np.unravel_index(np.argmax(r), r.shape)
print("R1 %s: band-pass structure r(0,0) %+.3f, best %+.3f at (dy,dx) (%d,%d), median |r| %.3f -> %s" % (tag, r[M, M], r[i], i[0] - M, i[1] - M,
      np.median(np.abs(r)), "SAME SURFACE" if r[i] > 5 * np.median(np.abs(r)) and max(abs(i[0] - M), abs(i[1] - M)) <= 3 else "CHECK BY EYE"))
PY
}
decide(){
  [ -f $C8SUM ] || { echo "NONE (no C8 summary)"; return; }
  if grep -q "LEARNS on the map's own scan (gate met)" $C8SUM; then echo A; elif grep -qE "DOES NOT learn|INDETERMINATE" $C8SUM; then echo C; else echo "NONE (C8 incomplete)"; fi; }
train4(){ # $1 = run prefix, $2.. = data folders (4)
  local p=$1; shift; local i=0
  ( while true; do sleep 120; find runs -maxdepth 2 -path "runs/${p}_*_$DAY/*" -name "epoch*.pt" -mmin +2 -delete 2>/dev/null; done ) > /dev/null 2>&1 &
  local PRN=$!
  for d in "$@"; do t=$(basename "$d" | sed 's/data_seg_\([a-z0-9]*\)_.*/\1/'); out=runs/${p}_${t}_e${EP}_$DAY
    log "=== TRAIN $t $d -> $out"
    python3 -u -m vesuvius_unet.train --data_dir "$d" --output_dir "$out" $BASE > $W/${p}_train_${t}_$DAY.log 2>&1
    rc=$?; log "=== $t finished rc=$rc; last.pt $(sha256sum $out/last.pt 2>/dev/null | cut -c1-16)"; [ $rc = 0 ] || { log "STOPPED: $t rc=$rc"; break; }
  done
  kill $PRN 2>/dev/null; find runs -maxdepth 2 -path "runs/${p}_*_$DAY/*" -name "epoch*.pt" -delete 2>/dev/null; }
cd "$PROJ" || fail "no $PROJ"
case "${1:-status}" in
  decide) echo "C8: $(grep -E 'C8 mean|incomplete' $C8SUM 2>/dev/null | tail -1)"; echo "C7S: $(grep -E '^(m9m2|p9p2):' $C7SSUM 2>/dev/null | tr '\n' ' ')"; echo "BRANCH: $(decide)" ;;
  auto)
    br=$(decide); log "c9 night: branch $br"; { echo "c9 night $DAY - DIAGNOSTIC after C7. Branch $br (rules relay 367)"; echo "C8 verdict: $(grep -E 'C8 mean|incomplete' $C8SUM 2>/dev/null | tail -1)"
      echo "C7S verdicts: $(grep -E '^(m9m2|p9p2):' $C7SSUM 2>/dev/null | tr '\n' ' ')"; } > $SUM
    case "$br" in
      A)
        [ -f $W/c8_LS.txt ] || fail "no c8_LS.txt"; L=$(awk '/^L=/{print substr($0,3)}' $W/c8_LS.txt); S=$(awk '/^S=/{print substr($0,3)}' $W/c8_LS.txt)
        IFS='|' read -r seg box <<< "$W045"; convert fw45 "$seg" "$box" 38 70
        z=$(zarr "$TITLE"); sh=$(curl -s "$B/PHerc0139/segments/$TITLE/surface-volumes/$z/$LEVEL/.zarray" | tr -d ' \n' | grep -o '"shape":\[[0-9,]*\]' | grep -o '[0-9,]*' )
        IFS=, read -r d0 h0 w0 <<< "$sh"; [ -n "${w0:-}" ] || fail "no title level-2 shape"; convert ftit "$TITLE" "0 0 $w0 $h0" 38 70
        for t in fw45 ftit; do python3 -I "$PREP" --src "$(one "data_seg_${t}_*_native")" --tag "$t" --L "$L" --S "$S" --xy_zoom 1.0 --depth 32 --go 2>&1 | grep -E "written|WARNING|STOPPED" | cut -c1-170; done
        f45=$(one "data_seg_fw45_*_native_rev5"); ft=$(one "data_seg_ftit_*_native_rev5")
        r1line=$(r1 "$PROJ/$(one "data_seg_fw45_*_native")" "$PROJ/$(one "data_seg_w045_*_native")" fw45 2>&1); echo "$r1line" | tee -a $SUM
        if ! echo "$r1line" | grep -q "SAME SURFACE"; then echo "TRANSFER SKIPPED: w045 R1 not SAME SURFACE (Sonnet 374 b) - nothing scored" | tee -a $SUM
        else
        log "=== TRANSFER (branch A): C8 ensemble on w045 (first look with a 2.399-render model; w045 labels seen in C7) + title; gate >= 0.70"
        python3 -I "$MAPS" --go --score --members C8 --c5_day $DAY --stride 16 --stamp "c9transfer_$(date -u +%Y%m%d_%H%M)" $f45 $ft > $W/c9_transfer_nohup.log 2>&1
        grep -E "SCORE .* ENSEMBLE|SCORE .* member" $W/c9_transfer_nohup.log | cut -c1-200 | tee -a $SUM
        a=$(grep -E "SCORE w045.* ENSEMBLE|SCORE fw45.* ENSEMBLE" $W/c9_transfer_nohup.log | grep -o 'AUC [0-9.]*' | head -1 | awk '{print $2}')
        python3 -c "a=float('${a:-nan}'); print('TRANSFER w045 ensemble AUC %.4f -> %s' % (a, 'TRANSFERS (gate met)' if a >= 0.70 else ('does not transfer (< 0.62)' if a < 0.62 else 'INDETERMINATE')))" | tee -a $SUM
        fi ;;
      C)
        fs=""; for e in "${SEGS[@]}"; do IFS='|' read -r n seg box <<< "$e"; convert g$n "$seg" "$box" 22 86
          src=$PROJ/$(one "data_seg_g${n}_*_native"); dst=${src/data_seg_g$n/data_seg_s$n}; mkdir -p "$dst"
          for k in $(seq 0 31); do ln -sf "$src/$(printf %02d $((2 * k))).tif" "$dst/$(printf %02d $k).tif"; done
          for f in mask.png inklabels.png label_raw.png; do ln -sf "$src/$f" "$dst/$f"; done; fs="$fs $dst"; done
        python3 -I "$PREP" --stats $fs 2>&1 | tee /tmp/c9_stats.txt | cut -c1-170
        L=$(grep -o 'L = [0-9.]*' /tmp/c9_stats.txt | awk '{print $3}'); S=$(grep -o 'S = [0-9.]*' /tmp/c9_stats.txt | awk '{print $3}'); [ -n "$L" ] && [ -n "$S" ] || fail "no L/S"
        printf 'L=%s\nS=%s\n# c9 slab (2.399-L2 layers 22..85 step 2)\n' "$L" "$S" > $W/c9_LS.txt
        for e in "${SEGS[@]}"; do IFS='|' read -r n seg box <<< "$e"; python3 -I "$PREP" --src "$(one "data_seg_s${n}_*_native")" --tag "s$n" --L "$L" --S "$S" --xy_zoom 1.0 --depth 32 --go 2>&1 | grep -E "written|WARNING|STOPPED" | cut -c1-170; done
        ds=""; for e in "${SEGS[@]}"; do IFS='|' read -r n seg box <<< "$e"; d=$(one "data_seg_s${n}_*_native_rev5") || exit 1; [ "$(ls $d | grep -cE '^[0-9]{2}\.tif$')" = 32 ] || fail "$d not 32 tifs"; ds="$ds $d"; done
        export C5_AUG=1 C5_L=$L C5_S=$S C5_P=0.8
        train4 c9s $ds
        python3 - "$W" "$DAY" <<'PY' | tee -a $SUM
import sys, re, os
W, DAY = sys.argv[1], sys.argv[2]
def tail(f, n=20):
    v = [float(m.group(1)) for m in (re.search(r"^Epoch \d+:.*val_AUC=([0-9.]+)", l) for l in open(f)) if m]
    return (sum(v[-n:]) / len(v[-n:]), len(v)) if v else None
rows, k = [], 0
for n in ("042", "043", "044", "047"):
    x = tail(os.path.join(W, "c9s_train_s%s_%s.log" % (n, DAY))) if os.path.exists(os.path.join(W, "c9s_train_s%s_%s.log" % (n, DAY))) else None
    c8 = tail(os.path.join(W, "c8_train_f%s_%s.log" % (n, DAY))) if os.path.exists(os.path.join(W, "c8_train_f%s_%s.log" % (n, DAY))) else None
    print("s%s slab own-box val AUC %s   (C8 f%s %s)" % (n, ("%.3f (%d ep)" % x) if x else "missing", n, ("%.3f" % c8[0]) if c8 else "missing"))
    if x and x[1] >= 200: rows.append(x[0]); k += x[0] >= 0.65
if len(rows) == 4:
    m = sum(rows) / 4
    print("SLAB mean %.3f (boxes >= 0.65: %d/4) -> %s" % (m, k, "LEARNS (gate met)" if (m >= 0.70 and k >= 3) else ("DOES NOT learn (< 0.62)" if m < 0.62 else "INDETERMINATE")))
else:
    print("SLAB incomplete: %d of 4" % len(rows))
PY
        ;;
      *) log "no branch ($br) - nothing run"; exit 0 ;;
    esac
    cd $W; A=$W/c9_archive_$(date -u +%Y%m%d_%H%M).tgz
    { ls c9_* | grep -v -e archive; ls c9s_* 2>/dev/null; ls VesuviusUNET/segconv_[fgs]*_provenance.json VesuviusUNET/segprep_[fgs]*_provenance.json 2>/dev/null
      for r in VesuviusUNET/runs/c9s_*_$DAY; do [ -d $r ] && find $r -type f ! -name '*.pt'; done; ls -d VesuviusUNET/c4_maps_c9transfer_* 2>/dev/null | while read r; do find $r -type f; done; } > $W/c9_archive_list.txt
    tar czf $A -T $W/c9_archive_list.txt && sha256sum $A > $A.sha256 && log "archive $A $(stat -c %s $A) B"
    sync; sleep 30; runpodctl config --apiKey "${RUNPOD_API_KEY:-}" >/dev/null 2>&1
    for i in 1 2 3 4 5; do log "c9: stopping pod ${RUNPOD_POD_ID:-?}"; runpodctl stop pod "${RUNPOD_POD_ID:-}" && break; sleep 60; done ;;
  status) [ -f $SUM ] && cat $SUM || echo "no c9 summary yet"; [ -f $W/c9_night_nohup.log ] && grep -E "===|STOPPED|branch|archive|stopping" $W/c9_night_nohup.log | tail -12 | cut -c1-160
    for f in $W/c9s_train_*_$DAY.log; do [ -e "$f" ] || continue; echo "--- $(basename $f): $(grep -E '^Epoch' $f | tail -1 | cut -c1-110)"; done ;;
  *) echo "usage: $0 decide|auto|status"; exit 2 ;;
esac
