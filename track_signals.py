"""
track_signals.py — 訊號品質追蹤工具

功能：
  1. 記錄每天的 BUY 訊號到 data/signal_log.csv
  2. 回填歷史訊號的 5日/10日/20日 追蹤價格
  3. 印出訊號品質統計

用法：
    python track_signals.py                    # 記錄今天 + 更新追蹤
    python track_signals.py --date 2026-04-14  # 回補特定日期的訊號
    python track_signals.py --stats-only       # 只看統計
"""
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

import yfinance as yf

LOG_FILE = ROOT / "data" / "signal_log.csv"
FIELDNAMES = [
    "date", "ticker", "signal", "score", "entry_price",
    "price_5d", "price_10d", "price_20d",
    "return_5d", "return_10d", "return_20d",
]


def ensure_log_exists():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
        print(f"  Created {LOG_FILE}")


def load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_log(rows: list[dict]):
    with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def record_signals_for_date(target_date: str):
    """
    對指定日期跑 signal_scanner，記錄 BUY 訊號。
    用 DB 裡的歷史價格資料重建那天的訊號狀態。
    """
    from pipeline.signal_scanner import scan_watchlist

    existing = load_log()
    existing_keys = {(r["date"], r["ticker"]) for r in existing}

    print(f"  Scanning signals for {target_date}...")
    signals = scan_watchlist()

    new_count = 0
    for sig in signals:
        if sig.action != "BUY":
            continue

        key = (target_date, sig.ticker)
        if key in existing_keys:
            continue

        score = sig.composite.total_score if sig.composite else 0
        score_label = sig.composite.signal.value if sig.composite else "N/A"

        row = {
            "date": target_date,
            "ticker": sig.ticker,
            "signal": f"BUY ({score_label})",
            "score": score,
            "entry_price": f"{sig.close_price:.2f}",
            "price_5d": "",
            "price_10d": "",
            "price_20d": "",
            "return_5d": "",
            "return_10d": "",
            "return_20d": "",
        }
        existing.append(row)
        new_count += 1
        print(f"    {sig.ticker} BUY @ ${sig.close_price:.2f} (score: {score})")

    if new_count == 0:
        print("    No BUY signals for this date.")
    else:
        # 按日期排序
        existing.sort(key=lambda r: (r["date"], r["ticker"]))
        save_log(existing)
        print(f"    Saved {new_count} signals")

    return new_count


def update_tracking_prices():
    """回填 5日/10日/20日 後的實際價格"""
    rows = load_log()
    if not rows:
        print("  No signals to track yet.")
        return

    today = datetime.now()
    tickers_needed = set()
    for row in rows:
        if not row["price_5d"] or not row["price_10d"] or not row["price_20d"]:
            tickers_needed.add(row["ticker"])

    if not tickers_needed:
        print("  All tracking prices already filled.")
        return

    print(f"  Fetching prices for {len(tickers_needed)} tickers...")
    price_cache = {}
    for ticker in tickers_needed:
        try:
            df = yf.download(ticker, period="60d", progress=False)
            if not df.empty:
                if hasattr(df.columns, 'levels'):
                    df.columns = df.columns.get_level_values(0)
                close_series = df["Close"]
                price_cache[ticker] = {
                    d.strftime("%Y-%m-%d"): float(v)
                    for d, v in close_series.items()
                }
        except Exception as e:
            print(f"    {ticker}: fetch failed: {e}")

    updated = 0
    for row in rows:
        entry_date = datetime.strptime(row["date"], "%Y-%m-%d")
        entry_price = float(row["entry_price"])
        ticker = row["ticker"]

        if ticker not in price_cache:
            continue

        prices = price_cache[ticker]

        for days, price_field, return_field in [
            (5, "price_5d", "return_5d"),
            (10, "price_10d", "return_10d"),
            (20, "price_20d", "return_20d"),
        ]:
            if row[price_field]:
                continue

            target_date = entry_date + timedelta(days=days)
            if target_date > today:
                continue

            for offset in range(0, 5):
                check = (target_date + timedelta(days=offset)).strftime("%Y-%m-%d")
                if check in prices:
                    tracked_price = prices[check]
                    ret = (tracked_price / entry_price - 1) * 100
                    row[price_field] = f"{tracked_price:.2f}"
                    row[return_field] = f"{ret:+.2f}%"
                    updated += 1
                    break

    if updated > 0:
        save_log(rows)
        print(f"  Updated {updated} tracking prices")
    else:
        print("  No prices to update yet (signals too recent)")


def print_stats():
    rows = load_log()
    if not rows:
        print("\nNo signal data yet.")
        return

    total = len(rows)
    has_10d = [r for r in rows if r["return_10d"]]

    print(f"\n{'='*60}")
    print(f"Signal Quality Report")
    print(f"{'='*60}")
    print(f"Total signals recorded: {total}")
    print(f"Signals with 10-day tracking: {len(has_10d)}")

    if not has_10d:
        print("\nNeed at least 10 days of data. Keep running daily!")
        return

    wins_10d = [r for r in has_10d if float(r["return_10d"].replace("%", "").replace("+", "")) > 0]
    win_rate = len(wins_10d) / len(has_10d) * 100
    avg_return = sum(float(r["return_10d"].replace("%", "").replace("+", "")) for r in has_10d) / len(has_10d)

    print(f"\n-- Overall (10-day) --")
    print(f"  Win rate:     {win_rate:.1f}% ({len(wins_10d)}/{len(has_10d)})")
    print(f"  Avg return:   {avg_return:+.2f}%")

    for label, subset in [
        ("Score 60+ (Buy/Strong Buy)", [r for r in has_10d if int(r["score"]) >= 60]),
        ("Score 50-59 (Hold)", [r for r in has_10d if 50 <= int(r["score"]) < 60]),
        ("Score < 50 (Wait/Sell)", [r for r in has_10d if int(r["score"]) < 50]),
    ]:
        if not subset:
            continue
        s_wins = [r for r in subset if float(r["return_10d"].replace("%", "").replace("+", "")) > 0]
        s_rate = len(s_wins) / len(subset) * 100
        s_avg = sum(float(r["return_10d"].replace("%", "").replace("+", "")) for r in subset) / len(subset)
        print(f"\n-- {label} ({len(subset)} signals) --")
        print(f"  Win rate:     {s_rate:.1f}% ({len(s_wins)}/{len(subset)})")
        print(f"  Avg return:   {s_avg:+.2f}%")

    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None,
                        help="Record signals for specific date (YYYY-MM-DD)")
    parser.add_argument("--stats-only", action="store_true")
    args = parser.parse_args()

    ensure_log_exists()

    if not args.stats_only:
        target = args.date or datetime.now().strftime("%Y-%m-%d")
        record_signals_for_date(target)
        print()
        update_tracking_prices()

    print_stats()