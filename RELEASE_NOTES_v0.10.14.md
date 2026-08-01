# v0.10.14 修复说明：严格一类买卖点与可复现 MACD 状态

v0.10.13 的线段、左右边界和提交时间已经稳定，但一买/一卖仍有三类基础错误：

1. 只用中枢核心区间 `ZG/ZD` 分离判断趋势，可能把更高级别中枢误判为趋势；
2. MACD 把正负柱全部取绝对值相加，下跌和上涨力度口径混杂；
3. EMA 从滚动窗口首价重新初始化，同一结构会随加载窗口改变信号。

v0.10.14 将正式一类点改为 fail-closed 的严格状态机。

## 正式一买条件

操作级别一买只有同时满足以下条件才进入 `trading_points`：

1. 已形成两个同级别、已完成的线段中枢；
2. 下跌趋势满足 `后 trend_GG < 前 trend_DD`；
3. `trend_GG/trend_DD` 只统计中枢盘整本体，不把最终离开线段 c 混入中枢范围；
4. 按 `a+A+b+B+c` 分解：A、B 是两个同级别中枢，b 是连接二者的向下走势，c 是 B 的最终向下离开走势；
5. c 内部已经出现“向下离开 B—回抽不回 B—继续向下”的次级别三卖，并至少包含两个次级别中枢；
6. c 创出从 b 开始的整个趋势新低；
7. 下跌只累计 MACD 负柱面积，并满足 `c负柱面积 < b负柱面积`；
8. MACD 必须由真实历史起点递推，或由持久化 `MacdAnchor` 精确恢复；
9. c 所在线段已经进入正式提交账本，通知时间使用真实 `committed_at`。

一卖按完全对称规则处理。

只有 `ZG/ZD` 核心区分离、但 `GG/DD` 波动区仍重叠时，输出 `REJECTED` 候选，
不再输出正式一类点。有限窗口没有精确 MACD 状态时输出 `PENDING`，不输出正式点。

## 中枢数据模型

`CentralZone` 和 `SegmentCentralZone` 新增：

```python
trend_strokes / trend_segments
trend_gg
trend_dd
departure_stroke / departure_segment
```

原有 `gg/dd` 保留用于完整切片审计；一类点趋势关系使用 `trend_gg/trend_dd`。
这是因为连续价格使最终离开单元在几何上仍与中枢区间相交，扫描器会把它保留在
中枢切片尾部，但理论 `a+A+b+B+c` 分解中该单元属于 b 或 c，而不是 A/B 中枢的盘整本体。

## 精确 MACD 状态

新增：

```python
MacdAnchor(
    asof,
    ema_fast,
    ema_slow,
    dea,
)

build_macd_anchor(raw_bars, anchor=None)
```

`analyze_bars()` 与 `FractalEngine` 新增 `macd_anchor` 参数；`AnalysisResult` 新增：

```python
macd_anchor
macd_final_anchor
```

滚动窗口必须同时恢复结构锚点和 MACD 锚点：

```python
result = analyze_bars(
    recent_bars,
    left_anchor=structure_anchor,
    macd_anchor=macd_anchor_before_recent_bars,
)
```

没有 `MacdAnchor` 的任意截断窗口不会生成正式一买/一卖。

## MACD 面积

```text
下跌：sum(-hist for hist < 0)
上涨：sum( hist for hist > 0)
```

不再使用 `sum(abs(hist))`。反向颜色柱体属于走势内部反弹/回撤，不计入当前方向力度。

## 验证

```bash
PYTHONPATH=src pytest -q
PYTHONPATH=src python scripts/validate_first_buy_logic.py \
  --demo-bars 5000 --real-bars 500 --random-cases 1000
PYTHONPATH=src python scripts/export_trading_point_regression.py
```

实际结果：

```text
pytest：113 tests，112 passed，1 skipped（可选 czsc 依赖未安装）
一买专项：4451 项检查，失败 0
随机独立差分：1000 组，正式一买样本 719，差异 0
校验器突变测试：伪造 MACD 面积、削弱 c 次级别结构，均被重新计算拦截
5000 根 Demo：55 次正式线段推进扫描，正式买卖点回撤 0
真实 BTCUSDT 500 根：校验问题 0，独立参考差异 0
确定性六类点回归：B1/B2/S1/S2/B3/S3 均正常，校验问题 0
```

5000 根 Demo 和当前 500 根真实快照没有满足全部严格条件的一类点，因此正例验证
由确定性 `a+A+b+B+c` 样本和 1000 组随机变体完成；真实数据用于验证无误报、无回撤和参考一致性。
