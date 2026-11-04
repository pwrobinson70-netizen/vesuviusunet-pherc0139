#!/usr/bin/env python3
"""umbilicus_from_pred: the scroll centre from the organisers' surface prediction, straight from the public zarr.  (MIT)

    vun-umbilicus-pred --z 2074,2115 [--method hole|ring] [--um 38.4] [--out-csv F]                  # centre at these heights
    vun-umbilicus-pred --compare PUBLISHED_UMBILICUS_9p6um.json --z-csv results/centre_l4_slices_sha256.csv --out-csv F

Source: the m7 surface prediction of PHerc. Paris 4 (OME-Zarr v2, 6 levels, public, CC BY-NC 4.0)
https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/representations/predictions/surfaces/20260411134726-surface-20260413222639-surface-m7-L2-th0.2.zarr
The tool READS the multiscale metadata and picks the level whose voxel size is nearest --um (default 38.4 um). In this zarr level 0 is the 9.6 um grid
(shape 18946 x 8174 x 8174; the "L2" in the name is the scan level it was computed on), so 38.4 um is level 2 (4737 x 2044 x 2044), the same grid as
Brief 25's level-4 CT slices. Heights are given in that grid (`z4`); the published centre line (umbilicus_9p6um.json) is divided by 4.

Two centre estimators on the binarised prediction (value >= 128) of one plane:

  hole   close the papyrus mask with a disc, find background components enclosed by papyrus (not touching the image border), take the one nearest the
         centroid of the filled scroll body and return its centroid; the disc radius grows from 2 px until such a hole of at least --min-hole-px exists.
  ring   the innermost ring: over a grid of candidate centres inside the body, cast rays, take the first papyrus pixel on each ray; a candidate is
         usable if >= 90 % of rays hit within the body; the centre is the usable candidate where the first-hit radius is most constant
         (smallest std / mean), refined on a 1 px grid. (Minimising the plain mean radius is degenerate: it is zero next to any sheet.)

Reading from the network needs `numcodecs` and `requests`-free stdlib urllib. Exit 0 on success, 2 on bad input, 3 on network failure.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

BASE = ("https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/representations/predictions/surfaces/"
        "20260411134726-surface-20260413222639-surface-m7-L2-th0.2.zarr")
BASE_UM = 9.6          # level 0 of this zarr (the scan's 2.4 um grid is level 2 of the CT; the prediction was made at 9.6 um)
ON_VALUE = 128


def _get(url, tries=4):
    err = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            err = e
        except Exception as e:  # noqa: BLE001 - network noise, retried
            err = e
    raise ConnectionError(f"fetch failed {url}: {err}")


def read_levels(base=BASE):
    """-> list of dict(path, scale (z, y, x), um, shape, chunks) from .zattrs and each level's .zarray."""
    meta = json.loads(_get(base + "/.zattrs"))
    out = []
    for ds in meta["multiscales"][0]["datasets"]:
        za = json.loads(_get(f"{base}/{ds['path']}/.zarray"))
        sc = [t for t in ds["coordinateTransformations"] if t["type"] == "scale"][0]["scale"]
        out.append(dict(path=ds["path"], scale=sc, um=BASE_UM * float(sc[-1]), shape=za["shape"], chunks=za["chunks"]))
    return out


def pick_level(levels, um=38.4):
    return min(levels, key=lambda L: abs(math.log(L["um"] / um)))


def fetch_plane(z, level, base=BASE, jobs=16, cache=None):
    """uint8 [y, x] plane z of a level dict from pick_level(). `cache` (dict) keeps decoded chunks, so heights in one z-chunk share downloads."""
    import numcodecs
    cz_, cy_, cx_ = level["chunks"]
    nz, ny, nx = level["shape"]
    if not 0 <= z < nz:
        raise ValueError(f"z {z} outside 0..{nz - 1}")
    cz, oz = divmod(int(z), cz_)
    out = np.zeros((ny, nx), np.uint8)
    cache = {} if cache is None else cache

    def one(t):
        cy, cx = t
        key = (level["path"], cz, cy, cx)
        if key not in cache:
            b = _get(f"{base}/{level['path']}/{cz}/{cy}/{cx}")
            if b is None:
                cache[key] = None
            else:
                a = np.frombuffer(numcodecs.Blosc().decode(b), np.uint8)
                nzc = min(cz_, nz - cz * cz_)
                cache[key] = a.reshape(cz_, cy_, cx_)[:nzc] if a.size == cz_ * cy_ * cx_ else a.reshape(nzc, -1)
        ch = cache[key]
        if ch is None:
            return
        y0, x0 = cy * cy_, cx * cx_
        tile = ch[oz]
        out[y0:y0 + cy_, x0:x0 + cx_] = tile[:min(cy_, ny - y0), :min(cx_, nx - x0)]

    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(one, [(cy, cx) for cy in range((ny + cy_ - 1) // cy_) for cx in range((nx + cx_ - 1) // cx_)]))
    return out


def _disc(r):
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (yy * yy + xx * xx) <= r * r


def centre_hole(plane, min_hole_px=30, r_max=14):
    """-> (cy, cx, info) or None. See module docstring."""
    from scipy import ndimage as ndi
    m = plane >= ON_VALUE
    if m.sum() < 1000:
        return None
    body0 = ndi.binary_fill_holes(ndi.binary_closing(m, _disc(8)))
    lab, n = ndi.label(body0)
    if n == 0:
        return None
    big = np.argmax(ndi.sum(body0, lab, range(1, n + 1))) + 1
    body = lab == big
    by, bx = ndi.center_of_mass(body)
    for r in range(2, r_max + 1):
        closed = ndi.binary_closing(m, _disc(r), border_value=0)
        bg = ~closed
        lab, n = ndi.label(bg)
        if n == 0:
            continue
        border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
        cands = []
        for i in range(1, n + 1):
            if i in border:
                continue
            ys, xs = np.nonzero(lab == i)
            if len(ys) < min_hole_px or not body[int(ys.mean()), int(xs.mean())]:
                continue
            cands.append((math.hypot(ys.mean() - by, xs.mean() - bx), ys.mean(), xs.mean(), len(ys)))
        if cands:
            d, cy, cx, a = min(cands)
            return float(cy), float(cx), dict(close_r=r, hole_px=int(a), body_cy=float(by), body_cx=float(bx))
    return None


def centre_ring(plane, n_rays=72, step=4):
    """-> (cy, cx, info) or None. See module docstring."""
    from scipy import ndimage as ndi
    m = plane >= ON_VALUE
    if m.sum() < 1000:
        return None
    body = ndi.binary_fill_holes(ndi.binary_closing(m, _disc(8)))
    lab, n = ndi.label(body)
    if n == 0:
        return None
    body = lab == (np.argmax(ndi.sum(body, lab, range(1, n + 1))) + 1)
    by, bx = ndi.center_of_mass(body)
    ys, xs = np.nonzero(body)
    R = float(np.sqrt(body.sum() / math.pi))
    th = np.linspace(0, 2 * math.pi, n_rays, endpoint=False)
    dy, dx = np.sin(th), np.cos(th)
    rr = np.arange(1, int(1.2 * R) + 1, 0.5)
    H, W = m.shape

    def score(cy, cx):
        py = np.clip(np.round(cy + rr[None, :] * dy[:, None]).astype(int), 0, H - 1)
        px = np.clip(np.round(cx + rr[None, :] * dx[:, None]).astype(int), 0, W - 1)
        hit = m[py, px]
        if m[int(round(cy)), int(round(cx))]:
            return None
        first = np.where(hit.any(1), hit.argmax(1), -1)
        ok = first >= 0
        if ok.mean() < 0.9:
            return None
        r = rr[first[ok]]
        mu = r.mean()
        return float(r.std() / mu) if mu >= 2 else None

    def search(cy0, cx0, half, st):
        best = (None, None, None)
        for cy in np.arange(cy0 - half, cy0 + half + 1e-9, st):
            for cx in np.arange(cx0 - half, cx0 + half + 1e-9, st):
                s = score(cy, cx)
                if s is not None and (best[0] is None or s < best[0]):
                    best = (s, cy, cx)
        return best

    s, cy, cx = search(by, bx, 0.35 * R, step)
    if s is None:
        return None
    s, cy, cx = search(cy, cx, step, 1)
    return float(cy), float(cx), dict(rel_spread=float(s), body_cy=float(by), body_cx=float(bx), body_radius_px=R)


METHODS = {"hole": centre_hole, "ring": centre_ring}


def published_centre(path):
    """-> z4, y4, x4 arrays of the published 9.6 um centre line divided by 4 (level-4 / 38.4 um voxels), sorted by z."""
    cp = json.load(open(path))["control_points"]
    a = np.array([[c["z"], c["y"], c["x"]] for c in cp], float)
    a = a[np.argsort(a[:, 0])] / 4.0
    return a[:, 0], a[:, 1], a[:, 2]


def _one_height(args):
    z, method, um, base, published = args
    levels = read_levels(base)
    L = pick_level(levels, um)
    plane = fetch_plane(z, L, base, 8)
    res = METHODS[method](plane)
    row = dict(z=int(z), method=method, level=L["path"], voxel_um=L["um"])
    if res is None:
        row.update(ok=0, est_y="", est_x="", err_vox="", err_um="")
        return row
    cy, cx, info = res
    row.update(ok=1, est_y=f"{cy:.2f}", est_x=f"{cx:.2f}", info=json.dumps(info))
    if published:
        zs, zy, zx = published_centre(published)
        ty, tx = float(np.interp(z, zs, zy)), float(np.interp(z, zs, zx))
        e = math.hypot(cy - ty, cx - tx)
        row.update(true_y=f"{ty:.2f}", true_x=f"{tx:.2f}", err_vox=f"{e:.2f}", err_um=f"{e * L['um']:.0f}")
    return row


def run_heights(heights, method, um=38.4, base=BASE, published=None, jobs=4):
    """One row per height: estimated centre (y, x in the chosen level's voxels) and, with `published`, the error against it."""
    L = pick_level(read_levels(base), um)
    args = [(z, method, um, base, published) for z in heights]
    if jobs <= 1:
        rows = [_one_height(a) for a in args]
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(jobs) as ex:
            rows = list(ex.map(_one_height, args))
    return rows, L


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--z", help="comma-separated heights in the chosen level's grid (38.4 um: the level-4 CT index)")
    ap.add_argument("--z-csv", help="CSV with a z_level4 column (e.g. results/centre_l4_slices_sha256.csv)")
    ap.add_argument("--method", choices=sorted(METHODS), default="hole")
    ap.add_argument("--um", type=float, default=38.4, help="target voxel size; the zarr level nearest to it is used")
    ap.add_argument("--compare", metavar="UMBILICUS_9p6um.json", help="published centre line to compare with")
    ap.add_argument("--out-csv")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--base", default=BASE)
    a = ap.parse_args(argv)
    zs = []
    if a.z:
        try:
            zs += [int(v) for v in a.z.split(",") if v]
        except ValueError:
            print("error: --z must be integers", file=sys.stderr)
            return 2
    if a.z_csv:
        with open(a.z_csv) as fh:
            zs += [int(r["z_level4"]) for r in csv.DictReader(fh)]
    if not zs:
        print("error: give --z or --z-csv", file=sys.stderr)
        return 2
    try:
        rows, L = run_heights(sorted(set(zs)), a.method, a.um, a.base, a.compare, a.jobs)
    except ConnectionError as e:
        print(f"network error: {e}", file=sys.stderr)
        return 3
    if a.out_csv:
        cols = []
        for r in rows:
            cols += [k for k in r if k not in cols]
        with open(a.out_csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    errs = [float(r["err_vox"]) for r in rows if r.get("err_vox") not in (None, "")]
    print(json.dumps(dict(level=L["path"], voxel_um=L["um"], heights=len(rows), estimated=sum(r["ok"] for r in rows),
                          mean_err_vox=float(np.mean(errs)) if errs else None, worst_err_vox=float(np.max(errs)) if errs else None)))
    if not a.out_csv:
        for r in rows:
            print({k: r[k] for k in r if k != "info"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
