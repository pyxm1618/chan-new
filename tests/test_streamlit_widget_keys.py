from __future__ import annotations

import ast
from pathlib import Path


def test_all_download_buttons_have_unique_explicit_keys() -> None:
    """Tabs are all rendered in one Streamlit run, so download keys must be global-unique."""

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"), filename=str(app_path))

    keys: list[str] = []
    calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "download_button":
            continue

        calls += 1
        key_keyword = next((kw for kw in node.keywords if kw.arg == "key"), None)
        assert key_keyword is not None, f"download_button at line {node.lineno} has no explicit key"
        assert isinstance(key_keyword.value, ast.Constant) and isinstance(
            key_keyword.value.value, str
        ), f"download_button at line {node.lineno} must use a literal string key"
        keys.append(key_keyword.value.value)

    assert calls > 0
    assert len(keys) == len(set(keys)), f"duplicate download_button keys: {keys}"
