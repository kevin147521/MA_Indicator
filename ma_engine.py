#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
ma_engine.py — 均線計算與預測引擎（純函式，Streamlit 與 notebook 都能呼叫）

設計原則：
1. 純函式，不依賴 Streamlit 與 finlab，方便測試與重用。
2. 預測「下個交易日」收盤後均線 = (現況均線 × N - 最早一日收盤 + 預測收盤) / N
   這是 SMA 數學定義的直接推導。
3. 判定門檻 ±0.3% 可調，預設對台股小型雜訊有合理容忍度。
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Dict, List


# === 預設均線週期 ===
DEFAULT_MA_WINDOWS = [5, 10, 20, 60]

# === 預設「持平」容忍門檻（百分比） ===
DEFAULT_FLAT_THRESHOLD_PCT = 0.3


@dataclass
class MAStatus:
    """單條均線的現況與預測狀態"""
    window: int
    current_value: float          # 現況均線（含今日收盤）
    predicted_value: float        # 預測下個交易日收盤後的均線
    delta: float                  # predicted - current
    delta_pct: float              # (predicted / current - 1) * 100
    status: str                   # "起漲" / "持平" / "跌破"
    color: str                    # 顯示用顏色
    emoji: str                    # 顯示用 emoji


@dataclass
class MAPredictionResult:
    """整體預測結果"""
    stock_id: str
    stock_name: str
    last_close: float             # 最後一日收盤
    last_date: pd.Timestamp       # 最後一日日期
    predicted_close: float        # 預測下個交易日收盤
    mas: Dict[int, MAStatus] = field(default_factory=dict)
    overall_signal: str = ""      # "偏多" / "偏空" / "盤整"
    overall_score: int = 0        # -N ~ +N，+ 代表起漲方向數 - 跌破方向數


def _classify(delta_pct: float, threshold: float) -> tuple[str, str, str]:
    """根據變化百分比回傳 (狀態中文, 顏色, emoji)"""
    if delta_pct > threshold:
        return "起漲", "#26a69a", "🟢"
    elif delta_pct < -threshold:
        return "跌破", "#ef5350", "🔴"
    else:
        return "持平", "#ffb300", "🟡"


def calc_sma_series(close: pd.Series, window: int) -> pd.Series:
    """計算 SMA 時序（pandas 內建 rolling.mean 包裝，方便測試）"""
    return close.rolling(window=window, min_periods=window).mean()


def predict_next_sma(
    close: pd.Series,
    window: int,
    predicted_next_close: float,
) -> tuple[float, float]:
    """
    預測下個交易日收盤後的 SMA(window)

    數學：
        SMA_N(明天含預測) = (SMA_N(今天) * N - close[t-N+1] + predicted_next_close) / N

    回傳 (current_sma, predicted_sma)
    """
    if len(close) < window:
        raise ValueError(f"資料長度 {len(close)} 不足以計算 SMA({window})")

    current_sma = float(close.iloc[-window:].mean())
    oldest = float(close.iloc[-window])  # 視窗內最舊那一根
    predicted_sma = (current_sma * window - oldest + predicted_next_close) / window
    return current_sma, predicted_sma


def predict_all_ma(
    close: pd.Series,
    last_date: pd.Timestamp,
    last_close: float,
    predicted_next_close: float,
    stock_id: str = "",
    stock_name: str = "",
    windows: List[int] = None,
    flat_threshold_pct: float = DEFAULT_FLAT_THRESHOLD_PCT,
) -> MAPredictionResult:
    """
    一次算完所有均線（含現況 + 預測 + 判定）

    Parameters
    ----------
    close : 收盤價時序（已過濾掉 NaN、依時間排序）
    last_date : 最後一筆的日期
    last_close : 最後一筆收盤價
    predicted_next_close : 你預測的下一個交易日收盤價
    windows : 要算的均線週期清單，預設 [5, 10, 20, 60]
    flat_threshold_pct : 持平容忍門檻（%），預設 0.3
    """
    if windows is None:
        windows = DEFAULT_MA_WINDOWS

    result = MAPredictionResult(
        stock_id=stock_id,
        stock_name=stock_name,
        last_close=float(last_close),
        last_date=pd.Timestamp(last_date),
        predicted_close=float(predicted_next_close),
    )

    up_count = 0
    down_count = 0
    flat_count = 0

    for w in windows:
        current, predicted = predict_next_sma(close, w, predicted_next_close)
        delta = predicted - current
        delta_pct = (predicted / current - 1.0) * 100 if current != 0 else 0.0
        status, color, emoji = _classify(delta_pct, flat_threshold_pct)

        result.mas[w] = MAStatus(
            window=w,
            current_value=current,
            predicted_value=predicted,
            delta=delta,
            delta_pct=delta_pct,
            status=status,
            color=color,
            emoji=emoji,
        )

        if status == "起漲":
            up_count += 1
        elif status == "跌破":
            down_count += 1
        else:
            flat_count += 1

    # 整體訊號（至少 2 條同方向才標記）
    total = up_count + down_count + flat_count
    score = up_count - down_count
    result.overall_score = score
    if abs(score) < max(2, total // 2):
        result.overall_signal = "盤整"
    elif score > 0:
        result.overall_signal = "偏多"
    else:
        result.overall_signal = "偏空"

    return result


def find_break_even_close(close: pd.Series, window: int) -> float:
    """
    反推「下個交易日收在多少，該均線會持平」

    數學：持平 ⇒ predicted_sma = current_sma
        ⇒ predicted_close = oldest_close

    回傳的就是目前視窗最舊那一根的收盤價（拿來對照很有用）
    """
    if len(close) < window:
        raise ValueError(f"資料長度 {len(close)} 不足以計算 SMA({window})")
    return float(close.iloc[-window])


def build_chart_data(
    close: pd.Series,
    predicted_next_close: float,
    windows: List[int] = None,
) -> pd.DataFrame:
    """
    組裝繪圖用的 DataFrame：
    - 收盤價
    - 4 條均線（用 rolling 算到最後一日為止）
    - 「預測收盤」作為額外一行附加在最後
    """
    if windows is None:
        windows = DEFAULT_MA_WINDOWS

    df = pd.DataFrame({"close": close})
    for w in windows:
        df[f"MA{w}"] = calc_sma_series(close, w)

    # 把預測的那一天加上去
    last_date = df.index[-1]
    # 推估下個交易日（粗略 +1 交易日）
    if isinstance(last_date, pd.Timestamp):
        try:
            next_date = last_date + pd.tseries.offsets.BDay(1)
        except Exception:
            next_date = last_date + pd.Timedelta(days=1)
    else:
        # 沒有 datetime index（如測試場景），用序數 +1
        next_date = len(df)

    pred_row = {"close": predicted_next_close}
    # 預測收盤 = (現況 MA × N - 視窗最舊 + 預測收盤) / N
    for w in windows:
        current = float(close.iloc[-w:].mean())
        oldest = float(close.iloc[-w])
        pred_row[f"MA{w}"] = (current * w - oldest + predicted_next_close) / w

    pred_df = pd.DataFrame([pred_row], index=[next_date])
    df = pd.concat([df, pred_df])
    return df
