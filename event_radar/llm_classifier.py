from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from event_radar.models import NewsEvent, ThemeMatch


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "config" / ".env")


SYSTEM_PROMPT = """You classify market news for an event-driven alert system.
Output ONLY valid JSON. No markdown, no preamble.

Rules:
- Use only the allowed theme keys provided by the user.
- Prefer the predefined theme tickers. Add extra tickers only when directly implied by the news.
- Do not make buy/sell recommendations.
- If the news is not market-relevant, return {"relevant": false, "themes": []}.

JSON shape:
{
  "relevant": true,
  "themes": [
    {
      "theme_key": "allowed_theme_key",
      "confidence": 0.0,
      "direction": "bullish|bearish|mixed",
      "matched_rationale": "short reason",
      "extra_tickers": []
    }
  ]
}
"""


def _strip_markdown_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    return raw


def _theme_catalog(theme_map: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = []
    for key, theme in (theme_map.get("themes") or {}).items():
        catalog.append(
            {
                "theme_key": key,
                "label": theme.get("label") or key,
                "category": theme.get("category") or "General",
                "direction": theme.get("direction") or "mixed",
                "tickers": theme.get("tickers") or [],
                "keywords": theme.get("keywords") or [],
            }
        )
    return catalog


def _build_prompt(event: NewsEvent, theme_map: dict[str, Any]) -> str:
    catalog = _theme_catalog(theme_map)
    return (
        "Classify this market news into zero or more allowed themes.\n\n"
        f"ALLOWED_THEMES_JSON:\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
        "NEWS_JSON:\n"
        f"{json.dumps({'title': event.title, 'summary': event.summary, 'source': event.source}, ensure_ascii=False)}"
    )


def _call_llm(model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> str:
    import litellm

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if "openrouter" in model:
        kwargs["api_key"] = os.getenv("OPENROUTER_API_KEY")
    response = litellm.completion(**kwargs)
    return response.choices[0].message.content.strip()


def classify_event_with_llm(
    event: NewsEvent,
    theme_map: dict[str, Any],
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 700,
    debug: bool = False,
) -> list[ThemeMatch]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_prompt(event, theme_map)},
    ]
    raw = _call_llm(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    data = json.loads(_strip_markdown_json(raw))
    if debug:
        print(f"  LLM raw: {json.dumps(data, ensure_ascii=False)[:500]}")
    if not data.get("relevant"):
        if debug:
            print("  LLM decision: not relevant")
        return []

    themes = theme_map.get("themes") or {}
    matches: list[ThemeMatch] = []
    for item in data.get("themes") or []:
        theme_key = str(item.get("theme_key") or "")
        theme = themes.get(theme_key)
        if not theme:
            continue

        base_tickers = [str(ticker).upper() for ticker in theme.get("tickers") or []]
        extra_tickers = [
            str(ticker).upper()
            for ticker in item.get("extra_tickers") or []
            if re.fullmatch(r"[A-Z][A-Z0-9.]{0,5}", str(ticker).upper())
        ]
        tickers = sorted(set(base_tickers + extra_tickers))
        confidence = max(0.0, min(1.0, float(item.get("confidence") or 0.0)))
        rationale = str(item.get("matched_rationale") or "llm_match").strip()
        direction = str(item.get("direction") or theme.get("direction") or "mixed")

        matches.append(
            ThemeMatch(
                theme=str(theme.get("label") or theme_key),
                category=str(theme.get("category") or "General"),
                tickers=tickers,
                matched_keywords=[rationale[:120]],
                score=max(1, round(confidence * 4)),
                direction=direction,
                confidence=round(confidence, 2),
            )
        )

    if debug:
        if matches:
            labels = ", ".join(match.theme for match in matches)
            print(f"  LLM matched: {labels}")
        else:
            print("  LLM matched theme keys that are not in theme_map")

    return sorted(matches, key=lambda item: item.confidence, reverse=True)
