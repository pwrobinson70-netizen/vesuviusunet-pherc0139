"""Independent pitch measurement along mesh normals (read-only): per-point autocorrelation lag of the first peak
(search 3..14 vox) and peak-gap median with low prominence, plus the tool's own ct_pitches under alternative flags."""
import json, sys
from common import *
import numpy as np, ssc_io, sheet_spacing_check as S
from scipy.ndimage import map_coordinates, gaussian_filter1d
from scipy.signal import find_peaks
from PIL import Image
A = ssc_io.load_mesh(A_DIR); B = ssc_io.load_mesh(B_DIR); p = S.Params()
res = {}
for z in HEIGHTS:
    im = np.asarray(Image.open(f"{SLICES}/{z:05d}.png"), float)
    out = {}
    for nm, M in (("A", A), ("B", B)):
        l = S.cut_line(M, z, p); n = S.normals(l, p)
        s = np.arange(-40, 40.01, 0.5); lags_ac = []; gaps = []
        for i in range(l.n):
            if not np.isfinite(n[i, 0]): continue
            pr = map_coordinates(im, [l.xy[i, 1] + n[i, 1]*s, l.xy[i, 0] + n[i, 0]*s], order=1)
            pr = gaussian_filter1d(pr, 1.0) ; pr = pr - gaussian_filter1d(pr, 16)
            if pr.std() < 1: continue
            ac = np.correlate(pr, pr, "full")[len(pr)-1:]; ac /= ac[0]
            lo, hi = 6, 28  # 3..14 vox
            pk, _ = find_peaks(ac[:hi+1]);  pk = [k for k in pk if k >= lo]
            if pk: lags_ac.append(pk[0]*0.5)
            pk2, _ = find_peaks(pr, prominence=0.15*(pr.max()-pr.min()), distance=3); gaps += list(np.diff(pk2)*0.5)
        out[nm] = dict(n=int(l.n), ac_first_peak_med=float(np.median(lags_ac)), ac_p25_p75=np.percentile(lags_ac, [25, 75]).tolist(),
                       peakgap_med=float(np.median(gaps)), peakgap_p25_p75=np.percentile(gaps, [25, 75]).tolist())
    # tool's own estimator under alternative parameters (sensitivity only; defaults untouched)
    la = S.cut_line(A, z, p); tile = im
    for lab, kw in (("default", {}), ("prom0.10", dict(peak_prominence_frac=0.10)), ("prom0.05", dict(peak_prominence_frac=0.05)),
                    ("prom0.10_mind2", dict(peak_prominence_frac=0.10, peak_min_distance_px=2.0)),
                    ("halflen30", dict(profile_halflen_vox=30.0)), ("halflen30_prom0.10", dict(profile_halflen_vox=30.0, peak_prominence_frac=0.10))):
        q = S.Params(**kw); v = S.ct_pitches(tile, (0, 0), la, 1.0, q)
        out["tool_" + lab] = dict(median=float(np.nanmedian(v)), frac_defined=float(np.isfinite(v).mean()))
    res[z] = out
    print(z, json.dumps(out, indent=None))
json.dump(res, open(REPO + "/tools/realdata_run/out/pitch_measurement.json", "w"), indent=1)
