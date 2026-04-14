"""
composite_scorer.py — 6 維度綜合技術評分系統

參考 daily_stock_analysis 的設計，用 6 個維度給每檔股票評 0-100 分：

  1. 趨勢狀態 (30 分)：MA5/MA10/MA20 排列
  2. 乖離率   (20 分)：價格距離 MA5 的偏離程度
  3. 量能     (15 分)：縮量回調最佳，放量下跌最差
  4. 均線支撐 (10 分)：MA5/MA10 是否有效支撐
  5. MACD     (15 分)：金叉死叉狀態
  6. RSI      (10 分)：超買超賣判斷

總分對應信號：
  75-100  強烈買入
  60-74   買入
  45-59   持有
  30-44   觀望
  < 30    賣出
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd
import numpy as np


class TrendStatus(str, Enum):
    STRONG_BULL = "強勢多頭"
    BULL = "多頭排列"
    WEAK_BULL = "弱勢多頭"
    CONSOLIDATION = "盤整"
    WEAK_BEAR = "弱勢空頭"
    BEAR = "空頭排列"
    STRONG_BEAR = "強勢空頭"


class VolumeStatus(str, Enum):
    HEAVY_VOLUME_UP = "放量上漲"
    HEAVY_VOLUME_DOWN = "放量下跌"
    SHRINK_VOLUME_UP = "縮量上漲"
    SHRINK_VOLUME_DOWN = "縮量回調"
    NORMAL = "量能正常"


class MACDStatus(str, Enum):
    GOLDEN_CROSS_ZERO = "零軸上金叉"
    GOLDEN_CROSS = "金叉"
    BULLISH = "多頭"
    CROSSING_UP = "上穿零軸"
    CROSSING_DOWN = "下穿零軸"
    BEARISH = "空頭"
    DEATH_CROSS = "死叉"


class RSIStatus(str, Enum):
    OVERBOUGHT = "超買"
    STRONG_BUY = "強勢買入"
    NEUTRAL = "中性"
    WEAK = "弱勢"
    OVERSOLD = "超賣"


class BuySignal(str, Enum):
    STRONG_BUY = "強烈買入"
    BUY = "買入"
    HOLD = "持有"
    WAIT = "觀望"
    SELL = "賣出"
    STRONG_SELL = "強烈賣出"


@dataclass
class CompositeScore:
    """單一股票的綜合評分結果"""
    ticker: str
    current_price: float
    
    # 各維度分數
    trend_score: int = 0          # 0-30
    bias_score: int = 0           # 0-20
    volume_score: int = 0         # 0-15
    support_score: int = 0        # 0-10
    macd_score: int = 0           # 0-15
    rsi_score: int = 0            # 0-10
    
    total_score: int = 0          # 0-100
    signal: BuySignal = BuySignal.WAIT
    
    # 各維度狀態（給 email 顯示用）
    trend_status: TrendStatus = TrendStatus.CONSOLIDATION
    volume_status: VolumeStatus = VolumeStatus.NORMAL
    macd_status: MACDStatus = MACDStatus.BULLISH
    rsi_status: RSIStatus = RSIStatus.NEUTRAL
    
    # 數值
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    bias_ma5: float = 0.0         # 乖離率（百分比）
    rsi_value: float = 0.0
    macd_value: float = 0.0
    
    # 加分理由 / 風險警告
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """計算所有技術指標：MA、MACD、RSI"""
    df = df.copy()
    
    # 均線
    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA10'] = df['close'].rolling(window=10).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()
    
    # MACD (12, 26, 9)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = ema12 - ema26
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD'] = (df['DIF'] - df['DEA']) * 2
    
    # RSI (14)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 量能比（當日量 / 5 日均量）
    df['vol_ma5'] = df['volume'].rolling(window=5).mean()
    df['vol_ratio'] = df['volume'] / df['vol_ma5']
    
    return df


def _analyze_trend(latest: pd.Series, result: CompositeScore) -> None:
    """分析趨勢狀態並給分（30 分）"""
    ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
    
    if ma5 > ma10 > ma20:
        # 多頭排列
        gap_5_10 = (ma5 - ma10) / ma10 * 100
        gap_10_20 = (ma10 - ma20) / ma20 * 100
        if gap_5_10 > 1.5 and gap_10_20 > 2:
            result.trend_status = TrendStatus.STRONG_BULL
            result.trend_score = 30
            result.reasons.append("✅ 強勢多頭排列，順勢做多")
        else:
            result.trend_status = TrendStatus.BULL
            result.trend_score = 26
            result.reasons.append("✅ 多頭排列")
    elif ma5 > ma10 and ma10 < ma20:
        result.trend_status = TrendStatus.WEAK_BULL
        result.trend_score = 18
    elif ma5 < ma10 and ma10 > ma20:
        result.trend_status = TrendStatus.WEAK_BEAR
        result.trend_score = 8
    elif ma5 < ma10 < ma20:
        gap_5_10 = (ma10 - ma5) / ma5 * 100
        gap_10_20 = (ma20 - ma10) / ma10 * 100
        if gap_5_10 > 1.5 and gap_10_20 > 2:
            result.trend_status = TrendStatus.STRONG_BEAR
            result.trend_score = 0
            result.risks.append("⚠️ 強勢空頭排列，不宜做多")
        else:
            result.trend_status = TrendStatus.BEAR
            result.trend_score = 4
            result.risks.append("⚠️ 空頭排列")
    else:
        result.trend_status = TrendStatus.CONSOLIDATION
        result.trend_score = 12


def _analyze_bias(result: CompositeScore, bias_threshold: float = 5.0) -> None:
    """乖離率評分（20 分）"""
    bias = result.bias_ma5
    
    if bias < 0:
        # 價格在 MA5 下方（回踩）
        if bias > -3:
            result.bias_score = 20
            result.reasons.append(f"✅ 略低於MA5({bias:+.1f}%)，回踩買點")
        elif bias > -5:
            result.bias_score = 16
            result.reasons.append(f"✅ 回踩MA5({bias:+.1f}%)，觀察支撐")
        else:
            result.bias_score = 8
            result.risks.append(f"⚠️ 乖離率過大({bias:+.1f}%)，可能破位")
    elif bias < 2:
        result.bias_score = 18
        result.reasons.append(f"✅ 貼近MA5({bias:+.1f}%)，介入好時機")
    elif bias < bias_threshold:
        result.bias_score = 14
        result.reasons.append(f"⚡ 略高於MA5({bias:+.1f}%)，可小倉介入")
    else:
        result.bias_score = 4
        result.risks.append(f"❌ 乖離率過高({bias:+.1f}%)，嚴禁追高")


def _analyze_volume(df: pd.DataFrame, result: CompositeScore) -> None:
    """量能評分（15 分）"""
    if len(df) < 5:
        result.volume_score = 8
        result.volume_status = VolumeStatus.NORMAL
        return
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    vol_ratio = float(latest.get('vol_ratio', 1.0))
    price_up = latest['close'] > prev['close']
    
    SHRINK = 0.7
    HEAVY = 1.5
    
    if vol_ratio < SHRINK and not price_up:
        result.volume_status = VolumeStatus.SHRINK_VOLUME_DOWN
        result.volume_score = 15
        result.reasons.append("✅ 縮量回調，主力洗盤")
    elif vol_ratio > HEAVY and price_up:
        result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
        result.volume_score = 12
        result.reasons.append("✅ 放量上漲，量價齊升")
    elif vol_ratio > HEAVY and not price_up:
        result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
        result.volume_score = 0
        result.risks.append("⚠️ 放量下跌，注意風險")
    elif vol_ratio < SHRINK and price_up:
        result.volume_status = VolumeStatus.SHRINK_VOLUME_UP
        result.volume_score = 6
    else:
        result.volume_status = VolumeStatus.NORMAL
        result.volume_score = 10


def _analyze_support(latest: pd.Series, result: CompositeScore) -> None:
    """支撐評分（10 分）"""
    close = result.current_price
    low = float(latest['low'])
    tolerance = 0.02
    
    # MA5 支撐：當天最低價接觸 MA5 但收盤站穩
    if abs(low - result.ma5) / result.ma5 < tolerance and close >= result.ma5:
        result.support_score += 5
        result.reasons.append("✅ MA5支撐有效")
    
    # MA10 支撐
    if abs(low - result.ma10) / result.ma10 < tolerance and close >= result.ma10:
        result.support_score += 5
        result.reasons.append("✅ MA10支撐有效")


def _analyze_macd(df: pd.DataFrame, result: CompositeScore) -> None:
    """MACD 評分（15 分）"""
    if len(df) < 27:
        result.macd_score = 5
        return
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    dif_now = float(latest['DIF'])
    dea_now = float(latest['DEA'])
    dif_prev = float(prev['DIF'])
    dea_prev = float(prev['DEA'])
    
    result.macd_value = dif_now - dea_now
    
    # 判斷狀態
    golden_cross = dif_prev < dea_prev and dif_now > dea_now
    death_cross = dif_prev > dea_prev and dif_now < dea_now
    
    if golden_cross and dif_now > 0:
        result.macd_status = MACDStatus.GOLDEN_CROSS_ZERO
        result.macd_score = 15
        result.reasons.append("✅ MACD 零軸上金叉，最強買點")
    elif golden_cross:
        result.macd_status = MACDStatus.GOLDEN_CROSS
        result.macd_score = 12
        result.reasons.append("✅ MACD 金叉")
    elif dif_prev < 0 and dif_now > 0:
        result.macd_status = MACDStatus.CROSSING_UP
        result.macd_score = 10
        result.reasons.append("✅ MACD 上穿零軸")
    elif dif_now > dea_now and dif_now > 0:
        result.macd_status = MACDStatus.BULLISH
        result.macd_score = 8
    elif death_cross:
        result.macd_status = MACDStatus.DEATH_CROSS
        result.macd_score = 0
        result.risks.append("⚠️ MACD 死叉")
    elif dif_prev > 0 and dif_now < 0:
        result.macd_status = MACDStatus.CROSSING_DOWN
        result.macd_score = 0
        result.risks.append("⚠️ MACD 下穿零軸")
    else:
        result.macd_status = MACDStatus.BEARISH
        result.macd_score = 2


def _analyze_rsi(latest: pd.Series, result: CompositeScore) -> None:
    """RSI 評分（10 分）"""
    rsi = float(latest['RSI']) if not pd.isna(latest['RSI']) else 50.0
    result.rsi_value = rsi
    
    if rsi > 70:
        result.rsi_status = RSIStatus.OVERBOUGHT
        result.rsi_score = 0
        result.risks.append(f"⚠️ RSI 超買 ({rsi:.0f})")
    elif rsi >= 50:
        result.rsi_status = RSIStatus.STRONG_BUY
        result.rsi_score = 8
        result.reasons.append(f"✅ RSI 強勢區 ({rsi:.0f})")
    elif rsi >= 40:
        result.rsi_status = RSIStatus.NEUTRAL
        result.rsi_score = 5
    elif rsi >= 30:
        result.rsi_status = RSIStatus.WEAK
        result.rsi_score = 3
    else:
        result.rsi_status = RSIStatus.OVERSOLD
        result.rsi_score = 10
        result.reasons.append(f"✅ RSI 超賣 ({rsi:.0f})，反彈機會")


def _generate_signal(result: CompositeScore) -> None:
    """根據總分產生最終信號"""
    score = result.total_score
    
    if score >= 75 and result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
        result.signal = BuySignal.STRONG_BUY
    elif score >= 60 and result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL, TrendStatus.WEAK_BULL]:
        result.signal = BuySignal.BUY
    elif score >= 45:
        result.signal = BuySignal.HOLD
    elif score >= 30:
        result.signal = BuySignal.WAIT
    elif result.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
        result.signal = BuySignal.STRONG_SELL
    else:
        result.signal = BuySignal.SELL


def compute_composite_score(ticker: str, df: pd.DataFrame) -> Optional[CompositeScore]:
    """
    對單檔股票計算 6 維度綜合評分。
    
    Args:
        ticker: 股票代碼
        df: OHLCV DataFrame，至少要 27 天才能算出完整 MACD
    
    Returns:
        CompositeScore 或 None（資料不足時）
    """
    if df is None or df.empty or len(df) < 27:
        return None
    
    df = df.sort_index()
    df = _calculate_indicators(df)
    
    latest = df.iloc[-1]
    
    result = CompositeScore(
        ticker=ticker,
        current_price=float(latest['close']),
        ma5=float(latest['MA5']),
        ma10=float(latest['MA10']),
        ma20=float(latest['MA20']),
        bias_ma5=float((latest['close'] - latest['MA5']) / latest['MA5'] * 100),
    )
    
    _analyze_trend(latest, result)
    _analyze_bias(result)
    _analyze_volume(df, result)
    _analyze_support(latest, result)
    _analyze_macd(df, result)
    _analyze_rsi(latest, result)
    
    result.total_score = (
        result.trend_score
        + result.bias_score
        + result.volume_score
        + result.support_score
        + result.macd_score
        + result.rsi_score
    )
    
    _generate_signal(result)
    
    return result


if __name__ == "__main__":
    # 簡單測試
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    
    from pipeline.db import get_connection, load_prices
    
    conn = get_connection()
    for ticker in ["TSLA", "NVDA", "AAPL"]:
        df = load_prices(conn, ticker)
        if df.empty:
            print(f"{ticker}: no data")
            continue
        
        score = compute_composite_score(ticker, df)
        if score is None:
            print(f"{ticker}: insufficient data")
            continue
        
        print(f"\n{'='*50}")
        print(f"{ticker}: {score.signal.value} ({score.total_score}/100)")
        print(f"{'='*50}")
        print(f"  Price: ${score.current_price:.2f}")
        print(f"  Trend: {score.trend_status.value} ({score.trend_score}/30)")
        print(f"  Bias:  {score.bias_ma5:+.2f}% ({score.bias_score}/20)")
        print(f"  Vol:   {score.volume_status.value} ({score.volume_score}/15)")
        print(f"  Sup:   {score.support_score}/10")
        print(f"  MACD:  {score.macd_status.value} ({score.macd_score}/15)")
        print(f"  RSI:   {score.rsi_value:.0f} ({score.rsi_status.value}) ({score.rsi_score}/10)")
        if score.reasons:
            print(f"  ✅ {' / '.join(score.reasons)}")
        if score.risks:
            print(f"  ⚠️ {' / '.join(score.risks)}")
    
    conn.close()