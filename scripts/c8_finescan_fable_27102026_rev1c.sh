#!/usr/bin/env bash
# c8_finescan_fable_27102026_rev1c.sh  (rev1c, [fable], 27 Oct 2026; rev1c: zarr() returned the full key prefix (doubled path, 404) -> basename only; rev1b: NIGHT HOOK - after the archive, if BOTH /workspace/c9_night_GO (Pedro's word) and
#   /workspace/c9_night_fable_27102026.sh exist, run 'bash c9_night_fable_27102026.sh auto' (it owns the stop from then on); else stop as rev1) -- PLAN C8 (diagnostic, after C7; labelled as such):
# train on the SCAN THE LABELS WERE MADE ON. PHerc0139 2.399 um / 78 keV render, zarr LEVEL 2 (xy 9.596 um, z 2.399 um), same four
# training boxes as C7 (origin-anchored: level-2 px = rint(9.362-px * 9.362/9.596), 1998 px square), labels = the same new_canon map
# area-meaned with R = 9.596/2.399 = 4 EXACTLY (integer blocks, origin-anchored), >= 128. 32 central layers [38,70) of 109 (77 um,
# centred on layer 54 = the surface, as C7's window was centred on its render's middle). Model/args = C7 e240 except --depth 32.
# Readout = each model's OWN within-box val AUC (mean of the last 20 epochs), compared with C7 e240 on the same boxes (~0.54).
# w045 / the title are NOT converted or scored. Gate: relay 361.
#   bash /workspace/c8_finescan_fable_27102026_rev1c.sh meta          read-only: level 0/1/2 .zarray per segment (chunks, dtype, compressor), map URL + size
#   bash /workspace/c8_finescan_fable_27102026_rev1c.sh fetch dry|go  converter rev6 --level 2 for the four boxes (dry = chunk list only)
#   bash /workspace/c8_finescan_fable_27102026_rev1c.sh r1            same-surface check: 2.399-L2 box vs the existing 9.362 box (w042..w047), structure correlation
#   bash /workspace/c8_finescan_fable_27102026_rev1c.sh stats         L/S of the four new boxes -> /workspace/c8_LS.txt
#   bash /workspace/c8_finescan_fable_27102026_rev1c.sh prep dry|go   segprep rev2 --depth 32 with c8 L/S
#   bash /workspace/c8_finescan_fable_27102026_rev1c.sh go            4 x 240 ep, depth 32 -> summary -> archive -> STOP THE POD (cap first)
#   bash /workspace/c8_finescan_fable_27102026_rev1c.sh status | summary
set -uo pipefail
W=/workspace; PROJ=$W/VesuviusUNET; SELF=$(readlink -f "$0"); KD=/root/c7r_stop
CONV=$W/scroll_segment_convert_fable_27102026_rev6.py; PREP=$W/segprep_c5_fable_25102026_rev2.py; LS=$W/c8_LS.txt
LOG=$W/c8_train_nohup.log; SUM=$W/c8_summary_27102026.txt; DAY=27102026; CAP_H=11; EP=240; DEPTH=32   # rev1b: CAP_H 11 -> hard cap 12 h from go covers C8 (~2 h) + the c9 night branch; c9 keeps its own stop
LEVEL=2; SEGVOX=9.596; LABVOX=2.399; ZL=109; NL0=38; NL1=70
B="https://vesuvius-challenge-open-data.s3.amazonaws.com"
BASE="--patch_size 64 --stride 64 --depth $DEPTH --base_channels 8 --batch_size 8 --gpus 0 --num_workers 4 --no_amp --aggregation max --loss bce_dice --seed 42 --lr 0.0003 --epochs $EP"
# tag | segment folder | level-2 box X0 Y0 X1 Y1 (= rint(C7 9.362 box x 9.362/9.596), 1998 square)
SEGS=(
  "f042|20260206000000-w042_2026020613|2537 2537 4535 4535"
  "f043|20260112000000-w043_2026011217|2537 3122 4535 5120"
  "f044|20260115000000-w044_2026011522|2341 3024 4339 5022"
  "f047|20260206000001-w047_2026020613|683 488 2681 2486"
)
declare -A C7TAG=([f042]=w042 [f043]=w043 [f044]=w044 [f047]=w047)
log(){ echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"; }
fail(){ log "STOPPED: $*"; exit 1; }
one(){ local n; n=$(ls -d $1 2>/dev/null | wc -l); [ "$n" -ge 1 ] || { echo "STOPPED: no folder matches $1" >&2; exit 1; }; ls -d $1 | sort | tail -1; }
zarr(){ curl -s "$B/?prefix=PHerc0139/segments/$1/surface-volumes/&delimiter=/" | grep -o '<Prefix>[^<]*2\.399um[^<]*\.zarr/' | sed 's/<Prefix>//; s#/$##; s#.*/##' | head -1; }
inkurl(){ local k; k=$(curl -s "$B/?prefix=PHerc0139/segments/$1/ink-detection/&delimiter=/" | grep -o '<Key>[^<]*2\.399um[^<]*new_canon[^<]*</Key>' | sed 's/<\/\?Key>//g')
  [ "$(echo "$k" | grep -c .)" = 1 ] || { echo "STOPPED: expected one 2.399 new_canon map for $1, got: $k" >&2; exit 1; }; echo "$B/$k"; }
podenv(){ for v in RUNPOD_POD_ID RUNPOD_API_KEY; do [ -n "${!v:-}" ] || { line=$(tr '\0' '\n' < /proc/1/environ 2>/dev/null | grep "^$v=" | head -1); [ -n "$line" ] && export "$line"; }; done
          [ -n "${RUNPOD_API_KEY:-}" ] && command -v runpodctl >/dev/null && runpodctl config --apiKey "$RUNPOD_API_KEY" >/dev/null 2>&1; }
cd "$PROJ" || fail "no $PROJ"
case "${1:-status}" in
  meta)
    for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"; z=$(zarr "$seg"); echo "=== $tag $seg zarr $z"
      for l in 0 1 2; do echo "  level $l: $(curl -s "$B/PHerc0139/segments/$seg/surface-volumes/$z/$l/.zarray" | tr -d ' \n' | cut -c1-260)"; done
      u=$(inkurl "$seg") || exit 1; echo "  map $(basename "$u" | cut -c1-90)... $(curl -sI "$u" | grep -i content-length | tr -d '\r')"; done ;;
  fetch)
    [ -f "$CONV" ] || fail "no $CONV"; python3 -I "$CONV" --selftest 2>&1 | tail -1 | grep -q "SELFTEST PASSED" || fail "converter rev6 selftest failed"
    for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"; z=$(zarr "$seg"); [ -n "$z" ] || fail "no 2.399 zarr for $seg"
      url=$(inkurl "$seg") || exit 1; log "fetch $tag $seg level $LEVEL box $box zarr $z"
      python3 -I "$CONV" --base_url "$B/PHerc0139/segments/$seg/surface-volumes/$z" --level $LEVEL --box $box --native --layers $ZL --native_layers $NL0 $NL1 \
        --seg_vox $SEGVOX --label_tif "$url" --label_downsample --label_vox $LABVOX --tag "$tag" --out_root "$PROJ" $([ "${2:-dry}" = go ] && echo --go) 2>&1 \
        | grep -E "zarr level|NATIVE|chunks needed|downsampled|registration|WARNING|STOPPED|written|DRY RUN|ink share|error|Error" | cut -c1-200
    done ;;
  r1)   # same-surface check (standing rule R1): the new box and the C7 9.362 box must show the same papyrus structure
    for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"
      python3 - "$PROJ/$(one "data_seg_${tag}_*_native")" "$PROJ/$(one "data_seg_${C7TAG[$tag]}_*_native")" "$tag" <<'PY'
import sys, glob, numpy as np, tifffile
from scipy.ndimage import zoom, gaussian_filter
from scipy.signal import fftconvolve
new, old, tag = sys.argv[1:4]
def mean_mid(d, n=8):
    t = sorted(glob.glob(d + "/[0-9][0-9].tif")); m = len(t) // 2
    return np.mean([tifffile.imread(f).astype(np.float32) for f in t[m - n // 2:m + n // 2]], axis=0)
a = mean_mid(new); b = zoom(mean_mid(old), 9.362 / 9.596, order=1)       # old box onto the 9.596 grid (origin-anchored)
h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1]); a, b = a[:h, :w], b[:h, :w]
hp = lambda x: (lambda y: (y - y.mean()) / (y.std() + 1e-6))(gaussian_filter(x, 2) - gaussian_filter(x, 16))   # band-pass: fibres / cracks
A, Bb = hp(a), hp(b); M = 24; Ac = A[M:-M, M:-M]
r = fftconvolve(Bb, Ac[::-1, ::-1], mode="valid") / Ac.size
i = np.unravel_index(np.argmax(r), r.shape)
print("R1 %s: band-pass structure r(0,0) %+.3f, best %+.3f at (dy,dx) (%d,%d), median |r| %.3f -> %s" % (tag, r[M, M], r[i], i[0] - M, i[1] - M,
      np.median(np.abs(r)), "SAME SURFACE" if r[i] > 5 * np.median(np.abs(r)) and max(abs(i[0] - M), abs(i[1] - M)) <= 3 else "CHECK BY EYE"))
PY
    done ;;
  stats)
    fs=""; for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"; fs="$fs $(one "data_seg_${tag}_*_native")"; done
    python3 -I "$PREP" --stats $fs 2>&1 | tee /tmp/c8_stats.txt | cut -c1-170
    L=$(grep -o 'L = [0-9.]*' /tmp/c8_stats.txt | awk '{print $3}'); S=$(grep -o 'S = [0-9.]*' /tmp/c8_stats.txt | awk '{print $3}')
    [ -n "$L" ] && [ -n "$S" ] || fail "could not parse L/S"
    printf 'L=%s\nS=%s\n# C8 (2.399-L2) own targets over the four boxes, %s\n' "$L" "$S" "$(date -u '+%Y-%m-%d %H:%M UTC')" > "$LS"; log "C8 L=$L S=$S -> $LS" ;;
  prep)
    [ -f "$LS" ] || fail "run stats first"; L=$(awk '/^L=/{print substr($0,3)}' $LS); S=$(awk '/^S=/{print substr($0,3)}' $LS)
    for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"
      python3 -I "$PREP" --src "$(one "data_seg_${tag}_*_native")" --tag "$tag" --L "$L" --S "$S" --xy_zoom 1.0 --depth $DEPTH $([ "${2:-dry}" = go ] && echo --go) 2>&1 \
        | grep -E "source stats|plan:|clipped|written|WARNING|STOPPED|DRY" | cut -c1-170; done ;;
  go)
    [ -e "$LOG" ] && { echo "refusing: $LOG exists"; exit 1; }
    python3 -c "import sklearn" 2>/dev/null || fail "scikit-learn missing - run c7r pre first"
    [ -f "$LS" ] || fail "no $LS"; L=$(awk '/^L=/{print substr($0,3)}' $LS); S=$(awk '/^S=/{print substr($0,3)}' $LS)
    declare -A D; for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"; D[$tag]=$(one "data_seg_${tag}_*_native_rev5") || exit 1
      k=$(ls "${D[$tag]}" | grep -cE '^[0-9]{2}\.tif$'); [ "$k" = $DEPTH ] || fail "${D[$tag]} has $k tifs, not $DEPTH"
      [ -e runs/c8_${tag}_e${EP}_$DAY ] && fail "run folder exists"; done
    podenv; command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] || fail "self-stop not available"
    mkdir -p $KD; chmod 700 $KD
    printf '#!/usr/bin/env bash\nexport RUNPOD_POD_ID=%s RUNPOD_API_KEY=%s\nsleep %d; sync; runpodctl config --apiKey $RUNPOD_API_KEY >/dev/null 2>&1\nfor i in 1 2 3 4 5; do echo "[$(date -u)] c8 hard cap reached, stopping pod"; runpodctl stop pod %s && break; sleep 60; done\n' \
      "$RUNPOD_POD_ID" "$RUNPOD_API_KEY" $(( (CAP_H + 1) * 3600 )) "$RUNPOD_POD_ID" > $KD/c8_hardcap.sh; chmod 700 $KD/c8_hardcap.sh
    setsid nohup bash $KD/c8_hardcap.sh > $W/c8_hardcap.log 2>&1 < /dev/null &
    echo $! > $W/c8_hardcap.pid; log "hard cap armed: pod stops at $(date -u -d "+$((CAP_H + 1)) hours" '+%H:%M UTC') at the latest"
    { echo "c8 record $DAY $(date -u '+%H:%M UTC'): DIAGNOSTIC after C7; 2.399 um render level $LEVEL (xy $SEGVOX um), labels R=$(python3 -c "print($SEGVOX/$LABVOX)"); gate relay 361"
      echo "train.py $(tr -d '\r' < vesuvius_unet/train.py | sha256sum | cut -c1-16) dataset.py $(tr -d '\r' < vesuvius_unet/dataset.py | sha256sum | cut -c1-16) converter $(sha256sum $CONV | cut -c1-16) this script $(sha256sum "$SELF" | cut -c1-16)"
      echo "C5_AUG=1 C5_L=$L C5_S=$S; args $BASE"; for t in "${!D[@]}"; do echo "$t ${D[$t]}"; done; } > $W/c8_record_$DAY.txt
    cat > $W/c8_seq_$DAY.sh <<EOF
#!/usr/bin/env bash
cd $PROJ; export C5_AUG=1 C5_L=$L C5_S=$S C5_P=0.8
( while true; do sleep 120; find runs -maxdepth 2 -path "runs/c8_*_$DAY/*" -name "epoch*.pt" -mmin +2 -delete 2>/dev/null; done ) > /dev/null 2>&1 &
PRN=\$!
for t in f042 f043 f044 f047; do
  case \$t in f042) d=${D[f042]};; f043) d=${D[f043]};; f044) d=${D[f044]};; f047) d=${D[f047]};; esac
  out=runs/c8_\${t}_e${EP}_$DAY
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === TRAIN \$t \$d -> \$out ==="
  python3 -u -m vesuvius_unet.train --data_dir \$d --output_dir \$out $BASE > $W/c8_train_\${t}_$DAY.log 2>&1
  rc=\$?; echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === \$t finished rc=\$rc; last.pt \$(sha256sum \$out/last.pt 2>/dev/null | cut -c1-16) ==="
  [ \$rc = 0 ] || { echo "STOPPED: \$t rc=\$rc"; break; }
done
kill \$PRN; find runs -maxdepth 2 -path "runs/c8_*_$DAY/*" -name "epoch*.pt" -delete 2>/dev/null
echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] TRAINING DONE"
bash $SELF summary > $SUM 2>&1
cd $W; A=$W/c8_archive_\$(date -u +%Y%m%d_%H%M).tgz
{ ls c8_* | grep -v -e archive -e hardcap.sh; ls VesuviusUNET/segconv_f04*_provenance.json VesuviusUNET/segprep_f04*_provenance.json 2>/dev/null; for r in VesuviusUNET/runs/c8_*_$DAY; do find \$r -type f ! -name '*.pt'; done; } > $W/c8_archive_list.txt
tar czf \$A -T $W/c8_archive_list.txt && sha256sum \$A > \$A.sha256 && echo "archive \$A \$(stat -c %s \$A) B"
if [ -f $W/c9_night_GO ] && [ -f $W/c9_night_fable_27102026.sh ]; then
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] NIGHT HOOK: c9_night_GO present -> handing over to c9_night_fable_27102026.sh auto (it stops the pod)"
  RUNPOD_POD_ID=\$RUNPOD_POD_ID RUNPOD_API_KEY=\$RUNPOD_API_KEY bash $W/c9_night_fable_27102026.sh auto > $W/c9_night_nohup.log 2>&1
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] c9 returned rc=\$? - stopping the pod as a safety net"
fi
sync; sleep 60; runpodctl config --apiKey "\$RUNPOD_API_KEY" >/dev/null 2>&1
for i in 1 2 3 4 5; do echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] stopping pod \$RUNPOD_POD_ID"; runpodctl stop pod \$RUNPOD_POD_ID && break; sleep 60; done
EOF
    RUNPOD_POD_ID=$RUNPOD_POD_ID RUNPOD_API_KEY=$RUNPOD_API_KEY setsid nohup bash $W/c8_seq_$DAY.sh > "$LOG" 2>&1 < /dev/null &
    sleep 20; log "started (4 runs, depth 32); record $W/c8_record_$DAY.txt"; head -2 "$LOG" ;;
  summary)
    python3 - "$W" "$DAY" <<'PY'
import sys, re, os
W, DAY = sys.argv[1], sys.argv[2]
def tail_auc(f, n=20):
    v = [float(m.group(1)) for m in (re.search(r"^Epoch \d+:.*val_AUC=([0-9.]+)", l) for l in open(f)) if m]
    l = [float(m.group(1)) for m in (re.search(r"^Epoch \d+: train_loss=([0-9.]+)", l) for l in open(f)) if m]
    return (sum(v[-n:]) / len(v[-n:]), len(v), l[0] if l else float("nan"), l[-1] if l else float("nan")) if v else None
print("PLAN C8 (DIAGNOSTIC after C7): 2.399 um render level 2 (xy 9.596 um), labels R=4. Own-box val AUC = mean of last 20 epochs.")
print("box   C8 (2.399-L2)                         C7 e240 same box (9.362)")
c8, c7, k = [], [], 0
for f, w in (("f042", "w042"), ("f043", "w043"), ("f044", "w044"), ("f047", "w047")):
    a = os.path.join(W, "c8_train_%s_%s.log" % (f, DAY)); b = os.path.join(W, "c7r_train_%s_e240_26102026.log" % w)
    x = tail_auc(a) if os.path.exists(a) else None; y = tail_auc(b) if os.path.exists(b) else None
    print("%s  %-38s %s" % (f, ("%.3f (%d ep, loss %.2f -> %.2f)" % x) if x else "missing", ("%.3f" % y[0]) if y else "missing"))
    if x and x[1] >= 200: c8.append(x[0]); k += x[0] >= 0.65
    if y: c7.append(y[0])
if len(c8) == 4:
    m = sum(c8) / 4
    v = "LEARNS on the map's own scan (gate met)" if (m >= 0.70 and k >= 3) else ("DOES NOT learn (mean < 0.62)" if m < 0.62 else "INDETERMINATE (0.62-0.70 or < 3 boxes >= 0.65)")
    print("C8 mean %.3f (boxes >= 0.65: %d/4); C7 e240 mean %.3f -> %s" % (m, k, sum(c7) / max(len(c7), 1), v))
else:
    print("C8 incomplete: %d of 4 runs with >= 200 epochs" % len(c8))
PY
    ;;
  status)
    [ -e "$LOG" ] && grep -E "===|STOPPED|DONE|archive|stopping" "$LOG" | cut -c1-150 || echo "no c8 log yet"
    for f in $W/c8_train_*_$DAY.log; do [ -e "$f" ] || continue; echo "--- $(basename $f): $(grep -E '^Epoch' $f | tail -1 | cut -c1-120)"; done
    [ -e $W/c8_hardcap.log ] && echo "--- hard cap log: $(tail -1 $W/c8_hardcap.log)"
    [ -e $SUM ] && cat $SUM ;;
  *) echo "usage: $0 meta|fetch dry|go|r1|stats|prep dry|go|go|status|summary"; exit 2 ;;
esac
