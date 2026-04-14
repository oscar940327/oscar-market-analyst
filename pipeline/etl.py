"""
etl.py — 每日資料管線（Phase 2 版）
新增：每日只算一次 market_regime（用 SPY+VIX），所有股票共用。
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

import yaml
from perception.price_fetcher import fetch_ohlcv
from perception.news_fetcher import fetch_news, format_news_for_llm
from perception.llm_scorer import score_sentiment
from perception.market_regime import calculate_market_regime
from pipeline.db import get_connection, upsert_prices, upsert_sentiment, load_prices


def load_watchlist() -> list[str]:
    config_path = ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("watchlist", [])


def load_ticker_names() -> dict[str, str]:
    config_path = ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("ticker_names", {})


def run_etl(
    watchlist: list[str] | None = None,
    lookback_days: int = 365,
    news_days: int = 3,
):
    if watchlist is None:
        watchlist = load_watchlist()

    if not watchlist:
        print("❌ 股票池是空的，請在 config/settings.yaml 設定 watchlist")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    def get_latest_trade_date(conn, watchlist: list[str]) -> str:
        """從 daily_prices 找出實際最新有資料的日期"""
        placeholders = ",".join("?" * len(watchlist))
        row = conn.execute(
            f"SELECT MAX(trade_date) FROM daily_prices WHERE ticker IN ({placeholders})",
            watchlist
        ).fetchone()
        return row[0] if row and row[0] else datetime.now().strftime("%Y-%m-%d")

    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    ticker_names = load_ticker_names()

    print(f"🚀 ETL Pipeline — {today}")
    print(f"📋 Watchlist: {', '.join(watchlist)}")
    print(f"📅 Price range: {start_date} ~ {today}")
    print()

    conn = get_connection()

    # ===== Phase A: 抓價格 =====
    print("=" * 50)
    print("Phase A: Fetching prices (YFinance)")
    print("=" * 50)

    for ticker in watchlist:
        df = fetch_ohlcv(ticker, start_date)
        if not df.empty:
            upsert_prices(conn, df, ticker)
            print(f"  💾 {ticker}: {len(df)} rows saved to DB")
        else:
            print(f"  ❌ {ticker}: no data")
    print()

    # 用實際最新交易日當 sentiment 的 trade_date，而不是「今天」
    trade_date = get_latest_trade_date(conn, watchlist)
    print(f"📅 Latest trade date in DB: {trade_date}")

    # ===== Phase B: 計算大盤狀態 =====
    print("=" * 50)
    print("Phase B: Market regime detection (SPY + VIX)")
    print("=" * 50)
    regime, regime_info = calculate_market_regime()
    print(f"  📊 Market regime: {regime.upper()}")
    print(f"     SPY ${regime_info.get('spy_close')} vs MA50 ${regime_info.get('spy_ma50')} "
          f"({regime_info.get('deviation_pct'):+.2f}%)")
    print(f"     VIX: {regime_info.get('vix_close')}")
    print(f"     Reason: {regime_info.get('reason')}")
    print()

    # ===== Phase C: 抓新聞 + LLM 評分 =====
    print("=" * 50)
    print("Phase C: News sentiment scoring (Tavily + LLM)")
    print("=" * 50)

    for ticker in watchlist:
        company = ticker_names.get(ticker, "")
        print(f"\n  --- {ticker} ({company or 'N/A'}) ---")

        # 1. 抓新聞
        news = fetch_news(ticker, company_name=company, days=news_days)
        news_text = format_news_for_llm(news)

        # 2. 組價格 context
        prices = load_prices(conn, ticker)
        price_ctx = ""
        if not prices.empty and len(prices) >= 2:
            last = prices.iloc[-1]
            prev = prices.iloc[-2]
            chg = ((last["close"] - prev["close"]) / prev["close"]) * 100
            price_ctx = (
                f"Close: ${last['close']:.2f}, "
                f"Change: {chg:+.2f}%, "
                f"Volume: {int(last['volume']):,}"
            )

        # 3. LLM 評分（不再要求 LLM 給 market_regime）
        result = score_sentiment(ticker, news_text, price_context=price_ctx)
        print(f"  📊 Score: {result.sentiment_score:+.2f} | Severity: {result.event_severity:.1f}")
        print(f"  💬 {result.reasoning}")

        # 4. 寫入 DB（用統一計算的 market_regime）
        upsert_sentiment(
            conn,
            trade_date=trade_date,
            ticker=ticker,
            sentiment_score=result.sentiment_score,
            event_severity=result.event_severity,
            market_regime=regime,
            reasoning=result.reasoning,
            raw_news=news_text[:2000],
        )

    conn.close()
    print()
    print("=" * 50)
    conn2 = get_connection()
    print(f"✅ ETL complete. Database: "
          f"{conn2.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0]} price rows, "
          f"{conn2.execute('SELECT COUNT(*) FROM daily_sentiment').fetchone()[0]} sentiment rows")
    conn2.close()
    print("=" * 50)


if __name__ == "__main__":
    run_etl()