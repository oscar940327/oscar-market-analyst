"""
news_fetcher.py — 新聞抓取器（單一查詢版）
回到簡單可靠的單一查詢邏輯。
"""
import os
from dataclasses import dataclass


@dataclass
class NewsItem:
    title: str
    snippet: str
    url: str
    source: str
    published_date: str | None = None


def fetch_news(
    ticker: str,
    company_name: str = "",
    max_results: int = 5,
    days: int = 3,
) -> list[NewsItem]:
    """用 Tavily API 抓取指定股票的最新新聞（單一查詢）"""
    api_key = os.getenv("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEYS", "").split(",")[0].strip()
    if not api_key:
        print(f"  ⚠️ {ticker}: TAVILY_API_KEY not set, skipping news")
        return []

    try:
        from tavily import TavilyClient
    except ImportError:
        print("  ⚠️ tavily-python not installed. Run: pip install tavily-python")
        return []

    search_term = f"{ticker} {company_name}".strip() if company_name else ticker
    query = f"{search_term} stock market news"

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,
            days=days,
            topic="news",
        )

        results = []
        for item in response.get("results", []):
            url = item.get("url", "")
            source = ""
            if "://" in url:
                source = url.split("://")[1].split("/")[0].replace("www.", "")

            results.append(NewsItem(
                title=item.get("title", ""),
                snippet=item.get("content", "")[:500],
                url=url,
                source=source,
                published_date=item.get("published_date") or item.get("publishedDate"),
            ))

        print(f"  ✅ {ticker}: fetched {len(results)} news articles")
        return results

    except Exception as e:
        print(f"  ⚠️ {ticker}: Tavily error: {e}")
        return []


def format_news_for_llm(news_items: list[NewsItem]) -> str:
    if not news_items:
        return "No recent news found."

    lines = []
    for i, item in enumerate(news_items, 1):
        date_str = f" ({item.published_date})" if item.published_date else ""
        lines.append(f"[{i}] {item.title}{date_str}")
        lines.append(f"    Source: {item.source}")
        lines.append(f"    {item.snippet[:200]}")
        lines.append("")

    return "\n".join(lines)