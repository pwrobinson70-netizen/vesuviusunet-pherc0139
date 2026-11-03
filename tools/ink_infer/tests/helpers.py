"""Synthetic fixtures: a planar tifxyz mesh, a CT with a painted spot, tiny checkpoints. No real data."""
import json
import os

import numpy as np

SPOT_VAL = 255


def write_plane_mesh(path, rows, cols, *, z0, scale=(1.0, 1.0), x0=0.0, y0=0.0, voxel_um=3.24,
                     holes=()):
    """Planar tifxyz: x = x0 + col/sx, y = y0 + row/sy, z = z0. holes = [(r0, r1, c0, c1)] -> -1."""
    import tifffile
    sx, sy = scale
    r, c = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    x = (x0 + c / sx).astype(np.float32)
    y = (y0 + r / sy).astype(np.float32)
    z = np.full((rows, cols), z0, np.float32)
    for r0, r1, c0, c1 in holes:
        x[r0:r1, c0:c1] = y[r0:r1, c0:c1] = z[r0:r1, c0:c1] = -1
    os.makedirs(path, exist_ok=True)
    for name, a in (("x", x), ("y", y), ("z", z)):
        tifffile.imwrite(os.path.join(path, f"{name}.tif"), a)
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump({"scale": [sx, sy], "voxelsize": voxel_um}, f)
    return str(path)


def make_ct(shape=(40, 96, 96), spot=None, half=1):
    """uint8 CT [z, y, x], zeros, with a bright cube centred on spot=(z, y, x) (level-0 voxels)."""
    ct = np.zeros(shape, np.uint8)
    if spot is not None:
        z, y, x = spot
        ct[z - half:z + half + 1, y - half:y + half + 1, x - half:x + half + 1] = SPOT_VAL
    return ct


def write_zarr(path, levels):
    """OME-Zarr-like group with arrays '0', '1', ... (works with zarr 2 and 3)."""
    import zarr
    g = zarr.open_group(str(path), mode="w")
    for i, a in enumerate(levels):
        if hasattr(g, "create_array"):
            g.create_array(str(i), data=a, chunks=tuple(min(32, s) for s in a.shape))
        else:
            g.create_dataset(str(i), data=a, chunks=tuple(min(32, s) for s in a.shape))
    return str(path)


def tiny_checkpoint(path, *, depth=16, patch=32, base_channels=2, aggregation="max", topk=None,
                    seed=0, wrap_module=False):
    """Random-weight UNet3D checkpoint in the layout run_hygiene_v2 writes (model/args/contract)."""
    import torch
    from vesuvius_unet.model import UNet3D
    torch.manual_seed(seed)
    m = UNet3D(1, base_channels, aggregation=aggregation, topk=topk)
    sd = m.state_dict()
    if wrap_module:
        sd = {"module." + k: v for k, v in sd.items()}
    torch.save({"model": sd,
                "args": {"base_channels": base_channels, "aggregation": aggregation, "topk": topk,
                         "depth": depth, "patch_size": patch},
                "contract": {"aggregation": aggregation, "topk": topk, "depth": depth,
                             "patch_size": patch}}, path)
    return path
