"""
test_sentiment_comparison.py — Phase 4b 核心測試
同時跑 baseline (4a) 和 sentiment 版 (4b)，直接對比差異。

輸出 4 欄表格：
    Ticker | Baseline | +Sentiment | Improvement | B&H
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from engine.runner import run_backtest
from engine.strategies.breakout import BreakoutStrategy
from engine.strategies.breakout_sentiment import BreakoutSentimentStrategy
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


def run_comparison():
    watchlist = load_watchlist()
    if not watchlist:
        print("❌ Watchlist 是空的")
        return

    print(f"\n{'='*70}")
    print(f"Phase 4b: Baseline vs Sentiment-Filtered Comparison")
    print(f"{'='*70}")
    print(f"Watchlist: {', '.join(watchlist)}\n")

    results = []

    for ticker in watchlist:
        print(f"\n{'─'*70}")
        print(f"Testing: {ticker}")
        print(f"{'─'*70}")

        # 1. 跑 baseline (4a)
        try:
            print(f"\n[Baseline - pure technical]")
            baseline = run_backtest(
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
        except Exception as e:
            print(f"  ❌ Baseline failed: {e}")
            continue

        # 2. 跑 sentiment 版 (4b)
        try:
            print(f"\n[+Sentiment filter]")
            sentiment_result = run_backtest(
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
        except Exception as e:
            print(f"  ❌ Sentiment version failed: {e}")
            continue

        if not baseline or not sentiment_result:
            continue

        # 3. 算 Buy & Hold
        bh_return = buy_and_hold_return(ticker)

        results.append({
            "ticker": ticker,
            "baseline_return": baseline.get("return_pct", 0),
            "baseline_dd": baseline.get("max_drawdown_pct", 0),
            "sent_return": sentiment_result.get("return_pct", 0),
            "sent_dd": sentiment_result.get("max_drawdown_pct", 0),
            "bh_return": bh_return,
        })

    # ===== 印對照表 =====
    print(f"\n\n{'='*82}")
    print(f"📊 COMPARISON — Baseline vs +Sentiment vs Buy & Hold")
    print(f"{'='*82}\n")

    header = f"{'Ticker':<8} │ {'Baseline':>12} │ {'+Sentiment':>12} │ {'Improve':>11} │ {'B&H':>10}"
    print(header)
    print("─" * 82)

    sent_wins_baseline = 0
    sent_wins_bh = 0
    baseline_wins_bh = 0

    for r in results:
        improvement = r["sent_return"] - r["baseline_return"]
        improve_marker = "✅" if improvement > 0 else ("❌" if improvement < 0 else "=")

        if r["sent_return"] > r["baseline_return"]:
            sent_wins_baseline += 1
        if r["sent_return"] > r["bh_return"]:
            sent_wins_bh += 1
        if r["baseline_return"] > r["bh_return"]:
            baseline_wins_bh += 1

        print(
            f"{r['ticker']:<8} │ "
            f"{r['baseline_return']:+10.2f}% │ "
            f"{r['sent_return']:+10.2f}% │ "
            f"{improve_marker} {improvement:+7.2f}% │ "
            f"{r['bh_return']:+8.2f}%"
        )

    print("─" * 82)

    n = len(results)
    if n > 0:
        avg_baseline = sum(r["baseline_return"] for r in results) / n
        avg_sent = sum(r["sent_return"] for r in results) / n
        avg_bh = sum(r["bh_return"] for r in results) / n

        print(f"\n📈 Average returns:")
        print(f"   Baseline:     {avg_baseline:+.2f}%")
        print(f"   +Sentiment:   {avg_sent:+.2f}%")
        print(f"   Buy & Hold:   {avg_bh:+.2f}%")
        print(f"\n🎯 +Sentiment beat Baseline on: {sent_wins_baseline}/{n} stocks")
        print(f"🎯 +Sentiment beat Buy & Hold on: {sent_wins_bh}/{n} stocks")
        print(f"🎯 Baseline beat Buy & Hold on: {baseline_wins_bh}/{n} stocks")

        # 判斷 sentiment 有沒有用
        print(f"\n{'─'*82}")
        if sent_wins_baseline >= n * 0.6:
            print(f"✅ Sentiment filter adds value — {sent_wins_baseline}/{n} stocks improved")
            print(f"   → Proceed to Phase 4c (position sizing by market regime)")
        elif sent_wins_baseline >= n * 0.4:
            print(f"⚠️  Sentiment has mixed effects — {sent_wins_baseline}/{n} improved")
            print(f"   → Review parameters (sentiment_threshold, severity_trigger)")
        else:
            print(f"❌ Sentiment hurts more than helps — only {sent_wins_baseline}/{n} improved")
            print(f"   → Investigate: loosen threshold? Check if LLM scores are noisy?")


if __name__ == "__main__":
    run_comparison()