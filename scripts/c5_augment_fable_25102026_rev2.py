#!/usr/bin/env python3
"""
c5_augment_fable_25102026_rev2.py  (rev2, [fable], 25 Oct 2026; rev1b + PATCH/WIN per instance from the dataset patch size (plan C6 M2 / C7 F5): C5Augment(L, S, p, patch=64), c5_from_env(enabled, patch=None) reads C5_PATCH or the caller value; win = ceil(patch x 1.18); selftest at 64 and 192) -- plan C5 rev2 item C5-3 + M2: scan-shift augmentation for training,
as a standalone module imported by dataset.py (three-line patch, see C5_DATASET_PATCH below). Train split only; never at inference.

Units: patches arrive as float32 in /65535 units (dataset.py line 167: volume / 65535.0), i.e. uint8 value / 255 after the
x257 encoding. The rev5 folders have in-mask median L and IQR S (uint8 units); the amplitudes below are expressed in units of
S (Sonnet 248 m1), with L and S passed in from the environment (C5_L, C5_S, the same numbers given to segprep --L --S).

Per patch, each op with probability P (default 0.8), drawn from the dataset's own numpy Generator (reseeded per worker, M2):
  contrast  g in [0.6, 1.5]      y = L + (x - L) * g            (contrast about the segment level, not a plain multiply)
  offset    d in [-0.5 S, +0.5 S] y = x + d
  gamma     k in [0.7, 1.4]      y = clip(x,0,1) ** k
  blur      sigma in [0, 1.2] px, x and y only (per layer), scipy gaussian_filter
  noise     sigma in [0, 0.3 S], additive Gaussian
  scale     f in [0.85, 1.18], x and y only: the caller hands a WIN x WIN window (WIN = ceil(64 x 1.18) = 76, plan m1); the
            volume is zoomed bilinear, the label nearest, both centre-cropped to 64. If the caller hands a 64 x 64 patch
            (unpatched sampler), scale is skipped and a counter says so - the rest still applies.
Order: scale first (geometry), then contrast, offset, gamma, blur, noise. Output clipped to [0, 1]. Label stays {0, 1}.

C5_DATASET_PATCH (against dataset.py sha256 43a643cf5b3948aa, CR-stripped; line numbers from Sonnet 246):
  (1) imports:                 from c5_augment_fable_24102026 import C5Augment, worker_seed, c5_from_env
  (2) end of __init__:         self.c5 = c5_from_env(self.split == "train" and augment)      # None unless C5_AUG=1
  (3) top of __getitem__:      if not getattr(self, "_c5_reseeded", False):
                                   self.rng = np.random.default_rng(worker_seed(self.seed)); self._c5_reseeded = True
      after the rot90 line:    if self.c5 is not None: vol_patch, label_patch = self.c5(vol_patch, label_patch, self.rng)
  Window size: if the sampler can be told to cut 76 x 76, do so when self.c5 is not None (self.c5.win); otherwise scale is
  skipped (counted) and C5 runs with the five intensity ops only - say which in the run record.
  train.py is NOT changed; the switch is the environment (C5_AUG=1 C5_L=<L> C5_S=<S> [C5_P=0.8]); dataset.py logs the
  settings once at init and the c5_train script writes them into the run record next to the banner (Sonnet 248 m4).
"""
import math, os, sys
import numpy as np

PATCH = 64                                 # module defaults (rev1b behaviour); rev2: each C5Augment carries its own patch/win
WIN = int(math.ceil(PATCH * 1.18))     # 76


def win_for(patch):
    """Window the dataset must cut so that a 0.85..1.18 zoom still yields a full patch after the centre crop: ceil(patch x 1.18)."""
    return int(math.ceil(int(patch) * 1.18))


def worker_seed(base_seed):
    """Per-worker seed (M2): base_seed in the main process; (base_seed, worker id) hashed in a DataLoader worker."""
    try:
        import torch
        wi = torch.utils.data.get_worker_info()
    except Exception:   # noqa: BLE001 - torch absent in the selftest container is fine
        wi = None
    if wi is None:
        return int(base_seed)
    return int((int(base_seed) * 1000003 + 7919 * (wi.id + 1)) % (2 ** 32))


def c5_from_env(enabled, patch=None):
    """rev2: patch = the dataset's patch_size (caller) or env C5_PATCH, default 64. A mismatch between the two is an error, not a guess."""
    if not enabled or os.environ.get("C5_AUG", "0") != "1":
        return None
    L = float(os.environ["C5_L"]); S = float(os.environ["C5_S"])
    p = float(os.environ.get("C5_P", "0.8"))
    env_patch = os.environ.get("C5_PATCH")
    if patch is not None and env_patch is not None and int(env_patch) != int(patch):
        raise ValueError("C5_PATCH=%s disagrees with the dataset patch_size %d" % (env_patch, int(patch)))
    patch = int(patch) if patch is not None else (int(env_patch) if env_patch is not None else PATCH)
    aug = C5Augment(L, S, p, patch=patch)
    print("[c5_augment] ENABLED: L %.1f S %.1f (uint8 units) p %.2f patch %d win %d; ops %s" % (L, S, p, aug.patch, aug.win, ",".join(aug.ops)), flush=True)
    return aug


class C5Augment:
    ops = ("scale", "contrast", "offset", "gamma", "blur", "noise")

    def __init__(self, L8, S8, p=0.8, contrast=(0.6, 1.5), offset_S=0.5, gamma=(0.7, 1.4), blur=(0.0, 1.2), noise_S=0.3, scale=(0.85, 1.18), patch=PATCH):
        self.L = L8 / 255.0; self.S = S8 / 255.0; self.p = p
        self.contrast, self.offset_S, self.gamma, self.blur, self.noise_S, self.scale = contrast, offset_S, gamma, blur, noise_S, scale
        self.patch = int(patch); self.win = win_for(self.patch)
        self.counts = {k: 0 for k in self.ops}; self.counts["scale_skipped"] = 0; self.n = 0
        self.last = {}

    def __call__(self, vol, lab, rng):
        """vol: float32 (D, h, w) in [0, 1]; lab: (h, w) {0,1} or {0,255}; h, w = PATCH (no scale) or >= WIN (scale)."""
        from scipy.ndimage import zoom, gaussian_filter
        self.n += 1; draws = {}
        v = np.asarray(vol, dtype=np.float32); l = np.asarray(lab)
        lab_max = 255 if l.max() > 1 else 1
        if v.shape[1] >= self.win and v.shape[2] >= self.win:
            if rng.random() < self.p:
                f = float(rng.uniform(*self.scale)); draws["scale"] = f; self.counts["scale"] += 1
                v = zoom(v, (1.0, f, f), order=1, mode="nearest", prefilter=False, grid_mode=False)
                l = zoom(l, (f, f), order=0, mode="nearest", grid_mode=False)
            v, l = _centre_crop(v, l, self.patch)
        elif v.shape[1] == self.patch and v.shape[2] == self.patch:
            self.counts["scale_skipped"] += 1
        else:
            raise ValueError("patch %s is neither %d nor >= %d wide" % (v.shape, self.patch, self.win))
        if rng.random() < self.p:
            g = float(rng.uniform(*self.contrast)); draws["contrast"] = g; self.counts["contrast"] += 1
            v = self.L + (v - self.L) * g
        if rng.random() < self.p:
            d = float(rng.uniform(-self.offset_S, self.offset_S)) * self.S; draws["offset"] = d; self.counts["offset"] += 1
            v = v + d
        if rng.random() < self.p:
            k = float(rng.uniform(*self.gamma)); draws["gamma"] = k; self.counts["gamma"] += 1
            v = np.clip(v, 0.0, 1.0) ** k
        if rng.random() < self.p:
            s = float(rng.uniform(*self.blur)); draws["blur"] = s; self.counts["blur"] += 1
            if s > 0.05:
                v = gaussian_filter(v, sigma=(0.0, s, s), mode="nearest")
        if rng.random() < self.p:
            s = float(rng.uniform(0.0, self.noise_S)) * self.S; draws["noise"] = s; self.counts["noise"] += 1
            v = v + rng.normal(0.0, s, v.shape).astype(np.float32)
        v = np.clip(v, 0.0, 1.0).astype(np.float32)
        self.last = draws
        if self.n <= 3 and os.environ.get("C5_PRINT_RNG") == "1":     # M2 check in the smoke run: draws must differ between workers
            try:
                import torch; wi = torch.utils.data.get_worker_info(); wid = "main" if wi is None else "worker%d" % wi.id
            except Exception:   # noqa: BLE001
                wid = "main"
            print("[c5_augment] %s draw %d: %s; scale_skipped %d" % (wid, self.n, {k: round(x, 4) for k, x in draws.items()}, self.counts["scale_skipped"]), flush=True)
        if lab_max == 255:
            l = ((l > 127) * 255).astype(lab.dtype if hasattr(lab, "dtype") else np.uint8)
        else:
            l = (l > 0.5).astype(lab.dtype if hasattr(lab, "dtype") else np.uint8)
        return v, l


def _centre_crop(v, l, n):
    h, w = v.shape[1], v.shape[2]
    y0, x0 = (h - n) // 2, (w - n) // 2
    return np.ascontiguousarray(v[:, y0:y0 + n, x0:x0 + n]), np.ascontiguousarray(l[y0:y0 + n, x0:x0 + n])


def _selftest_patch(patch, rng, D=16):
    """rev2: the rev1b checks at an arbitrary patch size (win = ceil(patch x 1.18)); stroke 4 px wide at the window centre."""
    L8, S8 = 150.0, 40.0
    win = win_for(patch)
    c = win // 2
    v = np.clip(rng.normal(L8, S8 / 1.35, (D, win, win)), 0, 255).astype(np.float32) / 255.0
    v[:, win // 8:win - win // 8, c - 2:c + 2] = 230 / 255.0
    lab = np.zeros((win, win), np.uint8); lab[win // 8:win - win // 8, c - 2:c + 2] = 255
    aug = C5Augment(L8, S8, p=1.0, patch=patch)
    assert aug.win == win and (patch != 64 or win == 76)
    pc = patch // 2
    for _ in range(30):
        out, lo = aug(v, lab, rng)
        assert out.shape == (D, patch, patch) and lo.shape == (patch, patch) and out.dtype == np.float32, (out.shape, lo.shape, out.dtype)
        assert out.min() >= 0.0 and out.max() <= 1.0
        assert set(np.unique(lo)).issubset({0, 255}), np.unique(lo)
        cols = np.nonzero(lo.any(axis=0))[0]
        assert cols.size >= 3, cols
        bright = int(np.argmax(out[D // 2, pc - 4:pc + 4].mean(axis=0)))   # brightest column, rows around the centre
        assert abs(bright - cols.mean()) <= 2.5, (bright, cols.mean(), aug.last)
    assert aug.counts["scale"] == 30 and aug.counts["scale_skipped"] == 0, aug.counts
    aug0 = C5Augment(L8, S8, p=0.0, patch=patch)
    o0, l0 = aug0(v, lab, rng)
    vc, lc = _centre_crop(v, lab, patch)
    assert np.array_equal(o0, vc) and np.array_equal(l0, lc)
    augp = C5Augment(L8, S8, p=1.0, patch=patch)
    op, lp = augp(vc, lc, rng)
    assert op.shape == (D, patch, patch) and augp.counts["scale_skipped"] == 1 and augp.counts["contrast"] == 1
    # a patch SMALLER than the augmenter's own patch must be refused, not silently padded (Sonnet 284 M2); a larger window is
    # legitimate (it is centre-cropped), so only the small direction is tested
    try:
        C5Augment(L8, S8, p=1.0, patch=patch * 3)(vc, lc, rng); raise AssertionError("too-small patch accepted")
    except ValueError:
        pass
    return v, lab, vc, lc


def selftest():
    rng = np.random.default_rng(1)
    L8, S8 = 150.0, 40.0
    D = 32
    for patch in (64, 192):
        _selftest_patch(patch, rng)
    # rev1b checks at 64 (unchanged)
    v = np.clip(rng.normal(L8, S8 / 1.35, (D, WIN, WIN)), 0, 255).astype(np.float32) / 255.0
    v[:, 10:66, 36:40] = 230 / 255.0
    lab = np.zeros((WIN, WIN), np.uint8); lab[10:66, 36:40] = 255
    vc, lc = _centre_crop(v, lab, PATCH)
    # determinism: same seed -> same output; different worker ids -> different seeds
    a1, _ = C5Augment(L8, S8)(v, lab, np.random.default_rng(5)); a2, _ = C5Augment(L8, S8)(v, lab, np.random.default_rng(5))
    assert np.array_equal(a1, a2)
    assert worker_seed(42) == 42
    # amplitudes in units of S: an offset draw never exceeds 0.5 S, noise sigma never exceeds 0.3 S
    augA = C5Augment(L8, S8, p=1.0)
    for _ in range(200):
        augA(vc, lc, rng)
        assert abs(augA.last["offset"]) <= 0.5 * S8 / 255 + 1e-9 and augA.last["noise"] <= 0.3 * S8 / 255 + 1e-9
    # env switch + rev2 patch plumbing
    os.environ.update({"C5_AUG": "1", "C5_L": "150", "C5_S": "40"})
    os.environ.pop("C5_PATCH", None)
    a = c5_from_env(True); assert isinstance(a, C5Augment) and a.patch == 64 and a.win == 76 and c5_from_env(False) is None
    assert c5_from_env(True, patch=192).win == 227
    os.environ["C5_PATCH"] = "192"; assert c5_from_env(True).patch == 192 and c5_from_env(True, patch=192).patch == 192
    try:
        c5_from_env(True, patch=64); raise AssertionError("C5_PATCH/patch_size mismatch accepted")
    except ValueError:
        pass
    os.environ.pop("C5_PATCH"); os.environ["C5_AUG"] = "0"; assert c5_from_env(True) is None
    print("SELFTEST PASSED: c5_augment rev2 (patch 64 win 76 and patch 192 win 227; ops %s)" % ",".join(C5Augment.ops))
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
