"""Phantom test cases shared by texture_judge, judge_panel and their tests (MIT).

A round phantom with the anisotropic fibre texture on, plus the traces the judges are tested on: the true sheet, a planted sheet switch,
a trace shifted into the gap, a trace that starts on the wrong sheet and stays on it."""
from __future__ import annotations

import dataclasses
import os
import sys

import numpy as np

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("phantom_scroll", "sheet_spacing_check"):
    if os.path.join(_TOOLS, d) not in sys.path:
        sys.path.insert(0, os.path.join(_TOOLS, d))
import phantom_scroll as ps  # noqa: E402
from ssc_io import ArrayVolume, build_mesh  # noqa: E402

FIBRE = dict(fibre=0.4, texture=0.1)         # visible fibre texture; the old isotropic texture turned down so it does not compete


def make_phantom(preset="round", size=160, seed=0, **over):
    """(Scroll, uint8 volume, Params). `over` overrides Params fields after the preset; the fibre texture is on unless fibre=0 is given."""
    kw = dict(FIBRE)
    kw.update(over)
    p = dataclasses.replace(ps.make_params(preset, size, seed), **kw)
    sc = ps.Scroll(p)
    vol, _ = sc.render()
    return sc, vol, p


def mesh_of(sc, w, name="trace"):
    """In-memory Mesh of the surface w (scalar or (rows, cols) array of winding coordinates)."""
    xyz = sc.trace(w)
    g = sc.p.grid_step
    return build_mesh(name, xyz[..., 0], xyz[..., 1], xyz[..., 2], {"scale": [1 / g, 1 / g]})


def switch_mesh(sc, turn=1, col=None, delta=1, width=0, row0=0, name="switch"):
    col = sc.n_cols() // 2 if col is None else col
    xyz, truth = ps.switch_trace(sc, dict(turn=turn, col=col, delta=delta, width=width, row0=row0))
    g = sc.p.grid_step
    return build_mesh(name, xyz[..., 0], xyz[..., 1], xyz[..., 2], {"scale": [1 / g, 1 / g]}), truth


def volume_of(vol):
    return ArrayVolume(vol)


def wrong_sheet_mesh(sc, start_turn=2):
    """A trace that starts on the wrong sheet (not the one the user wanted) and stays on it: internally consistent."""
    return mesh_of(sc, float(start_turn), "wrong_sheet")


def gap_mesh(sc, turn=1):
    """A trace shifted into the dark gap half a pitch from sheet `turn`."""
    return mesh_of(sc, turn + 0.5, "in_gap")
