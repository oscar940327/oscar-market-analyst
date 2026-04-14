"""臨時測試：確認 Polygon 歷史新聞到底能抓多久"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")

from perception.historical_news_fetcher import fetch_historical_news

# 測試幾個時間點
test_ranges = [
    ("2024-01-01", "2024-01-10"),   # 2 年前
    ("2023-01-01", "2023-01-10"),   # 3 年前
    ("2022-06-01", "2022-06-10"),   # 熊市中段
    ("2022-01-01", "2022-01-10"),   # 熊市開始
]

for from_date, to_date in test_ranges:
    print(f"\n{'='*55}")
    print(f"Testing: {from_date} ~ {to_date}")
    print(f"{'='*55}")
    
    news = fetch_historical_news(
        "TSLA", 
        from_date=from_date, 
        to_date=to_date,
        fetch_all_pages=False,  # 只抓第一頁，測試用
    )
    
    if news:
        print(f"  ✅ Got {len(news)} articles")
        print(f"  Oldest: {news[0].date}")
        print(f"  Newest: {news[-1].date}")
        print(f"  Sample: {news[0].headline[:80]}")
    else:
        print(f"  ❌ No articles found for this range")