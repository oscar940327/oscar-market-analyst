# Oscar Market Analyst

> 結合技術分析、LLM 情緒評分與大盤狀態風控的個人交易訊號系統。

![Python](https://img.shields.io/badge/python-3.11+-blue) ![Status](https://img.shields.io/badge/status-active-brightgreen)

[English README](./README.md)

---

## 專案概述

這是一套針對美股的端對端交易訊號系統。流程涵蓋價格資料擷取、金融新聞情緒評分（同時使用 LLM DeepSeek V3 與 FinBERT 兩種引擎）、多策略回測、以及每日 HTML 報告的自動產生與 email 推送。

專案的核心目標是嚴謹驗證兩個假設：**LLM 情緒訊號是否能改善純技術面基準策略**、以及 **大盤狀態感知的動態倉位是否能有效降低回撤**。兩個假設都透過 **橫跨 4 年、包含 2022 熊市的 14 檔美股回測** 來驗證。

**關鍵技術選擇：**
- **混搭情緒引擎**：FinBERT 負責歷史回填（決定性輸出），LLM 負責每日報告（保留可讀的推理文字）
- **三種策略對照**：純技術面基準（4a）、情緒過濾版（4b）、大盤狀態倉位版（4c）
- **跨熊市驗證**：測試範圍涵蓋 2022 熊市（SPY 下跌 25%），避免只用牛市資料產生的倖存者偏誤

---

## 核心發現

### 1. LLM 情緒過濾弊大於利

4 年、14 檔美股的回測顯示，把 LLM 情緒當作進場過濾條件，平均報酬比純技術面基準 **低 37.65%**。原本的「sentiment threshold」設計被廢除，改成只在極端值觸發的「緊急平倉」用途。

| 策略 | 平均 4 年報酬 | 勝過基準 |
|---|---|---|
| 4a 基準（純技術面） | **+114.48%** | — |
| 4b + 情緒過濾 | +76.83% | 4 / 14 |
| 4c + 大盤狀態倉位 | +53.07% | 2 / 14 |

### 2. 大盤狀態倉位降低回撤，但犧牲了報酬

基於大盤狀態的動態倉位（牛市 80% / 中性 50% / 熊市 20%）確實讓平均最大回撤 **降低了 10.74 個百分點**，但同時也讓累積報酬減少 61%。Regime 系統在「熊市轉牛市」的轉折期反應太慢，錯過了反彈的主要段落。

| 策略 | 最大回撤 | 平均報酬 |
|---|---|---|
| 4a 基準 | -34.26% | +114.48% |
| 4c + 大盤狀態倉位 | **-23.53%** | +53.07% |

### 3. LLM 情緒評分並非決定性輸出

這個發現是意外撞到的。當時我在 debug 另一個問題，不小心把同一份歷史回填跑了兩次——同樣的模型、同樣的 `temperature=0.1`、同樣的新聞資料、同樣的 prompt——結果兩次的平均回測報酬出現了明顯差距，個別股票的差距更大。差距大到足以推翻我之前歸因於「情緒過濾有效」的結論。

這個結果讓我不得不重新設計：既然「相同輸入 → 不同輸出」，那之前用 LLM 情緒跑出來的所有對照實驗都需要重跑。最後的解法是**混搭引擎**：FinBERT（決定性、免費、100% 可重現）負責 4 年歷史回填，LLM 則保留在每日報告，因為每日報告需要人類可讀的推理文字來幫助使用者理解訊號。

---

## 系統架構

```
┌──────────────────────────────────────────────────────────┐
│                      資料來源                            │
│  yfinance · Polygon News · Tavily · SPY/VIX（regime）    │
└────────────────────┬─────────────────────────────────────┘
                     │
         ┌───────────▼────────────┐
         │    perception/         │  資料擷取層
         │  - price_fetcher       │  抓 OHLCV 和新聞
         │  - news_fetcher        │
         │  - finbert_scorer      │  歷史回填（決定性）
         │  - llm_scorer          │  每日報告（有推理文字）
         │  - market_regime       │  Bull/Neutral/Bear
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │     pipeline/          │  儲存與編排
         │  - db.py (SQLite)      │
         │  - etl.py              │  每日 ETL
         │  - backfill_*.py       │  一次性歷史回填
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │      engine/           │  回測引擎
         │  - strategies/         │  4a、4b、4c 三個策略
         │  - feeds/              │  Backtrader 自訂 data feed
         │  - runner.py           │  Backtrader 主流程
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │     analyzer/          │  決策輔助
         │  - composite_scorer    │  6 維度綜合評分（0-100）
         │  - price_levels        │  理想買入 / 停損 / 目標價
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │     pipeline/          │  輸出層
         │  - signal_scanner.py   │  今日訊號掃描
         │  - report_builder.py   │  HTML 報告
         │  - email_sender.py     │  Gmail SMTP
         └────────────────────────┘
                     │
                     ▼
                每日 Email 報告
```

---

## 技術棧

| 層級 | 技術 | 選用原因 |
|---|---|---|
| 語言 | Python 3.11+ | 資料科學生態成熟 |
| 資料儲存 | SQLite | 零設定、足夠單人系統使用 |
| 回測框架 | Backtrader | 成熟的事件驅動框架，支援自訂 data feed |
| LLM 提供者 | OpenRouter + DeepSeek V3 | 成本低廉、具備推理能力 |
| 情緒回填引擎 | ProsusAI/FinBERT（HuggingFace） | 決定性輸出、金融領域 fine-tune、零 API 成本 |
| 歷史新聞來源 | Polygon.io | 美股擁有 2 年以上歷史新聞 |
| 每日新聞來源 | Tavily API | 近期新聞搜尋、訊號擷取效果好 |
| 價格資料 | yfinance | 免費、穩定的 OHLCV |
| 大盤狀態判斷 | SPY + VIX | 業界標準的大盤 regime 代理指標 |
| 報告產出 | HTML + Gmail SMTP | 零基礎設施成本 |

---

## 實驗結果

### 跨熊市對照測試（2022-01 至 2026-04，14 檔美股）

| Ticker | 4a 基準 | 4b +情緒 | 4c +Regime | Buy & Hold |
|---|---:|---:|---:|---:|
| TSLA | +72.65% | +26.98% | +39.56% | -12.75% |
| GOOGL | -8.91% | +23.60% | -1.69% | +118.80% |
| PLTR | +67.57% | +27.70% | +7.37% | +591.10% |
| MU | +67.68% | +98.29% | +42.96% | +339.26% |
| NVDA | +208.15% | +1.96% | -15.12% | +526.24% |
| TSM | +81.87% | +0.54% | -5.57% | +187.73% |
| RKLB | +399.75% | +370.32% | +269.33% | +457.79% |
| SOFI | +20.37% | -5.83% | +4.56% | +3.44% |
| AAPL | +30.51% | +19.64% | +9.22% | +43.11% |
| META | +97.33% | -11.47% | -29.25% | +86.05% |
| MSFT | +22.86% | +14.38% | -12.02% | +10.79% |
| AMD | +27.12% | +52.70% | +59.96% | +63.10% |
| AVGO | +112.14% | +52.33% | +49.50% | +460.14% |
| CRWD | +10.05% | -15.98% | -14.66% | +91.11% |
| **平均** | **+114.48%** | +76.83% | +53.07% | +371.44% |

### 結果解讀

- **TSLA 個案**：4 年下來 Buy & Hold 是 **-12.75%**，而技術面基準策略是 **+72.65%**——這證明系統在熊市環境下真的有價值。
- **4c 大盤狀態倉位的取捨**：最大回撤從 -34.26% 降到 -23.53%（改善 10.74 個百分點），但累積報酬比基準少很多。原因是 regime 系統在「熊市轉牛市」的轉折期仍保持減倉，錯過了反彈的最大段。
- **最終採用 4a 基準**：根據這份跨熊市測試的結果，正式環境使用 4a 基準 + 只在極端值觸發的緊急平倉。這個選擇與 Liu 等人（2025）在 [FINSABER](https://arxiv.org/abs/2505.07078) 論文中的發現一致——該論文指出 LLM 類策略在嚴謹的長期測試下常會失去優勢。

---

## 安裝與使用

### 環境需求

- Python 3.11+
- 約 1 GB 硬碟空間（FinBERT 模型 + 歷史資料）
- API keys：Polygon、Tavily、OpenRouter、Gmail（用來寄信）

### 安裝步驟

```bash
git clone https://github.com/oscar940327/oscar-market-analyst.git
cd oscar-market-analyst
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 複製環境變數範本並填入 API keys
cp config/.env.example config/.env
# 在 config/.env 裡填入 POLYGON_API_KEY、TAVILY_API_KEY、OPENROUTER_API_KEY、GMAIL_*
```

### 設定 watchlist

編輯 `config/settings.yaml`：

```yaml
watchlist:
  - TSLA
  - NVDA
  - AAPL
  # 最多 15 檔
```

### 每日流程

```bash
# 跑完整的每日 ETL + 掃描 + HTML 報告 + 寄信
python pipeline/daily_report.py

# 只預覽，不寄信
python pipeline/daily_report.py --preview
```

### 執行回測

```bash
# 三策略對照回測
python tests/test_phase4c_comparison.py
```

### 歷史資料回填（一次性設定）

```bash
# 回填 4 年的價格資料
python pipeline/backfill_prices.py

# 用 FinBERT 回填情緒（免費、約 30 分鐘）
python pipeline/backfill_sentiment.py --engine finbert --from 2022-01-01 --to 2025-03-31

# 回填大盤 regime
python pipeline/backfill_regime.py
```

---

## 專案結構

```
oscar-market-analyst/
├── analyzer/              # 綜合評分與操作參考價位
│   ├── composite_scorer.py    # 6 維度技術評分（0-100）
│   └── price_levels.py        # 買入 / 停損 / 目標價計算
├── config/
│   ├── .env                   # API keys（gitignored）
│   └── settings.yaml          # Watchlist 與參數
├── data/db/market.db          # SQLite 資料庫
├── engine/                # 回測引擎
│   ├── feeds/
│   │   └── sentiment_feed.py  # Backtrader 自訂 data feed
│   ├── strategies/
│   │   ├── breakout.py            # 4a 基準（正式使用）
│   │   ├── breakout_sentiment.py  # 4b 實驗
│   │   └── breakout_v2.py         # 4c 實驗
│   └── runner.py
├── perception/            # 資料擷取與評分
│   ├── price_fetcher.py       # yfinance
│   ├── news_fetcher.py        # Tavily（每日）
│   ├── historical_news_fetcher.py  # Polygon（歷史回填）
│   ├── llm_scorer.py          # DeepSeek V3 via OpenRouter
│   ├── finbert_scorer.py      # HuggingFace FinBERT
│   └── market_regime.py       # SPY + VIX regime 判斷
├── pipeline/              # 編排與輸出
│   ├── db.py                  # SQLite 介面
│   ├── etl.py                 # 每日 ETL
│   ├── backfill_prices.py
│   ├── backfill_sentiment.py
│   ├── backfill_regime.py
│   ├── signal_scanner.py      # 今日訊號掃描
│   ├── report_builder.py      # HTML 報告產生
│   ├── email_sender.py        # Gmail SMTP
│   └── daily_report.py        # 主要入口
├── tests/
│   └── test_phase4c_comparison.py  # 三策略對照測試
├── docs/
│   ├── experimental_results.md   # 完整實驗報告
│   └── decision_log.md           # 設計決策日誌
└── requirements.txt
```

---

## 設計決策

1. **混搭情緒引擎（FinBERT + LLM）** — 選擇 FinBERT 做歷史回填是在發現 LLM 的非決定性之後才決定的（見 Finding 3）。每日報告仍使用 LLM，因為它能產生人類可讀的推理文字，讓使用者更容易理解訊號。

2. **跨熊市測試** — 捨棄只用牛市資料的測試方式，因為 FINSABER 論文（Liu 等人，2025）指出 LLM 類策略在嚴謹測試下會退化。特別把歷史資料回填到 2022 年，以確保測試範圍涵蓋至少一段熊市。

3. **多維度新聞搜尋被 rollback** — 早期版本的 news_fetcher 把新聞搜尋分成 5 個結構化維度（財報 / 分析師意見 / 風險事件 / 產業 / 最新），用 round-robin 方式分組後送給 LLM。我原本的直覺是「結構化輸入會比通用 query 產生更好的情緒訊號」，這個直覺是錯的。直接對照兩個版本的結果顯示，多維度版本在同樣的 watchlist 上平均報酬 **低了 3.46%**。事後分析後我認為原因是 round-robin 稀釋了極端訊號——一天有 1 篇財報大好消息 + 4 篇中性新聞，經過 round-robin 加權後訊號強度被平均掉了，反而不如單一 query 能抓到極端值。最後回到原本的單一 query 設計。

4. **4c 作為實驗被保留但不採用為正式策略** — 雖然 4c 把平均最大回撤降低了 10.74 個百分點，但它在 14 檔股票中有 12 檔累積報酬輸給基準。正式環境使用 4a 基準 + 只做緊急平倉的 sentiment 用途。

5. **SQLite 作為儲存層** — 選擇 SQLite 而非 PostgreSQL 的原因是這是單人系統、資料量不大（約 3 萬筆）、零維運成本、所有資料都在單一檔案中，方便備份和搬遷。

---

## 未來規劃

**Walk-forward validation** 是目前最重要的待辦事項。現在的 4 年回測是把整段資料當成單一測試期間，但嚴謹的 walk-forward 驗證應該把資料切成訓練期（例如 2022-2024）做策略選擇與參數調整，然後在保留期（2025-2026）評估所選配置是否在樣本外仍然有效。

這件事很重要，因為現在「4a 為正式策略」這個決定是我在看過完整 4 年資料的結果後才做的——這本身有輕微的 lookahead 問題。一個真正的 walk-forward 測試要麼會驗證這個決定是對的，要麼會顯示有另一個配置在更嚴謹的方法學下表現更好。FINSABER 論文（Liu 等人，2025）指出很多 LLM 類策略在這種嚴謹測試下會崩潰，所以對這個系統做同樣的測試是自然的下一步。

---

## 參考文獻

- Liu, S., et al. (2025). *FINSABER: Financial Strategy Adaptation Benchmark Evaluating Robustness*. arXiv:2505.07078.
- Araci, D. (2019). *FinBERT: Financial Sentiment Analysis with Pre-trained Language Models*. arXiv:1908.10063.

---

## 作者

[@&lt;github-oscar940327&gt;](https://github.com/oscar940327)

---

## 授權

MIT License — 詳見 [LICENSE](./LICENSE)。