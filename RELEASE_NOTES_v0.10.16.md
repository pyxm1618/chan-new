# v0.10.16 修复说明：身份绑定、连续性校验与正式证据闭环

v0.10.15 已修复正式结构停更，但 MACD 状态锚点和线段提交证据仍缺少强身份绑定。错误品种、错误周期、断档锚点或跨品种线段证据可能污染正式买卖点。本版本完成以下修复。

## 1. MacdAnchor 强身份与连续性验证

`MacdAnchor` 新增并持久化：

- `symbol`、`interval`；
- 前一根 K 的 `last_open_time`、`last_close_time`；
- `expected_next_open_time`；
- 前一根 K 的 `last_bar_fingerprint`；
- `history_start_open_time`、`processed_bar_count`；
- `exact` 状态。

MACD 递推只有在以下条件全部满足时才保持精确：

1. 锚点品种与输入 K 线一致；
2. 锚点周期与输入 K 线一致；
3. 锚点游标恰好连接当前第一根 K；
4. 输入 K 线严格递增、无重复；
5. 固定周期数据内部无断档；
6. 锚点本身来自精确连续历史。

任一条件不满足，正式一买/一卖安全关闭，并输出诊断；不再仅凭 `anchor.asof < first_bar.close_time` 将状态标记为精确。

## 2. SegmentEvidence 与 Segment 一一绑定

每份正式证据新增：

- `segment_symbol`；
- `segment_interval`；
- `segment_fingerprint`；
- `confirmation_available_at`；
- `confirmation_stroke_fingerprint`。

证据必须与目标线段的品种、周期和结构指纹完全一致。跨品种证据、旧窗口证据或错误持久化记录会被拒绝。

外部提交时间映射从：

```python
{segment_index: committed_at}
```

改为：

```python
{segment.fingerprint: committed_at}
```

整数索引键不再接受。

## 3. 买卖点确认时间闭环校验

`validate_trading_points()` 现在可接收正式 `segment_evidence`、提交时间账本和稳定笔链，并从正式账本重新计算买卖点。任何 `confirmed_at_dt` 的提前、推迟或篡改都会被报告为确认时间不一致。

## 4. 不可变确认快照

正式线段提交时永久保存确认笔指纹和证据可用时间。后续候选尾笔发生共享端点迁移时，校验器不再按相同位置读取“当前新笔”，因此消除了错误的 `SEGMENT_COMMIT_TIME_BEFORE_EVIDENCE`。

## 5. 审计边界修复

- 空 `COMMITTED` 线段链现在返回空问题列表，不再触发 `UnboundLocalError`；
- 锚点后剩两笔时保留一条特征元素，短尾仍可审计；
- 新增统一原始 K 流校验模块 `bar_stream.py`。

## 验证

```text
全量测试：123 passed，1 skipped
身份安全专项：11 项检查，失败 0
5000 根结构稳定性：正式失败 0
1000 随机种子活性压力：失败 0
5000 根提交时间校验：问题 0
尾部特征覆盖：失败 0
一买专项：4229 项检查，失败 0
```

跳过项是未安装可选 `czsc` 包的参考差分测试，不是算法失败。
