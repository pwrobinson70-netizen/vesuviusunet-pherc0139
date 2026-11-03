#!/usr/bin/env python3
"""Score patch_merger on phantom_scroll phantoms (round, mild, bad, merged; the benchmark presets).

    python tools/patch_merger/score_on_phantoms.py --size 192 --json score.json

Patches come from winding_sweep (tools/winding_sweep, found in $WINDING_SWEEP_DIR or ../winding_sweep): the sweep is run
at several ray angles (--angles), each angle gives one patch per sheet crossing, so patches of the same sheet from
different angles overlap and patches of neighbouring sheets lie one pitch apart. If winding_sweep is not available the
script falls back to sheet_tracer patches seeded at those angles on every true turn (same overlap structure).
All patches of a phantom are given to patch_merger together (volume, estimated centre line, measured pitch).

Truth. The phantom's "turns" are windings of ONE continuous spiral sheet: turn k ends (angle 2 pi) where turn k+1 starts
(angle 0), so a correct merge across that seam is one long strip and a per-turn label would call it impure. Every point is
therefore given the spiral parameter t = k + column/n_cols of its nearest true-surface grid point (continuous across the
seam); the point is ON SHEET if that point is nearer than --tol x pitch. A surface is COHERENT where neighbouring grid
nodes differ by at most --jump turns of t (a jump of about 1 turn is a hop to the next winding); the on-turn fraction
reported is the share of a surface's nodes in its largest coherent piece (100% = no hop to a neighbouring winding anywhere),
and its t-span is the length of spiral it covers. Reported for the inputs and for the merged components: patches /
components, overlaps accepted and refused (with reasons), pooled on-turn fraction, number of surfaces below 99%, area.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, ".."))
WS = os.environ.get("WINDING_SWEEP_DIR", os.path.join(TOOLS, "winding_sweep"))
for d in (HERE, os.path.join(TOOLS, "phantom_scroll"), os.path.join(TOOLS, "sheet_tracer"), WS):
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)

import benchmark as bm  # noqa: E402
import patch_merger as pm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import trace_auditor as ta  # noqa: E402
import uf_io  # noqa: E402
from ssc_io import ArrayVolume  # noqa: E402

try:
    import winding_sweep as ws  # noqa: E402
except ImportError:
    ws = None


class Truth:
    def __init__(self, turns, pitch, tol, jump):
        nr, nc = turns[0].shape[:2]
        self.tree = cKDTree(np.concatenate([t.reshape(-1, 3) for t in turns]))
        self.t = np.concatenate([k + (np.arange(nr * nc) % nc) / nc for k in range(len(turns))])
        self.pitch, self.tol, self.jump = pitch, tol, jump

    def stats(self, P, valid):
        """-> dict(on_sheet, on_turn, t_span, n) for a (H, W, 3) grid."""
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        H, W = valid.shape
        d, i = self.tree.query(P[valid])
        t = np.full(valid.shape, np.nan)
        on = np.zeros(valid.shape, bool)
        t[valid], on[valid] = self.t[i], d < self.tol * self.pitch
        idx = np.arange(H * W).reshape(H, W)
        ok = valid & on
        e = []
        for sl_a, sl_b in (((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
                           ((slice(None, -1), slice(None)), (slice(1, None), slice(None)))):
            m = ok[sl_a] & ok[sl_b] & (np.abs(t[sl_a] - t[sl_b]) <= self.jump)
            e.append((idx[sl_a][m], idx[sl_b][m]))
        r, c = np.concatenate([x[0] for x in e]), np.concatenate([x[1] for x in e])
        n = int(valid.sum())
        if n == 0:
            return dict(on_sheet=0.0, on_turn=0.0, t_span=0.0, n=0)
        g = coo_matrix((np.ones(len(r)), (r, c)), shape=(H * W, H * W))
        _, lab = connected_components(g, directed=False)
        lab_v = lab[idx[ok]]
        best = np.bincount(lab_v).argmax() if lab_v.size else -1
        main = ok & (lab.reshape(H, W) == best)
        span = float(t[main].max() - t[main].min()) if main.any() else 0.0
        return dict(on_sheet=float(ok.sum() / n), on_turn=float(main.sum() / n), t_span=span, n=n)


def sweep_patches(name, p, sc, vol, work, angles, workers, log):
    """-> (list of patch dirs, notes)."""
    dirs, notes = [], []
    nz = vol.shape[0]
    src = ws.Source(vol.astype(np.float32), f"phantom {name}")
    cl = sc.centre_line()
    truth_json = os.path.join(work, "centre_truth.json")
    with open(truth_json, "w") as f:
        json.dump({"control_points": [{"z": float(a), "y": float(b), "x": float(c)} for a, b, c in cl]}, f)
    for ang in angles:
        sd = os.path.join(work, f"sweep_a{int(ang):03d}")
        r = None
        for um, tag in ((None, "estimated"), (truth_json, "truth")):
            try:
                r = ws.sweep(src, nz // 4, nz - nz // 4, sd, ws.Params(angle=float(ang), n_angles=1, workers=workers), umbilicus=um)
                break
            except (ws.InputError, ws.NoCrossings) as e:
                notes.append(f"angle {ang:g}, {tag} centre: {e}")
        if r is None:
            continue
        if tag != "estimated":
            notes.append(f"angle {ang:g}: swept with the true centre line (estimated centre failed)")
        for m in r["manifest"]:
            if m["patch"]:
                dirs.append(os.path.join(sd, m["patch"]))
        log(f"  {name}: angle {ang:g}: {sum(1 for m in r['manifest'] if m['patch'])} patches")
    return dirs, notes


def tracer_patches(name, p, sc, vol, work, angles, log):
    import sheet_tracer as st
    dirs = []
    nr, nc = sc.n_rows(), sc.n_cols()
    tp = st.Params(step_vox=p.grid_step, max_rows=int(nr / 2), max_cols=int(0.6 * nc))
    for k in range(p.turns):
        S = sc.turn_surface(k)
        for ang in angles:
            col = int(((ang % 360) / 360.0) * nc) % nc
            seed = S[nr // 2, col]
            try:
                res = st.trace(vol.astype(np.float32), seed, tp)
            except st.SeedError:
                continue
            out = os.path.join(work, f"tracer_t{k}_a{int(ang):03d}")
            st.write_outputs(out, res, tp, seed)
            dirs.append(out)
    log(f"  {name}: {len(dirs)} tracer patches")
    return dirs, ["winding_sweep not found: sheet_tracer patches seeded on every true turn"]


def score_one(name, size, seed, angles, workers, tol, jump, log=print):
    t0 = time.time()
    p = bm.make_params(name, size, seed)
    sc = ps.Scroll(p)
    vol, _ = sc.render()
    turns = [sc.turn_surface(k) for k in range(p.turns)]
    truth = Truth(turns, p.pitch, tol, jump)
    with tempfile.TemporaryDirectory() as work:
        if ws is not None:
            dirs, notes = sweep_patches(name, p, sc, vol, work, angles, workers, log)
            source = "winding_sweep"
        else:
            dirs, notes = tracer_patches(name, p, sc, vol, work, angles, log)
            source = "sheet_tracer"
        if not dirs:
            return dict(phantom=name, source=source, error="no patches", notes=notes)
        patches = pm.load_patches(dirs)
        cl = sc.centre_line()
        cen, info = ta.estimate_centre(uf_io.ArrayVolume(vol), 0.0, float(vol.shape[0]), ta.Params(), ta.uf.Params())
        if cen is None:
            centre, ctag = ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf), "truth (estimated failed)"
        else:
            centre, ctag = ta.Centre(*cen, "umbilicus_finder", 1.5 * 32.0), "estimated"
        in_rows = []
        for pa in patches:
            st_ = truth.stats(pa.P, pa.valid)
            in_rows.append(dict(patch=pa.name, area=pm.area_vx2(np.where(pa.valid[..., None], pa.P, -1.0)), **st_))
        rep = pm.merge(patches, ArrayVolume(vol), centre, pm.Params())
        comps = []
        for c in rep["components_data"]:
            st_ = truth.stats(c["P"], c["valid"])
            comps.append(dict(name=c["name"], area=c["area_vx2"], n_patches=len(c["patches"]), n_segments=len(c["segments"]), **st_))
    s = rep["summary"]
    pooled = lambda rows, k="on_turn": float(sum(r[k] * r["n"] for r in rows) / max(1, sum(r["n"] for r in rows)))  # noqa: E731
    return dict(phantom=name, source=source, centre=ctag, size=size, true_turns=p.turns, n_patches=len(patches),
                n_components=s["n_components"], seams_accepted=s["seams_accepted"], seams_refused=s["seams_refused"],
                refused_by_reason=s["refused_by_reason"], segments_dropped=s["segments_dropped"],
                cuts=sum(len(x["cuts"]) for x in rep["patches"]),
                on_turn_inputs=pooled(in_rows), on_turn_merged=pooled(comps), on_sheet_merged=pooled(comps, "on_sheet"),
                t_span_merged=[round(c["t_span"], 2) for c in comps],
                impure_inputs=sum(r["on_turn"] < 0.99 for r in in_rows), impure_merged=sum(c["on_turn"] < 0.99 for c in comps),
                area_inputs=float(sum(r["area"] for r in in_rows)), area_merged=float(sum(c["area"] for c in comps)),
                pitch=p.pitch, wall=time.time() - t0, notes=notes,
                components=comps, inputs=in_rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=192)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--angles", type=float, nargs="+", default=[30.0, 120.0, 210.0, 300.0], help="ray angles (degrees) of the sweeps")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--tol", type=float, default=0.25, help="on-sheet distance tolerance, x pitch")
    ap.add_argument("--jump", type=float, default=0.15, help="neighbouring nodes differing by more than this many turns of t are a hop")
    ap.add_argument("--phantoms", nargs="+", default=list(bm.PRESETS), choices=list(bm.PRESETS))
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    res = [score_one(n, a.size, a.seed, a.angles, a.workers, a.tol, a.jump, log=lambda m: print(m, file=sys.stderr)) for n in a.phantoms]
    print(f"\npatch_merger on phantoms, size {a.size}, seed {a.seed}, patches from {res[0].get('source')} at angles "
          f"{', '.join(f'{x:g}' for x in a.angles)}, on-sheet tolerance {a.tol:g} pitch, hop {a.jump:g} turn\n")
    print("| phantom | patches in | components | overlaps accepted / refused | refusal reasons | segments dropped | on-turn: inputs | on-turn: merged | below 99% in / out | spiral turns covered by components | area in -> merged (vox^2) | wall (s) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in res:
        if "error" in r:
            print(f"| {r['phantom']} | ERROR: {r['error']} |")
            continue
        why = ", ".join(f"{k} {v}" for k, v in r["refused_by_reason"].items()) or "-"
        print(f"| {r['phantom']} | {r['n_patches']} | {r['n_components']} | {r['seams_accepted']} / {r['seams_refused']} | {why} | "
              f"{r['segments_dropped']} | {100 * r['on_turn_inputs']:.1f}% | {100 * r['on_turn_merged']:.1f}% | "
              f"{r['impure_inputs']} / {r['impure_merged']} | {', '.join(f'{x:.2f}' for x in r['t_span_merged'])} | {r['area_inputs']:.0f} -> {r['area_merged']:.0f} | {r['wall']:.0f} |")
    for r in res:
        for n in r.get("notes", []):
            print(f"\nnote ({r['phantom']}): {n}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f, indent=2, default=float)
    return 0


if __name__ == "__main__":
    sys.exit(main())
