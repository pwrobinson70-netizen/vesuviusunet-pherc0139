#!/usr/bin/env python3
"""Fetch full z-planes of the public PHerc. Paris 4 zarr (level 4, 38.4 um) with HTTP range requests.

The level is stored uncompressed in 128^3 chunks (C order), so one z-plane of one chunk is a contiguous 16 KiB
range: a full 2044 x 2044 plane is 256 small requests (4 MB) instead of 512 MB of chunks.

    python fetch_l4_slices.py --z 140,1000,4500 --out DIR            # level-4 z indices
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

BASE = ("https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/volumes/"
        "20260411134726-2.400um-0.2m-78keV-masked.zarr")
LEVEL = 4
SHAPE = (4737, 2044, 2044)
CH = 128


def _get(url, rng=None, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Range": rng} if rng else {})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):          # absent chunk = fill value (0)
                return None
            err = e
        except Exception as e:                  # noqa: BLE001 - network noise, retried
            err = e
    raise RuntimeError(f"fetch failed {url}: {err}")


def fetch_plane(z, base=BASE, level=LEVEL, shape=SHAPE, jobs=16):
    """-> uint8 array [y, x] of level-`level` plane z."""
    cz, oz = divmod(int(z), CH)
    ny, nx = shape[1], shape[2]
    out = np.zeros((ny, nx), np.uint8)
    off = oz * CH * CH
    tasks = [(cy, cx) for cy in range((ny + CH - 1) // CH) for cx in range((nx + CH - 1) // CH)]

    def one(t):
        cy, cx = t
        b = _get(f"{base}/{level}/{cz}/{cy}/{cx}", f"bytes={off}-{off + CH * CH - 1}")
        if b is None:
            return
        if len(b) != CH * CH:
            raise RuntimeError(f"short read {len(b)} for chunk {cz}/{cy}/{cx}")
        tile = np.frombuffer(b, np.uint8).reshape(CH, CH)
        y0, x0 = cy * CH, cx * CH
        out[y0:y0 + CH, x0:x0 + CH] = tile[:min(CH, ny - y0), :min(CH, nx - x0)]

    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(one, tasks))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--z", required=True, help="comma-separated level-4 z indices")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    from PIL import Image
    os.makedirs(a.out, exist_ok=True)
    for z in [int(v) for v in a.z.split(",")]:
        img = fetch_plane(z)
        Image.fromarray(img).save(os.path.join(a.out, f"{z:05d}.png"), optimize=True, compress_level=9)
        print(z, img.shape, int(img.max()), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
