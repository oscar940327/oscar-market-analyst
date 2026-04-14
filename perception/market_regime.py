"""
market_regime.py — 大盤狀態判斷器
不靠 LLM 猜，用 SPY 和 VIX 的價格走勢計算客觀的市場狀態。

規則：
- SPY 收盤 > 50 日均線 → bull
- SPY 收盤 < 50 日均線 → bear
- 介於中間的灰色地帶 → neutral
- VIX > 30 → 強制改為 bear（恐慌期，無論 SPY 在哪）
- VIX > 25 且 SPY < MA50 → 確認 bear

這個值每天算一次，所有股票共用。
"""
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from perception.price_fetcher import fetch_ohlcv

Regime = Literal["bull", "neutral", "bear"]


def calculate_market_regime(
    lookback_days: int = 80,
) -> tuple[Regime, dict]:
    """
    抓 SPY 和 VIX 計算當前的大盤狀態。

    Returns:
        (regime, info) — regime 是 bull/neutral/bear，info 是 debug 用的數據
    """
    # 抓最近 80 天的 SPY 和 VIX（要至少 50 天才能算 MA50）
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days + 30)).strftime("%Y-%m-%d")

    print("  📥 fetching SPY...")
    spy_df = fetch_ohlcv("SPY", start_date, end_date)

    print("  📥 fetching ^VIX...")
    vix_df = fetch_ohlcv("^VIX", start_date, end_date)

    if spy_df.empty:
        print("  ⚠️ SPY data unavailable, defaulting to neutral")
        return "neutral", {"reason": "spy_data_missing"}

    # 計算 SPY 的 MA50
    spy_df = spy_df.copy()
    spy_df["ma50"] = spy_df["close"].rolling(window=50).mean()

    if len(spy_df) < 50:
        print(f"  ⚠️ SPY data only {len(spy_df)} rows (<50), defaulting to neutral")
        return "neutral", {"reason": "insufficient_history"}

    last = spy_df.iloc[-1]
    spy_close = float(last["close"])
    spy_ma50 = float(last["ma50"])

    # 偏離 MA50 多少 %
    deviation_pct = (spy_close - spy_ma50) / spy_ma50 * 100

    # VIX 取最後一筆
    vix_close = None
    if not vix_df.empty:
        vix_close = float(vix_df.iloc[-1]["close"])

    info = {
        "spy_close": round(spy_close, 2),
        "spy_ma50": round(spy_ma50, 2),
        "deviation_pct": round(deviation_pct, 2),
        "vix_close": round(vix_close, 2) if vix_close else None,
    }

    # ===== 判斷邏輯 =====
    # VIX 強制 override
    if vix_close is not None and vix_close > 30:
        info["reason"] = "vix_panic"
        return "bear", info

    # SPY 偏離 MA50 超過 ±2% 才算明確趨勢，否則算 neutral
    if deviation_pct > 2.0:
        regime = "bull"
    elif deviation_pct < -2.0:
        regime = "bear"
    else:
        regime = "neutral"

    # VIX 確認 bear
    if regime == "bear" and vix_close is not None and vix_close > 25:
        info["reason"] = "spy_below_ma50_confirmed_by_vix"
    elif regime == "bear":
        info["reason"] = "spy_below_ma50"
    elif regime == "bull":
        info["reason"] = "spy_above_ma50"
    else:
        info["reason"] = "spy_near_ma50"

    return regime, info


if __name__ == "__main__":
    regime, info = calculate_market_regime()
    print(f"\n📊 Market Regime: {regime}")
    print(f"   Info: {info}")