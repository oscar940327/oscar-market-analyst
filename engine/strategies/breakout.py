"""
breakout.py — N 日高點突破策略（純技術面，Phase 4a 基準線）

進場：收盤突破 N 日高點
出場：
  1. 收盤跌破 M 日低點（趨勢反轉）
  2. 從買入價跌 stop_loss_pct%（硬停損）
  3. 從進場後最高點回撤 trailing_pct%（移動停損保護獲利）

這是 Phase 4 的「對照組」——純技術面，不用 sentiment。
之後 4b 會在這個基礎上加 sentiment 過濾，看績效能不能改善。
"""
import backtrader as bt


class BreakoutStrategy(bt.Strategy):
    params = (
        ("entry_period", 20),       # 進場：突破 N 日高點
        ("exit_period", 10),        # 出場：跌破 M 日低點
        ("stop_loss_pct", 0.08),    # 硬停損：從買入價跌 8%
        ("trailing_pct", 0.15),     # 移動停損：從最高回撤 15%
        ("size_pct", 0.95),         # 部位大小：95% 資金
    )

    def __init__(self):
        # 技術指標
        # 用 highest/lowest，但要排除「今天」這根 K 線（避免訊號當天就成交）
        self.high_n = bt.indicators.Highest(
            self.data.high(-1), period=self.p.entry_period
        )
        self.low_m = bt.indicators.Lowest(
            self.data.low(-1), period=self.p.exit_period
        )

        # 追蹤狀態
        self.entry_price = None        # 進場價
        self.highest_since_entry = None  # 進場後的最高價（用於 trailing stop）
        self.order = None              # 待處理的訂單

        # 統計
        self.trades_won = 0
        self.trades_lost = 0
        self.total_pnl = 0.0

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

        self.log(f"{symbol} P&L: ${trade.pnlcomm:+,.2f}  (gross: ${trade.pnl:+,.2f})")

    def next(self):
        # 已有掛單就等
        if self.order:
            return

        close = self.data.close[0]

        # ========== 沒持倉：找進場訊號 ==========
        if not self.position:
            # 突破 N 日高點
            if close > self.high_n[0]:
                # 計算可買股數（用 95% 資金）
                cash = self.broker.getvalue() * self.p.size_pct
                size = int(cash / close)
                if size > 0:
                    self.log(f"📈 Breakout! close ${close:.2f} > N-day high ${self.high_n[0]:.2f}")
                    self.order = self.buy(size=size)

        # ========== 有持倉：檢查出場條件 ==========
        else:
            # 更新進場後最高價
            if close > self.highest_since_entry:
                self.highest_since_entry = close

            exit_reason = None

            # 條件 1：跌破 M 日低點
            if close < self.low_m[0]:
                exit_reason = f"trend reversal (close ${close:.2f} < {self.p.exit_period}d low ${self.low_m[0]:.2f})"

            # 條件 2：硬停損
            elif close < self.entry_price * (1 - self.p.stop_loss_pct):
                exit_reason = f"stop loss (-{self.p.stop_loss_pct*100:.0f}% from entry ${self.entry_price:.2f})"

            # 條件 3：移動停損
            elif close < self.highest_since_entry * (1 - self.p.trailing_pct):
                exit_reason = f"trailing stop (-{self.p.trailing_pct*100:.0f}% from peak ${self.highest_since_entry:.2f})"

            if exit_reason:
                self.log(f"📉 EXIT: {exit_reason}")
                self.order = self.close()

    def stop(self):
        total_trades = self.trades_won + self.trades_lost
        win_rate = (self.trades_won / total_trades * 100) if total_trades > 0 else 0
        print(f"\n  ── Trade Summary ──")
        print(f"  Total trades: {total_trades}  (Won: {self.trades_won}, Lost: {self.trades_lost})")
        print(f"  Win rate:     {win_rate:.1f}%")
        print(f"  Net P&L:      ${self.total_pnl:+,.2f}")