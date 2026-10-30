#!/usr/bin/env bash
# c10_l1_fable_28102026.sh  (rev1, [fable], 28 Oct 2026) -- PLAN C10 = C8 at the NEXT FINER level: 2.399 render LEVEL 1 (xy 4.798 um),
#   labels R = 4.798/2.399 = 2 exact, same 4 boxes in physical space (level-1 px = 2 x the C8 level-2 box, 3996 square), same 32 layers [38,70),
#   60 epochs (= C8's 240 x 1/4: 4x the tiles per box -> same optimiser STEPS). Question: does finer xy train better / quicker? Gate relay 391.
#   'night' = cap first, then fetch -> R1 -> stats -> prep -> go in the background; self-stop at the end. Built from c8 rev1c (lines below).
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
CONV=$W/scroll_segment_convert_fable_27102026_rev6.py; PREP=$W/segprep_c5_fable_25102026_rev2.py; LS=$W/c10_LS.txt
LOG=$W/c10_train_nohup.log; SUM=$W/c10_summary_28102026.txt; DAY=28102026; CAP_H=7; EP=60; DEPTH=32   # c10: CAP_H 7 -> hard cap 8 h from go (Sonnet 394 item 3: stale c8/c9 comment fixed)
LEVEL=1; SEGVOX=4.798; LABVOX=2.399; ZL=109; NL0=38; NL1=70
B="https://vesuvius-challenge-open-data.s3.amazonaws.com"
BASE="--patch_size 64 --stride 64 --depth $DEPTH --base_channels 8 --batch_size 8 --gpus 0 --num_workers 4 --no_amp --aggregation max --loss bce_dice --seed 42 --lr 0.0003 --epochs $EP"
# tag | segment folder | level-2 box X0 Y0 X1 Y1 (= rint(C7 9.362 box x 9.362/9.596), 1998 square)
SEGS=(
  "h042|20260206000000-w042_2026020613|5074 5074 9070 9070"
  "h043|20260112000000-w043_2026011217|5074 6244 9070 10240"
  "h044|20260115000000-w044_2026011522|4682 6048 8678 10044"
  "h047|20260206000001-w047_2026020613|1366 976 5362 4972"
)
declare -A C7TAG=([h042]=w042 [h043]=w043 [h044]=w044 [h047]=w047)
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
a = mean_mid(new); b = zoom(mean_mid(old), 9.362 / 4.798, order=1)       # c10: old box onto the 4.798 grid (origin-anchored)
h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1]); a, b = a[:h, :w], b[:h, :w]
hp = lambda x: (lambda y: (y - y.mean()) / (y.std() + 1e-6))(gaussian_filter(x, 2) - gaussian_filter(x, 16))   # band-pass: fibres / cracks
A, Bb = hp(a), hp(b); M = 48   # c10: +-48 px at 4.8 um = C8's +-24 at 9.6 um
Ac = A[M:-M, M:-M]
r = fftconvolve(Bb, Ac[::-1, ::-1], mode="valid") / Ac.size
i = np.unravel_index(np.argmax(r), r.shape)
print("R1 %s: band-pass structure r(0,0) %+.3f, best %+.3f at (dy,dx) (%d,%d), median |r| %.3f -> %s" % (tag, r[M, M], r[i], i[0] - M, i[1] - M,
      np.median(np.abs(r)), "SAME SURFACE" if r[i] > 5 * np.median(np.abs(r)) and max(abs(i[0] - M), abs(i[1] - M)) <= 6 else "CHECK BY EYE"))
PY
    done ;;
  stats)
    fs=""; for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"; fs="$fs $(one "data_seg_${tag}_*_native")"; done
    python3 -I "$PREP" --stats $fs 2>&1 | tee /tmp/c10_stats.txt | cut -c1-170
    L=$(grep -o 'L = [0-9.]*' /tmp/c10_stats.txt | awk '{print $3}'); S=$(grep -o 'S = [0-9.]*' /tmp/c10_stats.txt | awk '{print $3}')
    [ -n "$L" ] && [ -n "$S" ] || fail "could not parse L/S"
    printf 'L=%s\nS=%s\n# C10 (2.399-L1) own targets over the four boxes, %s\n' "$L" "$S" "$(date -u '+%Y-%m-%d %H:%M UTC')" > "$LS"; log "C8 L=$L S=$S -> $LS" ;;
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
      [ -e runs/c10_${tag}_e${EP}_$DAY ] && fail "run folder exists"; done
    podenv; command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] || fail "self-stop not available"
    mkdir -p $KD; chmod 700 $KD
    printf '#!/usr/bin/env bash\nexport RUNPOD_POD_ID=%s RUNPOD_API_KEY=%s\nsleep %d; sync; runpodctl config --apiKey $RUNPOD_API_KEY >/dev/null 2>&1\nfor i in 1 2 3 4 5; do echo "[$(date -u)] c8 hard cap reached, stopping pod"; runpodctl stop pod %s && break; sleep 60; done\n' \
      "$RUNPOD_POD_ID" "$RUNPOD_API_KEY" $(( (CAP_H + 1) * 3600 )) "$RUNPOD_POD_ID" > $KD/c10_hardcap.sh; chmod 700 $KD/c10_hardcap.sh
    setsid nohup bash $KD/c10_hardcap.sh > $W/c10_hardcap.log 2>&1 < /dev/null &
    echo $! > $W/c10_hardcap.pid; log "hard cap armed: pod stops at $(date -u -d "+$((CAP_H + 1)) hours" '+%H:%M UTC') at the latest"
    { echo "c10 record $DAY $(date -u '+%H:%M UTC'): DIAGNOSTIC after C7; 2.399 um render level $LEVEL (xy $SEGVOX um), labels R=$(python3 -c "print($SEGVOX/$LABVOX)"); gate relay 361"
      echo "train.py $(tr -d '\r' < vesuvius_unet/train.py | sha256sum | cut -c1-16) dataset.py $(tr -d '\r' < vesuvius_unet/dataset.py | sha256sum | cut -c1-16) converter $(sha256sum $CONV | cut -c1-16) this script $(sha256sum "$SELF" | cut -c1-16)"
      echo "C5_AUG=1 C5_L=$L C5_S=$S; args $BASE"; for t in "${!D[@]}"; do echo "$t ${D[$t]}"; done; } > $W/c10_record_$DAY.txt
    cat > $W/c10_seq_$DAY.sh <<EOF
#!/usr/bin/env bash
cd $PROJ; export C5_AUG=1 C5_L=$L C5_S=$S C5_P=0.8
( while true; do sleep 120; find runs -maxdepth 2 -path "runs/c10_*_$DAY/*" -name "epoch*.pt" -mmin +2 -delete 2>/dev/null; done ) > /dev/null 2>&1 &
PRN=\$!
for t in h042 h043 h044 h047; do
  case \$t in h042) d=${D[h042]};; h043) d=${D[h043]};; h044) d=${D[h044]};; h047) d=${D[h047]};; esac
  out=runs/c10_\${t}_e${EP}_$DAY
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === TRAIN \$t \$d -> \$out ==="
  python3 -u -m vesuvius_unet.train --data_dir \$d --output_dir \$out $BASE > $W/c10_train_\${t}_$DAY.log 2>&1
  rc=\$?; echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === \$t finished rc=\$rc; last.pt \$(sha256sum \$out/last.pt 2>/dev/null | cut -c1-16) ==="
  [ \$rc = 0 ] || { echo "STOPPED: \$t rc=\$rc"; break; }
done
kill \$PRN; find runs -maxdepth 2 -path "runs/c10_*_$DAY/*" -name "epoch*.pt" -delete 2>/dev/null
echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] TRAINING DONE"
bash $SELF summary > $SUM 2>&1
cd $W; A=$W/c10_archive_\$(date -u +%Y%m%d_%H%M).tgz
{ ls c10_* | grep -v -e archive -e hardcap.sh; ls VesuviusUNET/segconv_h04*_provenance.json VesuviusUNET/segprep_h04*_provenance.json 2>/dev/null; for r in VesuviusUNET/runs/c10_*_$DAY; do find \$r -type f ! -name '*.pt'; done; } > $W/c10_archive_list.txt
tar czf \$A -T $W/c10_archive_list.txt && sha256sum \$A > \$A.sha256 && echo "archive \$A \$(stat -c %s \$A) B"
sync; sleep 60; runpodctl config --apiKey "\$RUNPOD_API_KEY" >/dev/null 2>&1
for i in 1 2 3 4 5; do echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] stopping pod \$RUNPOD_POD_ID"; runpodctl stop pod \$RUNPOD_POD_ID && break; sleep 60; done
EOF
    RUNPOD_POD_ID=$RUNPOD_POD_ID RUNPOD_API_KEY=$RUNPOD_API_KEY setsid nohup bash $W/c10_seq_$DAY.sh > "$LOG" 2>&1 < /dev/null &
    sleep 20; log "started (4 runs, depth 32); record $W/c10_record_$DAY.txt"; head -2 "$LOG" ;;
  summary)
    python3 - "$W" <<'PY'
import sys, re, os
W = sys.argv[1]
def series(f):
    v = [float(m.group(1)) for m in (re.search(r"^Epoch \d+:.*val_AUC=([0-9.]+)", l) for l in open(f)) if m]
    return v
def at(v, frac, k=5):
    n = len(v); e = max(k, int(round(frac * n))); w = v[e - k:e]
    return sum(w) / len(w) if w else float("nan")
print("PLAN C10 (DIAGNOSTIC after C7/C8): 2.399 render LEVEL 1 (xy 4.798 um), labels R=2, 60 ep (= C8's steps). Own-box val AUC.")
print("box   C10 last-20 mean   C8 last-20 mean   | 'quicker': val AUC (5-ep mean) at 25/50/75/100 % of the steps, C10 vs C8")
c10, c8, up = [], [], 0
for h, f in (("h042", "f042"), ("h043", "f043"), ("h044", "f044"), ("h047", "f047")):
    a = os.path.join(W, "c10_train_%s_28102026.log" % h); b = os.path.join(W, "c8_train_%s_27102026.log" % f)
    x = series(a) if os.path.exists(a) else []; y = series(b) if os.path.exists(b) else []
    xm = sum(x[-20:]) / len(x[-20:]) if len(x) >= 50 else None; ym = sum(y[-20:]) / len(y[-20:]) if y else None
    q = " ".join("%.3f/%.3f" % (at(x, p), at(y, p)) for p in (0.25, 0.5, 0.75, 1.0)) if x and y else "n/a"
    print("%s  %-18s %-17s | %s" % (h, ("%.3f (%d ep)" % (xm, len(x))) if xm is not None else "missing/short", ("%.3f" % ym) if ym is not None else "missing", q))
    if xm is not None and ym is not None: c10.append(xm); c8.append(ym); up += (xm - ym) >= 0.03
if len(c10) == 4:
    d = sum(c10) / 4 - sum(c8) / 4
    v = "FINER IS BETTER (gate met)" if (d >= 0.05 and up >= 3) else ("FINER IS WORSE" if d <= -0.05 else "NO CLEAR DIFFERENCE")
    print("C10 mean %.3f vs C8 mean %.3f: diff %+.3f, boxes up >= 0.03: %d/4 -> %s" % (sum(c10) / 4, sum(c8) / 4, d, up, v))
else:
    print("C10 incomplete: %d of 4 comparable runs" % len(c10))
PY
    ;;
  night)    # cap FIRST, then the whole chain in the background (Pedro can close the window)
    podenv; command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] || fail "self-stop not available"
    m=$(free -g | awk '/^Mem:/{print $2}'); log "RAM ${m} GB"; [ "${m:-0}" -ge 40 ] || fail "RAM ${m} GB < 40 GB: level-1 conversion needs ~20-25 GB peak - not starting"
    mkdir -p $KD; chmod 700 $KD
    printf '#!/usr/bin/env bash\nexport RUNPOD_POD_ID=%s RUNPOD_API_KEY=%s\nsleep %d; sync; runpodctl config --apiKey $RUNPOD_API_KEY >/dev/null 2>&1\nfor i in 1 2 3 4 5; do echo "[$(date -u)] c10 night cap reached, stopping pod"; runpodctl stop pod %s && break; sleep 60; done\n' \
      "$RUNPOD_POD_ID" "$RUNPOD_API_KEY" $(( 8 * 3600 )) "$RUNPOD_POD_ID" > $KD/c10_nightcap.sh; chmod 700 $KD/c10_nightcap.sh
    setsid nohup bash $KD/c10_nightcap.sh > $W/c10_nightcap.log 2>&1 < /dev/null &
    log "night cap armed: pod stops by $(date -u -d '+8 hours' '+%H:%M UTC') at the latest"
    RUNPOD_POD_ID=$RUNPOD_POD_ID RUNPOD_API_KEY=$RUNPOD_API_KEY setsid nohup bash "$SELF" _night > $W/c10_night.log 2>&1 < /dev/null &
    sleep 5; log "night chain started; log $W/c10_night.log (status: bash $SELF status)" ;;
  _night)
    stopnow(){ log "STOPPED: $* - stopping the pod"; sync; runpodctl config --apiKey "$RUNPOD_API_KEY" >/dev/null 2>&1; for i in 1 2 3; do runpodctl stop pod "$RUNPOD_POD_ID" && break; sleep 60; done; exit 1; }
    # rev1b: skip the fetch if all four folders already exist (28 Oct resume after the R1 IndentationError; fetch output is unchanged)
    have=0; for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"; ls -d data_seg_${tag}_*_native >/dev/null 2>&1 && have=$((have+1)); done
    if [ "$have" = 4 ]; then log "all 4 boxes already fetched - fetch skipped"; else bash "$SELF" fetch go || stopnow "fetch"; fi
    for e in "${SEGS[@]}"; do IFS='|' read -r tag seg box <<< "$e"; one "data_seg_${tag}_*_native" >/dev/null || stopnow "no folder for $tag"; done
    bash "$SELF" r1 | tee $W/c10_r1.txt
    # pre-registered (relay 391): f044/f047 boxes (h044/h047) MUST be SAME SURFACE (they were in C8); h042/h043 are recorded (C8 override applies)
    grep -q "R1 h044.*SAME SURFACE" $W/c10_r1.txt && grep -q "R1 h047.*SAME SURFACE" $W/c10_r1.txt || stopnow "R1 h044/h047 not SAME SURFACE"
    bash "$SELF" stats || stopnow "stats"; bash "$SELF" prep go || stopnow "prep"
    bash "$SELF" go || stopnow "go" ;;
  status)
    [ -e "$LOG" ] && grep -E "===|STOPPED|DONE|archive|stopping" "$LOG" | cut -c1-150 || echo "no c10 log yet"; [ -f $W/c10_night.log ] && tail -8 $W/c10_night.log | cut -c1-160
    for f in $W/c10_train_*_$DAY.log; do [ -e "$f" ] || continue; echo "--- $(basename $f): $(grep -E '^Epoch' $f | tail -1 | cut -c1-120)"; done
    [ -e $W/c10_hardcap.log ] && echo "--- hard cap log: $(tail -1 $W/c10_hardcap.log)"
    [ -e $SUM ] && cat $SUM ;;
  *) echo "usage: $0 meta|fetch dry|go|r1|stats|prep dry|go|go|status|summary"; exit 2 ;;
esac
