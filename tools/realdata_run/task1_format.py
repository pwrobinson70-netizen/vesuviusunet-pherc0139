"""Task 1: load the real tifxyz meshes and report format facts (read-only)."""
import glob, json, os, sys
import numpy as np, tifffile
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "sheet_spacing_check"))
import ssc_io
D = os.path.join(REPO, "testdata", "pherc_paris4_45um")
for p in sorted(glob.glob(D + "/*.tifxyz")):
    print("==", os.path.basename(p))
    print("files:", sorted(os.listdir(p)))
    raw = {a: tifffile.imread(f"{p}/{a}.tif") for a in "xyz"}
    for a, r in raw.items():
        with tifffile.TiffFile(f"{p}/{a}.tif") as t:
            pg = t.pages[0]
            print(f"  {a}.tif raw: shape={r.shape} dtype={r.dtype} tiled={pg.is_tiled} compression={pg.compression.name} "
                  f"nonfinite={int((~np.isfinite(r)).sum())} ==-1:{int((r==-1).sum())} min/max(finite,!=-1)="
                  f"{r[np.isfinite(r)&(r!=-1)].min():.2f}/{r[np.isfinite(r)&(r!=-1)].max():.2f}")
    sent = [(raw[a] == -1) for a in "xyz"]
    anyS = sent[0] | sent[1] | sent[2]; allS = sent[0] & sent[1] & sent[2]
    print(f"  sentinel cells: any={int(anyS.sum())} all-three={int(allS.sum())} partial={int((anyS&~allS).sum())}")
    print("  z<=0 (store rule M2):", int((raw['z'] <= 0).sum()))
    m = ssc_io.load_mesh(p)
    meta = json.load(open(p + "/meta.json"))
    print(f"  ssc_io: shape={m.shape} dtype={m.x.dtype} n_invalid={m.n_invalid} of {m.valid.size} ({100*m.n_invalid/m.valid.size:.2f}%) "
          f"scale={m.scale} voxel_um={m.voxel_um} mask.tif={'yes' if os.path.exists(p+'/mask.tif') else 'no'}")
    v = m.valid
    bb = np.array([[np.nanmin(m.x), np.nanmin(m.y), np.nanmin(m.z)], [np.nanmax(m.x), np.nanmax(m.y), np.nanmax(m.z)]])
    mb = np.array(meta["bbox"])
    print("  computed bbox (xyz):", bb.round(2).tolist())
    print("  meta bbox:          ", mb.round(2).tolist(), " max|diff|=", float(np.abs(bb - mb).max()))
    # alt axis orders
    for nm, perm in (("zyx-reversed", [2, 1, 0]),):
        print(f"  meta bbox if reversed to zyx order: max|diff|=", float(np.abs(bb - mb[:, perm]).max()))
    print("  meta keys:", sorted(meta), "uuid:", meta.get("uuid"))
    H, W = m.shape
    sx, sy = m.scale
    print(f"  nominal size (cols/sx, rows/sy) = {W/sx:.1f} x {H/sy:.1f} voxels")
    # measured grid spacing
    dc = np.hypot.reduce([np.diff(a, axis=1) for a in (m.x, m.y, m.z)]); dr = np.hypot.reduce([np.diff(a, axis=0) for a in (m.x, m.y, m.z)])
    print(f"  measured step along cols (u): median={np.nanmedian(dc):.2f} vox (1/scale={1/sx:.2f}); along rows (v): median={np.nanmedian(dr):.2f} (1/scale={1/sy:.2f})")
    # which axis does z vary along?
    print(f"  mean |dz| along rows={np.nanmean(np.abs(np.diff(m.z,axis=0))):.2f}, along cols={np.nanmean(np.abs(np.diff(m.z,axis=1))):.2f}")
    print(f"  valid-cell z range {np.nanmin(m.z):.1f}..{np.nanmax(m.z):.1f}; per-column valid counts min/med/max:",
          v.sum(0).min(), int(np.median(v.sum(0))), v.sum(0).max())
    # area check
    print("  meta area_vx2:", meta.get("area_vx2"))
    # sentinel location summary
    if anyS.any():
        rr, cc = np.where(anyS); print(f"  invalid rows {rr.min()}-{rr.max()}, cols {cc.min()}-{cc.max()}")
