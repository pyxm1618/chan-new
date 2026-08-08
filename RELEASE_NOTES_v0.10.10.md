# v0.10.10 修复说明

## 修复目标

根治“已确认线段 / 中枢依赖可回撤笔，后续又消失或右边界缩回”的问题。

v0.10.9-fixed 的 `strokes[:-1]` 已被彻底删除。新版本不再用固定尾部长度猜测稳定性。

## 新状态模型

- `detected_strokes`：原始笔检测器当前输出，允许回退，仅供审计。
- `all_strokes`：当前接受的完整笔链。
- `stable_strokes`：由后续结构确认事件封存的只增前缀。
- `provisional_strokes`：仍可能迁移或撤销的连续尾部。
- `detected_segments`：当前直接识别出的线段，尾部允许变化。
- `segments`：正式 COMMITTED 线段，只追加。
- `provisional_segments`：已检测但尚未提交的尾部线段。

正式线段通过 `DETECTED -> 下一线段出现 -> COMMITTED` 两阶段状态机提交。
正式笔中枢仅消费 `stable_strokes`，正式线段中枢仅消费 `segments`。

## 主要改动

- `src/chan_monitor/engine.py`
  - 新增 `StructureState`。
  - 分离完整、稳定、候选笔链。
  - 增加只追加正式线段账本。
  - 批处理与增量引擎统一使用同一状态机。
- `src/chan_monitor/segments.py`
  - 新增 `detect_segments_from_anchor()`，从已稳定共享端点继续扫描。
- `src/chan_monitor/live.py`
  - 已收盘数据中的候选尾部也进入虚线层，不再只处理未收盘 K 的差异。
- `src/chan_monitor/chart.py`
  - 仅 `stable_strokes` 和正式 `segments` 绘制实线。
  - 候选笔与候选线段统一绘制同色虚线。
- `app.py`
  - 明确显示完整笔链、稳定笔、候选笔、正式线段和候选线段。
- `scripts/validate_structure_stability.py`
  - 新增 1000 / 5000 根逐前缀单调性验证工具。

## 验证结果

```text
95 passed, 1 skipped
```

5000 根逐根扫描：

```text
候选笔链非前缀变化：175 次（允许）
稳定笔回撤：0
正式线段回撤：0
正式笔中枢消失：0
正式笔中枢右边界缩回：0
正式线段中枢消失：0
正式线段中枢右边界缩回：0
```

覆盖原反例与扩展反例：

```text
125→126、175→176、235→236、378→379、
403→404、633→634、810→811、990→991
```

验证命令：

```bash
PYTHONPATH=src pytest --disable-warnings
PYTHONPATH=src python scripts/validate_structure_stability.py --bars 5000
```
