"""fake_prediction: a stand-in for a learned surface prediction, made from a (phantom) CT: the blurred sheet mask.  (MIT)

``blurred_sheet_mask(ct)``: pixels brighter than the midpoint of the CT's robust range are 'papyrus' (1), everything else 0;
the mask is blurred in-plane with a Gaussian and scaled to 0..255 (float32; ``as_uint8=True`` rounds). A new helper, the
phantom generators are untouched. Test support and demos only: a real prediction comes from the organisers' model.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


def blurred_sheet_mask(ct, frac=0.5, blur_sigma=1.0, as_uint8=False):
    ct = np.asarray(ct, dtype=np.float32)
    lo, hi = np.percentile(ct, 1.0), np.percentile(ct, 99.0)
    mask = (ct > lo + frac * (hi - lo)).astype(np.float32)
    if blur_sigma > 0:
        mask = gaussian_filter(mask, sigma=(0, blur_sigma, blur_sigma))
    out = 255.0 * mask
    return np.rint(out).astype(np.uint8) if as_uint8 else out.astype(np.float32)
