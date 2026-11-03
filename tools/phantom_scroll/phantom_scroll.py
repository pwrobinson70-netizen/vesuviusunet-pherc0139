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

Harder phantoms (v0.2, all OFF by default: with none of the flags below the output is byte-identical to v0.1):
  --fold SPEC     a sheet doubles back on itself over a local region (an S-shaped pleat, three layers at the middle)
  --delam SPEC    one sheet splits into two thin layers with a small gap
  --tear SPEC     a sheet ends and restarts with a radial offset (with a missing stretch between the two ends)
  --gap SPEC      a sheet segment is missing (the surface exists in the truth, but there is no bright sheet there)
  --spacing-ratio R   the local sheet spacing is compressed by a smooth factor between 1/R and 1 (angle, slowly z): max/min = R within a slice
  SPEC = turn=2,phi=200,z=-1,len=48,zlen=90[,amount=1.7][,h=6][,gap=10][,off=6]  (phi degrees, z/len voxels, z<0 = middle)
  --preset NAME   round, mild, crushed (= bad), merged, folded, delaminated, torn, gappy, crushed-hard
  --severity      also write severity.npy (float32, 0 = untouched .. 1 = worst) even when no v0.2 feature is on
Ground truth: winding.npy labels every voxel with its sheet (a folded / delaminated / torn sheet keeps its label on ALL its layers and
pieces; a gap keeps its label), surfaces/turn_NN follow the deformed sheet (S-shaped for a fold, the MID plane for a delamination, the
two pieces with the missing stretch interpolated for a tear). severity.npy is, per voxel inside the scroll, the larger of the feature
window (cos^2 bump, exactly 0 outside the window) and |ln s| / ln 4 clipped to 1, where s is the true local radial stretch of the
deformation (squash, warp, squeeze, spacing field), so an undeformed phantom has an all-zero map.

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

__version__ = "0.2.0"
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
    spacing_ratio: float = 1.0           # v0.2: max/min of the local sheet spacing within a slice (1 = off, up to 2.5 or more)
    features: tuple = ()                 # v0.2: tuple of dicts, see parse_feature (fold / delam / tear / gap)

    @property
    def nz(self):
        return int(self.shape[0])

    @property
    def centre0(self):
        return (self.shape[1] / 2.0 - 0.5, self.shape[2] / 2.0 - 0.5)       # (y, x)

    @property
    def r_end(self):
        return self.r0 + self.pitch * self.turns



# ------------------------------------------------------------------ v0.2 local features (fold, delamination, tear, gap)
FEATURE_KINDS = ("fold", "delam", "tear", "gap")
SEAM_MARGIN = math.radians(8.0)              # a feature window must stay this far from the angle-0 seam
LN_SEV = math.log(4.0)                       # severity 1 = local spacing changed by a factor 4 (either way)


def bump(x):
    """cos^2 bump with compact support: 1 at x = 0, exactly 0 for |x| >= 1."""
    x = np.asarray(x, float)
    return np.where(np.abs(x) < 1.0, np.cos(0.5 * math.pi * x) ** 2, 0.0)


FEATURE_DEFAULTS = dict(turn=1, phi=180.0, z=-1.0, len=40.0, zlen=80.0, amount=1.7, h=6.0, gap=10.0, off=6.0)


def parse_feature(kind, spec):
    """'turn=2,phi=200,z=-1,len=48,zlen=90,amount=1.7,h=6' -> dict (all numbers, kind added)."""
    if kind not in FEATURE_KINDS:
        raise ValueError(f"unknown feature {kind!r}")
    d = dict(FEATURE_DEFAULTS, kind=kind)
    for kv in spec.split(","):
        if kv.strip():
            k, v = kv.split("=")
            if k.strip() not in d:
                raise ValueError(f"unknown key {k!r} in {kind} spec {spec!r}")
            d[k.strip()] = float(v)
    d["turn"] = int(d["turn"])
    return d


class Feature:
    """One local deformation of ONE sheet, in the sheet's own unrolled frame: a = arc length along the sheet from the window
    centre (R0 * delta angle, R0 = undeformed radius of the sheet at the centre), e = radial offset from the undeformed sheet."""

    def __init__(self, sc, d):
        p = sc.p
        d = dict(FEATURE_DEFAULTS, **d)
        self.d, self.kind, self.turn = d, d["kind"], int(d["turn"])
        if not 0 <= self.turn < p.turns:
            raise ValueError(f"{self.kind}: turn {self.turn} outside 0..{p.turns - 1}")
        self.phi0 = math.radians(d["phi"] % 360.0)
        self.R0 = p.r0 + p.pitch * (self.turn + self.phi0 / TAU)
        self.L = max(2.0, d["len"] / 2.0)                    # half window length along the sheet (voxels)
        self.Zh = max(2.0, d["zlen"] / 2.0)                  # half window height (voxels)
        self.z0 = d["z"] if d["z"] >= 0 else sc.zc
        reach = self.L + (d["amount"] * 2 * self.L / math.pi if self.kind == "fold" else 0.0) + 2 * p.thickness
        marg = reach / self.R0
        if self.phi0 - marg < SEAM_MARGIN or self.phi0 + marg > TAU - SEAM_MARGIN:
            raise ValueError(f"{self.kind} window (phi {d['phi']:g} deg, reach {reach:.0f} vox) comes within 8 degrees of the "
                             f"angle-0 seam: move phi towards 180 or shorten len")
        if self.kind == "fold" and d["amount"] <= 0:
            raise ValueError("fold amount must be > 0 (> 1 makes the sheet double back)")
        size = {"fold": abs(d["h"]), "delam": 0.5 * abs(d["h"]), "tear": abs(d["off"])}.get(self.kind, 0.0)
        if size > 0.45 * p.pitch:
            raise ValueError(f"{self.kind}: radial size above 0.45 pitch would make the nearest-sheet label ambiguous")
        self.A = d["amount"] * 2 * self.L / math.pi if self.kind == "fold" else 0.0     # arc shift of a fold at its centre
        self.pad = 2 * p.thickness
        self.lo, self.hi = -self.L - self.pad, self.L + self.A + self.pad            # arc range that can hold deformed sheet
        self.ns = int(max(60, 4 * (self.hi - self.lo)))
        self.s = np.linspace(self.lo, self.hi, self.ns)                               # nominal arc coordinate of the samples
        self.beta = bump(self.s / self.L)

    # window value (0..1) at arc coordinate a and height z
    def window(self, a, z):
        """Severity window (0..1, exactly 0 outside): a cos^2 bump over the arc range [-L, L + A] and over the height range."""
        return bump((np.asarray(a) - 0.5 * self.A) / (self.L + 0.5 * self.A)) * bump((np.asarray(z) - self.z0) / self.Zh)

    def curve(self, bz):
        """Pieces of the deformed sheet for window height factor bz (scalar or (N,)). Each piece = (arc, e, keep) with arrays
        shaped (N, ns): arc coordinate, radial offset, and a validity mask."""
        d = self.d
        bz = np.atleast_1d(np.asarray(bz, float))[:, None]
        s, be = self.s[None, :], self.beta[None, :]
        if self.kind == "fold":
            return [(s + self.A * bz * be, d["h"] * bz * be, np.ones_like(s * bz, bool))]
        if self.kind == "delam":
            h = 0.5 * d["h"] * bz * be
            ok = np.ones_like(s * bz, bool)
            return [(s + 0 * bz, h, ok), (s + 0 * bz, -h, ok)]
        if self.kind == "tear":
            g = 0.5 * d["gap"] * bz
            x = np.clip((s - g) / np.maximum(self.L - g, 1e-9), 0, 1)
            relax = 1 - (3 * x ** 2 - 2 * x ** 3)                       # 1 at the restart, smoothstep down to 0 at +L
            first = np.broadcast_to(s, (bz.shape[0], s.shape[1])) < -g
            second = np.broadcast_to(s, (bz.shape[0], s.shape[1])) > g
            return [(s + 0 * bz, 0 * s * bz, first), (s + 0 * bz, d["off"] * bz * relax, second)]
        return []

    def apply(self, a, e, bz, scale, sig):
        """For voxels (a, e) in the window return (profile, brightness factor). `scale` converts undeformed voxels to
        deformed ones, `sig` is the sheet sigma in deformed voxels."""
        n = len(a)
        prof = np.empty(n)
        fac = np.ones(n)
        if self.kind == "gap":
            prof = np.exp(-(e * scale) ** 2 / (2 * sig ** 2))
            fac = 1 - np.clip(1.6 * bump(a / self.L) * bz, 0, 1)        # sheet brightness removed where the window is > 0.6
            return prof, fac
        sg = sig * (0.6 if self.kind == "delam" else 1.0)
        step = max(1, int(4_000_000 // (self.ns * (2 if self.kind in ("delam", "tear") else 1))))
        for i0 in range(0, n, step):
            sl = slice(i0, min(n, i0 + step))
            best = np.full(sl.stop - sl.start, np.inf)
            for arc, off, keep in self.curve(bz[sl]):
                dd = np.hypot(a[sl, None] - arc, e[sl, None] - off)
                dd = np.where(keep, dd, np.inf)
                best = np.minimum(best, dd.min(axis=1))
            prof[sl] = np.exp(-(best * scale[sl]) ** 2 / (2 * sg ** 2))
        return prof, fac

    def displace(self, phi, z, scale_w):
        """Truth-trace displacement for grid angle phi (array) and heights z: (new phi, radial offset e). `scale_w` (0..1) is the
        weight of this feature for the traced surface (1 on the sheet itself, fading to 0 half a pitch away)."""
        a = self.R0 * (phi - self.phi0)
        bz = bump((z - self.z0) / self.Zh)
        be = bump(a / self.L)
        d = self.d
        w = scale_w * bz
        if self.kind == "fold":
            return phi + w * self.A * be / self.R0, w * d["h"] * be
        if self.kind == "tear":
            g = 0.5 * d["gap"] * w
            x = np.clip((a - g) / np.maximum(self.L - g, 1e-9), 0, 1)
            relax = 1 - (3 * x ** 2 - 2 * x ** 3)
            ramp = np.clip((a + g) / np.maximum(2 * g, 1e-9), 0, 1)       # across the missing stretch: linear from the first end to the second
            return phi, np.where(g > 0, d["off"] * w * relax * ramp, 0.0)
        return phi, 0.0 * phi                            # delam: truth = mid plane; gap: surface unchanged


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
        # v0.2 (independent RNG stream, so the v0.1 fields do not change)
        if p.spacing_ratio < 1.0:
            raise ValueError("spacing_ratio is max/min of the local spacing and must be >= 1")
        rng = np.random.default_rng([p.seed, 13])
        self.sp_ph = rng.uniform(0, TAU, 2)
        g = self._sp_raw(np.linspace(0, TAU, 20001), self.zc)
        self._sp_lo, self._sp_hi = float(g.min()), float(g.max())
        self.features = [Feature(self, dict(d)) for d in p.features]

    def _sp_raw(self, phi, z):
        return 0.75 * np.sin(phi + self.sp_ph[0] + 0.012 * (np.asarray(z) - self.zc)) + 0.25 * np.sin(2 * phi + self.sp_ph[1])

    def spacing_factor(self, phi, z):
        """Radial scale of the local-spacing field at undeformed angle phi and height z (1 everywhere when spacing_ratio == 1).
        It only COMPRESSES (so the outer turns stay inside the volume): values lie in [1/spacing_ratio, 1] and max / min over
        phi at the middle slice is exactly spacing_ratio."""
        if self.p.spacing_ratio == 1.0:
            return np.ones(np.broadcast(np.asarray(phi), np.asarray(z)).shape)
        gn = np.clip((2 * self._sp_raw(phi, z) - (self._sp_hi + self._sp_lo)) / (self._sp_hi - self._sp_lo), -1.0, 1.0)
        return np.exp(0.5 * math.log(self.p.spacing_ratio) * (gn - 1.0))

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
        if self.p.spacing_ratio != 1.0:
            rel_s = rel * self.spacing_factor(np.arctan2(rel[1], rel[0]), q[0])
        else:
            rel_s = rel
        ax = np.tensordot(self.A, rel_s, axes=1)
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
            if self.p.spacing_ratio != 1.0:
                rel = rel / self.spacing_factor(np.arctan2(rel[1], rel[0]), p[0] - d[0])
            q = np.stack([p[0] - d[0], c[1] + rel[1], c[0] + rel[0]])
        if self.p.spacing_ratio != 1.0:
            # v0.2: with the compressing spacing field the plain fixed point above no longer contracts (the inverse step amplifies the
            # warp gradient by 1 / f), so finish with a damped residual iteration; omega is optimal for a Jacobian whose eigenvalues
            # lie in [squash / ratio, 1]. (Never reached when spacing_ratio == 1, so v0.1 outputs are unchanged.)
            lam = min(1.0, self.p.squash) / self.p.spacing_ratio
            omega = 2.0 / (1.0 + lam)
            for _ in range(60):
                res = self.forward(q) - p
                q = q - omega * res
                if np.abs(res).max() < 1e-7:
                    break
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
    def local_scale(self, q, rel):
        """True local radial stretch s of the forward map at undeformed points q (3, ...) (rel = (x, y) offset from the axis):
        the factor by which the spacing between neighbouring sheets is multiplied (1 = undeformed)."""
        r = np.maximum(np.hypot(rel[0], rel[1]), 1e-9)
        u = np.stack([np.zeros_like(r), rel[1] / r, rel[0] / r])
        eps = 0.5
        pa, pb = self.forward(q + eps * u), self.forward(q - eps * u)
        return np.sqrt(((pa - pb) ** 2).sum(axis=0)) / (2 * eps)

    def render_slab(self, z0, z1, ink_mask=None, severity=False):
        """Float32 intensity (0..1) and int16 winding for slices z0..z1-1 (plus a float32 severity map when severity=True)."""
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
        fct = self.spacing_factor(phi, q[0]) if p.spacing_ratio != 1.0 else 1.0
        scale = np.maximum(stretch, 0.05) * aff * fct                    # undeformed -> deformed radial distance
        d = dw * p.pitch * scale                                         # signed distance to the sheet, deformed voxels
        sig = p.thickness / 2.3548
        prof = np.exp(-d ** 2 / (2 * sig ** 2))
        bright = p.papyrus * (1 + p.texture * 0.5 * self.f.texture(q)
                              + 0.12 * p.texture * np.sin(phi * 2 + k * 1.7 + self.f.sv_ph[0]))
        win = np.zeros(k.shape)
        for ft in self.features:                                          # v0.2 local features
            a = ft.R0 * (phi - ft.phi0)
            bz = bump((q[0] - ft.z0) / ft.Zh)
            m = (k == ft.turn) & (a > ft.lo) & (a < ft.hi) & (bz > 0)
            if not m.any():
                continue
            e = r - self.radius(k, phi)
            sc_m = np.broadcast_to(scale, k.shape)[m]
            pr, fc = ft.apply(a[m], e[m], bz[m], sc_m, sig)
            prof[m] = pr
            bright[m] *= fc
            win[m] = np.maximum(win[m], ft.window(a[m], q[0][m]))
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
        out = np.clip(vol, 0, 1).astype(np.float32)
        if not severity:
            return out, lab
        sev = np.zeros(k.shape)
        if self.deformed():
            ls = np.abs(np.log(np.maximum(self.local_scale(q, rel), 1e-6))) / LN_SEV
            sev = np.where(ls < 1e-5, 0.0, np.clip(ls, 0, 1))
        sev = np.where(inside, np.maximum(sev, win), 0.0).astype(np.float32)
        return out, lab, sev

    def deformed(self):
        p = self.p
        return bool(p.squash != 1.0 or p.warp_amp != 0 or p.merge_strength != 0 or p.spacing_ratio != 1.0)

    def render(self, slab=32, ink_mask=None, severity=False):
        nz, ny, nx = self.p.shape
        vol = np.empty((nz, ny, nx), np.uint8)
        lab = np.empty((nz, ny, nx), np.int16)
        sev = np.empty((nz, ny, nx), np.float32) if severity else None
        for z0 in range(0, nz, slab):
            res = self.render_slab(z0, min(nz, z0 + slab), ink_mask, severity=severity)
            v, l = res[0], res[1]
            vol[z0:z0 + len(v)] = np.rint(v * 255).astype(np.uint8)
            lab[z0:z0 + len(v)] = l
            if severity:
                sev[z0:z0 + len(v)] = res[2]
        return (vol, lab, sev) if severity else (vol, lab)

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
        PHI_E, e_off = PHI, 0.0
        if self.features:                                    # v0.2: features move the truth surface exactly as they move the sheet
            kk = np.rint(w)
            cw = np.clip((0.5 - np.abs(w - kk)) / 0.25, 0, 1)    # 1 on the sheet, fading to 0 half a pitch away
            for ft in self.features:
                ph, e = ft.displace(PHI_E, Z, cw * (kk == ft.turn))
                PHI_E, e_off = ph, e_off + e
        rad = self.radius(w, PHI_E) + e_off
        c = self.axis(Z)
        q = np.stack([Z, c[1] + rad * np.sin(PHI_E), c[0] + rad * np.cos(PHI_E)])
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
def build(p: Params, out, *, zarr=True, png=False, bad_switches=(), bad_pairs=False, log=None, severity=None):
    """severity: None = write severity.npy only when a v0.2 feature or spacing field is on; True = always; False = never."""
    log = log or (lambda m: None)
    sc = Scroll(p)
    want_sev = bool(p.features or p.spacing_ratio != 1.0) if severity is None else bool(severity)
    os.makedirs(out, exist_ok=True)
    nr, nc = sc.n_rows(), sc.n_cols()
    mask = ink_mask_image(p, nr, nc) if p.ink else None
    log("rendering volume")
    if want_sev:
        vol, lab, sev = sc.render(ink_mask=mask, severity=True)
        np.save(os.path.join(out, "severity.npy"), sev)
    else:
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


# ------------------------------------------------------------------ presets
# Geometry for every preset: 4 turns, r0 = 18, pitch = 22, thickness = 6, grid step = 4 at size 256 (scaled with --size).
# "bad" is the v0.1 name of "crushed" and stays. Lengths in feature specs are given for size 256 and scaled with the size.
_MILD = dict(squash=0.85, squash_angle=30.0, warp_amp=3.0, irregular=0.05, tilt=(0.05, -0.03))
PRESETS = {
    "round": dict(),
    "mild": dict(_MILD),
    "bad": dict(squash=0.55, squash_angle=30.0, warp_amp=7.0, irregular=0.12, tilt=(0.10, -0.08)),
    "merged": dict(squash=0.8, warp_amp=3.0, irregular=0.05, merge_strength=0.85, merge_turn=1.5,
                   merge_phi=90.0, merge_sigma=0.09),      # merge_sigma given as a fraction of --size
    # v0.2: mild background deformation plus local damage, so the damage is what the tools see
    "folded": dict(_MILD, features=(dict(kind="fold", turn=2, phi=200.0, z=-1.0, len=44.0, zlen=90.0, amount=2.8, h=9.0),
                                    dict(kind="fold", turn=1, phi=285.0, z=60.0, len=36.0, zlen=70.0, amount=2.5, h=8.0))),
    "delaminated": dict(_MILD, features=(dict(kind="delam", turn=2, phi=120.0, z=-1.0, len=80.0, zlen=110.0, h=8.0),
                                         dict(kind="delam", turn=1, phi=290.0, z=170.0, len=60.0, zlen=80.0, h=7.0))),
    "torn": dict(_MILD, features=(dict(kind="tear", turn=2, phi=250.0, z=-1.0, len=60.0, zlen=90.0, gap=10.0, off=6.0),
                                  dict(kind="tear", turn=1, phi=80.0, z=70.0, len=50.0, zlen=70.0, gap=8.0, off=-5.0))),
    "gappy": dict(_MILD, features=(dict(kind="gap", turn=2, phi=150.0, z=-1.0, len=56.0, zlen=70.0),
                                   dict(kind="gap", turn=1, phi=295.0, z=170.0, len=44.0, zlen=60.0),
                                   dict(kind="gap", turn=3, phi=60.0, z=90.0, len=50.0, zlen=60.0))),
    # harder than "crushed": squash 0.5, warp 8, irregular 0.15 and a local-spacing field of 2.5x on top (spacing between 0.2 and 1 of
    # nominal, i.e. 4-22 voxels at size 256, thickness 6): neighbouring sheets overlap in the compressed sector
    "crushed-hard": dict(squash=0.5, squash_angle=30.0, warp_amp=8.0, irregular=0.15, tilt=(0.10, -0.08), spacing_ratio=2.5),
}
PRESET_NAMES = tuple(PRESETS) + ("crushed",)


def make_params(name, size=256, seed=0):
    """Params of preset `name` (also 'crushed' = 'bad') for a size^3 volume, 4 turns, geometry scaled with size / 256."""
    if name == "crushed":
        name = "bad"
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from {', '.join(PRESET_NAMES)}")
    kw = dict(PRESETS[name])
    scale = size / 256.0
    if "merge_sigma" in kw:
        kw["merge_sigma"] = kw["merge_sigma"] * size
    if "features" in kw:
        feats = []
        for d in kw["features"]:
            d = dict(d)
            for key in ("z", "len", "zlen", "h", "gap", "off"):
                if key in d and not (key == "z" and d[key] < 0):
                    d[key] = d[key] * scale
            feats.append(d)
        kw["features"] = tuple(feats)
    return Params(shape=(size,) * 3, seed=seed, turns=4, r0=18.0 * scale, pitch=22.0 * scale,
                  thickness=6.0 * scale, grid_step=4.0 * scale, **kw)


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
    ap.add_argument("--preset", choices=PRESET_NAMES, help="start from a preset (needs --size or --shape cube); other flags given explicitly override it")
    ap.add_argument("--severity", action="store_true", help="always write severity.npy")
    for kind in FEATURE_KINDS:
        ap.add_argument(f"--{kind}", action="append", default=[], metavar="SPEC",
                        help="turn=2,phi=200,z=-1,len=48,zlen=90[,amount=1.7][,h=6][,gap=10][,off=6]; repeatable")
    d = Params()
    for f in dataclasses.fields(Params):
        if f.name in ("shape", "features"):
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
    names = [f.name for f in dataclasses.fields(Params) if f.name not in ("shape", "features")]
    kw = {n: getattr(a, n) for n in names}
    kw["tilt"] = tuple(kw["tilt"])
    shape = tuple(a.shape) if a.shape else (a.size,) * 3 if a.size else (256, 256, 256)
    try:
        feats = [parse_feature(k, spec) for k in FEATURE_KINDS for spec in getattr(a, k)]
        if a.preset:
            if len(set(shape)) != 1:
                raise ValueError("--preset needs a cube (--size N)")
            base = make_params(a.preset, shape[0], a.seed)
            dflt = Params()
            for n in names:                                   # explicit flags beat the preset
                if getattr(a, n) != getattr(dflt, n):
                    kw[n] = getattr(a, n)
                else:
                    kw[n] = getattr(base, n)
            feats = list(base.features) + feats
        p = Params(shape=shape, features=tuple(feats), **kw)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if p.r_end + 4 > min(shape[1:]) / 2 * 1.2:
        print(f"warning: outer radius {p.r_end:.0f} vox is large for a {shape[1]}x{shape[2]} slice", file=sys.stderr)
    try:
        build(p, a.out, zarr=not a.no_zarr, png=a.png, bad_switches=[parse_switch(s) for s in a.bad_switch],
              bad_pairs=a.bad_pairs, log=lambda m: print(m, file=sys.stderr),
              severity=True if a.severity else None)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"phantom written to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
