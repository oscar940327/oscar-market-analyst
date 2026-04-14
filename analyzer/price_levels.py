"""
price_levels.py — 計算操作參考價位

純粹用技術面算理想買入價、停損價、目標價。
這些不是 LLM 編出來的數字，是基於：
  - MA5 / MA10 / MA20 (均線)
  - 過去 N 天的最高 / 最低 (Donchian)
  - 固定比例停損

所以是 deterministic 的，每次跑都會給同樣的結果。
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class PriceLevels:
    """單一股票的操作參考價位"""
    ticker: str
    current_price: float
    
    # 買入參考
    ideal_buy: float          # 理想買入價（接近 MA5）
    secondary_buy: float      # 次優買入價（接近 MA10）
    
    # 停損參考
    stop_loss_pct: float      # 固定百分比停損（從現價）
    stop_loss_ma: float       # 跌破 MA20 的價格
    stop_loss_final: float    # 兩者取較高（較保守）
    
    # 目標價
    take_profit: float        # 目標價（前 N 日高點）
    take_profit_label: str    # "20日高" 或 "60日高"
    
    # 風險報酬比
    risk_reward: float        # (目標-現價) / (現價-停損)


def compute_price_levels(
    ticker: str,
    df: pd.DataFrame,
    stop_loss_pct: float = 0.08,
    take_profit_lookback: int = 60,
) -> Optional[PriceLevels]:
    """
    計算操作參考價位。
    
    Args:
        ticker: 股票代碼
        df: OHLCV DataFrame
        stop_loss_pct: 固定百分比停損（預設 -8%）
        take_profit_lookback: 目標價用過去幾天的高點（預設 60 日）
    
    Returns:
        PriceLevels 或 None
    """
    if df is None or df.empty or len(df) < 20:
        return None
    
    df = df.sort_index().copy()
    
    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA10'] = df['close'].rolling(window=10).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()
    
    latest = df.iloc[-1]
    current = float(latest['close'])
    ma5 = float(latest['MA5'])
    ma10 = float(latest['MA10'])
    ma20 = float(latest['MA20'])
    
    # 理想買入：MA5 附近
    ideal_buy = round(ma5, 2)
    
    # 次優買入：MA10 附近
    secondary_buy = round(ma10, 2)
    
    # 停損 1：從現價跌 stop_loss_pct
    stop_loss_pct_price = current * (1 - stop_loss_pct)
    
    # 停損 2：跌破 MA20（只在現價還在 MA20 之上時才有效）
    if current > ma20:
        stop_loss_ma_price = ma20 * 0.99  # 跌破 MA20 1%
        # 取兩者較高的（先觸發）
        stop_loss_final = round(max(stop_loss_pct_price, stop_loss_ma_price), 2)
    else:
        # 現價已經跌破 MA20，只用百分比停損
        stop_loss_ma_price = stop_loss_pct_price  # 紀錄用
        stop_loss_final = round(stop_loss_pct_price, 2)
    
    # 目標價：過去 N 日高點
    lookback = min(take_profit_lookback, len(df))
    take_profit = float(df['high'].tail(lookback).max())
    take_profit_label = f"{lookback}日高"
    
    # 如果現價已經超過過去高點，目標往上推 5%
    if take_profit <= current:
        take_profit = current * 1.05
        take_profit_label = "現價 +5%"
    
    take_profit = round(take_profit, 2)
    
    # 風險報酬比
    risk = current - stop_loss_final
    reward = take_profit - current
    risk_reward = round(reward / risk, 2) if risk > 0 else 0.0
    
    return PriceLevels(
        ticker=ticker,
        current_price=round(current, 2),
        ideal_buy=ideal_buy,
        secondary_buy=secondary_buy,
        stop_loss_pct=round(stop_loss_pct_price, 2),
        stop_loss_ma=round(stop_loss_ma_price, 2),
        stop_loss_final=stop_loss_final,
        take_profit=take_profit,
        take_profit_label=take_profit_label,
        risk_reward=risk_reward,
    )


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    
    from pipeline.db import get_connection, load_prices
    
    conn = get_connection()
    for ticker in ["TSLA", "NVDA"]:
        df = load_prices(conn, ticker)
        if df.empty:
            continue
        
        levels = compute_price_levels(ticker, df)
        if levels is None:
            continue
        
        print(f"\n{ticker}:")
        print(f"  Current:       ${levels.current_price:.2f}")
        print(f"  Ideal buy:     ${levels.ideal_buy:.2f} (MA5)")
        print(f"  Secondary buy: ${levels.secondary_buy:.2f} (MA10)")
        print(f"  Stop loss:     ${levels.stop_loss_final:.2f}")
        print(f"  Take profit:   ${levels.take_profit:.2f} ({levels.take_profit_label})")
        print(f"  R/R ratio:     {levels.risk_reward:.2f}")
    
    conn.close()