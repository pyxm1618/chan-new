# v0.10.17 — K 线连续性与 MACD 锚点完整性加固

本版本基于 v0.10.16 的结构身份、正式提交证据和 MACD 状态绑定继续做安全审计，修复四个会让“不精确输入”被错误提升为精确 MACD 状态的边界问题。

## 修复内容

1. **单根 K 线也必须校验周期是否合法**
   - 旧实现只在相邻 K 线之间计算下一根开盘时间，因此单根 `90s` 等不支持周期可能被误报为 `continuous=True`。
   - 现在每根输入 K 都会先经过周期解析；不支持周期直接返回非连续状态。

2. **K 线收盘时间不得越过下一周期起点**
   - 旧实现只检查 `open_time` 网格，未约束 `close_time`。
   - 现在任一 K 的 `close_time > next_open_time(open_time, interval)` 都会被判定为非精确流，不能生成正式 `MacdAnchor`。

3. **持久化 `MacdAnchor` 的下一根游标必须可由自身状态唯一推导**
   - 不再只相信锚点自报的 `expected_next_open_time`。
   - 消费锚点前重新计算 `next_open_time(last_open_time, interval)`；二者不一致立即拒绝。

4. **持久化 `MacdAnchor` 的上一根收盘时间不能越过下一周期起点**
   - 防止内部时间游标自相矛盾但仍携带 `exact=True` 的锚点进入生产识别或独立参考复算。
   - 生产 `trading_points.py` 与独立 `trading_point_reference.py` 使用同一组不变量。

## 回归测试与 TDD 证据

本次新增 `tests/test_bar_stream_safety.py`，按 red → green 验证：

- 第一轮：新增单根非法周期与越界收盘时间反例后，旧实现为 `2 failed / 123 passed / 1 skipped`。
- 锚点下一根游标反例：旧实现为 `1 failed / 125 passed / 1 skipped`。
- 锚点游标 + 收盘时间两个内部自洽性反例：旧实现为 `2 failed / 125 passed / 1 skipped`。
- 独立参考复算器加入同样反例后：旧实现为 `2 failed / 127 passed / 1 skipped`。
- 完成生产与参考实现修复后：`129 passed / 1 skipped`；GitHub Actions Python 3.10、3.11、3.12、3.13 矩阵全部通过。

## 影响范围

本版本不修改一买/二买/三买、一卖/二卖/三卖的结构判定公式，不修改线段或中枢算法；变更集中在原始 K 线连续性和持久化 MACD 状态的输入边界，目标是继续保持正式信号 fail-closed。
