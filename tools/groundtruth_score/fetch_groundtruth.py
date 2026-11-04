#!/usr/bin/env python3
"""Rebuild a public ground-truth sample of verified PHerc. Paris 4 (Scroll 1) patches (CC BY-NC 4.0), with retries and resume.

Selection rule (reverse-engineered from the two published samples and checked against every patch in them):
the 22563 verified-patch folder names, sorted; candidates = names[OFFSET::141]; walk the candidates in order, keep a patch when its
window is under 768 px in x and y and it has at least 100 valid grid cells, until 40 are kept (or 22 MB of output). OFFSET is 53
for seed 20261104 (testdata/pherc_paris4_groundtruth) and 32 for seed 20261105 (testdata/pherc_paris4_groundtruth_b).

Window = source meta.json bbox, 32 px margin, floor / ceil; heights = round(z0 + f (z1 - z0)) for f = 1/4, 1/2, 3/4.
Per patch: mesh.tifxyz (x, y shifted by the window origin, invalid = -1, mask.tif, zlib), slices/ (CT level 2, 8-bit, window), surfpred/ (m7
surface prediction, 8-bit, window). Only a patch with all 11 files is ever left on disk (written in a temp folder, then renamed).

    python fetch_groundtruth.py --offset 32 --out testdata/pherc_paris4_groundtruth_b [--verify-against DIR]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
import tifffile
from PIL import Image

ROOT = "https://vesuvius-challenge-open-data.s3.amazonaws.com/"
P = "PHercParis4/representations/spiral/20260411134726-spiral-dataset-20261019084150/"
PATCHES = P + "verified_patches/"
CT = "PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/2"
PRED = "PHercParis4/representations/predictions/surfaces/20260411134726-surface-20260413222639-surface-m7-L2-th0.2.zarr/0"
STEP, MARGIN, MAXWIN, MINVALID, MAXBYTES = 141, 32, 768, 100, 22_000_000
SESSION = requests.Session()


def get(url, rng=None, tries=6, ok404=False):
    last = None
    for k in range(tries):
        try:
            r = SESSION.get(url, headers={"Range": rng} if rng else {}, timeout=60)
            if r.status_code in (200, 206):
                return r.content
            if r.status_code in (403, 404):
                if ok404:
                    return None
                raise RuntimeError(f"HTTP {r.status_code} {url}")
            last = RuntimeError(f"HTTP {r.status_code} {url}")
        except (requests.RequestException, RuntimeError) as e:
            last = e
            if isinstance(e, RuntimeError) and "HTTP 40" in str(e):
                raise
        time.sleep(min(30, 2 ** k))
    raise RuntimeError(f"giving up on {url}: {last}")


def list_names():
    names, tok = [], None
    while True:
        q = {"list-type": "2", "prefix": PATCHES, "delimiter": "/"}
        if tok:
            q["continuation-token"] = tok
        x = get(ROOT + "?" + urllib.parse.urlencode(q)).decode()
        names += re.findall("<Prefix>" + re.escape(PATCHES) + "([^<]+)/</Prefix>", x)
        m = re.search("<NextContinuationToken>([^<]+)</NextContinuationToken>", x)
        if not m:
            return names
        tok = m.group(1)


def read_tif(b):
    return tifffile.imread(io.BytesIO(b))


def window_and_heights(meta):
    (x0, y0, z0), (x1, y1, z1) = meta["bbox"]
    win = dict(x0=int(math.floor(x0 - MARGIN)), x1=int(math.ceil(x1 + MARGIN)),
               y0=int(math.floor(y0 - MARGIN)), y1=int(math.ceil(y1 + MARGIN)))
    win["heights"] = [int(round(z0 + f * (z1 - z0))) for f in (0.25, 0.5, 0.75)]
    return win


def load_source(name):
    base = ROOT + PATCHES + name + "/"
    meta = json.loads(get(base + "meta.json"))
    x, y, z = (read_tif(get(base + f"{c}.tif")).astype(np.float32) for c in "xyz")
    mb = get(base + "mask.tif", ok404=True)
    mask = read_tif(mb) > 0 if mb is not None else np.ones(x.shape, bool)
    valid = mask & (x != -1) & (y != -1) & (z != -1)
    return meta, x, y, z, valid


def ct_window(z, y0, y1, x0, x1, jobs=16):
    """CT level 2 plane window by range requests (uncompressed 128^3 chunks, C order)."""
    CH = 128
    cz, oz = divmod(z, CH)
    out = np.zeros((y1 - y0, x1 - x0), np.uint8)
    tasks = [(cy, cx) for cy in range(y0 // CH, (y1 - 1) // CH + 1) for cx in range(x0 // CH, (x1 - 1) // CH + 1)]
    off = oz * CH * CH

    def one(t):
        cy, cx = t
        b = get(f"{ROOT}{CT}/{cz}/{cy}/{cx}", f"bytes={off}-{off + CH * CH - 1}", ok404=True)
        if b is None:
            return
        if len(b) != CH * CH:
            raise RuntimeError("short CT read")
        tile = np.frombuffer(b, np.uint8).reshape(CH, CH)
        ya, xa = max(y0, cy * CH), max(x0, cx * CH)
        yb, xb = min(y1, cy * CH + CH), min(x1, cx * CH + CH)
        out[ya - y0:yb - y0, xa - x0:xb - x0] = tile[ya - cy * CH:yb - cy * CH, xa - cx * CH:xb - cx * CH]

    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(one, tasks))
    return out


_PCACHE = {}


def pred_chunk(cz, cy, cx):
    k = (cz, cy, cx)
    if k not in _PCACHE:
        from numcodecs import Blosc
        b = get(f"{ROOT}{PRED}/{cz}/{cy}/{cx}", ok404=True)
        _PCACHE[k] = None if b is None else np.frombuffer(Blosc().decode(b), np.uint8).reshape(192, 192, 192)
        if len(_PCACHE) > 64:
            _PCACHE.pop(next(iter(_PCACHE)))
    return _PCACHE[k]


def pred_window(z, y0, y1, x0, x1):
    CH = 192
    cz, oz = divmod(z, CH)
    out = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for cy in range(y0 // CH, (y1 - 1) // CH + 1):
        for cx in range(x0 // CH, (x1 - 1) // CH + 1):
            c = pred_chunk(cz, cy, cx)
            if c is None:
                continue
            ya, xa = max(y0, cy * CH), max(x0, cx * CH)
            yb, xb = min(y1, cy * CH + CH), min(x1, cx * CH + CH)
            out[ya - y0:yb - y0, xa - x0:xb - x0] = c[oz, ya - cy * CH:yb - cy * CH, xa - cx * CH:xb - cx * CH]
    return out


def build_patch(name, meta, x, y, z, valid, dst):
    win = window_and_heights(meta)
    tmp = dst + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    mesh = os.path.join(tmp, "mesh.tifxyz")
    os.makedirs(mesh)
    xs, ys, zs = x.copy(), y.copy(), z.copy()
    xs[valid] -= win["x0"]
    ys[valid] -= win["y0"]
    for a in (xs, ys, zs):
        a[~valid] = -1.0
    for c, a in zip("xyz", (xs, ys, zs)):
        tifffile.imwrite(os.path.join(mesh, f"{c}.tif"), a.astype(np.float32), compression="zlib")
    tifffile.imwrite(os.path.join(mesh, "mask.tif"), (valid * 255).astype(np.uint8), compression="zlib")
    m = json.loads(json.dumps(meta))
    m["bbox"] = [[m["bbox"][0][0] - win["x0"], m["bbox"][0][1] - win["y0"], m["bbox"][0][2]],
                 [m["bbox"][1][0] - win["x0"], m["bbox"][1][1] - win["y0"], m["bbox"][1][2]]]
    m["source_folder"] = f"{ROOT}{PATCHES}{name}/"
    m["crop_note"] = (f"verified patch, 9.6 um grid (level 2 of the 2.4 um scan); x,y shifted by -({win['x0']},{win['y0']}); z unchanged; "
                      f"invalid cells set to -1 and mask.tif written (255 = valid; source mask applied where it existed); "
                      f"window x {win['x0']}:{win['x1']} y {win['y0']}:{win['y1']}; heights {win['heights']}")
    m["window"] = win
    json.dump(m, open(os.path.join(mesh, "meta.json"), "w"), indent=2)
    for sub, fn in (("slices", ct_window), ("surfpred", pred_window)):
        os.makedirs(os.path.join(tmp, sub))
        for h in win["heights"]:
            Image.fromarray(fn(h, win["y0"], win["y1"], win["x0"], win["x1"])).save(os.path.join(tmp, sub, f"{h:05d}.png"))
    return tmp, win


def complete(d):
    need = [f"mesh.tifxyz/{f}" for f in ("x.tif", "y.tif", "z.tif", "mask.tif", "meta.json")]
    try:
        win = json.load(open(os.path.join(d, "mesh.tifxyz", "meta.json")))["window"]
    except (OSError, ValueError, KeyError):
        return False
    need += [f"{s}/{h:05d}.png" for s in ("slices", "surfpred") for h in win["heights"]]
    return all(os.path.isfile(os.path.join(d, n)) and os.path.getsize(os.path.join(d, n)) > 0 for n in need)


def dir_bytes(d):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs)


def compare(a, b):
    """Compare two patch folders: meshes (arrays), meta window/bbox, PNG pixels. -> list of differences."""
    diffs = []
    for c in ("x", "y", "z", "mask"):
        pa, pb = (tifffile.imread(os.path.join(d, "mesh.tifxyz", c + ".tif")) for d in (a, b))
        if pa.shape != pb.shape or not np.array_equal(pa, pb):
            diffs.append(f"{c}.tif differs")
    ma, mb = (json.load(open(os.path.join(d, "mesh.tifxyz", "meta.json"))) for d in (a, b))
    for k in sorted(set(ma) | set(mb)):
        if ma.get(k) != mb.get(k):
            diffs.append(f"meta[{k}] differs")
    for s in ("slices", "surfpred"):
        fa, fb = sorted(os.listdir(os.path.join(a, s))), sorted(os.listdir(os.path.join(b, s)))
        if fa != fb:
            diffs.append(f"{s} file names differ")
            continue
        for f in fa:
            if not np.array_equal(np.array(Image.open(os.path.join(a, s, f))), np.array(Image.open(os.path.join(b, s, f)))):
                diffs.append(f"{s}/{f} pixels differ")
    return diffs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offset", type=int, required=True, help="candidate offset (53 = seed 20261104, 32 = seed 20261105)")
    ap.add_argument("--out", required=True, help="output folder; patches go to OUT/patches/")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--verify-against", help="folder of an existing sample: rebuild its patches that fall in the selection and compare")
    ap.add_argument("--only", help="comma-separated name substrings (debug)")
    a = ap.parse_args(argv)
    names = list_names()
    print(f"{len(names)} verified patch folders")
    cands = names[a.offset::STEP]
    print(f"{len(cands)} candidates (offset {a.offset}, step {STEP})")
    if a.only:
        cands = [c for c in cands if any(k in c for k in a.only.split(","))]
    pdir = os.path.join(a.out, "patches")
    os.makedirs(pdir, exist_ok=True)
    kept, total = [], 0
    for name in cands:
        if len(kept) >= a.n:
            break
        dst = os.path.join(pdir, name)
        try:
            meta, x, y, z, valid = load_source(name)
        except RuntimeError as e:
            print(f"skip (source unreadable: {e}) {name}")
            continue
        win = window_and_heights(meta)
        if win["x1"] - win["x0"] >= MAXWIN or win["y1"] - win["y0"] >= MAXWIN:
            print(f"skip (window too large) {name}")
            continue
        if int(valid.sum()) < MINVALID:
            print(f"skip (too few valid cells) {name}")
            continue
        if complete(dst):
            print(f"[{len(kept) + 1}/{a.n}] have {name}")
        else:
            shutil.rmtree(dst, ignore_errors=True)
            tmp, win = build_patch(name, meta, x, y, z, valid, dst)
            os.rename(tmp, dst)
            print(f"[{len(kept) + 1}/{a.n}] {name} grid {valid.shape} valid {int(valid.sum())} window {win['x1'] - win['x0']}x{win['y1'] - win['y0']} "
                  f"heights {win['heights']}", flush=True)
        if a.verify_against:
            ref = os.path.join(a.verify_against, "patches", name)
            if os.path.isdir(ref) and complete(ref):
                d = compare(dst, ref)
                print("   verify:", "IDENTICAL to the published patch" if not d else "DIFFERS: " + "; ".join(d))
        sz = dir_bytes(dst)
        if total + sz > MAXBYTES:
            print(f"size cap reached before {name}; stopping")
            shutil.rmtree(dst, ignore_errors=True)
            break
        total += sz
        kept.append(name)
    print(f"kept {len(kept)} patches, {total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
