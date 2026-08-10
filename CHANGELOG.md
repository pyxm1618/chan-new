# Changelog

本文件记录对当前项目有长期意义的版本变化。它是**历史摘要**，不是当前系统说明；当前行为以 `main` 代码、`pyproject.toml`、`README.md` 和 `VALIDATION.md` 为准。

详细的修复过程、TDD 红绿记录、逐次审计证据和当时的测试输出保留在 Git commit 与 Pull Request 历史中，不再为每个补丁版本维护独立的根目录 `RELEASE_NOTES_vX.Y.Z.md`。

## v0.11.0 — 单级别线段中枢买卖点

- 正式生产买卖点明确采用**单级别**语义：只消费当前周期的正式线段、正式线段中枢、同级价格关系和同级 MACD 证据。
- B1 / S1：两个连续线段中枢必须满足严格同向趋势关系；比较同级连接段 `b` 与最终离开段 `c`，要求 `c` 创趋势新极值且同方向 MACD 柱面积小于 `b`。
- B2 / S2：必须先存在正式 B1 / S1；随后本级别反向段后的第一次回试不得破坏一类点极值。
- B3 / S3：保持“离开本级别线段中枢后，第一次反向回试不重新进入中枢”的规则，边界触碰允许。
- 删除生产 B1 / S1 对 `segment.strokes` 内部“三买/三卖 + 至少两个笔中枢”的依赖；删除生产 B2 / S2 对回试线段内部笔级 B1 / S1 的依赖。
- 当前周期内部的笔**不再被当作真实次级别**。真实 1m→5m 等递归确认留到后续独立阶段，并要求显式提供真实低级别分析结果。
- 保留 v0.10.17 已有的正式线段 `committed_at`、结构 fingerprint、K 线连续性和 `MacdAnchor` 完整性约束；证据不足继续 fail closed。

## v0.10.17 — K 线连续性与 MACD 锚点完整性

- 单根 K 线也强制校验周期是否合法。
- 拒绝 `close_time` 越过下一周期起点的 K 线。
- `MacdAnchor.expected_next_open_time` 必须能从 `last_open_time + interval` 重新推导。
- 拒绝 `last_close_time` 越过下一周期起点的持久化 MACD 锚点。
- 生产实现与独立参考实现采用相同的锚点完整性约束。
- 最终候选发布前测试：`129 passed, 1 skipped`，Python 3.10–3.13 GitHub Actions 矩阵通过。

## v0.10.16 — 身份绑定与正式证据闭环

- `MacdAnchor` 绑定 symbol、interval、时间游标、历史状态和上一根 K 指纹。
- `SegmentEvidence` 绑定线段 symbol、interval、结构 fingerprint 和确认快照。
- 外部线段提交时间映射改为使用 `Segment.fingerprint`，拒绝不安全的整数索引键。
- `validate_trading_points()` 可以从正式证据重新校验交易点确认时间。
- 修复空正式线段链、确认尾笔迁移和短尾特征覆盖等审计边界问题。

## v0.10.15 — 正式结构活性与提交边界

- `stable_strokes` 只封存正式线段真实几何，不再把仍可能迁移的确认证据笔错误封存。
- 正式买卖点接口强制要求完整的正式提交时间证据。
- 修复锚点后 1–2 笔短尾被误报为未扫描的问题。
- 增加随机种子结构活性压力验证，防止共享端点迁移导致正式结构永久停更。

## v0.10.14 — 严格一类买卖点与可复现 MACD

- 一类买卖点采用更严格的同级中枢趋势关系和 `a+A+b+B+c` 结构约束。
- 下跌只比较 MACD 负柱面积，上涨只比较正柱面积。
- 引入持久化 `MacdAnchor`，避免滚动窗口从窗口首价重新初始化 EMA 后产生窗口依赖信号。
- 缺少精确 MACD 历史时正式一类点 fail closed。

## v0.10.13 — 特征序列尾部覆盖

- 锚点模式在最后一个尚未形成完整线段的扫描区间也保留特征元素、特征分型与诊断。
- 消除正常未完成尾部被错误报告为 `FEATURE_SEQUENCE_TAIL_NOT_SCANNED` 的问题。

## v0.10.12 — 正式账本校验与真实提交时间

- 区分直接检测结果 `DETECTED` 与正式提交账本 `COMMITTED` 的校验语义。
- `SegmentEvidence` 增加 `committed_at` 和 `committed_at_bar_position`。
- 交易点确认时间开始优先使用结构真正进入正式账本的时刻，而不是结构端点时间。

## v0.10.11 — 左边界 fail-closed

- 明确有限窗口不能自行恢复绝对线段相位。
- 无真实历史起点声明、无 `StructureAnchor` 时，只输出候选层，不发布正式线段、中枢和买卖点。
- 增加持久化 `StructureAnchor` 恢复机制与左右边界窗口验证。

## v0.10.10 — 稳定结构状态机

- 删除依赖 `strokes[:-1]` 等固定裁尾策略的“伪稳定前缀”。
- 引入 `StructureState`，明确 `detected / stable / provisional` 三层结构。
- 正式线段改为两阶段 `DETECTED → COMMITTED` 提交。
- 正式笔中枢和正式线段中枢只消费稳定/正式结构。

## 更早版本

v0.10.9 及更早版本属于当前状态机与证据体系形成前的迭代阶段。需要追溯具体实现时请使用 Git 历史；这些旧方案不应被当作当前算法语义。
