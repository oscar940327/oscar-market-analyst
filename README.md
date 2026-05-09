# Oscar Market Analyst

> Event-driven market radar for detecting market-moving news, mapping events to affected tickers, confirming technical reaction, and sending focused email alerts.

[中文版 README](./README_zh.md)

---

## Overview

Oscar Market Analyst is being refactored from a stock-centered daily report and backtest project into an **Event-driven Market Radar**.

The current production direction is not automatic trading and not AI stock picking. The system is designed to:

- scan free market news sources,
- classify important market events with an LLM and deterministic keyword fallback,
- map events to predefined market themes and related tickers,
- check whether those tickers are technically reacting,
- send email alerts only when there is something worth reviewing,
- record every event and alert in SQLite,
- track alert performance after 1 / 3 / 5 / 20 trading days.

The old daily report and backtesting system is preserved as legacy research. Its main value is the technical-analysis logic, historical experiments, and evidence that naive LLM sentiment filters did not improve the trading strategy under robust testing.

---

## Current Status

The Event Radar MVP is implemented and automated.

Completed:

- RSS news scanner.
- Keyword theme matching.
- OpenRouter LLM event classifier with fixed JSON output.
- Deterministic `theme_map.yaml` theme-to-ticker mapping.
- SQLite tables for market events, radar alerts, alert performance, and trend states.
- Technical confirmation using 20/55-day breakout, MA20, volume ratio, and relative strength versus SPY / QQQ.
- Fundamental check using yfinance valuation and quality metrics.
- Fundamental rating: `A / B / C / D / E / Unknown`.
- Fundamental red-flag overlay that can cap alert priority.
- Event Alert email format.
- Trend state management: Active / Cooling / Closed / Archived.
- Trend Alert preview and optional sending.
- Performance tracking and summary commands.
- GitHub Actions automation.
- Unit tests for core Event Radar behavior.

Current automation:

- Runs on GitHub Actions Monday-Friday at Taiwan 20:30.
- Updates prices and scans news.
- Sends **Event Alert** emails when new confirmed or partial alerts exist.
- Updates Trend state, but does **not** automatically send Trend Alert emails.
- Updates alert performance when enough trading days have passed.
- Commits updated radar state back to the repository database.
- Leaves the legacy daily report workflow disabled on `main` unless it is explicitly run manually.

---

## What Gets Emailed

### Event Alert

An Event Alert is sent when:

1. a news item matches a market theme,
2. the theme maps to related tickers,
3. a related ticker has enough technical confirmation,
4. the alert has not already been sent.

The email contains:

- ticker,
- theme,
- priority: `High Priority` or `Watchlist`,
- technical status: `confirmed` or `partial`,
- source news title and link,
- close price,
- relative strength,
- volume ratio,
- alert reason,
- reference stop-loss / take-profit / trailing-stop levels,
- fundamental rating and summary when available.

### Trend Alert

Trend Alerts are currently **not sent automatically**. They are updated and can be previewed manually.

Trend state can become:

- `Active`: theme/ticker is still worth tracking.
- `Cooling`: multiple weakening signals are present.
- `Closed`: stronger end-of-trend conditions are present.
- `Archived`: no related alert has appeared for a longer period.

Cooling currently requires multiple signals, such as:

- below MA20,
- underperforming SPY / QQQ over 20 days,
- drawdown from high,
- no related alerts for several days.

Preview Trend Alerts:

```bash
python -m event_radar.cli --send-trend-alerts --dry-run
```

Send Trend Alerts manually:

```bash
python -m event_radar.cli --send-trend-alerts
```

---

## Daily Usage

Run the full daily radar locally without sending email:

```bash
python -m event_radar.cli --run-daily --max-events 30
```

Run and send Event Alert emails if any exist:

```bash
python -m event_radar.cli --run-daily --max-events 30 --send-email-alerts
```

Update trend states without sending Trend Alert emails:

```bash
python -m event_radar.cli --update-trends
```

Update alert performance:

```bash
python -m event_radar.cli --update-performance
```

Summarize performance by theme:

```bash
python -m event_radar.cli --performance-summary --summary-horizon 5 --summary-group-by theme
```

---

## GitHub Actions

The Event Radar workflow is defined in:

```text
.github/workflows/event_radar.yml
```

Required GitHub Actions secrets:

```text
OPENROUTER_API_KEY
GMAIL_SENDER
GMAIL_RECEIVER
GMAIL_APP_PASSWORD
```

Manual workflow testing:

1. Go to GitHub Actions.
2. Select `Event radar`.
3. Click `Run workflow`.
4. Use `send_email=false` for a dry operational check.
5. Use `send_email=true` only when email sending should be enabled.

---

## Installation

```bash
git clone https://github.com/oscar940327/personal-market-analysis.git
cd personal-market-analysis
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create local environment file:

```bash
cp config/.env.example config/.env
```

Fill in:

```text
OPENROUTER_API_KEY
GMAIL_SENDER
GMAIL_RECEIVER
GMAIL_APP_PASSWORD
```

---

## Configuration

Event Radar config:

```text
config/event_radar.yaml
```

Theme-to-ticker map:

```text
config/theme_map.yaml
```

Important trend settings:

```yaml
trend_management:
  cooling_no_news_days: 5
  closed_no_news_days: 20
  cooling_drawdown_pct: 0.08
  closed_drawdown_pct: 0.15
  cooling_min_signals: 2
  closed_min_signals: 2
```

Increase `cooling_min_signals` if Trend state is still too noisy. Decrease it if the system is too slow to flag weakening themes.

---

## Project Structure

```text
event_radar/
  cli.py                      # Main Event Radar CLI
  config.py                   # YAML config loading
  email_alert.py              # Event and Trend email rendering/sending
  fundamental_check.py        # yfinance valuation / quality rating
  llm_classifier.py           # OpenRouter LLM classification
  models.py                   # Data models
  performance.py              # Alert performance tracking and summaries
  price_update.py             # yfinance price updates
  repository.py               # SQLite persistence
  rss_scanner.py              # RSS ingestion
  service.py                  # Event classification and alert draft creation
  technical_confirmation.py   # Breakout / MA / volume / RS confirmation
  theme_mapper.py             # Keyword theme matching
  trends.py                   # Active / Cooling / Closed / Archived trend states

config/
  event_radar.yaml            # Radar thresholds and RSS sources
  theme_map.yaml              # Market themes and related tickers
  .env.example                # Local environment template

pipeline/
  db.py                       # Shared SQLite price database helpers
  email_sender.py             # Gmail SMTP helper

tests/
  test_event_radar.py         # Event Radar unit tests
```

Legacy backtest and daily report modules still exist in:

```text
analyzer/
engine/
perception/
pipeline/
```

Those are retained for research and reference. The intended long-term direction is for `main` to focus on Event Radar, while legacy backtest/report code remains available on the `legacy-backtest` branch.

---

## Tests

Run Event Radar tests:

```bash
python -m unittest tests.test_event_radar
```

The tests cover:

- keyword theme matching,
- alert draft generation,
- email deduplication,
- event and alert persistence deduplication,
- technical confirmation,
- trend alert deduplication,
- performance summary,
- stricter multi-signal Trend Cooling rules.

---

## Legacy Research Summary

Before the Event Radar pivot, this project tested whether LLM sentiment improved a technical breakout strategy.

Key findings:

- A pure technical breakout baseline outperformed sentiment-filtered variants in the 4-year cross-bear-market test.
- Regime sizing reduced drawdown but sacrificed too much return.
- LLM sentiment scoring was not deterministic enough for historical backtesting.
- FinBERT remained useful for deterministic historical sentiment backfill, while LLMs are better suited for current event interpretation and human-readable reasoning.

The resulting design decision:

```text
Use LLMs to understand market events, not to directly decide trades.
Use technical confirmation to verify whether related tickers are actually reacting.
```

---

## Remaining Work

The project is usable, but not fully finished.

Near-term:

- Observe Event Alert quality for several trading days.
- Review false positives and missed themes.
- Tune `theme_map.yaml` and alert priority thresholds.
- Decide whether Trend Alert emails should remain manual or become automated later.
- Observe whether fundamental red-flag capping improves alert quality.

Medium-term:

- Build performance review reports from accumulated alert outcomes.
- Rank themes by post-alert return and benchmark-relative return.
- Rank technical conditions by usefulness.
- Rank fundamental ratings by post-alert usefulness.
- Add optional weekly summary email.
- Add more reliable news sources if RSS quality is insufficient.

Long-term:

- Remove or relocate legacy daily report/backtest code from `main` if you want a stricter Event Radar-only branch.
- Keep old daily report/backtest code in `legacy-backtest`.
- Add richer event taxonomy and better duplicate-event clustering.
- Validate whether Event Radar alerts produce useful research leads over time.

---

## Disclaimer

This project is a personal market research and alerting tool. It does not make automatic trading decisions and is not financial advice.
