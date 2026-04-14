"""
historical_news_fetcher.py — Polygon.io 歷史新聞抓取器（單一查詢版）

回到簡單的邏輯：抓回所有新聞，按時間排序，每天取最新 15 篇。
不做分類，因為實驗證明多維度分類反而稀釋了重要訊號。
"""
import os
import time
import datetime as datetime_module
from dataclasses import dataclass

import requests


@dataclass
class HistoricalNewsItem:
    headline: str
    summary: str
    url: str
    source: str
    datetime: int
    related_ticker: str

    @property
    def date(self):
        return datetime_module.datetime.fromtimestamp(self.datetime).date()


def _iso_to_timestamp(iso_str: str) -> int:
    try:
        dt = datetime_module.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return 0


def fetch_historical_news(
    ticker: str,
    from_date: str,
    to_date: str,
    max_retries: int = 3,
    page_limit: int = 1000,
    fetch_all_pages: bool = True,
) -> list[HistoricalNewsItem]:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print("  ⚠️ POLYGON_API_KEY not set")
        return []

    url = "https://api.polygon.io/v2/reference/news"
    params = {
        "ticker": ticker,
        "published_utc.gte": from_date,
        "published_utc.lte": to_date,
        "limit": page_limit,
        "sort": "published_utc",
        "order": "desc",
        "apiKey": api_key,
    }

    all_results: list[HistoricalNewsItem] = []
    next_url: str | None = None
    page_num = 0

    while True:
        page_num += 1

        for attempt in range(1, max_retries + 1):
            try:
                if next_url:
                    full_url = next_url
                    if "apiKey=" not in full_url:
                        sep = "&" if "?" in full_url else "?"
                        full_url = f"{full_url}{sep}apiKey={api_key}"
                    response = requests.get(full_url, timeout=30)
                else:
                    response = requests.get(url, params=params, timeout=30)

                if response.status_code == 429:
                    wait = 15 * attempt
                    print(f"    ⏳ {ticker}: rate limited, wait {wait}s...")
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                data = response.json()
                break

            except requests.exceptions.RequestException as e:
                if attempt == max_retries:
                    print(f"    ❌ {ticker}: Polygon error after {max_retries} retries: {e}")
                    return all_results
                time.sleep(3 * attempt)
        else:
            break

        page_items = data.get("results", [])
        for item in page_items:
            published = item.get("published_utc", "")
            ts = _iso_to_timestamp(published)
            headline = item.get("title", "")
            summary = (item.get("description") or "")[:200]

            publisher = item.get("publisher", {})
            source = publisher.get("name", "") if isinstance(publisher, dict) else str(publisher)

            all_results.append(HistoricalNewsItem(
                headline=headline,
                summary=summary,
                url=item.get("article_url", ""),
                source=source,
                datetime=ts,
                related_ticker=ticker,
            ))

        next_url = data.get("next_url")
        if not fetch_all_pages or not next_url or len(page_items) == 0:
            break

        print(f"    📄 {ticker}: fetched page {page_num} ({len(page_items)} items), next page in 13s...")
        time.sleep(13)

    all_results.sort(key=lambda x: x.datetime)
    print(f"  ✅ {ticker}: got {len(all_results)} total articles from Polygon ({page_num} page(s))")
    return all_results


def group_news_by_date(
    news_items: list[HistoricalNewsItem],
    max_per_day: int = 15,
) -> dict[str, list[HistoricalNewsItem]]:
    """按日期分組，每天取最新 15 篇"""
    grouped: dict[str, list[HistoricalNewsItem]] = {}
    for item in news_items:
        if item.datetime == 0:
            continue
        d = datetime_module.datetime.fromtimestamp(item.datetime).strftime("%Y-%m-%d")
        grouped.setdefault(d, []).append(item)

    for d in grouped:
        grouped[d] = sorted(grouped[d], key=lambda x: x.datetime, reverse=True)[:max_per_day]

    return grouped


def format_news_for_llm(news_items: list[HistoricalNewsItem]) -> str:
    """把新聞列表格式化給 LLM"""
    if not news_items:
        return "No news for this date."

    lines = []
    for i, item in enumerate(news_items, 1):
        lines.append(f"[{i}] {item.headline}")
        if item.source:
            lines.append(f"    Source: {item.source}")
        if item.summary:
            lines.append(f"    {item.summary[:200]}")
        lines.append("")

    return "\n".join(lines)