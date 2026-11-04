#!/usr/bin/env python3
"""surface_agreement: does a tifxyz trace lie on the sheet that a machine-made surface prediction marks?  (MIT)

    python surface_agreement.py TRACE [TRACE ...] --pred-png-dir DIR | --pred-zarr VOL.zarr
        [--ct-png-dir DIR | --ct-zarr VOL.zarr] [--png-pixel-um UM --voxel-size-um UM] [--heights z1,z2,..] --out-dir DIR

For every trace and every height the trace is cut by the plane z = height (the cut line the other tools use). At each cut-line
point the prediction (0..255, higher = more papyrus-like) is sampled along the in-plane normal, from -k to +k voxels, and the tool reports

  * the prediction value at the trace point,
  * the offset (voxels, + = along the normal) to the nearest prediction RIDGE: a local maximum of the smoothed profile,
    so the middle of a predicted band, also when the prediction is a binary mask;
  * a verdict: ON-PREDICTED-SHEET (value at the trace >= --on-value-min and a ridge within --on-tol-vox), OFF, or
    NOT JUDGED (no prediction data: slice missing, point outside the image, no usable normal).

Then, when a CT volume on the same grid is given, the same points get our peak-based verdict (offset to the nearest CT sheet
peak, the measure of tools/label_drift; ON if within --ct-on-tol-vox) and a 2 x 2 table per height (ours vs the prediction) lists
the points on which the two disagree. --audit adds the trace_auditor verdict (and the spacing check for two traces) as context.
Output: report.json, report.txt, points_<trace>.csv, png/ overlays. Every threshold is a flag (README.md). Exit code 0, 2 bad input.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates
from scipy.signal import find_peaks

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _d in ("sheet_spacing_check", "common", "label_drift", "trace_auditor", "sheet_switch_finder", "umbilicus_finder", "crush_map"):
    _p = os.path.join(_TOOLS, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
import local_pitch as lpm  # noqa: E402
import sheet_spacing_check as ssc  # noqa: E402
import label_drift as ld  # noqa: E402
from ssc_io import ArrayVolume, InputError, PngVolume, ZarrVolume, load_mesh, to_px  # noqa: E402

__version__ = "0.1.0"
ON, OFF, NJ = "ON-PREDICTED-SHEET", "OFF", "NOT JUDGED"
OURS_ON, OURS_OFF = "ON-CT-PEAK", "OFF"


@dataclass
class Params:
    # --- sampling along the normal
    half_len_vox: float = 30.0          # k: profile from -k to +k voxels along the in-plane normal (the ridge search range)
    step_px: float = 0.5                # profile sample step (pixels of the prediction image)
    sigma_px: float = 1.5               # Gaussian smoothing of the profile before ridges are looked for (pixels); a binary band needs > 0
    # --- prediction verdict
    ridge_prominence: float = 64.0      # a ridge: local maximum of the smoothed profile at least this far (0..255 units) above its surroundings
    on_value_min: float = 128.0         # ON needs the prediction value at the trace point (0..255) at least this
    on_tol_vox: float = 3.0             # ... and the nearest ridge within this many voxels (keep it well under half the sheet pitch: at half a pitch every point is "near" a sheet)
    pred_max: float = 255.0             # the value that means "certainly papyrus"; values are rescaled so that this becomes 255
    # --- our (CT peak) verdict, same measure as tools/label_drift
    ct_on_tol_vox: float = 2.0          # ON if the nearest CT sheet peak along the normal is within this many voxels (same caveat: well under half the pitch)
    ct_prominence_frac: float = 0.10    # CT sheet peak: min prominence / robust profile range (label_drift default)
    # --- per-height verdict of the prediction check
    pass_on_fraction: float = 0.8       # a height PASSes if at least this fraction of its judged points is ON
    min_judged_points: int = 10         # fewer judged points at a height = NOT JUDGED
    # --- heights
    n_heights: int = 5                  # when --heights is not given: this many, evenly spaced over the z range of the traces ...
    height_margin: float = 0.10         # ... after trimming this fraction of the range at each end
    # --- overlays
    png_scale: int = 3                  # overlay magnification (integer)
    png_margin_px: int = 20             # overlay crop: this many pixels around the trace points
    max_listed: int = 200               # disagreeing points listed per height in report.json (all of them are in the CSV)

    def validate(self):
        for k in ("half_len_vox", "step_px", "ridge_prominence", "on_tol_vox", "ct_on_tol_vox", "pred_max"):
            if not getattr(self, k) > 0:
                raise InputError(f"--{k.replace('_', '-')} must be > 0")
        if self.sigma_px < 0 or self.png_scale < 1 or self.min_judged_points < 1 or self.n_heights < 1 or self.png_margin_px < 0:
            raise InputError("--sigma-px >= 0, --png-scale >= 1, --min-judged-points >= 1, --n-heights >= 1, --png-margin-px >= 0 needed")
        for k in ("on_value_min", "pass_on_fraction", "height_margin", "ct_prominence_frac"):
            if not 0 <= getattr(self, k) <= 255 or (k != "on_value_min" and getattr(self, k) > 1):
                raise InputError(f"--{k.replace('_', '-')} out of range")
        return self


# ------------------------------------------------------------------ sampling
def _tile(vol, line, z, half_px, pad=3):
    """Image tile around the cut line (+ the profile reach); returns (tile, origin(x0, y0), (H, W)). InputError if the slice is missing."""
    H, W = vol.probe_shape(z)
    pts = to_px(line.xy, vol.ct_scale)
    reach = int(math.ceil(half_px)) + pad
    x0 = max(0, int(math.floor(pts[:, 0].min())) - reach)
    y0 = max(0, int(math.floor(pts[:, 1].min())) - reach)
    x1 = min(W, int(math.ceil(pts[:, 0].max())) + reach + 1)
    y1 = min(H, int(math.ceil(pts[:, 1].max())) + reach + 1)
    if x1 <= x0 or y1 <= y0:
        raise InputError(f"the trace at z={z:g} lies outside the {W}x{H} image")
    return vol.tile(z, x0, y0, x1, y1), (x0, y0), (H, W)


def profiles(tile, origin, xy_px, nrm, p: Params, ct_scale):
    """Raw and smoothed profiles along the normals. Returns (s_vox (m,), raw (n, m), smooth (n, m)); the middle column is s = 0.
    Rows with an undefined normal are NaN."""
    nh = int(round(p.half_len_vox / ct_scale / p.step_px))
    s_px = np.arange(-nh, nh + 1) * p.step_px
    pts = np.asarray(xy_px, float) - np.asarray(origin, float)
    ok = np.isfinite(nrm[:, 0])
    xs = pts[:, 0:1] + np.where(ok, nrm[:, 0], 0.0)[:, None] * s_px[None, :]
    ys = pts[:, 1:2] + np.where(ok, nrm[:, 1], 0.0)[:, None] * s_px[None, :]
    raw = map_coordinates(np.asarray(tile, float), [ys.ravel(), xs.ravel()], order=1, mode="nearest").reshape(len(pts), -1)
    sm = gaussian_filter1d(raw, p.sigma_px / p.step_px, axis=1, mode="nearest") if p.sigma_px > 0 else raw.copy()
    raw[~ok], sm[~ok] = np.nan, np.nan
    return s_px * ct_scale, raw, sm


def nearest_ridge(s_vox, sm, prominence):
    """Offset (voxels) of the ridge of the smoothed profile nearest to s = 0 and its height; (nan, nan) if there is none."""
    if not np.all(np.isfinite(sm)):
        return float("nan"), float("nan")
    pk, _ = find_peaks(sm, prominence=prominence)
    if len(pk) == 0:
        return float("nan"), float("nan")
    j = pk[int(np.argmin(np.abs(s_vox[pk])))]
    off = float(s_vox[j])
    if 0 < j < len(sm) - 1:                                  # sub-sample position by a 3-point parabola
        a, b, c = sm[j - 1], sm[j], sm[j + 1]
        den = a - 2 * b + c
        if den < 0:
            off += float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) * float(s_vox[1] - s_vox[0])
    return off, float(sm[j])


def judge_prediction(raw, sm, s_vox, inside, p: Params):
    """Per point: (value at the trace, offset to the nearest ridge, verdict)."""
    n = len(raw)
    mid = raw.shape[1] // 2
    val = raw[:, mid].copy() if n else np.zeros(0)
    off = np.full(n, np.nan)
    verdict = np.full(n, NJ, dtype=object)
    for i in range(n):
        if not (inside[i] and np.isfinite(val[i])):
            continue
        off[i], _ = nearest_ridge(s_vox, sm[i], p.ridge_prominence)
        verdict[i] = ON if (val[i] >= p.on_value_min and np.isfinite(off[i]) and abs(off[i]) <= p.on_tol_vox) else OFF
    return val, off, verdict


def judge_ct(tile, origin, xy_px, nrm, p: Params, sp, ct_scale, inside):
    """Per point: (signed offset to the nearest CT sheet peak, verdict) with label_drift's measure."""
    n = len(xy_px)
    off = np.full(n, np.nan)
    verdict = np.full(n, NJ, dtype=object)
    if n == 0:
        return off, verdict
    ldp = ld.Params(peak_prominence_frac=p.ct_prominence_frac)
    s_vox, prof = lpm.sample_profiles(tile, origin, xy_px, nrm, ct_scale, ssc.pitch_params(sp))
    drift = ld.measure_profiles(s_vox, prof, ldp, ct_scale)[0]
    off[:] = drift
    for i in range(n):
        if inside[i] and np.isfinite(drift[i]):
            verdict[i] = OURS_ON if abs(drift[i]) <= p.ct_on_tol_vox else OURS_OFF
    return off, verdict


# ------------------------------------------------------------------ one trace, one height
def analyse_height(mesh, pred, ct, h, p: Params):
    """Returns (record, rows). rows: list of dict per cut-line point; record: counts and the 2x2 table."""
    sp = ssc.Params()
    line = ssc.cut_line(mesh, float(h), sp)
    rec = dict(z=float(h), n_points=int(line.n), note="")
    if line.n == 0:
        rec["note"] = "height outside the z range of the trace"
        return _fill_record(rec, [], p), []
    nrm = ssc.normals(line, sp)
    rows = [dict(trace=mesh.name, z=float(h), col=int(line.col[i]), run=int(line.run[i]), x=float(line.xy[i, 0]), y=float(line.xy[i, 1]),
                 pred_value=float("nan"), pred_offset_vox=float("nan"), pred_verdict=NJ,
                 ct_offset_vox=float("nan"), ct_verdict=NJ, agreement="") for i in range(line.n)]
    try:
        tile, origin, (H, W) = _tile(pred, line, float(h), p.half_len_vox / pred.ct_scale)
    except InputError as e:
        rec["note"] = f"no prediction data: {e}"
        return _fill_record(rec, rows, p, ct_given=ct is not None), rows
    xy_px = to_px(line.xy, pred.ct_scale)
    inside = (xy_px[:, 0] >= 0) & (xy_px[:, 0] <= W - 1) & (xy_px[:, 1] >= 0) & (xy_px[:, 1] <= H - 1)
    s_vox, raw, sm = profiles(tile * (255.0 / p.pred_max), origin, xy_px, nrm, p, pred.ct_scale)
    val, off, ver = judge_prediction(raw, sm, s_vox, inside, p)
    for r, a, b, c in zip(rows, val, off, ver):
        r["pred_value"], r["pred_offset_vox"], r["pred_verdict"] = float(a), float(b), str(c)
    if ct is not None:
        try:
            ctile, corigin, (cH, cW) = _tile(ct, line, float(h), ssc.Params().profile_halflen_vox / ct.ct_scale)
            cxy = to_px(line.xy, ct.ct_scale)
            cin = (cxy[:, 0] >= 0) & (cxy[:, 0] <= cW - 1) & (cxy[:, 1] >= 0) & (cxy[:, 1] <= cH - 1)
            coff, cver = judge_ct(ctile, corigin, cxy, nrm, p, sp, ct.ct_scale, cin)
            for r, a, b in zip(rows, coff, cver):
                r["ct_offset_vox"], r["ct_verdict"] = float(a), str(b)
        except InputError as e:
            rec["note"] = (rec["note"] + "; " if rec["note"] else "") + f"no CT data: {e}"
    return _fill_record(rec, rows, p, ct_given=ct is not None), rows


def _fill_record(rec, rows, p: Params, ct_given=False):
    pv = [r["pred_verdict"] for r in rows]
    n_on, n_off, n_nj = pv.count(ON), pv.count(OFF), pv.count(NJ)
    rec.update(pred_on=n_on, pred_off=n_off, pred_not_judged=n_nj,
               pred_on_fraction=(n_on / (n_on + n_off)) if n_on + n_off else None,
               pred_judged_fraction=((n_on + n_off) / len(rows)) if rows else 0.0)
    if n_on + n_off < p.min_judged_points:
        rec["pred_verdict"] = NJ
    else:
        rec["pred_verdict"] = "PASS" if rec["pred_on_fraction"] >= p.pass_on_fraction else "FAIL"
    if ct_given:
        t = {(a, b): 0 for a in (OURS_ON, OURS_OFF) for b in (ON, OFF)}
        dis = []
        for r in rows:
            if r["ct_verdict"] == NJ or r["pred_verdict"] == NJ:
                r["agreement"] = "not compared"
                continue
            t[(r["ct_verdict"], r["pred_verdict"])] += 1
            if (r["ct_verdict"] == OURS_ON) == (r["pred_verdict"] == ON):
                r["agreement"] = "agree"
            else:
                r["agreement"] = "ours ON / prediction OFF" if r["ct_verdict"] == OURS_ON else "ours OFF / prediction ON"
                dis.append(r)
        n = sum(t.values())
        rec["table_2x2"] = dict(ours_on_pred_on=t[(OURS_ON, ON)], ours_on_pred_off=t[(OURS_ON, OFF)],
                                ours_off_pred_on=t[(OURS_OFF, ON)], ours_off_pred_off=t[(OURS_OFF, OFF)])
        rec["n_compared"] = n
        rec["agreement_fraction"] = ((t[(OURS_ON, ON)] + t[(OURS_OFF, OFF)]) / n) if n else None
        rec["ours_on_fraction"] = ((t[(OURS_ON, ON)] + t[(OURS_ON, OFF)]) / n) if n else None
        rec["n_disagree"] = len(dis)
        rec["disagreements"] = [dict(col=r["col"], x=r["x"], y=r["y"], kind=r["agreement"], pred_value=r["pred_value"],
                                     pred_offset_vox=r["pred_offset_vox"], ct_offset_vox=r["ct_offset_vox"]) for r in dis[:p.max_listed]]
    return rec


def sum_tables(recs):
    keys = ("ours_on_pred_on", "ours_on_pred_off", "ours_off_pred_on", "ours_off_pred_off")
    return {k: sum(r["table_2x2"][k] for r in recs if "table_2x2" in r) for k in keys}


# ------------------------------------------------------------------ whole run
def auto_heights(meshes, p: Params):
    lo, hi = -math.inf, math.inf
    for m in meshes:
        z = m.z[m.valid]
        if not z.size:
            raise InputError(f"trace {m.name} has no valid points")
        lo, hi = max(lo, float(z.min())), min(hi, float(z.max()))
    if hi <= lo:
        raise InputError("the traces share no z range; pass --heights")
    a, b = lo + p.height_margin * (hi - lo), hi - p.height_margin * (hi - lo)
    return [float(round(v)) for v in (np.linspace(a, b, p.n_heights) if p.n_heights > 1 else [(a + b) / 2])]


def run(meshes, pred, ct, heights, p: Params):
    """Returns (report dict, rows per trace)."""
    p.validate()
    traces, allrows = [], {}
    for m in meshes:
        recs, rows = [], []
        for h in heights:
            rec, rr = analyse_height(m, pred, ct, h, p)
            recs.append(rec)
            rows += rr
        n_on = sum(r["pred_on"] for r in recs)
        n_off = sum(r["pred_off"] for r in recs)
        tr = dict(name=m.name, heights=recs, pred_on=n_on, pred_off=n_off, pred_not_judged=sum(r["pred_not_judged"] for r in recs),
                  pred_on_fraction=(n_on / (n_on + n_off)) if n_on + n_off else None)
        if ct is not None:
            tr["table_2x2"] = sum_tables(recs)
            t = tr["table_2x2"]
            n = sum(t.values())
            tr["n_compared"] = n
            tr["agreement_fraction"] = ((t["ours_on_pred_on"] + t["ours_off_pred_off"]) / n) if n else None
        traces.append(tr)
        allrows[m.name] = rows
    return dict(tool_version=__version__, params=asdict(p), heights=[float(h) for h in heights], traces=traces), allrows


# ------------------------------------------------------------------ the existing auditor, for context
def run_audit(trace_paths, args, heights, out_tmp):
    """Run tools/trace_auditor on the same traces / CT / heights; returns a short per-trace summary (or the reason it could not run)."""
    import trace_auditor as ta
    argv = list(trace_paths) + ["--heights", ",".join(f"{h:g}" for h in heights), "--out-dir", out_tmp]
    argv += ["--png-dir", args.ct_png_dir] if args.ct_png_dir else ["--zarr", args.ct_zarr]
    if args.png_pixel_um:
        argv += ["--png-pixel-um", str(args.png_pixel_um)]
    if args.voxel_size_um:
        argv += ["--voxel-size-um", str(args.voxel_size_um)]
    if args.umbilicus:
        argv += ["--umbilicus", args.umbilicus]
    import contextlib
    import io
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        try:
            rc = ta.main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
    f = os.path.join(out_tmp, "audit.json")
    if rc == 2 or not os.path.isfile(f):
        return dict(ran=False, reason=(err.getvalue().strip().splitlines() or ["auditor failed"])[-1])
    with open(f, encoding="utf-8") as fh:
        rep = json.load(fh)
    res = rep["result"]
    return dict(ran=True, tool_version=rep["tool_version"], centre=rep["inputs"]["centre"],
                traces=[dict(name=t["name"], verdict=t["verdict"], reasons=t["reasons"],
                             checks=[dict(check=c["check"], status=c["status"], reason=c["reason"]) for c in t["checks"]]) for t in res["traces"]],
                spacing=(None if not res.get("pair") else dict(status=res["pair"]["spacing"]["status"], reason=res["pair"]["spacing"]["reason"])))


# ------------------------------------------------------------------ outputs
def text_report(rep):
    L = [f"surface_agreement {rep['tool_version']}   heights {', '.join(f'{h:g}' for h in rep['heights'])}"]
    for t in rep["traces"]:
        f = t["pred_on_fraction"]
        L += ["", f"{t['name']}: prediction ON at {'-' if f is None else format(100 * f, '.0f') + '%'} of judged points "
                  f"({t['pred_on']} ON, {t['pred_off']} OFF, {t['pred_not_judged']} NOT JUDGED)"]
        for r in t["heights"]:
            ff = r["pred_on_fraction"]
            L.append(f"  z={r['z']:g}: {r['pred_verdict']}; {r['n_points']} points, ON {'-' if ff is None else format(100 * ff, '.0f') + '%'}"
                     + (f"  [{r['note']}]" if r["note"] else ""))
            if "table_2x2" in r:
                T = r["table_2x2"]
                L += ["      2x2 (rows: ours = CT peak, columns: prediction)       pred ON   pred OFF",
                      f"                                    ours ON      {T['ours_on_pred_on']:7d}   {T['ours_on_pred_off']:8d}",
                      f"                                    ours OFF     {T['ours_off_pred_on']:7d}   {T['ours_off_pred_off']:8d}",
                      f"      compared {r['n_compared']}, agree "
                      f"{'-' if r['agreement_fraction'] is None else format(100 * r['agreement_fraction'], '.0f') + '%'}, {r['n_disagree']} disagree"]
        if "table_2x2" in t:
            T = t["table_2x2"]
            L.append(f"  all heights: ours ON/pred ON {T['ours_on_pred_on']}, ours ON/pred OFF {T['ours_on_pred_off']}, "
                     f"ours OFF/pred ON {T['ours_off_pred_on']}, ours OFF/pred OFF {T['ours_off_pred_off']}")
    a = rep.get("audit")
    if a:
        L.append("")
        if a["ran"]:
            L.append(f"trace_auditor {a['tool_version']} (centre: {a['centre']}):")
            L += [f"  {t['name']}: {t['verdict']}  " + "; ".join(t["reasons"])[:300] for t in a["traces"]]
            if a["spacing"]:
                L.append(f"  spacing: {a['spacing']['status']}  {a['spacing']['reason']}")
        else:
            L.append(f"trace_auditor did not run: {a['reason']}")
    return "\n".join(L) + "\n"


CSV_COLS = ["trace", "z", "col", "run", "x", "y", "pred_value", "pred_offset_vox", "pred_verdict", "ct_offset_vox", "ct_verdict", "agreement"]


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{r[k]:.3f}" if isinstance(r[k], float) else r[k]) for k in CSV_COLS})


COL = {ON: (40, 220, 60), OFF: (235, 40, 40), NJ: (240, 200, 0)}
DIS = {"ours ON / prediction OFF": (255, 0, 255), "ours OFF / prediction ON": (0, 220, 255)}


def _dot(img, x, y, col, r):
    H, W = img.shape[:2]
    x0, x1, y0, y1 = max(0, x - r), min(W, x + r + 1), max(0, y - r), min(H, y + r + 1)
    if x1 > x0 and y1 > y0:
        img[y0:y1, x0:x1] = col


def _crop_base(vol, z, rows, p: Params):
    tile, origin, _ = _tile(vol, type("L", (), dict(xy=np.array([[r["x"], r["y"]] for r in rows])))(), float(z), p.png_margin_px)
    t = np.asarray(tile, float)
    hi = np.percentile(t, 99.5) if t.size else 1.0
    g = np.clip(t / (hi if hi > 0 else 1.0), 0, 1) * 255
    return np.stack([g] * 3, -1).astype(np.uint8), origin


def write_overlays(out_dir, name, rows, pred, ct, heights, p: Params):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for h in heights:
        rr = [r for r in rows if r["z"] == float(h)]
        if not rr:
            continue
        for kind, vol in (("pred", pred), ("ct", ct)):
            if vol is None:
                continue
            try:
                base, (x0, y0) = _crop_base(vol, h, rr, p)
            except InputError:
                continue
            S = p.png_scale
            img = np.kron(base, np.ones((S, S, 1), np.uint8)) if S > 1 else base.copy()
            for r in rr:
                px, py = to_px(np.array([[r["x"], r["y"]]]), vol.ct_scale)[0]
                cx, cy = int(round((px - x0) * S)), int(round((py - y0) * S))
                if kind == "pred":
                    col = COL[r["pred_verdict"]]
                else:
                    col = DIS.get(r["agreement"], (255, 255, 255) if r["agreement"] == "agree" else (120, 120, 120))
                _dot(img, cx, cy, col, max(1, S // 2))
            f = os.path.join(out_dir, f"{name}_z{h:g}_{'on_prediction' if kind == 'pred' else 'disagreement_on_ct'}.png")
            Image.fromarray(img).save(f)
            made.append(f)
    return made


# ------------------------------------------------------------------ CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("traces", nargs="+", help="tifxyz folder(s)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pred-png-dir", help="surface prediction as a PNG stack (one 8-bit PNG per slice)")
    g.add_argument("--pred-zarr", help="surface prediction as a zarr volume [z, y, x]")
    ap.add_argument("--pred-zarr-level", type=int, default=0)
    ap.add_argument("--ct-png-dir", help="CT PNG stack on the same grid (enables the 2x2 comparison with our peak-based verdict)")
    ap.add_argument("--ct-zarr")
    ap.add_argument("--ct-zarr-level", type=int, default=0)
    ap.add_argument("--png-pixel-um", type=float, help="PNG pixel size (um); with --voxel-size-um gives the pixels per mesh voxel")
    ap.add_argument("--voxel-size-um", type=float, help="mesh voxel size (um) (PNG input)")
    ap.add_argument("--png-pattern", default="{z:05d}.png")
    ap.add_argument("--heights", help="comma-separated z heights (voxels); default --n-heights over the common z range")
    ap.add_argument("--transpose", action="store_true", help="grids have z varying along columns")
    ap.add_argument("--audit", action="store_true", help="also run tools/trace_auditor on the traces (needs the CT; --umbilicus or its own estimate)")
    ap.add_argument("--umbilicus", help="centre line file for --audit")
    ap.add_argument("--out-dir", required=True)
    for f in dataclasses.fields(Params):
        v = getattr(Params(), f.name)
        ap.add_argument("--" + f.name.replace("_", "-"), dest=f.name, type=type(v), default=v)
    return ap


def _volume(png_dir, zarr, level, a, vox):
    if png_dir:
        return PngVolume(png_dir, a.png_pixel_um, vox, a.png_pattern)
    return ZarrVolume(zarr, level)


def main(argv=None):
    a = build_parser().parse_args(argv)
    p = Params(**{f.name: getattr(a, f.name) for f in dataclasses.fields(Params)})
    try:
        p.validate()
        if a.ct_png_dir and a.ct_zarr:
            raise InputError("give --ct-png-dir or --ct-zarr, not both")
        meshes = [load_mesh(t, ssc.Params().invalid_value, a.transpose) for t in a.traces]
        vox = a.voxel_size_um or next((m.voxel_um for m in meshes if m.voxel_um), None)
        pred = _volume(a.pred_png_dir, a.pred_zarr, a.pred_zarr_level, a, vox)
        ct = _volume(a.ct_png_dir, a.ct_zarr, a.ct_zarr_level, a, vox) if (a.ct_png_dir or a.ct_zarr) else None
        if a.audit and ct is None:
            raise InputError("--audit needs a CT volume (--ct-png-dir or --ct-zarr)")
        try:
            heights = [float(h) for h in a.heights.split(",") if h.strip()] if a.heights else auto_heights(meshes, p)
        except ValueError as e:
            raise InputError(f"--heights must be comma-separated numbers: {e}") from e
        rep, rows = run(meshes, pred, ct, heights, p)
        rep["inputs"] = dict(traces=list(a.traces), prediction=a.pred_png_dir or a.pred_zarr, ct=a.ct_png_dir or a.ct_zarr)
        if a.audit:
            with tempfile.TemporaryDirectory() as tmp:
                rep["audit"] = run_audit(a.traces, a, heights, tmp)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "report.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rep, fh, indent=2, default=float)
    txt = text_report(rep)
    with open(os.path.join(a.out_dir, "report.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt)
    for m in meshes:
        write_csv(os.path.join(a.out_dir, f"points_{m.name}.csv"), rows[m.name])
        write_overlays(os.path.join(a.out_dir, "png"), m.name, rows[m.name], pred, ct, heights, p)
    print(txt, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
