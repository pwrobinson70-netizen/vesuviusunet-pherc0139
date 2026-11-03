"""Independent sheet-pitch measurement: radial intensity profiles about a rough centre, mean autocorrelation (read-only)."""
import sys, numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter1d
from scipy.signal import find_peaks
D = "testdata/pherc_paris4_45um/slices/%05d.png"
cx, cy = float(sys.argv[1]), float(sys.argv[2])   # rough centre in px (x, y)
for z in (2073, 2600, 3128):
    im = np.asarray(Image.open(D % z), dtype=float)
    out = {}
    for rmin, rmax in ((40, 200), (150, 350), (300, 500)):
        acs = []
        for ang in np.linspace(0, 2*np.pi, 360, endpoint=False):
            r = np.arange(rmin, rmax, 0.5)
            p = map_coordinates(im, [cy + r*np.sin(ang), cx + r*np.cos(ang)], order=1)
            p = gaussian_filter1d(p, 1.0); p = p - gaussian_filter1d(p, 12)
            if p.std() < 1: continue
            ac = np.correlate(p, p, "full")[len(p)-1:]; ac /= ac[0]; acs.append(ac[:60])
        m = np.mean(acs, 0)
        pk, _ = find_peaks(m, prominence=0.02)
        out[(rmin, rmax)] = [(round(k*0.5, 1), round(m[k], 3)) for k in pk[:3]]
    print(z, out)
