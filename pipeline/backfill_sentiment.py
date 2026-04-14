"""
backfill_sentiment.py — 歷史 sentiment 回填（支援 LLM 或 FinBERT）

用法：
    # 預設 FinBERT 引擎（免費、快、穩定、決定性）
    python pipeline/backfill_sentiment.py --from 2022-01-01 --to 2025-03-31

    # 或用 LLM 引擎（要錢、慢、但有 reasoning）
    python pipeline/backfill_sentiment.py --engine llm --from 2022-01-01 --to 2025-03-31

    # 舊式用法（最近 N 天）
    python pipeline/backfill_sentiment.py --days 250
    python pipeline/backfill_sentiment.py --ticker TSLA --days 5

引擎比較：
    FinBERT: 決定性輸出（同樣輸入 = 同樣結果）、零成本、< 0.1 秒/筆
    LLM:     有隨機性、~$1/千筆、~1.5 秒/筆、但 reasoning 人類可讀
"""
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

import yaml
from perception.historical_news_fetcher import (
    fetch_historical_news,
    group_news_by_date,
    format_news_for_llm,
)
from pipeline.db import get_connection, upsert_sentiment, load_prices


def load_watchlist() -> list[str]:
    config_path = ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("watchlist", [])


def get_trading_dates_by_days(conn, ticker: str, days: int) -> list[str]:
    cutoff = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT trade_date FROM daily_prices "
        "WHERE ticker = ? AND trade_date >= ? "
        "ORDER BY trade_date DESC LIMIT ?",
        (ticker, cutoff, days)
    ).fetchall()
    return sorted([r[0] for r in rows])


def get_trading_dates_by_range(
    conn, ticker: str, from_date: str, to_date: str
) -> list[str]:
    rows = conn.execute(
        "SELECT trade_date FROM daily_prices "
        "WHERE ticker = ? AND trade_date >= ? AND trade_date <= ? "
        "ORDER BY trade_date ASC",
        (ticker, from_date, to_date)
    ).fetchall()
    return [r[0] for r in rows]


def backfill_ticker(
    conn,
    ticker: str,
    trading_dates: list[str],
    engine: str,
    skip_existing: bool = True,
    delay_between_llm_calls: float = 1.5,
):
    """
    對單檔股票回填 sentiment。

    engine: "finbert" 或 "llm"
    """
    print(f"\n{'='*60}")
    print(f"Backfilling: {ticker}  (engine: {engine})")
    print(f"{'='*60}")

    if not trading_dates:
        print(f"  ⚠️ {ticker}: no price data, run backfill_prices.py first")
        return

    from_date = trading_dates[0]
    to_date = trading_dates[-1]
    print(f"  📅 Trading days: {from_date} ~ {to_date} ({len(trading_dates)} days)")

    # 1. 抓新聞
    print(f"  📥 Fetching all news from Polygon...")
    all_news = fetch_historical_news(ticker, from_date, to_date)
    print(f"  ✅ Got {len(all_news)} total news articles")

    if not all_news:
        print(f"  ⚠️ {ticker}: no news available for this period")
        return

    # 2. 按日期分組
    grouped = group_news_by_date(all_news)
    print(f"  📦 News distributed across {len(grouped)} unique days")

    # 3. 對每個交易日評分
    processed = 0
    skipped = 0
    failed = 0

    for trade_date in trading_dates:
        if skip_existing:
            existing = conn.execute(
                "SELECT 1 FROM daily_sentiment WHERE trade_date=? AND ticker=?",
                (trade_date, ticker)
            ).fetchone()
            if existing:
                skipped += 1
                continue

        day_news = grouped.get(trade_date, [])
        if not day_news:
            upsert_sentiment(
                conn,
                trade_date=trade_date,
                ticker=ticker,
                sentiment_score=0.0,
                event_severity=0.0,
                market_regime="neutral",
                reasoning="(no news this day)",
                raw_news="",
            )
            processed += 1
            continue

        # ========== 根據 engine 選擇評分方式 ==========
        if engine == "finbert":
            # FinBERT：直接收 news 物件列表
            from perception.finbert_scorer import score_sentiment_finbert
            result = score_sentiment_finbert(ticker, day_news)
            # 沒有 delay，FinBERT 是本地的
        else:
            # LLM：先格式化成文字
            from perception.llm_scorer import score_sentiment
            news_text = format_news_for_llm(day_news)

            prices = load_prices(conn, ticker, end_date=trade_date)
            price_ctx = ""
            if not prices.empty and len(prices) >= 2:
                today_row = prices.iloc[-1]
                prev = prices.iloc[-2]
                chg = ((today_row["close"] - prev["close"]) / prev["close"]) * 100
                price_ctx = (
                    f"Date: {trade_date}, Close: ${today_row['close']:.2f}, "
                    f"Change: {chg:+.2f}%"
                )

            result = score_sentiment(ticker, news_text, price_context=price_ctx)
            time.sleep(delay_between_llm_calls)  # LLM 才要 delay

        # 判斷是否失敗
        if "error" in result.reasoning.lower() or "failed" in result.reasoning.lower():
            failed += 1
            print(f"    ❌ {trade_date}: {result.reasoning[:60]}")
        else:
            processed += 1
            if engine == "finbert":
                # FinBERT 印簡短版
                print(f"    ✅ {trade_date}: score={result.sentiment_score:+.2f} "
                      f"sev={result.event_severity:.2f} ({len(day_news)} news)")
            else:
                print(f"    ✅ {trade_date}: score={result.sentiment_score:+.2f} "
                      f"sev={result.event_severity:.1f} ({len(day_news)} news)")

        # raw_news 文字 (用於 DB 存檔)
        news_text_for_db = format_news_for_llm(day_news)

        upsert_sentiment(
            conn,
            trade_date=trade_date,
            ticker=ticker,
            sentiment_score=result.sentiment_score,
            event_severity=result.event_severity,
            market_regime="neutral",  # 之後由 backfill_regime.py 覆蓋
            reasoning=result.reasoning,
            raw_news=news_text_for_db[:2000],
        )

    print(f"\n  📊 Summary: {processed} new, {skipped} skipped, {failed} failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=str, default="finbert",
                        choices=["finbert", "llm"],
                        help="Scoring engine: finbert (default, free, fast) or llm")
    parser.add_argument("--days", type=int, default=250,
                        help="Number of trading days to backfill (default: 250)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Backfill only this ticker")
    parser.add_argument("--from", dest="from_date", type=str, default=None,
                        help="Start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--to", dest="to_date", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--no-skip", action="store_true",
                        help="Do not skip existing sentiment records")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between LLM calls (ignored for FinBERT)")
    args = parser.parse_args()

    if args.ticker:
        watchlist = [args.ticker.upper()]
    else:
        watchlist = load_watchlist()

    use_range_mode = args.from_date is not None
    if use_range_mode and not args.to_date:
        args.to_date = datetime.now().strftime("%Y-%m-%d")

    print(f"🚀 Sentiment Backfill")
    print(f"🧠 Engine: {args.engine.upper()}")
    print(f"📋 Watchlist: {', '.join(watchlist)}")
    if use_range_mode:
        print(f"📅 Date range: {args.from_date} ~ {args.to_date}")
    else:
        print(f"📅 Days: {args.days}")
    if args.engine == "llm":
        print(f"⏱️  Delay between LLM calls: {args.delay}s")

    conn = get_connection()

    for ticker in watchlist:
        if use_range_mode:
            trading_dates = get_trading_dates_by_range(
                conn, ticker, args.from_date, args.to_date
            )
        else:
            trading_dates = get_trading_dates_by_days(conn, ticker, args.days)

        backfill_ticker(
            conn,
            ticker=ticker,
            trading_dates=trading_dates,
            engine=args.engine,
            skip_existing=not args.no_skip,
            delay_between_llm_calls=args.delay,
        )

    total = conn.execute("SELECT COUNT(*) FROM daily_sentiment").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"✅ Backfill complete. Total sentiment rows in DB: {total}")
    print(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()