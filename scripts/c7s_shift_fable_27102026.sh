#!/usr/bin/env bash
# c7s_shift_fable_27102026.sh  (rev1, [fable], 27 Oct 2026) -- PHerc0139 LABEL-SHIFT DIAGNOSTIC (post hoc, labelled as such).
# Question (Sonnet 358/360): is the within-box failure (val AUC 0.48-0.58 while train loss -> 0.27) caused by a residual label shift of
# ~9 px down / ~2.5 px right (the footprint asymmetry, relay 345)? Test: retrain the 240-epoch rung on the SAME four boxes with the
# labels moved (dy,dx) = (-9,-2) [moves the map up/left = the "correcting" direction] and (+9,+2) [control], everything else = c7r e240.
# Readout = each model's OWN within-box validation AUC (interleaved val strips of its own box). w045 and the title are NOT touched.
# Pre-registered gate (relay 357): see "summary".
#   bash /workspace/c7s_shift_fable_27102026.sh prep     build data_c7s_<t>_<tag> folders: symlinks to the rev5 tifs + mask, shifted inklabels.png
#   bash /workspace/c7s_shift_fable_27102026.sh go       8 runs (2 shifts x 4 boxes x 240 ep) -> summary -> archive -> STOP THE POD (cap armed first)
#   bash /workspace/c7s_shift_fable_27102026.sh status
#   bash /workspace/c7s_shift_fable_27102026.sh summary  (read-only; also run automatically at the end of go)
set -uo pipefail
W=/workspace; PROJ=$W/VesuviusUNET; LS=$W/c7_LS.txt; SELF=$(readlink -f "$0"); KD=/root/c7r_stop
LOG=$W/c7s_train_nohup.log; SUM=$W/c7s_summary_27102026.txt; STOPLOG=$W/c7s_autostop.log; DAY=27102026; CAP_H=4
ORDER="w042 w043 w044 w047"; SHIFTS="m9m2:-9:-2 p9p2:9:2"; EP=240; DEPTH=16
BASE="--patch_size 64 --stride 64 --depth $DEPTH --base_channels 8 --batch_size 8 --gpus 0 --num_workers 4 --no_amp --aggregation max --loss bce_dice --seed 42 --lr 0.0003 --epochs $EP"
log(){ echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"; }
fail(){ log "STOPPED: $*"; exit 1; }
one(){ local n; n=$(ls -d $1 2>/dev/null | wc -l); [ "$n" -ge 1 ] || { echo "STOPPED: no folder matches $1" >&2; exit 1; }; ls -d $1 | sort | tail -1; }
podenv(){ for v in RUNPOD_POD_ID RUNPOD_API_KEY; do [ -n "${!v:-}" ] || { line=$(tr '\0' '\n' < /proc/1/environ 2>/dev/null | grep "^$v=" | head -1); [ -n "$line" ] && export "$line"; }; done
          [ -n "${RUNPOD_API_KEY:-}" ] && command -v runpodctl >/dev/null && runpodctl config --apiKey "$RUNPOD_API_KEY" >/dev/null 2>&1; }
cd "$PROJ" || fail "no $PROJ"
case "${1:-status}" in
  prep)
    for t in $ORDER; do src=$PROJ/$(one "data_seg_${t}_*_native_rev5") || fail "no rev5 folder for $t"
      for s in $SHIFTS; do IFS=: read -r tag dy dx <<< "$s"; d=$PROJ/data_c7s_${t}_${tag}
        [ -e "$d" ] && { echo "exists: $d (kept)"; continue; }
        mkdir -p "$d"; for f in "$src"/[0-9][0-9].tif "$src"/mask.png; do ln -s "$f" "$d/"; done
        python3 - "$src/inklabels.png" "$d/inklabels.png" "$dy" "$dx" <<'PY' || fail "shift failed"
import sys, numpy as np
from PIL import Image
src, dst, dy, dx = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
a = np.array(Image.open(src)); H, W = a.shape; b = np.zeros_like(a)
# label pixel (y, x) moves to (y + dy, x + dx); pixels shifted in from outside are 0 (no ink)
ys, yd = (slice(0, H - dy), slice(dy, H)) if dy >= 0 else (slice(-dy, H), slice(0, H + dy))
xs, xd = (slice(0, W - dx), slice(dx, W)) if dx >= 0 else (slice(-dx, W), slice(0, W + dx))
b[yd, xd] = a[ys, xs]
Image.fromarray(b).save(dst)
print("%s: ink share %.4f -> %.4f (shift dy %+d dx %+d)" % (dst.split("/")[-2], (a > 0).mean(), (b > 0).mean(), dy, dx))
PY
      done; done
    ls -d data_c7s_* ;;
  go)
    [ -e "$LOG" ] && { echo "refusing: $LOG exists"; exit 1; }
    python3 -c "import sklearn" 2>/dev/null || fail "scikit-learn missing - run c7r pre first"
    for t in $ORDER; do for s in $SHIFTS; do tag=${s%%:*}; [ -d data_c7s_${t}_${tag} ] || fail "run prep first"; [ -e runs/c7s_${t}_${tag}_e${EP}_$DAY ] && fail "run folder exists"; done; done
    podenv; command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] || fail "self-stop not available"
    [ -f $LS ] || fail "no $LS"; L=$(awk '/^L=/{print substr($0,3)}' $LS); S=$(awk '/^S=/{print substr($0,3)}' $LS)
    mkdir -p $KD; chmod 700 $KD
    printf '#!/usr/bin/env bash\nexport RUNPOD_POD_ID=%s RUNPOD_API_KEY=%s\nsleep %d; sync; runpodctl config --apiKey $RUNPOD_API_KEY >/dev/null 2>&1\nfor i in 1 2 3 4 5; do echo "[$(date -u)] c7s hard cap reached, stopping pod"; runpodctl stop pod %s && break; sleep 60; done\n' \
      "$RUNPOD_POD_ID" "$RUNPOD_API_KEY" $(( (CAP_H + 1) * 3600 )) "$RUNPOD_POD_ID" > $KD/c7s_hardcap.sh; chmod 700 $KD/c7s_hardcap.sh
    setsid nohup bash $KD/c7s_hardcap.sh > $W/c7s_hardcap.log 2>&1 < /dev/null &
    echo $! > $W/c7s_hardcap.pid; log "hard cap armed: pod stops at $(date -u -d "+$((CAP_H + 1)) hours" '+%H:%M UTC') at the latest"
    { echo "c7s shift diagnostic record $DAY $(date -u '+%H:%M UTC'): POST HOC, after the C7 re-run (relay 353/360); gate relay 357"
      echo "train.py $(tr -d '\r' < vesuvius_unet/train.py | sha256sum | cut -c1-16) dataset.py $(tr -d '\r' < vesuvius_unet/dataset.py | sha256sum | cut -c1-16) this script $(sha256sum "$SELF" | cut -c1-16)"
      echo "C5_AUG=1 C5_L=$L C5_S=$S; args $BASE; shifts $SHIFTS"; } > $W/c7s_record_$DAY.txt
    cat > $W/c7s_seq_$DAY.sh <<EOF
#!/usr/bin/env bash
cd $PROJ; export C5_AUG=1 C5_L=$L C5_S=$S C5_P=0.8
( while true; do sleep 120; find runs -maxdepth 2 -path "runs/c7s_*_$DAY/*" -name "epoch*.pt" -mmin +2 -delete 2>/dev/null; done ) > /dev/null 2>&1 &
PRN=\$!
for s in $SHIFTS; do tag=\${s%%:*}; for t in $ORDER; do
  out=runs/c7s_\${t}_\${tag}_e${EP}_$DAY
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === TRAIN \$tag \$t -> \$out ==="
  python3 -u -m vesuvius_unet.train --data_dir data_c7s_\${t}_\${tag} --output_dir \$out $BASE > $W/c7s_train_\${t}_\${tag}_$DAY.log 2>&1
  rc=\$?; echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === \$tag \$t finished rc=\$rc; last.pt \$(sha256sum \$out/last.pt 2>/dev/null | cut -c1-16) ==="
  [ \$rc = 0 ] || { echo "STOPPED: \$tag \$t rc=\$rc"; break 2; }
done; done
kill \$PRN; find runs -maxdepth 2 -path "runs/c7s_*_$DAY/*" -name "epoch*.pt" -delete 2>/dev/null
echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] TRAINING DONE"
bash $SELF summary > $SUM 2>&1
cd $W; A=$W/c7s_archive_\$(date -u +%Y%m%d_%H%M).tgz
{ ls c7s_* | grep -v -e archive -e hardcap.sh; for r in VesuviusUNET/runs/c7s_*_$DAY; do find \$r -type f ! -name '*.pt'; done; } > $W/c7s_archive_list.txt
tar czf \$A -T $W/c7s_archive_list.txt && sha256sum \$A > \$A.sha256 && echo "archive \$A \$(stat -c %s \$A) B"
sync; sleep 60; runpodctl config --apiKey "\$RUNPOD_API_KEY" >/dev/null 2>&1
for i in 1 2 3 4 5; do echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] stopping pod \$RUNPOD_POD_ID"; runpodctl stop pod \$RUNPOD_POD_ID && break; sleep 60; done
EOF
    RUNPOD_POD_ID=$RUNPOD_POD_ID RUNPOD_API_KEY=$RUNPOD_API_KEY setsid nohup bash $W/c7s_seq_$DAY.sh > "$LOG" 2>&1 < /dev/null &
    sleep 20; log "started (8 runs ~10 min each); record $W/c7s_record_$DAY.txt"; head -2 "$LOG" ;;
  summary)
    python3 - "$W" "$DAY" <<'PY'
import sys, re, glob, os
W, DAY = sys.argv[1], sys.argv[2]
def tail_auc(f, n=20):
    v = [float(m.group(1)) for m in (re.search(r"^Epoch \d+:.*val_AUC=([0-9.]+)", l) for l in open(f)) if m]
    return (sum(v[-n:]) / len(v[-n:]), v[-1], len(v)) if v else (float("nan"), float("nan"), 0)
rows = {}
for t in ("w042", "w043", "w044", "w047"):
    b = os.path.join(W, "c7r_train_%s_e240_26102026.log" % t)
    rows.setdefault(t, {})["0,0 (c7r e240)"] = tail_auc(b) if os.path.exists(b) else None
    for tag in ("m9m2", "p9p2"):
        f = os.path.join(W, "c7s_train_%s_%s_%s.log" % (t, tag, DAY))
        rows[t][tag] = tail_auc(f) if os.path.exists(f) else None
print("PHerc0139 label-shift diagnostic (POST HOC). Within-box val AUC: mean of the last 20 epochs (last epoch, epochs logged)")
cols = ["0,0 (c7r e240)", "m9m2", "p9p2"]
print("box   " + "".join("%-26s" % c for c in cols))
means = {c: [] for c in cols}
for t, r in rows.items():
    cells = []
    for c in cols:
        x = r.get(c)
        cells.append("%-26s" % ("%.3f (%.3f, %d ep)" % x if x else "missing"))
        if x and x[2] >= 200: means[c].append(x[0])
    print(t + "  " + "".join(cells))
print("mean  " + "".join("%-26s" % ("%.3f (n %d)" % (sum(v) / len(v), len(v)) if v else "n/a") for v in means.values()))
base = rows
for tag in ("m9m2", "p9p2"):
    d = [rows[t][tag][0] - rows[t]["0,0 (c7r e240)"][0] for t in rows if rows[t].get(tag) and rows[t].get("0,0 (c7r e240)") and rows[t][tag][2] >= 200]
    if len(d) == 4:
        md = sum(d) / 4; k = sum(x >= 0.05 for x in d)
        verdict = "SHIFT HELPS (gate met)" if (md >= 0.10 and k >= 3) else "no evidence this shift fixes it"
        print("%s: mean gain %+.3f, boxes gaining >= 0.05: %d/4 -> %s" % (tag, md, k, verdict))
    else:
        print("%s: incomplete (%d of 4 runs with >= 200 epochs)" % (tag, len(d)))
PY
    ;;
  status)
    [ -e "$LOG" ] && grep -E "===|STOPPED|DONE|archive|stopping" "$LOG" | cut -c1-150 || echo "no c7s log yet"
    for f in $W/c7s_train_*_$DAY.log; do [ -e "$f" ] || continue; echo "--- $(basename $f): $(grep -E '^Epoch' $f | tail -1 | cut -c1-120)"; done
    [ -e $W/c7s_hardcap.log ] && echo "--- hard cap log: $(tail -1 $W/c7s_hardcap.log)"
    [ -e $SUM ] && cat $SUM ;;
  *) echo "usage: $0 prep|go|status|summary"; exit 2 ;;
esac
