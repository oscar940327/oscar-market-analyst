from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from html import escape
import re

from event_radar.models import RadarAlert, TrendAlert
from pipeline.email_sender import send_html_email


_PRIORITY_RANK = {
    "High Priority": 0,
    "Strong Watchlist": 1,
    "Watchlist": 2,
    "Weak Watchlist": 3,
    "Info": 4,
}

_STATUS_RANK = {
    "confirmed": 0,
    "partial": 1,
    "unconfirmed": 2,
    "insufficient_data": 3,
}


_CSS = """
<style>
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    max-width: 820px;
    margin: 0 auto;
    padding: 20px;
    color: #24292f;
    background: #f6f8fa;
}
.container {
    background: #ffffff;
    border-radius: 8px;
    padding: 28px;
    border: 1px solid #d0d7de;
}
h1 {
    font-size: 22px;
    margin: 0 0 6px;
}
.subtitle {
    margin: 0 0 22px;
    color: #57606a;
    font-size: 13px;
}
.alert {
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 14px;
    margin: 12px 0;
    background: #ffffff;
}
.priority-high {
    border-left: 5px solid #cf222e;
}
.priority-watch {
    border-left: 5px solid #bf8700;
}
.priority-info {
    border-left: 5px solid #0969da;
}
.headline {
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 4px;
}
.summary {
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 12px 14px;
    margin: 14px 0 18px;
    background: #f6f8fa;
}
.summary h2 {
    font-size: 15px;
    margin: 0 0 8px;
}
.summary ol {
    margin: 0;
    padding-left: 20px;
}
.summary li {
    margin: 8px 0;
}
.ticker-list {
    font-size: 13px;
    line-height: 1.45;
    margin: 8px 0;
}
.ticker-row {
    border-top: 1px solid #d8dee4;
    padding-top: 8px;
    margin-top: 8px;
}
.ticker-name {
    font-weight: 700;
}
.meta {
    color: #57606a;
    font-size: 12px;
    margin-bottom: 10px;
}
.badge {
    display: inline-block;
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 650;
    margin-right: 6px;
}
.badge-high { background: #ffebe9; color: #a40e26; }
.badge-watch { background: #fff8c5; color: #7d4e00; }
.badge-info { background: #ddf4ff; color: #0969da; }
.grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    margin: 10px 0;
}
.metric {
    background: #f6f8fa;
    border-radius: 6px;
    padding: 8px;
}
.label {
    color: #57606a;
    font-size: 11px;
    margin-bottom: 3px;
}
.value {
    font-weight: 650;
    font-size: 13px;
}
.reason {
    color: #24292f;
    font-size: 13px;
    line-height: 1.45;
}
.fundamental {
    margin-top: 8px;
    color: #57606a;
    font-size: 12px;
    line-height: 1.4;
}
a { color: #0969da; }
.footer {
    color: #57606a;
    font-size: 12px;
    margin-top: 22px;
    border-top: 1px solid #d0d7de;
    padding-top: 12px;
}
@media (max-width: 640px) {
    body { padding: 12px; }
    .container { padding: 18px; }
    .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
"""


def _priority_class(priority: str) -> str:
    if priority == "High Priority":
        return "priority-high"
    if priority in {"Strong Watchlist", "Watchlist", "Weak Watchlist"}:
        return "priority-watch"
    return "priority-info"


def _priority_badge(priority: str) -> str:
    css = {
        "High Priority": "badge-high",
        "Strong Watchlist": "badge-watch",
        "Watchlist": "badge-watch",
        "Weak Watchlist": "badge-info",
    }.get(priority, "badge-info")
    return f'<span class="badge {css}">{escape(priority)}</span>'


@dataclass(frozen=True)
class EventAlertGroup:
    event_id: int
    theme: str
    alerts: list[RadarAlert]

    @property
    def title(self) -> str:
        return self.alerts[0].event_title

    @property
    def best_priority(self) -> str:
        return min(
            (alert.priority for alert in self.alerts),
            key=lambda priority: _PRIORITY_RANK.get(priority, 9),
        )

    @property
    def event_strength(self) -> int:
        return max(_event_strength(alert) for alert in self.alerts)


def dedupe_alerts_for_email(alerts: list[RadarAlert]) -> list[RadarAlert]:
    """Keep one email row per event/theme/ticker, preferring stronger technical evidence."""
    best: dict[tuple[int, str, str], RadarAlert] = {}
    for alert in alerts:
        key = (alert.event_id, alert.theme, alert.ticker)
        current = best.get(key)
        if current is None:
            best[key] = alert
            continue

        alert_rank = (
            _PRIORITY_RANK.get(alert.priority, 9),
            _STATUS_RANK.get(alert.technical_status, 9),
            -alert.alert_id,
        )
        current_rank = (
            _PRIORITY_RANK.get(current.priority, 9),
            _STATUS_RANK.get(current.technical_status, 9),
            -current.alert_id,
        )
        if alert_rank < current_rank:
            best[key] = alert

    return sorted(
        best.values(),
        key=lambda item: (
            _PRIORITY_RANK.get(item.priority, 9),
            item.theme,
            item.ticker,
        ),
    )


def _fmt_price(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2%}"


def _fmt_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}x"


def _event_strength(alert: RadarAlert) -> int:
    value = (alert.metadata or {}).get("news_event_strength")
    if value is None:
        match = re.search(r"news_event_strength=(\d+)", alert.reason)
        value = match.group(1) if match else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return 100


def _ticker_tier(alert: RadarAlert) -> str:
    tier = str((alert.metadata or {}).get("ticker_tier") or "core").lower()
    return tier if tier in {"core", "secondary", "extended"} else "core"


def _confirmation_count(alert: RadarAlert) -> int:
    value = (alert.metadata or {}).get("confirmation_count")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def filter_alerts_for_email(alerts: list[RadarAlert]) -> list[RadarAlert]:
    """Apply email noise controls while keeping all alerts persisted in the DB."""
    eligible = []
    for alert in alerts:
        if _event_strength(alert) < 40:
            continue
        if alert.priority in {"Info", "Weak Watchlist"}:
            continue
        if alert.technical_status not in {"confirmed", "partial"}:
            continue
        eligible.append(alert)
    return dedupe_alerts_for_email(eligible)


def _source_line(alert: RadarAlert) -> str:
    parts = [part for part in [alert.event_source, alert.event_published_at] if part]
    text = " · ".join(escape(part) for part in parts)
    if alert.event_url:
        link = escape(alert.event_url, quote=True)
        return f'{text} · <a href="{link}">source</a>' if text else f'<a href="{link}">source</a>'
    return text


def _fundamental_line(alert: RadarAlert) -> str:
    fundamental = alert.metadata.get("fundamental") if alert.metadata else None
    if not isinstance(fundamental, dict):
        return ""
    rating = escape(str(fundamental.get("rating") or "Unknown"))
    summary = escape(str(fundamental.get("summary") or ""))
    check_date = escape(str(fundamental.get("check_date") or ""))
    label = f"Fundamental {rating}"
    if check_date:
        label += f" ({check_date})"
    return f'<div class="fundamental"><strong>{label}</strong>: {summary}</div>'


def _group_alerts(alerts: list[RadarAlert]) -> list[EventAlertGroup]:
    grouped: dict[tuple[int, str], list[RadarAlert]] = defaultdict(list)
    for alert in alerts:
        grouped[(alert.event_id, alert.theme)].append(alert)
    groups = [
        EventAlertGroup(event_id=event_id, theme=theme, alerts=items)
        for (event_id, theme), items in grouped.items()
    ]
    return sorted(
        groups,
        key=lambda group: (
            _PRIORITY_RANK.get(group.best_priority, 9),
            -group.event_strength,
            group.theme,
        ),
    )


def _ticker_names(alerts: list[RadarAlert]) -> str:
    return ", ".join(escape(alert.ticker) for alert in alerts) or "none"


def _split_group_tickers(group: EventAlertGroup) -> tuple[list[RadarAlert], list[RadarAlert], list[RadarAlert]]:
    visible_main: list[RadarAlert] = []
    visible_secondary: list[RadarAlert] = []
    folded: list[RadarAlert] = []

    for alert in sorted(
        group.alerts,
        key=lambda item: (
            {"core": 0, "secondary": 1, "extended": 2}.get(_ticker_tier(item), 3),
            _PRIORITY_RANK.get(item.priority, 9),
            -_confirmation_count(item),
            item.ticker,
        ),
    ):
        tier = _ticker_tier(alert)
        strong = alert.priority in {"High Priority", "Strong Watchlist"}
        if tier == "core":
            visible_main.append(alert)
        elif tier == "secondary" and (group.event_strength >= 60 or strong):
            visible_secondary.append(alert)
        elif tier == "extended" and strong:
            visible_secondary.append(alert)
        else:
            folded.append(alert)

    return visible_main, visible_secondary, folded


def _summary_html(groups: list[EventAlertGroup]) -> str:
    if not groups:
        return ""
    rows = []
    for group in groups[:5]:
        main, secondary, folded = _split_group_tickers(group)
        primary = main or secondary or folded
        rows.append(
            f"""
            <li>
                <strong>{escape(group.theme)}</strong>
                <div class="meta">
                    Strength: {group.event_strength} · Status: {escape(group.best_priority)}
                </div>
                <div class="ticker-list">主要標的: {_ticker_names(primary[:5])}</div>
                <div class="meta">{escape(group.title)}</div>
            </li>
            """
        )
    return f"""
    <div class="summary">
        <h2>今日重點</h2>
        <ol>{''.join(rows)}</ol>
    </div>
    """


def _ticker_detail(alert: RadarAlert) -> str:
    return f"""
    <div class="ticker-row">
        <span class="ticker-name">{escape(alert.ticker)}</span>
        {_priority_badge(alert.priority)}
        <div class="grid">
            <div class="metric">
                <div class="label">Close</div>
                <div class="value">{_fmt_price(alert.close_price)}</div>
            </div>
            <div class="metric">
                <div class="label">Technical</div>
                <div class="value">{escape(alert.technical_status)}</div>
            </div>
            <div class="metric">
                <div class="label">Rel. Strength</div>
                <div class="value">{_fmt_pct(alert.relative_strength)}</div>
            </div>
            <div class="metric">
                <div class="label">Volume</div>
                <div class="value">{_fmt_float(alert.volume_ratio)}</div>
            </div>
        </div>
        {_fundamental_line(alert)}
    </div>
    """


def build_alert_email(alerts: list[RadarAlert], report_date: str | None = None) -> str:
    report_date = report_date or date.today().isoformat()
    alerts = filter_alerts_for_email(alerts)
    groups = _group_alerts(alerts)

    cards = []
    for group in groups:
        first = group.alerts[0]
        source = _source_line(first)
        main, secondary, folded = _split_group_tickers(group)
        compact = group.event_strength < 60
        detail_alerts = [] if compact else main + secondary
        folded_text = _ticker_names(folded)
        folded_html = (
            f'<div class="ticker-list"><strong>折疊:</strong> {folded_text}</div>'
            if folded
            else ""
        )
        detail_html = "".join(_ticker_detail(alert) for alert in detail_alerts)
        if compact:
            detail_html = (
                '<div class="meta">事件強度低於 60，僅顯示摘要。</div>'
            )

        cards.append(
            f"""
            <div class="alert {_priority_class(group.best_priority)}">
                <div class="headline">
                    {_priority_badge(group.best_priority)}
                    {escape(group.theme)}
                </div>
                <div class="meta">{escape(group.title)}</div>
                <div class="meta">{source}</div>
                <div class="ticker-list"><strong>主要觀察:</strong> {_ticker_names(main)}</div>
                <div class="ticker-list"><strong>延伸觀察:</strong> {_ticker_names(secondary)}</div>
                {folded_html}
                <div class="reason">Event strength: {group.event_strength}</div>
                {detail_html}
            </div>
            """
        )

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        {_CSS}
    </head>
    <body>
        <div class="container">
            <h1>Event Radar Alerts</h1>
            <p class="subtitle">{escape(report_date)} · {len(groups)} event group(s) · {len(alerts)} visible ticker alert(s)</p>
            {_summary_html(groups)}
            {''.join(cards)}
            <div class="footer">
                Generated by Oscar Market Analyst Event Radar.
            </div>
        </div>
    </body>
    </html>
    """


def build_alert_subject(alerts: list[RadarAlert], report_date: str | None = None) -> str:
    report_date = report_date or date.today().isoformat()
    alerts = filter_alerts_for_email(alerts)
    groups = _group_alerts(alerts)
    high_count = sum(1 for alert in alerts if alert.priority == "High Priority")
    strong_count = sum(1 for alert in alerts if alert.priority == "Strong Watchlist")
    watch_count = sum(1 for alert in alerts if alert.priority == "Watchlist")
    if high_count:
        return f"[Event Radar] {report_date} - {high_count} high priority ticker(s)"
    if strong_count:
        return f"[Event Radar] {report_date} - {strong_count} strong watchlist ticker(s)"
    if watch_count:
        return f"[Event Radar] {report_date} - {len(groups)} watchlist event(s)"
    return f"[Event Radar] {report_date} - {len(groups)} event(s)"


def send_event_alert_email(alerts: list[RadarAlert]) -> bool:
    alerts = filter_alerts_for_email(alerts)
    if not alerts:
        return False
    html = build_alert_email(alerts)
    subject = build_alert_subject(alerts)
    return send_html_email(subject=subject, html_body=html)


def _fmt_trend_price(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def build_trend_alert_subject(
    alerts: list[TrendAlert],
    report_date: str | None = None,
) -> str:
    report_date = report_date or date.today().isoformat()
    closed = sum(1 for alert in alerts if alert.status == "Closed")
    cooling = sum(1 for alert in alerts if alert.status == "Cooling")
    if closed:
        return f"[Event Radar] {report_date} - {closed} trend closed alert(s)"
    return f"[Event Radar] {report_date} - {cooling} trend cooling alert(s)"


def build_trend_alert_email(
    alerts: list[TrendAlert],
    report_date: str | None = None,
) -> str:
    report_date = report_date or date.today().isoformat()
    cards = []
    for alert in sorted(
        alerts,
        key=lambda item: (item.status != "Closed", item.theme, item.ticker),
    ):
        priority_class = "priority-high" if alert.status == "Closed" else "priority-watch"
        badge_class = "badge-high" if alert.status == "Closed" else "badge-watch"
        cards.append(
            f"""
            <div class="alert {priority_class}">
                <div class="headline">
                    <span class="badge {badge_class}">{escape(alert.status)}</span>
                    {escape(alert.ticker)} · {escape(alert.theme)}
                </div>
                <div class="meta">Last related alert: {escape(alert.last_event_date or "n/a")}</div>
                <div class="grid">
                    <div class="metric">
                        <div class="label">Close</div>
                        <div class="value">{_fmt_trend_price(alert.last_close)}</div>
                    </div>
                    <div class="metric">
                        <div class="label">High Watermark</div>
                        <div class="value">{_fmt_trend_price(alert.high_watermark)}</div>
                    </div>
                    <div class="metric">
                        <div class="label">Status</div>
                        <div class="value">{escape(alert.status)}</div>
                    </div>
                    <div class="metric">
                        <div class="label">Theme</div>
                        <div class="value">{escape(alert.theme)}</div>
                    </div>
                </div>
                <div class="reason">{escape(alert.reason)}</div>
            </div>
            """
        )

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        {_CSS}
    </head>
    <body>
        <div class="container">
            <h1>Event Radar Trend Alerts</h1>
            <p class="subtitle">{escape(report_date)} · {len(alerts)} trend alert(s)</p>
            {''.join(cards)}
            <div class="footer">
                Generated by Oscar Market Analyst Event Radar.
            </div>
        </div>
    </body>
    </html>
    """


def send_trend_alert_email(alerts: list[TrendAlert]) -> bool:
    if not alerts:
        return False
    html = build_trend_alert_email(alerts)
    subject = build_trend_alert_subject(alerts)
    return send_html_email(subject=subject, html_body=html)
