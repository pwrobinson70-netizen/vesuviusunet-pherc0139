"""[fable] 5 Nov 2026 - true-blank test, step 1: pick windows from the HAND labels, by the rule in
docs/SCROLL1_TRUE_BLANK.md (committed before this runs). Reads only the coarse OME level of inklabels.zarr and
supervision.zarr (default level 4 = 38.4 um; a few MB per segment). No ink picture or CT is read here.

For each of the 8 labelled Scroll 1 segments (list order):
  candidate windows = 2 x 2 cm squares on a 2 mm grid, fully inside the label array;
  checked share     = fraction of the window inside supervision (> 0);
  ink share         = fraction of the window labelled ink (> 0);
  TRUE BLANK        = checked share >= 0.95 AND ink share == 0; among those, the one farthest from any labelled ink;
  INK (positive)    = the highest ink share among windows with checked share >= 0.95.
Blanks are taken from segments in list order until 3 are found; each segment that gives a blank also gives its INK
window. One CSV per segment (same columns as results/scroll1_letter_windows.csv) for scripts/letter_test_c1_scroll1.py.

Run (PowerShell):  C:\\VesuviusUNET\\venv_repo\\Scripts\\python.exe -u C:\\VesuviusUNET\\pick_trueblank_fable_05112026.py
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--bucket", default="https://vesuvius-challenge-open-data.s3.amazonaws.com")
ap.add_argument("--out", default=r"C:\VesuviusUNET\private\scroll1_trueblank_05112026")
ap.add_argument("--level", type=int, default=4)
ap.add_argument("--n-blank", type=int, default=3)
ap.add_argument("--min-checked", type=float, default=0.95)
ap.add_argument("--window-cm", type=float, default=2.0)
ap.add_argument("--step-mm", type=float, default=2.0)
a = ap.parse_args()
B = a.bucket.rstrip("/")
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
SEGS = ["20230702185753", "20230929220926", "20231007101619", "20231012184424", "20231016151002", "20231031143852",
        "20231106155351", "20231210121321"]
SUB = "ink-labels/2.4um-volume-20260411134726/20260918/"
UM0 = 2.4
STATS = {"bytes": 0}
os.makedirs(a.out, exist_ok=True)


def get(url):
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as f:
                b = f.read()
                STATS["bytes"] += len(b)
                return b
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
        except Exception:  # noqa: BLE001
            time.sleep(2)
    raise ConnectionError(url)


def keys_under(prefix):
    out, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        root = ET.fromstring(get(f"{B}/?{urllib.parse.urlencode(q)}"))
        out += [c.findtext(f"{NS}Key") for c in root.findall(f"{NS}Contents")]
        if root.findtext(f"{NS}IsTruncated") == "true":
            token = root.findtext(f"{NS}NextContinuationToken")
        else:
            return out


def fetch_level(seg, name, level, local_root):
    """Mirror <name>.zarr/zarr.json and level <level>/ to a local folder and read it with zarr (handles sharding)."""
    import zarr
    base = f"PHercParis4/segments/{seg}/{SUB}{name}.zarr/"
    loc = os.path.join(local_root, seg, f"{name}.zarr")
    for k in [base + "zarr.json"] + keys_under(f"{base}{level}/"):
        dst = os.path.join(loc, *k[len(base):].split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.isfile(dst):
            b = get(f"{B}/{urllib.parse.quote(k)}")
            if b is None:
                raise ConnectionError(f"could not read {k}")
            open(dst, "wb").write(b)
    g = zarr.open_group(loc, mode="r")
    ms = (g.attrs.get("ome") or {}).get("multiscales") or g.attrs.get("multiscales")
    sc = [t for t in ms[0]["datasets"][level]["coordinateTransformations"] if t["type"] == "scale"][0]["scale"]
    return np.asarray(g[str(level)][...]), float(sc[-1])


def box_sum(S, w):
    """Sum of every w x w box via an integral image; result[y, x] = sum S[y:y+w, x:x+w]."""
    I = np.pad(S.astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    return I[w:, w:] - I[:-w, w:] - I[w:, :-w] + I[:-w, :-w]


rows_all, report = [], []
blanks = 0
for seg in SEGS:
    if blanks >= a.n_blank:
        break
    try:
        ink, um = fetch_level(seg, "inklabels", a.level, a.out)
        sup, um2 = fetch_level(seg, "supervision", a.level, a.out)
    except Exception as e:  # noqa: BLE001
        report.append(f"{seg}: labels not readable ({type(e).__name__}: {e}) - skipped")
        continue
    f = um / UM0
    w = int(round(a.window_cm * 1e4 / um))
    st = max(1, int(round(a.step_mm * 1e3 / um)))
    I, S = (ink > 0), (sup > 0)
    if I.shape[0] < w or I.shape[1] < w:
        report.append(f"{seg}: label array {I.shape} smaller than a window ({w} px) - skipped")
        continue
    chk = box_sum(S, w)[::st, ::st] / (w * w)
    ins = box_sum(I, w)[::st, ::st] / (w * w)
    ok = chk >= a.min_checked
    from scipy.ndimage import distance_transform_edt
    dist = distance_transform_edt(~I) if I.any() else np.full(I.shape, 1e9)
    line = (f"{seg}: labels {I.shape[1]} x {I.shape[0]} px at {um:g} um (x{f:g} to 2.4 um); ink {I.mean():.4f}, "
            f"checked {S.mean():.3f}; {ok.sum()} windows with checked >= {a.min_checked}")
    blank_c = [(y, x) for y, x in zip(*np.nonzero(ok & (ins == 0)))]
    if not blank_c or not (ok & (ins > 0)).any():
        report.append(line + f"; true blanks {len(blank_c)} - no blank+ink pair, skipped")
        continue
    # true blank farthest from labelled ink (min distance over the window), then the INK window
    def mind(c):
        y, x = c[0] * st, c[1] * st
        return float(dist[y:y + w, x:x + w].min())
    by, bx = max(blank_c, key=mind)
    iy, ix = np.unravel_index(np.argmax(np.where(ok, ins, -1)), ins.shape)
    report.append(line + f"; true blanks {len(blank_c)}; chose blank at min ink distance {mind((by, bx)) * um / 1e3:.1f} mm, "
                  f"ink window ink share {ins[iy, ix]:.3f}")
    _, ikeys = (None, keys_under(f"PHercParis4/segments/{seg}/ink-detection/"))
    ink_key = [k for k in ikeys if "2.4um" in k and "20260411134726" in k and k.endswith(".tif")]
    seg_rows = []
    for role, (yy, xx), share in (("trueblank", (by, bx), 0.0), ("labelink", (iy, ix), float(ins[iy, ix]))):
        r0, c0 = int(yy * st * f), int(xx * st * f)
        win0 = int(round(a.window_cm * 1e4 / UM0))
        seg_rows.append(dict(role=role, segment=seg, ink_key=ink_key[0] if ink_key else "", ink_bytes="", ink_etag="",
                             row0_px=r0, col0_px=c0, row1_px=r0 + win0, col1_px=c0 + win0,
                             label_ink_share=f"{share:.4f}", checked_share=f"{chk[yy, xx]:.3f}",
                             rule="docs/SCROLL1_TRUE_BLANK.md", fixed_on="2026-11-05"))
    with open(os.path.join(a.out, f"trueblank_windows_{seg}.csv"), "w", encoding="utf-8", newline="\n") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(seg_rows[0].keys()), lineterminator="\n")
        wr.writeheader()
        wr.writerows(seg_rows)
    rows_all += seg_rows
    blanks += 1

print(f"\n[fable] true-blank step 1 - window pick from hand labels - {time.strftime('%d %b %Y %H:%M')}")
for line in report:
    print(line)
for r in rows_all:
    print(f"  {r['segment']} {r['role']:9s} rows {r['row0_px']}-{r['row1_px']} cols {r['col0_px']}-{r['col1_px']} px (2.4 um), "
          f"label ink {r['label_ink_share']}, checked {r['checked_share']}")
print(f"segments with a pair: {blanks}; downloaded {STATS['bytes'] / 1e6:.1f} MB; CSVs in {a.out}")
print("Labels at coarse level only; no ink picture, CT or full-resolution label was read.")
