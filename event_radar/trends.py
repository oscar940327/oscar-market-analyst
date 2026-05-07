from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from event_radar.repository import EventRepository
from pipeline.db import load_prices


@dataclass(frozen=True)
class TrendStateResult:
    theme: str
    ticker: str
    status: str
    reason: str
    last_close: float | None
    high_watermark: float | None


@dataclass(frozen=True)
class TrendThresholds:
    cooling_no_news_days: int = 5
    closed_no_news_days: int = 20
    cooling_drawdown_pct: float = 0.08
    closed_drawdown_pct: float = 0.15


def _pct_change(df: pd.DataFrame, days: int) -> float | None:
    if df.empty or len(df) <= days:
        return None
    start = float(df["close"].iloc[-days - 1])
    end = float(df["close"].iloc[-1])
    if start == 0:
        return None
    return (end - start) / start


def _underperforming_benchmark(
    repository: EventRepository,
    ticker_prices: pd.DataFrame,
    days: int = 20,
) -> bool:
    ticker_return = _pct_change(ticker_prices, days)
    if ticker_return is None:
        return False
    benchmark_returns = []
    for benchmark in ["SPY", "QQQ"]:
        value = _pct_change(load_prices(repository.conn, benchmark), days)
        if value is not None:
            benchmark_returns.append(value)
    return bool(benchmark_returns and ticker_return < max(benchmark_returns))


def update_trend_states(
    repository: EventRepository,
    thresholds: TrendThresholds = TrendThresholds(),
    dry_run: bool = False,
) -> list[TrendStateResult]:
    rows = repository.conn.execute(
        """
        SELECT
            a.theme, a.ticker, MAX(a.alert_id), MAX(a.alert_date)
        FROM radar_alerts a
        WHERE a.status='open'
          AND a.technical_status IN ('confirmed', 'partial', 'unconfirmed')
        GROUP BY a.theme, a.ticker
        ORDER BY a.theme, a.ticker
        """
    ).fetchall()

    results: list[TrendStateResult] = []
    today = date.today()
    for theme, ticker, alert_id, last_event_date in rows:
        prices = load_prices(repository.conn, str(ticker))
        last_close = None
        high_watermark = None
        reasons = []
        status = "Active"

        days_since_news = (today - date.fromisoformat(str(last_event_date))).days
        if days_since_news >= thresholds.closed_no_news_days:
            status = "Closed"
            reasons.append(f"no related alert for {days_since_news} days")
        elif days_since_news >= thresholds.cooling_no_news_days:
            status = "Cooling"
            reasons.append(f"no related alert for {days_since_news} days")

        if not prices.empty:
            prices = prices.sort_index()
            last_close = float(prices.iloc[-1]["close"])
            after_alert = prices[prices.index >= pd.Timestamp(str(last_event_date))]
            if not after_alert.empty:
                high_watermark = float(after_alert["close"].max())
                drawdown = (last_close - high_watermark) / high_watermark
                if drawdown <= -thresholds.closed_drawdown_pct:
                    status = "Closed"
                    reasons.append(f"drawdown from high {drawdown:.2%}")
                elif drawdown <= -thresholds.cooling_drawdown_pct and status == "Active":
                    status = "Cooling"
                    reasons.append(f"drawdown from high {drawdown:.2%}")

            if len(prices) >= 21:
                ma20 = float(prices["close"].tail(20).mean())
                if last_close < ma20 and status == "Active":
                    status = "Cooling"
                    reasons.append("below MA20")

            if _underperforming_benchmark(repository, prices) and status == "Active":
                status = "Cooling"
                reasons.append("underperforming SPY/QQQ over 20d")

        reason = "; ".join(reasons) if reasons else "trend remains active"
        result = TrendStateResult(
            theme=str(theme),
            ticker=str(ticker),
            status=status,
            reason=reason,
            last_close=round(last_close, 2) if last_close is not None else None,
            high_watermark=round(high_watermark, 2) if high_watermark is not None else None,
        )
        results.append(result)

        if not dry_run:
            repository.upsert_trend_state(
                theme=str(theme),
                ticker=str(ticker),
                status=status,
                last_event_date=str(last_event_date),
                last_alert_id=int(alert_id),
                last_close=result.last_close,
                high_watermark=result.high_watermark,
                reason=reason,
            )

    return results
