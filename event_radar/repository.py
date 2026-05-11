from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Iterable

from pipeline.db import get_connection

from event_radar.models import (
    AlertDraft,
    ClassifiedEvent,
    FundamentalSnapshot,
    PendingAlert,
    RadarAlert,
    TechnicalCheck,
    ThemeMatch,
    TrendAlert,
    utc_now_iso,
)


def ensure_event_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS market_events (
            event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date    TEXT NOT NULL,
            source        TEXT,
            title         TEXT NOT NULL,
            summary       TEXT,
            url           TEXT,
            published_at  TEXT,
            category      TEXT,
            theme         TEXT,
            direction     TEXT,
            confidence    REAL DEFAULT 0,
            raw_json      TEXT,
            created_at    TEXT NOT NULL,
            UNIQUE(url)
        );

        CREATE TABLE IF NOT EXISTS radar_alerts (
            alert_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id         INTEGER NOT NULL,
            alert_date       TEXT NOT NULL,
            ticker           TEXT NOT NULL,
            theme            TEXT NOT NULL,
            priority         TEXT NOT NULL,
            reason           TEXT NOT NULL,
            technical_status TEXT NOT NULL DEFAULT 'pending',
            close_price      REAL,
            relative_strength REAL,
            breakout         INTEGER,
            volume_ratio     REAL,
            status           TEXT NOT NULL DEFAULT 'open',
            raw_json         TEXT,
            created_at       TEXT NOT NULL,
            UNIQUE(event_id, ticker),
            FOREIGN KEY(event_id) REFERENCES market_events(event_id)
        );

        CREATE INDEX IF NOT EXISTS idx_market_events_date
            ON market_events(event_date, theme);
        CREATE INDEX IF NOT EXISTS idx_radar_alerts_ticker
            ON radar_alerts(ticker, alert_date);

        CREATE TABLE IF NOT EXISTS alert_performance (
            alert_id              INTEGER NOT NULL,
            horizon_days          INTEGER NOT NULL,
            price_date            TEXT NOT NULL,
            entry_price           REAL NOT NULL,
            exit_price            REAL NOT NULL,
            return_pct            REAL NOT NULL,
            benchmark_return_pct  REAL,
            relative_return_pct   REAL,
            max_drawdown_pct      REAL,
            updated_at            TEXT NOT NULL,
            PRIMARY KEY(alert_id, horizon_days),
            FOREIGN KEY(alert_id) REFERENCES radar_alerts(alert_id)
        );

        CREATE TABLE IF NOT EXISTS trend_states (
            theme           TEXT NOT NULL,
            ticker          TEXT NOT NULL,
            status          TEXT NOT NULL,
            last_event_date TEXT,
            last_alert_id   INTEGER,
            last_close      REAL,
            high_watermark  REAL,
            reason          TEXT,
            updated_at      TEXT NOT NULL,
            PRIMARY KEY(theme, ticker)
        );

        CREATE TABLE IF NOT EXISTS fundamental_checks (
            ticker             TEXT NOT NULL,
            check_date         TEXT NOT NULL,
            rating             TEXT NOT NULL,
            valuation_score    INTEGER NOT NULL,
            quality_score      INTEGER NOT NULL,
            summary            TEXT NOT NULL,
            metrics_json       TEXT,
            raw_json           TEXT,
            updated_at         TEXT NOT NULL,
            PRIMARY KEY(ticker, check_date)
        );
        """
    )
    _ensure_column(conn, "radar_alerts", "alert_sent_at", "TEXT")
    _ensure_column(conn, "radar_alerts", "alert_channel", "TEXT")
    _ensure_column(conn, "trend_states", "trend_alert_sent_at", "TEXT")
    _ensure_column(conn, "trend_states", "trend_alert_channel", "TEXT")
    _ensure_column(conn, "trend_states", "notified_status", "TEXT")
    conn.commit()


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _load_json_object(value: object) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class EventRepository:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()
        ensure_event_tables(self.conn)

    def close(self) -> None:
        self.conn.close()

    def save_event(self, classified: ClassifiedEvent) -> int:
        primary = classified.primary_match
        raw = {
            "matches": [
                {
                    "theme": match.theme,
                    "category": match.category,
                    "tickers": match.tickers,
                    "matched_keywords": match.matched_keywords,
                    "score": match.score,
                    "direction": match.direction,
                    "confidence": match.confidence,
                    "ticker_tiers": match.ticker_tiers,
                }
                for match in classified.matches
            ]
        }
        event_date = classified.news.published_at[:10] or date.today().isoformat()

        event_url = classified.news.url or None
        self.conn.execute(
            """
            INSERT OR IGNORE INTO market_events
                (event_date, source, title, summary, url, published_at,
                 category, theme, direction, confidence, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_date,
                classified.news.source,
                classified.news.title,
                classified.news.summary,
                event_url,
                classified.news.published_at,
                primary.category if primary else None,
                primary.theme if primary else None,
                primary.direction if primary else None,
                primary.confidence if primary else 0.0,
                json.dumps(raw, ensure_ascii=False),
                classified.created_at,
            ),
        )
        self.conn.commit()

        if event_url:
            row = self.conn.execute(
                "SELECT event_id FROM market_events WHERE url=?",
                (event_url,),
            ).fetchone()
            if row:
                return int(row[0])

        row = self.conn.execute(
            """
            SELECT event_id FROM market_events
            WHERE title=? AND created_at=?
            ORDER BY event_id DESC
            LIMIT 1
            """,
            (classified.news.title, classified.created_at),
        ).fetchone()
        if row:
            return int(row[0])
        raise RuntimeError("Unable to persist market event")

    def save_alerts(self, alerts: Iterable[AlertDraft]) -> int:
        count = 0
        for alert in alerts:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO radar_alerts
                    (event_id, alert_date, ticker, theme, priority, reason,
                     technical_status, raw_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.event_id,
                    date.today().isoformat(),
                    alert.ticker,
                    alert.theme,
                    alert.priority,
                    alert.reason,
                    alert.technical_status,
                    json.dumps(alert.metadata, ensure_ascii=False),
                    utc_now_iso(),
                ),
            )
            if cursor.rowcount > 0:
                count += 1
        self.conn.commit()
        return count

    def load_pending_alerts(self, limit: int = 100) -> list[PendingAlert]:
        rows = self.conn.execute(
            """
            SELECT alert_id, event_id, ticker, theme, priority, reason, raw_json
            FROM radar_alerts
            WHERE status='open' AND technical_status='pending'
            ORDER BY alert_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            PendingAlert(
                alert_id=int(row[0]),
                event_id=int(row[1]),
                ticker=str(row[2]),
                theme=str(row[3]),
                priority=str(row[4]),
                reason=str(row[5]),
                metadata=_load_json_object(row[6]),
            )
            for row in rows
        ]

    def update_technical_check(
        self,
        alert_id: int,
        check: TechnicalCheck,
    ) -> None:
        raw_json = json.dumps(check.metadata, ensure_ascii=False)
        self.conn.execute(
            """
            UPDATE radar_alerts
            SET priority=?,
                reason=?,
                technical_status=?,
                close_price=?,
                relative_strength=?,
                breakout=?,
                volume_ratio=?,
                raw_json=?
            WHERE alert_id=?
            """,
            (
                check.priority,
                check.reason,
                check.technical_status,
                check.close_price,
                check.relative_strength,
                1 if check.breakout else 0,
                check.volume_ratio,
                raw_json,
                alert_id,
            ),
        )
        self.conn.commit()

    def upsert_fundamental_check(
        self,
        ticker: str,
        check_date: str,
        rating: str,
        valuation_score: int,
        quality_score: int,
        summary: str,
        metrics: dict,
        raw: dict,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO fundamental_checks
                (ticker, check_date, rating, valuation_score, quality_score,
                 summary, metrics_json, raw_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, check_date) DO UPDATE SET
                rating=excluded.rating,
                valuation_score=excluded.valuation_score,
                quality_score=excluded.quality_score,
                summary=excluded.summary,
                metrics_json=excluded.metrics_json,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                ticker.upper(),
                check_date,
                rating,
                int(valuation_score),
                int(quality_score),
                summary,
                json.dumps(metrics, ensure_ascii=False),
                json.dumps(raw, ensure_ascii=False),
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def load_latest_fundamental(self, ticker: str) -> FundamentalSnapshot | None:
        row = self.conn.execute(
            """
            SELECT ticker, check_date, rating, valuation_score, quality_score, summary
            FROM fundamental_checks
            WHERE ticker=?
            ORDER BY check_date DESC, updated_at DESC
            LIMIT 1
            """,
            (ticker.upper(),),
        ).fetchone()
        if not row:
            return None
        return FundamentalSnapshot(
            ticker=str(row[0]),
            check_date=str(row[1]),
            rating=str(row[2]),
            valuation_score=int(row[3]),
            quality_score=int(row[4]),
            summary=str(row[5]),
        )

    def load_unsent_alerts(
        self,
        limit: int = 50,
        priorities: set[str] | None = None,
        include_unconfirmed: bool = False,
    ) -> list[RadarAlert]:
        params: list[object] = []
        where = ["a.status='open'", "a.alert_sent_at IS NULL"]
        if priorities:
            placeholders = ",".join("?" for _ in priorities)
            where.append(f"a.priority IN ({placeholders})")
            params.extend(sorted(priorities))
        if not include_unconfirmed:
            where.append("a.technical_status IN ('confirmed', 'partial')")

        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT
                a.alert_id, a.event_id, a.alert_date, a.ticker, a.theme,
                a.priority, a.reason, a.technical_status, a.close_price,
                a.relative_strength, a.breakout, a.volume_ratio, a.raw_json,
                e.title, e.source, e.url, e.published_at, e.direction,
                f.check_date, f.rating, f.valuation_score, f.quality_score, f.summary
            FROM radar_alerts a
            JOIN market_events e ON e.event_id = a.event_id
            LEFT JOIN fundamental_checks f
              ON f.ticker = a.ticker
             AND f.check_date = (
                SELECT MAX(f2.check_date)
                FROM fundamental_checks f2
                WHERE f2.ticker = a.ticker
             )
            WHERE {' AND '.join(where)}
            ORDER BY
                CASE a.priority
                    WHEN 'High Priority' THEN 1
                    WHEN 'Watchlist' THEN 2
                    ELSE 3
                END,
                a.alert_id
            LIMIT ?
            """,
            params,
        ).fetchall()

        alerts: list[RadarAlert] = []
        for row in rows:
            metadata = {}
            if row[12]:
                try:
                    metadata = json.loads(str(row[12]))
                except json.JSONDecodeError:
                    metadata = {}
            if row[18] is not None:
                metadata["fundamental"] = {
                    "check_date": str(row[18]),
                    "rating": str(row[19]),
                    "valuation_score": int(row[20]),
                    "quality_score": int(row[21]),
                    "summary": str(row[22]),
                }
            alerts.append(
                RadarAlert(
                    alert_id=int(row[0]),
                    event_id=int(row[1]),
                    alert_date=str(row[2]),
                    ticker=str(row[3]),
                    theme=str(row[4]),
                    priority=str(row[5]),
                    reason=str(row[6]),
                    technical_status=str(row[7]),
                    close_price=float(row[8]) if row[8] is not None else None,
                    relative_strength=float(row[9]) if row[9] is not None else None,
                    breakout=bool(row[10]) if row[10] is not None else None,
                    volume_ratio=float(row[11]) if row[11] is not None else None,
                    event_title=str(row[13]),
                    event_source=str(row[14] or ""),
                    event_url=str(row[15] or ""),
                    event_published_at=str(row[16] or ""),
                    event_direction=str(row[17] or ""),
                    metadata=metadata,
                )
            )
        return alerts

    def mark_alerts_sent(self, alert_ids: Iterable[int], channel: str = "email") -> int:
        ids = list(alert_ids)
        if not ids:
            return 0
        sent_at = utc_now_iso()
        count = 0
        for alert_id in ids:
            cursor = self.conn.execute(
                """
                UPDATE radar_alerts
                SET alert_sent_at=?, alert_channel=?
                WHERE alert_id=? AND alert_sent_at IS NULL
                """,
                (sent_at, channel, alert_id),
            )
            count += cursor.rowcount
        self.conn.commit()
        return count

    def load_alerts_for_performance(self, limit: int = 200) -> list[PendingAlert]:
        rows = self.conn.execute(
            """
            SELECT alert_id, event_id, ticker, theme, priority, reason, raw_json
            FROM radar_alerts
            WHERE status='open'
              AND close_price IS NOT NULL
              AND technical_status IN ('confirmed', 'partial', 'unconfirmed')
            ORDER BY alert_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            PendingAlert(
                alert_id=int(row[0]),
                event_id=int(row[1]),
                ticker=str(row[2]),
                theme=str(row[3]),
                priority=str(row[4]),
                reason=str(row[5]),
                metadata=_load_json_object(row[6]),
            )
            for row in rows
        ]

    def upsert_alert_performance(
        self,
        alert_id: int,
        horizon_days: int,
        price_date: str,
        entry_price: float,
        exit_price: float,
        return_pct: float,
        benchmark_return_pct: float | None,
        relative_return_pct: float | None,
        max_drawdown_pct: float | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO alert_performance
                (alert_id, horizon_days, price_date, entry_price, exit_price,
                 return_pct, benchmark_return_pct, relative_return_pct,
                 max_drawdown_pct, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alert_id, horizon_days) DO UPDATE SET
                price_date=excluded.price_date,
                entry_price=excluded.entry_price,
                exit_price=excluded.exit_price,
                return_pct=excluded.return_pct,
                benchmark_return_pct=excluded.benchmark_return_pct,
                relative_return_pct=excluded.relative_return_pct,
                max_drawdown_pct=excluded.max_drawdown_pct,
                updated_at=excluded.updated_at
            """,
            (
                alert_id,
                horizon_days,
                price_date,
                entry_price,
                exit_price,
                return_pct,
                benchmark_return_pct,
                relative_return_pct,
                max_drawdown_pct,
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def upsert_trend_state(
        self,
        theme: str,
        ticker: str,
        status: str,
        last_event_date: str | None,
        last_alert_id: int | None,
        last_close: float | None,
        high_watermark: float | None,
        reason: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO trend_states
                (theme, ticker, status, last_event_date, last_alert_id,
                 last_close, high_watermark, reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(theme, ticker) DO UPDATE SET
                status=excluded.status,
                last_event_date=excluded.last_event_date,
                last_alert_id=excluded.last_alert_id,
                last_close=excluded.last_close,
                high_watermark=excluded.high_watermark,
                reason=excluded.reason,
                updated_at=excluded.updated_at
            """,
            (
                theme,
                ticker,
                status,
                last_event_date,
                last_alert_id,
                last_close,
                high_watermark,
                reason,
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def load_unsent_trend_alerts(
        self,
        limit: int = 50,
        statuses: set[str] | None = None,
    ) -> list[TrendAlert]:
        statuses = statuses or {"Cooling", "Closed"}
        placeholders = ",".join("?" for _ in statuses)
        params: list[object] = sorted(statuses)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT theme, ticker, status, last_event_date, last_close,
                   high_watermark, reason
            FROM trend_states
            WHERE status IN ({placeholders})
              AND (notified_status IS NULL OR notified_status != status)
            ORDER BY
                CASE status
                    WHEN 'Closed' THEN 1
                    WHEN 'Cooling' THEN 2
                    ELSE 3
                END,
                theme,
                ticker
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            TrendAlert(
                theme=str(row[0]),
                ticker=str(row[1]),
                status=str(row[2]),
                last_event_date=str(row[3] or ""),
                last_close=float(row[4]) if row[4] is not None else None,
                high_watermark=float(row[5]) if row[5] is not None else None,
                reason=str(row[6] or ""),
            )
            for row in rows
        ]

    def mark_trend_alerts_sent(
        self,
        alerts: Iterable[TrendAlert],
        channel: str = "email",
    ) -> int:
        sent_at = utc_now_iso()
        count = 0
        for alert in alerts:
            cursor = self.conn.execute(
                """
                UPDATE trend_states
                SET trend_alert_sent_at=?,
                    trend_alert_channel=?,
                    notified_status=?
                WHERE theme=? AND ticker=? AND status=?
                """,
                (
                    sent_at,
                    channel,
                    alert.status,
                    alert.theme,
                    alert.ticker,
                    alert.status,
                ),
            )
            count += cursor.rowcount
        self.conn.commit()
        return count


def priority_for_match(
    match: ThemeMatch,
    high_min: int,
    watchlist_min: int,
    high_priority_min_event_strength: int = 70,
) -> str:
    if match.score >= high_min and match.event_strength >= high_priority_min_event_strength:
        return "High Priority"
    if match.score >= watchlist_min:
        return "Watchlist"
    return "Info"
