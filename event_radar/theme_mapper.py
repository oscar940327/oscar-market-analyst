from __future__ import annotations

import re
from typing import Any

from event_radar.event_strength import score_news_event_strength
from event_radar.models import NewsEvent, ThemeMatch


TICKER_TIERS = ("core", "secondary", "extended")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def theme_tickers_and_tiers(theme: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Return theme tickers with optional core/secondary/extended tier metadata."""
    tickers: list[str] = []
    tiers: dict[str, str] = {}

    for tier in TICKER_TIERS:
        for ticker in theme.get(tier) or []:
            normalized = str(ticker).upper()
            if normalized not in tiers:
                tickers.append(normalized)
                tiers[normalized] = tier

    if not tickers:
        for ticker in theme.get("tickers") or []:
            normalized = str(ticker).upper()
            if normalized not in tiers:
                tickers.append(normalized)
                tiers[normalized] = "core"

    return tickers, tiers


def match_themes(
    event: NewsEvent,
    theme_map: dict[str, Any],
    min_score: int = 1,
) -> list[ThemeMatch]:
    text = _normalize(event.text)
    event_strength = score_news_event_strength(event)
    matches: list[ThemeMatch] = []

    for theme_key, theme in (theme_map.get("themes") or {}).items():
        keywords = theme.get("keywords") or []
        matched = []

        for keyword in keywords:
            normalized_keyword = _normalize(str(keyword))
            if normalized_keyword and normalized_keyword in text:
                matched.append(str(keyword))

        if len(matched) < min_score:
            continue

        score = len(matched)
        confidence = min(1.0, 0.35 + score * 0.2)
        tickers, ticker_tiers = theme_tickers_and_tiers(theme)
        matches.append(
            ThemeMatch(
                theme=str(theme.get("label") or theme_key),
                category=str(theme.get("category") or "General"),
                tickers=tickers,
                matched_keywords=matched,
                score=score,
                direction=str(theme.get("direction") or "mixed"),
                confidence=round(confidence, 2),
                event_strength=event_strength,
                ticker_tiers=ticker_tiers,
            )
        )

    return sorted(matches, key=lambda item: item.score, reverse=True)
