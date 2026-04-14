"""
backfill_regime.py — 歷史 market_regime 回填
對過去 N 天的每個交易日，計算當時的 SPY + VIX → 寫入 daily_sentiment 的 market_regime 欄位。

跟 perception/market_regime.py 的規則一樣：
  - SPY close > MA50 且偏離 > +2% → bull
  - SPY close < MA50 且偏離 < -2% → bear
  - 介於中間 → neutral
  - VIX > 30 → 強制 bear
  - VIX > 25 且 SPY < MA50 → 確認 bear

零 LLM 成本，純計算。幾秒跑完。
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

from perception.price_fetcher import fetch_ohlcv
from pipeline.db import get_connection


def compute_regime_for_date(spy_df, vix_df, target_date: str) -> str:
    """
    對給定日期計算當時的 regime。
    用的是「到那一天為止」的 SPY 價格（避免前視偏誤）。
    """
    # 截取到 target_date 的 SPY 資料
    spy_slice = spy_df[spy_df.index <= target_date]
    if len(spy_slice) < 50:
        return "neutral"  # 資料不足時 default

    last = spy_slice.iloc[-1]
    spy_close = float(last["close"])
    spy_ma50 = float(spy_slice["close"].tail(50).mean())
    deviation_pct = (spy_close - spy_ma50) / spy_ma50 * 100

    # VIX（取到 target_date）
    vix_close = None
    if not vix_df.empty:
        vix_slice = vix_df[vix_df.index <= target_date]
        if not vix_slice.empty:
            vix_close = float(vix_slice.iloc[-1]["close"])

    # VIX 強制 override
    if vix_close is not None and vix_close > 30:
        return "bear"

    # 根據偏離判斷
    if deviation_pct > 2.0:
        return "bull"
    elif deviation_pct < -2.0:
        return "bear"
    else:
        return "neutral"


def backfill_regime(lookback_days: int = 400):
    """
    對過去 lookback_days 天的每一天，算出當時的 regime 並更新 DB。

    注意：這個函式會對 daily_sentiment 裡已有的所有 ticker × date 組合做更新，
    不新增 row，只改 market_regime 欄位。
    """
    print(f"🚀 Regime Backfill — past {lookback_days} days\n")

    # 先看 DB 裡 sentiment 的日期範圍
    conn = get_connection()
    row = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM daily_sentiment"
    ).fetchone()
    conn.close()
    
    if row and row[0]:
        # 用 DB 實際日期範圍 + 80 天緩衝（算 MA50 用）
        from datetime import datetime as _dt
        db_min = _dt.strptime(row[0], "%Y-%m-%d")
        start_date = (db_min - timedelta(days=80)).strftime("%Y-%m-%d")
        end_date = _dt.now().strftime("%Y-%m-%d")
        print(f"  📅 DB sentiment range: {row[0]} ~ {row[1]}")
    else:
        # fallback
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=lookback_days + 80)).strftime("%Y-%m-%d")

    # 1. 先抓一次 SPY 和 VIX 的完整歷史（多抓 80 天以算 MA50）
    print("📥 Fetching SPY full history...")

    spy_df = fetch_ohlcv("SPY", start_date, end_date)
    if spy_df.empty:
        print("❌ Failed to fetch SPY data")
        return

    print("📥 Fetching ^VIX full history...")
    vix_df = fetch_ohlcv("^VIX", start_date, end_date)

    print()

    # 2. 從 daily_sentiment 拿所有需要更新的 trade_date
    conn = get_connection()
    dates = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT trade_date FROM daily_sentiment ORDER BY trade_date"
        ).fetchall()
    ]

    if not dates:
        print("⚠️ daily_sentiment 表是空的，先跑 backfill_sentiment.py")
        conn.close()
        return

    print(f"📅 Found {len(dates)} unique trade dates to process")
    print()

    # 3. 對每個日期算 regime，批次更新
    regime_counts = {"bull": 0, "neutral": 0, "bear": 0}

    for trade_date in dates:
        regime = compute_regime_for_date(spy_df, vix_df, trade_date)
        regime_counts[regime] += 1

        conn.execute(
            "UPDATE daily_sentiment SET market_regime = ? WHERE trade_date = ?",
            (regime, trade_date),
        )

    conn.commit()
    conn.close()

    # 4. 統計
    total = sum(regime_counts.values())
    print("=" * 50)
    print("📊 Regime Distribution")
    print("=" * 50)
    for regime, count in regime_counts.items():
        pct = count / total * 100 if total else 0
        bar = "█" * int(pct / 5)
        print(f"  {regime:<8} {count:>4} days ({pct:>5.1f}%) {bar}")
    print(f"\n✅ Regime backfill complete. Updated {total} dates.")


if __name__ == "__main__":
    backfill_regime()