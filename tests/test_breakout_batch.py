"""
test_breakout_batch.py — Phase 4a 批次測試
跑 BreakoutStrategy 在整個 watchlist 上，並對比 Buy & Hold。

輸出一張對照表，告訴你策略在哪些股票上有效。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from engine.runner import run_backtest
from engine.strategies.breakout import BreakoutStrategy
from pipeline.db import get_connection, load_prices


def buy_and_hold_return(ticker: str) -> tuple[float, float]:
    """
    計算 Buy & Hold 報酬率（用 watchlist 同樣的時間範圍）。
    回傳 (return_pct, max_drawdown_pct)
    """
    conn = get_connection()
    df = load_prices(conn, ticker)
    conn.close()

    if df.empty or len(df) < 2:
        return 0.0, 0.0

    first_close = df["close"].iloc[0]
    last_close = df["close"].iloc[-1]
    return_pct = (last_close / first_close - 1) * 100

    # 計算最大回撤
    cum_max = df["close"].cummax()
    drawdown = (df["close"] - cum_max) / cum_max * 100
    max_dd = abs(drawdown.min())

    return return_pct, max_dd


def load_watchlist() -> list[str]:
    config_path = ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("watchlist", [])


def run_batch():
    watchlist = load_watchlist()
    if not watchlist:
        print("❌ Watchlist 是空的")
        return

    print(f"\n{'='*70}")
    print(f"Phase 4a: Batch Test — BreakoutStrategy vs Buy & Hold")
    print(f"{'='*70}")
    print(f"Watchlist: {', '.join(watchlist)}\n")

    results = []

    for ticker in watchlist:
        print(f"\n{'─'*70}")
        print(f"Testing: {ticker}")
        print(f"{'─'*70}")

        # 1. 跑策略
        try:
            strat_result = run_backtest(
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
            print(f"  ❌ Strategy failed: {e}")
            continue

        if not strat_result:
            continue

        # 2. 算 Buy & Hold
        bh_return, bh_dd = buy_and_hold_return(ticker)

        # 3. 收集
        results.append({
            "ticker": ticker,
            "strat_return": strat_result.get("return_pct", 0),
            "strat_dd": strat_result.get("max_drawdown_pct", 0),
            "strat_sharpe": strat_result.get("sharpe"),
            "bh_return": bh_return,
            "bh_dd": bh_dd,
        })

    # ===== 印出對照表 =====
    print(f"\n\n{'='*78}")
    print(f"📊 BATCH RESULTS — Breakout Strategy vs Buy & Hold")
    print(f"{'='*78}\n")

    header = f"{'Ticker':<8} │ {'Strategy Ret':>13} │ {'B&H Ret':>10} │ {'Diff':>10} │ {'Strat DD':>10} │ {'B&H DD':>10}"
    print(header)
    print("─" * 78)

    strat_wins = 0
    total_strat = 0
    total_bh = 0

    for r in results:
        diff = r["strat_return"] - r["bh_return"]
        diff_marker = "✅" if diff > 0 else "❌"

        if diff > 0:
            strat_wins += 1

        total_strat += r["strat_return"]
        total_bh += r["bh_return"]

        sharpe_str = f"{r['strat_sharpe']:.2f}" if r['strat_sharpe'] else "N/A"

        print(
            f"{r['ticker']:<8} │ "
            f"{r['strat_return']:+11.2f}% │ "
            f"{r['bh_return']:+8.2f}% │ "
            f"{diff_marker} {diff:+6.2f}% │ "
            f"{r['strat_dd']:>8.2f}% │ "
            f"{r['bh_dd']:>8.2f}%"
        )

    print("─" * 78)

    n = len(results)
    if n > 0:
        avg_strat = total_strat / n
        avg_bh = total_bh / n

        print(f"\n📈 Strategy avg return:  {avg_strat:+.2f}%")
        print(f"📈 Buy & Hold avg return: {avg_bh:+.2f}%")
        print(f"🎯 Strategy beat B&H on:  {strat_wins}/{n} stocks")

        if strat_wins >= n / 2:
            print(f"\n✅ Strategy is competitive — proceed to Phase 4b (add sentiment)")
        else:
            print(f"\n⚠️  Strategy underperforms B&H — consider tuning params first")
            print(f"    Try: longer entry_period (50?), tighter stop_loss (5%?)")


if __name__ == "__main__":
    run_batch()