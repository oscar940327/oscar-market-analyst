"""
sentiment_feed.py — 自訂 Backtrader Data Feed
擴充 PandasData，多加 sentiment_score 和 event_severity 兩條 lines。

關鍵：
- 繼承自 bt.feeds.PandasData
- 在 lines 裡宣告新欄位
- 在 params 裡告訴 Backtrader 怎麼從 DataFrame 找到這些欄位
"""
import backtrader as bt


class SentimentPandasData(bt.feeds.PandasData):
    """
    Backtrader 資料源，除了 OHLCV 之外還帶 sentiment 資訊。

    在策略裡可以這樣使用：
        self.data.sentiment_score[0]    # 當天的情緒分數
        self.data.event_severity[0]     # 當天的事件嚴重度
        self.data.close[0]              # 一般 OHLCV 也照常用
    """

    # 1. 宣告新增的 lines（欄位）
    lines = ("sentiment_score", "event_severity")

    # 2. 告訴 Backtrader 怎麼從 DataFrame 找到這些欄位
    #    -1 = autodetect by column name
    params = (
        ("sentiment_score", -1),
        ("event_severity", -1),
    )