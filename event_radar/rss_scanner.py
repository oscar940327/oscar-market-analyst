from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from event_radar.models import NewsEvent


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    if child is None or child.text is None:
        return ""
    return html.unescape(child.text).strip()


def _parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def fetch_rss_events(feeds: list[dict[str, Any]], limit: int = 30) -> list[NewsEvent]:
    events: list[NewsEvent] = []

    for feed in feeds:
        name = str(feed.get("name") or "RSS")
        url = str(feed.get("url") or "")
        headers = DEFAULT_HEADERS | {
            str(key): str(value)
            for key, value in (feed.get("headers") or {}).items()
        }
        if not url:
            continue

        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"RSS fetch failed for {name}: {exc}")
            continue

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            print(f"RSS parse failed for {name}: {exc}")
            continue

        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall(".//item")
        for item in items:
            title = _text(item, "title")
            if not title:
                continue

            events.append(
                NewsEvent(
                    title=title,
                    summary=_text(item, "description"),
                    url=_text(item, "link"),
                    source=name,
                    published_at=_parse_date(_text(item, "pubDate")),
                )
            )

            if len(events) >= limit:
                return events

    return events
