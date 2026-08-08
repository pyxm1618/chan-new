# v0.10.11 修复说明

## 修复目标

修复有限窗口左侧历史缺失导致的错误首段、错误首个笔中枢和错误首个线段中枢。
v0.10.10 的右侧状态机能够阻止正式结构随新 K 回撤，但不能从任意截断窗口中
推断绝对线段相位。v0.10.11 不再尝试用“跳过第一条/前几条结构”猜测对齐。

## 安全规则

- 默认 `left_boundary_anchored=False`。
- 无真实历史起点声明、无持久化锚点时：
  - 完整笔链、检测线段和候选中枢照常计算；
  - 所有检测线段进入 `unresolved_prefix_segments`；
  - 正式线段、正式中枢和买卖点全部为空。
- `left_boundary_anchored=True` 仅适用于调用方能证明数据从真实历史起点开始的情况。
- 新增 `StructureAnchor`，可从持久化的正式线段端点继续计算。
- 锚点无法在当前笔链中匹配时 fail closed，不猜测替代起点。

## 数据模型

- `stable_strokes`：只保证右侧不会回撤。
- `resolved_strokes`：同时满足右侧稳定和左侧锚定，正式笔中枢只消费该字段。
- `unresolved_prefix_segments`：左边界未解析的全部候选线段。
- `provisional_segments`：左边界已解析后，尚未由下一段提交的右侧候选。
- `left_boundary_resolved`：当前正式结构是否具备可信左边界。
- `left_boundary_anchored` / `left_anchor`：左边界来源。

## UI 与 API

- Streamlit 新增“确认数据从真实历史起点开始”开关，默认关闭。
- `analyze_bars`、`FractalEngine`、`analyze_static`、`analyze_snapshot` 均支持：
  - `left_boundary_anchored`
  - `left_anchor`
- 无锚点模式会明确提示正式结构停止输出，候选仍以虚线展示。

## 验证结果

```text
101 passed, 1 skipped
```

5000 根右边界逐根扫描：

```text
候选笔回撤：175
稳定笔回撤：0
正式线段回撤：0
正式笔中枢消失/缩回：0
正式线段中枢消失/缩回：0
```

5000 根左边界窗口扫描：

```text
无锚点窗口：19，错误正式输出：0
持久化锚点窗口：20，线段后缀/中枢子序列错误：0
锚点缺失窗口：1，fail-closed 失败：0
```

验证命令：

```bash
PYTHONPATH=src pytest
PYTHONPATH=src python scripts/validate_structure_stability.py --bars 5000
PYTHONPATH=src python scripts/validate_window_stability.py --bars 5000
```
