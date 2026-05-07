from __future__ import annotations

from typing import Any

from event_radar.llm_classifier import classify_event_with_llm
from event_radar.models import AlertDraft, ClassifiedEvent, NewsEvent
from event_radar.repository import EventRepository, priority_for_match
from event_radar.theme_mapper import match_themes


def classify_events(
    events: list[NewsEvent],
    theme_map: dict[str, Any],
    min_theme_score: int = 1,
    use_llm: bool = False,
    llm_config: dict[str, Any] | None = None,
) -> list[ClassifiedEvent]:
    classified = []
    for index, event in enumerate(events, start=1):
        if use_llm:
            print(f"Classifying event {index}/{len(events)}: {event.title[:90]}")
        matches = []
        if use_llm:
            llm_config = llm_config or {}
            try:
                matches = classify_event_with_llm(
                    event,
                    theme_map,
                    model=str(llm_config.get("model") or "openrouter/deepseek/deepseek-chat-v3-0324"),
                    temperature=float(llm_config.get("temperature", 0.1)),
                    max_tokens=int(llm_config.get("max_tokens", 700)),
                    debug=bool(llm_config.get("debug", False)),
                )
            except Exception as exc:
                print(f"LLM classification failed, using keyword fallback: {exc}")

        if not matches:
            matches = match_themes(event, theme_map, min_score=min_theme_score)
        if matches:
            classified.append(ClassifiedEvent(news=event, matches=matches))
    return classified


def build_alert_drafts(
    event_id: int,
    classified: ClassifiedEvent,
    high_priority_min_score: int = 3,
    watchlist_min_score: int = 2,
) -> list[AlertDraft]:
    alerts: list[AlertDraft] = []

    for match in classified.matches:
        priority = priority_for_match(match, high_priority_min_score, watchlist_min_score)
        keyword_text = ", ".join(match.matched_keywords[:4])
        reason = (
            f"{match.theme}: matched {keyword_text}; "
            f"direction={match.direction}; confidence={match.confidence:.2f}"
        )

        for ticker in match.tickers:
            alerts.append(
                AlertDraft(
                    event_id=event_id,
                    ticker=ticker,
                    theme=match.theme,
                    priority=priority,
                    reason=reason,
                    metadata={
                        "category": match.category,
                        "direction": match.direction,
                        "matched_keywords": match.matched_keywords,
                        "theme_score": match.score,
                    },
                )
            )

    return alerts


def persist_classified_events(
    classified_events: list[ClassifiedEvent],
    repository: EventRepository,
    high_priority_min_score: int = 3,
    watchlist_min_score: int = 2,
) -> tuple[int, int]:
    event_count = 0
    alert_count = 0

    for classified in classified_events:
        event_id = repository.save_event(classified)
        event_count += 1
        alerts = build_alert_drafts(
            event_id,
            classified,
            high_priority_min_score=high_priority_min_score,
            watchlist_min_score=watchlist_min_score,
        )
        alert_count += repository.save_alerts(alerts)

    return event_count, alert_count
