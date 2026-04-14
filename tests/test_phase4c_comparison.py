"""
test_phase4c_comparison.py — Phase 4c 三方對照測試

1. Baseline            (4a) — 純技術面突破
2. +Sentiment (old)    (4b) — sentiment 進場過濾 + 緊急平倉
3. +Emergency+Regime   (4c) — sentiment 只做緊急平倉 + regime 動態倉位

四欄對照 + Buy & Hold 基準。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from engine.runner import run_backtest
from engine.strategies.breakout import BreakoutStrategy
from engine.runner import run_backtest
from engine.strategies.breakout import BreakoutStrategy
from engine.strategies.breakout_sentiment import BreakoutSentimentStrategy
from engine.strategies.breakout_v2 import BreakoutV2Strategy
from pipeline.db import get_connection, load_prices


def buy_and_hold_return(ticker: str) -> float:
    conn = get_connection()
    df = load_prices(conn, ticker)
    conn.close()
    if df.empty or len(df) < 2:
        return 0.0
    return (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100


def load_watchlist() -> list[str]:
    config_path = ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("watchlist", [])


def run_three_way():
    watchlist = load_watchlist()
    if not watchlist:
        print("❌ Watchlist 是空的")
        return

    print(f"\n{'='*85}")
    print(f"Phase 4c: Three-Way Comparison")
    print(f"{'='*85}")
    print(f"Watchlist: {', '.join(watchlist)}\n")

    results = []

    for ticker in watchlist:
        print(f"\n{'─'*85}")
        print(f"Testing: {ticker}")
        print(f"{'─'*85}")

        row = {"ticker": ticker}

        # 1. Baseline 4a
        try:
            print(f"\n[4a Baseline]")
            r = run_backtest(
                ticker=ticker,
                strategy_class=BreakoutStrategy,
                cash=100000,
                commission=0.001,
                strategy_params={
                    "entry_period": 20,
                    "exit_period": 10,
                    "stop_loss_pct": 0.08,
                    "trailing_pct": 0.15,
                },
                print_summary=False,
            )
            row["baseline"] = r.get("return_pct", 0) if r else 0
            row["baseline_dd"] = r.get("max_drawdown_pct", 0) if r else 0
        except Exception as e:
            print(f"  ❌ 4a failed: {e}")
            continue

        # 2. Phase 4b (sentiment 進場過濾 + 緊急平倉)
        try:
            print(f"\n[4b +Sentiment filter + emergency]")
            r = run_backtest(
                ticker=ticker,
                strategy_class=BreakoutSentimentStrategy,
                cash=100000,
                commission=0.001,
                strategy_params={
                    "entry_period": 20,
                    "exit_period": 10,
                    "stop_loss_pct": 0.08,
                    "trailing_pct": 0.15,
                    "sentiment_threshold": 0.3,
                    "severity_trigger": 0.8,
                    "sentiment_floor": -0.7,
                },
                print_summary=False,
            )
            row["phase4b"] = r.get("return_pct", 0) if r else 0
        except Exception as e:
            print(f"  ❌ 4b failed: {e}")
            row["phase4b"] = 0

        # 3. Phase 4c (只做緊急平倉 + regime 倉位)
        try:
            print(f"\n[4c Emergency-only + regime sizing]")
            r = run_backtest(
                ticker=ticker,
                strategy_class=BreakoutV2Strategy,
                cash=100000,
                commission=0.001,
                strategy_params={
                    "entry_period": 20,
                    "exit_period": 10,
                    "stop_loss_pct": 0.08,
                    "trailing_pct": 0.15,
                    "severity_trigger": 0.8,
                    "sentiment_floor": -0.7,
                    "bull_size_pct": 0.80,
                    "neutral_size_pct": 0.50,
                    "bear_size_pct": 0.20,
                    "use_sentiment_exit": True,
                    "use_regime_sizing": True,
                },
                print_summary=False,
            )
            row["phase4c"] = r.get("return_pct", 0) if r else 0
            row["phase4c_dd"] = r.get("max_drawdown_pct", 0) if r else 0
        except Exception as e:
            print(f"  ❌ 4c failed: {e}")
            row["phase4c"] = 0

        row["bh"] = buy_and_hold_return(ticker)
        results.append(row)

    # ===== 對照表 =====
    print(f"\n\n{'='*90}")
    print(f"📊 THREE-WAY COMPARISON")
    print(f"{'='*90}\n")

    header = (
        f"{'Ticker':<8} │ "
        f"{'4a Baseline':>12} │ "
        f"{'4b +Sent':>12} │ "
        f"{'4c +Regime':>12} │ "
        f"{'B&H':>10}"
    )
    print(header)
    print("─" * 90)

    n = len(results)
    sum_baseline = 0
    sum_4b = 0
    sum_4c = 0
    sum_bh = 0
    c_beat_baseline = 0
    c_beat_4b = 0

    for r in results:
        sum_baseline += r["baseline"]
        sum_4b += r["phase4b"]
        sum_4c += r["phase4c"]
        sum_bh += r["bh"]

        if r["phase4c"] > r["baseline"]:
            c_beat_baseline += 1
        if r["phase4c"] > r["phase4b"]:
            c_beat_4b += 1

        print(
            f"{r['ticker']:<8} │ "
            f"{r['baseline']:+10.2f}% │ "
            f"{r['phase4b']:+10.2f}% │ "
            f"{r['phase4c']:+10.2f}% │ "
            f"{r['bh']:+8.2f}%"
        )

    print("─" * 90)

    if n > 0:
        print(f"\n📈 Average Returns:")
        print(f"   4a Baseline:       {sum_baseline/n:+.2f}%")
        print(f"   4b +Sentiment:     {sum_4b/n:+.2f}%")
        print(f"   4c +Regime Sizer:  {sum_4c/n:+.2f}%")
        print(f"   Buy & Hold:        {sum_bh/n:+.2f}%")

        print(f"\n🎯 4c beats 4a Baseline: {c_beat_baseline}/{n}")
        print(f"🎯 4c beats 4b:          {c_beat_4b}/{n}")

        print(f"\n📉 Max Drawdown (lower is better):")
        avg_baseline_dd = sum(r.get("baseline_dd", 0) for r in results) / n
        avg_4c_dd = sum(r.get("phase4c_dd", 0) for r in results) / n
        print(f"   4a Baseline:       -{avg_baseline_dd:.2f}%")
        print(f"   4c +Regime Sizer:  -{avg_4c_dd:.2f}%")

        if avg_4c_dd < avg_baseline_dd:
            print(f"   ✅ 4c reduced drawdown by {avg_baseline_dd - avg_4c_dd:.2f}%")
        else:
            print(f"   ⚠️ 4c did not reduce drawdown")


if __name__ == "__main__":
    run_three_way()