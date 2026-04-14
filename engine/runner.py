"""
runner.py — 回測執行器（Phase 4c 版）

新增：把 market_regime 以 dict 形式外掛在 data feed 上，
讓 strategy 可以在 next() 裡用 data._regime_series 拿到當天的 regime。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backtrader as bt

from pipeline.db import get_connection, load_merged, load_sentiment
from engine.feeds.sentiment_feed import SentimentPandasData


def run_backtest(
    ticker: str,
    strategy_class: type[bt.Strategy],
    cash: float = 100000,
    commission: float = 0.001,
    start_date: str | None = None,
    end_date: str | None = None,
    strategy_params: dict | None = None,
    print_summary: bool = True,
) -> dict:
    print(f"\n{'='*55}")
    print(f"Backtest: {ticker} with {strategy_class.__name__}")
    print(f"{'='*55}")

    conn = get_connection()
    df = load_merged(conn, ticker, start_date, end_date)

    # 順便拿 sentiment 裡的 market_regime（字串，沒辦法當 line）
    sent_df = load_sentiment(conn, ticker, start_date, end_date)
    regime_series: dict[str, str] = {}
    if not sent_df.empty:
        # 注意：regime 也要 shift 1 天才能在 T+1 使用（跟 sentiment 一樣）
        shifted = sent_df["market_regime"].shift(1)
        for idx, val in shifted.items():
            if val and str(val) != "nan":
                key = idx.strftime("%Y-%m-%d")
                regime_series[key] = str(val)

    conn.close()

    if df.empty:
        print(f"  ❌ No data for {ticker}")
        return {}

    df = df.copy()
    keep_cols = ["open", "high", "low", "close", "volume",
                 "sentiment_score", "event_severity"]
    df = df[[c for c in keep_cols if c in df.columns]]

    print(f"  📊 Loaded {len(df)} bars ({df.index[0].date()} ~ {df.index[-1].date()})")
    has_sent = (df["sentiment_score"].abs() > 0.001) | (df["event_severity"] > 0.001)
    print(f"  💭 Bars with sentiment data: {has_sent.sum()}")
    if regime_series:
        regime_counts = {"bull": 0, "neutral": 0, "bear": 0}
        for r in regime_series.values():
            if r in regime_counts:
                regime_counts[r] += 1
        print(f"  📈 Regime distribution: {regime_counts}")

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    data = SentimentPandasData(dataname=df)
    data._regime_series = regime_series
    cerebro.adddata(data, name=ticker)

    if strategy_params:
        cerebro.addstrategy(strategy_class, **strategy_params)
    else:
        cerebro.addstrategy(strategy_class)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    initial = cerebro.broker.getvalue()
    results = cerebro.run()
    final = cerebro.broker.getvalue()

    strat = results[0]
    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    dd = strat.analyzers.drawdown.get_analysis().get("max", {}).get("drawdown", 0)
    rtot = strat.analyzers.returns.get_analysis().get("rtot", 0)

    summary = {
        "ticker": ticker,
        "strategy": strategy_class.__name__,
        "initial": initial,
        "final": final,
        "return_pct": (final / initial - 1) * 100,
        "total_return_pct": rtot * 100,
        "sharpe": sharpe,
        "max_drawdown_pct": dd,
        "bars": len(df),
    }

    if print_summary:
        print(f"\n  ── Results ──")
        print(f"  Initial:      ${initial:,.2f}")
        print(f"  Final:        ${final:,.2f}")
        print(f"  Return:       {summary['return_pct']:+.2f}%")
        if sharpe:
            print(f"  Sharpe:       {sharpe:.2f}")
        print(f"  Max DD:       -{dd:.2f}%")

    return summary


if __name__ == "__main__":
    from engine.strategies.breakout_v2 import BreakoutV2Strategy

    result = run_backtest(
        ticker="TSLA",
        strategy_class=BreakoutV2Strategy,
        cash=100000,
    )