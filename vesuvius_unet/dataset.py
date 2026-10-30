"""
Patch dataset for Vesuvius Challenge ink detection, built from a fragment's
`surface_volume/` slice stack (e.g. 00.tif ... 64.tif) plus its `inklabels.png`
ground-truth mask -- the same layout used by the original Kaggle "Vesuvius
Challenge - Ink Detection" competition and by scrollprize.org's data browser.

Unlike the small-crop RandomForest starter notebook, this tiles the FULL
fragment into many (depth x patch_size x patch_size) patches, so the 3D U-Net
sees real spatial variety across the whole scan, not just one dense region.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

import numpy as np
import tifffile as tiff
import torch
from PIL import Image
from torch.utils.data import Dataset

from .c5_augment_fable_24102026 import c5_from_env, worker_seed   # plan C5 rev2 (C5-3 + M2); inactive unless env C5_AUG=1


def _load_volume_and_mask(data_dir: str, depth: int) -> tuple[np.ndarray, np.ndarray]:
    """Load all slices into memory as (D, H, W) uint16, plus the (H, W) uint8 mask.

    Memory note: a full fragment (65 slices at ~8000x6000px) is roughly 6-7GB
    as uint16. That's fine on a workstation with 32GB+ RAM; if you're tight on
    RAM, downsample the TIFFs to disk first (e.g. with `tifffile` + `cv2.resize`)
    and point `data_dir` at the smaller copies.
    """
    slice_paths = sorted(
        p for p in glob.glob(os.path.join(data_dir, "*.tif")) + glob.glob(os.path.join(data_dir, "*.tiff"))
        if "inklabel" not in os.path.basename(p).lower()
    )
    if not slice_paths:
        raise FileNotFoundError(f"No slice TIFFs found in {data_dir!r}")

    label_candidates = glob.glob(os.path.join(data_dir, "*inklabel*"))
    if not label_candidates:
        raise FileNotFoundError(f"No inklabels file found in {data_dir!r}")
    label_path = label_candidates[0]

    if len(slice_paths) < depth:
        raise ValueError(f"Need at least {depth} slices, found {len(slice_paths)} in {data_dir!r}")
    # Use the first `depth` slices (z=0 is the outermost/surface slice for the
    # Kaggle "surface_volume" layout). Drop any extra slices beyond `depth`.
    slice_paths = slice_paths[:depth]

    # Load into a pre-allocated array rather than a Python list + np.stack --
    # a full fragment is ~6-7GB, and building a list first would transiently
    # need ~2x that memory (list + final array) right when it's most likely
    # to matter.
    first = tiff.imread(slice_paths[0])
    volume = np.empty((depth, *first.shape), dtype=np.uint16)
    volume[0] = first
    del first
    for i, p in enumerate(slice_paths[1:], start=1):
        volume[i] = tiff.imread(p)

    if label_path.lower().endswith((".tif", ".tiff")):
        mask = tiff.imread(label_path)
    else:
        mask = np.array(Image.open(label_path))
    mask = (mask > 0).astype(np.uint8)

    if mask.shape != volume.shape[1:]:
        raise ValueError(f"mask shape {mask.shape} != slice shape {volume.shape[1:]}")

    return volume, mask


@dataclass
class TileIndex:
    y0: int
    x0: int


class VesuviusPatchDataset(Dataset):
    """Yields (volume_patch, label_patch) pairs.

    volume_patch: float32 tensor (1, depth, patch_size, patch_size), normalised to [0, 1]
    label_patch:  float32 tensor (1, patch_size, patch_size), values in {0, 1}

    Tiles are assigned to `split="train"` or `split="val"` by interleaved
    vertical strips spread across the whole fragment width (every Nth
    tile-column goes to val, where N ~= 1/val_fraction), rather than one
    single left/right cut. A single hard column cut can put the *entire*
    validation split in a region that happens to contain no ink at all if
    the writing isn't evenly spread across the fragment (verified to happen
    on Fragment 1: its rightmost 20% is 100% blank papyrus), which silently
    makes every validation metric read 0.0/NaN forever regardless of how
    well the model is actually learning. Interleaved strips still give a
    spatial holdout (train and val tiles never overlap, since tiles are
    non-overlapping by default), but each strip samples across the fragment
    so val sees a representative slice of wherever the ink actually is.
    """

    def __init__(
        self,
        data_dir: str,
        split: str = "train",
        patch_size: int = 256,
        depth: int = 64,
        stride: int | None = None,
        val_fraction: float = 0.2,
        min_ink_fraction_to_keep_negative: float = 0.0,
        negative_keep_prob: float = 0.15,
        augment: bool = True,
        seed: int = 42,
        volume: np.ndarray | None = None,
        mask: np.ndarray | None = None,
    ):
        assert split in ("train", "val")
        self.patch_size = patch_size
        self.depth = depth
        self.augment = augment and split == "train"
        self.rng = np.random.default_rng(seed if split == "train" else seed + 1)
        # plan C5 rev2: augmentation module (train split only, env switch) and per-worker RNG (M2).
        self.seed = seed if split == "train" else seed + 1
        self.c5 = c5_from_env(self.augment)   # None unless C5_AUG=1; with None every line below behaves exactly as before
        self._c5_reseeded = False

        if volume is None or mask is None:
            volume, mask = _load_volume_and_mask(data_dir, depth)
        self.volume = volume  # (D, H, W) uint16, shared across train/val splits
        self.mask = mask      # (H, W) uint8

        D, H, W = self.volume.shape
        stride = stride or patch_size

        xs = list(range(0, W - patch_size + 1, stride))
        ys = list(range(0, H - patch_size + 1, stride))
        # Every Nth tile-COLUMN (by index, not pixel position) goes to val,
        # spread evenly across the width -- see class docstring for why.
        val_every = max(1, round(1 / val_fraction)) if val_fraction > 0 else 0

        tiles: list[TileIndex] = []
        for y0 in ys:
            for i, x0 in enumerate(xs):
                is_val_col = val_every > 0 and (i % val_every == val_every - 1)
                if split == "train" and is_val_col:
                    continue
                if split == "val" and not is_val_col:
                    continue
                tiles.append(TileIndex(y0, x0))

        # Keep every tile that contains at least some ink; subsample
        # ink-free tiles so the dataset isn't dominated by empty background
        # (real fragments are mostly blank papyrus around the written area).
        kept = []
        for t in tiles:
            patch_mask = self.mask[t.y0 : t.y0 + patch_size, t.x0 : t.x0 + patch_size]
            ink_frac = patch_mask.mean()
            if ink_frac > min_ink_fraction_to_keep_negative or self.rng.random() < negative_keep_prob:
                kept.append(t)
        self.tiles = kept

        if not self.tiles:
            raise RuntimeError(
                f"No tiles found for split={split!r} — fragment may be smaller than "
                f"one patch_size={patch_size}, or val_fraction leaves no room."
            )

    def __len__(self) -> int:
        return len(self.tiles)

    def __getitem__(self, idx: int):
        t = self.tiles[idx]
        p = self.patch_size
        if self.c5 is not None and not self._c5_reseeded:   # M2: one RNG stream per DataLoader worker (C5 runs only)
            self.rng = np.random.default_rng(worker_seed(self.seed))
            self._c5_reseeded = True
        if self.c5 is not None:
            # C5-3 scale needs a wider window (self.c5.win = 76) centred on the tile, clamped inside the volume;
            # C5Augment zooms it and centre-crops back to p. NOTE: near a val column the window can include up to
            # (win - p) // 2 = 6 px of it - in-crop val metrics only; recorded in the C5 run record.
            wn = self.c5.win
            H, W = self.mask.shape
            y0 = min(max(t.y0 - (wn - p) // 2, 0), H - wn)
            x0 = min(max(t.x0 - (wn - p) // 2, 0), W - wn)
            vol_patch = self.volume[:, y0 : y0 + wn, x0 : x0 + wn].astype(np.float32) / 65535.0
            lbl_patch = self.mask[y0 : y0 + wn, x0 : x0 + wn].astype(np.float32)
        else:
            vol_patch = self.volume[:, t.y0 : t.y0 + p, t.x0 : t.x0 + p].astype(np.float32) / 65535.0
            lbl_patch = self.mask[t.y0 : t.y0 + p, t.x0 : t.x0 + p].astype(np.float32)

        if self.augment:
            if self.rng.random() < 0.5:
                vol_patch = vol_patch[:, :, ::-1].copy()
                lbl_patch = lbl_patch[:, ::-1].copy()
            if self.rng.random() < 0.5:
                vol_patch = vol_patch[:, ::-1, :].copy()
                lbl_patch = lbl_patch[::-1, :].copy()
            k = int(self.rng.integers(0, 4))
            if k:
                vol_patch = np.rot90(vol_patch, k, axes=(1, 2)).copy()
                lbl_patch = np.rot90(lbl_patch, k, axes=(0, 1)).copy()
            if self.c5 is not None:   # plan C5 rev2, C5-3: scale (window -> p) then intensity ops
                vol_patch, lbl_patch = self.c5(vol_patch, lbl_patch, self.rng)

        vol_t = torch.from_numpy(vol_patch).unsqueeze(0)   # (1, D, p, p)
        lbl_t = torch.from_numpy(lbl_patch).unsqueeze(0)   # (1, p, p)
        return vol_t, lbl_t

    @property
    def ink_fraction(self) -> float:
        """Overall ink-pixel fraction across this split's tiles (for pos_weight)."""
        fracs = [
            self.mask[t.y0 : t.y0 + self.patch_size, t.x0 : t.x0 + self.patch_size].mean()
            for t in self.tiles
        ]
        return float(np.mean(fracs)) if fracs else 0.0


def make_train_val_datasets(data_dir: str, **kwargs) -> tuple[VesuviusPatchDataset, VesuviusPatchDataset]:
    """Load the volume/mask once and share it between train and val splits
    (avoids reading the ~6GB fragment from disk twice)."""
    depth = kwargs.get("depth", 64)
    volume, mask = _load_volume_and_mask(data_dir, depth)
    train_ds = VesuviusPatchDataset(data_dir, split="train", volume=volume, mask=mask, **kwargs)
    val_ds = VesuviusPatchDataset(data_dir, split="val", volume=volume, mask=mask, **kwargs)
    return train_ds, val_ds


if __name__ == "__main__":
    import sys

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    train_ds, val_ds = make_train_val_datasets(data_dir, patch_size=256, depth=64, stride=256)
    print(f"train tiles: {len(train_ds)}  (ink frac ~{train_ds.ink_fraction:.3f})")
    print(f"val tiles:   {len(val_ds)}  (ink frac ~{val_ds.ink_fraction:.3f})")
    v, l = train_ds[0]
    print("sample volume patch:", v.shape, v.dtype, "label patch:", l.shape, l.dtype)
