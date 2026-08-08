# CZSC 结构监控项目

**当前基线：v0.10.17**

这是一个面向 Binance K 线的 CZSC（缠论结构）监控与验证项目。主流程覆盖：

```text
原始 K 线
→ 去包含
→ 分型
→ 笔
→ 标准特征序列线段
→ 笔中枢 / 线段中枢
→ B1 / B2 / B3 与 S1 / S2 / S3
→ 候选层与正式层分离
```

当前版本的核心目标不是“尽可能多报信号”，而是让正式结构和正式买卖点具备可审计、可复现、不会因窗口或尾部变化而被提前确认的证据链。

## 当前状态

v0.10.17 在 v0.10.16 的结构身份绑定和正式证据闭环基础上，进一步收紧原始 K 线连续性与持久化 MACD 锚点完整性：

- 单根 K 线也必须通过周期合法性校验；
- K 线 `close_time` 不得越过下一周期起点；
- `MacdAnchor.expected_next_open_time` 必须能够由自身 `last_open_time + interval` 唯一推导；
- `MacdAnchor.last_close_time` 不得越过下一周期起点；
- 生产实现与独立参考实现使用同一组锚点不变量；
- `SegmentEvidence`、正式提交时间和结构指纹保持强绑定；
- 正式买卖点在证据不足时继续采用 **fail closed**：保留候选或拒绝，不提升为正式信号。

版本历史统一记录在 [`CHANGELOG.md`](CHANGELOG.md)。逐版本 `RELEASE_NOTES_v0.10.xx.md` 已移除，避免历史修复说明被误读为当前系统文档。

## 正式层与候选层

项目明确区分“当前检测结果”和“可以被下游消费的正式结果”。

```text
detected_strokes          当前笔检测结果，允许尾部变化
all_strokes               当前接受的完整笔链
stable_strokes            已封存、只增不减的稳定笔前缀
provisional_strokes       仍可能迁移或撤销的尾部笔

detected_segments         当前窗口直接识别出的线段
unresolved_prefix_segments 左边界尚未解析时的候选线段
segments                  已正式提交的线段账本
provisional_segments      尚未提交的右侧候选线段
```

正式下游只消费具有可信左边界、稳定右边界和完整提交证据的结构。

### 左边界

任意有限历史窗口本身不能证明绝对线段相位。因此默认：

```text
没有真实历史起点声明，也没有持久化 StructureAnchor
→ 可以计算候选笔和候选线段
→ 不发布正式线段、中枢和买卖点
```

调用方只有在能够证明数据从真实历史起点开始时，才应显式使用：

```python
result = analyze_bars(
    bars,
    left_boundary_anchored=True,
)
```

生产滚动窗口更推荐恢复持久化 `StructureAnchor`。

### 右边界

正式线段采用两阶段提交：

```text
DETECTED
   │ 后续结构提供足够确认
   ▼
COMMITTED
```

当前最后一条已检测线段可以继续变化；只有进入 `segments` 的正式线段才允许被正式中枢、交易点、通知和回测消费。

## MACD 状态与身份绑定

滚动窗口不能从窗口首价重新初始化 EMA 后再把结果当作精确历史。正式一类点需要：

- 从真实历史起点递推 MACD；或
- 使用可以精确连接当前窗口的持久化 `MacdAnchor`。

锚点会绑定：

- `symbol`；
- `interval`；
- 上一根 K 的时间游标；
- 上一根 K 的内容指纹；
- 历史起点和累计处理数量；
- `exact` 状态。

品种、周期、时间连续性或内容身份任一不匹配时，正式信号不会继续沿用该锚点。

## 买卖点状态

代码当前已经包含：

- B1 / S1；
- B2 / S2；
- B3 / S3。

正式交易点必须绑定正式结构、结构身份和真实 `committed_at`，不能使用线段端点时间或候选结构时间冒充实时可知时间。

需要特别说明：**当前存在六类交易点实现，不代表跨级别买点语义已经完成最终产品定义。** 后续开发仍会继续强化“操作级别结构”和“次级别证明”的显式关系，因此当前实现应被视为已经具备安全证据边界的算法基线，而不是最终交易策略承诺。

## 数据与刷新

Streamlit 默认配置：

```text
数据源：Binance
交易对：BTCUSDT
周期：5m
已收盘历史：5000 根
实时未收盘：最多 1 根
```

首次加载会分页获取历史数据，之后使用增量 REST 轮询：

- 当前未收盘 K 与已收盘历史严格分离；
- 当前 K 更新只影响 live / provisional 展示；
- 新 K 收盘后才推进 confirmed 分析；
- 页面暂停过久时重新加载完整历史窗口；
- 请求失败保留上一份完整快照，不让半截数据进入正式分析；
- 对 429 / 418 / 5xx 使用退避处理。

当前 UI 不是逐 tick 交易终端，也没有后台常驻 WebSocket 守护进程。

## 图表语义

- 稳定笔和正式线段：实线；
- 候选笔和候选线段：同色虚线；
- 当前未收盘 K：独立实时层；
- 图层颜色、粗细、透明度和 hover 设置只影响展示，不进入算法判断。

候选结构允许迁移、替换或消失，不参与正式中枢和正式买卖点计算。

## 安装与启动

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
pytest
streamlit run app.py
```

默认页面加载 `BTCUSDT / 5m / 5000 根`。

## 命令行下载

```bash
chan-structure fetch \
  --symbol BTCUSDT \
  --interval 5m \
  --limit 5000 \
  --market spot \
  --output artifacts/BTCUSDT_5m_5000.csv
```

## 验证

当前 v0.10.17 代码基线在合并前的最终 GitHub Actions 中通过 Python 3.10、3.11、3.12、3.13 矩阵；测试结果为：

```text
129 passed, 1 skipped
```

跳过项是未安装可选 `czsc` 包时的参考差分测试，不代表算法失败。

完整的当前验证入口、验证脚本与判定原则见 [`VALIDATION.md`](VALIDATION.md)。

## 回归产物

`artifacts/` 中包含 DEMO、真实快照对比和历史回归产物，用于复现算法问题和防止回归。

其中部分文件名包含 `v0.10.11`、`v0.10.15`、`v0.10.16` 等历史版本号。**这些名称表示该回归样本产生或冻结时的版本，不代表当前运行版本。** 当前版本以 `pyproject.toml` 和本 README 的“当前基线”为准。

## 文档约定

为了避免版本文档互相冲突，仓库只维护三类主文档：

- `README.md`：当前系统是什么、如何运行、当前语义；
- `CHANGELOG.md`：历史版本发生过什么变化；
- `VALIDATION.md`：当前版本如何验证、哪些不变量必须成立。

详细的历史修复过程、TDD 红绿记录和逐次审计证据保留在 Git commit 与已关闭 Pull Request 中，不再复制成多份根目录 release-note 文件。

## 当前阶段边界

- 当前 UI 使用周期自适应的增量 REST 轮询，不是逐 tick 交易终端；
- 已具备当前 K、候选结构和正式结构的数据隔离；
- 已具备结构锚点、MACD 锚点、正式提交时间和身份完整性校验；
- 尚未提供后台常驻进程、数据库、WebSocket 守护和消息通知服务；
- 后续任何通知都必须只使用正式结构及真实 `confirmed_at_dt`；
- 跨级别买点语义仍属于后续开发范围，不应由旧版本说明文件替代当前设计。
