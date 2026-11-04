#!/usr/bin/env python3
"""Before/after benchmark of geometric_repair on tifxyz meshes (ours).  Writes a markdown table.

    python benchmark_infill.py MESH.tifxyz [MESH2.tifxyz ...] [--depths 1 2 3] [--out BENCHMARK.md]

For each mesh: invalid vertices before/after infill, and the hold-out error (hide the outermost `depth` rings of the valid
region, infill, compare with the real coordinates) for geometric_repair vs the naive baseline 'copy the nearest valid vertex'.
Same flags as geometric_repair for the fit parameters.
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import geometric_repair as g  # noqa: E402
from tifxyz_repair.core import load_patch  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("meshes", nargs="+")
    ap.add_argument("--depths", type=int, nargs="+", default=[1, 2, 3], help="hold-out depths in grid rings (default %(default)s)")
    ap.add_argument("--out")
    d = g.Params()
    ap.add_argument("--max-rings", type=int, default=d.max_rings)
    ap.add_argument("--fit-radius", type=int, default=d.fit_radius)
    ap.add_argument("--min-neighbours", type=int, default=d.min_neighbours)
    ap.add_argument("--max-residual-frac", type=float, default=d.max_residual_frac)
    a = ap.parse_args(argv)
    p = g.Params(a.max_rings, a.fit_radius, a.min_neighbours, a.max_residual_frac)
    L = ["| mesh | grid | invalid before | invalid after | infilled |", "|---|---|---|---|---|"]
    H = ["| mesh | hidden ring depth | hidden | filled | ours RMS / median / max (vox) | nearest-copy RMS / median / max (vox) |", "|---|---|---|---|---|---|"]
    for m in a.meshes:
        name = os.path.basename(m.rstrip("/"))
        pa = load_patch(m)
        _, _, _, _, rep = g.repair(pa, p)
        L.append(f"| {name} | {rep['shape_hw'][0]}x{rep['shape_hw'][1]} | {rep['invalid_before']} ({100 * rep['invalid_fraction_before']:.1f}%) | "
                 f"{rep['invalid_after']} ({100 * rep['invalid_fraction_after']:.1f}%) | {rep['infilled']} |")
        P, v = pa.points(), g.valid_vertices(pa)
        for dep in a.depths:
            h = g.holdout(P, v, dep, p)
            o, n = h["ours"], h["nearest_copy"]
            H.append(f"| {name} | {dep} | {h['hidden']} | {h['filled']} ({100 * h['fill_rate']:.0f}%) | "
                     f"{o['rms']:.1f} / {o['median']:.1f} / {o['max']:.1f} | {n['rms']:.1f} / {n['median']:.1f} / {n['max']:.1f} |")
    text = "\n".join(["## Invalid vertices", ""] + L + ["", "## Hold-out error", ""] + H) + "\n"
    print(text)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
