from __future__ import annotations

import re
from typing import Any

from event_radar.models import NewsEvent, ThemeMatch


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def match_themes(
    event: NewsEvent,
    theme_map: dict[str, Any],
    min_score: int = 1,
) -> list[ThemeMatch]:
    text = _normalize(event.text)
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
        matches.append(
            ThemeMatch(
                theme=str(theme.get("label") or theme_key),
                category=str(theme.get("category") or "General"),
                tickers=[str(ticker).upper() for ticker in theme.get("tickers", [])],
                matched_keywords=matched,
                score=score,
                direction=str(theme.get("direction") or "mixed"),
                confidence=round(confidence, 2),
            )
        )

    return sorted(matches, key=lambda item: item.score, reverse=True)

