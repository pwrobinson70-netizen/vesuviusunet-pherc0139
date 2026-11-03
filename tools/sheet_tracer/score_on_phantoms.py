#!/usr/bin/env python3
"""Part C score: sheet_tracer -> trace_auditor -> trace_repair (where FAIL) -> trace_auditor on the four phantoms (MIT).

    python tools/sheet_tracer/score_on_phantoms.py --size 256 --out score_out --json score.json

Per phantom (round, mild, bad = badly crushed, merged = sheets touching; benchmark presets) and 3 seeds (turn 1 mid, turn 2 mid,
turn 2 at 30% height / 35% angle; all away from the angle seam): grow a patch, audit it alone, repair it if the verdict is
FAIL (growth radiates from the seed cell: --origin-cell), audit again. Reports per patch: points, area (voxel^2), the
fraction of points on the seed's turn (continuous winding coordinate within 0.35 of the seed's turn, seam-safe) before and after
repair, and the verdict before / after. --centre truth uses the exact centre line (default; the estimated one costs time and can
be NOT JUDGED), --centre estimated uses umbilicus_finder.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, ".."))
for d in (HERE, os.path.join(TOOLS, "phantom_scroll"), os.path.join(TOOLS, "trace_auditor"), os.path.join(TOOLS, "trace_repair"),
          os.path.join(TOOLS, "sheet_spacing_check")):
    if d not in sys.path:
        sys.path.insert(0, d)

import benchmark as bm  # noqa: E402
import phantom_scroll as ps  # noqa: E402
import sheet_tracer as st  # noqa: E402
import trace_auditor as ta  # noqa: E402
import trace_repair as tr  # noqa: E402
import uf_io  # noqa: E402
from ssc_io import ArrayVolume, load_mesh  # noqa: E402

SEEDS = [dict(name="t1-mid", turn=1, row=0.5, col=0.5), dict(name="t2-mid", turn=2, row=0.5, col=0.5),
         dict(name="t2-low", turn=2, row=0.3, col=0.35)]


def turn_fraction(sc, mesh, k, seed_xyz):
    """Fraction of valid points of `mesh` on turn k: continuous winding coordinate (seam-safe, anchored at the seed)."""
    pts = np.stack([mesh.x, mesh.y, mesh.z], -1)[mesh.valid]
    if not len(pts):
        return 0.0
    def wphi(P):
        q = sc.inverse(np.asarray(P, float).reshape(-1, 3).T[::-1])
        rel = np.stack([q[2], q[1]]) - sc.axis(q[0])
        w, phi, _ = sc.winding(rel)
        return w, phi
    _, phi_s = wphi(seed_xyz)
    w, phi = wphi(pts)
    delta = np.angle(np.exp(1j * (phi - phi_s[0])))
    m = np.round((phi_s[0] + delta - phi) / (2 * np.pi))
    return float(np.mean(np.abs((w - m) - k) < 0.35))


def make_centre(mode, sc, vol, p):
    if mode == "truth":
        cl = sc.centre_line()
        return ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf)
    cen, info = ta.estimate_centre(uf_io.ArrayVolume(vol), 0.0, float(vol.shape[0]), ta.Params(), ta.uf.Params())
    return ta.Centre(*cen, "umbilicus_finder", 1.5 * 32.0) if cen is not None else None


def audit(mesh, avol, centre):
    z = mesh.z[mesh.valid]
    lo, hi = float(z.min()), float(z.max())
    H = [float(round(lo + f * (hi - lo))) for f in (0.15, 0.3, 0.5, 0.7, 0.85)]
    rep = ta.audit([mesh], avol, H, centre, ta.Params(), ta.ssf.Params(vertical=1), ta.ssc.Params(band_height_vox=H[1] - H[0]))
    rep.pop("polar")
    t = rep["traces"][0]
    return rep, t["verdict"], [c["check"] for c in t["checks"] if c["status"] == ta.FAIL]


def run_phantom(name, size, seed, mode, work, log):
    p = bm.make_params(name, size, seed)
    sc = ps.Scroll(p)
    vol, lab = sc.render()
    np.save(os.path.join(work, f"{name}_vol.npy"), vol)
    avol, centre = ArrayVolume(vol), make_centre(mode, sc, vol, p)
    T = st.Tracer(vol, st.Params())
    rows = []
    for sd in SEEDS:
        tru = sc.turn_surface(sd["turn"])
        seed_xyz = tru[int(sd["row"] * (tru.shape[0] - 1)), int(sd["col"] * (tru.shape[1] - 1))]
        prm = st.Params(step_vox=p.grid_step, max_rows=61, max_cols=41)
        d = os.path.join(work, f"{name}_{sd['name']}")
        rec = dict(phantom=name, seed=sd["name"], turn=sd["turn"], seed_xyz=seed_xyz.tolist())
        try:
            res = st.trace(vol, seed_xyz, prm, tracer=T)
        except st.SeedError as e:
            rec.update(error=f"seed rejected: {e}")
            rows.append(rec)
            continue
        summ = st.write_outputs(d, res, prm, seed_xyz)
        m = load_mesh(d)
        rec.update(points=int(m.valid.sum()), area_vx2=json.load(open(os.path.join(d, "meta.json")))["area_vx2"],
                   stop=res["stop_reason"], on_turn_before=turn_fraction(sc, m, sd["turn"], seed_xyz))
        rep, rec["verdict_before"], rec["fails_before"] = audit(m, avol, centre)
        rec.update(on_turn_after=rec["on_turn_before"], verdict_after=rec["verdict_before"], repaired=False)
        if rec["verdict_before"] == ta.FAIL:
            aj = os.path.join(work, f"{name}_{sd['name']}_audit.json")
            json.dump(dict(result=rep), open(aj, "w"), default=float)
            out = d + "_fixed"
            sr, sc_ = res["seed_cell"][0] - summ["crop_offset_rc"][0], res["seed_cell"][1] - summ["crop_offset_rc"][1]
            rc = tr.main([d, "--audit", aj, "--npy", os.path.join(work, f"{name}_vol.npy"), "--out", out, "--origin-cell", str(sr), str(sc_)])
            if rc == 0 and os.path.isdir(out):
                m2 = load_mesh(out)
                rec["repaired"] = json.load(open(os.path.join(out, "repair_summary.json")))["repaired"]
                rec["on_turn_after"] = turn_fraction(sc, m2, sd["turn"], seed_xyz)
                _, rec["verdict_after"], rec["fails_after"] = audit(m2, avol, centre)
            else:
                rec["repair_error"] = f"trace_repair exit {rc}"
        log(f"{name} {sd['name']}: {rec['points']} pts, on-turn {rec['on_turn_before']:.3f} -> {rec['on_turn_after']:.3f}, "
            f"{rec['verdict_before']} -> {rec['verdict_after']}")
        rows.append(rec)
    return rows


def table(rows):
    h = ("| phantom | seed | points | area (vx^2) | on correct turn before | after repair | verdict before | verdict after | failing checks before |\n"
         "|---|---|---|---|---|---|---|---|---|")
    out = [h]
    for r in rows:
        if "error" in r:
            out.append(f"| {r['phantom']} | {r['seed']} | - | - | - | - | - | - | {r['error']} |")
            continue
        out.append(f"| {r['phantom']} | {r['seed']} | {r['points']} | {r['area_vx2']:.0f} | {100 * r['on_turn_before']:.1f}% | "
                   f"{100 * r['on_turn_after']:.1f}%{'' if r['repaired'] else ' (not repaired)'} | {r['verdict_before']} | {r['verdict_after']} | "
                   f"{', '.join(r.get('fails_before', []))} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0, help="phantom seed")
    ap.add_argument("--phantoms", default="round,mild,bad,merged")
    ap.add_argument("--centre", choices=["truth", "estimated"], default="truth")
    ap.add_argument("--out")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    work = a.out or tempfile.mkdtemp(prefix="tracer_score_")
    os.makedirs(work, exist_ok=True)
    rows = []
    for n in a.phantoms.split(","):
        rows += run_phantom(n, a.size, a.seed, a.centre, work, lambda m: print(m, file=sys.stderr, flush=True))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=2, default=float)
    print(table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
