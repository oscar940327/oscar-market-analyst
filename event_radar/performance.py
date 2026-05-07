from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from event_radar.repository import EventRepository
from pipeline.db import load_prices


@dataclass(frozen=True)
class PerformanceResult:
    alert_id: int
    ticker: str
    horizon_days: int
    price_date: str
    return_pct: float
    benchmark_return_pct: float | None
    relative_return_pct: float | None
    max_drawdown_pct: float | None


@dataclass(frozen=True)
class PerformanceSummary:
    group: str
    horizon_days: int
    sample_count: int
    avg_return_pct: float
    avg_benchmark_return_pct: float | None
    avg_relative_return_pct: float | None
    avg_max_drawdown_pct: float | None
    win_rate: float
    benchmark_beat_rate: float | None


def _return_after_horizon(
    prices: pd.DataFrame,
    alert_date: str,
    entry_price: float,
    horizon_days: int,
) -> tuple[str, float, float, float] | None:
    if prices.empty:
        return None
    future = prices[prices.index > pd.Timestamp(alert_date)]
    if len(future) < horizon_days:
        return None
    window = future.iloc[:horizon_days]
    exit_row = window.iloc[-1]
    exit_price = float(exit_row["close"])
    price_date = window.index[-1].strftime("%Y-%m-%d")
    return_pct = (exit_price - entry_price) / entry_price
    min_low = float(window["low"].min())
    max_drawdown_pct = (min_low - entry_price) / entry_price
    return price_date, exit_price, return_pct, max_drawdown_pct


def _benchmark_return(
    repository: EventRepository,
    alert_date: str,
    horizon_days: int,
) -> float | None:
    returns = []
    for ticker in ["SPY", "QQQ"]:
        prices = load_prices(repository.conn, ticker)
        if prices.empty:
            continue
        entry_candidates = prices[prices.index <= pd.Timestamp(alert_date)]
        if entry_candidates.empty:
            continue
        entry = float(entry_candidates.iloc[-1]["close"])
        result = _return_after_horizon(prices, alert_date, entry, horizon_days)
        if result is not None:
            returns.append(result[2])
    return max(returns) if returns else None


def update_alert_performance(
    repository: EventRepository,
    horizons: tuple[int, ...] = (1, 3, 5, 20),
    limit: int = 200,
    dry_run: bool = False,
) -> list[PerformanceResult]:
    results: list[PerformanceResult] = []
    alerts = repository.load_alerts_for_performance(limit=limit)

    for alert in alerts:
        row = repository.conn.execute(
            """
            SELECT alert_date, close_price
            FROM radar_alerts
            WHERE alert_id=?
            """,
            (alert.alert_id,),
        ).fetchone()
        if not row or row[1] is None:
            continue

        alert_date = str(row[0])
        entry_price = float(row[1])
        prices = load_prices(repository.conn, alert.ticker)

        for horizon in horizons:
            perf = _return_after_horizon(prices, alert_date, entry_price, horizon)
            if perf is None:
                continue
            price_date, exit_price, return_pct, max_drawdown_pct = perf
            benchmark_return_pct = _benchmark_return(repository, alert_date, horizon)
            relative_return_pct = (
                return_pct - benchmark_return_pct
                if benchmark_return_pct is not None
                else None
            )

            result = PerformanceResult(
                alert_id=alert.alert_id,
                ticker=alert.ticker,
                horizon_days=horizon,
                price_date=price_date,
                return_pct=return_pct,
                benchmark_return_pct=benchmark_return_pct,
                relative_return_pct=relative_return_pct,
                max_drawdown_pct=max_drawdown_pct,
            )
            results.append(result)

            if not dry_run:
                repository.upsert_alert_performance(
                    alert_id=alert.alert_id,
                    horizon_days=horizon,
                    price_date=price_date,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    return_pct=return_pct,
                    benchmark_return_pct=benchmark_return_pct,
                    relative_return_pct=relative_return_pct,
                    max_drawdown_pct=max_drawdown_pct,
                )

    return results


def summarize_alert_performance(
    repository: EventRepository,
    horizon_days: int = 5,
    group_by: str = "theme",
    min_count: int = 1,
) -> list[PerformanceSummary]:
    allowed_groups = {
        "theme": "a.theme",
        "priority": "a.priority",
        "technical_status": "a.technical_status",
    }
    group_sql = allowed_groups.get(group_by)
    if group_sql is None:
        raise ValueError(
            "group_by must be one of: theme, priority, technical_status"
        )

    rows = repository.conn.execute(
        f"""
        SELECT
            {group_sql} AS group_name,
            COUNT(*) AS sample_count,
            AVG(p.return_pct) AS avg_return_pct,
            AVG(p.benchmark_return_pct) AS avg_benchmark_return_pct,
            AVG(p.relative_return_pct) AS avg_relative_return_pct,
            AVG(p.max_drawdown_pct) AS avg_max_drawdown_pct,
            AVG(CASE WHEN p.return_pct > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
            AVG(
                CASE
                    WHEN p.relative_return_pct IS NULL THEN NULL
                    WHEN p.relative_return_pct > 0 THEN 1.0
                    ELSE 0.0
                END
            ) AS benchmark_beat_rate
        FROM alert_performance p
        JOIN radar_alerts a ON a.alert_id = p.alert_id
        WHERE p.horizon_days = ?
        GROUP BY {group_sql}
        HAVING COUNT(*) >= ?
        ORDER BY avg_relative_return_pct DESC, avg_return_pct DESC
        """,
        (horizon_days, min_count),
    ).fetchall()

    return [
        PerformanceSummary(
            group=str(row[0]),
            horizon_days=horizon_days,
            sample_count=int(row[1]),
            avg_return_pct=float(row[2]),
            avg_benchmark_return_pct=float(row[3]) if row[3] is not None else None,
            avg_relative_return_pct=float(row[4]) if row[4] is not None else None,
            avg_max_drawdown_pct=float(row[5]) if row[5] is not None else None,
            win_rate=float(row[6]),
            benchmark_beat_rate=float(row[7]) if row[7] is not None else None,
        )
        for row in rows
    ]
