# Oscar Market Analyst

> 事件驅動的市場雷達：掃描可能影響市場的新聞，對應受影響股票，確認技術面是否真的反應，最後只寄出值得研究的 Email alert。

[English README](./README.md)

---

## 專案概述

Oscar Market Analyst 正在從「股票為中心的每日報告 / 回測系統」重構成 **Event-driven Market Radar：事件驅動市場雷達**。

目前正式方向不是自動交易，也不是 AI 自動選股。這套系統的目標是：

- 掃描免費市場新聞來源，
- 用 LLM 與 deterministic keyword fallback 判斷重要市場事件，
- 把事件對應到預先定義好的市場主題與相關股票，
- 檢查相關股票的技術面是否真的開始反應，
- 只有有值得研究的 alert 時才寄 email，
- 將每個 event / alert 記錄到 SQLite，
- 追蹤 alert 後 1 / 3 / 5 / 20 個交易日的績效。

舊版 daily report / backtest 系統仍保留為 legacy research。它的價值在於技術分析邏輯、歷史實驗紀錄，以及證明「單純把 LLM sentiment 當進場過濾」在嚴格測試下沒有改善策略。

---

## 目前狀態

Event Radar MVP 已經完成並自動化。

已完成：

- RSS 新聞掃描器。
- Keyword theme matching。
- OpenRouter LLM event classifier，固定 JSON 輸出。
- `theme_map.yaml` deterministic theme-to-ticker 對照表。
- SQLite tables：market events、radar alerts、alert performance、trend states。
- 技術確認：20/55 日突破、MA20、成交量倍數、相對 SPY / QQQ 強弱。
- Event Alert email 格式。
- Trend state 管理：Active / Cooling / Closed。
- Trend Alert preview 與手動寄送。
- Alert performance tracking 與 summary command。
- GitHub Actions 自動化。
- Event Radar 核心單元測試。

目前自動化流程：

- GitHub Actions 週一到週五台灣時間 20:30 自動執行。
- 更新價格並掃描新聞。
- 有新的 confirmed / partial Event Alert 時才寄 email。
- 更新 Trend state，但 **不自動寄 Trend Alert email**。
- 當交易日數足夠時更新 alert performance。
- 將 radar state 寫回 repo 的 SQLite database。

---

## 什麼情況會寄信

### Event Alert

Event Alert 會在以下條件成立時寄出：

1. 新聞符合某個市場主題，
2. 該主題能對應到相關股票，
3. 相關股票有足夠技術確認，
4. 這個 alert 還沒有寄過。

Email 內容包含：

- 股票代號，
- 主題，
- 優先級：`High Priority` 或 `Watchlist`，
- 技術狀態：`confirmed` 或 `partial`，
- 來源新聞標題與連結，
- 收盤價，
- 相對強弱，
- 成交量倍數，
- alert reason，
- 參考停損 / 止盈 / trailing stop。

### Trend Alert

Trend Alert 目前 **不會自動寄信**。系統會更新狀態，需要時可以手動 preview。

Trend state 分為：

- `Active`：這個 theme/ticker 仍值得追蹤。
- `Cooling`：多個轉弱訊號同時出現。
- `Closed`：出現更強的趨勢結束條件。

Cooling 目前需要多個訊號，例如：

- 跌破 MA20，
- 最近 20 天跑輸 SPY / QQQ，
- 從高點回撤，
- 多天沒有新的相關 alert。

預覽 Trend Alert，不寄信：

```bash
python -m event_radar.cli --send-trend-alerts --dry-run
```

手動寄出 Trend Alert：

```bash
python -m event_radar.cli --send-trend-alerts
```

---

## 每日使用方式

本機跑完整 daily radar，但不寄信：

```bash
python -m event_radar.cli --run-daily --max-events 30
```

本機跑 daily radar，若有 Event Alert 則寄信：

```bash
python -m event_radar.cli --run-daily --max-events 30 --send-email-alerts
```

更新 Trend state，不寄 Trend Alert：

```bash
python -m event_radar.cli --update-trends
```

更新 alert performance：

```bash
python -m event_radar.cli --update-performance
```

依 theme 統計 performance：

```bash
python -m event_radar.cli --performance-summary --summary-horizon 5 --summary-group-by theme
```

---

## GitHub Actions

Event Radar workflow：

```text
.github/workflows/event_radar.yml
```

需要設定的 GitHub Actions secrets：

```text
OPENROUTER_API_KEY
GMAIL_SENDER
GMAIL_RECEIVER
GMAIL_APP_PASSWORD
```

手動測試 workflow：

1. 到 GitHub Actions。
2. 選 `Event radar`。
3. 點 `Run workflow`。
4. 用 `send_email=false` 做不寄信測試。
5. 只有要測試寄信時才用 `send_email=true`。

---

## 安裝

```bash
git clone https://github.com/oscar940327/personal-market-analysis.git
cd personal-market-analysis
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

建立本機環境變數檔：

```bash
cp config/.env.example config/.env
```

填入：

```text
OPENROUTER_API_KEY
GMAIL_SENDER
GMAIL_RECEIVER
GMAIL_APP_PASSWORD
```

---

## 設定

Event Radar 設定：

```text
config/event_radar.yaml
```

主題與股票對照表：

```text
config/theme_map.yaml
```

重要 trend 設定：

```yaml
trend_management:
  cooling_no_news_days: 5
  closed_no_news_days: 20
  cooling_drawdown_pct: 0.08
  closed_drawdown_pct: 0.15
  cooling_min_signals: 2
  closed_min_signals: 2
```

如果 Trend state 還是太吵，可以提高 `cooling_min_signals`。如果覺得系統太慢才標記轉弱，可以降低它。

---

## 專案結構

```text
event_radar/
  cli.py                      # Event Radar CLI 入口
  config.py                   # YAML config loading
  email_alert.py              # Event / Trend email rendering 與寄送
  llm_classifier.py           # OpenRouter LLM 分類
  models.py                   # Data models
  performance.py              # Alert performance tracking 與 summary
  price_update.py             # yfinance 價格更新
  repository.py               # SQLite persistence
  rss_scanner.py              # RSS ingestion
  service.py                  # Event classification 與 alert draft 建立
  technical_confirmation.py   # Breakout / MA / volume / RS 技術確認
  theme_mapper.py             # Keyword theme matching
  trends.py                   # Active / Cooling / Closed trend states

config/
  event_radar.yaml            # Radar 門檻與 RSS sources
  theme_map.yaml              # 市場主題與相關股票
  .env.example                # 本機環境變數範本

pipeline/
  db.py                       # 共用 SQLite price database helper
  email_sender.py             # Gmail SMTP helper

tests/
  test_event_radar.py         # Event Radar 單元測試
```

舊版 backtest 與 daily report 模組仍在：

```text
analyzer/
engine/
perception/
pipeline/
```

這些模組目前保留作為研究與參考。長期方向是讓 `main` 聚焦 Event Radar，舊版 backtest/report code 則保留在 `legacy-backtest` branch。

---

## 測試

執行 Event Radar 測試：

```bash
python -m unittest tests.test_event_radar
```

目前測試涵蓋：

- keyword theme matching，
- alert draft generation，
- email deduplication，
- event / alert persistence deduplication，
- technical confirmation，
- trend alert deduplication，
- performance summary，
- 更嚴格的 multi-signal Trend Cooling 規則。

---

## 舊版研究摘要

在 Event Radar pivot 之前，這個專案主要在測試：LLM sentiment 是否能改善技術突破策略。

核心發現：

- 純技術突破基準在 4 年跨熊市測試中勝過 sentiment-filtered variants。
- Regime sizing 可以降低回撤，但犧牲太多報酬。
- LLM sentiment scoring 不夠 deterministic，不適合作為歷史回測核心訊號。
- FinBERT 適合 deterministic historical sentiment backfill；LLM 更適合用來理解當前事件並產生可讀 reasoning。

最後的設計決策：

```text
用 LLM 理解市場事件，不讓 LLM 直接決定交易。
用技術確認檢查相關股票是否真的開始反應。
```

---

## 剩餘工作

專案目前可用，但還沒有完全完成。

近期：

- 觀察 Event Alert 品質數個交易日。
- 檢查 false positives 與 missed themes。
- 調整 `theme_map.yaml` 與 alert priority thresholds。
- 決定 Trend Alert email 長期維持手動，或之後改成 weekly digest / 自動寄送。
- 確認 `legacy-backtest` 已推到 GitHub remote branch。

中期：

- 從累積的 alert outcomes 建立 performance review report。
- 依 post-alert return 與 benchmark-relative return 排名 themes。
- 分析哪些 technical conditions 最有用。
- 加入 optional weekly summary email。
- 如果 RSS 品質不足，增加更穩定的新聞來源。

長期：

- 清理 `main`，讓它更明確聚焦 Event Radar。
- 將舊 daily report / backtest code 保留在 `legacy-backtest`。
- 增加 Archived trend state。
- 建立更完整的 event taxonomy 與 duplicate-event clustering。
- 驗證 Event Radar alerts 是否長期能產生有用的研究線索。

---

## 免責聲明

這是個人市場研究與 alert 工具，不會自動交易，也不是投資建議。
