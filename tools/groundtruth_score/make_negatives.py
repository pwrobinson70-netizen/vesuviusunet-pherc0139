"""make_negatives: deliberately broken copies of the verified Scroll 1 patches (PHerc. Paris 4).  (MIT)

    python make_negatives.py GROUNDTRUTH_DIR OUT_DIR [--seed 20261104] [--patch NAME ...]
    (installed: `vun-negatives ...`)

GROUNDTRUTH_DIR is testdata/pherc_paris4_groundtruth (its README.md must say "PHerc. Paris 4", otherwise the tool refuses to run).
For each verified patch (a folder with mesh.tifxyz/meta.json; the raw leftovers without one are ignored) four tifxyz folders are written to
OUT_DIR/<patch>/<kind>/ (x.tif y.tif z.tif mask.tif meta.json; the original is never touched):

  shift-half  every valid point moved along the local in-plane sheet normal by half the local sheet pitch (the trace sits between sheets)
  shift-full  ... by one full pitch (it sits on the NEIGHBOURING sheet: a classic sheet switch that looks fine locally)
  switch-mid  left half of the grid columns unchanged, right half moved by one pitch (the trace switches sheets in the middle)
  scramble    the z values of the valid cells shuffled among themselves (shape kept, geometry destroyed)

The local pitch is measured on the CT slice at the middle height of the patch (sheet_switch_finder, local-pitch mode, the patch's own
slices/ PNG). If it cannot be measured (non-finite or outside 3..60 voxels) the median over the patches that could be measured is used and
the manifest says so. The sign of the shift is drawn once per patch from the fixed seed and is the same for the three shift kinds.
manifest.csv has one row per patch: pitch, source, signed shift of each kind, number of points moved.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import numpy as np

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _d in ("sheet_spacing_check", "sheet_switch_finder", "label_drift", "common"):
    sys.path.insert(0, os.path.join(_TOOLS, _d))
import label_drift as ld  # noqa: E402
import sheet_switch_finder as ssf  # noqa: E402
from ssc_io import load_mesh  # noqa: E402

KINDS = ("shift-half", "shift-full", "switch-mid", "scramble")
REQUIRED_README_TEXT = "PHerc. Paris 4"
VOXEL_UM = 9.6
PITCH_RANGE = (3.0, 60.0)
DEFAULT_SEED = 20261104


class Refused(SystemExit):
    pass


def check_readme(root):
    rp = os.path.join(root, "README.md")
    if not os.path.isfile(rp):
        raise Refused(f"refusing to run: {root} has no README.md (it must say '{REQUIRED_README_TEXT}')")
    with open(rp, encoding="utf-8", errors="replace") as fh:
        if REQUIRED_README_TEXT not in fh.read():
            raise Refused(f"refusing to run: the README.md in {root} does not say '{REQUIRED_README_TEXT}'")


def list_patches(root):
    """The verified patches: folders under patches/ with mesh.tifxyz/meta.json (raw leftovers have none)."""
    pr = os.path.join(root, "patches")
    return [p for p in sorted(os.listdir(pr)) if os.path.isfile(os.path.join(pr, p, "mesh.tifxyz", "meta.json"))]


def measure_pitch(root, patch, tmp_json):
    """Local sheet pitch (voxels) from the CT slice at the middle height: sheet_switch_finder's per-height `ct_pitch_vox`."""
    pd = os.path.join(root, "patches", patch)
    with open(os.path.join(pd, "mesh.tifxyz", "meta.json")) as fh:
        hs = json.load(fh)["window"]["heights"]
    mid = hs[len(hs) // 2]
    ssf.main([os.path.join(pd, "mesh.tifxyz"), "--png-dir", os.path.join(pd, "slices"), "--png-pixel-um", str(VOXEL_UM),
              "--voxel-size-um", str(VOXEL_UM), "--heights", str(mid), "--out-json", tmp_json])
    with open(tmp_json) as fh:
        h = json.load(fh)["result"]["heights"]
    v = h[0].get("ct_pitch_vox") if h else None
    return (float(v) if v is not None else float("nan")), mid


def inplane_normals(m):
    """Unit in-plane (x, y) part of the surface normal at every node; nodes without a usable one take the nearest usable node's."""
    from scipy.ndimage import distance_transform_edt
    n = ld.surface_normals(m)
    with np.errstate(all="ignore"):
        hn = np.hypot(n[..., 0], n[..., 1])
        ux, uy = n[..., 0] / hn, n[..., 1] / hn
    ok = m.valid & np.isfinite(ux) & np.isfinite(uy) & (hn > 1e-6)
    if not ok.any():
        raise ValueError("no node with a usable in-plane normal")
    idx = distance_transform_edt(~ok, return_distances=False, return_indices=True)
    return ux[tuple(idx)], uy[tuple(idx)]


def write_tifxyz(out, src_dir, x, y, z, valid, note):
    import tifffile
    os.makedirs(out, exist_ok=True)
    for a, g in zip("xyz", (x, y, z)):
        tifffile.imwrite(os.path.join(out, f"{a}.tif"), np.where(valid, g, -1.0).astype(np.float32), compression="zlib")
    tifffile.imwrite(os.path.join(out, "mask.tif"), (valid * 255).astype(np.uint8), compression="zlib")
    with open(os.path.join(src_dir, "meta.json")) as fh:
        meta = json.load(fh)
    meta["negative"] = note
    with open(os.path.join(out, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)


def make_one(src_dir, out_root, shift_vox, rng_seed, kinds=KINDS):
    """Write the requested kinds for one patch; returns {kind: n_points_changed}. shift_vox is the signed full pitch."""
    m = load_mesh(src_dir, -1.0, False)
    if not m.valid.any():
        raise ValueError("patch has no valid points")
    ux, uy = inplane_normals(m)
    W = m.shape[1]
    done = {}
    for kind in kinds:
        x, y, z = m.x.copy(), m.y.copy(), m.z.copy()
        if kind == "scramble":
            zv = z[m.valid].copy()
            np.random.default_rng(rng_seed).shuffle(zv)
            z[m.valid] = zv
            moved = int(m.valid.sum())
        else:
            s = {"shift-half": 0.5 * shift_vox, "shift-full": shift_vox, "switch-mid": shift_vox}[kind]
            sel = m.valid.copy()
            if kind == "switch-mid":
                sel &= (np.arange(W)[None, :] >= W // 2)
            x[sel] += s * ux[sel]
            y[sel] += s * uy[sel]
            moved = int(sel.sum())
        write_tifxyz(os.path.join(out_root, kind), src_dir, x, y, z, m.valid,
                     dict(kind=kind, signed_full_pitch_shift_vox=shift_vox, seed=rng_seed))
        done[kind] = moved
    return done


def run(root, out, seed=DEFAULT_SEED, only=None, kinds=KINDS):
    check_readme(root)
    patches = list_patches(root)         # always the full list: seeds, signs and the fallback pitch do not depend on --patch
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "_pitch_tmp.json")
    meas = {}
    for p in patches:
        try:
            meas[p] = measure_pitch(root, p, tmp)
        except Exception:   # noqa: BLE001  (an unmeasurable patch takes the median below)
            meas[p] = (float("nan"), None)
    if os.path.exists(tmp):
        os.remove(tmp)

    def good(v):
        return bool(np.isfinite(v) and PITCH_RANGE[0] <= v <= PITCH_RANGE[1])

    fallback = float(np.median([v[0] for v in meas.values() if good(v[0])] or [10.0]))
    rng = np.random.default_rng(seed)
    rows = []
    for i, p in enumerate(patches):
        pitch, mid = meas[p]
        ok = good(pitch)
        pitch = float(pitch) if ok else fallback
        sign = 1.0 if rng.random() < 0.5 else -1.0
        full = sign * pitch
        if only and p not in set(only):
            continue
        n = make_one(os.path.join(root, "patches", p, "mesh.tifxyz"), os.path.join(out, p), full, seed + i, kinds)
        rows.append(dict(patch=p, mid_height=mid, pitch_vox=round(pitch, 3), pitch_source="ct-mid-height" if ok else "fallback-median",
                         sign=int(sign), shift_half_vox=round(0.5 * full, 3), shift_full_vox=round(full, 3),
                         shift_switch_mid_vox=round(full, 3), n_points_shifted=n.get("shift-full", ""),
                         n_points_shifted_switch_mid=n.get("switch-mid", ""), n_points_scrambled=n.get("scramble", ""), seed=seed + i))
    with open(os.path.join(out, "manifest.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["patch"])
        w.writeheader()
        w.writerows(rows)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("groundtruth_dir", help="testdata/pherc_paris4_groundtruth (its README.md must say 'PHerc. Paris 4')")
    ap.add_argument("out_dir", help="e.g. results/negatives")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--patch", action="append", help="only this patch folder name (repeatable)")
    ap.add_argument("--kinds", default=",".join(KINDS))
    a = ap.parse_args(argv)
    kinds = tuple(k for k in a.kinds.split(",") if k)
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        ap.error(f"unknown kind(s) {bad}; choose from {KINDS}")
    rows = run(a.groundtruth_dir, a.out_dir, a.seed, a.patch, kinds)
    print(json.dumps(dict(patches=len(rows), kinds=list(kinds), out=a.out_dir, manifest=os.path.join(a.out_dir, "manifest.csv"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
