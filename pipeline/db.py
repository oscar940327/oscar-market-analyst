"""
db.py — SQLite 資料庫工具
負責建表、寫入、讀取。所有模組共用這一個 DB 入口。
"""
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "market.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS daily_prices (
        trade_date  TEXT    NOT NULL,
        ticker      TEXT    NOT NULL,
        open        REAL,
        high        REAL,
        low         REAL,
        close       REAL,
        volume      INTEGER,
        adj_close   REAL,
        PRIMARY KEY (trade_date, ticker)
    );

    CREATE TABLE IF NOT EXISTS daily_sentiment (
        trade_date      TEXT    NOT NULL,
        ticker          TEXT    NOT NULL,
        sentiment_score REAL,
        event_severity  REAL DEFAULT 0,
        market_regime   TEXT,
        reasoning       TEXT,
        raw_news        TEXT,
        PRIMARY KEY (trade_date, ticker)
    );

    CREATE INDEX IF NOT EXISTS idx_prices_ticker ON daily_prices(ticker, trade_date);
    CREATE INDEX IF NOT EXISTS idx_sentiment_ticker ON daily_sentiment(ticker, trade_date);
    """)
    conn.commit()


def upsert_prices(conn: sqlite3.Connection, df: pd.DataFrame, ticker: str):
    for idx, row in df.iterrows():
        td = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        conn.execute("""
            INSERT INTO daily_prices (trade_date,ticker,open,high,low,close,volume,adj_close)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(trade_date,ticker) DO UPDATE SET
                open=excluded.open,high=excluded.high,low=excluded.low,
                close=excluded.close,volume=excluded.volume,adj_close=excluded.adj_close
        """, (td, ticker, float(row.get("open",0)), float(row.get("high",0)),
              float(row.get("low",0)), float(row.get("close",0)),
              int(row.get("volume",0)), float(row.get("adj_close", row.get("close",0)))))
    conn.commit()


def upsert_sentiment(conn, trade_date, ticker, sentiment_score,
                     event_severity=0.0, market_regime="neutral",
                     reasoning="", raw_news=""):
    conn.execute("""
        INSERT INTO daily_sentiment
            (trade_date,ticker,sentiment_score,event_severity,market_regime,reasoning,raw_news)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(trade_date,ticker) DO UPDATE SET
            sentiment_score=excluded.sentiment_score,event_severity=excluded.event_severity,
            market_regime=excluded.market_regime,reasoning=excluded.reasoning,raw_news=excluded.raw_news
    """, (trade_date, ticker, sentiment_score, event_severity, market_regime, reasoning, raw_news))
    conn.commit()


def load_prices(conn, ticker, start_date=None, end_date=None) -> pd.DataFrame:
    q = "SELECT * FROM daily_prices WHERE ticker=?"
    p = [ticker]
    if start_date: q += " AND trade_date>=?"; p.append(start_date)
    if end_date:   q += " AND trade_date<=?"; p.append(end_date)
    q += " ORDER BY trade_date"
    df = pd.read_sql_query(q, conn, params=p)
    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date"); df.index.name = "date"
    return df


def load_sentiment(conn, ticker, start_date=None, end_date=None) -> pd.DataFrame:
    q = "SELECT * FROM daily_sentiment WHERE ticker=?"
    p = [ticker]
    if start_date: q += " AND trade_date>=?"; p.append(start_date)
    if end_date:   q += " AND trade_date<=?"; p.append(end_date)
    q += " ORDER BY trade_date"
    df = pd.read_sql_query(q, conn, params=p)
    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date"); df.index.name = "date"
    return df


def load_merged(conn, ticker, start_date=None, end_date=None) -> pd.DataFrame:
    """
    價格 + sentiment 合併，sentiment shift 1 天防止前視偏誤。
    T 日的情緒只能在 T+1 的策略決策中使用。
    """
    prices = load_prices(conn, ticker, start_date, end_date)
    sent = load_sentiment(conn, ticker, start_date, end_date)
    if prices.empty:
        return prices
    if not sent.empty:
        shifted = sent[["sentiment_score","event_severity","market_regime"]].shift(1)
        merged = prices.join(shifted, how="left")
    else:
        merged = prices.copy()
        merged["sentiment_score"] = None
        merged["event_severity"] = None
        merged["market_regime"] = None
    merged["sentiment_score"] = merged["sentiment_score"].fillna(0.0)
    merged["event_severity"] = merged["event_severity"].fillna(0.0)
    merged["market_regime"] = merged["market_regime"].fillna("neutral")
    return merged
