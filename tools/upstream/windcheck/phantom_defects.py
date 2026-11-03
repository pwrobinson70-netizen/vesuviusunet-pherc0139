"""phantom_defects: plant a CUT and a CROSSING into the folded sheet of a phantom_scroll 'folded' phantom.  (ours, MIT)

Truth for the windcheck benchmark.  The TRUE folded sheet (phantom_scroll v2, turn_NN of a --fold phantom) is an S-shaped pleat whose layers
lie a few voxels apart but never cross (self-proximity, not self-intersection: windcheck's engine must PASS it).  From it we make defective traces:

  cut(P, a, b)         inside the grid columns a..b every row is replaced by the straight line between its end points: the trace short-cuts
                       the pleat and leaves the sheet (off-sheet), without crossing itself.
  cross(P, N, a, b, A) inside a..b the trace is displaced along the surface normal by A * (2s - 1) * sin(pi s), s = (u - a)/(b - a): the pleat's
                       layers get different offsets, so they pass through each other (self-intersection), whatever the CT shows.
  fold_window(P, valid) the grid columns a..b of the pleat (where, in the mid row, the sheet runs backwards about the scroll axis, padded).
All pure numpy on (H, W, 3) XYZ arrays; the amplitude A is in voxels (a flag of score_on_phantoms.py).
"""
import numpy as np


def fold_window(P, valid, pad=6):
    H, W, _ = P.shape
    mid = H // 2
    cx, cy = P[..., 0][valid].mean(), P[..., 1][valid].mean()
    row = P[mid]
    tan = np.gradient(row[:, :2], axis=0)
    rad = row[:, :2] - [cx, cy]
    perp = np.stack([-rad[:, 1], rad[:, 0]], 1)
    back = np.nonzero((tan * perp).sum(1) < 0)[0]
    if back.size == 0:
        return None
    return max(int(back.min()) - pad, 1), min(int(back.max()) + pad, W - 2)


def cut(P, a, b):
    Q = P.copy()
    s = ((np.arange(a, b + 1) - a) / (b - a))[None, :, None]
    Q[:, a:b + 1] = P[:, [a]] * (1 - s) + P[:, [b]] * s
    return Q


def cross(P, N, a, b, A):
    Q = P.copy()
    s = (np.arange(a, b + 1) - a) / (b - a)
    d = A * (2 * s - 1) * np.sin(np.pi * s)
    Q[:, a:b + 1] = P[:, a:b + 1] + np.nan_to_num(N[:, a:b + 1]) * d[None, :, None]       # no normal (grid edge / invalid) -> not displaced
    return Q
