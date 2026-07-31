# v0.10.12 修复说明

## 修复内容

### 1. 修复稳定末笔校验误报

旧页面把正式账本与直接检测结果使用同一校验语义，并把
`resolved_strokes` 的最后一笔机械视为可回撤笔，因此 5000 根可信起点数据
会产生：

- `SEGMENT_FEATURE_SEQUENCE_MISMATCH`
- `SEGMENT_CONFIRMATION_USES_REVERSIBLE_LAST_STROKE`

现在新增 `SegmentValidationTarget`：

- `DETECTED`：直接检测链必须与全量重算完全一致；
- `COMMITTED`：正式账本必须是从其真实锚点重算结果的连续前缀。

校验器同时接收 `stable_stroke_count`，只有该位置之后的笔才被视为可回撤。
Streamlit 页面改为使用完整 `result.strokes`、正式账本语义和真实稳定前缀长度。

### 2. 增加线段真实提交时间

`SegmentEvidence` 新增：

- `committed_at`
- `committed_at_bar_position`

`StructureState.update()` 在每根原始 K 收盘后推进结构；新线段真正追加到
`segments` 时，记录当前 K 的 `close_time` 和零基位置。批量分析、增量分析、
重放和导出均保留该数据。

交易点确认时间现在优先使用 `committed_at`，避免把线段端点或特征确认笔时间
误当成实时可知时间。

## 验证结果

```text
106 passed, 1 skipped
5000 根正式账本校验问题：0
56 条正式线段 committed_at 缺失：0
提交时间逆序：0
逐根首次提交时刻不一致：0
右侧正式结构回撤：0
左边界错误正式输出：0
```
