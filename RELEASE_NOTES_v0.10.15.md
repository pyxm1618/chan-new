# v0.10.15 修复说明：正式结构活性、提交边界与买卖点证据

v0.10.14 已经解决正式结构右侧回撤、左边界错相位、真实提交时间和严格一买逻辑，但仍有一个阻断级状态机问题：线段提交时把“用于确认的尾部证据笔”也写进 `stable_strokes`。该证据笔的共享端点后来仍可能发生 `SHARED_ENDPOINT_REPLACED`，导致原始检测链中旧端点消失，规范笔链无法重新接入，正式线段、中枢和买卖点从此永久停更。

## 1. stable_strokes 只封存正式线段几何

旧逻辑：

```python
stable_count = max(evidence.confirmed_at_position) + 1
```

新逻辑：

```python
stable_count = max(evidence.end_position) + 1
```

`end_position` 是正式线段真实几何终点；`confirmed_at_position` 是后续特征序列证据位置。后者保存在不可变的 `SegmentEvidence` 快照中，但不再冒充稳定笔。

这样同时满足：

- 正式线段几何前缀只增不减；
- 确认证据仍可完整审计；
- 证据尾笔发生共享端点迁移时，候选尾部可以重新计算；
- 正式结构不会因旧端点丢失而永久停更。

## 2. 校验器区分“正式几何稳定”与“确认事件证据”

`COMMITTED` 账本校验现在要求：

```text
segment.end_position < stable_stroke_count
```

而不再错误要求：

```text
segment.confirmed_at_position < stable_stroke_count
```

一次性 `DETECTED` 校验仍会拒绝直接依赖可回撤最后一笔的候选线段，原有安全约束没有被关闭。

## 3. 买卖点公开接口强制正式提交证据

`detect_trading_points()` 不再在缺少 `SegmentEvidence.committed_at` 时回退到：

- 确认笔端点时间；
- 线段结构端点时间。

调用方必须提供以下任一种完整证据：

```python
segment_evidence=[...]
```

或：

```python
segment_commit_times={segment_index: committed_at}
```

缺少任一输入线段的正式提交时间时，接口返回零正式买卖点并产生：

```text
FORMAL_SEGMENT_COMMIT_EVIDENCE_MISSING
```

提交时间早于线段结构可用时间则直接拒绝。

## 4. 锚点后 1～2 笔不再误报尾部未扫描

`validate_feature_sequence_coverage()` 新增 `scan_start_position`。当锚点后只剩 1～2 笔时，这属于标准特征序列正常的未完成尾部，不再按整条历史笔链长度误报：

```text
FEATURE_SEQUENCE_EMPTY_FOR_LONG_CHAIN
FEATURE_SEQUENCE_TAIL_NOT_SCANNED
```

## 5. 新增活性验证

命令：

```bash
PYTHONPATH=src python scripts/validate_structure_liveness.py --seeds 1000 --bars 300
```

结果：

```text
随机种子：1000
每个种子：300 根 K
发生共享端点迁移的种子：252
稳定锚点丢失：0
稳定笔或正式线段非前缀变化：0
正式结构提交滞后：0
失败：0
```

两个在 v0.10.14 中可确定性冻结的压力种子也加入回归测试：

```text
seed 159：旧版最终停在 9 笔 / 1 段；新版继续推进到 47 笔 / 5 段
seed 188：旧版最终停在 15 笔 / 1 段；新版继续推进到 60 笔 / 5 段
```

## 6. 回归结果

```text
全量测试：117 passed, 1 skipped
5000 根 DEMO 候选笔回撤：175
稳定笔回撤：0
正式线段回撤：0
正式笔中枢消失或右边界缩回：0
正式线段中枢消失或右边界缩回：0
正式线段账本校验问题：0
提交时间缺失/倒序/首次提交不一致：0
一买专项随机差分：1000 组，差异 0
```

5000 根 DEMO 最终结构边界：

```text
detected_strokes：338
stable_strokes：328
provisional_strokes：10
formal segments：56
provisional segments：1
```
