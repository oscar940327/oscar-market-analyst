"""
breakout_v2.py — Phase 4c 最終版策略

設計理念（來自 FINSABER 論文 + 你的實驗結論）：
1. 平時完全不用 sentiment 過濾進場（避免 LLM 雜訊影響日常決策）
2. sentiment 只做「緊急平倉」— event_severity > 0.8 或 sentiment < -0.7
3. 倉位大小由 market_regime 動態決定：
   - bull regime → 80% 資金
   - neutral regime → 50% 資金
   - bear regime → 20% 資金

這樣的設計把 LLM 的雜訊隔離在「極端事件偵測」這個窄用途上，
主要的 alpha 來源是「技術面 + 大盤風險控管」。
"""
import backtrader as bt


class BreakoutV2Strategy(bt.Strategy):
    params = (
        # 技術面
        ("entry_period", 20),
        ("exit_period", 10),
        ("stop_loss_pct", 0.08),
        ("trailing_pct", 0.15),

        # sentiment 緊急平倉（只在極端值觸發）
        ("severity_trigger", 0.8),
        ("sentiment_floor", -0.7),

        # regime 動態倉位
        ("bull_size_pct", 0.80),
        ("neutral_size_pct", 0.50),
        ("bear_size_pct", 0.20),

        # 是否啟用各個功能（方便做消融測試）
        ("use_sentiment_exit", True),
        ("use_regime_sizing", True),
    )

    def __init__(self):
        # 技術指標（排除當天避免 lookahead）
        self.high_n = bt.indicators.Highest(
            self.data.high(-1), period=self.p.entry_period
        )
        self.low_m = bt.indicators.Lowest(
            self.data.low(-1), period=self.p.exit_period
        )

        self.entry_price = None
        self.highest_since_entry = None
        self.order = None

        # 統計
        self.trades_won = 0
        self.trades_lost = 0
        self.total_pnl = 0.0
        self.emergency_exits = 0
        self.regime_size_history = {"bull": 0, "neutral": 0, "bear": 0}

    def log(self, txt: str):
        dt = self.data.datetime.date(0)
        print(f"  {dt} │ {txt}")

    def _get_current_regime(self) -> str:
        """
        目前的 market_regime。這個資料沒透過 PandasData line 傳進來
        （因為 regime 是字串不是數字），所以要從別的地方拿。
        這裡先用一個簡單的做法：從 data feed 外掛的 dict 拿。
        如果沒有就回傳 neutral。
        """
        # runner 會把 regime series 綁在 data 上
        regime_series = getattr(self.data, "_regime_series", None)
        if regime_series is None:
            return "neutral"

        dt = self.data.datetime.date(0)
        key = dt.strftime("%Y-%m-%d")
        return regime_series.get(key, "neutral")

    def _get_position_pct(self, regime: str) -> float:
        if not self.p.use_regime_sizing:
            return 0.95  # 不用 regime sizing 就用固定 95%

        if regime == "bull":
            return self.p.bull_size_pct
        if regime == "bear":
            return self.p.bear_size_pct
        return self.p.neutral_size_pct

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.highest_since_entry = order.executed.price
                self.log(f"▲ BUY  ${order.executed.price:7.2f} × {order.executed.size}")
            else:
                self.log(f"▼ SELL ${order.executed.price:7.2f} × {abs(order.executed.size)}")
                self.entry_price = None
                self.highest_since_entry = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"✗ Order failed: {order.getstatusname()}")

        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

        self.total_pnl += trade.pnlcomm
        if trade.pnlcomm > 0:
            self.trades_won += 1
            symbol = "+"
        else:
            self.trades_lost += 1
            symbol = "-"
        self.log(f"{symbol} P&L: ${trade.pnlcomm:+,.2f}")

    def next(self):
        if self.order:
            return

        close = self.data.close[0]
        sentiment = self.data.sentiment_score[0]
        severity = self.data.event_severity[0]
        has_sentiment = abs(sentiment) > 0.001 or severity > 0.001

        # ========== 持倉中 ==========
        if self.position:
            if close > self.highest_since_entry:
                self.highest_since_entry = close

            # 緊急平倉檢查（只在極端值觸發）
            if self.p.use_sentiment_exit and has_sentiment:
                if severity > self.p.severity_trigger:
                    self.log(f"🚨 EMERGENCY EXIT: severity={severity:.2f} > {self.p.severity_trigger}")
                    self.order = self.close()
                    self.emergency_exits += 1
                    return
                if sentiment < self.p.sentiment_floor:
                    self.log(f"🚨 EMERGENCY EXIT: sentiment={sentiment:.2f} < {self.p.sentiment_floor}")
                    self.order = self.close()
                    self.emergency_exits += 1
                    return

            # 常規出場條件
            exit_reason = None
            if close < self.low_m[0]:
                exit_reason = f"trend reversal (close ${close:.2f} < ${self.low_m[0]:.2f})"
            elif close < self.entry_price * (1 - self.p.stop_loss_pct):
                exit_reason = f"stop loss (-{self.p.stop_loss_pct*100:.0f}%)"
            elif close < self.highest_since_entry * (1 - self.p.trailing_pct):
                exit_reason = f"trailing stop (-{self.p.trailing_pct*100:.0f}%)"

            if exit_reason:
                self.log(f"📉 EXIT: {exit_reason}")
                self.order = self.close()
            return

        # ========== 無持倉 ==========
        # 純技術面判斷進場（不用 sentiment 過濾）
        if close > self.high_n[0]:
            # 拿當下的 regime 決定倉位
            regime = self._get_current_regime()
            size_pct = self._get_position_pct(regime)
            self.regime_size_history[regime] += 1

            cash = self.broker.getvalue() * size_pct
            size = int(cash / close)
            if size > 0:
                self.log(
                    f"📈 Breakout! close ${close:.2f} > {self.p.entry_period}d high "
                    f"${self.high_n[0]:.2f} [{regime} → {size_pct*100:.0f}%]"
                )
                self.order = self.buy(size=size)

    def stop(self):
        total_trades = self.trades_won + self.trades_lost
        win_rate = (self.trades_won / total_trades * 100) if total_trades > 0 else 0
        print(f"\n  ── Trade Summary ──")
        print(f"  Total trades:    {total_trades}  (Won: {self.trades_won}, Lost: {self.trades_lost})")
        print(f"  Win rate:        {win_rate:.1f}%")
        print(f"  Net P&L:         ${self.total_pnl:+,.2f}")
        print(f"  Emergency exits: {self.emergency_exits}")
        if self.p.use_regime_sizing:
            regime_str = ", ".join(f"{k}={v}" for k, v in self.regime_size_history.items() if v > 0)
            print(f"  Regime entries:  {regime_str or 'none'}")