"""The C1 letter-test summary must judge each window by its role: ink windows by the ink rule, blanks by the blank rule.

The script runs on import (argparse, downloads), so role_kind is pulled out of its source and run on its own.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "letter_test_c1_scroll1.py"


def _role_kind():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "role_kind")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SRC), "exec"), ns)
    return ns["role_kind"]


def test_letter_and_labelink_are_ink():
    rk = _role_kind()
    assert [rk(r) for r in ("letter1", "letter2", "letter3", "labelink")] == ["ink"] * 4


def test_blank_and_trueblank_are_blank():
    rk = _role_kind()
    assert rk("blank") == "blank" and rk("trueblank") == "blank"


def test_unknown_role_gets_no_rule():
    assert _role_kind()("diagnostic") == "other"
