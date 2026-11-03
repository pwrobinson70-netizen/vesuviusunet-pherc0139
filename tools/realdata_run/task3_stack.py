import sys; sys.path.insert(0, __import__("os").path.dirname(__file__))
from common import *
import numpy as np, ssc_io, sheet_spacing_check as S
from scipy.spatial import cKDTree
A=ssc_io.load_mesh(A_DIR); B=ssc_io.load_mesh(B_DIR); p=S.Params()
for z in HEIGHTS:
    la,lb=S.cut_line(A,z,p),S.cut_line(B,z,p)
    c0=np.array([1180.,1100.])
    # curves: split at middle column
    def split(l,mid): return l.xy[l.col<mid], l.xy[l.col>=mid]
    ma=(la.col.min()+la.col.max())//2; mb=(lb.col.min()+lb.col.max())//2
    A1,A2=split(la,ma); B1,B2=split(lb,mb)
    print(z,"turn radii about (1180,1100): A1 %.0f..%.0f A2 %.0f..%.0f B1 %.0f..%.0f B2 %.0f..%.0f"%tuple(np.r_[[ (np.hypot(*(c-c0).T).min(),np.hypot(*(c-c0).T).max()) for c in (A1,A2,B1,B2)]].ravel()))
    nrm=S.normals(la,p)
    for nm,pts_ref,idx in (("A1",A1,np.where(la.col<ma)[0]),("A2",A2,np.where(la.col>=ma)[0])):
        row=[]
        for on,oc in (("A1",A1),("A2",A2),("B1",B1),("B2",B2)):
            if on==nm: continue
            # signed offset along normal to nearest point of the other curve (nearest in 2D)
            t=cKDTree(oc); d,i=t.query(la.xy[idx],k=1); v=oc[i]-la.xy[idx]; sg=np.sum(v*nrm[idx],axis=1); ok=np.isfinite(sg)
            row.append("%s: dist med %.1f, signed med %+.1f"%(on,np.median(d[ok]),np.median(sg[ok])))
        print("  from",nm,"|"," | ".join(row))
