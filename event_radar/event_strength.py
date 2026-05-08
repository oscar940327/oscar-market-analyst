from __future__ import annotations

import re

from event_radar.models import NewsEvent


def score_news_event_strength(event: NewsEvent) -> int:
    """Score whether a news item is a market-moving event or light commentary."""
    text = f"{event.title}\n{event.summary}".casefold()

    weak_patterns = [
        r"\bbest .*stock",
        r"\btop .*stock",
        r"\bstock pick",
        r"\bshould you buy\b",
        r"\bcould be\b",
        r"\bgot \$",
        r"\bby 20\d{2}\b",
        r"\binvestors .* ignoring\b",
        r"\bmotley fool\b",
        r"\bcathie wood\b",
        r"\bopinion\b",
    ]
    if any(re.search(pattern, text) for pattern in weak_patterns):
        return 25

    major_patterns = [
        r"\braises? guidance\b",
        r"\blowers? guidance\b",
        r"\bincreases? .*capex\b",
        r"\bcuts? production\b",
        r"\bdisrupts? .*supply\b",
        r"\bsanctions?\b",
        r"\bconflict\b",
        r"\bceasefire\b",
        r"\bopec\b",
    ]
    if any(re.search(pattern, text) for pattern in major_patterns):
        return 90

    earnings_patterns = [
        r"\bearnings\b",
        r"\brevenue\b",
        r"\bmargin\b",
        r"\bforecast\b",
        r"\boutlook\b",
        r"\bguidance\b",
    ]
    if any(re.search(pattern, text) for pattern in earnings_patterns):
        return 85

    analyst_patterns = [
        r"\banalyst\b",
        r"\bupgrade\b",
        r"\bdowngrade\b",
        r"\bprice target\b",
        r"\binitiates?\b",
    ]
    if any(re.search(pattern, text) for pattern in analyst_patterns):
        return 70

    price_commentary_patterns = [
        r"\bprices? today\b",
        r"\bholds near\b",
        r"\bopens? at\b",
        r"\bjumps\b",
        r"\bfalls\b",
    ]
    if any(re.search(pattern, text) for pattern in price_commentary_patterns):
        return 40

    return 50
