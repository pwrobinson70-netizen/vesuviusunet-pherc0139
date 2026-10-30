#!/usr/bin/env bash
# c7r_rerun_fable_26102026_rev1g.sh  (rev1g, [fable], 27 Oct 2026; rev1g: "posctl" = Sonnet 346 positive control (footprint margins + reg24c --binary --hp 3 on every other converter folder with an edge); "override" = written GATE O override (OFFSET file kept as _OFFSET_overridden), go then labels every record/check line AFTER THE OUTLINE GATE FIRED (overridden); rev1f: the COUNTED e240 ensemble is scored right after the e240 rung (before e1000 trains), so a slower GPU (A4500) hitting the 6 h cap cannot lose the counted number; rev1e = Pedro 23:55 UTC "test a real stop now": the pod key gets Unauthorized on "get pod" even when configured, so a REAL stop is the proof: new "stoptest"; go accepts keytest OR a stoptest marker older than this container start; go requires sklearn (pre after a restart); alive() also checks the command line (pids are reused after a restart); rev1d = Sonnet 334: reg24c failure -> GATE O ERROR (go refuses), go re-arms the hard cap at CAP_H+1 from go, stopper scripts with the key live on /root (container disk), the old /workspace copy is removed; rev1c, Pedro 23:40 UTC: runpodctl 1.14 ignores the env key -> podenv writes it into runpodctl config on the pod, keytest proves it, go requires it; per-epoch snapshot PRUNER in the new run folders only; rev1b -- plan C7 RE-RUN ("ladder"). Sonnet 322: session A UNDER-TRAINED
# (60 epochs = ~3.8k steps vs C3's ~13.9k). Same four boxes, code and args as session A EXCEPT --epochs.
# rev1b = Sonnet 330 review + Pedro's answers 26 Oct ~23:25 UTC: re-run NOW; e240 is COUNTED (step-matched to C3), e1000 descriptive;
#   bar 0.70 (= P8a, set before session A); outline test per Sonnet 318 item 2 on the TITLE (selftest, --binary --hp 3, then plain
#   --binary, three readings) writing a gate file that go REQUIRES; go chains train -> score ONCE -> archive (no .pt) -> stop pod
#   (auto-stop on CHECK DONE / STOPPED / 6 h cap); nvidia-smi sampler; go refuses existing run folders.
# Gates and wording: relay 329 as amended by 331.
#   bash /workspace/c7r_rerun_fable_26102026_rev1g.sh pre        pip install, GPU, data folders, L/S, train.py schedule lines, runpodctl/self-stop check (read-only)
#   bash /workspace/c7r_rerun_fable_26102026_rev1g.sh keytest  read-only: runpodctl configured with the pod's key and can see this pod
#   bash /workspace/c7r_rerun_fable_26102026_rev1g.sh cap 7      HARD CAP: stop this pod after 7 h whatever happens (arm FIRST, right after pre)
#   bash /workspace/c7r_rerun_fable_26102026_rev1g.sh outline    GATE O (CPU, read-only except the gate file)
#   bash /workspace/c7r_rerun_fable_26102026_rev1g.sh go         Pedro's word: 8 runs (4 x 240 then 4 x 1000) -> check (scored ONCE) -> archive -> STOP THE POD
#   bash /workspace/c7r_rerun_fable_26102026_rev1g.sh status     progress
# Nothing is deleted. Session A's runs/logs/records are not touched (new names: suffix e240 / e1000, files c7r_*).
set -uo pipefail
W=/workspace; PROJ=$W/VesuviusUNET; LS=$W/c7_LS.txt; SELF=$(readlink -f "$0")
REG24C=$W/reg24_sonnet_25102026c.py; MARG=$W/c7r_margins_fable_27102026.py; MAPS=$W/c4_maps_fable_25102026_rev4b.py; STRIDE=16
KD=/root/c7r_stop   # rev1d: key-bearing stopper scripts on the container disk, never on the network volume
LOG=$W/c7r_train_nohup.log; CLOG=$W/c7r_check_nohup.log; GATE=$W/c7r_gateO; GPULOG=$W/c7r_gpu_util.csv; STOPLOG=$W/c7r_autostop.log
TAGO=""; [ -e $W/c7r_gateO_OVERRIDE ] && TAGO=" [AFTER THE OUTLINE GATE FIRED - overridden, see c7r_gateO_OVERRIDE]"
DAY=26102026                     # fixed: the pre-registration day (runs/c7_<t>_md_s42_bc8_d16_26102026e240 / ...e1000)
LADDER="240 1000"; COUNTED=240; DESCR=1000; BAR=0.70; ORDER="w042 w043 w044 w047"; DEPTH=16; CAP_H=6; SHARP=3.0
BASE="--patch_size 64 --stride 64 --depth $DEPTH --base_channels 8 --batch_size 8 --gpus 0 --num_workers 4 --no_amp --aggregation max --loss bce_dice --seed 42 --lr 0.0003"
alive(){ local st; [ -n "${1:-}" ] || return 1; st=$(ps -o stat= -p "$1" 2>/dev/null | tr -d ' '); [ -n "$st" ] && [ "${st#Z}" = "$st" ] && ps -o args= -p "$1" 2>/dev/null | grep -q "c7r_"; }   # ours and not a zombie
STOPMARK=/workspace/c7r_stoptest_TRIED
stopproven(){ local m b; [ -f $STOPMARK ] || return 1; m=$(stat -c %Y $STOPMARK); b=$(date -d "$(ps -o lstart= -p 1)" +%s 2>/dev/null) || return 1; [ "$m" -lt "$b" ]; }   # marker written, then the container restarted
log(){ echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"; }
fail(){ log "STOPPED: $*"; exit 1; }
one(){ local n; n=$(ls -d $1 2>/dev/null | wc -l); [ "$n" -ge 1 ] || { echo "STOPPED: no folder matches $1" >&2; exit 1; }
       [ "$n" = 1 ] || echo "NOTE: $n folders match $1; using the newest" >&2; ls -d $1 | sort | tail -1; }
loadLS(){ [ -f "$LS" ] || fail "$LS missing"; export C5_L=$(awk '/^L=/{print substr($0,3)}' "$LS") C5_S=$(awk '/^S=/{print substr($0,3)}' "$LS")
          [ -n "$C5_L" ] && [ -n "$C5_S" ] || fail "L/S not in $LS"; }
podenv(){ for v in RUNPOD_POD_ID RUNPOD_API_KEY; do   # Sonnet's c3_autostop pattern: the ssh shell lacks them, pid 1 has them
            [ -n "${!v:-}" ] || { line=$(tr '\0' '\n' < /proc/1/environ 2>/dev/null | grep "^$v=" | head -1); [ -n "$line" ] && export "$line"; }; done
          # rev1c: runpodctl 1.14 reads ~/.runpod/config.toml, not the env -> write the pod's own key there (value never printed)
          [ -n "${RUNPOD_API_KEY:-}" ] && command -v runpodctl >/dev/null && runpodctl config --apiKey "$RUNPOD_API_KEY" >/dev/null 2>&1; }
keyok(){ local o; o=$(runpodctl get pod "$RUNPOD_POD_ID" 2>&1); echo "$o" | head -4 | cut -c1-160; echo "$o" | grep -qiE "unauthorized|error|not found" && return 1; echo "$o" | grep -q "$RUNPOD_POD_ID"; }
# reading of one reg24c run: prints "<kind> dy dx sharp" with kind aligned|offset|unclear|flat
reading(){ local out dy dx sh; out=$(python3 -I "$REG24C" "$@" 2>&1); echo "$out" | grep -e "binary outline" -e "r(0,0)" -e "best" -e median -e top5 | cut -c1-200 >&2
  echo "$out" | grep -q "best |r|" || { echo "$out" | tail -3 | cut -c1-200 >&2; echo "error x x 0"; return; }   # rev1d: a failed run is an ERROR, not "flat"
  dy=$(echo "$out" | sed -n 's/.*at (dy, dx) = (\([-0-9]*\), \([-0-9]*\)).*/\1/p'); dx=$(echo "$out" | sed -n 's/.*at (dy, dx) = (\([-0-9]*\), \([-0-9]*\)).*/\2/p')
  sh=$(echo "$out" | sed -n 's/.*best\/median \([0-9.]*\).*/\1/p')
  [ -n "$dy" ] && [ -n "$dx" ] && [ -n "$sh" ] || { echo "flat x x 0"; return; }
  python3 - "$dy" "$dx" "$sh" "$SHARP" <<'PY'
import sys
dy, dx, sh, th = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
d = max(abs(dy), abs(dx))
k = "flat" if sh < th else ("aligned" if d <= 1 else ("offset" if d >= 3 else "unclear"))
print(k, dy, dx, sh)
PY
}
cd "$PROJ" || fail "no $PROJ"
case "${1:-status}" in
  pre)
    pip install -q --break-system-packages tifffile scipy pillow scikit-learn 2>&1 | tail -2
    python3 -c "import sklearn, tifffile, scipy, PIL; print('imports ok, sklearn', sklearn.__version__)" || fail "imports"
    python3 -c "import torch; assert torch.cuda.is_available(); print('GPU', torch.cuda.get_device_name(0))" || fail "no CUDA"
    loadLS; log "L/S (session A, unchanged) = $C5_L / $C5_S (want 83.0 / 69.5)"
    for t in $ORDER w045 title; do d=$(one "data_seg_${t}_*_native_rev5"); k=$(ls "$d" | grep -cE '^[0-9]{2}\.tif$'); echo "$t $d tifs $k $( [ -f $d/inklabels.png ] && echo labels-ok)"; done
    echo "title converter folder (outline test): $(one "data_seg_title_*_native") label_raw $( [ -f "$(one "data_seg_title_*_native")/label_raw.png" ] && echo ok || echo MISSING)"
    grep -q "c5_augment_fable_24102026" vesuvius_unet/dataset.py && echo "dataset.py has the C5 patch" || fail "C5 patch missing"
    for t in $ORDER; do for e in $LADDER; do [ -e runs/c7_${t}_md_s42_bc8_d16_${DAY}e$e ] && echo "WARNING: runs/c7_${t}_md_s42_bc8_d16_${DAY}e$e exists - go will refuse"; done; done
    echo "--- train.py lines about schedule / epochs (does the LR schedule stretch with --epochs?):"
    grep -nE "sched|cosine|OneCycle|StepLR|warmup|args\.epochs|T_max" vesuvius_unet/train.py | cut -c1-160
    echo "--- checkpoint saving:"; grep -nE "last\.pt|best\.pt|epoch[0-9]*\.pt|epoch%" vesuvius_unet/train.py | cut -c1-160
    podenv; echo "--- self-stop: runpodctl $(command -v runpodctl || echo MISSING); POD_ID ${RUNPOD_POD_ID:-MISSING}; API key $([ -n "${RUNPOD_API_KEY:-}" ] && echo present || echo MISSING)"
    [ -n "${RUNPOD_POD_ID:-}" ] && command -v runpodctl >/dev/null && { echo "--- runpodctl can see this pod (read-only call, proves the key works):"; keyok && echo "KEY OK" || echo "KEY NOT OK - self-stop will NOT work"; }
    df -h /workspace | tail -1 ;;
  outline)
    [ -f "$REG24C" ] || fail "$REG24C not on the pod - copy Sonnet's reg24_sonnet_25102026c.py to /workspace"
    rm -f ${GATE}_*; python3 -I "$REG24C" --selftest 2>&1 | tail -4 | cut -c1-200; python3 -I "$REG24C" --selftest >/dev/null 2>&1 || fail "reg24c selftest failed"
    t=$(one "data_seg_title_*_native") || { echo "GATE O ERROR: no title converter folder" > ${GATE}_ERROR; fail "no data_seg_title_*_native folder"; }
    T=$PROJ/$t; [ -n "$t" ] && [ -d "$T" ] && [ -f "$T/label_raw.png" ] || { echo "GATE O ERROR: $T missing or no label_raw.png" > ${GATE}_ERROR; fail "title folder $T missing / no label_raw.png"; }
    echo "--- title, --binary --hp 3"; r1=$(reading "$T" --M 24 --binary --hp 3); echo "    reading: $r1"
    echo "--- title, --binary (plain)"; r2=$(reading "$T" --M 24 --binary); echo "    reading: $r2"
    for t in $ORDER w045; do echo "--- box $t, --binary --hp 3 (DESCRIPTIVE ONLY, not gated)"; rb=$(reading "$PROJ/$(one "data_seg_${t}_*_native")" --M 24 --binary --hp 3); echo "    reading: $rb"; done
    k1=${r1%% *}; k2=${r2%% *}
    if [ "$k1" = error ] || [ "$k2" = error ]; then v=ERROR; why="reg24c failed on the title (see above) - no reading; go refuses"
    elif [ "$k1" = offset ] || [ "$k2" = offset ]; then v=OFFSET; why="a sharp outline peak >= 3 px off (0,0): labels offset - STOP, record the shift, do not train"
    elif [ "$k1" = unclear ] || [ "$k2" = unclear ]; then v=OFFSET; why="a sharp peak 2 px off (0,0) - between 318's readings; treated as STOP (conservative), ask Sonnet"
    elif [ "$k1" = aligned ] || [ "$k2" = aligned ]; then v=PASS; why="sharp outline peak at (0,0)+-1: aligned"
    else v=UNINFORMATIVE; why="no sharp peak (best/median < $SHARP) in either reading: uninformative - recorded, training may go (318)"; fi
    { echo "GATE O $v $(date -u '+%Y-%m-%d %H:%M UTC'): $why"; echo "title hp3: $r1"; echo "title plain: $r2"; } > ${GATE}_$v
    log "GATE O $v: $why (file ${GATE}_$v)"; [ $v = ERROR ] && exit 1; true ;;
  go)
    [ -e "$LOG" ] && { echo "refusing: $LOG exists (already started); use status"; exit 1; }
    { [ -e ${GATE}_PASS ] || [ -e ${GATE}_UNINFORMATIVE ] || [ -e ${GATE}_OVERRIDE ]; } || fail "no GATE O pass/uninformative file - run outline first (an OFFSET file means do not train)"
    [ -e ${GATE}_OFFSET ] && fail "GATE O OFFSET on record - do not train (a written override renames it: see override)"
    [ -e ${GATE}_ERROR ] && fail "GATE O ERROR on record - re-run outline once the error is fixed"
    for t in $ORDER; do for e in $LADDER; do [ -e runs/c7_${t}_md_s42_bc8_d16_${DAY}e$e ] && fail "runs/c7_${t}_md_s42_bc8_d16_${DAY}e$e already exists"; done; done
    podenv; command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] || fail "self-stop not available (runpodctl / POD_ID / API key) - not starting an unattended night run"
    python3 -c "import sklearn" 2>/dev/null || fail "scikit-learn missing (pod restarted?) - run pre first"
    if keyok >/dev/null; then echo "self-stop: keytest OK"; elif stopproven; then if grep -q "pod $RUNPOD_POD_ID" $STOPMARK; then echo "self-stop: PROVEN by stoptest ($(cat $STOPMARK)) and a container restart since"
      else echo "self-stop: stoptest passed on ANOTHER pod ($(cat $STOPMARK)); this pod $RUNPOD_POD_ID untested - accepted on Pedro's word (Trust it, go ahead, 27 Oct)"; fi
    else fail "self-stop not proven (keytest Unauthorized, no stoptest + restart) - not starting an unattended night run"; fi
    loadLS; export C5_AUG=1 C5_P="${C5_P:-0.8}"
    declare -A D; for t in $ORDER; do D[$t]=$(one "data_seg_${t}_*_native_rev5"); done
    rec=$W/c7r_train_record_$DAY.txt
    { echo "c7r re-run record $DAY $(date -u '+%H:%M UTC'): ladder $LADDER epochs; COUNTED e$COUNTED bar $BAR (ensemble papyrus AUC on w045, SECOND LOOK); e$DESCR descriptive; relay 329 + 331$TAGO"
      if [ -e ${GATE}_OVERRIDE ]; then head -1 ${GATE}_OVERRIDE; else cat ${GATE}_* | head -1; fi; echo "C5_AUG=1 C5_L=$C5_L C5_S=$C5_S C5_P=$C5_P"
      echo "dataset.py (CR-stripped) $(tr -d '\r' < vesuvius_unet/dataset.py | sha256sum | cut -c1-16); c5_augment $(tr -d '\r' < vesuvius_unet/c5_augment_fable_24102026.py | sha256sum | cut -c1-16); train.py $(tr -d '\r' < vesuvius_unet/train.py | sha256sum | cut -c1-16); this script $(sha256sum "$SELF" | cut -c1-16)"
      for t in $ORDER; do echo "$t data_dir ${D[$t]}"; done; echo "base args: $BASE --epochs <240|1000>"; } > "$rec"
    cat > $W/c7r_train_seq_$DAY.sh <<EOF
#!/usr/bin/env bash
cd $PROJ
export C5_AUG=1 C5_L=$C5_L C5_S=$C5_S C5_P=$C5_P
( echo "utc,gpu_util_pct,mem_used_mib"; while true; do echo "\$(date -u +%H:%M:%S),\$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits | tr -d ' ')"; sleep 60; done ) > $GPULOG 2>&1 &
SMP=\$!
( while true; do sleep 120   # rev1c PRUNER (Pedro 23:40 UTC): NEW run folders only; keeps last.pt, best.pt, epoch n with n%60==0 or (n+1)%60==0
    find runs -maxdepth 2 -path "runs/c7_*_md_s42_bc8_d16_${DAY}e*" -name "epoch*.pt" -mmin +2 2>/dev/null | while read f; do
      n=\$(basename "\$f" .pt | tr -dc 0-9); n=\$((10#\${n:-0})); [ \$((n % 60)) = 0 ] || [ \$(((n + 1) % 60)) = 0 ] || rm -f "\$f"; done
  done ) > $W/c7r_pruner.log 2>&1 &
PRN=\$!
for e in $LADDER; do for t in $ORDER; do
  case \$t in w042) d=${D[w042]};; w043) d=${D[w043]};; w044) d=${D[w044]};; w047) d=${D[w047]};; esac
  out=runs/c7_\${t}_md_s42_bc8_d16_${DAY}e\$e
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === TRAIN e\$e \$t data_dir \$d -> \$out ==="
  python3 -u -m vesuvius_unet.train --data_dir \$d --output_dir \$out $BASE --epochs \$e > $W/c7r_train_\${t}_e\${e}_$DAY.log 2>&1
  rc=\$?
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] === e\$e \$t finished rc=\$rc; last.pt \$(sha256sum \$out/last.pt 2>/dev/null | cut -c1-16) best.pt \$(sha256sum \$out/best.pt 2>/dev/null | cut -c1-16) ==="
  [ \$rc = 0 ] || { echo "STOPPED: e\$e \$t failed rc=\$rc"; kill \$SMP \$PRN; exit 1; }
done; echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] LADDER e\$e DONE (all four)"
  [ \$e = $COUNTED ] && { echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] scoring the COUNTED e$COUNTED ensemble now"; bash $SELF _checkc; echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] COUNTED check returned"; }
done
kill \$SMP \$PRN
find runs -maxdepth 2 -path "runs/c7_*_md_s42_bc8_d16_${DAY}e*" -name "epoch*.pt" | while read f; do   # final prune pass (training over)
  n=\$(basename "\$f" .pt | tr -dc 0-9); n=\$((10#\${n:-0})); [ \$((n % 60)) = 0 ] || [ \$(((n + 1) % 60)) = 0 ] || rm -f "\$f"; done
echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] ALL EIGHT TRAINED"
bash $SELF _checkd
EOF
    mkdir -p $KD; chmod 700 $KD
    cat > $KD/c7r_autostop_loop.sh <<EOF
#!/usr/bin/env bash
export RUNPOD_POD_ID='$RUNPOD_POD_ID' RUNPOD_API_KEY='$RUNPOD_API_KEY'
t0=\$(date +%s); why="check done"
while ! { grep -q "=== CHECK DONE" $CLOG 2>/dev/null || grep -q "STOPPED" $LOG 2>/dev/null; }; do
  sleep 60; [ \$(( \$(date +%s) - t0 )) -ge $(( CAP_H * 3600 )) ] && { why="ceiling $CAP_H h reached"; break; }
done
grep -q "STOPPED" $LOG 2>/dev/null && why="training STOPPED"
echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] \$why; archiving (no .pt)"
cd $W; A=$W/c7r_archive_\$(date -u +%Y%m%d_%H%M).tgz
{ ls c7r_* 2>/dev/null; ls c7_LS.txt; ls -d VesuviusUNET/runs/c7_*_${DAY}e* 2>/dev/null | while read r; do find \$r -type f ! -name '*.pt'; done
  ls -d VesuviusUNET/*c7rcheck_* 2>/dev/null | while read r; do find \$r -type f; done; } | grep -v -e "c7r_archive_" -e "c7r_autostop_loop.sh" -e "c7r_hardcap.sh" > $W/c7r_archive_list.txt   # the two stopper scripts hold the API key - never archived
tar czf \$A -T $W/c7r_archive_list.txt && sha256sum \$A > \$A.sha256 && echo "archive \$A \$(stat -c %s \$A) B"
sync; sleep 120
runpodctl config --apiKey "\$RUNPOD_API_KEY" >/dev/null 2>&1
echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] stopping pod \$RUNPOD_POD_ID now"
for i in 1 2 3 4 5; do runpodctl stop pod \$RUNPOD_POD_ID && { echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] stop accepted (try \$i)"; break; }
  echo "[\$(date -u '+%Y-%m-%d %H:%M:%S UTC')] stop failed (try \$i), retrying in 60 s"; sleep 60; done
EOF
    chmod 700 $KD/c7r_autostop_loop.sh
    setsid nohup bash $KD/c7r_autostop_loop.sh > "$STOPLOG" 2>&1 < /dev/null &
    echo $! > $W/c7r_autostop.pid
    # rev1d (Sonnet 334 #2): replace any earlier hard cap with one at CAP_H+1 h from NOW, so go's own stopper (CAP_H) always fires first
    if [ -f $W/c7r_hardcap.pid ]; then P=$(cat $W/c7r_hardcap.pid)
      if alive "$P"; then kill -- -"$P" 2>/dev/null || kill "$P" 2>/dev/null; sleep 1; alive "$P" && fail "could not cancel the earlier hard cap (pid $P)"; echo "earlier hard cap (pid $P) cancelled"
      else echo "earlier hard cap pid $P not running (pod restarted?) - nothing to cancel"; fi; rm -f $W/c7r_hardcap.pid; fi
    rm -f $W/c7r_hardcap.sh   # rev1b left a key-bearing copy on the network volume
    bash "$SELF" cap $(( CAP_H + 1 )) | tail -2; alive "$(cat $W/c7r_hardcap.pid 2>/dev/null)" || fail "new hard cap not running - not starting"
    setsid nohup bash $W/c7r_train_seq_$DAY.sh > "$LOG" 2>&1 < /dev/null &
    sleep 30; log "started; record $rec; autostop armed (log $STOPLOG, cap $CAP_H h)"; head -1 "$LOG" | cut -c1-160
    f=$W/c7r_train_w042_e240_$DAY.log; [ -f "$f" ] && grep -iE "val|error|Traceback|nan" "$f" | tail -3 | cut -c1-160 ;;
  posctl)   # read-only positive control (Sonnet 346): footprint margins on every converter folder with label_raw.png; reg24c --binary --hp 3 where the scan has an edge
    [ -f "$MARG" ] || fail "$MARG not on the pod"; [ -f "$REG24C" ] || fail "$REG24C not on the pod"
    for d in $(ls -d data_seg_*_native 2>/dev/null); do [ -f "$d/label_raw.png" ] || continue
      o=$(python3 -I "$MARG" "$PROJ/$d" 2>&1); echo "$o" | cut -c1-200
      echo "$o" | grep -q "no edge" && continue; echo "$o" | grep -q "skipped" && continue
      python3 -I "$REG24C" "$PROJ/$d" --M 24 --binary --hp 3 2>&1 | grep -e "r(0,0)" -e "best |r|" -e top5 -e "best/median" | sed 's/^/    reg24c hp3: /' | cut -c1-200
    done ;;
  override) # written override of a GATE O OFFSET (Pedro 27 Oct "Re-run tonight anyway" + two-agent written decision in the relay)
    [ -e ${GATE}_OFFSET ] || fail "no GATE O OFFSET file to override"
    [ -n "${2:-}" ] || fail "give the relay note numbers of the written decision, e.g. override 345-348"
    { echo "GATE O OVERRIDDEN $(date -u '+%Y-%m-%d %H:%M UTC'): decision in relay notes ${2}; Pedro 27 Oct: Re-run tonight anyway."
      echo "Reason (relay 345): map footprint = scan footprint grown on all four sides (+16 top, +34 bottom, +17 left, +22 right px) - the hp-3 outline"
      echo "  correlation measured growth, not a translation. Every result of this run is labelled AFTER THE OUTLINE GATE FIRED."
      echo "Original verdict:"; cat ${GATE}_OFFSET; } > ${GATE}_OVERRIDE
    mv ${GATE}_OFFSET ${GATE}_OFFSET_overridden; log "override written: ${GATE}_OVERRIDE (OFFSET kept as ${GATE}_OFFSET_overridden)"; cat ${GATE}_OVERRIDE ;;
  keytest)  # read-only: configure runpodctl with the pod's own key and prove it can see this pod
    podenv; [ -n "${RUNPOD_POD_ID:-}" ] || fail "no RUNPOD_POD_ID"; keyok && log "KEY OK: runpodctl sees pod $RUNPOD_POD_ID - self-stop can work (also fixes the cap armed earlier: it calls runpodctl at fire time)" || fail "KEY NOT OK - self-stop will not work" ;;
  stoptest) # REAL stop of THIS pod, once, to prove the pod's own key can stop it (Pedro 23:55 UTC). Press Start in RunPod afterwards.
    podenv; [ -n "${RUNPOD_POD_ID:-}" ] || fail "no RUNPOD_POD_ID"
    echo "stoptest $(date -u '+%Y-%m-%d %H:%M:%S UTC') pod $RUNPOD_POD_ID" > $STOPMARK; sync
    log "stopping pod $RUNPOD_POD_ID now (if this connection drops, it worked)"; runpodctl stop pod "$RUNPOD_POD_ID" 2>&1 | head -3; rc=${PIPESTATUS[0]}
    sleep 90; log "runpodctl exit $rc and the pod is still up after 90 s - the self-stop did NOT work (marker kept: it proves nothing without a restart)"; exit 1 ;;
  cap)      # safety net while the pod waits: stop THIS pod after N hours whatever happens (default 7). Independent of go's own stopper.
    podenv; command -v runpodctl >/dev/null && [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] || fail "self-stop not available (runpodctl / POD_ID / API key)"
    H=${2:-7}; mkdir -p $KD; chmod 700 $KD; [ -f $W/c7r_hardcap.pid ] && alive "$(cat $W/c7r_hardcap.pid)" && { echo "a hard cap is already armed: $(head -1 $W/c7r_hardcap.log)"; exit 0; }
    printf '#!/usr/bin/env bash\n# c7r_hardcap\nexport RUNPOD_POD_ID=%s RUNPOD_API_KEY=%s\nsleep %d; sync; runpodctl config --apiKey $RUNPOD_API_KEY >/dev/null 2>&1\nfor i in 1 2 3 4 5; do echo "[$(date -u)] hard cap reached, stopping pod"; runpodctl stop pod %s && break; sleep 60; done\n' \
      "$RUNPOD_POD_ID" "$RUNPOD_API_KEY" $(( H * 3600 )) "$RUNPOD_POD_ID" > $KD/c7r_hardcap.sh; chmod 700 $KD/c7r_hardcap.sh
    echo "hard cap armed $(date -u '+%Y-%m-%d %H:%M UTC'): pod stops at $(date -u -d "+$H hours" '+%Y-%m-%d %H:%M UTC') at the latest" > $W/c7r_hardcap.log
    setsid nohup bash $KD/c7r_hardcap.sh >> $W/c7r_hardcap.log 2>&1 < /dev/null &
    echo $! > $W/c7r_hardcap.pid; sleep 1; cat $W/c7r_hardcap.log; alive "$(cat $W/c7r_hardcap.pid)" && echo "hard cap process alive (pid $(cat $W/c7r_hardcap.pid))" || echo "WARNING: hard cap process not running" ;;
  _checkc)  # called by the training sequence after the e240 rung only - COUNTED, scored ONCE
    grep -q "LADDER e$COUNTED DONE" "$LOG" 2>/dev/null || fail "e$COUNTED rung not finished"
    [ -e "$CLOG" ] && { echo "refusing: counted check already started"; exit 1; }
    f45=$(one "data_seg_w045_*_native_rev5"); ft=$(one "data_seg_title_*_native_rev5")
    { echo "=== COUNTED (329/331): e$COUNTED ensemble, papyrus AUC on w045 (SECOND LOOK); PASS if >= $BAR$TAGO"
      python3 -I "$MAPS" --go --score --members C7 --c5_day "${DAY}e$COUNTED" --stride $STRIDE --stamp "c7rcheck_e${COUNTED}_$(date -u +%Y%m%d_%H%M)" $f45 $ft
      echo "=== COUNTED CHECK DONE"; } > "$CLOG" 2>&1 < /dev/null ;;
  _checkd)  # called by the training sequence at the end - DESCRIPTIVE only
    grep -q "ALL EIGHT TRAINED" "$LOG" 2>/dev/null || fail "training not finished"
    grep -q "=== COUNTED CHECK DONE" "$CLOG" 2>/dev/null || echo "NOTE: counted check missing or incomplete" >> "$CLOG"
    grep -q "=== DESCRIPTIVE ONLY" "$CLOG" 2>/dev/null && { echo "refusing: descriptive check already started"; exit 1; }
    f45=$(one "data_seg_w045_*_native_rev5"); ft=$(one "data_seg_title_*_native_rev5")
    { echo "=== DESCRIPTIVE ONLY: e$DESCR ensemble on w045 + title$TAGO"
      python3 -I "$MAPS" --go --score --members C7 --c5_day "${DAY}e$DESCR" --stride $STRIDE --stamp "c7rcheck_e${DESCR}_$(date -u +%Y%m%d_%H%M)" $f45 $ft
      echo "=== CHECK DONE"; } >> "$CLOG" 2>&1 < /dev/null ;;
  status)
    ls ${GATE}_* 2>/dev/null | sed 's/^/gate file: /'
    [ -e "$LOG" ] && grep -E "===|STOPPED|DONE|ALL EIGHT" "$LOG" | cut -c1-170 || echo "no training log yet"
    for f in $W/c7r_train_w0*_e*_$DAY.log; do [ -e "$f" ] || continue
      echo "--- $(basename "$f"): epochs $(grep -ciE 'epoch[ =]*[0-9]+.*(val|loss)' "$f"); last: $(grep -iE 'epoch' "$f" | tail -1 | cut -c1-150)"
      grep -ciE "Traceback|error| nan" "$f" | sed 's/^/    error\/nan lines: /'; done
    [ -e "$CLOG" ] && { echo "--- check log:"; grep -iE "auc|ensemble|STOP|error|Traceback|===" "$CLOG" | tail -30 | cut -c1-200; }
    [ -e "$STOPLOG" ] && { echo "--- autostop:"; tail -3 "$STOPLOG"; echo "    autostop alive: $(alive "$(cat $W/c7r_autostop.pid 2>/dev/null)" && echo yes || echo no)"; }
    [ -e $W/c7r_hardcap.log ] && echo "--- $(head -1 $W/c7r_hardcap.log); alive: $(alive "$(cat $W/c7r_hardcap.pid 2>/dev/null)" && echo yes || echo no)"
    [ -e "$GPULOG" ] && echo "--- GPU last: $(tail -1 $GPULOG)"
    echo "--- $(pgrep -fc '[v]esuvius_unet[.]train') train process(es); $(date -u '+%H:%M UTC')" ;;
  *) echo "usage: $0 pre|keytest|stoptest|cap [H]|outline|posctl|override NOTES|go|status"; exit 2 ;;
esac
