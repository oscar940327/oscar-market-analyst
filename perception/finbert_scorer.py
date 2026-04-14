"""
finbert_scorer.py — 用 FinBERT 做情緒評分（本地模型、免費、決定性）

為什麼用 FinBERT：
- 專門在金融新聞上 fine-tune 過，比通用 LLM 準
- 本地模型，零延遲、零成本
- 決定性輸出（同樣輸入 → 同樣結果），解決 LLM 的雜訊問題

模型：ProsusAI/finbert（Hugging Face 上下載次數最多的金融 sentiment 模型）

輸出跟 llm_scorer.SentimentResult 介面相容，可以無痛替換：
- sentiment_score: -1 ~ 1
- event_severity: 0 ~ 1
- reasoning: 統計式的描述（不像 LLM 那麼人類可讀，但還是有資訊）

使用：
    from perception.finbert_scorer import score_sentiment_finbert
    result = score_sentiment_finbert("TSLA", news_items)
    print(result.sentiment_score, result.event_severity, result.reasoning)
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class SentimentResult:
    """跟 llm_scorer.SentimentResult 介面相容"""
    sentiment_score: float
    event_severity: float
    reasoning: str


# ===== 全域模型實例（lazy load）=====
_finbert_pipeline = None


def _get_pipeline():
    """第一次呼叫時才下載/載入模型，之後快取重用"""
    global _finbert_pipeline
    if _finbert_pipeline is None:
        try:
            from transformers import pipeline
        except ImportError:
            raise ImportError(
                "transformers not installed. Run: pip install transformers torch"
            )

        print("  📥 Loading FinBERT model (first time only, ~450MB)...")
        _finbert_pipeline = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            device=-1,  # CPU；要用 GPU 改成 0
        )
        print("  ✅ FinBERT loaded")
    return _finbert_pipeline


def score_sentiment_finbert(
    ticker: str,
    news_items: list[Any],
) -> SentimentResult:
    """
    對一組新聞做情緒評分。

    Args:
        ticker: 股票代碼（只為了 reasoning 裡顯示用）
        news_items: HistoricalNewsItem 或 NewsItem 列表，需要有 headline 或 title 屬性

    演算法：
        1. 對每篇新聞跑 FinBERT，得 (positive, neutral, negative) 機率
        2. 單篇分數 = positive_prob - negative_prob（範圍 -1 ~ 1）
        3. 當日 sentiment_score = 所有單篇分數的平均
        4. 當日 event_severity = 所有單篇分數絕對值的最大值
           （邏輯：如果今天有任何一篇超極端，severity 就高）
    """
    if not news_items:
        return SentimentResult(0.0, 0.0, "(no news)")

    # 提取每篇的標題（HistoricalNewsItem 用 headline、NewsItem 用 title）
    texts = []
    for item in news_items:
        text = getattr(item, "headline", None) or getattr(item, "title", "")
        if text:
            # FinBERT 的 max length 是 512 tokens，截短避免爆炸
            texts.append(text[:300])

    if not texts:
        return SentimentResult(0.0, 0.0, "(no valid news text)")

    try:
        pipe = _get_pipeline()
        # 一次批次處理所有新聞
        results = pipe(texts, truncation=True, max_length=512)
    except Exception as e:
        print(f"  ⚠️ {ticker}: FinBERT error: {e}")
        return SentimentResult(0.0, 0.0, f"FinBERT error: {str(e)[:100]}")

    # 每篇轉成 -1 ~ 1 的分數
    per_article_scores = []
    pos_count = 0
    neg_count = 0
    neu_count = 0

    for r in results:
        label = r["label"].lower()
        score = r["score"]

        if label == "positive":
            per_article_scores.append(score)
            pos_count += 1
        elif label == "negative":
            per_article_scores.append(-score)
            neg_count += 1
        else:  # neutral
            per_article_scores.append(0.0)
            neu_count += 1

    n = len(per_article_scores)

    # 當日總分 = 平均
    avg_score = sum(per_article_scores) / n if n > 0 else 0.0

    # severity = 最極端那篇的絕對值
    # 這樣設計是因為：如果今天有 1 篇超負面 + 10 篇中性，
    # severity 要高（代表「今天有大事」），而不是被 10 篇中性平均掉
    max_abs = max(abs(s) for s in per_article_scores) if per_article_scores else 0.0

    # 限制範圍
    avg_score = max(-1.0, min(1.0, avg_score))
    severity = max(0.0, min(1.0, max_abs))

    # reasoning 是統計描述（不像 LLM 那樣人類可讀，但還是有用）
    reasoning = (
        f"FinBERT: {pos_count} positive, {neu_count} neutral, {neg_count} negative "
        f"out of {n} articles (avg={avg_score:+.2f}, max_severity={severity:.2f})"
    )

    return SentimentResult(
        sentiment_score=round(avg_score, 3),
        event_severity=round(severity, 3),
        reasoning=reasoning,
    )


if __name__ == "__main__":
    # 小測試
    from dataclasses import dataclass

    @dataclass
    class FakeNews:
        headline: str

    samples = [
        FakeNews("Tesla smashes Q4 earnings, delivers record profit"),
        FakeNews("NVIDIA unveils breakthrough Blackwell Ultra chip"),
        FakeNews("Tesla faces SEC investigation over Autopilot safety"),
        FakeNews("Analysts downgrade Tesla citing demand concerns"),
        FakeNews("Apple reports quarterly results in line with estimates"),
    ]

    result = score_sentiment_finbert("TEST", samples)
    print(f"\nScore:    {result.sentiment_score:+.2f}")
    print(f"Severity: {result.event_severity:.2f}")
    print(f"Reason:   {result.reasoning}")