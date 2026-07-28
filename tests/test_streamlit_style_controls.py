from __future__ import annotations

import ast
from pathlib import Path


REQUIRED_STYLE_LABELS = {
    "笔颜色", "笔线宽", "笔端点",
    "线段颜色", "线段线宽", "线段端点",
    "笔中枢颜色", "笔中枢边框", "笔中枢中轴", "笔中枢填充",
    "线段中枢颜色", "线段中枢边框", "线段中枢中轴", "线段中枢填充",
    "顶分型颜色", "顶分型大小", "顶分型边框",
    "底分型颜色", "底分型大小", "底分型边框",
    "一买颜色", "二买颜色", "三买颜色",
    "一卖颜色", "二卖颜色", "三卖颜色",
    "一买大小", "二买大小", "三买大小",
    "一卖大小", "二卖大小", "三卖大小",
    "买卖点边框粗细", "背景颜色", "背景填充",
    "悬停背景颜色", "悬停背景不透明度",
}


def _style_calls() -> list[ast.Call]:
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"color_picker", "slider"} or not node.args:
            continue
        label = node.args[0]
        if isinstance(label, ast.Constant) and isinstance(label.value, str) and label.value in REQUIRED_STYLE_LABELS:
            calls.append(node)
    return calls


def test_all_non_k_layers_have_style_controls() -> None:
    labels = {call.args[0].value for call in _style_calls()}
    assert labels == REQUIRED_STYLE_LABELS


def test_style_widget_keys_are_explicit_and_unique() -> None:
    keys: list[str] = []
    for call in _style_calls():
        key_kw = next((kw for kw in call.keywords if kw.arg == "key"), None)
        assert key_kw is not None
        assert isinstance(key_kw.value, ast.Constant) and isinstance(key_kw.value.value, str)
        keys.append(key_kw.value.value)
    assert len(keys) == len(set(keys))


def test_hover_toggle_has_explicit_unique_key() -> None:
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8"))
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "toggle" or not node.args:
            continue
        label = node.args[0]
        if isinstance(label, ast.Constant) and label.value == "显示悬停数据框":
            matches.append(node)
    assert len(matches) == 1
    key_kw = next((kw for kw in matches[0].keywords if kw.arg == "key"), None)
    assert key_kw is not None
    assert isinstance(key_kw.value, ast.Constant)
    assert key_kw.value.value == "style_hover_enabled"
