from __future__ import annotations

import argparse

from event_radar.config import load_event_config, load_theme_map
from event_radar.email_alert import (
    build_alert_subject,
    build_trend_alert_subject,
    dedupe_alerts_for_email,
    send_event_alert_email,
    send_trend_alert_email,
)
from event_radar.models import NewsEvent
from event_radar.performance import (
    summarize_alert_performance,
    update_alert_performance,
)
from event_radar.price_update import update_radar_prices
from event_radar.repository import EventRepository
from event_radar.rss_scanner import fetch_rss_events
from event_radar.service import classify_events, persist_classified_events
from event_radar.technical_confirmation import (
    TechnicalThresholds,
    confirm_pending_alerts,
)
from event_radar.trends import TrendThresholds, update_trend_states


def _sample_event(args: argparse.Namespace) -> NewsEvent | None:
    if not args.sample_title:
        return None
    return NewsEvent(
        title=args.sample_title,
        summary=args.sample_summary or "",
        source="manual",
        published_at=args.sample_date or "",
    )


def _technical_thresholds(event_config: dict) -> TechnicalThresholds:
    technical_config = event_config.get("technical_confirmation", {})
    return TechnicalThresholds(
        breakout_lookback=int(technical_config.get("breakout_lookback", 20)),
        major_breakout_lookback=int(technical_config.get("major_breakout_lookback", 55)),
        volume_lookback=int(technical_config.get("volume_lookback", 20)),
        volume_ratio_min=float(technical_config.get("volume_ratio_min", 1.3)),
        relative_strength_days=int(technical_config.get("relative_strength_days", 20)),
        high_priority_confirmations=int(
            technical_config.get("high_priority_confirmations", 3)
        ),
        watchlist_confirmations=int(technical_config.get("watchlist_confirmations", 1)),
        stop_loss_pct=float(technical_config.get("stop_loss_pct", 0.08)),
        first_take_profit_pct=float(technical_config.get("first_take_profit_pct", 0.10)),
        second_take_profit_pct=float(technical_config.get("second_take_profit_pct", 0.20)),
        trailing_stop_pct=float(technical_config.get("trailing_stop_pct", 0.08)),
    )


def _load_unsent_email_alerts(
    repository: EventRepository,
    limit: int,
    include_info_alerts: bool = False,
    include_unconfirmed_alerts: bool = False,
):
    priorities = {"High Priority", "Watchlist"}
    if include_info_alerts:
        priorities.add("Info")
    return repository.load_unsent_alerts(
        limit=limit,
        priorities=priorities,
        include_unconfirmed=include_unconfirmed_alerts,
    )


def _print_email_preview(alerts) -> list:
    display_alerts = dedupe_alerts_for_email(alerts)
    print(f"Unsent email alerts: {len(alerts)}")
    if len(display_alerts) != len(alerts):
        print(f"Email rows after dedupe: {len(display_alerts)}")
    if display_alerts:
        print(f"Subject: {build_alert_subject(display_alerts)}")
        for alert in display_alerts[:20]:
            print(
                f"- {alert.priority} {alert.ticker} "
                f"({alert.technical_status}) {alert.theme}"
            )
    return display_alerts


def main() -> None:
    parser = argparse.ArgumentParser(description="Event-driven market radar MVP")
    parser.add_argument(
        "--run-daily",
        action="store_true",
        help="Run prices, RSS scan, classification, technical confirmation, and email preview",
    )
    parser.add_argument(
        "--skip-unsent-alerts",
        action="store_true",
        help="Mark current unsent email alerts as test_skip without sending",
    )
    parser.add_argument("--sample-title", help="Classify one manual event title")
    parser.add_argument("--sample-summary", default="", help="Manual event summary")
    parser.add_argument("--sample-date", default="", help="Manual event date")
    parser.add_argument(
        "--confirm-technicals",
        action="store_true",
        help="Confirm pending alert drafts using local price data",
    )
    parser.add_argument(
        "--update-performance",
        action="store_true",
        help="Update 1/3/5/20 trading-day alert performance",
    )
    parser.add_argument(
        "--performance-summary",
        action="store_true",
        help="Summarize alert performance by theme, priority, or technical status",
    )
    parser.add_argument(
        "--summary-horizon",
        type=int,
        default=5,
        help="Performance summary horizon in trading days",
    )
    parser.add_argument(
        "--summary-group-by",
        choices=["theme", "priority", "technical_status"],
        default="theme",
        help="Performance summary grouping",
    )
    parser.add_argument(
        "--summary-min-count",
        type=int,
        default=1,
        help="Minimum samples required for each performance summary row",
    )
    parser.add_argument(
        "--update-trends",
        action="store_true",
        help="Update Active/Cooling/Closed trend states",
    )
    parser.add_argument(
        "--send-email-alerts",
        action="store_true",
        help="Send unsent confirmed or partial alerts by email",
    )
    parser.add_argument(
        "--send-trend-alerts",
        action="store_true",
        help="Send unsent Cooling or Closed trend state alerts by email",
    )
    parser.add_argument(
        "--update-prices",
        action="store_true",
        help="Update local prices for theme-map tickers and SPY/QQQ",
    )
    parser.add_argument(
        "--price-lookback-days",
        type=int,
        default=220,
        help="Initial price lookback for tickers with no local data",
    )
    parser.add_argument(
        "--price-refresh-overlap-days",
        type=int,
        default=10,
        help="Refresh overlap when ticker already has local prices",
    )
    parser.add_argument(
        "--price-max-retries",
        type=int,
        default=2,
        help="Maximum yfinance retries per ticker",
    )
    parser.add_argument(
        "--include-info-alerts",
        action="store_true",
        help="Include Info alerts when sending alert email",
    )
    parser.add_argument(
        "--include-unconfirmed-alerts",
        action="store_true",
        help="Include unconfirmed alerts when sending alert email",
    )
    parser.add_argument("--limit", type=int, default=100, help="Alert confirmation limit")
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use OpenRouter LLM classification before keyword fallback",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Maximum RSS events to scan for this run",
    )
    parser.add_argument(
        "--rss-dry-run",
        action="store_true",
        help="Fetch RSS events and print titles without classifying or saving",
    )
    parser.add_argument(
        "--llm-debug",
        action="store_true",
        help="Print compact LLM classification decisions",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print matches without saving")
    args = parser.parse_args()

    if args.skip_unsent_alerts:
        repository = EventRepository()
        try:
            alerts = _load_unsent_email_alerts(
                repository,
                limit=args.limit,
                include_info_alerts=args.include_info_alerts,
                include_unconfirmed_alerts=args.include_unconfirmed_alerts,
            )
            display_alerts = _print_email_preview(alerts)
            if args.dry_run or not alerts:
                return
            marked = repository.mark_alerts_sent(
                [alert.alert_id for alert in alerts],
                channel="test_skip",
            )
            print(f"Marked alerts test_skip: {marked}")
            if display_alerts:
                print("Skipped email send")
        finally:
            repository.close()
        return

    if args.run_daily:
        event_config = load_event_config()
        theme_map = load_theme_map()
        radar_config = event_config.get("radar", {})
        priority_config = event_config.get("alert_priority", {})
        event_limit = args.max_events or int(radar_config.get("max_events_per_run", 30))

        print("Step 1/4: Updating radar prices")
        price_results = update_radar_prices(
            lookback_days=args.price_lookback_days,
            refresh_overlap_days=args.price_refresh_overlap_days,
            max_retries=args.price_max_retries,
            dry_run=args.dry_run,
        )
        saved_rows = sum(result.rows_saved for result in price_results)
        print(f"Radar price tickers: {len(price_results)}, rows saved: {saved_rows}")

        print("Step 2/4: Fetching and classifying events")
        events = fetch_rss_events(
            event_config.get("rss_feeds") or [],
            limit=event_limit,
        )
        classified = classify_events(
            events,
            theme_map,
            min_theme_score=int(radar_config.get("min_theme_score", 1)),
            use_llm=True,
            llm_config=(event_config.get("llm", {}) | {"debug": args.llm_debug}),
        )
        print(f"Scanned events: {len(events)}")
        print(f"Matched events: {len(classified)}")
        for item in classified[:10]:
            primary = item.primary_match
            if primary is None:
                continue
            print(f"- {primary.theme} [{primary.category}] -> {', '.join(primary.tickers)}")
            print(f"  {item.news.title}")

        if args.dry_run:
            print("Dry run: skipped database writes, technical confirmation, and email")
            return

        repository = EventRepository()
        try:
            event_count, alert_count = persist_classified_events(
                classified,
                repository,
                high_priority_min_score=int(priority_config.get("high_priority_min_score", 3)),
                watchlist_min_score=int(priority_config.get("watchlist_min_score", 2)),
            )
            print(f"Saved events: {event_count}")
            print(f"Saved alert drafts: {alert_count}")

            print("Step 3/4: Confirming technicals")
            daily_limit = max(args.limit, alert_count)
            technical_results = confirm_pending_alerts(
                repository,
                limit=daily_limit,
                dry_run=False,
                thresholds=_technical_thresholds(event_config),
            )
            print(f"Checked pending alerts: {len(technical_results)}")

            print("Step 4/4: Email preview")
            alerts = _load_unsent_email_alerts(
                repository,
                limit=daily_limit,
                include_info_alerts=args.include_info_alerts,
                include_unconfirmed_alerts=args.include_unconfirmed_alerts,
            )
            display_alerts = _print_email_preview(alerts)
            should_send = args.send_email_alerts
            if not should_send:
                print("Email not sent. Add --send-email-alerts to send in --run-daily mode.")
                return

            if display_alerts and send_event_alert_email(display_alerts):
                marked = repository.mark_alerts_sent(
                    [alert.alert_id for alert in alerts],
                    channel="email",
                )
                print(f"Marked alerts sent: {marked}")
            elif display_alerts:
                print("Email alert send failed")
        finally:
            repository.close()
        return

    if args.update_trends:
        event_config = load_event_config()
        trend_config = event_config.get("trend_management", {})
        thresholds = TrendThresholds(
            cooling_no_news_days=int(trend_config.get("cooling_no_news_days", 5)),
            closed_no_news_days=int(trend_config.get("closed_no_news_days", 20)),
            cooling_drawdown_pct=float(trend_config.get("cooling_drawdown_pct", 0.08)),
            closed_drawdown_pct=float(trend_config.get("closed_drawdown_pct", 0.15)),
            cooling_min_signals=int(trend_config.get("cooling_min_signals", 2)),
            closed_min_signals=int(trend_config.get("closed_min_signals", 2)),
        )
        repository = EventRepository()
        try:
            results = update_trend_states(
                repository,
                thresholds=thresholds,
                dry_run=args.dry_run,
            )
            trend_alerts = repository.load_unsent_trend_alerts(limit=args.limit)
        finally:
            repository.close()
        print(f"Trend states checked: {len(results)}")
        for result in results[:30]:
            print(
                f"- {result.status} {result.ticker} {result.theme}: "
                f"close={result.last_close} high={result.high_watermark} "
                f"reason={result.reason}"
            )
        print(f"Unsent trend alerts: {len(trend_alerts)}")
        if trend_alerts:
            print(f"Subject: {build_trend_alert_subject(trend_alerts)}")
            for alert in trend_alerts[:20]:
                print(
                    f"- {alert.status} {alert.ticker} {alert.theme}: "
                    f"{alert.reason}"
                )
        if args.dry_run or not args.send_trend_alerts or not trend_alerts:
            return

        repository = EventRepository()
        try:
            if send_trend_alert_email(trend_alerts):
                marked = repository.mark_trend_alerts_sent(trend_alerts, channel="email")
                print(f"Marked trend alerts sent: {marked}")
            else:
                print("Trend alert email send failed")
        finally:
            repository.close()
        return

    if args.update_performance:
        repository = EventRepository()
        try:
            results = update_alert_performance(
                repository,
                limit=args.limit,
                dry_run=args.dry_run,
            )
        finally:
            repository.close()
        print(f"Performance rows: {len(results)}")
        for result in results[:30]:
            benchmark = (
                f"{result.benchmark_return_pct:+.2%}"
                if result.benchmark_return_pct is not None
                else "n/a"
            )
            relative = (
                f"{result.relative_return_pct:+.2%}"
                if result.relative_return_pct is not None
                else "n/a"
            )
            drawdown = (
                f"{result.max_drawdown_pct:+.2%}"
                if result.max_drawdown_pct is not None
                else "n/a"
            )
            print(
                f"- alert={result.alert_id} {result.ticker} "
                f"{result.horizon_days}d return={result.return_pct:+.2%} "
                f"benchmark={benchmark} relative={relative} drawdown={drawdown}"
            )
        return

    if args.performance_summary:
        repository = EventRepository()
        try:
            summaries = summarize_alert_performance(
                repository,
                horizon_days=args.summary_horizon,
                group_by=args.summary_group_by,
                min_count=args.summary_min_count,
            )
        finally:
            repository.close()
        print(
            f"Performance summary: horizon={args.summary_horizon}d "
            f"group_by={args.summary_group_by} rows={len(summaries)}"
        )
        for item in summaries[:30]:
            benchmark = (
                f"{item.avg_benchmark_return_pct:+.2%}"
                if item.avg_benchmark_return_pct is not None
                else "n/a"
            )
            relative = (
                f"{item.avg_relative_return_pct:+.2%}"
                if item.avg_relative_return_pct is not None
                else "n/a"
            )
            drawdown = (
                f"{item.avg_max_drawdown_pct:+.2%}"
                if item.avg_max_drawdown_pct is not None
                else "n/a"
            )
            beat_rate = (
                f"{item.benchmark_beat_rate:.0%}"
                if item.benchmark_beat_rate is not None
                else "n/a"
            )
            print(
                f"- {item.group}: n={item.sample_count} "
                f"avg_return={item.avg_return_pct:+.2%} "
                f"benchmark={benchmark} relative={relative} "
                f"drawdown={drawdown} win_rate={item.win_rate:.0%} "
                f"beat_rate={beat_rate}"
            )
        return

    if args.update_prices:
        results = update_radar_prices(
            lookback_days=args.price_lookback_days,
            refresh_overlap_days=args.price_refresh_overlap_days,
            max_retries=args.price_max_retries,
            dry_run=args.dry_run,
        )
        print(f"Radar price tickers: {len(results)}")
        for result in results:
            status = "dry-run" if result.skipped else f"saved={result.rows_saved}"
            if result.error:
                status = f"error={result.error}"
            print(
                f"- {result.ticker}: {status}, "
                f"latest_before={result.latest_before or 'none'}, "
                f"start={result.start_date}"
            )
        return

    if args.send_email_alerts:
        priorities = {"High Priority", "Watchlist"}
        if args.include_info_alerts:
            priorities.add("Info")

        repository = EventRepository()
        try:
            alerts = repository.load_unsent_alerts(
                limit=args.limit,
                priorities=priorities,
                include_unconfirmed=args.include_unconfirmed_alerts,
            )
            display_alerts = dedupe_alerts_for_email(alerts)
            print(f"Unsent email alerts: {len(alerts)}")
            if len(display_alerts) != len(alerts):
                print(f"Email rows after dedupe: {len(display_alerts)}")
            if display_alerts:
                print(f"Subject: {build_alert_subject(display_alerts)}")
                for alert in display_alerts[:20]:
                    print(
                        f"- {alert.priority} {alert.ticker} "
                        f"({alert.technical_status}) {alert.theme}"
                    )

            if args.dry_run or not display_alerts:
                return

            if send_event_alert_email(display_alerts):
                marked = repository.mark_alerts_sent(
                    [alert.alert_id for alert in alerts],
                    channel="email",
                )
                print(f"Marked alerts sent: {marked}")
            else:
                print("Email alert send failed")
        finally:
            repository.close()
        return

    if args.send_trend_alerts:
        repository = EventRepository()
        try:
            trend_alerts = repository.load_unsent_trend_alerts(limit=args.limit)
            print(f"Unsent trend alerts: {len(trend_alerts)}")
            if trend_alerts:
                print(f"Subject: {build_trend_alert_subject(trend_alerts)}")
                for alert in trend_alerts[:20]:
                    print(
                        f"- {alert.status} {alert.ticker} {alert.theme}: "
                        f"{alert.reason}"
                    )
            if args.dry_run or not trend_alerts:
                return
            if send_trend_alert_email(trend_alerts):
                marked = repository.mark_trend_alerts_sent(trend_alerts, channel="email")
                print(f"Marked trend alerts sent: {marked}")
            else:
                print("Trend alert email send failed")
        finally:
            repository.close()
        return

    if args.confirm_technicals:
        event_config = load_event_config()
        technical_config = event_config.get("technical_confirmation", {})
        thresholds = TechnicalThresholds(
            breakout_lookback=int(technical_config.get("breakout_lookback", 20)),
            major_breakout_lookback=int(technical_config.get("major_breakout_lookback", 55)),
            volume_lookback=int(technical_config.get("volume_lookback", 20)),
            volume_ratio_min=float(technical_config.get("volume_ratio_min", 1.3)),
            relative_strength_days=int(technical_config.get("relative_strength_days", 20)),
            high_priority_confirmations=int(
                technical_config.get("high_priority_confirmations", 3)
            ),
            watchlist_confirmations=int(
                technical_config.get("watchlist_confirmations", 1)
            ),
            stop_loss_pct=float(technical_config.get("stop_loss_pct", 0.08)),
            first_take_profit_pct=float(
                technical_config.get("first_take_profit_pct", 0.10)
            ),
            second_take_profit_pct=float(
                technical_config.get("second_take_profit_pct", 0.20)
            ),
            trailing_stop_pct=float(technical_config.get("trailing_stop_pct", 0.08)),
        )
        repository = EventRepository()
        try:
            results = confirm_pending_alerts(
                repository,
                limit=args.limit,
                dry_run=args.dry_run,
                thresholds=thresholds,
            )
        finally:
            repository.close()

        print(f"Checked pending alerts: {len(results)}")
        for alert, check in results[:20]:
            print(
                f"- {alert.ticker}: {check.priority} "
                f"({check.technical_status}) close={check.close_price}"
            )
            print(f"  {check.reason}")
        return

    event_config = load_event_config()
    theme_map = load_theme_map()
    radar_config = event_config.get("radar", {})
    priority_config = event_config.get("alert_priority", {})

    sample = _sample_event(args)
    if sample:
        events = [sample]
    else:
        events = fetch_rss_events(
            event_config.get("rss_feeds") or [],
            limit=args.max_events or int(radar_config.get("max_events_per_run", 30)),
        )

    if args.rss_dry_run:
        print(f"Fetched RSS events: {len(events)}")
        for event in events[:30]:
            print(f"- [{event.source}] {event.title}")
        return

    classified = classify_events(
        events,
        theme_map,
        min_theme_score=int(radar_config.get("min_theme_score", 1)),
        use_llm=args.use_llm,
        llm_config=(event_config.get("llm", {}) | {"debug": args.llm_debug}),
    )

    print(f"Scanned events: {len(events)}")
    print(f"Matched events: {len(classified)}")

    for item in classified[:10]:
        primary = item.primary_match
        if primary is None:
            continue
        print(f"- {primary.theme} [{primary.category}] -> {', '.join(primary.tickers)}")
        print(f"  {item.news.title}")
        print(f"  keywords: {', '.join(primary.matched_keywords)}")

    if args.dry_run:
        return

    repository = EventRepository()
    try:
        event_count, alert_count = persist_classified_events(
            classified,
            repository,
            high_priority_min_score=int(priority_config.get("high_priority_min_score", 3)),
            watchlist_min_score=int(priority_config.get("watchlist_min_score", 2)),
        )
    finally:
        repository.close()

    print(f"Saved events: {event_count}")
    print(f"Saved alert drafts: {alert_count}")


if __name__ == "__main__":
    main()
