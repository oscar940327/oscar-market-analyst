"""
llm_scorer.py — LLM 情緒評分器
Phase 2.1 修正：
1. 加自動重試（503 過載自動等 5 秒再試）
2. JSON 欄位順序改為 reasoning 在前，強迫 LLM 先寫理由
3. 加詳細的失敗除錯訊息
"""
import os
import json
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class SentimentResult:
    sentiment_score: float
    event_severity: float
    reasoning: str


# ===== Prompt =====
# 關鍵：reasoning 放第一個，強迫 LLM 先寫理由再給分數
SYSTEM_PROMPT = """You are a quantitative sentiment scoring engine for a stock trading system. Read news articles and output ONLY a JSON object. No markdown, no explanation, no preamble.

CRITICAL: The JSON must contain ALL THREE fields IN THIS ORDER: reasoning, sentiment_score, event_severity. The `reasoning` field MUST be a non-empty string explaining your analysis.

SCORING RULES:

reasoning: REQUIRED. One sentence (max 30 words) explaining your score, referencing specific facts from the news.

sentiment_score: Float from -1.0 to 1.0
  +1.0 = Extremely bullish (blowout earnings, FDA approval, massive contract win)
  +0.5 = Moderately positive (good earnings, analyst upgrades, sector tailwinds)
   0.0 = Neutral or mixed signals
  -0.5 = Moderately negative (earnings miss, downgrades, technical breakdown)
  -1.0 = Extremely bearish (fraud, CEO arrested, bankruptcy risk, major recall)

event_severity: Float from 0.0 to 1.0
  0.0 = No significant event, normal market noise
  0.3 = Minor event (analyst opinion change, small product update)
  0.6 = Notable event (earnings report, regulatory decision, major partnership)
  0.9 = Critical event (CEO indicted, data breach, key drug failure)
  1.0 = Existential threat to the company

OUTPUT FORMAT (strict JSON, fields in this exact order):
{"reasoning": "<one sentence explaining the score>", "sentiment_score": <float>, "event_severity": <float>}"""


def _build_user_prompt(ticker: str, news_text: str, price_context: str = "") -> str:
    return f"""Score the news for {ticker}. Output JSON with reasoning FIRST.

{f"PRICE CONTEXT: {price_context}" if price_context else ""}

NEWS:
{news_text}

Output the JSON now (reasoning must be non-empty):"""


def _patch_truncated_json(raw: str) -> Optional[dict]:
    """嘗試修復被截斷的 JSON"""
    last_comma = raw.rfind(",")
    if last_comma > 0:
        patched = raw[:last_comma] + "}"
        try:
            return json.loads(patched)
        except json.JSONDecodeError:
            return None
    return None


def _call_llm_once(model: str, kwargs: dict) -> str:
    """呼叫一次 LLM，回傳原始字串"""
    import litellm
    response = litellm.completion(**kwargs)
    return response.choices[0].message.content.strip()


def score_sentiment(
    ticker: str,
    news_text: str,
    price_context: str = "",
    model: Optional[str] = None,
    max_retries: int = 3,
) -> SentimentResult:
    """
    呼叫 LLM 對新聞做情緒評分。
    遇到 503 過載會自動等 5 秒重試，最多 3 次。
    """
    try:
        import litellm  # noqa
    except ImportError:
        print("  ⚠️ litellm not installed. Run: pip install litellm")
        return SentimentResult(0.0, 0.0, "LLM unavailable")

    if model is None:
        model = os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash")

    user_prompt = _build_user_prompt(ticker, news_text, price_context)

    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }
    
    if "openrouter" in model:
        kwargs["api_key"] = os.getenv("OPENROUTER_API_KEY")
    elif "gemini" in model:
        kwargs["api_key"] = os.getenv("GEMINI_API_KEY")
    elif "openai" in model or "deepseek" in model:
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")

    raw = ""
    last_error = None

    # ===== 重試迴圈 =====
    for attempt in range(1, max_retries + 1):
        try:
            raw = _call_llm_once(model, kwargs)
            break  # 成功就跳出
        except Exception as e:
            err_str = str(e)
            last_error = err_str

            # 503 過載 → 等等再試
            if "503" in err_str or "UNAVAILABLE" in err_str or "overloaded" in err_str.lower():
                if attempt < max_retries:
                    wait = 5 * attempt
                    print(f"  ⏳ {ticker}: Gemini overloaded, retry {attempt}/{max_retries} in {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    print(f"  ❌ {ticker}: Gemini still overloaded after {max_retries} retries")
                    return SentimentResult(0.0, 0.0, f"Gemini 503 (retried {max_retries}x)")
            else:
                # 非 503 錯誤直接放棄
                print(f"  ⚠️ {ticker}: LLM error: {err_str[:150]}")
                return SentimentResult(0.0, 0.0, f"LLM error: {err_str[:100]}")

    if not raw:
        return SentimentResult(0.0, 0.0, f"No response: {last_error}")

    # ===== 解析 JSON =====
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = _patch_truncated_json(raw)
        if data is None:
            print(f"  ⚠️ {ticker}: JSON unparseable, raw: {raw[:200]}")
            return SentimentResult(0.0, 0.0, "Parse failed")

    reasoning = str(data.get("reasoning", "")).strip()
    if not reasoning:
        reasoning = "(LLM omitted reasoning despite prompt)"

    return SentimentResult(
        sentiment_score=max(-1.0, min(1.0, float(data.get("sentiment_score", 0)))),
        event_severity=max(0.0, min(1.0, float(data.get("event_severity", 0)))),
        reasoning=reasoning[:200],
    )