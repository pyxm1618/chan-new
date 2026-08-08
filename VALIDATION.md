# 当前验证说明

**适用基线：v0.10.17**

本文只描述当前代码应该如何验证，以及哪些不变量必须成立。历史版本的测试数字、失败样本和逐次修复过程不再混入当前验证文档；需要追溯时请查看 `CHANGELOG.md`、Git commit 和已关闭 Pull Request。

## 1. 基础测试

```bash
PYTHONPATH=src pytest -q
```

v0.10.17 合并前的最终 GitHub Actions 结果：

```text
129 passed, 1 skipped
Python 3.10: passed
Python 3.11: passed
Python 3.12: passed
Python 3.13: passed
```

跳过项是未安装可选 `czsc` 包时的参考差分测试，不代表生产算法失败。

文档修改本身不改变算法结果。后续代码变更必须重新运行测试，不能长期沿用上述数字作为“永远有效”的证明。

## 2. 当前专项验证入口

| 脚本 | 目的 |
|---|---|
| `scripts/validate_structure_stability.py` | 验证右边界候选变化不会让稳定笔、正式线段和正式中枢回撤 |
| `scripts/validate_window_stability.py` | 验证有限窗口左边界 fail-closed，以及 `StructureAnchor` 恢复后的结构一致性 |
| `scripts/validate_segment_commits.py` | 验证正式线段提交账本、`committed_at` 和逐根首次可知时间 |
| `scripts/validate_feature_tail_coverage.py` | 验证标准特征序列扫描覆盖尾部，避免漏扫或误报 |
| `scripts/validate_structure_liveness.py` | 验证共享端点迁移后正式结构仍能继续推进，不发生永久停更 |
| `scripts/validate_identity_safety.py` | 验证 symbol / interval / fingerprint / MACD anchor / SegmentEvidence 身份绑定 |
| `scripts/validate_first_buy_logic.py` | 验证严格一类买卖点、MACD 方向面积、锚点和确定性差分 |
| `scripts/export_trading_point_regression.py` | 导出六类买卖点确定性回归材料 |
| `scripts/export_live_data_regression.py` | 生成 5000 根 DEMO 全流程回归材料 |

常用组合：

```bash
PYTHONPATH=src pytest -q
PYTHONPATH=src python scripts/validate_structure_stability.py --bars 5000
PYTHONPATH=src python scripts/validate_window_stability.py --bars 5000
PYTHONPATH=src python scripts/validate_segment_commits.py --bars 5000
PYTHONPATH=src python scripts/validate_feature_tail_coverage.py
PYTHONPATH=src python scripts/validate_structure_liveness.py --seeds 1000 --bars 300
PYTHONPATH=src python scripts/validate_identity_safety.py
PYTHONPATH=src python scripts/validate_first_buy_logic.py --demo-bars 5000 --real-bars 500 --random-cases 1000
```

## 3. K 线输入不变量

正式分析使用的原始 K 线至少必须满足：

- `open_time` 严格递增；
- 不允许重复 `open_time`；
- 周期字符串必须受支持，即使输入只有一根 K 线也要校验；
- 固定周期相邻 K 线必须连续，不能用断档数据维持 `exact=True`；
- 单根 K 的 `close_time` 不得越过该周期的下一根 `open_time`；
- 已收盘历史与当前未收盘 K 必须分层，当前 K 不得进入正式结构计算。

任何不能证明精确连续性的输入，都不能继续生成或维持精确 MACD 状态。

## 4. 左边界不变量

有限历史窗口不能自行证明绝对线段相位。

无真实历史起点声明、无持久化 `StructureAnchor` 时必须满足：

```python
result.segments == ()
result.central_zones == ()
result.segment_central_zones == ()
result.trading_points == ()
result.unresolved_prefix_segments == result.detected_segments
```

允许计算候选层，但不允许把候选层提升为正式结构。

持久化锚点恢复时：

- 锚点必须精确匹配当前笔链端点；
- 匹配失败必须 fail closed；
- 恢复后的正式线段必须与完整历史参考结果保持一致的后缀关系；
- 正式中枢不得凭窗口内部数据重新猜测跨窗口边界。

## 5. 右边界与正式提交不变量

候选层可以随新 K 到来而迁移、替换或撤销；正式层必须保持只追加语义。

必须持续验证：

```text
stable_strokes：不能回撤
segments：不能回撤
正式笔中枢：不能消失或缩回右边界
正式线段中枢：不能消失或缩回右边界
```

`SegmentEvidence` 中的确认事件证据和 `segments` 中的正式几何不是同一概念。`stable_strokes` 只封存正式线段几何所需要的稳定前缀，不能把仍可能迁移的后续确认证据笔错误封存进去。

## 6. 正式提交时间不变量

交易点的实时可知时间必须来自正式账本实际提交时刻，而不是：

- 线段端点时间；
- 特征分型时间；
- 确认笔自身端点时间；
- 调用方任意补写的时间。

每条正式线段必须保留：

```text
committed_at
committed_at_bar_position
```

并满足：

- 不缺失；
- 随正式账本单调推进；
- 不早于所需结构证据真正可用的时间；
- 与逐根重放中第一次进入正式账本的时刻一致。

## 7. MACD 锚点不变量

`MacdAnchor` 必须绑定正确的：

- `symbol`；
- `interval`；
- `last_open_time`；
- `last_close_time`；
- `expected_next_open_time`；
- `last_bar_fingerprint`；
- 历史起点和累计处理状态；
- `exact` 标志。

消费锚点时必须重新计算：

```text
next_open_time(last_open_time, interval)
```

并要求它等于持久化的 `expected_next_open_time`。同时 `last_close_time` 不得越过该下一周期起点。

品种、周期、时间游标、内容指纹、内部连续性任一不匹配，正式一类点必须安全关闭。

## 8. 买卖点验证边界

当前代码包含 B1 / B2 / B3 与 S1 / S2 / S3。

正式交易点至少必须满足：

- 来源结构已经进入正式账本；
- 所需 `SegmentEvidence` 身份与目标线段完全一致；
- `confirmed_at_dt` 不早于全部必要证据的真实可用时间；
- 窗口缺少精确结构或 MACD 锚点时不发布正式点；
- 候选点与正式点不能混用。

一类点专项还需要验证趋势关系、`a+A+b+B+c` 分解、方向一致的 MACD 柱面积和严格背驰条件。

跨级别买点语义仍会继续开发，因此这里验证的是**当前实现的安全边界与可复现性**，不是宣称交易策略已经最终完成。

## 9. 回归产物如何理解

`artifacts/` 中保留三类材料：

- `artifacts/regression/`：确定性 bug 复现和算法回归；
- `artifacts/validation/`：某次专项验证冻结的结果；
- `artifacts/real/`：真实市场快照和参考对比。

其中部分文件名包含历史版本号，例如 `v0.10.12`、`v0.10.15`、`v0.10.16`。这些是**历史测试夹具/快照名称**，不是当前版本声明。

判断当前系统状态时，优先级为：

```text
当前 main 代码与 pyproject.toml
> 当前 README / VALIDATION
> 当前 CI
> CHANGELOG
> 历史 artifacts / Git commit / 已关闭 PR
```

不要根据单个旧 artifact 或旧测试数字推断当前代码行为。

## 10. 文档与验证维护规则

以后版本升级时：

1. `pyproject.toml` 的版本号是代码版本事实来源；
2. `README.md` 只描述当前状态，不继续堆叠逐版本修复日志；
3. `CHANGELOG.md` 追加历史摘要；
4. `VALIDATION.md` 只保留当前仍适用的验证入口和不变量；
5. 历史失败数字、TDD red/green 过程放在 PR 或 commit 中，不再新增根目录 `RELEASE_NOTES_vX.Y.Z.md`；
6. 任何代码逻辑变更都要重新跑对应测试和专项验证后再合并。
