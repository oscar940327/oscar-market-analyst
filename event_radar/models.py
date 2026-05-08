from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class NewsEvent:
    title: str
    summary: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.summary}".strip()


@dataclass(frozen=True)
class ThemeMatch:
    theme: str
    category: str
    tickers: list[str]
    matched_keywords: list[str]
    score: int
    direction: str = "mixed"
    confidence: float = 0.0
    event_strength: int = 100


@dataclass(frozen=True)
class ClassifiedEvent:
    news: NewsEvent
    matches: list[ThemeMatch]
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def primary_match(self) -> ThemeMatch | None:
        if not self.matches:
            return None
        return sorted(self.matches, key=lambda item: item.score, reverse=True)[0]


@dataclass(frozen=True)
class AlertDraft:
    event_id: int
    ticker: str
    theme: str
    priority: str
    reason: str
    technical_status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingAlert:
    alert_id: int
    event_id: int
    ticker: str
    theme: str
    priority: str
    reason: str


@dataclass(frozen=True)
class TechnicalCheck:
    ticker: str
    technical_status: str
    priority: str
    close_price: float | None = None
    relative_strength: float | None = None
    breakout: bool = False
    volume_ratio: float | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RadarAlert:
    alert_id: int
    event_id: int
    alert_date: str
    ticker: str
    theme: str
    priority: str
    reason: str
    technical_status: str
    close_price: float | None
    relative_strength: float | None
    breakout: bool | None
    volume_ratio: float | None
    event_title: str
    event_source: str
    event_url: str
    event_published_at: str
    event_direction: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrendAlert:
    theme: str
    ticker: str
    status: str
    last_event_date: str
    last_close: float | None
    high_watermark: float | None
    reason: str
