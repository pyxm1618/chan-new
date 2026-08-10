# 架构实现状态补充

> 日期：2026-08-10  
> 适用基线：`main` 已合入 PR #13 与 PR #15 之后的 v0.11.0 fixed-level baseline。  
> 作用：补充 `docs/ARCHITECTURE.md` 中与“当前实现状态”有关、已经因 PR #15 专项审计而变化的部分。目标架构本体不因此改变。

## 1. 已完成的 fixed-level bootstrap qualification

PR #15 已完成并通过以下专项资格审计与修复：

- Lesson 67/77 第二种情况的 reverse feature-sequence 确认，不再递归复用 primary detector 的未来 `actual_break` 语义；
- formal trading-point facade 只接受真实、identity-matching、已 committed 的 `SegmentEvidence`，调用方提供的 `segment_commit_times` 不能伪造 formal provenance；
- `SegmentEvidence.segment_index`、`committed_at` 类型/时区以及结构可用时间均在 formal 边界 fail closed 校验；
- Lesson 78 的 Segment 实际价格区间使用组成笔真实 high/low，而不是只使用形式端点；
- SegmentCentralZone 独立 reference 与 fixture 已迁移到实际组成笔区间语义；
- formal TradingPoint 集成测试已经覆盖 `detect_segments -> committed SegmentEvidence -> formal detector` 的真实 provenance 链；
- 原著 fixed-level 默认 `min_bi_len=7` 已统一到库、CLI 和 Streamlit 生产入口，`6` 仅保留为显式兼容选择；
- Python 3.10 / 3.11 / 3.12 / 3.13 CI 在最终 qualification head 上全部通过。

因此，`docs/ARCHITECTURE.md` 中任何仍表述为“项目自身 Segment 语义专项审计尚未完成 / 仍需完成”的实现状态描述，均由本文更新为：

> **Segment 语义与 formal provenance 的专项 qualification 已完成。**

## 2. 仍未完成的架构迁移

上述 qualification PASS 不等于终局架构已经实现。当前仍缺少或尚未完成：

- 显式 `AnalysisContext`；
- 显式 `minimum_analysis_level_ref`；
- 正式 `SegmentRoleBinding` / `SEGMENT_AS_SUBLEVEL_ATOM` provenance materialization；
- Identity / Quality / Strategy 的完整对象级拆分；
- `DivergenceFact` 与 `DivergenceEvidence` 的正式解耦；
- 将 MACD hard gate 从当前实现方式迁移为可审计、可替换的 EvidenceMethod；
- `DecompositionEngine`、versioned `StructureInterpretation` 与 Movement 本体；
- strict recursive structure-level materialization；
- 区间套、跨级别买卖点构成、小转大、共振等后续阶段。

因此当前代码最准确的定位仍是：

```text
ORIGINAL_THEORY-oriented fixed-level operational implementation
+
qualified formal Segment / SegmentEvidence bootstrap boundary
+
尚未 materialize 完整 AnalysisContext / bootstrap provenance ontology
+
MACD evidence coupling 仍属于后续技术债
```

## 3. 对 ARCHITECTURE.md 当前状态段落的解释

`docs/ARCHITECTURE.md` 是长期 Target Architecture 文档，其核心本体、递归关系、typed provenance、Identity/Quality/Strategy 边界以及分阶段路线仍有效。

对于其中第 19、20、23 节涉及“当前 PR #13 / 当前迁移状态”的文字，应按以下更新理解：

1. PR #13 已与 qualification PR #15 一并进入 `main`，不再是待合入分支；
2. Segment 语义专项审计已完成，不再是 Phase 1 的未决前置条件；
3. Phase 1 后续重点转为显式 `AnalysisContext` / bootstrap provenance、Identity/Quality/Strategy 分离、EvidenceMethod 解耦与真实行情一致性验证；
4. strict recursion、区间套、小转大和共振仍不属于当前已完成范围。

## 4. 不改变的长期结论

以下架构结论保持不变：

- `GeometricSegment != MovementType`；
- fixed-level operational 与 strict recursive 均为合法但必须显式区分的分析模式；
- formal Segment 可以在明确最小分析级别的上下文中承担 sublevel atom 角色；
- GG/DD 仍是 strict same-level trend separation；
- MACD 是证据方法，不是背驰理论定义本身；
- TradingPoint Identity、QualityFacts、StrategyDecision 必须硬隔离；
- 历史结构允许 versioned recomposition，但不得静默改写；
- 跨级别构成、极值承载、区间套定位和共振必须使用不同 typed relation / composite 语义。
