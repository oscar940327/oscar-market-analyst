"""
signal_scanner.py — 每日訊號掃描器（Phase 5.5 + 方向 A 修正版）

最終策略設計（基於跨熊市 4 年回測證據）：
  - 進場：純技術面突破 20 日高（來自 4a baseline，已證實 +114% 平均報酬）
  - 出場：技術停損 / 移動停損 / 趨勢反轉（4a baseline）
  - 緊急保險：sentiment severity > 0.8 或 sentiment < -0.7 觸發出場（4c 緊急平倉層）
  - 倉位：固定 95%（不用 regime sizer，已證實傷害報酬）

對每檔股票同時執行：
  1. 上述策略訊號掃描 → BUY / EMERGENCY_EXIT / HOLD
  2. 6 維度綜合技術評分
  3. 操作參考價位（理想買入、停損、目標）
"""
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backtrader as bt
import yaml

from pipeline.db import get_connection, load_merged, load_prices
from engine.feeds.sentiment_feed import SentimentPandasData
from analyzer.composite_scorer import compute_composite_score, CompositeScore
from analyzer.price_levels import compute_price_levels, PriceLevels


@dataclass
class TradingSignal:
    ticker: str
    action: str                  # "BUY", "EMERGENCY_EXIT", "HOLD"
    close_price: float

    # 進場訊號欄位
    entry_trigger: float = 0.0
    stop_loss: float = 0.0
    trailing_stop_initial: float = 0.0
    n_day_high: float = 0.0
    sentiment_score: float = 0.0
    event_severity: float = 0.0
    sentiment_reasoning: str = ""
    filter_reason: str = ""
    market_regime: str = "neutral"

    # Phase 5.5
    composite: Optional[CompositeScore] = None
    levels: Optional[PriceLevels] = None


class SignalScanStrategy(bt.Strategy):
    """
    最終版掃描策略：4a baseline 邏輯 + sentiment 緊急平倉保險層
    
    跟 BreakoutStrategy 相同的進出場邏輯，但加 sentiment 緊急平倉檢查。
    不使用 regime sizer。
    """
    params = (
        ("entry_period", 20),
        ("exit_period", 10),
        ("stop_loss_pct", 0.08),
        ("trailing_pct", 0.15),
        # 緊急平倉門檻（極端值才觸發）
        ("severity_trigger", 0.8),
        ("sentiment_floor", -0.7),
    )

    def __init__(self):
        self.high_n = bt.indicators.Highest(
            self.data.high(-1), period=self.p.entry_period
        )
        self.low_m = bt.indicators.Lowest(
            self.data.low(-1), period=self.p.exit_period
        )
        self.signal: TradingSignal | None = None

    def next(self):
        pass

    def stop(self):
        close = self.data.close[0]
        high_n = self.high_n[0]
        sentiment = self.data.sentiment_score[0]
        severity = self.data.event_severity[0]

        ticker = self.data._name
        has_sentiment = abs(sentiment) > 0.001 or severity > 0.001

        # ===== 1. 緊急平倉保險（最優先）=====
        # 假設使用者已持有，severity 或 sentiment 觸發極端值就出場
        if has_sentiment:
            if severity > self.p.severity_trigger:
                self.signal = TradingSignal(
                    ticker=ticker,
                    action="EMERGENCY_EXIT",
                    close_price=close,
                    sentiment_score=sentiment,
                    event_severity=severity,
                    filter_reason=f"event_severity={severity:.2f} > {self.p.severity_trigger}",
                )
                return
            if sentiment < self.p.sentiment_floor:
                self.signal = TradingSignal(
                    ticker=ticker,
                    action="EMERGENCY_EXIT",
                    close_price=close,
                    sentiment_score=sentiment,
                    event_severity=severity,
                    filter_reason=f"sentiment={sentiment:.2f} < {self.p.sentiment_floor}",
                )
                return

        # ===== 2. 進場訊號（純技術面）=====
        # 4a baseline 邏輯：突破 20 日高即可進場，不過濾 sentiment
        if close > high_n:
            self.signal = TradingSignal(
                ticker=ticker,
                action="BUY",
                close_price=close,
                entry_trigger=close,
                stop_loss=close * (1 - self.p.stop_loss_pct),
                trailing_stop_initial=close * (1 - self.p.trailing_pct),
                n_day_high=high_n,
                sentiment_score=sentiment,
                event_severity=severity,
            )
            return

        # ===== 3. 沒訊號 =====
        self.signal = TradingSignal(
            ticker=ticker,
            action="HOLD",
            close_price=close,
            sentiment_score=sentiment,
            event_severity=severity,
        )


def scan_ticker(ticker: str) -> TradingSignal | None:
    conn = get_connection()

    df_merged = load_merged(conn, ticker)
    if df_merged.empty:
        conn.close()
        return None

    # 取最後 sentiment 的 reasoning + regime
    reasoning = ""
    regime = "neutral"
    if len(df_merged) >= 2:
        prev_date = df_merged.index[-2].strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT reasoning, market_regime FROM daily_sentiment "
            "WHERE ticker=? AND trade_date=?",
            (ticker, prev_date)
        ).fetchone()
        if row:
            reasoning = row[0] or ""
            regime = row[1] or "neutral"

    keep = ["open", "high", "low", "close", "volume",
            "sentiment_score", "event_severity"]
    df_bt = df_merged[[c for c in keep if c in df_merged.columns]]

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000)
    data = SentimentPandasData(dataname=df_bt)
    cerebro.adddata(data, name=ticker)
    cerebro.addstrategy(SignalScanStrategy)
    results = cerebro.run()

    signal = results[0].signal
    if signal:
        signal.sentiment_reasoning = reasoning
        signal.market_regime = regime

    # 綜合評分（用純價格資料）
    df_prices = load_prices(conn, ticker)
    composite = compute_composite_score(ticker, df_prices)
    levels = compute_price_levels(ticker, df_prices)

    if signal:
        signal.composite = composite
        signal.levels = levels

    conn.close()
    return signal


def scan_watchlist() -> list[TradingSignal]:
    config_path = ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    watchlist = config.get("watchlist", [])

    signals = []
    for ticker in watchlist:
        try:
            sig = scan_ticker(ticker)
            if sig:
                signals.append(sig)
        except Exception as e:
            print(f"  ⚠️ {ticker}: scan failed: {e}")

    return signals


if __name__ == "__main__":
    print("🔍 Scanning watchlist (4a baseline + emergency exit)...\n")
    signals = scan_watchlist()

    for sig in signals:
        icon = {
            "BUY": "🟢", "EMERGENCY_EXIT": "🚨", "HOLD": "⚪",
        }.get(sig.action, "❓")

        score_str = ""
        if sig.composite:
            score_str = f"  [{sig.composite.signal.value} {sig.composite.total_score}/100]"

        print(f"{icon} {sig.ticker}: {sig.action}{score_str}")
        print(f"   Close: ${sig.close_price:.2f}")

        if sig.composite:
            c = sig.composite
            print(f"   Trend: {c.trend_status.value} | "
                  f"Bias: {c.bias_ma5:+.1f}% | "
                  f"RSI: {c.rsi_value:.0f}")

        if sig.levels:
            l = sig.levels
            print(f"   Buy: ${l.ideal_buy:.2f} | "
                  f"Stop: ${l.stop_loss_final:.2f} | "
                  f"Target: ${l.take_profit:.2f} | "
                  f"R/R: {l.risk_reward:.2f}")
        print()