#!/usr/bin/env python3
"""calib: measure where the trace-checking tools are reliable, on phantom_scroll phantoms with known truth (MIT).

Library used by run_grid.py (the full grid -> one CSV), sweep_thresholds.py (one threshold at a time) and
report.py (plots + docs/OPERATING_RANGE.md). Nothing here is real scan data: a phantom tells you whether a tool CAN
fail, not that it works on a scroll.

Cells: seed x grid step x sheet pitch x deformation (round, mild, crushed, merged). The volume does not depend on the
grid step, so it is rendered once per (seed, pitch, deformation, size) and cached on disk as .npz; the tifxyz
surfaces for a grid step are generated in memory (identical to what phantom_scroll writes).

Verdict correctness (the number the operating ranges are built on), per trace or pair:
  sheet_switch_finder  true turn: no switch with confidence >= min_conf.  Planted switch: a switch of the right
                       direction within col_tol columns of the true column at >= 1 height (a switch somewhere else is wrong).
  sheet_spacing_check  true adjacent pair: mean clean fraction >= min_clean.  skipped / shared / off-sheet B: below it.
  umbilicus_finder     per slice: flagged OK and raw centre within centre_tol of the truth, or not OK and further.
  trace_auditor        true trace / pair: PASS.  Bad trace / pair: FAIL.  NOT JUDGED counts as NOT correct (it is an
                       abstention, reported separately in the CSV as verdict = NOT JUDGED).
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):   # one BLAS thread per worker process
    os.environ.setdefault(_v, "1")

import dataclasses  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, ".."))
for _d in ("phantom_scroll", "sheet_spacing_check", "sheet_switch_finder", "umbilicus_finder", "trace_auditor"):
    _p = os.path.join(TOOLS, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phantom_scroll as ps  # noqa: E402
import sheet_spacing_check as ssc  # noqa: E402
import sheet_switch_finder as ssf  # noqa: E402
import trace_auditor as ta  # noqa: E402
import umbilicus_finder as uf  # noqa: E402
import uf_io  # noqa: E402
from ssc_io import ArrayVolume, build_mesh  # noqa: E402

DEFORMS = ("round", "mild", "crushed", "merged")
DEFAULT_SEEDS = tuple(range(20))
DEFAULT_STEPS = (2, 5, 10, 20)
DEFAULT_PITCHES = (8, 15, 30, 60)
HEIGHT_FRACS = (0.25, 0.4, 0.5, 0.6, 0.75)
USABLE_VALID_FRAC = 0.3      # a trace with fewer valid grid cells than this is not used (sheet mostly outside the volume)

COLUMNS = ["seed", "grid_step", "pitch", "deform", "size", "tool", "kind", "case", "expected", "verdict",
           "verdict_correct", "clean_fraction", "recall", "false_switches", "centre_err", "col_err", "valid_frac",
           "runtime_s", "extra"]

PASS, FAIL, NJ = ta.PASS, ta.FAIL, ta.NJ


# ------------------------------------------------------------------------------------------ configuration
@dataclasses.dataclass
class Cfg:
    """Tool parameter overrides (field name -> value) plus the verdict rules of the standalone tools."""
    ssf: dict = dataclasses.field(default_factory=dict)      # sheet_switch_finder.Params fields
    ssc: dict = dataclasses.field(default_factory=dict)      # sheet_spacing_check.Params fields
    uf: dict = dataclasses.field(default_factory=dict)       # umbilicus_finder.Params fields
    ta: dict = dataclasses.field(default_factory=dict)       # trace_auditor.Params fields
    min_conf: float = 0.3          # ssf: a switch counts at or above this confidence (= trace_auditor default)
    min_clean: float = 0.8         # ssc: PASS at or above this mean clean fraction (= trace_auditor default)
    col_tol: float = 12.0          # ssf: a found switch must be within max(2, col_tol / grid_step) + width/2 columns
    centre_tol_pitch: float = 0.25  # umbilicus: a centre is right if within this x pitch (and at least 1.5 voxels)
    auditor_centre: str = "estimated"   # 'estimated' (umbilicus_finder, end to end) or 'truth'
    z_step_uf: float = 8.0

    def with_override(self, group, name, value):
        d = dataclasses.replace(self, **{group: {**getattr(self, group), name: value}})
        return d


# ------------------------------------------------------------------------------------------ phantoms
def geometry(pitch, size):
    """r0, thickness and the sheet used as the base of the pair / switch tests for a given pitch."""
    pitch = float(pitch)
    r0 = float(np.clip(0.5 * pitch, 6.0, 14.0))
    thickness = max(2.0, 0.27 * pitch)                  # same sheet / pitch ratio as phantom_scroll/benchmark.py
    base = 1 if r0 + pitch * 3.0 <= 0.5 * size else 0   # sheets base .. base+2 fit in the slice -> use sheet 1 as A
    return r0, thickness, base


def deform_kwargs(name, size, pitch, r0):
    import benchmark as bm      # phantom_scroll/benchmark.py presets
    key = {"crushed": "bad"}.get(name, name)
    kw = dict(bm.PRESETS[key])
    if "merge_sigma" in kw:
        kw["merge_sigma"] = kw["merge_sigma"] * size
        fits = r0 + pitch * 1.75 <= 0.42 * size
        kw["merge_turn"] = 1.5 if fits else 0.25        # blob between sheets 1/2, or 0/1 when they do not fit
    return kw


def phantom_params(seed, pitch, deform, size, grid_step):
    r0, thick, _ = geometry(pitch, size)
    return ps.Params(shape=(size,) * 3, seed=int(seed), turns=4, r0=r0, pitch=float(pitch), thickness=thick,
                     grid_step=float(grid_step), **deform_kwargs(deform, size, float(pitch), r0))


def cache_path(cache_dir, seed, pitch, deform, size):
    return os.path.join(cache_dir, f"ph_{size}_s{int(seed)}_p{float(pitch):g}_{deform}.npz")


class Phantom:
    """One (seed, pitch, deformation, size): the cached volume and, per grid step, in-memory meshes."""

    def __init__(self, seed, pitch, deform, size=192, cache_dir=None):
        self.seed, self.pitch, self.deform, self.size = int(seed), float(pitch), deform, int(size)
        self.r0, self.thickness, self.base = geometry(pitch, size)
        self.cache_dir = cache_dir
        self.vol = None
        self._scrolls, self._meshes = {}, {}
        self._load()

    def _load(self):
        path = cache_path(self.cache_dir, self.seed, self.pitch, self.deform, self.size) if self.cache_dir else None
        if path and os.path.isfile(path):
            try:
                with np.load(path) as z:
                    self.vol = z["vol"]
                return
            except Exception:       # noqa: BLE001 - a truncated cache file from a killed run: re-render
                pass
        sc = ps.Scroll(phantom_params(self.seed, self.pitch, self.deform, self.size, 4.0))
        self.vol, _ = sc.render()
        if path:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = path + ".tmp.npz"
            np.savez_compressed(tmp, vol=self.vol)
            os.replace(tmp, path)

    @property
    def avol(self):
        return ArrayVolume(self.vol)

    def scroll(self, step):
        if step not in self._scrolls:
            self._scrolls[step] = ps.Scroll(phantom_params(self.seed, self.pitch, self.deform, self.size, step))
        return self._scrolls[step]

    def mesh(self, step, w, name=None):
        key = (step, round(float(w), 4) if np.isscalar(w) else name)
        if key not in self._meshes:
            xyz = self.scroll(step).trace(w)
            self._meshes[key] = build_mesh(name or f"w{w:g}", xyz[..., 0], xyz[..., 1], xyz[..., 2],
                                           {"scale": [1.0 / step, 1.0 / step]})
        return self._meshes[key]

    def heights(self):
        return [float(round(f * (self.size - 1))) for f in HEIGHT_FRACS]

    def switch_specs(self, step):
        nc = self.scroll(step).n_cols()
        b = self.base
        w = max(1, int(round(16.0 / step)))
        return [dict(turn=b, col=int(nc * 0.30), delta=1.0, width=0, row0=0),
                dict(turn=b + 1, col=int(nc * 0.55), delta=-1.0, width=w, row0=0),
                dict(turn=b, col=int(nc * 0.70), delta=1.0, width=0, row0=0)]

    def switch_mesh(self, step, i, spec):
        xyz, truth = ps.switch_trace(self.scroll(step), spec)
        key = (step, f"switch{i}")
        if key not in self._meshes:
            self._meshes[key] = build_mesh(f"switch_{i:02d}", xyz[..., 0], xyz[..., 1], xyz[..., 2],
                                           {"scale": [1.0 / step, 1.0 / step]})
        return self._meshes[key], truth

    def usable(self, mesh):
        return float(mesh.valid.mean()) >= USABLE_VALID_FRAC

    def true_turns(self, step):
        return [(k, self.mesh(step, float(k), f"turn_{k:02d}")) for k in range(4)
                if self.usable(self.mesh(step, float(k), f"turn_{k:02d}"))]

    def bad_pair_meshes(self, step):
        """name -> B mesh for A = turn `base` (skipped / shared / off_sheet), only those with enough data."""
        k = self.base
        out = {}
        for name, w in (("skipped", k + 2.0), ("shared", k + 0.15), ("off_sheet", k + 1.42)):
            m = self.mesh(step, w, f"pair_{name}")
            if self.usable(m):
                out[name] = m
        return out


# ------------------------------------------------------------------------------------------ row helper
def _row(ph, step, tool, kind, case, expected, verdict, correct, t0, **kw):
    r = {c: "" for c in COLUMNS}
    r.update(seed=ph.seed, grid_step=step, pitch=ph.pitch, deform=ph.deform, size=ph.size, tool=tool, kind=kind,
             case=case, expected=expected, verdict=verdict, verdict_correct=int(bool(correct)),
             runtime_s=round(time.time() - t0, 3))
    for k, v in kw.items():
        if k == "extra":
            v = json.dumps(v, default=float, separators=(",", ":"))
        elif isinstance(v, (float, np.floating)):
            v = "" if not np.isfinite(v) else round(float(v), 5)
        r[k] = v
    return r


def _ssf_params(cfg, vertical):
    return ssf.Params(vertical=vertical, **cfg.ssf)


def _ssc_params(cfg, ph):
    kw = dict(band_height_vox=float(ph.heights()[1] - ph.heights()[0]))
    kw.update(cfg.ssc)
    return ssc.Params(**kw)


# ------------------------------------------------------------------------------------------ sheet_switch_finder
def eval_ssf(ph, step, cfg):
    rows, hs, sp, avol = [], ph.heights(), _ssf_params(cfg, 0), ph.avol
    tol0 = max(2.0, cfg.col_tol / step)
    for k, m in ph.true_turns(step):
        t0 = time.time()
        r = ssf.run_finder(m, avol, hs, sp)
        n_all = sum(1 for s in r["switches"] if s["kind"] == "horizontal")
        n = sum(1 for s in r["switches"] if s["kind"] == "horizontal" and s["confidence"] >= cfg.min_conf)
        rows.append(_row(ph, step, "sheet_switch_finder", "true", f"turn_{k:02d}", PASS, FAIL if n else PASS, n == 0, t0,
                         false_switches=n, valid_frac=float(m.valid.mean()), extra={"n_unfiltered": n_all}))
    for i, spec in enumerate(ph.switch_specs(step)):
        t0 = time.time()
        m, tr = ph.switch_mesh(step, i, spec)
        if not ph.usable(m):
            continue
        r = ssf.run_finder(m, avol, hs, sp)
        tol = tol0 + tr["width"] / 2.0
        hit_h, errs, spurious, any_conf = 0, [], 0, 0
        by_h = {}
        for s in r["switches"]:
            if s["kind"] != "horizontal" or s["confidence"] < cfg.min_conf:
                continue
            any_conf += 1
            ok = abs(s["col"] - tr["centre_col"]) <= tol and s["direction"] == tr["direction"]
            by_h.setdefault(s["height"], []).append((ok, abs(s["col"] - tr["centre_col"])))
        for h in hs:
            good = [e for ok, e in by_h.get(h, []) if ok]
            hit_h += bool(good)
            errs += [min(good)] if good else []
            spurious += sum(1 for ok, _ in by_h.get(h, []) if not ok)
        found = hit_h > 0
        rows.append(_row(ph, step, "sheet_switch_finder", "bad", f"switch_{i:02d}", FAIL, FAIL if any_conf else PASS, found, t0,
                         recall=hit_h / len(hs), false_switches=spurious, col_err=float(np.median(errs)) if errs else float("nan"),
                         valid_frac=float(m.valid.mean()), extra={"turn": tr["turn"], "delta": tr["delta"], "col": tr["col"]}))
    return rows


# ------------------------------------------------------------------------------------------ sheet_spacing_check
def _clean(A, B, avol, hs, p):
    r = ssc.run_check(A, B, avol, hs, p)
    hh = [h for h in r["heights"] if h["n_points_a"] and h["n_points_b"]]
    return float(np.mean([h["clean_fraction"] for h in hh])) if hh else float("nan")


def eval_ssc(ph, step, cfg):
    rows, hs, p, avol = [], ph.heights(), None, ph.avol
    p = _ssc_params(cfg, ph)
    turns = dict(ph.true_turns(step))

    def one(case, kind, A, B, expected):
        t0 = time.time()
        try:
            c = _clean(A, B, avol, hs, p)
        except Exception as e:      # noqa: BLE001 - InputError (no data) etc.: not judged
            return _row(ph, step, "sheet_spacing_check", kind, case, expected, NJ, False, t0, extra={"error": str(e)[:80]})
        verdict = NJ if not np.isfinite(c) else (PASS if c >= cfg.min_clean else FAIL)
        return _row(ph, step, "sheet_spacing_check", kind, case, expected, verdict, verdict == expected, t0, clean_fraction=c,
                    valid_frac=float(min(A.valid.mean(), B.valid.mean())))

    for k in range(3):
        if k in turns and k + 1 in turns:
            rows.append(one(f"pair_{k}_{k + 1}", "true", turns[k], turns[k + 1], PASS))
    A = ph.mesh(step, float(ph.base), f"turn_{ph.base:02d}")
    if ph.usable(A):
        for name, B in ph.bad_pair_meshes(step).items():
            rows.append(one(f"pair_{name}", "bad", A, B, FAIL))
    return rows


# ------------------------------------------------------------------------------------------ umbilicus_finder
def eval_uf(ph, cfg):
    t0 = time.time()
    vol = uf_io.ArrayVolume(ph.vol)
    rows, summ = uf.run(vol, uf.Params(**cfg.uf), z_start=8, z_stop=ph.size - 8, z_step=cfg.z_step_uf)
    truth = ph.scroll(4).centre_line()
    tol = max(1.5, cfg.centre_tol_pitch * ph.pitch)
    err_s, err_ok, correct, n_ok = [], [], [], 0
    for r in rows:
        t = truth[int(round(r["z"]))]
        if np.isfinite(r["y"]):
            err_s.append(float(np.hypot(r["y"] - t[1], r["x"] - t[2])))
        e_raw = float(np.hypot(r["raw_y"] - t[1], r["raw_x"] - t[2])) if np.isfinite(r["raw_y"]) else float("inf")
        ok = r["flag"] == "OK"
        n_ok += ok
        correct.append((ok and e_raw <= tol) or (not ok and e_raw > tol))
        if ok:
            err_ok.append(e_raw)
    return [_uf_row(ph, rows, n_ok, correct, err_s, err_ok, tol, summ["pitch_vox"], t0)]


def _uf_row(ph, rows, n_ok, correct, err_s, err_ok, tol, pe, t0):
    r = _row(ph, "", "umbilicus_finder", "true", "volume", "OK", f"{n_ok}/{len(rows)} OK", False, t0,
             recall=n_ok / max(len(rows), 1), centre_err=float(np.mean(err_s)) if err_s else float("nan"),
             extra={"err_ok_mean": float(np.mean(err_ok)) if err_ok else None, "tol": tol,
                    "pitch_est": None if pe is None or not np.isfinite(pe) else float(pe)})
    r["verdict_correct"] = round(float(np.mean(correct)), 5)       # fraction of slices whose OK / LOW flag was right
    return r


# ------------------------------------------------------------------------------------------ trace_auditor
def make_centre(ph, cfg):
    if cfg.auditor_centre == "truth":
        cl = ph.scroll(4).centre_line()
        return ta.Centre(cl[:, 0], cl[:, 1], cl[:, 2], "truth", np.inf), "truth"
    tp = ta.Params(**cfg.ta)
    cen, info = ta.estimate_centre(uf_io.ArrayVolume(ph.vol), 0.0, float(ph.size), tp, uf.Params(**cfg.uf))
    if cen is None:
        return None, f"estimated: only {info['n_ok']} OK"
    return ta.Centre(*cen, "umbilicus_finder", tp.centre_max_gap * tp.centre_z_step), "estimated"


def eval_ta(ph, step, cfg, centre=None):
    rows, hs, avol = [], ph.heights(), ph.avol
    if centre is None:
        centre, _ = make_centre(ph, cfg)
    par, sfp = ta.Params(**cfg.ta), _ssf_params(cfg, 1)
    scp = _ssc_params(cfg, ph)

    def audit(meshes):
        return ta.audit(meshes, avol, hs, centre, par, sfp, scp)

    def emit(case, kind, expected, tr, t0, valid, pair=None):
        fired = sorted(c["check"] for c in tr["checks"] if c["status"] == FAIL)
        extra = {"fired": fired, "centre": cfg.auditor_centre}
        cf = [c.get("clean_fraction") for c in tr["checks"] if c["check"] == "spacing"]
        n_sw = sum(len(c.get("switches", [])) for c in tr["checks"] if c["check"] == "switch_finder")
        rows.append(_row(ph, step, "trace_auditor", kind, case, expected, tr["verdict"], tr["verdict"] == expected, t0,
                         clean_fraction=cf[0] if cf and cf[0] is not None else float("nan"), false_switches=n_sw,
                         valid_frac=valid, extra=extra))

    turns = dict(ph.true_turns(step))
    for k, m in turns.items():
        t0 = time.time()
        emit(f"turn_{k:02d}_alone", "true", PASS, audit([m])["traces"][0], t0, float(m.valid.mean()))
    for k in range(3):
        if k in turns and k + 1 in turns:
            t0 = time.time()
            emit(f"turn_{k + 1:02d}_vs_{k:02d}", "true", PASS, audit([turns[k], turns[k + 1]])["traces"][1], t0,
                 float(min(turns[k].valid.mean(), turns[k + 1].valid.mean())))
    for i, spec in enumerate(ph.switch_specs(step)):
        m, _ = ph.switch_mesh(step, i, spec)
        if ph.usable(m):
            t0 = time.time()
            emit(f"switch_{i:02d}_alone", "bad", FAIL, audit([m])["traces"][0], t0, float(m.valid.mean()))
    A = ph.mesh(step, float(ph.base), f"turn_{ph.base:02d}")
    if ph.usable(A):
        for name, B in ph.bad_pair_meshes(step).items():
            t0 = time.time()
            emit(f"pair_{name}", "bad", FAIL, audit([A, B])["traces"][1], t0, float(min(A.valid.mean(), B.valid.mean())))
    return rows


# ------------------------------------------------------------------------------------------ one phantom, all steps
def evaluate_phantom(seed, pitch, deform, steps, size=192, cache_dir=None, cfg=None, tools=("ssf", "ssc", "uf", "ta")):
    cfg = cfg or Cfg()
    ph = Phantom(seed, pitch, deform, size, cache_dir)
    rows = []
    if "uf" in tools:
        rows += eval_uf(ph, cfg)
    centre = make_centre(ph, cfg)[0] if "ta" in tools else None
    for st in steps:
        if "ssf" in tools:
            rows += eval_ssf(ph, st, cfg)
        if "ssc" in tools:
            rows += eval_ssc(ph, st, cfg)
        if "ta" in tools:
            rows += eval_ta(ph, st, cfg, centre)
    return rows
