#!/usr/bin/env python3
"""phantom_scroll: a small synthetic CT of a rolled papyrus scroll WITH KNOWN GROUND TRUTH (MIT).

    python phantom_scroll.py --out DIR [--size 256] [--turns 4] [--squash 0.7] [--warp-amp 6] ...

Geometry (undeformed): the scroll axis is z. In every xy plane the sheet is an (optionally irregular)
Archimedean spiral r(psi) = r0 + pitch * psi / (2 pi) + dr(psi), psi = angle + 2 pi * winding. Sheet k is
the winding w = k (k = 0 .. turns-1). The volume is then deformed by T = axis tilt + affine squash +
smooth non-rigid warp + an optional local radial "squeeze" that can push neighbouring sheets together
until they touch and merge. Everything that is output is pushed through the SAME forward map T, so the
surfaces, centre line and winding numbers are exact for the volume that was rendered (the volume is
rendered with a fixed-point inverse of T; the round-trip error is checked by the tests).

Outputs (all under --out): volume.zarr (OME-Zarr, level 0 and 1) and/or volume_png/, surfaces/turn_NN
(tifxyz exactly as VC3D writes it, see docs/FORMATS.md), centreline.csv + centreline_villa.json,
winding.npy (int16, turn index per voxel, -1 outside the scroll), truth.json, optional ink mask and
deliberately BAD traces (--bad-switch, --bad-pairs). Seeded and deterministic.

CPU only. Dependencies: numpy, tifffile, pillow, zarr (zarr only for --zarr).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import uuid as _uuid
from dataclasses import dataclass, field

import numpy as np

__version__ = "0.1.0"
TAU = 2 * math.pi
MAX_IRREGULAR = 0.30                        # 2 pi * 0.522 * 0.30 = 0.98 < 1: the spiral stays a spiral


@dataclass
class Params:
    shape: tuple = (256, 256, 256)       # (nz, ny, nx)
    seed: int = 0
    turns: int = 4                       # number of full turns (sheets 0 .. turns-1)
    r0: float = 18.0                     # radius of sheet 0 at angle 0 (voxels)
    pitch: float = 22.0                  # radial distance between neighbouring turns (voxels)
    thickness: float = 6.0               # sheet FWHM (voxels)
    irregular: float = 0.0               # spiral irregularity, fraction of pitch (0 = Archimedean)
    texture: float = 0.25                # relative sheet brightness texture (0..1)
    noise: float = 0.04                  # white noise sigma (fraction of full scale)
    tilt: tuple = (0.0, 0.0)             # axis drift (y, x) voxels per slice
    squash: float = 1.0                  # affine squash factor (<1 compresses along --squash-angle)
    squash_angle: float = 30.0           # degrees; this direction is left unchanged, the PERPENDICULAR one is compressed
    warp_amp: float = 0.0                # smooth non-rigid warp amplitude (voxels)
    warp_wavelength: float = 90.0        # warp wavelength (voxels)
    merge_strength: float = 0.0          # 0 = none; 0.8 = local pitch cut to 20% at the centre of the blob
    merge_turn: float = 1.5              # blob radius = r0 + pitch*(merge_turn + merge_phi/360)
    merge_phi: float = 90.0              # blob angle (degrees)
    merge_z: float = -1.0                # blob height (voxels); <0 = middle
    merge_sigma: float = 22.0            # blob size (voxels)
    ink: bool = False
    ink_turn: int = 1
    ink_text: str = "INK"
    ink_delta: float = 0.10              # relative brightness change of the sheet under ink
    grid_step: float = 4.0               # tifxyz grid step (voxels): meta scale = 1 / grid_step
    air: float = 0.06                    # background intensity (0..1)
    papyrus: float = 0.80                # sheet peak intensity (0..1)

    @property
    def nz(self):
        return int(self.shape[0])

    @property
    def centre0(self):
        return (self.shape[1] / 2.0 - 0.5, self.shape[2] / 2.0 - 0.5)       # (y, x)

    @property
    def r_end(self):
        return self.r0 + self.pitch * self.turns


# ------------------------------------------------------------------ smooth random fields
def _unit(rng, n, dim):
    v = rng.normal(size=(n, dim))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


class Fields:
    """Deterministic smooth fields built from a few random sinusoids (no FFT, no large arrays)."""

    def __init__(self, p: Params):
        rng = np.random.default_rng([p.seed, 7])
        K = 5
        self.p = p
        self.dir = _unit(rng, K, 3)                      # wave vectors (z, y, x directions)
        self.ph = rng.uniform(0, TAU, K)
        self.lam = p.warp_wavelength * rng.uniform(0.7, 1.4, K)
        self.e = _unit(rng, K, 3)                        # displacement directions
        self.e[:, 0] *= 0.25                             # small z displacement
        self.K = K
        self.tdir = _unit(rng, 6, 3)
        self.tph = rng.uniform(0, TAU, 6)
        self.tlam = rng.uniform(7.0, 19.0, 6)
        self.sv_ph = rng.uniform(0, TAU, 2)
        self.ir_a = rng.uniform(0, TAU, 2)

    def warp(self, q):
        """Displacement (dz, dy, dx) at q (3, ...) in (z, y, x)."""
        out = np.zeros_like(q)
        if self.p.warp_amp == 0:
            return out
        for j in range(self.K):
            arg = TAU * np.tensordot(self.dir[j], q, axes=1) / self.lam[j] + self.ph[j]
            s = np.sin(arg) * self.p.warp_amp / math.sqrt(self.K)
            out += self.e[j].reshape(3, *([1] * (q.ndim - 1))) * s
        return out

    def texture(self, q):
        t = np.zeros(q.shape[1:])
        for j in range(6):
            t += np.sin(TAU * np.tensordot(self.tdir[j], q, axes=1) / self.tlam[j] + self.tph[j])
        return t / math.sqrt(6.0)

    def dr(self, psi):
        """Spiral irregularity (voxels) as a function of unwrapped angle psi."""
        a = self.p.irregular * self.p.pitch
        if a == 0:
            return 0.0 * psi
        return a * (0.55 * np.sin(psi * 0.37 + self.ir_a[0]) + 0.35 * np.sin(psi * 0.91 + self.ir_a[1]))

    def dr_prime(self, psi):
        """d dr / d psi (voxels per radian)."""
        a = self.p.irregular * self.p.pitch
        if a == 0:
            return 0.0 * psi
        return a * (0.55 * 0.37 * np.cos(psi * 0.37 + self.ir_a[0]) + 0.35 * 0.91 * np.cos(psi * 0.91 + self.ir_a[1]))


# ------------------------------------------------------------------ the forward map T
class Scroll:
    def __init__(self, p: Params):
        self.p, self.f = p, Fields(p)
        if p.irregular >= MAX_IRREGULAR:       # REVIEW_ROUND2 P1: |dr'| <= 0.522 irregular pitch, the radius must keep growing with w
            raise ValueError(f"irregular={p.irregular:g} makes neighbouring turns cross (1 + 2 pi dr'/pitch can reach 0): "
                             f"use irregular < {MAX_IRREGULAR:g}")
        a = math.radians(p.squash_angle)
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        self.A = R @ np.diag([1.0, p.squash]) @ R.T       # acts on (x, y) column vectors
        self.Ainv = np.linalg.inv(self.A)
        cy, cx = p.centre0
        self.c0 = np.array([cx, cy])
        self.zc = (p.nz - 1) / 2.0
        mz = p.merge_z if p.merge_z >= 0 else self.zc
        rc = p.r0 + p.pitch * (p.merge_turn + p.merge_phi / 360.0)
        self.blob = (mz, math.radians(p.merge_phi), rc)

    # undeformed axis centre (x, y) at height z
    def axis(self, z):
        ty, tx = self.p.tilt
        z = np.asarray(z, float)
        return np.stack([self.c0[0] + tx * (z - self.zc), self.c0[1] + ty * (z - self.zc)])

    def _squeeze(self, qz, rel):
        """Radial displacement vector (x, y) and radial stretch f = dr_def/dr of the squeeze at q."""
        k = self.p.merge_strength
        if k == 0:
            return np.zeros_like(rel), np.ones(qz.shape)
        mz, mphi, rc = self.blob
        sg = self.p.merge_sigma
        r = np.hypot(rel[0], rel[1])
        phi = np.arctan2(rel[1], rel[0])
        arc = r * np.angle(np.exp(1j * (phi - mphi)))
        G = np.exp(-((qz - mz) ** 2 + arc ** 2 + (r - rc) ** 2) / (2 * sg ** 2))
        rr = np.where(r > 1e-9, r, 1.0)
        disp = -k * G * (r - rc) / rr * rel                       # = -k G (r - rc) e_r
        stretch = 1 - k * G * (1 - (r - rc) ** 2 / sg ** 2)
        return disp, stretch

    def forward(self, q):
        """q (3, ...) = (z, y, x) in the undeformed frame -> p (3, ...) deformed."""
        c = self.axis(q[0])
        rel = np.stack([q[2], q[1]]) - c                           # (x, y)
        sq, _ = self._squeeze(q[0], rel)
        ax = np.tensordot(self.A, rel, axes=1)
        d = self.f.warp(q)
        px, py = c[0] + ax[0] + sq[0] + d[2], c[1] + ax[1] + sq[1] + d[1]
        return np.stack([q[0] + d[0], py, px])

    def inverse(self, p, iters=14):
        """Fixed-point inverse of forward (the displacement is small and smooth)."""
        q = p.astype(np.float64).copy()
        for _ in range(iters):
            c = self.axis(q[0])
            sq, _ = self._squeeze(q[0], np.stack([q[2], q[1]]) - c)
            d = self.f.warp(q)
            tgt = np.stack([p[2] - d[2], p[1] - d[1]]) - c - sq
            rel = np.tensordot(self.Ainv, tgt, axes=1)
            q = np.stack([p[0] - d[0], c[1] + rel[1], c[0] + rel[0]])
        return q

    # ---- spiral geometry in the undeformed frame
    def radius(self, w, phi):
        return self.p.r0 + self.p.pitch * (w + phi / TAU) + self.f.dr(TAU * w + phi)

    def winding(self, rel):
        """Continuous winding coordinate w (sheet k is w == k) and angle phi in [0, 2 pi) of rel (x, y)."""
        r = np.hypot(rel[0], rel[1])
        phi = np.mod(np.arctan2(rel[1], rel[0]), TAU)
        w = (r - self.p.r0) / self.p.pitch - phi / TAU
        if self.p.irregular:                   # Newton on f(w) = (r - r0 - dr(2 pi w + phi)) / pitch - phi / 2 pi - w, f' < 0
            for _ in range(8):
                psi = TAU * w + phi
                f = (r - self.p.r0 - self.f.dr(psi)) / self.p.pitch - phi / TAU - w
                w = w - f / (-TAU * self.f.dr_prime(psi) / self.p.pitch - 1.0)
        return w, phi, r

    # ---- rendering
    def render_slab(self, z0, z1, ink_mask=None):
        """Float32 intensity (0..1) and int16 winding for slices z0..z1-1."""
        p = self.p
        nz, ny, nx = p.shape
        zz, yy, xx = np.mgrid[z0:z1, 0:ny, 0:nx].astype(np.float64)
        pt = np.stack([zz, yy, xx])
        q = self.inverse(pt)
        c = self.axis(q[0])
        rel = np.stack([q[2], q[1]]) - c
        w, phi, r = self.winding(rel)
        k = np.clip(np.rint(w), 0, p.turns - 1)
        dw = w - k
        _, stretch = self._squeeze(q[0], rel)
        ang = np.arctan2(rel[1], rel[0]) - math.radians(p.squash_angle)
        aff = np.sqrt(np.cos(ang) ** 2 + (p.squash * np.sin(ang)) ** 2)    # radial stretch of the affine map
        d = dw * p.pitch * np.maximum(stretch, 0.05) * aff               # signed distance to the sheet, deformed voxels
        sig = p.thickness / 2.3548
        prof = np.exp(-d ** 2 / (2 * sig ** 2))
        bright = p.papyrus * (1 + p.texture * 0.5 * self.f.texture(q)
                              + 0.12 * p.texture * np.sin(phi * 2 + k * 1.7 + self.f.sv_ph[0]))
        if p.ink and ink_mask is not None:
            h, wd = ink_mask.shape
            row = np.clip(np.rint(q[0] / p.grid_step).astype(int), 0, h - 1)
            col = np.clip(np.rint(phi / TAU * wd).astype(int) % wd, 0, wd - 1)
            on = (k == p.ink_turn) & (ink_mask[row, col] > 0) & (np.abs(d) < p.thickness)
            bright = bright * np.where(on, 1 + p.ink_delta, 1.0)
        inside = (w > -0.5) & (w < p.turns - 0.5)
        vol = p.air + (bright - p.air) * prof * (np.abs(dw) < 0.5)
        vol = np.where(inside | (prof > 0.01), vol, p.air)
        vol = np.where(w < -0.5, p.air, vol)
        rng = np.random.default_rng([p.seed, 11, z0])
        vol = vol + rng.normal(0, p.noise, vol.shape)
        lab = np.where(inside, k, -1).astype(np.int16)
        return np.clip(vol, 0, 1).astype(np.float32), lab

    def render(self, slab=32, ink_mask=None):
        nz, ny, nx = self.p.shape
        vol = np.empty((nz, ny, nx), np.uint8)
        lab = np.empty((nz, ny, nx), np.int16)
        for z0 in range(0, nz, slab):
            v, l = self.render_slab(z0, min(nz, z0 + slab), ink_mask)
            vol[z0:z0 + len(v)] = np.rint(v * 255).astype(np.uint8)
            lab[z0:z0 + len(v)] = l
        return vol, lab

    # ---- ground truth surfaces / centre line
    def n_cols(self):
        return max(8, int(round(TAU * (self.p.r0 + self.p.pitch * self.p.turns / 2) / self.p.grid_step)))

    def n_rows(self):
        return int((self.p.nz - 1) // self.p.grid_step) + 1

    def trace(self, w):
        """tifxyz points (rows, cols, 3) = (x, y, z) of the surface w (scalar, or (rows, cols) array):
        rows follow z, columns follow the angle. Cells that fall outside the volume are (-1, -1, -1)."""
        p = self.p
        nr, nc = self.n_rows(), self.n_cols()
        zr = np.arange(nr) * p.grid_step
        phi = np.arange(nc) * TAU / nc
        w = np.broadcast_to(np.asarray(w, float), (nr, nc))
        Z, PHI = np.meshgrid(zr, phi, indexing="ij")
        rad = self.radius(w, PHI)
        c = self.axis(Z)
        q = np.stack([Z, c[1] + rad * np.sin(PHI), c[0] + rad * np.cos(PHI)])
        z, y, x = self.forward(q)
        out = np.stack([x, y, z], axis=-1).astype(np.float32)
        nz, ny, nx = p.shape
        bad = (x < 0) | (y < 0) | (z < 0) | (x > nx - 1) | (y > ny - 1) | (z > nz - 1)
        out[bad] = -1.0
        return out

    def turn_surface(self, k):
        return self.trace(float(k))

    def centre_line(self):
        z = np.arange(self.p.nz, dtype=float)
        c = self.axis(z)
        q = np.stack([z, c[1], c[0]])
        pz, py, px = self.forward(q)
        return np.stack([pz, py, px], axis=1)                           # rows (z, y, x) of the deformed axis


# ------------------------------------------------------------------ ink mask
def ink_mask_image(p: Params, n_rows, n_cols):
    """Binary (rows, cols) letter mask on the grid of one turn (rows = z, cols = angle)."""
    from PIL import Image, ImageDraw, ImageFont
    h, w = n_rows, n_cols
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=max(10, int(h * 0.30)))
    except TypeError:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), p.ink_text, font=font)
    d.text(((w - (box[2] - box[0])) // 2 - box[0], (h - (box[3] - box[1])) // 2 - box[1]), p.ink_text, fill=255, font=font)
    return (np.asarray(im) > 127).astype(np.uint8)


# ------------------------------------------------------------------ writers
def write_tifxyz(path, xyz, scale):
    """tifxyz exactly as VC3D writes it (docs/FORMATS.md): x.tif, y.tif, z.tif float32 (H, W), meta.json."""
    import tifffile
    os.makedirs(path, exist_ok=True)
    xyz = np.asarray(xyz, np.float32)
    for k, ax in enumerate("xyz"):
        tifffile.imwrite(os.path.join(path, f"{ax}.tif"), np.ascontiguousarray(xyz[..., k]))
    ok = xyz[..., 0] != -1
    if ok.any():
        pts = xyz[ok]
        bbox = [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()]
    else:
        bbox = [[-1.0] * 3, [-1.0] * 3]
    meta = {"bbox": bbox, "format": "tifxyz", "scale": [float(scale[0]), float(scale[1])], "type": "seg",
            "uuid": str(_uuid.uuid5(_uuid.NAMESPACE_URL, os.path.basename(os.path.normpath(path))))}
    with open(os.path.join(path, "meta.json"), "w") as f:
        json.dump(meta, f, indent=4)


def write_zarr(path, vol):
    import zarr
    g = zarr.open_group(path, mode="w", zarr_format=2)
    a0 = g.create_array("0", shape=vol.shape, chunks=(32, 64, 64), dtype="u1")
    a0[...] = vol
    nz, ny, nx = (s // 2 * 2 for s in vol.shape)
    v1 = vol[:nz, :ny, :nx].astype(np.float32).reshape(nz // 2, 2, ny // 2, 2, nx // 2, 2).mean(axis=(1, 3, 5))
    a1 = g.create_array("1", shape=v1.shape, chunks=(32, 64, 64), dtype="u1")
    a1[...] = np.rint(v1).astype(np.uint8)
    g.attrs["multiscales"] = [{"version": "0.4", "name": "phantom", "axes": [{"name": n, "type": "space"} for n in "zyx"],
                               "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0, 1.0]}]},
                                            {"path": "1", "coordinateTransformations": [{"type": "scale", "scale": [2.0, 2.0, 2.0]}]}]}]


def write_pngs(path, vol):
    from PIL import Image
    os.makedirs(path, exist_ok=True)
    for z in range(vol.shape[0]):
        Image.fromarray(vol[z]).save(os.path.join(path, f"{z:05d}.png"))


# ------------------------------------------------------------------ bad traces
def parse_switch(spec):
    """'turn=1,col=60,delta=1[,width=0][,row0=0]' -> dict."""
    d = dict(turn=1, col=0, delta=1.0, width=0, row0=0)
    for kv in spec.split(","):
        k, v = kv.split("=")
        d[k.strip()] = float(v)
    d["turn"], d["col"], d["width"], d["row0"] = int(d["turn"]), int(d["col"]), int(d["width"]), int(d["row0"])
    return d


def switch_trace(sc: Scroll, s):
    """Surface that follows turn s['turn'] and from column s['col'] (rows >= row0) follows turn + delta
    (a linear ramp over s['width'] columns if width > 0). Returns (xyz, truth dict)."""
    nr, nc = sc.n_rows(), sc.n_cols()
    c = np.arange(nc, dtype=float)[None, :]
    r = np.arange(nr)[:, None]
    ramp = (c >= s["col"]).astype(float) if s["width"] == 0 else np.clip((c - s["col"]) / s["width"], 0, 1)
    w = s["turn"] + s["delta"] * ramp * (r >= s["row0"])
    truth = dict(turn=s["turn"], col=s["col"], delta=s["delta"], width=s["width"], row0=s["row0"],
                 centre_col=s["col"] + s["width"] / 2.0, n_cols=nc, n_rows=nr,
                 direction="outward" if s["delta"] > 0 else "inward")
    return sc.trace(w), truth


def pair_traces(sc: Scroll, turn=1):
    """B traces for the spacing check against A = turn `turn`. expect: 'adjacent' | 'skipped' | 'shared' | 'off_sheet'."""
    k = turn
    out = {"adjacent": (k + 1, "adjacent"), "skipped": (k + 2, "skipped"), "shared": (k + 0.15, "shared"),
           "off_sheet": (k + 1.42, "off_sheet")}
    return {n: (sc.trace(w), e) for n, (w, e) in out.items()}


# ------------------------------------------------------------------ build everything
def build(p: Params, out, *, zarr=True, png=False, bad_switches=(), bad_pairs=False, log=None):
    log = log or (lambda m: None)
    sc = Scroll(p)
    os.makedirs(out, exist_ok=True)
    nr, nc = sc.n_rows(), sc.n_cols()
    mask = ink_mask_image(p, nr, nc) if p.ink else None
    log("rendering volume")
    vol, lab = sc.render(ink_mask=mask)
    if zarr:
        write_zarr(os.path.join(out, "volume.zarr"), vol)
    if png:
        write_pngs(os.path.join(out, "volume_png"), vol)
    np.save(os.path.join(out, "winding.npy"), lab)
    scale = (1.0 / p.grid_step, 1.0 / p.grid_step)
    for k in range(p.turns):
        write_tifxyz(os.path.join(out, "surfaces", f"turn_{k:02d}"), sc.turn_surface(k), scale)
    cl = sc.centre_line()
    with open(os.path.join(out, "centreline.csv"), "w") as f:
        f.write("z,y,x\n" + "\n".join(f"{a:.4f},{b:.4f},{c:.4f}" for a, b, c in cl) + "\n")
    with open(os.path.join(out, "centreline_villa.json"), "w") as f:
        json.dump({"control_points": [{"z": float(a), "y": float(b), "x": float(c)} for a, b, c in cl]}, f, indent=2)
    truth = dict(tool_version=__version__, params=dataclasses.asdict(p), n_rows=nr, n_cols=nc, grid_scale=list(scale),
                 n_turns=p.turns, pitch=p.pitch, units="voxels; x/y/z order in tifxyz, (z, y, x) in csv/volume",
                 switches=[], pairs=[], ink=None)
    if mask is not None:
        from PIL import Image
        Image.fromarray(mask * 255).save(os.path.join(out, "ink_mask.png"))
        truth["ink"] = dict(turn=p.ink_turn, mask="ink_mask.png", text=p.ink_text, delta=p.ink_delta,
                            note="mask rows/cols = grid of surfaces/turn_NN (rows = z, cols = angle)")
    for i, spec in enumerate(bad_switches):
        xyz, t = switch_trace(sc, spec)
        name = f"switch_{i:02d}"
        write_tifxyz(os.path.join(out, "bad", name), xyz, scale)
        truth["switches"].append(dict(trace=f"bad/{name}", **t))
    if bad_pairs:
        a = "surfaces/turn_01"
        for name, (xyz, expect) in pair_traces(sc, 1).items():
            write_tifxyz(os.path.join(out, "bad", f"pair_{name}"), xyz, scale)
            truth["pairs"].append(dict(a=a, b=f"bad/pair_{name}", name=name, expect=expect))
    with open(os.path.join(out, "truth.json"), "w") as f:
        json.dump(truth, f, indent=2)
    return sc, vol, lab, truth


# ------------------------------------------------------------------ CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, help="cube edge (voxels); default 256")
    ap.add_argument("--shape", type=int, nargs=3, metavar=("Z", "Y", "X"))
    ap.add_argument("--no-zarr", action="store_true")
    ap.add_argument("--png", action="store_true", help="also write volume_png/")
    ap.add_argument("--bad-switch", action="append", default=[], metavar="SPEC",
                    help="turn=1,col=60,delta=1[,width=0][,row0=0]; repeatable")
    ap.add_argument("--bad-pairs", action="store_true", help="write B traces: adjacent / skipped / shared / off_sheet")
    d = Params()
    for f in dataclasses.fields(Params):
        if f.name == "shape":
            continue
        v = getattr(d, f.name)
        flag = "--" + f.name.replace("_", "-")
        if f.name == "tilt":
            ap.add_argument(flag, type=float, nargs=2, default=v, metavar=("Y", "X"))
        elif isinstance(v, bool):
            ap.add_argument(flag, action="store_true")
        else:
            ap.add_argument(flag, type=type(v), default=v)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    kw = {f.name: getattr(a, f.name) for f in dataclasses.fields(Params) if f.name != "shape"}
    kw["tilt"] = tuple(kw["tilt"])
    shape = tuple(a.shape) if a.shape else (a.size,) * 3 if a.size else (256, 256, 256)
    p = Params(shape=shape, **kw)
    if p.r_end + 4 > min(shape[1:]) / 2 * 1.2:
        print(f"warning: outer radius {p.r_end:.0f} vox is large for a {shape[1]}x{shape[2]} slice", file=sys.stderr)
    try:
        build(p, a.out, zarr=not a.no_zarr, png=a.png, bad_switches=[parse_switch(s) for s in a.bad_switch],
              bad_pairs=a.bad_pairs, log=lambda m: print(m, file=sys.stderr))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"phantom written to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
