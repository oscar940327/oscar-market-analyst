"""
price_fetcher.py — 美股價格抓取器
從 ai-trader/ai_trader/data/fetchers/us_stock.py 簡化而來。
只保留核心的 yfinance 下載 + 標準化邏輯。
"""
import time
from typing import Optional

import pandas as pd
import yfinance as yf


def fetch_ohlcv(
    ticker: str,
    start_date: str,
    end_date: Optional[str] = None,
    max_retries: int = 3,
) -> pd.DataFrame:
    """
    抓取單檔美股 OHLCV 數據。

    Returns:
        DataFrame, index=DatetimeIndex('date'),
        columns=['open','high','low','close','volume','adj_close']
    """
    for attempt in range(1, max_retries + 1):
        try:
            df = yf.download(
                ticker,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=False,
            )
            if df.empty:
                print(f"  WARN {ticker}: no data (attempt {attempt}/{max_retries})")
                if attempt == max_retries:
                    return pd.DataFrame()
                time.sleep(2 ** attempt)
                continue

            df = df.reset_index()

            # 處理 MultiIndex columns（yfinance 有時會回傳）
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.columns = df.columns.str.lower()
            df = df.rename(columns={"adj close": "adj_close"})

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
            df.index.name = "date"

            # 只保留需要的欄位
            keep = ["open", "high", "low", "close", "volume", "adj_close"]
            available = [c for c in keep if c in df.columns]
            df = df[available].dropna(subset=["close"])

            print(f"  OK {ticker}: {len(df)} rows ({df.index[0].date()} ~ {df.index[-1].date()})")
            return df

        except Exception as e:
            print(f"  WARN {ticker}: error (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)

    return pd.DataFrame()


def fetch_batch(
    tickers: list[str],
    start_date: str,
    end_date: Optional[str] = None,
) -> dict[str, pd.DataFrame]:
    """抓取多檔股票，回傳 {ticker: DataFrame}"""
    results = {}
    for ticker in tickers:
        df = fetch_ohlcv(ticker, start_date, end_date)
        if not df.empty:
            results[ticker] = df
    return results
