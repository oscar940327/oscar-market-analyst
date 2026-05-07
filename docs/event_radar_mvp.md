# Event Radar MVP

This is the first incremental slice of the new event-driven market radar.
It runs separately from the legacy daily report and backtest pipeline.

## What This Slice Does

- Loads market news events from RSS feeds or a manual sample input.
- Maps event text to predefined market themes by keyword.
- Expands matched themes into candidate tickers.
- Stores matched events in `market_events`.
- Stores ticker-level alert drafts in `radar_alerts`.
- Confirms pending alert drafts with local price data.
- Updates radar ticker prices from yfinance.
- Optionally classifies events with OpenRouter before keyword fallback.
- Sends confirmed or partial alerts by email.
- Tracks alert performance after 1/3/5/20 trading days.
- Maintains basic Active/Cooling/Closed trend states.

## What It Does Not Do Yet

- It does not automatically trade.
- It does not make final buy/sell decisions.
- It does not yet send separate Trend Cooling emails.

Those are intended as follow-up slices.

## Run A Dry-Run Sample

```bash
python -m event_radar.cli --sample-title "AI server demand lifts HBM and DRAM memory pricing" --dry-run
```

## Run A Dry-Run Sample With OpenRouter

```bash
python -m event_radar.cli --sample-title "AI server demand lifts HBM and DRAM memory pricing" --use-llm --dry-run
```

## Persist A Sample

```bash
python -m event_radar.cli --sample-title "AI server demand lifts HBM and DRAM memory pricing"
```

## Run RSS Scan

```bash
python -m event_radar.cli
```

Use OpenRouter classification before keyword fallback:

```bash
python -m event_radar.cli --use-llm
```

## Run Daily Radar

Daily radar runs the normal operating sequence:

- Update radar ticker prices.
- Fetch RSS events.
- Classify events with OpenRouter.
- Persist matched events and alert drafts.
- Confirm technicals.
- Show an email preview.

Preview mode, without database writes:

```bash
python -m event_radar.cli --run-daily --max-events 10 --dry-run
```

Normal daily run, with email preview only:

```bash
python -m event_radar.cli --run-daily --max-events 30
```

Normal daily run and send email:

```bash
python -m event_radar.cli --run-daily --max-events 30 --send-email-alerts
```

Mark current unsent alerts as test-skipped:

```bash
python -m event_radar.cli --skip-unsent-alerts
```

## Update Radar Prices

This updates all tickers referenced by `config/theme_map.yaml`, plus `SPY` and `QQQ`.

```bash
python -m event_radar.cli --update-prices
```

## Confirm Pending Alerts

This step uses local SQLite price data only. It does not require an API key.

```bash
python -m event_radar.cli --confirm-technicals --dry-run
python -m event_radar.cli --confirm-technicals
```

Technical confirmation checks:

- 20-day breakout.
- 55-day breakout.
- Above MA20.
- Volume ratio against 20-day average volume.
- 20-day relative strength versus `SPY` and `QQQ` when benchmark data exists.
- Reference stop loss, first/second take-profit, and trailing stop levels.

## Send Email Alerts

```bash
python -m event_radar.cli --send-email-alerts --dry-run
python -m event_radar.cli --send-email-alerts
```

By default this sends unsent `High Priority` and `Watchlist` alerts whose technical
status is `confirmed` or `partial`.

## Track Alert Performance

```bash
python -m event_radar.cli --update-performance --dry-run
python -m event_radar.cli --update-performance
```

Performance horizons:

- 1 trading day.
- 3 trading days.
- 5 trading days.
- 20 trading days.

## Update Trend States

```bash
python -m event_radar.cli --update-trends --dry-run
python -m event_radar.cli --update-trends
```

Trend states:

- `Active`
- `Cooling`
- `Closed`

## Config Files

- `config/event_radar.yaml`: RSS feeds, scan limits, alert priority thresholds.
- `config/event_radar.yaml`: technical confirmation thresholds.
- `config/event_radar.yaml`: LLM, price update, and trend management thresholds.
- `config/theme_map.yaml`: deterministic theme-to-ticker mapping.

## SQLite Tables

- `market_events`: event-level record.
- `radar_alerts`: ticker-level alerts with technical confirmation fields.
- `alert_performance`: post-alert returns, benchmark-relative returns, and drawdown.
- `trend_states`: theme/ticker trend state tracking.
