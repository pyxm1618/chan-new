# 当前验证说明

**适用基线：v0.11.0**

本文只描述当前代码应该如何验证，以及哪些不变量必须成立。历史失败样本、TDD 红绿过程和旧版本测试数字保留在 Git commit 与 Pull Request 历史中。

## 1. 基础测试

```bash
PYTHONPATH=src pytest -q
```

正式合并门槛是 GitHub Actions Python 3.10、3.11、3.12、3.13 全矩阵通过。任何代码逻辑变更都必须使用当前 head 重新验证，不能沿用旧版本的成功结果。

未安装可选 `czsc` 包时，参考差分测试可以显示为 skipped；这不代表生产算法失败。

## 2. v0.11.0 单级别买卖点专项契约

当前生产买卖点必须严格使用单级别输入：

```text
正式线段
+ 正式线段中枢
+ 同级价格关系
+ 同级精确 MACD
+ 正式提交时间/结构身份
→ B1/B2/B3、S1/S2/S3
```

禁止把当前周期线段内部的 `segment.strokes` 当作真实低级别数据。真实跨周期递归属于后续独立模式。

专项自动化测试必须覆盖：

- 每条正式线段只有一笔时，合法的 B1 / B2 与 S1 / S2 仍能成立；
- 改变线段内部笔细节但不改变正式线段几何时，单级别点不应因此改变；
- 少于两个线段中枢不能形成 B1 / S1；
- B1 / S1 缺少精确 MACD 历史时只能保留候选，不能成为正式点；
- B2 / S2 必须有前置正式 B1 / S1；
- B2 第一次回试跌破 B1 低点必须拒绝，S2 镜像；
- B3 / S3 的第一次回试允许准确触碰 `ZG/ZD` 边界，但不能重新进入中枢；
- 缺少任一正式线段提交证据时正式交易点接口 fail closed；
- 对外 API 与 `analyze_bars` 的生产运行时必须使用单级别 detector。

### B1 / S1 不变量

B1 至少满足：

1. 两个连续正式线段中枢形成严格向下趋势关系；
2. 同级连接段 `b` 与最终离开段 `c` 均向下；
3. `c` 创出本次趋势新低；
4. MACD 状态精确；
5. `c` 的负柱面积小于 `b` 的负柱面积；
6. `confirmed_at_dt` 不得早于 `c` 正式进入账本的时刻。

S1 完全镜像。当前版本不要求 `c` 内部出现笔级三买/三卖，也不要求内部至少两个笔中枢。

### B2 / S2 不变量

B2 必须由正式 B1 派生：B1 后第一条正式线段为反弹，紧随其后的第一条反向回试线段终点不得跌破 B1 低点。S2 镜像。当前版本不要求回试线段内部存在笔级 B1/S1。

### B3 / S3 不变量

B3：正式线段向上离开固定线段中枢后，紧随其后的第一条向下回试线段最低点满足 `low >= ZG`。S3 镜像要求 `high <= ZD`。边界触碰允许。

## 3. 当前专项验证入口

| 脚本 | 目的 |
|---|---|
| `scripts/validate_structure_stability.py` | 验证右边界候选变化不会让稳定笔、正式线段和正式中枢回撤 |
| `scripts/validate_window_stability.py` | 验证有限窗口左边界 fail-closed，以及 `StructureAnchor` 恢复后的结构一致性 |
| `scripts/validate_segment_commits.py` | 验证正式线段提交账本、`committed_at` 和逐根首次可知时间 |
| `scripts/validate_feature_tail_coverage.py` | 验证标准特征序列扫描覆盖尾部 |
| `scripts/validate_structure_liveness.py` | 验证共享端点迁移后正式结构仍能继续推进 |
| `scripts/validate_identity_safety.py` | 验证 symbol / interval / fingerprint / MACD anchor / SegmentEvidence 身份绑定 |
| `scripts/validate_first_buy_logic.py` | 历史严格一类点实现的回归材料；不再作为 v0.11.0 单级别生产语义的唯一判定来源 |
| `scripts/export_trading_point_regression.py` | 导出交易点历史回归材料 |

## 4. K 线输入不变量

正式分析使用的原始 K 线至少必须满足：

- `open_time` 严格递增；
- 不允许重复 `open_time`；
- 周期字符串必须受支持，即使输入只有一根 K 线也要校验；
- 固定周期相邻 K 线必须连续；
- 单根 K 的 `close_time` 不得越过该周期下一根 `open_time`；
- 已收盘历史与当前未收盘 K 必须分层。

任何不能证明精确连续性的输入，都不能继续生成或维持精确 MACD 状态。

## 5. 左边界不变量

有限历史窗口不能自行证明绝对线段相位。无真实历史起点声明、无持久化 `StructureAnchor` 时必须满足：

```python
result.segments == ()
result.central_zones == ()
result.segment_central_zones == ()
result.trading_points == ()
result.unresolved_prefix_segments == result.detected_segments
```

持久化锚点必须精确匹配当前笔链端点；匹配失败必须 fail closed。

## 6. 右边界与正式提交不变量

候选层可以随新 K 迁移、替换或撤销；正式层保持只追加语义：

```text
stable_strokes：不能回撤
segments：不能回撤
正式笔中枢：不能消失或缩回右边界
正式线段中枢：不能消失或缩回右边界
```

`stable_strokes` 只封存正式线段真实几何所需要的稳定前缀，不能把仍可能迁移的后续确认证据笔一起冻结。

## 7. 正式提交时间与身份不变量

每条正式线段必须具有真实：

```text
committed_at
committed_at_bar_position
segment_fingerprint
```

交易点的 `confirmed_at_dt` 必须来自全部必要结构真正可用后的正式提交时刻，不能使用线段端点时间、特征分型时间或调用方任意补写时间兜底。

外部提交时间映射必须以 `Segment.fingerprint` 为键。缺失、错配或身份冲突时正式买卖点必须停止输出。

## 8. MACD 锚点不变量

`MacdAnchor` 必须绑定正确的：

- `symbol`；
- `interval`；
- `last_open_time`；
- `last_close_time`；
- `expected_next_open_time`；
- `last_bar_fingerprint`；
- 历史起点和累计处理状态；
- `exact` 标志。

消费锚点时必须重新计算 `next_open_time(last_open_time, interval)` 并与持久化 `expected_next_open_time` 完全一致；`last_close_time` 不得越过下一周期起点。

## 9. 批量、增量与未来函数

相同已收盘数据和相同锚点状态下：

```text
analyze_bars(batch)
== FractalEngine.extend(batch)
```

正式交易点至少要在 `(point_type, dt, price, segment_index, confirmed_at_dt)` 上一致。

任何点都不能依赖其确认线段之后才出现的数据；后续数据允许产生新点，但不能把历史点的 `confirmed_at_dt` 提前。

## 10. 回归产物与维护规则

`artifacts/` 中的历史版本号表示样本冻结时的版本，不是当前运行版本。判断当前系统状态时优先级为：

```text
当前 main 代码与 pyproject.toml
> 当前 README / VALIDATION
> 当前 CI
> CHANGELOG
> 历史 artifacts / Git commit / 已关闭 PR
```

以后版本升级时：

1. `pyproject.toml` 是代码版本事实来源；
2. `README.md` 只描述当前状态；
3. `CHANGELOG.md` 追加历史摘要；
4. `VALIDATION.md` 只保留当前仍适用的验证入口和不变量；
5. TDD red/green 过程保存在 PR/commit；
6. 任何代码逻辑变更都要使用最终 head 重新运行完整测试矩阵后再合并。
