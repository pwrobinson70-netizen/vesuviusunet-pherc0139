# [fable] c10_counted_fable_28102026.py - COUNTED C10 readout, pre-registered in relay 395 (Sonnet 394 item 1)
# before any C10 epoch line was read.
# Matched windows: the last 8.3 % of each run's training.
#   C10 (60 ep): mean val_AUC of its LAST 5 epochs.  C8 (240 ep): mean of its LAST 20 epochs.
# Gate (thresholds unchanged from 391):
#   FINER IS BETTER: mean diff >= +0.05 AND >= 3 of 4 boxes up >= 0.03
#   FINER IS WORSE:  mean diff <= -0.05
#   otherwise:       NO CLEAR DIFFERENCE
# The script's own `summary` (last-20 vs last-20) stays DESCRIPTIVE only.
# Usage (on the pod): python3 -I /workspace/c10_counted_fable_28102026.py /workspace
import sys, re, os

W = sys.argv[1] if len(sys.argv) > 1 else "/workspace"
PAT = re.compile(r"^Epoch \d+:.*val_AUC=([0-9.]+)")
BOXES = (("h042", "f042"), ("h043", "f043"), ("h044", "f044"), ("h047", "f047"))
N10, K10, N8, K8 = 60, 5, 240, 20


def series(f):
    if not os.path.exists(f):
        return []
    return [float(m.group(1)) for m in (PAT.search(l) for l in open(f, errors="replace")) if m]


def mean(v):
    return sum(v) / len(v)


print("C10 COUNTED readout (pre-registered, relay 395): C10 last %d of %d ep vs C8 last %d of %d ep (both last 8.3 %%)" % (K10, N10, K8, N8))
print("box   C10 last-5   C8 last-20   diff     | descriptive: C10 last-20")
a10, a8, up, ok = [], [], 0, True
for h, f in BOXES:
    x = series(os.path.join(W, "c10_train_%s_28102026.log" % h))
    y = series(os.path.join(W, "c8_train_%s_27102026.log" % f))
    if len(x) != N10 or len(y) != N8:
        print("%s  INCOMPLETE: C10 %d of %d epochs, C8 %d of %d epochs" % (h, len(x), N10, len(y), N8))
        ok = False
        continue
    xm, ym = mean(x[-K10:]), mean(y[-K8:])
    a10.append(xm); a8.append(ym); up += (xm - ym) >= 0.03
    print("%s  %.3f        %.3f        %+.3f   | %.3f" % (h, xm, ym, xm - ym, mean(x[-20:])))
if ok and len(a10) == 4:
    d = mean(a10) - mean(a8)
    v = "FINER IS BETTER (gate met)" if (d >= 0.05 and up >= 3) else ("FINER IS WORSE" if d <= -0.05 else "NO CLEAR DIFFERENCE")
    print("COUNTED: C10 %.3f vs C8 %.3f: diff %+.3f, boxes up >= 0.03: %d/4 -> %s" % (mean(a10), mean(a8), d, up, v))
else:
    print("COUNTED: not available - a run is missing or short (no verdict; do not substitute a partial run)")
