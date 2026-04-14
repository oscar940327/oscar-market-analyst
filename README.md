# Oscar Market Analyst

> A personal trading signal system combining technical analysis, LLM sentiment scoring, and regime-aware risk control.

![Python](https://img.shields.io/badge/python-3.11+-blue) ![Status](https://img.shields.io/badge/status-active-brightgreen)

[中文版 README](./README_zh.md)

---

## Overview

An end-to-end trading signal system for US equities that ingests price data, extracts sentiment from financial news using both LLM (DeepSeek V3) and FinBERT, runs multiple backtesting strategies, and generates daily HTML reports delivered via email.

The system was built to rigorously test whether **LLM-based sentiment signals improve a technical-analysis baseline**, and whether **regime-aware position sizing** reduces drawdown effectively. Both hypotheses were validated through a **4-year cross-bear-market backtest** on 14 large-cap US stocks.

**Key technical choices:**
- **Hybrid sentiment engine**: FinBERT for deterministic historical backfill, LLM for daily reports with human-readable reasoning
- **Three comparison strategies**: Pure technical baseline (4a), sentiment-filtered (4b), regime-aware sizer (4c)
- **Cross-bear validation**: Tested across 2022 bear market (SPY -25%) to avoid survivorship bias in bull-only data

---

## Key Findings


### 1. LLM sentiment filtering hurts more than it helps

A 4-year backtest across 14 stocks showed that adding LLM sentiment as an entry filter **reduced average returns by 37.65%** compared to the pure technical baseline. The "sentiment threshold" approach was abandoned in favor of "emergency-only" sentiment usage.

| Strategy | Avg Return (4y) | Beats Baseline |
|---|---|---|
| 4a Baseline (pure technical) | **+114.48%** | — |
| 4b + Sentiment filter | +76.83% | 4 / 14 |
| 4c + Regime sizer | +53.07% | 2 / 14 |

### 2. Regime sizing reduces drawdown but sacrifices returns

The market-regime-based position sizer (80% bull / 50% neutral / 20% bear) **reduced average max drawdown by 10.74 percentage points**, but at the cost of 61% lower cumulative returns. The regime system is slow to scale back up during bear-to-bull transitions, missing rebound rallies.

| Strategy | Max Drawdown | Avg Return |
|---|---|---|
| 4a Baseline | -34.26% | +114.48% |
| 4c + Regime sizer | **-23.53%** | +53.07% |

### 3. LLM sentiment scoring is non-deterministic

This finding was accidental. While debugging a different issue, I re-ran the exact same backfill twice — same model, same `temperature=0.1`, same news data, same prompts — and got materially different average backtest returns across the two runs, with individual ticker results varying substantially. The discrepancy was large enough that it could plausibly explain any "improvement" I had previously attributed to sentiment filtering.

The implication was uncomfortable: if identical runs produce different backtest results, then any "improvement" from LLM sentiment over baseline might be noise rather than signal. This invalidated several earlier experiments and forced a redesign.

The resolution was a **hybrid engine**: FinBERT (deterministic, free, 100% reproducible) is used for the 4-year historical backfill where reasoning text is irrelevant, while LLM is retained for daily reports where human-readable reasoning helps the end user interpret signals.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Data Sources                         │
│  yfinance · Polygon News · Tavily · SPY/VIX (regime)     │
└────────────────────┬─────────────────────────────────────┘
                     │
         ┌───────────▼────────────┐
         │    perception/         │  ETL layer
         │  - price_fetcher       │  Fetches OHLCV + news
         │  - news_fetcher        │
         │  - finbert_scorer      │  Historical (deterministic)
         │  - llm_scorer          │  Daily (reasoning-rich)
         │  - market_regime       │  Bull/Neutral/Bear
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │     pipeline/          │  Storage & orchestration
         │  - db.py (SQLite)      │
         │  - etl.py              │  Daily ETL
         │  - backfill_*.py       │  One-time historical backfills
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │      engine/           │  Backtesting
         │  - strategies/         │  4a, 4b, 4c strategies
         │  - feeds/              │  Custom Backtrader data feed
         │  - runner.py           │  Backtrader orchestrator
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │     analyzer/          │  Decision support
         │  - composite_scorer    │  6-dimension scoring (0-100)
         │  - price_levels        │  Entry/stop/target prices
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │     pipeline/          │  Output layer
         │  - signal_scanner.py   │  Today's signals
         │  - report_builder.py   │  HTML report
         │  - email_sender.py     │  Gmail SMTP
         └────────────────────────┘
                     │
                     ▼
              Daily Email Report
```

---

## Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Language | Python 3.11+ | Data science ecosystem |
| Data storage | SQLite | Zero-config, adequate for single-user system |
| Backtesting | Backtrader | Mature event-driven framework with custom data feed support |
| LLM provider | OpenRouter + DeepSeek V3 | Cost-effective, reasoning-capable |
| Sentiment backfill | ProsusAI/FinBERT (HuggingFace) | Deterministic, finance-tuned, no API cost |
| News source | Polygon.io | 2+ years historical coverage for US equities |
| Daily news | Tavily API | Recent news search with good signal extraction |
| Price data | yfinance | Free, reliable OHLCV |
| Market regime | SPY + VIX | Standard broad-market regime proxies |
| Reporting | HTML + Gmail SMTP | Zero infrastructure cost |

---

## Experimental Results

### Cross-Bear-Market Comparison (2022-01 to 2026-04, 14 stocks)

| Ticker | 4a Baseline | 4b +Sent | 4c +Regime | Buy & Hold |
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
| **Average** | **+114.48%** | +76.83% | +53.07% | +371.44% |

### Interpretation

- **TSLA case study**: Over the 4-year window, buy-and-hold produced **-12.75%** while the technical baseline produced **+72.65%** — demonstrating that the system adds value in bearish conditions.
- **4c regime sizer trade-off**: While it reduces average max drawdown from -34.26% to -23.53% (-10.74pp improvement), it underperforms on returns because it scales down position size during the bear-to-bull transition, missing rebound rallies.
- **4a baseline selection**: Based on 14-stock cross-bear results, the production system uses 4a baseline with sentiment-only-for-emergency-exit. This matches the findings of Liu et al. (2025) in [FINSABER](https://arxiv.org/abs/2505.07078), which noted that LLM-based strategies deteriorate under robust long-term testing.

---

## Installation & Usage

### Requirements

- Python 3.11+
- ~1 GB disk space (for FinBERT model + historical data)
- API keys: Polygon, Tavily, OpenRouter, Gmail (for email sending)

### Setup

```bash
git clone https://github.com/oscar940327/oscar-market-analyst.git
cd oscar-market-analyst
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Copy the example env and fill in your API keys
cp config/.env.example config/.env
# Edit config/.env with POLYGON_API_KEY, TAVILY_API_KEY, OPENROUTER_API_KEY, GMAIL_*
```

### Configure your watchlist

Edit `config/settings.yaml`:

```yaml
watchlist:
  - TSLA
  - NVDA
  - AAPL
  # ... up to 15 tickers
```

### Daily workflow

```bash
# Run daily ETL + scan + HTML report + email
python pipeline/daily_report.py

# Preview only (no email)
python pipeline/daily_report.py --preview
```

### Run backtests

```bash
# Three-way strategy comparison across the watchlist
python tests/test_phase4c_comparison.py
```

### Historical backfill (one-time setup)

```bash
# Backfill 4 years of price data
python pipeline/backfill_prices.py

# Backfill sentiment using FinBERT (free, ~30 min)
python pipeline/backfill_sentiment.py --engine finbert --from 2022-01-01 --to 2025-03-31

# Backfill market regime
python pipeline/backfill_regime.py
```

---

## Project Structure

```
oscar-market-analyst/
├── analyzer/              # Composite scoring & price levels
│   ├── composite_scorer.py    # 6-dimension technical scoring (0-100)
│   └── price_levels.py        # Entry / stop / target calculation
├── config/
│   ├── .env                   # API keys (gitignored)
│   └── settings.yaml          # Watchlist & thresholds
├── data/db/market.db          # SQLite database
├── engine/                # Backtesting engine
│   ├── feeds/
│   │   └── sentiment_feed.py  # Custom Backtrader data feed
│   ├── strategies/
│   │   ├── breakout.py            # 4a baseline (production)
│   │   ├── breakout_sentiment.py  # 4b experimental
│   │   └── breakout_v2.py         # 4c experimental
│   └── runner.py
├── perception/            # Data ingestion & scoring
│   ├── price_fetcher.py       # yfinance
│   ├── news_fetcher.py        # Tavily (daily)
│   ├── historical_news_fetcher.py  # Polygon (backfill)
│   ├── llm_scorer.py          # DeepSeek V3 via OpenRouter
│   ├── finbert_scorer.py      # HuggingFace FinBERT
│   └── market_regime.py       # SPY + VIX regime classification
├── pipeline/              # Orchestration & output
│   ├── db.py                  # SQLite interface
│   ├── etl.py                 # Daily ETL
│   ├── backfill_prices.py
│   ├── backfill_sentiment.py
│   ├── backfill_regime.py
│   ├── signal_scanner.py      # Today's signal detection
│   ├── report_builder.py      # HTML report generation
│   ├── email_sender.py        # Gmail SMTP
│   └── daily_report.py        # Main entry point
├── tests/
│   └── test_phase4c_comparison.py  # Three-way backtest
├── docs/
│   ├── experimental_results.md   # Full experimental report
│   └── decision_log.md           # Engineering decisions with rationale
└── requirements.txt
```

---

## Design Decisions

1. **Hybrid sentiment engine (FinBERT + LLM)** — FinBERT was chosen for historical backfill after discovering LLM non-determinism (3.61% result variance between identical runs). LLM is retained for daily reports to preserve human-readable reasoning.

2. **Cross-bear-market testing** — Bull-only backtesting was rejected because the FINSABER paper (Liu et al., 2025) demonstrated that LLM strategies deteriorate under robust testing. 2022 data was backfilled specifically to include a bear market regime.

3. **Multi-dimensional news search rolled back** — An earlier version of the news fetcher split searches across 5 structured dimensions (earnings / analyst opinion / risk events / industry / latest) and used round-robin selection to feed the LLM. The intuition was that structured inputs would yield better sentiment signals than a single generic query. The intuition was wrong. A direct comparison showed the multi-dimensional version produced **-3.46% lower average returns** than the single-query version on the same watchlist. After some analysis, the likely cause is that round-robin selection dilutes extreme signals — a day with one earnings beat and four neutral stories gets averaged into a weaker signal than a single query would capture. The simpler approach was restored and the multi-dimensional branch was abandoned.

4. **Regime sizer kept as experimental, not production** — Despite reducing drawdown by 10.74 percentage points, 4c underperforms on cumulative returns in 12 of 14 stocks. The production system uses 4a baseline with sentiment-emergency-exit only.

5. **SQLite for storage** — Chosen over PostgreSQL because this is a single-user system with modest data volume (~30k rows). Zero operational overhead; all data is in one file.

---

## Future Work

**Walk-forward validation** is the most important outstanding item. The current 4-year backtest uses the entire window as a single test period. A proper walk-forward protocol would split the data into a training window (e.g., 2022-2024) for strategy selection and parameter tuning, then evaluate on a held-out window (2025-2026) to measure whether the chosen configuration generalizes out-of-sample.

This matters because the current production choice (4a baseline) was made after observing results on the full window — which introduces a mild form of lookahead. A walk-forward test would either validate this choice or surface that some other configuration performs better under stricter methodology. The FINSABER paper (Liu et al., 2025) demonstrates that many LLM-based strategies collapse under this kind of stricter testing, so applying the same protocol here would be a natural next step.

---

## References

- Liu, S., et al. (2025). *FINSABER: Financial Strategy Adaptation Benchmark Evaluating Robustness*. arXiv:2505.07078.
- Araci, D. (2019). *FinBERT: Financial Sentiment Analysis with Pre-trained Language Models*. arXiv:1908.10063.

---

## Author

[@<github-oscar940327>](https://github.com/oscar940327)

---

## License

MIT License — see [LICENSE](./LICENSE) for details.