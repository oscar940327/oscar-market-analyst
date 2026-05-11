from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class FundamentalCheck:
    ticker: str
    check_date: str
    rating: str
    valuation_score: int
    quality_score: int
    summary: str
    metrics: dict[str, float | None] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


InfoProvider = Callable[[str], dict[str, Any]]


def fetch_yfinance_info(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    cache_dir = Path(__file__).resolve().parent.parent / "data" / "cache" / "yfinance"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(str(cache_dir))
    return dict(yf.Ticker(ticker).get_info() or {})


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _score_lower_better(value: float | None, good: float, fair: float, poor: float) -> int:
    if value is None or value <= 0:
        return 0
    if value <= good:
        return 2
    if value <= fair:
        return 1
    if value <= poor:
        return 0
    return -1


def _score_higher_better(value: float | None, good: float, fair: float, weak: float = 0.0) -> int:
    if value is None:
        return 0
    if value >= good:
        return 2
    if value >= fair:
        return 1
    if value >= weak:
        return 0
    return -1


def _rating(
    valuation_score: int,
    quality_score: int,
    fcf_yield: float | None,
    free_cash_flow: float | None,
    debt_to_equity: float | None,
) -> str:
    total = valuation_score + quality_score
    severe_cash_flow_problem = fcf_yield is not None and fcf_yield <= -0.10
    weak_cash_flow = (
        (fcf_yield is not None and fcf_yield < 0)
        or (free_cash_flow is not None and free_cash_flow <= 0)
    )
    severe_debt_risk = debt_to_equity is not None and debt_to_equity > 400
    debt_risk = debt_to_equity is not None and debt_to_equity > 200
    very_expensive = valuation_score < 0

    if severe_cash_flow_problem or severe_debt_risk or quality_score < 0:
        return "E"
    if weak_cash_flow and (very_expensive or quality_score < 4):
        return "D"
    if debt_risk and total < 5:
        return "D"
    if valuation_score >= 4 and quality_score >= 6 and not weak_cash_flow and not debt_risk:
        return "A"
    if valuation_score >= 2 and quality_score >= 4 and not severe_cash_flow_problem:
        return "B"
    if quality_score >= 5 and total >= 2:
        return "C"
    if total >= 0:
        return "D"
    return "E"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _fmt_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}x"


def build_fundamental_check(
    ticker: str,
    info: dict[str, Any],
    check_date: str | None = None,
) -> FundamentalCheck:
    ticker = ticker.upper()
    check_date = check_date or date.today().isoformat()
    trailing_pe = _num(info.get("trailingPE"))
    forward_pe = _num(info.get("forwardPE"))
    peg_ratio = _num(info.get("pegRatio"))
    price_to_sales = _num(info.get("priceToSalesTrailing12Months"))
    price_to_book = _num(info.get("priceToBook"))
    free_cash_flow = _num(info.get("freeCashflow"))
    market_cap = _num(info.get("marketCap"))
    fcf_yield = (
        free_cash_flow / market_cap
        if free_cash_flow is not None and market_cap and market_cap > 0
        else None
    )

    revenue_growth = _num(info.get("revenueGrowth"))
    earnings_growth = _num(info.get("earningsGrowth"))
    profit_margin = _num(info.get("profitMargins"))
    operating_margin = _num(info.get("operatingMargins"))
    roe = _num(info.get("returnOnEquity"))
    debt_to_equity = _num(info.get("debtToEquity"))

    metrics = {
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "peg_ratio": peg_ratio,
        "price_to_sales": price_to_sales,
        "price_to_book": price_to_book,
        "free_cash_flow_yield": fcf_yield,
        "revenue_growth": revenue_growth,
        "earnings_growth": earnings_growth,
        "profit_margin": profit_margin,
        "operating_margin": operating_margin,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "free_cashflow": free_cash_flow,
    }

    available = sum(1 for value in metrics.values() if value is not None)
    if available < 4:
        return FundamentalCheck(
            ticker=ticker,
            check_date=check_date,
            rating="Unknown",
            valuation_score=0,
            quality_score=0,
            summary="fundamental data unavailable or too sparse",
            metrics=metrics,
            raw=info,
        )

    valuation_score = sum(
        [
            _score_lower_better(forward_pe or trailing_pe, good=18, fair=30, poor=50),
            _score_lower_better(peg_ratio, good=1.2, fair=2.0, poor=3.0),
            _score_lower_better(price_to_sales, good=5, fair=10, poor=18),
            _score_lower_better(price_to_book, good=5, fair=10, poor=20),
            _score_higher_better(fcf_yield, good=0.05, fair=0.02, weak=0.0),
        ]
    )
    quality_score = sum(
        [
            _score_higher_better(revenue_growth, good=0.15, fair=0.05, weak=0.0),
            _score_higher_better(earnings_growth, good=0.15, fair=0.05, weak=0.0),
            _score_higher_better(profit_margin, good=0.18, fair=0.08, weak=0.0),
            _score_higher_better(operating_margin, good=0.20, fair=0.10, weak=0.0),
            _score_higher_better(roe, good=0.15, fair=0.08, weak=0.0),
            1 if debt_to_equity is None or debt_to_equity <= 150 else -1,
            1 if free_cash_flow is not None and free_cash_flow > 0 else -1,
        ]
    )
    rating = _rating(
        valuation_score,
        quality_score,
        fcf_yield=fcf_yield,
        free_cash_flow=free_cash_flow,
        debt_to_equity=debt_to_equity,
    )
    summary = (
        f"rating={rating}; valuation_score={valuation_score}; "
        f"quality_score={quality_score}; forward_pe={_fmt_ratio(forward_pe)}; "
        f"revenue_growth={_fmt_pct(revenue_growth)}; "
        f"operating_margin={_fmt_pct(operating_margin)}; "
        f"fcf_yield={_fmt_pct(fcf_yield)}"
    )

    return FundamentalCheck(
        ticker=ticker,
        check_date=check_date,
        rating=rating,
        valuation_score=valuation_score,
        quality_score=quality_score,
        summary=summary,
        metrics=metrics,
        raw=info,
    )


def check_fundamental(
    ticker: str,
    provider: InfoProvider = fetch_yfinance_info,
    check_date: str | None = None,
) -> FundamentalCheck:
    try:
        info = provider(ticker)
    except Exception as exc:
        return FundamentalCheck(
            ticker=ticker.upper(),
            check_date=check_date or date.today().isoformat(),
            rating="Unknown",
            valuation_score=0,
            quality_score=0,
            summary=f"fundamental fetch failed: {exc}",
            raw={"error": str(exc)},
        )
    return build_fundamental_check(ticker, info, check_date=check_date)


def update_fundamental_checks(
    repository,
    tickers: list[str],
    provider: InfoProvider = fetch_yfinance_info,
    dry_run: bool = False,
) -> list[FundamentalCheck]:
    results = []
    for ticker in sorted({item.upper() for item in tickers}):
        check = check_fundamental(ticker, provider=provider)
        results.append(check)
        if not dry_run:
            repository.upsert_fundamental_check(
                ticker=check.ticker,
                check_date=check.check_date,
                rating=check.rating,
                valuation_score=check.valuation_score,
                quality_score=check.quality_score,
                summary=check.summary,
                metrics=check.metrics,
                raw=check.raw,
            )
    return results
