"""Entry points. Each one puts the tool's folder on sys.path and calls the tool's own ``main()``.

Layout: in a source / editable install the tools are in ``<repo>/tools/<name>``; in a regular install
they are copied to ``vun_tools/_tools/<name>`` (see pyproject.toml). Nothing here changes what a tool does.
"""
import importlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = (os.path.join(_HERE, "_tools"), os.path.join(os.path.dirname(_HERE), "tools"))


def _tools_root():
    for c in _CANDIDATES:
        if os.path.isdir(c):
            return c
    raise SystemExit("vun_tools: cannot find the tools folder (looked in: " + ", ".join(_CANDIDATES) + ")")


def _run(folder, module):
    root = _tools_root()
    d = os.path.join(root, folder)
    if not os.path.isdir(d):
        raise SystemExit(f"vun_tools: tool folder missing: {d}")
    for p in (d, os.path.dirname(root) if os.path.basename(root) == "tools" else None):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module(module).main()


def spacing():
    return _run("sheet_spacing_check", "sheet_spacing_check")


def switch():
    return _run("sheet_switch_finder", "sheet_switch_finder")


def umbilicus():
    return _run("umbilicus_finder", "umbilicus_finder")


def audit():
    return _run("trace_auditor", "trace_auditor")


def phantom():
    return _run("phantom_scroll", "phantom_scroll")


def crush():
    return _run("crush_map", "crush_map")


def ink():
    return _run("ink_infer", "ink_infer")


def merge():
    return _run("patch_merger", "patch_merger")


def sweep():
    return _run("winding_sweep", "winding_sweep")


def drift():
    return _run("label_drift", "label_drift")
def sweep():
    return _run("winding_sweep", "winding_sweep")
def merge():
    return _run("patch_merger", "patch_merger")
