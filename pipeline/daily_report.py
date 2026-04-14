"""
daily_report.py — Phase 5 主流程入口
手動跑這個檔案就會：
    1. 跑 ETL 更新今天的價格 + sentiment + market_regime
    2. 掃描 watchlist 產生交易訊號
    3. 產生 HTML 報告
    4. 寄到你的 Gmail

使用：
    python pipeline/daily_report.py              # 跑完整流程
    python pipeline/daily_report.py --no-email   # 只產生報告，不寄信
    python pipeline/daily_report.py --no-etl     # 跳過 ETL（用現有 DB 資料）
    python pipeline/daily_report.py --preview    # 把 HTML 存成檔案 + 不寄信
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

from pipeline.etl import run_etl
from pipeline.signal_scanner import scan_watchlist
from pipeline.report_builder import build_html_report
from pipeline.email_sender import send_html_email
from perception.market_regime import calculate_market_regime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true", help="不寄信，只產生報告")
    parser.add_argument("--no-etl", action="store_true", help="跳過 ETL，用現有 DB 資料")
    parser.add_argument("--preview", action="store_true", help="把 HTML 存成檔案（不寄信）")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"📊 Oscar Market Analyst — Daily Report {today}")
    print(f"{'='*60}\n")

    # ===== Step 1: ETL =====
    if not args.no_etl:
        print("🔄 Step 1: Running ETL (prices + sentiment + regime)...\n")
        try:
            run_etl()
        except Exception as e:
            print(f"⚠️ ETL failed: {e}")
            print("   Continuing with existing DB data...")
    else:
        print("⏭️  Skipping ETL (--no-etl flag)\n")

    # ===== Step 2: 算 market regime =====
    print("\n📊 Step 2: Computing market regime...")
    try:
        regime, regime_info = calculate_market_regime()
        print(f"   Regime: {regime.upper()}")
    except Exception as e:
        print(f"⚠️ Regime calc failed: {e}")
        regime = "neutral"
        regime_info = {}

    # ===== Step 3: 掃描訊號 =====
    print("\n🔍 Step 3: Scanning watchlist for signals...")
    signals = scan_watchlist()

    buy_count = sum(1 for s in signals if s.action == "BUY")
    emergency_count = sum(1 for s in signals if s.action == "EMERGENCY_EXIT")
    filtered_count = sum(1 for s in signals if s.action == "FILTERED")
    print(f"   Found: {buy_count} BUY, {emergency_count} EMERGENCY, "
          f"{filtered_count} FILTERED")

    # ===== Step 4: 產生 HTML =====
    print("\n📝 Step 4: Building HTML report...")
    html = build_html_report(
        signals=signals,
        regime=regime,
        regime_info=regime_info,
        report_date=today,
    )

    # ===== Step 5: 輸出 =====
    if args.preview or args.no_email:
        # 存成檔案
        report_dir = ROOT / "report"
        report_dir.mkdir(parentos=True, exist_ok=True)
        output_path = report_dir / f"report_{today}.html"
        output_path.write_text(html, encoding="utf-8")
        print(f"\n💾 Report saved to: {output_path}")
        print(f"   Open with browser to preview")
        return

    # 寄信
    print("\n📧 Step 5: Sending email...")
    # 決定主旨：根據是否有 urgent 訊號
    if emergency_count > 0:
        subject = f"🚨 [URGENT] Oscar — {today} ({emergency_count} 緊急平倉)"
    elif buy_count > 0:
        subject = f"🟢 Oscar — {today} ({buy_count} 進場訊號)"
    else:
        subject = f"📊 Oscar — {today} (無訊號)"

    success = send_html_email(subject=subject, html_body=html)

    if success:
        print(f"\n✅ Daily report complete.")
    else:
        # 寄信失敗時，自動存成檔案 fallback
        fallback = report_dir / f"report_{today}_failed_to_send.html"
        fallback.write_text(html, encoding="utf-8")
        print(f"   Report saved to fallback: {fallback}")


if __name__ == "__main__":
    main()
    