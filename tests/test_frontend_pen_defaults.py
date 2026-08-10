from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _imports_name(tree: ast.Module, module: str, name: str, *, level: int = 0) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and node.level == level
        and any(alias.name == name for alias in node.names)
        for node in tree.body
    )


def test_cli_min_bi_len_defaults_use_shared_original_theory_constant() -> None:
    tree = _tree(ROOT / "src" / "chan_monitor" / "cli.py")
    defaults: list[ast.expr | None] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        if not any(
            isinstance(arg, ast.Constant) and arg.value == "--min-bi-len"
            for arg in node.args
        ):
            continue
        defaults.append(_keyword(node, "default"))

    assert len(defaults) == 2
    assert all(
        isinstance(default, ast.Name) and default.id == "DEFAULT_MIN_BI_LEN"
        for default in defaults
    )
    assert _imports_name(tree, "strokes", "DEFAULT_MIN_BI_LEN", level=1)


def test_streamlit_min_bi_len_default_uses_shared_original_theory_constant() -> None:
    tree = _tree(ROOT / "app.py")
    matching_calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "number_input":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value == "最小笔长（无包含 K 数）":
            matching_calls.append(node)

    assert len(matching_calls) == 1
    value = _keyword(matching_calls[0], "value")
    assert isinstance(value, ast.Name) and value.id == "DEFAULT_MIN_BI_LEN"
    assert _imports_name(tree, "chan_monitor.strokes", "DEFAULT_MIN_BI_LEN")
