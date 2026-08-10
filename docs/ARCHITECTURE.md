# 缠论分析引擎终局架构与理论边界

> 状态：Target Architecture / 长期基线候选  
> 日期：2026-08-08  
> 目的：定义项目长期理论本体、工程边界、证据模型、递归关系和分阶段开发顺序。  
> 重要：本文不是当前已实现功能清单。终局架构可以先设计清楚，但实现必须循序渐进。

---

## 0. 本文解决什么问题

本项目的长期目标不是“把若干缠论指标写成信号函数”，而是建立一套：

- 无未来函数；
- 可回放；
- 可审计；
- 支持固定操作级别；
- 支持严格递归级别；
- 支持区间套；
- 支持跨级别买卖点关系；
- 支持都业华实践规则；
- 支持策略配置但不污染理论事实；
- 长期可演进而不需要反复推倒本体模型；

的缠论分析引擎。

本文最重要的任务是先回答：

> **市场中的每一种对象究竟是什么，它与其他对象是什么关系。**

只有本体和依赖关系稳定后，算法细节才有长期价值。

---

# 1. Architecture Invariants

以下原则优先于历史代码、参数兼容和短期实现便利。

## 1.1 周期、分析上下文、操作级别、结构级别必须分离

```text
MarketInterval
!= AnalysisContext
!= OperationLevel
!= StructureLevelRef
```

1m、5m、30m 首先是市场数据采样/观察周期，不能永久写死为理论结构级别。

---

## 1.2 严格递归与固定级别分析都属于合法分析模式

原著既给出了严格递归定义，也明确允许在实际操作中选定最小分析级别、忽略更低层内部结构。

因此终局必须同时支持：

```text
STRICT_RECURSIVE
FIXED_LEVEL_OPERATIONAL
```

二者不是“正确 vs 错误”，而是不同的分析模式。

但必须记录 provenance，绝不能静默混用。

---

## 1.3 GeometricSegment 与 MovementType 本体不同

```text
GeometricSegment != MovementType
```

但是，在特定 `AnalysisContext` 中，正式线段可以承担一个上下文角色：

```text
GeometricSegment
SERVES_AS_SUBLEVEL_ATOM_IN
AnalysisContext
```

这尤其适用于原著第57课所描述的“最小分析级别 bootstrap”。

因此：

- 不允许把任意 Segment 永久声明为某理论级别的 Movement；
- 也不允许把所有 Segment-based 分析一概降格为工程近似。

---

## 1.4 Canonical Central Zone 的组成单位取决于分析模式和 bootstrap

严格递归模式：

```text
completed Movement@L(n-1)
× 3+
-> CentralZone@L(n)
```

固定级别、最小分析级别 bootstrap：

```text
formal Segment
serves as sublevel atom in AnalysisContext
× 3+
-> CentralZone at selected minimum analysis level
```

中枢对象必须记录 constituent 的真实语义来源。

---

## 1.5 趋势、背驰、走势完成、买卖点是不同事实

禁止把它们揉成一个 Detector。

终局关系是：

```text
Structure Facts
├─> Divergence Engine
├─> Movement Completion / Evolution Engine
└─> TradingPoint Identity Engine
```

它们共享底层事实，但不是父子枚举关系。

---

## 1.6 禁止 `TerminationMode -> B1/B2/B3`

B1、B2、B3 的理论来源不同：

- B1：趋势 + 趋势背驰；
- B2：B1 后的次级别走势序列，以及理论上的直接次级别 B1 构成；
- B3：次级别走势离开中枢 + 第一次次级别回试不进入中枢。

都业华“四种终结模式”不能成为三类买卖点的父节点。

---

## 1.7 Identity / Quality / Strategy 三层硬隔离

```text
TradingPoint Identity
!= Quality Facts
!= Strategy Decision
```

策略配置只能筛选已经存在的事实，不能重新定义历史上的 B1/B2/B3。

---

## 1.8 身份所需证据与策略附加证据必须分开

例如：

```text
严格递归模式下 B2 的 direct-sublevel B1 provenance
```

属于 Identity 理论关系。

而：

```text
策略额外要求 1m + 5m 共振
```

属于策略/组合要求。

二者不能共用一个 `recursive_confirmation`。

---

## 1.9 MACD 是证据方法，不是背驰理论定义

原著第24课明确把 MACD 描述为“辅助判断”“不绝对精确但方便”的方法。

因此：

```text
MACD fail
!= ORIGINAL_THEORY divergence impossible
```

当前算法可以使用 MACD 作为工程判断方法，但必须记录 `evidence_method`。

---

## 1.10 区间套、买点构成、极值承载、跨级别转折、共振必须分开

至少区分：

```text
DIRECTLY_CONSTITUTES
REALIZES_EXTREMUM_OF
NARROWS_TO
LOCATES
COINCIDES
CROSS_LEVEL_TURN_OF   # 如未来需要实体关系边
```

共振最终仍是 profile-versioned 的组合事实/信号。

---

## 1.11 不使用泛化 `TRIGGERS`

“小级别背驰引发大级别转折”有明确理论语义。

一个无约束的：

```text
TRIGGERS
```

容易把小转大、区间套、买点构成和普通时序因果混在一起。

因此使用专门的 `OriginalCrossLevelTurnFact`，必要时再映射成语义明确的 typed relation。

---

## 1.12 共振不是第四类买点

原著第17课本身就谈到“不同级别的同步共振”。

但：

```text
Resonance != TradingPointType
```

程序中的可执行共振规则还需要明确时间/价格窗口，因此放到 Composite 层。

---

## 1.13 都业华 Practice 与原著必须分源

```text
ORIGINAL_THEORY
DU_YEHUA_PRACTICE
PROJECT_POLICY
```

三类来源必须可以审计。

未经原课程直接核验的都业华细节，标记：

```text
DU_YEHUA_PRACTICE_UNVERIFIED_DETAIL
```

---

## 1.14 当前历史事实可以被“重新解释”，但不能被静默篡改

走势具有结合性、多义性。

因此未来允许：

```text
StructureInterpretation v1
-> later information / decomposition rule
-> StructureInterpretation v2
```

但必须：

- v1 仍可审计；
- v2 有自己的 `confirmed_at`；
- 不能物理改写过去在当时可知信息下已经提交的解释。

---

## 1.15 终局架构先设计，实现严格分期

任何阶段在以下验证没有稳定前，不进入下一阶段：

- 无未来函数；
- prefix consistency；
- replay/realtime 一致；
- identity/evidence 可审计；
- 真实行情验证。

---

# 2. 理论来源与 Provenance：必须正交化

上一版把 `ORIGINAL_THEORY_CANONICAL / FIXED_LEVEL_OPERATIONAL / SEGMENT_APPROXIMATION` 混在同一维度，这是不够精确的。

终局不使用一个“大而全”的 `IdentityBasis` 枚举，而使用正交 provenance。

## 2.1 `TheorySource`

回答：规则理论来源是什么？

```text
ORIGINAL_THEORY
DU_YEHUA_PRACTICE
PROJECT_POLICY
```

一个买点可以：

```text
theory_source = ORIGINAL_THEORY
analysis_mode = FIXED_LEVEL_OPERATIONAL
```

这两者完全不冲突。

---

## 2.2 `AnalysisMode`

回答：本次分析按什么级别体系执行？

```text
STRICT_RECURSIVE
FIXED_LEVEL_OPERATIONAL
```

### STRICT_RECURSIVE

从选定最低基础单元开始逐级生成：

```text
Movement@L(n-1)
-> CentralZone@L(n)
-> Movement@L(n)
-> CentralZone@L(n+1)
-> ...
```

### FIXED_LEVEL_OPERATIONAL

选定操作/分析级别，将更低级别细节按既定规则折叠，直接在该视角中完成走势、中枢和买卖点分析。

原著第38、53、57课都提供了这种实用分析的理论依据。

---

## 2.3 `LevelBootstrapMethod`

回答：某个分析层级最底部的 constituent 如何获得？

至少预留：

```text
ATOMIC_UNIT
SEGMENT_AS_SUBLEVEL_ATOM
LOWER_LEVEL_MOVEMENT_PROJECTION
```

### `ATOMIC_UNIT`

严格从最低不可分单元启动。

### `SEGMENT_AS_SUBLEVEL_ATOM`

原著第57课所述：先选定最小分析级别，在该视角中更低级别结构都可看作线段，每一正式线段承担该最小分析级别的次级别走势单元角色，三个线段重叠形成最小分析级别中枢。

这是一种**上下文角色**，不是类型相等。

### `LOWER_LEVEL_MOVEMENT_PROJECTION`

已经独立得到的完成低级别 Movement，在高一级观察中被投影成无内部结构单元。

对应原著第53课的“5分钟走势在30分钟视角可看成线段”。

---

## 2.4 `DecompositionPolicy`

回答：走势按什么规则分解？

首个正式策略建议：

```text
SAME_LEVEL_DECOMPOSITION
```

来源：原著第38课。

未来可以增加其他明确政策，但不得让“当前只有一种实现”冒充理论上不存在多义性。

---

## 2.5 `EvidenceMethod`

回答：某个语义事实通过什么计算方法获得支持？

例如：

```text
CENTER_STRUCTURE
MOVEMENT_POWER
MACD_HISTOGRAM_AREA
MACD_DIFF_DEA
MA_AREA
DU_RULE_xxx
```

一个结构本体可能完全符合 `ORIGINAL_THEORY + FIXED_LEVEL_OPERATIONAL`，但其中背驰计算暂时使用：

```text
evidence_method = PROJECT_POLICY_MACD_APPROXIMATION
```

这不会把整条结构链都降格成“工程近似”。

---

## 2.6 `ProvenanceBundle`

任何正式结构/买点至少可追溯：

```text
theory_source
analysis_mode
level_bootstrap_method
decomposition_policy_id
evidence_method_refs[]
analysis_context_id
rule_version
```

这些字段是正交的。

---

# 3. 核心上下文对象

## 3.1 `MarketInterval`

例如：

```text
1m / 5m / 30m / 1h / 1d
```

只回答数据采样周期。

---

## 3.2 `OperationLevel`

回答：策略准备在哪个级别操作。

它是操作选择，不等于 K 线周期，也不等于全局永久结构级别。

---

## 3.3 `AnalysisContext`

一次完整分析的上下文，至少包含：

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

同一行情可以存在多个合法 `AnalysisContext`。

---

## 3.4 `DecompositionEngine`

`DecompositionPolicy` 是规则；`DecompositionEngine` 是执行者。

职责：

```text
Geometric / lower-level structures
+
AnalysisContext
+
DecompositionPolicy
-> StructureInterpretation
```

首个正式实现：

```text
SAME_LEVEL_DECOMPOSITION
```

### Candidate tail 与 committed interpretation

实时情况下：

- 尾部允许候选变化；
- 已正式提交的解释拥有明确 `confirmed_at`；
- 后续如因结合律/更高层重组需要不同解释，生成新的 versioned `StructureInterpretation`；
- 不静默覆盖旧版本。

---

## 3.5 `StructureInterpretation`

用于表达：

> 同一 underlying market interval，在某个 AnalysisContext + DecompositionPolicy 下的一种合法结构解释。

至少包含：

```text
interpretation_id
analysis_context_id
decomposition_policy_id
version
underlying_market_range
parent_interpretation_refs[]
recomposition_refs[]
confirmed_at
fingerprint
```

---

# 4. Geometric Structure 与 Movement 本体

## 4.1 几何层

```text
Raw Bar
-> Inclusion
-> Fractal
-> Stroke
-> GeometricSegment
```

这一层只回答几何结构。

禁止直接塞入：

- 理论级别；
- B1/B2/B3；
- 共振；
- 质量策略。

---

## 4.2 `GeometricSegment`

包含：

- direction；
- high/low；
- start/end；
- commit evidence；
- `confirmed_at`；
- fingerprint。

它本体上不是 `MovementType`。

---

## 4.3 `SegmentRoleBinding`

为第57课最小分析级别 bootstrap 增加正式角色关系：

```text
segment_id
analysis_context_id
role = SUBLEVEL_ATOM
minimum_analysis_level_ref
confirmed_at
rule_version
```

语义：

```text
GeometricSegment
SERVES_AS_SUBLEVEL_ATOM_IN
AnalysisContext
```

不是：

```text
GeometricSegment == MovementType
```

---

## 4.4 `MovementType`

必须是一等实体：

```text
movement_id
analysis_context_id
structure_level_ref
movement_type = CONSOLIDATION | UP_TREND | DOWN_TREND
submovement_refs[]
central_zone_refs[]
start/end
completion_state
interpretation_id
confirmed_at
fingerprint
```

---

# 5. Structure Level 与递归链

## 5.1 `StructureLevelGraph`

至少表达：

```text
DIRECT_SUBLEVEL_OF
DIRECT_SUPERLEVEL_OF
COMPOSES
COMPOSED_BY
```

级别优先使用关系型表示，而不是：

```text
structure_level = "5m"
```

---

## 5.2 严格递归必须显式写成跨级别链

```text
Movement@L(n-1)
        ↓ 3+ overlap
CentralZone@L(n)
        ↓ organizes
Movement@L(n)
        ↓ 3+ overlap
CentralZone@L(n+1)
        ↓
Movement@L(n+1)
```

这样避免“Movement 和 CentralZone 谁先有”的伪循环。

答案是：

> **不同 level 之间递归推进。**

---

## 5.3 固定级别最小分析 bootstrap

第57课允许：

```text
选定 minimum_analysis_level = L
↓
L 以下结构在该视角折叠为 formal Segment
↓
Segment serves as sublevel atom
↓
3+ Segment overlap
↓
CentralZone@L
```

因此：

> Segment-based central-zone construction 在满足上下文前提时，可以是 `ORIGINAL_THEORY + FIXED_LEVEL_OPERATIONAL`，不能一概标成 `PROJECT_POLICY approximation`。

---

## 5.4 高级别 Movement projection

第53课允许：

```text
completed Movement@L(n-1)
-> projection atom in L(n) view
```

必须保留：

```text
representation_of = movement_id
```

这与第57课的 bootstrap role 不同。

---

# 6. CentralZone 与生命周期

## 6.1 `CentralZone`

建议终局统一为一个语义对象，但记录：

```text
central_zone_id
structure_level_ref
analysis_context_id
constituent_type
constituent_refs[]
level_bootstrap_method
zg
zd
gg
dd
lifecycle
interpretation_id
confirmed_at
fingerprint
```

`constituent_type` 可以是：

```text
MOVEMENT_REF
SEGMENT_SUBLEVEL_ATOM_REF
ATOMIC_UNIT_REF
```

这样不需要把 `SegmentCentralZone` 永久定义为“理论上低一等”的对象。

---

## 6.2 `CentralZoneLifecycle`

至少预留：

```text
FORMING
ESTABLISHED
EXTENDING
COMPLETED
EXPANDED_TO_HIGHER_LEVEL
```

“新生”建议作为前后中枢关系，而不是简单生命周期状态。

---

## 6.3 趋势身份使用 GG/DD，而不是只用 ZG/ZD

原著第20课走势中枢中心定理二：

```text
later.GG < previous.DD
<=> 下跌及其延续

later.DD > previous.GG
<=> 上涨及其延续
```

如果：

```text
later.ZG < previous.ZD
but later.GG >= previous.DD
```

或上涨镜像情况，则核心中枢区虽然分离，但外围波动仍有重叠，应进入**更高级别中枢**语义，而不是 strict trend。

因此：

- GG/DD 完全分离是 strict trend identity；
- ZG/ZD 是中枢核心区和 B3 边界；
- 不得把 GG/DD 降格成“更强趋势”质量条件。

---

# 7. Movement Completion 与重新组合

## 7.1 `MovementCompletionState`

至少：

```text
FORMING
COMPLETION_CANDIDATE
COMPLETED
```

必要时可以增加 superseded interpretation 状态，但不要删除旧事实。

---

## 7.2 “原走势完成”与“更高层走势仍形成中”不是矛盾

第43课明确：同级别趋势背驰导致该级别原走势类型终止。

第29课同时说明：最后中枢级别扩展并不等于简单的：

```text
completed trend + independent higher-level consolidation
```

正确建模：

```text
SourceInterpretation:
source movement = COMPLETED

HigherLevelInterpretation:
recomposes same underlying market range
higher-level movement = FORMING (possible)
```

---

## 7.3 `RECOMPOSES_FROM`

不要假设新的 higher-level movement 必须把旧 source movement 当成一个不可拆 child 完整 `CONTAINS`。

原著第29、36课允许重新组合分解边界。

因此在 `StructureInterpretation` 间增加：

```text
new_interpretation
RECOMPOSES_FROM
old_interpretation
```

该关系表示重新解释同一 underlying market data，而不是简单父子包含。

---

# 8. Divergence：语义、证据、生命周期三分

## 8.1 `DivergenceFact`

只表达理论语义，例如：

```text
divergence_id
semantic_type = TREND_DIVERGENCE | CONSOLIDATION_DIVERGENCE
analysis_context_id
structure_level_ref
movement_ref
comparison_leg_a_ref
comparison_leg_c_ref
comparison_leg_completion_refs[]
price_extreme_fact_ref
lifecycle
confirmed_at
```

注意：

> 不再使用含糊的 `completion_fact` 指向 source movement completion。

---

## 8.2 `DivergenceLifecycle`

至少：

```text
CANDIDATE
CONFIRMED
INVALIDATED
```

原因：进入背驰段不等于背驰已经最终确认；后续更细结构可能改变候选判断。

---

## 8.3 避免 Divergence ↔ Completion 循环依赖

禁止：

```text
Divergence requires source Movement completed
AND
Movement completion requires Divergence
```

正确关系：

- 比较腿自身必须具备足够的正式完成证据；
- Divergence 可以先有 `CANDIDATE`；
- `CONFIRMED Divergence` 可以成为 source movement completion/evolution 的输入事实之一；
- source movement completion 不是同一个 DivergenceFact 的前置硬条件。

---

## 8.4 `DivergenceEvidence`

独立记录：

```text
evidence_id
divergence_id
evidence_method
raw_values
evidence_refs[]
as_of
confirmed_at
rule_version
```

MACD 属于这里。

---

## 8.5 盘整背驰不是自动终结

```text
ConsolidationDivergenceFact
!= MovementCompleted
!= Standard B1
```

原著第27课把盘整背驰解释为企图脱离中枢的走势力度不足、重新回到中枢。

因此后续仍需观察：

- 中枢延伸；
- 中枢扩展；
- 第三类买卖点；
- 其他走势演化。

都业华可以在实践层进一步把满足附加条件的某类盘整背驰归为其终结模式，但不能把原著 `ConsolidationDivergenceFact` 自带成“终结”。

---

# 9. TradingPoint Identity

标准类型始终只有：

```text
B1 / B2 / B3
S1 / S2 / S3
```

强一买、递归一买、共振一买、小一大二都不是新的标准类型。

---

## 9.1 `TradingPointIdentity`

至少包含：

```text
trading_point_id
point_type
analysis_context_id
structure_level_ref
identity_status
identity_evidence_refs[]
provenance_bundle
position/time/price
confirmed_at
fingerprint
```

---

## 9.2 `IdentityStatus`

```text
CONFIRMED
REJECTED
PENDING_IDENTITY_EVIDENCE
```

`PENDING_IDENTITY_EVIDENCE` 只用于**当前分析模式要求 materialize 的身份必要证据尚未完成**。

它不用于策略等待。

---

# 10. B1 / B2 / B3 的理论边界

## 10.1 B1

标准 B1：

```text
>= 2 same-level central zones
+
strict trend relation (GG/DD)
+
trend divergence
```

关键：

- 一个中枢后的盘整背驰不是标准趋势 B1；
- `zone_count = 3` 只是客观事实；
- “3中枢一定比2中枢更强”不是原著定理；
- 如果都业华课程确认某种中枢数量/末端盘背增强质量，由 Practice/Quality 层解释。

---

## 10.2 B2：理论构成关系与证据 materialization 分开

原著买卖点定律：

```text
B1@direct-sublevel
DIRECTLY_CONSTITUTES
B2@higher-level
```

这是理论必然关系。

但：

> **理论上必然存在** 和 **当前 AnalysisContext 是否必须显式 materialize** 是两件事。

### STRICT_RECURSIVE

必须：

```text
direct-sublevel B1 materialized
+
relation evidence bound
```

否则：

```text
PENDING_IDENTITY_EVIDENCE
```

### FIXED_LEVEL_OPERATIONAL

原著第53、57课允许在选定操作/最小分析级别直接使用三类买卖点，而不要求每次都向下展开所有内部结构。

因此可以记录：

```text
constitution_semantics = THEORETICALLY_ENTAILED
materialization_status = NOT_REQUIRED_IN_THIS_CONTEXT
```

这不是否认 B2 的低级别 B1 构成定律。

如果以后在兼容的更低级别 AnalysisContext 中 materialize：

```text
DIRECTLY_CONSTITUTES
```

则补充 provenance；不应把固定级别历史身份静默改写。

如兼容上下文下无法 materialize，应触发理论/分解一致性审计，而不是默默忽略。

---

## 10.3 B2 空间位置属于 Quality/Evolution

以下不是基础 B2 身份门槛：

- 反弹是否重新进入前下降中枢；
- 是否达到 ZG；
- 回调是否守住 ZD；
- 是否进一步守住 ZG；
- 是否与 B3 重合。

所以：

```text
没有涨到 ZG
!= REJECTED B2
```

---

## 10.4 B3

原著严格边界：

```text
sublevel movement leaves center upward
+
first sublevel movement retest
+
pullback_low >= ZG
```

卖三镜像：

```text
pullback_high <= ZD
```

在 `FIXED_LEVEL_OPERATIONAL + SEGMENT_AS_SUBLEVEL_ATOM` 上下文中，formal Segment 可以承担这里的 sublevel movement unit 角色。

因此 Segment departure/retest **不必天然被视为工程近似**；前提是：

- minimum analysis level 明确；
- Segment 规则与该上下文一致；
- role binding 有 provenance。

强三买“不与中枢任一波动重叠”属于都业华 Practice/Quality，不能替换标准 ZG/ZD 身份边界。

---

## 10.5 多身份允许并存

同一结构位置可以同时存在：

```text
B2
B3
```

跨级别还可以：

```text
L1 B1
L2 B2
L2 B3
```

因此一个 price/time position 不能只能挂一个唯一枚举。

---

# 11. Identity / Quality / Strategy

## 11.1 Identity

只回答：

> 它在当前 AnalysisContext 中是不是 B1/B2/B3？

质量配置不得进入 identity detector。

---

## 11.2 Quality Facts

只保存客观事实，例如：

### B1

```text
zone_count
MACD ratio
price/movement power facts
additional lower-level exhaustion facts
```

### B2

```text
rebound vs ZD/ZG
retrace vs B1/ZD/ZG
retrace depth
B2+B3 coincidence
```

### B3

```text
distance from ZG/ZD
whether overlaps any center fluctuation
leave strength
retest depth
```

---

## 11.3 Evidence Scope

```text
SINGLE_LEVEL_OBSERVABLE
CROSS_LEVEL_IDENTITY_MATERIALIZED
CROSS_LEVEL_THEORETICALLY_ENTAILED
CROSS_LEVEL_QUALITY_OPTIONAL
```

这样可以同时支持 strict recursive 和 fixed-level operational。

---

## 11.4 StrategyDecision

```text
ACCEPTED
FILTERED
WAITING_FOR_STRATEGY_EVIDENCE
```

`REJECTED` 只属于 Identity。

例如：

```text
基础 B3 成立
但策略只做 Du 强三买
强度不足
=> FILTERED
```

---

# 12. Cross-Level Typed Relation Store

底层结构递归、区间套、买点构成应由不同算法执行，但可以共享同一个 typed relation store。

## 12.1 每条关系的硬元数据

至少包含：

```text
relation_id
relation_type
from_ref
from_structure_level_ref
from_analysis_context_id

to_ref
to_structure_level_ref
to_analysis_context_id

direction
status
as_of
confirmed_at
evidence_refs[]
theory_source
rule_version
fingerprint
```

关系本身也必须满足无未来函数和可审计要求。

---

## 12.2 `DIRECTLY_CONSTITUTES`

典型：

```text
B1@direct-sublevel
-> B2@higher-level
```

只表达直接次级别构成。

---

## 12.3 `REALIZES_EXTREMUM_OF`

表达：

```text
某个次级别以下买卖点
承载/实现
更高级别买卖点极值
```

不要求恰好是直接次级别。

---

## 12.4 `NARROWS_TO`

区间套过程：

```text
higher divergence segment
-> lower divergence segment
```

逐级收缩。

---

## 12.5 `LOCATES`

区间套最终定位：

```text
terminal lower-level structure
-> higher-level turning region/extremum
```

---

## 12.6 `COINCIDES`

表达已经独立成立的身份处于同一结构位置/区域。

工程容差必须版本化。

---

## 12.7 `CROSS_LEVEL_TURN_OF`

如未来需要把原著小级别背驰—大级别转折物化为 relation edge，应使用明确类型：

```text
lower-level turn fact
CROSS_LEVEL_TURN_OF
higher-level movement transition
```

不要用 generic `TRIGGERS`。

---

# 13. 区间套

区间套严格是自上而下定位：

```text
higher-level divergence segment
-> find corresponding lower-level divergence segment
-> continue narrowing
-> terminal precise region / extremum
```

不是：

```text
scan all lowest-level B1
-> guess which one will become higher-level point
```

区间套算法与 StructureLevel 递归算法分开执行。

共享 typed relation store，不共享“同一个递归函数”。

---

# 14. Movement Evolution

## 14.1 与 TradingPoint Engine 并列

```text
Movement / CentralZone / Divergence / Completion facts
├─> TradingPointIdentityEngine
└─> MovementEvolutionEngine
```

---

## 14.2 背驰后三类结果

原著第29、43课联合语义：

### 共同事实

```text
source movement at divergence level = COMPLETED/TERMINATED
```

### A. 最后中枢级别扩展

- source movement 已结束；
- 同一 underlying market data 可以被更高级别重新组合；
- 新的 higher-level interpretation 可能仍 FORMING；
- 不等于简单的“旧走势 + 独立新盘整”。

### B. 更大级别盘整

```text
completed source trend
+
new independent higher-level consolidation movement
```

### C. 反趋势

```text
completed source trend
+
reverse trend movement
```

反趋势可以是同级别或以上级别。

---

# 15. 原著跨级别转折与都业华“小转大”

## 15.1 `OriginalCrossLevelTurnFact`

属于：

```text
ORIGINAL_THEORY
```

表达：

- 背驰级别与当前走势级别可能不同；
- 小级别背驰可以通过后续结构引发更大级别转折；
- 大级别买卖点极值可能落在更低某一级别买卖点上。

---

## 15.2 `DuTerminationPattern.SMALL_TO_LARGE`

属于：

```text
DU_YEHUA_PRACTICE
```

它可以消费 `OriginalCrossLevelTurnFact`，但不能与原著跨级别定理直接声明为同义枚举。

---

# 16. 都业华 Practice Layer

## 16.1 `DuTerminationPattern`

当前只确认 taxonomy 级别：

1. 中枢背驰；
2. 盘整背驰；
3. 小转大；
4. 中枢无背驰直接终结。

课程目录和多个二手整理高度一致，但精确算法在没有直接课程证据前不能写死。

因此：

- 保留都业华原实践命名；
- 不擅自把“中枢背驰”重命名成“趋势背驰”；
- 不擅自把“中枢无背驰”唯一解释成中枢延伸/级别扩展；
- 每个正式算法落地前重新核验课程证据。

---

## 16.2 Du Quality

### B1

候选事实：

- 中枢数量；
- 背驰证据强度；
- 末端真实低级别盘背；
- 分型停顿；
- R 比率。

注意：

```text
zone_count = 3
```

是事实，不自动等于“比2强”。

只有课程规则确认后才由 Du evaluator 做强弱映射。

### B2

- 上涨进入原中枢程度；
- 是否达到 ZG；
- 回调守 B1 / ZD / ZG；
- 回调深度；
- 与 B3 重合。

### B3

- 基础 ZG/ZD 已成立；
- 是否不与中枢任何内部波动重叠；
- 离开力度；
- 回抽幅度。

---

## 16.3 非标准交易机会

使用：

```text
NonStandardTradingOpportunity
```

容纳：

- 原著大级别类一买/类二买；
- 都业华类二买；
- 分型重构买点。

不要创建 B4/B5。

---

# 17. Strategy 与 CompositeSignal

## 17.1 `QualityProfile`

控制：

> 已成立身份达到什么质量才接受。

例如：

- B1：只接受 zone_count >= 2 / >= 3；
- MACD evidence ratio；
- B2：反弹最低位置；
- B2：回调最低守位；
- B3：基础三买 / Du 强三买。

这些全部不能进入理论 identity detector。

---

## 17.2 `LocalizationProfile`

控制：

- 是否需要区间套；
- 最低定位到哪里；
- 是否要求 strict recursive materialization；
- 是否接受 fixed-level operational 结果。

---

## 17.3 `SignalProfile`

控制：

- 小一 + 大二；
- 小一 + 大三；
- 小一 + 大二三；
- 多级别同步；
- Du termination + trading point quality。

---

## 17.4 `CompositeSignal`

只读派生：

```text
TradingPointIdentity[]
+
CrossLevelRelation[]
+
QualityFacts[]
+
PracticePatterns[]
+
StrategyProfile
-> CompositeSignal
```

不建立 canonical `MarketReversalEvent`。

---

# 18. Theory Audit / Invariant Facilities

终局系统除了业务算法，还需要理论审计设施。

## 18.1 `TheoryInvariantSuite`

用于持续验证不会被实现者“优化”坏的硬规则。

示例：

```text
MarketInterval != StructureLevelRef
GeometricSegment != MovementType
GG/DD defines strict same-level trend separation
MACD alone must not define ORIGINAL_THEORY divergence
QualityProfile must not change TradingPointIdentity
NARROWS_TO != LOCATES
DIRECTLY_CONSTITUTES != REALIZES_EXTREMUM_OF
```

---

## 18.2 `TradingPointCompletenessInvariantChecker`

它不是新的买点检测器，而是理论审计器。

用途：

- 检查完整走势转换是否存在相应三类买卖点解释；
- 检查 B2/B3 overlap 是否允许；
- 检查 canonical B2 的 direct-sublevel constitution provenance；
- 检查 B3 是否是第一次有效回试；
- 检查买卖点完备性实现是否被后续重构破坏。

它只做验证，不生成交易信号。

---

## 18.3 Relation Invariant Tests

例如：

```text
confirmed_at >= all required evidence confirmed_at
as_of >= confirmed_at
relation endpoints belong to compatible contexts
no same-interval internal stroke masquerades as real lower-level context
```

---

# 19. 当前 PR #13 的准确定位

这部分必须比“整条路径都是 approximation”更精确。

当前大致路径：

```text
current interval bars
-> Stroke
-> formal GeometricSegment
-> SegmentCentralZone
-> B1/B2/B3
```

## 19.1 Segment / CentralZone 结构部分

**不能一刀切标成 PROJECT_POLICY approximation。**

如果经过专门审计确认：

1. 当前 Segment 符合项目选定的缠论线段规则；
2. `AnalysisContext.minimum_analysis_level` 明确；
3. `analysis_mode = FIXED_LEVEL_OPERATIONAL`；
4. `level_bootstrap_method = SEGMENT_AS_SUBLEVEL_ATOM`；
5. 所有 formal segment 的 role binding 可审计；

那么：

```text
Segment -> CentralZone
```

可以按原著第57课解释为合法的 fixed-level operational bootstrap。

因此当前技术债是：

> **缺少显式 AnalysisContext / bootstrap provenance，而不是“Segment 中枢理论上必然错误”。**

---

## 19.2 GG/DD 趋势门槛

当前：

```text
last.gg < previous.dd
last.dd > previous.gg
```

与原著第20课 strict trend 定理方向一致。

**不是技术债，不得改成只比较 ZG/ZD。**

---

## 19.3 MACD hard gate

当前 B1 使用 MACD 柱面积背驰作为正式判定 hard gate。

这一点仍是明确技术债。

正确 provenance 应更接近：

```text
theory_source = ORIGINAL_THEORY
analysis_mode = FIXED_LEVEL_OPERATIONAL
level_bootstrap = SEGMENT_AS_SUBLEVEL_ATOM
evidence_method = PROJECT_POLICY_MACD_APPROXIMATION
```

而不是把整个 trading point 标成：

```text
SEGMENT_APPROXIMATION
```

---

## 19.4 当前 B2

如果固定级别 operational context 成立：

```text
B1
-> next sublevel-atom rebound
-> first retrace
```

可以作为该上下文内的 operational B2。

理论上的：

```text
direct-sublevel B1 constitution
```

仍然成立，但不要求当前固定级别分析每次都向下 materialize。

---

## 19.5 当前 B3

同理，如果 formal Segment 在当前最小分析级别承担 sublevel atom：

```text
segment departure
+
first segment retest
+
ZG/ZD boundary
```

可以是 fixed-level operational B3，而非天然工程近似。

---

## 19.6 当前真正需要迁移的旧模型

### TD-1：缺少正交 provenance

需要逐步引入：

```text
AnalysisContext
AnalysisMode
LevelBootstrapMethod
EvidenceMethod
```

### TD-2：MACD 与 Divergence semantic 耦合

拆为：

```text
DivergenceFact
DivergenceEvidence
```

### TD-3：旧 `TrendDivergence` 过度耦合

不要继续把：

- 理论背驰；
- MACD；
- 历史伪递归字段；
- 强弱判断；

塞在一个对象里。

### TD-4：缺少 DecompositionEngine / StructureInterpretation

当前确定性路径可以继续运行，但长期要能表达同级别分解与后续合法重组。

---

# 20. 推荐开发顺序

终局架构现在设计完整，但仍然不允许一次开发全部。

## Phase 0：数据/时间/无未来函数基础

持续加固：

- 时间连续性；
- commit ledger；
- `confirmed_at`；
- fingerprint；
- prefix consistency；
- replay/realtime 一致。

---

## Phase 1：当前 Fixed-Level MVP 收口 —— 当前优先

只做：

1. 保留现有单级别 B1/B2/B3；
2. 明确 `AnalysisContext`；
3. 明确：
   ```text
   analysis_mode = FIXED_LEVEL_OPERATIONAL
   level_bootstrap_method = SEGMENT_AS_SUBLEVEL_ATOM
   ```
   前提是完成一次 Segment 语义专项审计；
4. Identity / Quality / Strategy 拆开；
5. 实现 `QualityProfile`；
6. 实现 `StrategyFilter`；
7. 保存 B1/B2/B3 原始质量事实；
8. 把 MACD 记录为独立 evidence method；
9. 真实行情、prefix consistency、无重绘验证。

明确不做：

- strict recursive materialization；
- 区间套；
- 小转大；
- 共振；
- 真实低级别末端盘背。

---

## Phase 2：DecompositionEngine + Movement 本体

实现：

- `DecompositionEngine`；
- `SAME_LEVEL_DECOMPOSITION`；
- `StructureInterpretation`；
- versioned recomposition；
- `MovementType`；
- `MovementCompletionState`；
- `CentralZoneLifecycle`；
- fixed-level movement semantics。

---

## Phase 3：Divergence Semantics + B1

实现：

- `DivergenceFact`；
- `DivergenceLifecycle`；
- `DivergenceEvidence`；
- MACD 解耦；
- trend/consolidation divergence；
- B1 identity 与 evidence audit。

---

## Phase 4：STRICT_RECURSIVE Structure Level

实现：

```text
Movement@L(n-1)
-> CentralZone@L(n)
-> Movement@L(n)
```

以及：

- `StructureLevelGraph`；
- direct sub/super level；
- recursive composition；
- `LOWER_LEVEL_MOVEMENT_PROJECTION`。

---

## Phase 5：Cross-Level TradingPoint Identity

实现：

- strict B2 materialized `DIRECTLY_CONSTITUTES`；
- B3 direct-sublevel movement evidence；
- `REALIZES_EXTREMUM_OF`；
- B2+B3 coincidence；
- multi-identity audit。

---

## Phase 6：区间套

实现：

- `NARROWS_TO`；
- `LOCATES`；
- `LocalizationProfile`；
- 逐级 divergence evidence chain。

---

## Phase 7：Movement Evolution / Recomposition

实现：

- `RECOMPOSES_FROM`；
- source vs higher-level lifecycle；
- 中枢延伸/新生/扩展；
- 背驰后三类演化；
- B3 后演化；
- 合法/待确认/已排除分支。

---

## Phase 8：Original Cross-Level Turn + Du Practice

先原著事实，再都业华实践：

- `OriginalCrossLevelTurnFact`；
- `DuTerminationPattern`；
- 小转大；
- 四种终结；
- 类二买；
- 分型重构；
- 分型停顿；
- R 比率；
- 黄金分割。

每项独立来源、独立测试。

---

## Phase 9：CompositeSignal / Resonance

最后实现：

- 小一 + 大二；
- 小一 + 大三；
- 小一 + 大二三；
- 多级别同步；
- SignalProfile；
- CompositeSignal。

---

# 21. 每次新增规则前的归类检查

任何规则进入代码前必须回答：

1. `theory_source` 是什么？
2. `analysis_mode` 是什么？
3. `level_bootstrap_method` 是什么？
4. `decomposition_policy` 是什么？
5. 它是 Geometric Fact 还是 Movement Fact？
6. 它属于哪个 `StructureLevelRef`？
7. 它是 Divergence semantic 还是 Evidence？
8. 它是 IdentityEvidence 吗？
9. 是理论必然但 operational context 可不 materialize 的证据吗？
10. 它只是 QualityFact 吗？
11. 它属于哪种 typed CrossLevelRelation？
12. 它属于 ORIGINAL 还是 Du Practice？
13. 它只是策略过滤吗？
14. 它只是 CompositeSignal 吗？
15. `as_of / confirmed_at / evidence_refs / rule_version` 是否齐全？

如果无法归类，**不得直接写进 TradingPointDetector。**

---

# 22. 理论依据索引

以下链接为公开原文镜像。架构以课文和定理本身为依据。

## 22.1 缠中说禅原著

1. **中枢、盘整、趋势、走势终完美、B2构成定律、同步共振**  
   《教你炒股票17》  
   https://iczsc.com/read/017/

2. **中枢、走势类型与完成**  
   《教你炒股票18》  
   https://iczsc.com/read/018/

3. **GG/DD、ZG/ZD、趋势/级别扩展、第三类买卖点**  
   《教你炒股票20》  
   https://iczsc.com/read/020/

4. **三类买卖点完备性、B2空间位置、B2+B3重合**  
   《教你炒股票21》  
   https://iczsc.com/read/021/

5. **MACD辅助判断背驰**  
   《教你炒股票24》  
   https://iczsc.com/read/024/

6. **趋势背驰、盘整背驰、类一买、区间套基础**  
   《教你炒股票27》  
   https://iczsc.com/read/027/

7. **背驰后三类演化、最后中枢扩展**  
   《教你炒股票29》  
   https://iczsc.com/read/029/

8. **严格递归级别与实用级别分析**  
   《教你炒股票35》  
   https://iczsc.com/read/035/

9. **走势连接结合性、多义性、重新组合**  
   《教你炒股票36》  
   https://iczsc.com/read/036/

10. **同级别分解、唯一分解规则**  
    《教你炒股票38》  
    https://iczsc.com/read/038/

11. **背驰级别与走势级别、原走势终止**  
    《教你炒股票43》  
    https://iczsc.com/read/043/

12. **多级别显微镜、低级别 Movement 在高级别投影为线段**  
    《教你炒股票53》  
    https://iczsc.com/read/053/

13. **最小分析级别 bootstrap：线段承担次级别走势单元角色**  
    《教你炒股票57》  
    https://iczsc.com/read/057/

---

## 22.2 都业华课程/公开资料

可以较可靠确认课程主题包括：

- 背驰及盘整背驰；
- 一买定义及实战；
- 一买走势分类；
- 区间套；
- 四种终结模式；
- 二买定义及实战；
- 二买走势分类；
- 走势中枢重新定义；
- 三买定义及定位；
- 三买后走势演变；
- 大小周期组合等。

课程主题可以确认；精确算法必须尽量回到原课程。

---

# 23. 当前迁移结论

近期项目仍然只做：

```text
Fixed-Level 单级别买卖点
-> provenance 补齐
-> Identity / Quality / Strategy 分离
-> 可配置质量门槛
-> 严格审计
```

这轮架构修订后的关键结论：

1. **不再把当前 Segment 路径整体粗暴标成 `SEGMENT_APPROXIMATION`。**
2. 第57课允许正式 Segment 在选定最小分析级别中承担 sublevel atom 角色。
3. 当前 Segment -> CentralZone 是否可以正式归入 `FIXED_LEVEL_OPERATIONAL`，仍需对项目自身 Segment 语义做一次专项审计。
4. 当前 GG/DD strict trend 条件保留，不改成 ZG/ZD。
5. 当前 MACD hard gate 仍属于 EvidenceMethod 技术债。
6. 以后真正 strict recursion 仍建立在：
   ```text
   Movement@L(n-1)
   -> CentralZone@L(n)
   -> Movement@L(n)
   ```
   上，而不是在 Segment 对象上无限增加递归字段。
7. fixed-level operational 与 strict recursive 可以长期并存，并通过正交 provenance 明确区分。

---

# 24. 最终一句话

> **缠论级别既可以严格按 Movement→CentralZone→Movement 递归生成，也可以在明确的最小分析级别中把正式线段作为次级别原子进行固定级别操作分析；线段与走势类型仍是不同本体，只是在特定上下文承担角色。所有结果必须用 theory source、analysis mode、bootstrap method、decomposition policy、evidence method 等正交 provenance 描述；买卖点身份、质量与策略严格分离；跨级别构成、极值承载、区间套定位和共振分别建模；历史结构允许以 versioned StructureInterpretation 合法重组但不得静默改写；当前项目优先把 fixed-level MVP 做准，严格递归、区间套、小转大和共振按阶段逐步实现。**
