from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from event_radar.models import PendingAlert, TechnicalCheck
from event_radar.repository import EventRepository
from pipeline.db import load_prices


@dataclass(frozen=True)
class TechnicalThresholds:
    breakout_lookback: int = 20
    major_breakout_lookback: int = 55
    volume_lookback: int = 20
    volume_ratio_min: float = 1.3
    relative_strength_days: int = 20
    high_priority_confirmations: int = 3
    watchlist_confirmations: int = 1
    stop_loss_pct: float = 0.08
    first_take_profit_pct: float = 0.10
    second_take_profit_pct: float = 0.20
    trailing_stop_pct: float = 0.08


def _pct_change(df: pd.DataFrame, days: int) -> float | None:
    if df.empty or len(df) <= days:
        return None
    start = float(df["close"].iloc[-days - 1])
    end = float(df["close"].iloc[-1])
    if start == 0:
        return None
    return (end - start) / start


def _relative_strength(
    ticker_prices: pd.DataFrame,
    spy_prices: pd.DataFrame,
    qqq_prices: pd.DataFrame,
    days: int,
) -> float | None:
    ticker_return = _pct_change(ticker_prices, days)
    spy_return = _pct_change(spy_prices, days)
    qqq_return = _pct_change(qqq_prices, days)

    benchmarks = [value for value in [spy_return, qqq_return] if value is not None]
    if ticker_return is None or not benchmarks:
        return None
    return ticker_return - max(benchmarks)


def confirm_alert(
    alert: PendingAlert,
    repository: EventRepository,
    thresholds: TechnicalThresholds = TechnicalThresholds(),
) -> TechnicalCheck:
    prices = load_prices(repository.conn, alert.ticker)
    if prices.empty or len(prices) < thresholds.breakout_lookback + 1:
        return TechnicalCheck(
            ticker=alert.ticker,
            technical_status="insufficient_data",
            priority="Info",
            reason=f"{alert.reason}; technical confirmation unavailable",
            metadata={"error": "insufficient_price_data"},
        )

    prices = prices.sort_index()
    latest = prices.iloc[-1]
    close = float(latest["close"])
    previous = prices.iloc[:-1]

    high_20 = float(previous["high"].tail(thresholds.breakout_lookback).max())
    high_55 = float(previous["high"].tail(thresholds.major_breakout_lookback).max())
    breakout_20 = close > high_20
    breakout_55 = close > high_55

    ma20 = float(previous["close"].tail(20).mean()) if len(previous) >= 20 else None
    above_ma20 = ma20 is not None and close > ma20

    avg_volume = float(previous["volume"].tail(thresholds.volume_lookback).mean())
    volume_ratio = float(latest["volume"]) / avg_volume if avg_volume > 0 else None
    volume_confirmed = volume_ratio is not None and volume_ratio >= thresholds.volume_ratio_min

    spy_prices = load_prices(repository.conn, "SPY")
    qqq_prices = load_prices(repository.conn, "QQQ")
    relative_strength = _relative_strength(
        prices,
        spy_prices,
        qqq_prices,
        thresholds.relative_strength_days,
    )
    rs_confirmed = relative_strength is not None and relative_strength > 0

    confirmations = [
        breakout_20,
        breakout_55,
        above_ma20,
        volume_confirmed,
        rs_confirmed,
    ]
    confirmation_count = sum(1 for item in confirmations if item)

    if confirmation_count >= thresholds.high_priority_confirmations:
        priority = "High Priority"
        technical_status = "confirmed"
    elif confirmation_count >= thresholds.watchlist_confirmations:
        priority = "Watchlist"
        technical_status = "partial"
    else:
        priority = "Info"
        technical_status = "unconfirmed"

    details = [
        f"20d_breakout={breakout_20}",
        f"55d_breakout={breakout_55}",
        f"above_ma20={above_ma20}",
        f"volume_ratio={volume_ratio:.2f}" if volume_ratio is not None else "volume_ratio=n/a",
        (
            f"relative_strength={relative_strength:+.2%}"
            if relative_strength is not None
            else "relative_strength=n/a"
        ),
    ]
    stop_loss = close * (1 - thresholds.stop_loss_pct)
    first_take_profit = close * (1 + thresholds.first_take_profit_pct)
    second_take_profit = close * (1 + thresholds.second_take_profit_pct)
    trailing_stop = close * (1 - thresholds.trailing_stop_pct)
    risk_details = [
        f"stop={stop_loss:.2f}",
        f"tp1={first_take_profit:.2f}",
        f"tp2={second_take_profit:.2f}",
        f"trailing_stop={trailing_stop:.2f}",
    ]

    return TechnicalCheck(
        ticker=alert.ticker,
        technical_status=technical_status,
        priority=priority,
        close_price=round(close, 2),
        relative_strength=round(relative_strength, 4) if relative_strength is not None else None,
        breakout=breakout_20 or breakout_55,
        volume_ratio=round(volume_ratio, 2) if volume_ratio is not None else None,
        reason=f"{alert.reason}; {'; '.join(details)}; {'; '.join(risk_details)}",
        metadata={
            "close": close,
            "high_20": high_20,
            "high_55": high_55,
            "ma20": ma20,
            "breakout_20": breakout_20,
            "breakout_55": breakout_55,
            "above_ma20": above_ma20,
            "volume_confirmed": volume_confirmed,
            "rs_confirmed": rs_confirmed,
            "confirmation_count": confirmation_count,
            "risk_levels": {
                "reference_entry": close,
                "stop_loss": stop_loss,
                "first_take_profit": first_take_profit,
                "second_take_profit": second_take_profit,
                "trailing_stop": trailing_stop,
            },
        },
    )


def confirm_pending_alerts(
    repository: EventRepository,
    limit: int = 100,
    dry_run: bool = False,
    thresholds: TechnicalThresholds = TechnicalThresholds(),
) -> list[tuple[PendingAlert, TechnicalCheck]]:
    results = []
    for alert in repository.load_pending_alerts(limit=limit):
        check = confirm_alert(alert, repository, thresholds=thresholds)
        results.append((alert, check))
        if not dry_run:
            repository.update_technical_check(alert.alert_id, check)
    return results
