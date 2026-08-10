# 项目最终目标与进度总控（Goal / Handoff Source of Truth）

> **文件定位：项目长期目标、当前阶段、已验证进度、未完成事项与下一步的总控文档。**  
> 仓库：`pyxm1618/chan-new`  
> 默认分支：`main`  
> 当前代码基线：`v0.11.0`  
> 当前阶段：**Phase 1 — Fixed-Level Operational Baseline 收口阶段**  
> 本文版本：`1.0`  
> 首次建立：`2026-08-10`  
> 本文建立前最后核验的 `main`：`3f46c43d2d6490b52d0600739a1b7984fd7c528e`  
>
> **任何新的 AI / 开发者接手本项目时，应先完整阅读本文，再阅读与当前任务直接相关的代码、测试、`README.md`、`VALIDATION.md`、`docs/ARCHITECTURE.md` 和其他专项文档。**

---

# 0. 本文解决什么问题

本项目开发周期长、理论边界复杂、历史 PR 多，最大的风险不是“忘记某个函数怎么写”，而是：

1. 新的 AI 只看到当前代码，误把阶段性实现当成最终目标；
2. 新的 AI 只看到长期架构，误把未来计划当成当前已经实现；
3. 修一个局部问题时重新引入已经明确禁止的理论错误，例如把本周期内部笔伪装成真实低级别；
4. PR 合并后没有同步项目阶段，后续重复审计、重复开发或错误跳阶段；
5. 用旧 PR、旧 CI、旧文档中的成功结果证明当前代码，造成“看起来完成、实际上没有验证”；
6. 随着 AI 更换，项目逐渐偏离用户最初要做的系统。

因此本文必须长期承担五个职责：

```text
最终目标
+
不可违反的理论/工程边界
+
当前真实阶段
+
已验证完成 / 尚未完成
+
唯一明确的下一步
```

本文不是代码说明书，也不替代详细架构文档。具体实现细节仍以代码和专项文档为准。

---

# 1. 真相优先级与更新规则

## 1.1 两类“Source of Truth”必须分开

### A. 最终目标 / 不可违反原则

除非用户后续**明确修改目标**，本文中的“最终目标”和“硬约束”是项目方向的 Source of Truth。

任何局部实现、历史代码、旧 PR 都不能因为“现在已经这样写了”而反向改变最终目标。

### B. 当前实现事实

判断“现在代码到底做到了什么”时，优先级为：

```text
当前 main 代码 + pyproject.toml
> 当前自动化测试 + 最新 head CI
> README.md / VALIDATION.md
> goal.md 的当前进度段
> ARCHITECTURE_IMPLEMENTATION_STATUS.md
> CHANGELOG.md
> 历史 PR / commit / artifacts
```

如果本文的“当前进度”与 `main` 代码、测试或最新 CI 冲突：

> **以当前代码和可复现证据为准，并立即修正本文。**

不能为了维护文档表面一致而否认代码事实。

---

## 1.2 什么情况下必须更新本文

发生以下任一情况，必须在同一 PR 或紧邻 PR 中同步更新 `goal.md`：

- 一个 Phase / Subphase 正式完成；
- 当前阶段发生变化；
- 最终目标或理论边界经用户明确修改；
- 新增/删除一个长期阶段；
- 发现此前“已完成”其实不成立；
- 一个关键 blocker 被验证并解决；
- 生产语义发生重大改变；
- 下一步发生改变；
- 一个历史方案被正式 supersede。

普通内部重构、拼写修复、无阶段意义的小补丁，不要求机械修改本文。

---

## 1.3 禁止的进度写法

严禁：

- 计划写进文档就标成“完成”；
- 有类/接口但没有生产路由和测试就标成“完成”；
- 单元测试通过但真实 formal 路径未覆盖就标成“完成”；
- 使用旧 commit / 旧 PR 的 CI 证明新 head；
- 只因为 PR mergeable 就声称功能完成；
- 用“代码大概有了”“应该没问题”“理论上支持”代替验证；
- 用一个主观百分比代替阶段验收。

如果用户询问完成度，可以给估计百分比，但**百分比永远不是本文的验收依据**。

---

## 1.4 推荐状态词

本文长期只使用以下状态：

```text
VERIFIED_COMPLETE   已实现，并有当前可追溯验证证据
IN_PROGRESS         正在实现或尚未完成收口
PLANNED             已进入长期路线，但尚未开始正式实现
BLOCKED             已知 blocker 阻止继续
DEFERRED            主动延后，不属于当前阶段
SUPERSEDED          已被后续方案替代，不能作为当前基线
```

---

# 2. 用户最初真正要做的系统

## 2.1 一句话最终目标

构建一套**真正按缠论结构运行、可量化、无未来函数、可回放、可审计、可持续演进，并最终支持固定级别与严格递归多级别分析的缠论行情监控与信号系统**。

它不是“几个 B1/B2/B3 函数”的集合，也不是“MACD + 中枢”的指标策略。

最终系统必须把：

```text
市场数据
→ 几何结构
→ 走势结构
→ 中枢 / 级别
→ 背驰
→ 买卖点身份
→ 跨级别关系 / 区间套
→ 质量事实
→ 实践规则
→ 策略筛选 / 组合信号
→ 监控与展示
```

建成可解释、可追溯、可验证的完整链路。

---

# 3. 最终理论目标

## 3.1 底层几何结构必须正确

基础结构链至少包括：

```text
Raw Bar
→ Inclusion / 去包含
→ Fractal / 分型
→ Stroke / 笔
→ GeometricSegment / 线段
```

这些对象首先是几何事实，不应提前混入策略强弱、交易建议或伪级别语义。

---

## 3.2 严格递归级别是最终核心能力之一

最终必须能正式表达：

```text
Movement@L(n-1)
→ CentralZone@L(n)
→ Movement@L(n)
→ CentralZone@L(n+1)
→ Movement@L(n+1)
→ ...
```

严格递归不是用一个周期标签冒充结构级别，也不是把 5m 线段内部的 5m 笔叫成“1m”。

真实跨周期 / 跨级别递归必须消费真实、兼容、可审计的低级别分析结果。

---

## 3.3 固定级别分析与严格递归必须长期并存

最终系统同时支持：

```text
STRICT_RECURSIVE
FIXED_LEVEL_OPERATIONAL
```

二者都是合法分析模式，但必须显式记录 provenance，绝不能静默混用。

固定级别模式允许在明确的最小分析级别中，把 formal Segment 作为上下文中的 sublevel atom 使用；但：

```text
GeometricSegment != MovementType
```

Segment 只是承担上下文角色，不因此在全局本体上变成走势类型。

---

## 3.4 必须正式实现同级别分解与 Movement 本体

最终不能停在：

```text
K线 → 笔 → 线段 → 中枢 → 买卖点
```

还必须实现：

- `DecompositionEngine`；
- `SAME_LEVEL_DECOMPOSITION`；
- `StructureInterpretation`；
- `MovementType`；
- `MovementCompletionState`；
- `CentralZoneLifecycle`；
- 合法 recomposition；
- 走势连接结合性与多义性的版本化表达；
- 已完成 source movement 与仍在形成 higher-level interpretation 的并存。

历史结构允许被后续信息**重新解释**，但不得静默篡改当时已正式提交的解释。

---

## 3.5 中枢、趋势和走势完成必须是独立事实

严格趋势身份使用 GG/DD 的同级别分离条件；ZG/ZD 仍用于中枢核心区和 B3 边界。

不能为了“信号更强”把 GG/DD 从身份条件降格成质量条件，也不能把 ZG/ZD 偷换成趋势定义。

---

## 3.6 背驰语义与计算证据必须解耦

最终至少区分：

```text
DivergenceFact
DivergenceLifecycle
DivergenceEvidence
EvidenceMethod
```

MACD 是一种辅助证据方法，不是 ORIGINAL_THEORY 背驰定义本身。

因此最终必须允许在不改变理论事实模型的前提下，替换或增加不同 evidence method。

---

## 3.7 买卖点 Identity / Quality / Strategy 必须硬隔离

最终长期边界：

```text
TradingPoint Identity
!= Quality Facts
!= Strategy Decision
```

标准身份仍只有：

```text
B1 / B2 / B3
S1 / S2 / S3
```

“强一买”“强三买”“递归一买”“共振一买”“小一大二”等不能被偷偷创建为新的 canonical 买卖点类型。

质量配置只能筛选已经存在的身份，不能重新定义历史事实。

---

## 3.8 必须实现真正的跨级别买卖点关系

最终需要正式表达至少：

```text
DIRECTLY_CONSTITUTES
REALIZES_EXTREMUM_OF
COINCIDES
```

典型包括：

```text
B1@direct-sublevel
DIRECTLY_CONSTITUTES
B2@higher-level
```

以及低级别买卖点对高级别极值的承载关系。

系统必须允许同一位置同时存在多个合法身份，例如 B2+B3，以及不同级别上的多重身份。

---

## 3.9 区间套必须是真正的自上而下逐级定位

最终区间套不是“扫描最低周期信号再猜大级别”，也不是简单多周期指标共振。

必须实现：

```text
higher-level divergence segment
→ corresponding lower-level divergence segment
→ continue narrowing
→ terminal lower-level structure
→ locate higher-level turning region / extremum
```

并使用不同关系表达：

```text
NARROWS_TO
LOCATES
```

区间套算法与结构递归算法是不同算法，可以共享 typed relation store，但不能混成一个含糊“递归函数”。

---

## 3.10 Movement Evolution / Recomposition 必须独立实现

最终系统要能表达：

- 背驰后原走势完成；
- 最后中枢级别扩展；
- 更大级别盘整；
- 反趋势；
- 中枢延伸 / 新生 / 扩展；
- B3 后走势演化；
- 同一 underlying market data 的 higher-level recomposition。

TradingPoint Engine 与 MovementEvolutionEngine 应并列消费结构事实，而不是互相硬编码。

---

## 3.11 原著与都业华 Practice 必须分源

长期 provenance 至少区分：

```text
ORIGINAL_THEORY
DU_YEHUA_PRACTICE
PROJECT_POLICY
```

都业华实践层计划覆盖或保留扩展能力，包括但不限于：

- 四种终结模式；
- 小转大；
- 类二买；
- 分型重构；
- 分型停顿；
- R 比率；
- 黄金分割；
- 买卖点强弱 / 质量规则；
- 大小周期组合。

任何都业华细则，在没有足够来源证据前不得冒充缠论原著定理。

---

## 3.12 共振 / CompositeSignal 是组合层，不是新买点类型

最终可支持：

- 小一 + 大二；
- 小一 + 大三；
- 小一 + 大二三；
- 多级别同步；
- Practice pattern + TradingPoint quality 等组合。

但：

```text
Resonance != TradingPointType
CompositeSignal != TradingPointIdentity
```

---

# 4. 最终工程目标与硬约束

## 4.1 无未来函数是最高工程约束之一

每一个 formal 结构和信号必须回答：

```text
它最早什么时候真正可知？
当时依赖的全部证据是否已经存在？
后续数据是否被偷偷用于提前确认？
```

必须使用真实：

- `confirmed_at`；
- `committed_at`；
- evidence refs；
- fingerprint；
- analysis context / provenance。

不能用结构端点时间、调用时间或人工补写时间冒充首次可知时间。

---

## 4.2 Candidate 与 Formal 必须分层

尾部候选结构可以：

- 迁移；
- 替换；
- 撤销；
- 消失。

但已经满足 formal 条件、在当时可知信息下正式提交的历史事实，不能因为之后行情走势失败而被 retroactively 删除。

特别是：

> **“确认的买点后来失败/止损”与“当时尚未完成的候选结构后来被重构取消”必须严格区分。**

一个已经正式确认的买点后续表现差，不等于它在历史上“从未是买点”。

---

## 4.3 必须可 replay、可 audit、可复现

长期要求：

- prefix consistency；
- batch / incremental 一致；
- replay / realtime 一致；
- formal evidence 可追溯；
- 输入身份可验证；
- 任何缺失关键证据的 formal 路径 fail closed；
- 历史结论必须能解释“为什么当时成立”。

---

## 4.4 左右边界必须安全

有限历史窗口不能自行证明绝对结构相位。

左边界证据不足时只能输出候选；右边界未确认结构不能冒充 formal。

`StructureAnchor`、`MacdAnchor`、`SegmentEvidence` 等持久化/恢复对象必须身份绑定，错配就 fail closed。

---

## 4.5 真实低级别数据不能被本级别内部结构替代

这是已经明确修正过的硬约束：

> **禁止重新使用 same-interval internal strokes 作为 fake lower-level evidence。**

例如：5m Segment 内部由 5m Stroke 组成，不意味着这些 Stroke 是真实 1m Movement。

未来 strict recursive / cross-level implementation 必须显式输入真实低级别分析结果。

---

## 4.6 不允许“为了跑出信号”降低 formal 门槛

缺少：

- 精确历史；
- commit evidence；
- identity match；
- compatible context；
- 必要 lower-level materialization（在 strict 模式要求时）；

都必须停在 candidate / pending / rejected / diagnostic，而不是静默兜底生成正式信号。

---

# 5. 最终产品 / 监控层目标

算法正确性优先于展示层，但项目最终不是只在测试里存在的算法库。

用户此前明确提出过的产品层目标包括：

- 自用为主，但 UI 要清晰、美观；
- 最新触发信号优先可见；
- 明确区分“最新事件 / 24 小时信号流 / 今日分类 / 历史归档”；
- 历史信号不得混入今日信号；
- 前端只展示后端已经定义并确认的标准信号，不在前端另造理论判断；
- 信号分类、时间排序和历史/当前状态必须明确；
- 未来通知只允许消费 formal 结构和真实 `confirmed_at`。

此前某一阶段的 `dashboard-web` 范围还明确要求 REST 轮询、不接 WebSocket，并保留旧 Streamlit legacy；这是当时前端实现范围约束，**不自动升级为整个终局系统永久的传输层限制**。未来若重启产品层开发，应先核对用户最新要求再决定 REST / WebSocket / 后台守护等实现方式。

当前本文**不把自动下单、自动交易、目标价、盈亏比或系统替用户作交易决策**列为既定最终目标；除非用户未来明确增加。

---

# 6. 长期架构分期

以下分期是当前长期路线。不得为了“尽快做高级功能”跳过当前阶段的退出条件。

## Phase 0 — 数据 / 时间 / 无未来函数基础

目标：

- K 线输入连续性；
- 左右边界安全；
- stable / provisional；
- formal commit ledger；
- `confirmed_at` / `committed_at`；
- fingerprint / identity；
- StructureAnchor / MacdAnchor；
- prefix consistency；
- batch / incremental / replay 一致；
- formal evidence fail closed。

**当前状态：`IN_PROGRESS`（大量核心基础已建立，但作为长期基础设施仍需持续加固，不宣称永久结束）。**

---

## Phase 1 — Fixed-Level Operational Baseline 收口

目标：

- 单级别 B1/B2/B3、S1/S2/S3 基线；
- formal Segment / SegmentCentralZone qualification；
- 明确 `AnalysisContext`；
- 明确 minimum analysis level；
- formal `SegmentRoleBinding` / `SEGMENT_AS_SUBLEVEL_ATOM` provenance；
- Identity / Quality / Strategy 拆分；
- QualityProfile / StrategyFilter；
- DivergenceFact / DivergenceEvidence / EvidenceMethod 解耦；
- MACD 从“硬编码身份逻辑”迁移为可审计 evidence method；
- 真实行情 / prefix / replay / no-repaint 验证达到可冻结标准。

**当前状态：`IN_PROGRESS`。这是现在的当前阶段。**

---

## Phase 2 — DecompositionEngine + Movement 本体

目标：

- `DecompositionEngine`；
- `SAME_LEVEL_DECOMPOSITION`；
- versioned `StructureInterpretation`；
- `MovementType`；
- `MovementCompletionState`；
- `CentralZoneLifecycle`；
- fixed-level movement semantics；
- legal recomposition。

**当前状态：`PLANNED`。**

---

## Phase 3 — Divergence Semantics + B1

目标：

- 完整 `DivergenceFact`；
- `DivergenceLifecycle`；
- `DivergenceEvidence`；
- 多 EvidenceMethod；
- trend / consolidation divergence；
- B1 identity 与 divergence evidence 的正式审计关系。

说明：Phase 1 会先完成当前 MACD 耦合的必要解耦基础；Phase 3 再在 Movement 本体之上完成完整 divergence semantics。

**当前状态：`PLANNED`。**

---

## Phase 4 — STRICT_RECURSIVE Structure Level

目标：

```text
Movement@L(n-1)
→ CentralZone@L(n)
→ Movement@L(n)
```

并实现：

- `StructureLevelGraph`；
- direct sub/super level；
- recursive composition；
- `LOWER_LEVEL_MOVEMENT_PROJECTION`；
- 真实低级别 AnalysisResult 输入；
- 严格跨级别无未来函数验证。

**当前状态：`PLANNED`。**

---

## Phase 5 — Cross-Level TradingPoint Identity

目标：

- strict B2 materialized `DIRECTLY_CONSTITUTES`；
- B3 direct-sublevel movement evidence；
- `REALIZES_EXTREMUM_OF`；
- B2+B3 coincidence；
- multi-identity audit；
- compatible AnalysisContext / StructureLevel relation validation。

**当前状态：`PLANNED`。**

---

## Phase 6 — 区间套

目标：

- `NARROWS_TO`；
- `LOCATES`；
- `LocalizationProfile`；
- 逐级 divergence evidence chain；
- terminal localization；
- 上下级别时间 / 价格 / provenance 一致性。

**当前状态：`PLANNED`。**

---

## Phase 7 — Movement Evolution / Recomposition

目标：

- `RECOMPOSES_FROM`；
- source vs higher-level lifecycle；
- 中枢延伸 / 新生 / 扩展；
- 背驰后三类演化；
- B3 后演化；
- 合法 / 待确认 / 已排除分支。

**当前状态：`PLANNED`。**

---

## Phase 8 — Original Cross-Level Turn + Du Practice

先建立原著跨级别事实，再叠加实践层：

- `OriginalCrossLevelTurnFact`；
- 小级别背驰引发更高级别转折；
- `DuTerminationPattern`；
- 四种终结；
- 小转大；
- 类二买；
- 分型重构；
- 分型停顿；
- R 比率；
- 黄金分割。

每项独立 provenance、独立规则版本、独立测试。

**当前状态：`PLANNED`。**

---

## Phase 9 — CompositeSignal / Resonance + 产品化收口

目标：

- 小一 + 大二；
- 小一 + 大三；
- 小一 + 大二三；
- 多级别同步；
- SignalProfile；
- CompositeSignal；
- 标准信号流；
- 监控 / 展示 / 历史归档；
- 必要时的正式通知链路。

Composite 层只消费已经成立的结构、身份、关系、质量和 Practice facts，不反向污染理论层。

**当前状态：`PLANNED`。**

---

# 7. 当前真实基线：v0.11.0

## 7.1 当前生产链路

`main` 当前生产语义是：

```text
当前周期 K 线
→ 去包含
→ 分型
→ 笔
→ 标准特征序列线段
→ formal Segment / SegmentEvidence
→ SegmentCentralZone
→ 单级别 B1/B2/B3、S1/S2/S3
```

正式交易点消费：

- 当前周期正式提交线段；
- 当前周期正式线段中枢；
- 同级价格关系；
- 当前周期精确 MACD 状态；
- 真实 Segment `committed_at`；
- identity-bound `SegmentEvidence`。

**当前不是 strict recursive 多级别系统。**

---

# 8. 已验证完成的关键能力

以下条目可以标为 `VERIFIED_COMPLETE`，但只表示该条目在当前范围内已经建立，不表示整个终局功能完成。

## 8.1 单级别生产买卖点边界 — `VERIFIED_COMPLETE`

PR #13 完成：

- 生产交易点切换为严格单级别输入；
- B1/S1 不再要求 departure Segment 内部笔级三买/三卖；
- B2/S2 不再要求 retracement Segment 内部笔级 B1/S1；
- B3/S3 保持 formal Segment 离开 + 第一次反向回试边界；
- same-interval internal strokes 不再充当 fake lower timeframe；
- 生产 API / runtime 路由到单级别 detector。

PR #13 在合入 #15 后的最终集成 head：`7d476194ea8b08477e1297fb08d46b4b9bbea853`。

最终集成 CI：GitHub Actions `31352678936`，Python 3.10 / 3.11 / 3.12 / 3.13 全部 success。

#13 合入 `main` 的 merge commit：`e9ff8f9f51a1f34deeb06c45d318c015cb0e11a7`。

---

## 8.2 Fixed-Level Bootstrap Qualification — `VERIFIED_COMPLETE`

PR #15 完成并验证：

- Lesson 67/77 第二种 reverse feature-sequence confirmation 不再递归复用 primary detector 的 future `actual_break` 语义；
- reverse 三元素分型在第三元素完成时确认；
- formal facade 必须使用真实、identity-matching、committed `SegmentEvidence`；
- caller-supplied `segment_commit_times` 不能伪造 formal provenance；
- `segment_index` identity 必须匹配；
- `committed_at` 必须是合法带时区 datetime，并且不得早于结构真正可用时间；
- malformed evidence 在 formal 边界 fail closed，不向下游抛出未控制异常；
- Lesson 78 Segment 实际价格区间使用 constituent Stroke 的真实 high/low；
- SegmentCentralZone reference / fixture 已迁移到合法多笔 Segment 与真实范围语义；
- formal TradingPoint 测试覆盖 `detect_segments → committed SegmentEvidence → formal detector` 真实 provenance 链；
- 原著 fixed-level 生产默认 `min_bi_len=7` 已统一到库、CLI、Streamlit；
- `min_bi_len=6` 只作为显式历史 / CZSC compatibility 选择。

PR #15 最终 head：`0ce0e7ca2057f7363b92fe2f970160bf6d6747ca`。

其最终 qualification CI：GitHub Actions `31351863677`，Python 3.10 / 3.11 / 3.12 / 3.13 全部 success；Python 3.11 为 `149 passed, 1 skipped`。

#15 合入 #13 分支的 merge commit：`7d476194ea8b08477e1297fb08d46b4b9bbea853`。

---

## 8.3 Formal structure / time / identity 基础设施 — `VERIFIED_COMPLETE`（当前范围）

当前已建立并有测试覆盖的关键约束包括：

- K 线 interval / continuity 校验；
- 单根 K 线周期合法性；
- close_time 不得越过下一周期起点；
- 当前未收盘 K 与已收盘历史分层；
- 左边界无 anchor 时 formal fail closed；
- stable / provisional Stroke 分层；
- detected / committed Segment 分层；
- formal Segment commit ledger；
- `committed_at` / `committed_at_bar_position`；
- Segment fingerprint / identity；
- `SegmentEvidence`；
- `StructureAnchor`；
- `MacdAnchor` identity / continuity；
- 缺少 formal evidence 时 TradingPoint fail closed；
- batch / incremental 和 future-function 相关不变量已有正式验证契约。

注意：这些能力“当前范围内已验证”不代表 Phase 0 永久完成。随着 Movement、strict recursion、cross-level relation 出现，Phase 0 的无未来函数与 provenance 基础必须继续扩展。

---

## 8.4 长期架构边界文档 — `VERIFIED_COMPLETE`（文档基线）

PR #14 已把长期架构合入 `main`：

- `docs/ARCHITECTURE.md`；
- `docs/ARCHITECTURE_IMPLEMENTATION_STATUS.md`。

后者明确：Segment semantics / formal provenance qualification 已完成，但完整 AnalysisContext / bootstrap provenance ontology 和更高阶段仍未实现。

PR #14 最新文档 head CI：GitHub Actions `31352927141`，Python 3.10 / 3.11 / 3.12 / 3.13 全部 success。

#14 合入 `main` 的 merge commit：`3f46c43d2d6490b52d0600739a1b7984fd7c528e`。

---

# 9. 当前明确未完成的内容

## 9.1 Phase 1 必须完成但尚未完成

以下均为 `IN_PROGRESS / PLANNED`，不得声称已完成：

### A. 显式 AnalysisContext

缺少正式 materialization：

```text
analysis_context_id
market_interval
operation_level_ref
minimum_analysis_level_ref
analysis_mode
level_bootstrap_method
decomposition_policy_id
as_of
data_range
rule_version
```

当前 fixed-level 语义已经通过 qualification，但上下文仍主要存在于代码约定 / 文档语义，而不是完整正式对象。

### B. minimum analysis level + SegmentRoleBinding

必须把：

```text
formal GeometricSegment
SERVES_AS_SUBLEVEL_ATOM_IN
AnalysisContext
```

从“理论允许 / 当前语义解释”正式 materialize 成可审计 provenance。

### C. Identity / Quality / Strategy 完整拆分

当前还没有完成终局要求的对象级：

```text
TradingPointIdentity
QualityFacts
StrategyDecision
QualityProfile
StrategyFilter
```

不得把后续强弱规则直接塞回当前 TradingPoint identity detector。

### D. DivergenceFact / DivergenceEvidence / EvidenceMethod 解耦

当前 B1/S1 仍以 MACD hard gate 参与生产判定。

需要把理论背驰语义与 MACD 证据方法分开，使 MACD 成为可追溯、可替换的 EvidenceMethod，而不是整个背驰本体。

### E. Phase 1 真实行情冻结验证

当前已有 DEMO、历史 artifacts、stability scripts 和大量回归测试，但 Phase 1 最终退出前还需要形成明确、可复现的真实行情 / golden truth / prefix / replay / no-repaint 验收集合，并证明 final formal path 在这些样本上稳定。

---

## 9.2 Phase 2–9 尚未正式完成

以下终局能力仍不能作为当前系统能力宣传：

- Movement 本体；
- 同级别分解；
- versioned StructureInterpretation；
- strict recursive structure levels；
- 真实跨周期递归；
- cross-level B1/B2/B3 constitution；
- 区间套；
- Movement Evolution；
- 原著跨级别转折；
- 都业华完整实践层；
- 小转大；
- 多级别共振 / CompositeSignal；
- 完整长期产品化通知链路。

---

# 10. 当前唯一建议的下一步

## Phase 1.1 — AnalysisContext + Bootstrap Provenance

**下一项开发不应直接跳到 strict recursion、区间套或都业华强弱规则。**

应从最新 `main` 新建独立开发分支，优先完成：

1. 正式 `AnalysisContext` 数据模型；
2. `AnalysisMode`；
3. `LevelBootstrapMethod`；
4. `minimum_analysis_level_ref`；
5. formal `SegmentRoleBinding`；
6. fixed-level 当前生产路径绑定上述 provenance；
7. SegmentCentralZone 与 formal TradingPoint 能追溯对应 AnalysisContext / bootstrap role；
8. 不改变已经通过 qualification 的单级别 B1/B2/B3 身份语义；
9. 缺失 / 错配 context 或 role binding 时 formal fail closed；
10. 增加独立 reference / integration / negative tests；
11. 当前 head Python 3.10–3.13 CI 全绿；
12. 更新 README / VALIDATION / ARCHITECTURE_IMPLEMENTATION_STATUS / 本文当前进度。

### Phase 1.1 的禁止项

本阶段禁止顺手加入：

- strict recursive materialization；
- fake lower-level evidence；
- 区间套；
- 小转大；
- 共振；
- 都业华强弱 profile；
- 未经分层的策略规则；
- 大规模与 provenance 无关的重写。

目标是**把已经 qualification PASS 的 fixed-level 语义正式装进可审计上下文模型**，不是再次改写买卖点理论。

---

# 11. Phase 1 后续顺序

Phase 1.1 完成后，默认顺序：

```text
Phase 1.1  AnalysisContext + Bootstrap Provenance
↓
Phase 1.2  Identity / Quality / Strategy separation
↓
Phase 1.3  DivergenceFact / DivergenceEvidence / EvidenceMethod decoupling
↓
Phase 1.4  Real-market golden truth + prefix/replay/no-repaint freeze
↓
Phase 1 EXIT
↓
Phase 2     DecompositionEngine + Movement
↓
Phase 3     Full Divergence Semantics
↓
Phase 4     STRICT_RECURSIVE
↓
Phase 5     Cross-Level TradingPoint
↓
Phase 6     区间套
↓
Phase 7     Movement Evolution
↓
Phase 8     Original Cross-Level Turn + Du Practice
↓
Phase 9     Composite / Resonance / Productization
```

只有出现新的代码证据或用户明确调整优先级时，才改变此顺序，并必须同步更新本文。

---

# 12. 每次新 AI 接手的强制流程

新的 AI 接手时，不需要先把全部历史 PR 从头读一遍，但必须执行：

## Step 1：先读本文

先回答四个问题：

```text
最终目标是什么？
当前 Phase 是什么？
已经 VERIFIED_COMPLETE 什么？
下一步是什么？
```

如果回答不出来，不应直接开发。

## Step 2：核验当前 GitHub / main

至少确认：

- 默认分支仍是 `main`；
- 当前 `pyproject.toml` 版本；
- `main` 最新代码是否与本文基线一致；
- 是否存在 open PR / stacked PR；
- 当前任务是否已有未合并实现；
- 最新相关 CI 是否属于当前 head。

## Step 3：只读与当前任务相关的详细代码

本文负责“方向和进度”，代码负责“具体怎么实现”。

不要因为本文没有列某个函数就重新发明算法；也不要因为代码里存在历史实现就默认它符合最终目标。

## Step 4：开发前对标硬约束

尤其检查：

- 是否引入未来函数；
- 是否把 candidate 当 formal；
- 是否使用 fake lower-level；
- 是否混淆 Segment / Movement；
- 是否混淆 fixed-level / strict recursive；
- 是否把 MACD 当理论定义；
- 是否用 Quality / Strategy 改写 Identity；
- 是否把 Du Practice 冒充 ORIGINAL_THEORY；
- 是否破坏已确认历史事实不可静默撤销的规则。

## Step 5：完成后回写本文

只有证据足够才能把状态升级成 `VERIFIED_COMPLETE`。

---

# 13. 每次进度更新建议模板

每次重要阶段完成后，在本文“变更记录”增加：

```text
日期：
版本 / main commit：
完成的 Phase/Subphase：
合并 PR：
关键语义变化：
新增/改变的不变量：
测试证据：
CI：
仍未完成：
当前阶段：
下一步：
```

如果发现错误完成声明，应明确记录：

```text
Previous status: VERIFIED_COMPLETE
Corrected status: IN_PROGRESS / BLOCKED
Reason: ...
Evidence: ...
```

禁止为了“看起来进度没有倒退”保留错误状态。

---

# 14. 当前阶段退出标准

## Phase 1 只有同时满足以下条件才允许标记 `VERIFIED_COMPLETE`

- [x] 单级别 B1/B2/B3、S1/S2/S3 生产路径成立；
- [x] same-interval internal Stroke 不再作为 fake lower-level；
- [x] Segment semantics / SegmentCentralZone range qualification 完成；
- [x] formal SegmentEvidence / committed_at / fingerprint 边界完成；
- [x] fixed-level 原著默认 `min_bi_len=7` 生产入口统一；
- [ ] `AnalysisContext` 正式实现；
- [ ] `minimum_analysis_level_ref` 正式实现；
- [ ] `SegmentRoleBinding` / bootstrap provenance 正式实现；
- [ ] Identity / Quality / Strategy 完整拆分；
- [ ] QualityProfile / StrategyFilter 完成；
- [ ] DivergenceFact / DivergenceEvidence / EvidenceMethod 达到 Phase 1 所需解耦；
- [ ] MACD hard gate 迁移为可审计 EvidenceMethod；
- [ ] 真实行情 / golden truth 验收集明确；
- [ ] prefix / replay / no-repaint 在 Phase 1 final path 上通过；
- [ ] 最终 Phase 1 head Python 3.10–3.13 CI 全绿；
- [ ] README / VALIDATION / ARCHITECTURE_IMPLEMENTATION_STATUS / goal.md 与代码一致。

因此截至本文建立时：

> **Phase 1 尚未完成。项目当前仍处于 Phase 1 收口阶段。**

---

# 15. 当前风险清单

## R1. 最大方向性风险：过早进入 strict recursion

如果在 AnalysisContext / bootstrap provenance、Identity/Quality/Strategy 和 EvidenceMethod 还没收口时直接做跨级别递归，会把当前隐式语义放大到多级别，后续代价更高。

## R2. 再次引入 fake lower-level

任何为了复用当前 `segment.strokes` 而把它们解释成真实低级别的方案，直接违反已确认边界。

## R3. 把 MACD 工程证据固化成理论本体

当前 MACD hard gate 是阶段性生产实现，不应成为未来 Divergence ontology。

## R4. 强弱 / Practice 污染买卖点 Identity

都业华强弱、策略门槛、共振只能在 Identity 之后消费事实。

## R5. 文档进度超过代码

本文最大的价值就是阻止“路线图完成幻觉”。任何状态必须可追溯到当前代码和测试。

## R6. 只测 synthetic，不做真实行情冻结验收

自动化 fixture 很重要，但 Phase 1 退出前仍需要明确的 real-market / golden truth 证据集合。

---

# 16. 相关文档职责

为了避免多个文档再次互相冲突，长期职责固定为：

- **`goal.md`**：最终目标、硬约束、当前阶段、进度、下一步、AI 接手入口；
- **`README.md`**：当前系统现在能做什么、如何运行；
- **`VALIDATION.md`**：当前版本如何验证、当前必须满足哪些不变量；
- **`docs/ARCHITECTURE.md`**：长期本体与详细终局架构；
- **`docs/ARCHITECTURE_IMPLEMENTATION_STATUS.md`**：长期架构相对当前代码的专项迁移状态补充；
- **`CHANGELOG.md`**：版本历史摘要；
- **代码 / 测试 / CI**：当前实现事实的最高证据；
- **历史 PR / commit / artifacts**：取证与回溯，不作为当前状态优先来源。

如果这些文档发生冲突，应按第 1 节的真相优先级处理，并修复冲突。

---

# 17. 当前变更记录

## 2026-08-10 — 建立 Goal / Handoff Source of Truth

基线：`main @ 3f46c43d2d6490b52d0600739a1b7984fd7c528e`，`v0.11.0`。

已确认：

- PR #15 fixed-level bootstrap qualification 已完成；
- PR #15 已先合入 #13；
- #13 post-qualification Python 3.10–3.13 CI 全绿后已合入 main；
- #14 长期架构与实现状态补充 CI 全绿后已合入 main；
- 当前项目定位仍是 Phase 1 Fixed-Level Operational Baseline 收口；
- strict recursion、cross-level trading points、区间套、小转大、共振均尚未完成。

当前下一步：

> **Phase 1.1 — 正式实现 AnalysisContext + minimum analysis level + SegmentRoleBinding / bootstrap provenance。**

---

# 18. 给下一位 AI 的最后一句话

> **不要把当前 v0.11.0 的单级别 SegmentCentralZone 买卖点系统当成最终产品。它只是已经通过 Segment/formal provenance qualification 的 Fixed-Level 基线。最终目标仍是：在无未来函数、可审计、真实 provenance 的前提下，同时支持 fixed-level operational 与严格 Movement→CentralZone→Movement 递归，继续完成同级别分解、Movement、完整背驰语义、跨级别买卖点、区间套、走势演化、原著跨级别转折、都业华实践与组合共振；当前唯一应优先推进的是 Phase 1 收口，而不是跳阶段。**
