# CZSC 结构监控项目 · 5000 根实时数据版 v0.10.11

## v0.10.11 左边界锚定：根治“窗口首段错位”

v0.10.10 已经解决右侧新 K 导致正式结构回撤，但有限历史窗口仍存在另一类问题：
程序无法仅凭窗口内部数据证明第一条线段的绝对相位。任意把历史从中间裁开，
都可能得到一个几何上自洽、但相对完整历史起点错误的首段；笔中枢和线段中枢
会继续继承这个错误。

v0.10.11 改为**默认安全关闭（fail closed）**：

```text
没有真实历史起点声明，也没有持久化结构锚点
    -> all_strokes / detected_segments 继续计算并展示
    -> 全部检测线段进入 unresolved_prefix_segments 候选层
    -> segments / central_zones / segment_central_zones / trading_points 为空
```

这不是“少算一条首段”，而是承认有限窗口本身无法恢复绝对线段相位。正式结构
只有在以下两种情况下才允许输出：

1. 调用方能证明输入从真实历史起点开始，显式传入 `left_boundary_anchored=True`；
2. 调用方从持久化历史加载一个已经确认的线段端点 `StructureAnchor`。

### API 示例

真实历史起点：

```python
result = analyze_bars(
    bars,
    left_boundary_anchored=True,
)
```

普通最近 N 根窗口：

```python
result = analyze_bars(bars)
assert result.segments == ()
assert result.unresolved_prefix_segments == result.detected_segments
```

从持久化线段端点继续：

```python
from chan_monitor import StructureAnchor, analyze_bars

anchor = StructureAnchor(
    dt=last_committed_segment.end_dt,
    value=last_committed_segment.end_value,
    mark=last_committed_segment.fx_b.mark,
)
result = analyze_bars(recent_bars, left_anchor=anchor)
```

`StructureAnchor` 必须能在当前笔链端点中精确匹配。找不到时不会猜测替代起点，
而是继续保持正式结构为空。端点锚点只恢复线段相位；由于当前版本没有持久化
“进行中的中枢”状态，锚点之后的第一个笔中枢分组和第一个线段中枢仍会保守地
留在候选层，避免把跨窗口中枢误报为正式中枢。

### 四层结构语义

```text
all_strokes             当前完整笔链，可能包含右侧可回撤尾部
stable_strokes          仅解决右边界回撤的封存前缀
resolved_strokes        同时通过右侧稳定性与左侧锚定的正式笔序列
provisional_strokes     右侧仍可迁移或撤销的尾部

detected_segments       当前窗口直接识别结果，仅作候选/审计
unresolved_prefix_segments  左边界未解析的候选线段
segments                有可信左锚点且通过右侧两阶段提交的正式线段
provisional_segments    左边界已解析后的右侧候选尾段
```

Streamlit 页面新增“确认数据从真实历史起点开始”开关，默认关闭。Binance 最近
5000 根、任意 CSV 截断窗口默认都不会发布正式线段/中枢/买卖点；只有用户明确
确认数据起点可信时才启用正式层。生产系统更推荐传入持久化 `StructureAnchor`。

### 验证

```bash
PYTHONPATH=src pytest
PYTHONPATH=src python scripts/validate_structure_stability.py --bars 5000
PYTHONPATH=src python scripts/validate_window_stability.py --bars 5000
```

验证结果：

```text
完整测试：101 passed, 1 skipped
右边界逐根扫描：5000 根，候选笔回撤 175 次，正式层异常 0
左边界窗口扫描：19 个无锚点窗口，错误正式输出 0
持久化锚点扫描：20 个窗口，线段后缀/中枢子序列错误 0
锚点已被裁掉：1 个窗口，正确 fail closed
```

## 历史：v0.10.10 稳定结构状态机（只解决右边界回撤）

v0.10.9-fixed 采用 `strokes[:-1]` 隔离最后一笔，只能把反例向后推迟，
不能证明剩余笔是稳定前缀。v0.10.10 删除了固定尾部窗口，改为显式维护
结构状态与只追加的正式账本。

### 结构分层

```text
detected_strokes     原始笔状态机当前直接输出，允许级联回退，仅用于审计
all_strokes          当前接受的完整笔链 = stable_strokes + provisional_strokes
stable_strokes       已被后续结构确认事件封存，只增不减
provisional_strokes  仍可能迁移、替换或撤销的连续尾部

detected_segments    当前完整笔链上的直接线段识别结果，允许尾部变化
segments             COMMITTED 正式线段，只追加
provisional_segments 已识别但尚未提交的尾部线段
```

正式线段采用两阶段提交：

```text
DETECTED
   │ 后续又识别出一条线段
   ▼
COMMITTED
```

也就是当前最后一条已检测线段始终保留为候选；只有下一条线段出现后，前一条
线段及其确认所依赖的笔前缀才进入正式账本。这里没有 `[:-1]`、`[:-2]` 或
任何固定安全距离。

### 下游消费规则

```text
正式笔中枢       <- stable_strokes
候选笔中枢       <- all_strokes
正式线段中枢     <- segments
候选线段中枢     <- detected_segments
正式买卖点       <- stable_strokes + segments + 正式中枢
```

图表也按同一语义绘制：稳定笔和正式线段为实线；`provisional_strokes` 与
`provisional_segments` 为同色虚线。即使所有 K 都已收盘，尚未提交的结构尾部
也不会再冒充正式结构。

### 逐根前缀验证

项目新增 `StructureState` 和：

```bash
PYTHONPATH=src python scripts/validate_structure_stability.py --bars 5000
```

同一批确定性 DEMO 数据的结果：

```text
扫描原始 K：5000
原始笔状态机候选回退：175 次（允许，只发生在 provisional 层）
最终 detected_strokes：338
最终 all_strokes：338
最终 stable_strokes：330
最终 provisional_strokes：8
最终正式线段：56
最终候选线段：1

稳定笔前缀回撤：0
正式线段回撤：0
正式笔中枢消失：0
正式笔中枢右边界缩回：0
正式线段中枢消失：0
正式线段中枢右边界缩回：0
```

专项回归覆盖：

```text
125 -> 126
175 -> 176
235 -> 236
378 -> 379
403 -> 404
633 -> 634
810 -> 811
990 -> 991
```

这些位置允许 `detected_strokes`、候选线段和候选中枢变化，但要求：

```python
previous_stable_strokes == current_stable_strokes[:len(previous_stable_strokes)]
previous_confirmed_segments == current_confirmed_segments[:len(previous_confirmed_segments)]
```

两项断言在 1000 / 5000 根逐根扫描中均为零异常。

## 本版本完成的内容

### 1. 5 分钟历史深度扩大到 5000 根

Streamlit 默认配置已经改为：

```text
数据源：Binance
交易对：BTCUSDT
周期：5m
已收盘历史：5000 根
实时未收盘：最多 1 根
```

Binance REST 单次请求有上限，因此首次加载会自动向前分页、去重、排序并统一判断收盘状态：

- 现货每页最多请求 1000 根；
- U 本位合约每页最多请求 1500 根；
- 最终精确保留最近 5000 根已收盘 K；
- 另行读取当前可能尚未收盘的 K；
- 5000 根历史和当前 K 不混在同一个确认层中。

官方接口：

- Spot Kline：<https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data>
- USD-M Kline：<https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data>

### 2. 周期自适应刷新

UI 使用 **增量 REST 轮询**。首次加载完整 5000 根，之后只读取尾部可能新增或修订的 K，不会每次重新下载全部历史。

推荐刷新间隔：

| K 线周期 | UI 刷新间隔 |
|---|---:|
| 1m | 10 秒 |
| 3m | 20 秒 |
| 5m | 30 秒 |
| 15m | 60 秒 |
| 30m | 90 秒 |
| 1h | 120 秒 |
| 2h | 180 秒 |
| 4h / 6h / 8h / 12h | 300 秒 |
| 1d | 600 秒 |
| 3d | 900 秒 |
| 1w / 1M | 1800 秒 |

这不是交易所推送频率。Binance 现货非 1 秒 Kline WebSocket 的更新速度约为 2 秒；UI 没有必要按每个推送做一次全结构重算，所以采用更慢、按周期分级的重绘频率。Streamlit 使用 `st.fragment(run_every=...)` 驱动自动刷新。

相关官方文档：

- Binance Spot Kline Stream：<https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#klinecandlestick-streams-for-utc>
- Streamlit fragments：<https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment>

刷新过程具备以下保护：

- 只拉取尾部窗口；
- 当前 K 更新时复用已确认分析结果；
- 新 K 收盘时才重算确认结构；
- 页面暂停过久、超过整个历史窗口时，自动重新拉取干净的 5000 根；
- 请求失败时保留上一份完整快照，不让半截数据进入分析；
- 对 429 / 418 / 5xx 做退避重试，并遵守 `Retry-After`。

### 3. 已确认和未确认结构分层

数据层同时维护两套分析：

```text
confirmed
只使用 5000 根已收盘 K
内部仍拆成 stable / provisional；正式下游只消费 stable 与 COMMITTED 结构

live
使用已收盘 K + 当前未收盘 K
只用于展示尾部可能怎样变化
```

因此当前 K 永远不会污染正式结构。

图形约定：

- 稳定笔与正式线段使用实线；
- 未确认笔与未确认线段使用相同颜色、相同粗细的虚线；
- 默认笔线宽降为 `1.1`，默认线段线宽降为 `2.2`，减少对 K 线的遮挡；
- 未收盘 K 使用可配置的半透明时间带；
- 虚线悬停会显示“为什么尚未确认”和来源笔序号。

侧边栏的“图层样式：颜色 / 粗细”支持配置所有非 K 线图层：

- 笔：颜色、线宽、端点大小；
- 线段：颜色、线宽、端点大小；
- 笔中枢与线段中枢：边框颜色、边框粗细、中轴标记大小、填充透明度；
- 顶分型与底分型：颜色、标记大小、边框粗细；
- B1/B2/B3 与 S1/S2/S3：每类独立颜色和标记大小，共用可配置边框粗细；
- 实时未收盘 K 背景：颜色和填充透明度。

样式控件使用固定 Streamlit key，因此自动刷新和页面重跑不会重置用户选择；“恢复默认样式”可以一次还原。颜色和粗细只影响展示，不进入任何结构计算或买卖点判断。

鼠标悬停数据框也可以单独配置：

- “显示悬停数据框”可一键关闭所有 K 线与叠加图层的 hover 弹框；
- 可配置悬停背景颜色；
- 可配置背景不透明度，`0` 为完全透明，`1` 为完全不透明；
- 文字颜色根据背景亮度自动切换深色或浅色，避免深色背景下不可读；
- 这些设置同样只影响展示，不触发结构重算。

未确认笔连接到当前未完成无包含 K 区域中的最极端价；未确认线段连接到标准特征序列尚未确认区域中的候选极值。它们是**可迁移、可消失的候选结构**，不参与中枢和买卖点计算。

### 4. 5000 根图表可用性

全屏头部布局已经压缩，避免标题区占用过多纵向空间：

- 图表顶部边距由 `230px` 降为 `150px`；
- 数据来源信息由最多 12 行合并为 3～4 行；
- 标题、来源信息和状态条分别占用固定紧凑区域；
- Plotly 开启 `autosize`，在普通视图和全屏视图中重新利用可用宽度；
- 图例仍保留在主图顶部，不再被大面积空白向下挤压。

图表仍加载全部 5000 根，但首屏默认只显示最后 320 根：

- 触控板或滚轮缩放；
- 拖拽平移；
- 底部范围条浏览完整历史；
- 可分别开关分型、笔、线段、笔中枢、线段中枢和买卖点。

## 数据正确性保护

### K 线层

每次快照都会校验：

- 时间严格递增；
- open time 不重复；
- 周期一致；
- 相邻时间间隔不能小于所选周期；
- 已收盘窗口最多 5000 根；
- 当前 K 最多一根且必须晚于最后一根已收盘 K；
- 记录大于一个周期的时间缺口数。

### 结构层

5000 根完整流程会运行：

- 笔链方向、共享端点、最小长度及更极端端点验证；
- 标准特征序列线段独立参考实现差分；
- 线段方向、奇数笔数、共享端点和确认依据验证；
- 笔中枢和线段中枢边界、连续切片、最大延伸验证；
- 买卖点端点、级别证据、确认时间和中枢边界验证。

需要注意：本项目的笔状态机包含此前人工发现并修复的“共享端点迁移”逻辑，所以最终笔结果可能与冻结的旧 CZSC v0.9.69 状态机不同；去包含 K 和分型仍与该旧基线逐项比较，线段则使用独立标准特征序列实现复算。

## 确定性 5000 根回归产物

为了在没有网络时仍可复核完整流程，仓库内包含一批明确标注为 **DEMO / 模拟数据** 的 5000 根 5m 回归：

```text
已收盘 K：5000
当前 K：1
无包含 K：3721
分型：851
完整笔链：338
稳定笔：330
候选笔：8
正式线段：56
候选线段：1
正式笔中枢：基于 stable_strokes 计算
正式线段中枢：基于 segments 计算
最终端点发生迁移的线段：9
端点迁移事件：27
所有结构验证问题：0
标准特征序列线段差分：57 / 57 一致
确认依据差分：57 / 57 一致
特征元素：659
特征分型：88
特征序列尾部缺口：0
```

产物位于：

```text
artifacts/regression/live_5000_5m_demo_raw.html
artifacts/regression/live_5000_5m_demo_merged.html
artifacts/regression/live_5000_5m_demo_summary.json
artifacts/regression/live_5000_5m_demo_provisional_strokes.csv
artifacts/regression/live_5000_5m_demo_provisional_segments.csv
artifacts/regression/live_5000_5m_demo_hover_disabled.html
artifacts/regression/live_5000_5m_demo_hover_dark_transparent.html
artifacts/regression/gap_endpoint_lock_bug_summary.json
artifacts/regression/gap_no_gap_competition_bug_summary.json
artifacts/regression/gap_no_gap_competition_trace.csv
artifacts/regression/gap_endpoint_migrations.csv
artifacts/regression/gap_endpoint_303_migration_trace.csv
artifacts/regression/first_segment_boundary_regression.json
artifacts/regression/live_5000_5m_demo_unresolved_segment_prefix_strokes.csv
artifacts/regression/structure_stability_5000.json
```

这些文件仅用于算法和界面回归，不是真实市场行情。实际运行 Streamlit 时默认直接连接 Binance。

## 自动化测试

```text
95 passed, 1 skipped
```

覆盖新增内容：

- 现货 5000 根向前分页；
- 当前 K 排除与精确历史窗口；
- 增量尾部覆盖和去重；
- 页面长时间暂停后的完整重载；
- 当前 K 变化时复用确认结果；
- 新 K 收盘后确认层重算；
- 5000 根 5m 全结构确定性；
- 实线 / 虚线继承同一用户样式；
- 所有非 K 线图层的自定义颜色、线宽、边框、标记大小与中枢透明度；
- 原有分型、笔、线段、中枢、买卖点全部回归。

跳过项是未安装外部 `czsc` 包的可选兼容测试；项目内置独立参考实现均已运行。

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
pytest
streamlit run app.py
```

浏览器打开 Streamlit 提示的本地地址。默认会加载 `BTCUSDT / 5m / 5000 根`。

## 命令行下载

```bash
chan-structure fetch \
  --symbol BTCUSDT \
  --interval 5m \
  --limit 5000 \
  --market spot \
  --output artifacts/BTCUSDT_5m_5000.csv
```

## 重新生成 5000 根回归

```bash
PYTHONPATH=src python scripts/export_live_data_regression.py
```

## 当前阶段边界

- 当前 UI 是周期自适应的增量 REST 轮询，不是逐 tick 交易终端；
- 已经具备当前 K、确认结构和候选虚线的数据隔离；
- 还没有后台常驻进程、数据库、WebSocket 守护和飞书消息；
- 后续通知必须只使用已确认结构及 `confirmed_at_dt`，不能使用虚线候选。


## 历史方案：v0.10.9 最后一笔隔离（已被 v0.10.10 取代）

该版本曾尝试仅隔离当前最后一笔。这个策略不能构造稳定前缀，现仅保留为历史说明：

```text
segment_evidence.confirmed_at_position < len(strokes) - 1
```

若确认位置等于当前最后一笔，线段不会进入已确认集合，而是留在未完成线段区域，并由图表以同色虚线展示。纯特征序列单元测试仍可关闭该实时稳定策略，以便单独验证算法定义。

新增原始 K 前缀回归：235 根 K 时第 20 笔确认的候选线段不会画成实线；增加第 236 根 K 后该笔被撤销，前两条实线段保持完全不变。
