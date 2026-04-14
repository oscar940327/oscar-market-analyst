"""
backfill_prices.py — 歷史價格回填
對指定的 ticker 抓取指定日期範圍的 OHLCV，補進 DB。
專門給跨熊市測試用，不用動原本的每日 ETL 流程。

用法：
    python pipeline/backfill_prices.py
    python pipeline/backfill_prices.py --from 2022-01-01 --to 2025-03-31
    python pipeline/backfill_prices.py --ticker TSLA --from 2022-01-01
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

from perception.price_fetcher import fetch_ohlcv
from pipeline.db import get_connection, upsert_prices


# 跨熊市測試專用的 6 檔（SNDK 排除，因為 2025-02 才獨立上市）
#CROSS_BEAR_WATCHLIST = ["TSLA", "GOOGL", "PLTR", "MU", "NVDA", "SOFI"]
CROSS_BEAR_WATCHLIST = ["AAPL", "META", "MSFT", "AMD", "AVGO", "CRWD", "TSM", "RKLB"]


def backfill_ticker(ticker: str, from_date: str, to_date: str) -> int:
    """抓單一 ticker 在指定範圍的 OHLCV，寫入 DB"""
    print(f"\n{'='*55}")
    print(f"Backfilling prices: {ticker}")
    print(f"Range: {from_date} ~ {to_date}")
    print(f"{'='*55}")

    try:
        df = fetch_ohlcv(ticker, from_date, to_date)
    except Exception as e:
        print(f"  ❌ Fetch failed: {e}")
        return 0

    if df.empty:
        print(f"  ⚠️ No data returned")
        return 0

    print(f"  📊 Got {len(df)} bars ({df.index[0].date()} ~ {df.index[-1].date()})")

    conn = get_connection()
    try:
        upsert_prices(conn, df, ticker)
        conn.commit()
    finally:
        conn.close()

    print(f"  💾 Saved to DB")
    return len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default=None,
                        help="指定單一 ticker（預設全部 6 檔）")
    parser.add_argument("--from", dest="from_date", type=str, default="2022-01-01",
                        help="起始日期 YYYY-MM-DD（預設 2022-01-01）")
    parser.add_argument("--to", dest="to_date", type=str, default="2025-03-31",
                        help="結束日期 YYYY-MM-DD（預設 2025-03-31，避免跟現有資料重疊）")
    args = parser.parse_args()

    tickers = [args.ticker] if args.ticker else CROSS_BEAR_WATCHLIST

    print(f"\n🚀 Historical Price Backfill")
    print(f"📋 Tickers: {', '.join(tickers)}")
    print(f"📅 Range: {args.from_date} ~ {args.to_date}")

    total = 0
    failures = []

    for ticker in tickers:
        try:
            count = backfill_ticker(ticker, args.from_date, args.to_date)
            total += count
        except Exception as e:
            print(f"  ❌ {ticker} failed: {e}")
            failures.append(ticker)

    print(f"\n{'='*55}")
    print(f"✅ Backfill complete")
    print(f"   Total bars saved: {total}")
    if failures:
        print(f"   Failed: {', '.join(failures)}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()