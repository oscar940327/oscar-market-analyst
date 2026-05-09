from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape

from event_radar.models import RadarAlert, TrendAlert
from pipeline.email_sender import send_html_email


_PRIORITY_RANK = {
    "High Priority": 0,
    "Watchlist": 1,
    "Info": 2,
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
    if priority == "Watchlist":
        return "priority-watch"
    return "priority-info"


def _priority_badge(priority: str) -> str:
    css = {
        "High Priority": "badge-high",
        "Watchlist": "badge-watch",
    }.get(priority, "badge-info")
    return f'<span class="badge {css}">{escape(priority)}</span>'


def dedupe_alerts_for_email(alerts: list[RadarAlert]) -> list[RadarAlert]:
    """Keep one email row per theme/ticker, preferring stronger technical evidence."""
    best: dict[tuple[str, str], RadarAlert] = {}
    for alert in alerts:
        key = (alert.theme, alert.ticker)
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


def build_alert_email(alerts: list[RadarAlert], report_date: str | None = None) -> str:
    report_date = report_date or date.today().isoformat()
    by_event: dict[int, list[RadarAlert]] = defaultdict(list)
    for alert in alerts:
        by_event[alert.event_id].append(alert)

    cards = []
    for event_alerts in by_event.values():
        event_alerts = sorted(
            event_alerts,
            key=lambda item: (item.priority != "High Priority", item.ticker),
        )
        title = escape(event_alerts[0].event_title)
        source = _source_line(event_alerts[0])

        for alert in event_alerts:
            cards.append(
                f"""
                <div class="alert {_priority_class(alert.priority)}">
                    <div class="headline">
                        {_priority_badge(alert.priority)}
                        {escape(alert.ticker)} · {escape(alert.theme)}
                    </div>
                    <div class="meta">{title}</div>
                    <div class="meta">{source}</div>
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
                    <div class="reason">{escape(alert.reason)}</div>
                    {_fundamental_line(alert)}
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
            <p class="subtitle">{escape(report_date)} · {len(alerts)} alert(s)</p>
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
    high_count = sum(1 for alert in alerts if alert.priority == "High Priority")
    watch_count = sum(1 for alert in alerts if alert.priority == "Watchlist")
    if high_count:
        return f"[Event Radar] {report_date} - {high_count} high priority alert(s)"
    if watch_count:
        return f"[Event Radar] {report_date} - {watch_count} watchlist alert(s)"
    return f"[Event Radar] {report_date} - {len(alerts)} alert(s)"


def send_event_alert_email(alerts: list[RadarAlert]) -> bool:
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
