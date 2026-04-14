"""
test_breakout.py — Phase 4a 測試腳本
跑 BreakoutStrategy 在單一股票上的回測。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.runner import run_backtest
from engine.strategies.breakout import BreakoutStrategy


if __name__ == "__main__":
    # 改這裡來測試不同股票
    TICKER = "TSLA"

    print(f"\n{'='*60}")
    print(f"Phase 4a: Pure Breakout Strategy Test")
    print(f"{'='*60}")

    result = run_backtest(
        ticker=TICKER,
        strategy_class=BreakoutStrategy,
        cash=100000,
        commission=0.001,
        strategy_params={
            "entry_period": 20,
            "exit_period": 10,
            "stop_loss_pct": 0.08,
            "trailing_pct": 0.15,
        },
    )