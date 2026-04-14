"""
breakout_sentiment.py — 加上 sentiment 過濾 + 緊急平倉的混合策略（Phase 4b）

繼承 4a 的 BreakoutStrategy 邏輯，加兩層 sentiment 判斷：

1. 進場過濾（soft gate）：
   - 技術面條件：突破 N 日高點
   - sentiment 條件：sentiment_score >= sentiment_threshold（預設 0.3）
   - 如果當天沒有 sentiment 資料（=0），FALLBACK 到純技術面不過濾
   - 這樣設計讓策略在有 sentiment 時變嚴格，沒 sentiment 時等於 4a baseline

2. 緊急平倉（hard exit）：
   - event_severity > severity_trigger（預設 0.8）OR
   - sentiment_score < sentiment_floor（預設 -0.7）
   - 任一觸發 → 隔天開盤市價出場，不等技術面停損
   - 這是為了避開黑天鵝（像 CEO 被起訴、重大訴訟）
"""
import backtrader as bt


class BreakoutSentimentStrategy(bt.Strategy):
    params = (
        # 技術面參數（與 4a 相同）
        ("entry_period", 20),
        ("exit_period", 10),
        ("stop_loss_pct", 0.08),
        ("trailing_pct", 0.15),
        ("size_pct", 0.95),

        # sentiment 參數（新增）
        ("sentiment_threshold", 0.3),      # 進場要求 sentiment > 此值
        ("severity_trigger", 0.8),         # event_severity > 此值觸發緊急平倉
        ("sentiment_floor", -0.7),         # sentiment < 此值觸發緊急平倉
    )

    def __init__(self):
        # 技術指標（與 4a 相同，用 -1 排除今天避免訊號當天成交）
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

        # sentiment 專屬統計
        self.sentiment_filtered_count = 0   # 因為 sentiment 不足被擋下的進場次數
        self.emergency_exits = 0            # 緊急平倉次數

    def log(self, txt: str):
        dt = self.data.datetime.date(0)
        print(f"  {dt} │ {txt}")

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

    def _has_sentiment(self, sentiment: float, severity: float) -> bool:
        """判斷當天是否有真的 sentiment 資料（非零即視為有）"""
        return abs(sentiment) > 0.001 or severity > 0.001

    def next(self):
        if self.order:
            return

        close = self.data.close[0]
        sentiment = self.data.sentiment_score[0]
        severity = self.data.event_severity[0]

        # ========== 有持倉：優先檢查緊急平倉 ==========
        if self.position:
            # 更新進場後最高價
            if close > self.highest_since_entry:
                self.highest_since_entry = close

            # 緊急平倉條件（只在有 sentiment 資料時觸發）
            if self._has_sentiment(sentiment, severity):
                if severity > self.p.severity_trigger:
                    self.log(f"🚨 EMERGENCY EXIT: event_severity={severity:.2f} > {self.p.severity_trigger}")
                    self.order = self.close()
                    self.emergency_exits += 1
                    return
                if sentiment < self.p.sentiment_floor:
                    self.log(f"🚨 EMERGENCY EXIT: sentiment={sentiment:.2f} < {self.p.sentiment_floor}")
                    self.order = self.close()
                    self.emergency_exits += 1
                    return

            # 一般出場條件（跟 4a 相同）
            exit_reason = None
            if close < self.low_m[0]:
                exit_reason = f"trend reversal (close ${close:.2f} < {self.p.exit_period}d low ${self.low_m[0]:.2f})"
            elif close < self.entry_price * (1 - self.p.stop_loss_pct):
                exit_reason = f"stop loss (-{self.p.stop_loss_pct*100:.0f}% from entry ${self.entry_price:.2f})"
            elif close < self.highest_since_entry * (1 - self.p.trailing_pct):
                exit_reason = f"trailing stop (-{self.p.trailing_pct*100:.0f}% from peak ${self.highest_since_entry:.2f})"

            if exit_reason:
                self.log(f"📉 EXIT: {exit_reason}")
                self.order = self.close()
            return

        # ========== 沒持倉：檢查進場訊號 ==========
        # 先看技術面
        if close <= self.high_n[0]:
            return  # 沒突破就不用繼續

        # 再看 sentiment 過濾（軟接入）
        if self._has_sentiment(sentiment, severity):
            # 有 sentiment 資料 → 用它過濾
            if sentiment < self.p.sentiment_threshold:
                self.sentiment_filtered_count += 1
                # debug 印出被擋的訊號，方便之後分析
                # self.log(f"🛑 Breakout filtered by sentiment ({sentiment:.2f} < {self.p.sentiment_threshold})")
                return
            entry_note = f"sentiment={sentiment:+.2f} ✓"
        else:
            # 沒 sentiment → fallback 純技術面
            entry_note = "(no sentiment, pure technical)"

        # 通過過濾 → 下單
        cash = self.broker.getvalue() * self.p.size_pct
        size = int(cash / close)
        if size > 0:
            self.log(f"📈 Breakout! close ${close:.2f} > {self.p.entry_period}d high ${self.high_n[0]:.2f} {entry_note}")
            self.order = self.buy(size=size)

    def stop(self):
        total_trades = self.trades_won + self.trades_lost
        win_rate = (self.trades_won / total_trades * 100) if total_trades > 0 else 0
        print(f"\n  ── Trade Summary ──")
        print(f"  Total trades:         {total_trades}  (Won: {self.trades_won}, Lost: {self.trades_lost})")
        print(f"  Win rate:             {win_rate:.1f}%")
        print(f"  Net P&L:              ${self.total_pnl:+,.2f}")
        print(f"  Filtered by sentiment: {self.sentiment_filtered_count}  (entries blocked)")
        print(f"  Emergency exits:      {self.emergency_exits}")