"""
report_builder.py — Phase 5.5: 含綜合評分區塊的 HTML 報告
"""
from datetime import datetime
from pipeline.signal_scanner import TradingSignal


_CSS = """
<style>
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    max-width: 760px;
    margin: 0 auto;
    padding: 20px;
    color: #24292e;
    background: #f6f8fa;
}
.container {
    background: white;
    border-radius: 8px;
    padding: 30px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
h1 {
    color: #0366d6;
    border-bottom: 2px solid #e1e4e8;
    padding-bottom: 10px;
    margin-top: 0;
}
h2 {
    color: #24292e;
    margin-top: 30px;
    font-size: 18px;
    border-left: 4px solid #0366d6;
    padding-left: 10px;
}
.regime-badge {
    display: inline-block;
    padding: 6px 14px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 14px;
}
.regime-bull { background: #d4edda; color: #155724; }
.regime-neutral { background: #fff3cd; color: #856404; }
.regime-bear { background: #f8d7da; color: #721c24; }

.signal-card {
    border: 1px solid #e1e4e8;
    border-radius: 6px;
    padding: 16px;
    margin: 14px 0;
    background: #fafbfc;
}
.signal-buy { border-left: 4px solid #28a745; }
.signal-emergency { border-left: 4px solid #dc3545; background: #fff5f5; }

.score-card {
    border: 1px solid #e1e4e8;
    border-radius: 6px;
    padding: 14px;
    margin: 10px 0;
    background: #fafbfc;
}
.score-strong-buy { border-left: 5px solid #28a745; background: #f0fff4; }
.score-buy { border-left: 5px solid #5cb85c; }
.score-hold { border-left: 5px solid #f0ad4e; }
.score-wait { border-left: 5px solid #999; opacity: 0.85; }
.score-sell { border-left: 5px solid #dc3545; opacity: 0.75; }

.ticker {
    font-size: 18px;
    font-weight: 700;
    color: #24292e;
}
.action-tag {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    margin-left: 8px;
}
.tag-buy { background: #28a745; color: white; }
.tag-emergency { background: #dc3545; color: white; }

.score-big {
    display: inline-block;
    font-size: 24px;
    font-weight: 700;
    color: #0366d6;
    margin-left: 10px;
}
.score-big.high { color: #28a745; }
.score-big.mid { color: #f0ad4e; }
.score-big.low { color: #dc3545; }

.score-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px 16px;
    margin: 10px 0;
    font-size: 13px;
}
.score-row {
    display: flex;
    justify-content: space-between;
}
.score-row .label { color: #586069; }
.score-row .value { font-weight: 500; font-family: 'SF Mono', Menlo, monospace; }

.levels-box {
    background: #f6f8fa;
    border-radius: 4px;
    padding: 10px 14px;
    margin-top: 10px;
    font-size: 13px;
    font-family: 'SF Mono', Menlo, monospace;
}
.levels-box .row {
    display: flex;
    justify-content: space-between;
    padding: 3px 0;
}
.levels-box .label { color: #586069; }

table.signal-info {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0;
}
table.signal-info td {
    padding: 6px 0;
    font-size: 14px;
}
table.signal-info td.label {
    color: #586069;
    width: 40%;
}
table.signal-info td.value {
    font-weight: 500;
    font-family: 'SF Mono', Menlo, monospace;
}

.reasons {
    margin-top: 8px;
    font-size: 12px;
    color: #2d6e3e;
}
.risks {
    margin-top: 4px;
    font-size: 12px;
    color: #b94a48;
}
.reasoning {
    font-style: italic;
    color: #586069;
    font-size: 13px;
    margin-top: 10px;
    padding: 10px;
    background: #f6f8fa;
    border-radius: 4px;
}
.footer {
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid #e1e4e8;
    font-size: 12px;
    color: #6a737d;
    text-align: center;
}
.empty {
    text-align: center;
    padding: 20px;
    color: #6a737d;
    font-style: italic;
}
</style>
"""


def _regime_badge(regime: str) -> str:
    label_map = {
        "bull": "🐂 Bull (多頭)",
        "bear": "🐻 Bear (空頭)",
        "neutral": "⚖️ Neutral (中性)",
    }
    return f'<span class="regime-badge regime-{regime}">{label_map.get(regime, regime)}</span>'


def _score_class(signal_value: str) -> str:
    mapping = {
        "強烈買入": "score-strong-buy",
        "買入": "score-buy",
        "持有": "score-hold",
        "觀望": "score-wait",
        "賣出": "score-sell",
        "強烈賣出": "score-sell",
    }
    return mapping.get(signal_value, "score-hold")


def _score_color_class(score: int) -> str:
    if score >= 75:
        return "high"
    elif score >= 45:
        return "mid"
    else:
        return "low"


def _render_composite_card(sig: TradingSignal) -> str:
    if not sig.composite:
        return ""

    c = sig.composite
    l = sig.levels
    css_class = _score_class(c.signal.value)
    score_color = _score_color_class(c.total_score)

    dimensions_html = f"""
    <div class="score-grid">
        <div class="score-row">
            <span class="label">📈 趨勢</span>
            <span class="value">{c.trend_status.value} ({c.trend_score}/30)</span>
        </div>
        <div class="score-row">
            <span class="label">📐 乖離率</span>
            <span class="value">{c.bias_ma5:+.1f}% ({c.bias_score}/20)</span>
        </div>
        <div class="score-row">
            <span class="label">📊 量能</span>
            <span class="value">{c.volume_status.value} ({c.volume_score}/15)</span>
        </div>
        <div class="score-row">
            <span class="label">🎯 支撐</span>
            <span class="value">{c.support_score}/10</span>
        </div>
        <div class="score-row">
            <span class="label">🔵 MACD</span>
            <span class="value">{c.macd_status.value} ({c.macd_score}/15)</span>
        </div>
        <div class="score-row">
            <span class="label">🌡️ RSI</span>
            <span class="value">{c.rsi_value:.0f} ({c.rsi_status.value}) ({c.rsi_score}/10)</span>
        </div>
    </div>
    """

    levels_html = ""
    if l:
        levels_html = f"""
        <div class="levels-box">
            <div class="row"><span class="label">💰 理想買入 (MA5)</span><span>${l.ideal_buy:.2f}</span></div>
            <div class="row"><span class="label">💰 次優買入 (MA10)</span><span>${l.secondary_buy:.2f}</span></div>
            <div class="row"><span class="label">🛑 停損</span><span>${l.stop_loss_final:.2f}</span></div>
            <div class="row"><span class="label">🎯 目標 ({l.take_profit_label})</span><span>${l.take_profit:.2f}</span></div>
            <div class="row"><span class="label">⚖️ 風險報酬比</span><span>{l.risk_reward:.2f}</span></div>
        </div>
        """

    reasons_html = ""
    if c.reasons:
        reasons_html = f'<div class="reasons">{" · ".join(c.reasons)}</div>'
    risks_html = ""
    if c.risks:
        risks_html = f'<div class="risks">{" · ".join(c.risks)}</div>'

    return f"""
    <div class="score-card {css_class}">
        <div>
            <span class="ticker">{c.ticker}</span>
            <span class="score-big {score_color}">{c.total_score}</span>
            <span style="color: #586069;">/100 · {c.signal.value}</span>
            <span style="float: right; color: #586069; font-size: 13px;">${c.current_price:.2f}</span>
        </div>
        {dimensions_html}
        {levels_html}
        {reasons_html}
        {risks_html}
    </div>
    """


def _render_buy_signal(sig: TradingSignal) -> str:
    return f"""
    <div class="signal-card signal-buy">
        <div>
            <span class="ticker">{sig.ticker}</span>
            <span class="action-tag tag-buy">🟢 BREAKOUT</span>
        </div>
        <table class="signal-info">
            <tr><td class="label">📊 突破狀態</td>
                <td class="value">${sig.close_price:.2f} > 20日高 ${sig.n_day_high:.2f} ✓</td></tr>
            <tr><td class="label">💰 觸發價</td>
                <td class="value">${sig.entry_trigger:.2f}</td></tr>
            <tr><td class="label">🛑 絕對停損</td>
                <td class="value">${sig.stop_loss:.2f} (-8%)</td></tr>
            <tr><td class="label">📉 移動停損</td>
                <td class="value">${sig.trailing_stop_initial:.2f} (-15%)</td></tr>
            <tr><td class="label">🌍 大盤狀態</td>
                <td class="value">{sig.market_regime}</td></tr>
        </table>
    </div>
    """


def _render_emergency_signal(sig: TradingSignal) -> str:
    return f"""
    <div class="signal-card signal-emergency">
        <div>
            <span class="ticker">{sig.ticker}</span>
            <span class="action-tag tag-emergency">🚨 EMERGENCY EXIT</span>
        </div>
        <table class="signal-info">
            <tr><td class="label">📰 情緒分數</td><td class="value">{sig.sentiment_score:+.2f}</td></tr>
            <tr><td class="label">⚡ 事件嚴重度</td><td class="value">{sig.event_severity:.1f}</td></tr>
            <tr><td class="label">💥 觸發原因</td><td class="value">{sig.filter_reason}</td></tr>
            <tr><td class="label">📍 收盤價</td><td class="value">${sig.close_price:.2f}</td></tr>
        </table>
        {f'<div class="reasoning">💬 {sig.sentiment_reasoning}</div>' if sig.sentiment_reasoning else ''}
        <div class="reasoning" style="color: #dc3545; font-weight: 600;">
            ⚠️ 如持有此股，建議明日開盤立即市價賣出。
        </div>
    </div>
    """


def build_html_report(
    signals: list[TradingSignal],
    regime: str,
    regime_info: dict,
    report_date: str | None = None,
) -> str:
    # Phase 5.5 marker for grep verification
    if report_date is None:
        report_date = datetime.now().strftime("%Y-%m-%d")

    buys = [s for s in signals if s.action == "BUY"]
    emergencies = [s for s in signals if s.action == "EMERGENCY_EXIT"]

    scored_signals = [s for s in signals if s.composite is not None]
    scored_signals.sort(key=lambda s: s.composite.total_score, reverse=True)

    regime_desc = (
        f"SPY ${regime_info.get('spy_close', 'N/A')} / "
        f"MA50 ${regime_info.get('spy_ma50', 'N/A')} "
        f"({regime_info.get('deviation_pct', 0):+.2f}%)"
        f" | VIX: {regime_info.get('vix_close', 'N/A')}"
    )

    body_parts = [
        '<div class="container">',
        f'<h1>📊 每日交易分析報告</h1>',
        f'<p><b>日期：</b>{report_date}</p>',
        f'<p><b>市場環境：</b>{_regime_badge(regime)}</p>',
        f'<p style="color: #586069; font-size: 13px;">{regime_desc}</p>',
    ]

    if emergencies:
        body_parts.append('<h2>🚨 緊急平倉警告</h2>')
        for sig in emergencies:
            body_parts.append(_render_emergency_signal(sig))

    if buys:
        body_parts.append(f'<h2>🟢 突破進場訊號 ({len(buys)})</h2>')
        for sig in buys:
            body_parts.append(_render_buy_signal(sig))

    if not buys and not emergencies:
        body_parts.append('<h2>📋 今日策略訊號</h2>')
        body_parts.append('<div class="empty">無進場訊號 / 無緊急平倉</div>')

    body_parts.append(f'<h2>📊 綜合評分排行榜 ({len(scored_signals)} 檔)</h2>')
    body_parts.append('<p style="color: #586069; font-size: 13px;">')
    body_parts.append('6 維度技術評分（趨勢/乖離率/量能/支撐/MACD/RSI），按分數排序。')
    body_parts.append('包含理想買入價、停損價、目標價的計算結果。')
    body_parts.append('</p>')

    if scored_signals:
        for sig in scored_signals:
            body_parts.append(_render_composite_card(sig))
    else:
        body_parts.append('<div class="empty">資料不足，無法計算評分</div>')

    body_parts.append("""
    <div class="footer">
        Oscar Market Analyst · Phase 5.5<br>
        本報告由系統自動產生，僅作為決策參考，不構成投資建議
    </div>
    </div>
    """)

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <title>Daily Trading Report - {report_date}</title>
    {_CSS}
</head>
<body>
    {"".join(body_parts)}
</body>
</html>"""

    return html