from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from event_radar.config import load_theme_map
from event_radar.theme_mapper import theme_tickers_and_tiers
from perception.price_fetcher import fetch_ohlcv
from pipeline.db import get_connection, upsert_prices


@dataclass(frozen=True)
class PriceUpdateResult:
    ticker: str
    start_date: str
    rows_saved: int = 0
    latest_before: str | None = None
    skipped: bool = False
    error: str = ""


def tickers_from_theme_map(theme_map: dict[str, Any] | None = None) -> list[str]:
    theme_map = theme_map or load_theme_map()
    tickers = {"SPY", "QQQ"}
    for theme in (theme_map.get("themes") or {}).values():
        for ticker in theme_tickers_and_tiers(theme)[0]:
            tickers.add(ticker)
    return sorted(tickers)


def _latest_trade_date(conn, ticker: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(trade_date) FROM daily_prices WHERE ticker=?",
        (ticker.upper(),),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def _start_date_for_update(
    latest_trade_date: str | None,
    lookback_days: int,
    refresh_overlap_days: int,
) -> str:
    if latest_trade_date:
        latest = datetime.strptime(latest_trade_date, "%Y-%m-%d").date()
        return (latest - timedelta(days=refresh_overlap_days)).isoformat()
    return (date.today() - timedelta(days=lookback_days)).isoformat()


def update_radar_prices(
    tickers: list[str] | None = None,
    lookback_days: int = 220,
    refresh_overlap_days: int = 10,
    max_retries: int = 2,
    dry_run: bool = False,
) -> list[PriceUpdateResult]:
    tickers = sorted({ticker.upper() for ticker in (tickers or tickers_from_theme_map())})
    results: list[PriceUpdateResult] = []

    conn = get_connection()
    try:
        for ticker in tickers:
            latest = _latest_trade_date(conn, ticker)
            start_date = _start_date_for_update(
                latest,
                lookback_days=lookback_days,
                refresh_overlap_days=refresh_overlap_days,
            )

            if dry_run:
                results.append(
                    PriceUpdateResult(
                        ticker=ticker,
                        start_date=start_date,
                        latest_before=latest,
                        skipped=True,
                    )
                )
                continue

            try:
                df = fetch_ohlcv(ticker, start_date, max_retries=max_retries)
                if df.empty:
                    results.append(
                        PriceUpdateResult(
                            ticker=ticker,
                            start_date=start_date,
                            latest_before=latest,
                            rows_saved=0,
                        )
                    )
                    continue
                upsert_prices(conn, df, ticker)
                results.append(
                    PriceUpdateResult(
                        ticker=ticker,
                        start_date=start_date,
                        latest_before=latest,
                        rows_saved=len(df),
                    )
                )
            except Exception as exc:
                results.append(
                    PriceUpdateResult(
                        ticker=ticker,
                        start_date=start_date,
                        latest_before=latest,
                        error=str(exc),
                    )
                )
    finally:
        conn.close()

    return results
