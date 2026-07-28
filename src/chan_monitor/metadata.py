from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class AnalysisMetadata:
    """描述一次 K 线分析的数据来源，避免把模拟数据误认为真实行情。"""

    source_name: str = "未标注数据源"
    market: str = "未标注市场"
    source_url: str | None = None
    is_demo: bool = False
    retrieved_at: datetime | None = None
    note: str | None = None

    @classmethod
    def binance_rest(cls, *, market: str, source_url: str) -> "AnalysisMetadata":
        return cls(
            source_name="Binance REST API",
            market=market,
            source_url=source_url,
            is_demo=False,
            retrieved_at=datetime.now(timezone.utc),
            note="已确认结构仅使用已收盘 K；当前 K 仅用于实时虚线候选",
        )

    @classmethod
    def demo(cls) -> "AnalysisMetadata":
        return cls(
            source_name="内置模拟数据",
            market="DEMO / 模拟市场",
            is_demo=True,
            retrieved_at=datetime.now(timezone.utc),
            note="确定性波形，仅用于界面与算法边界测试，不代表真实行情",
        )
