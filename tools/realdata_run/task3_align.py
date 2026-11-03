import sys; sys.path.insert(0, __import__("os").path.dirname(__file__))
from common import *
import numpy as np, ssc_io, sheet_spacing_check as S
from scipy.spatial import cKDTree
A=ssc_io.load_mesh(A_DIR); B=ssc_io.load_mesh(B_DIR); p=S.Params()
for z in HEIGHTS:
    la,lb=S.cut_line(A,z,p),S.cut_line(B,z,p)
    d,i=cKDTree(lb.xy).query(la.xy,k=1)
    dc=lb.col[i]-la.col
    print(z,"nearest-B dist: med %.1f p10 %.1f p90 %.1f | col offset (B nearest - A col): med %d, p10 %d p90 %d, frac|off|>5: %.2f"%(np.median(d),*np.percentile(d,[10,90]),np.median(dc),*np.percentile(dc,[10,90]),(abs(dc)>5).mean()))
    # same-column distance
    common=np.intersect1d(la.col,lb.col); ia=[np.where(la.col==c)[0][0] for c in common]; ib=[np.where(lb.col==c)[0][0] for c in common]
    ds=np.hypot(*(la.xy[ia]-lb.xy[ib]).T); print("   same-col dist med %.1f p90 %.1f"%(np.median(ds),np.percentile(ds,90)))
    # radial position along spiral about rough centre
    c0=np.array([1180.,1100.]); ra=np.hypot(*(la.xy-c0).T); print("   A radius first/last col: %.0f %.0f"%(ra[0],ra[-1]))
