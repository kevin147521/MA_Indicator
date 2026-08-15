#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
barchart_engine.py — 寶塔線（Three-Line Break）計算引擎

寶塔線兩種模式：
1. 「單日比較」（simple）：當日收 > 昨收 → 紅；當日收 < 昨收 → 綠
   簡單直觀，貼近一般 trader 看盤習慣。
2. 「三日轉向」（three_line_break，預設 3）：連續 N 日同向才算新趨勢
   經典寶塔線規則，過濾雜訊但反應慢。

視覺化（台股慣例：紅=漲、綠=跌）：
- 上漲：實體紅柱（從 prev_close 畫到 close）
- 下跌：空心綠柱（從 close 畫到 prev_close，僅描邊）
- 持平：跳過（不畫）

日K / 週K 切換：
- 週K = 日線 resample('W-FRI') 對齊台股週五收盤
  Open = 週內首日 open, High = max(high), Low = min(low),
  Close = 週內末日 close, Volume = sum(volume)
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Literal


# === 預設參數 ===
DEFAULT_THRESHOLD = 3  # 三日轉向用
RISING_COLOR = "#ef5350"   # 紅 = 漲
FALLING_COLOR = "#26a69a"  # 綠 = 跌


# ============================================================
# 日K → 週K resample
# ============================================================
def resample_to_weekly(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """
    日線 OHLCV → 週線 OHLCV（對齊台股，每週週五收）。

    Parameters
    ----------
    ohlcv : index=日期, columns=[open, high, low, close, volume]

    Returns
    -------
    DataFrame index=週結束日（週五），同欄位結構

    Notes
    -----
    - 用 W-FRI 對齊台股交易週（週一～週五）
    - 週內若有假日缺資料，pandas 會跳過 NaN（不影響 OHLCV 計算）
    - 最後一週若是「本週走到一半」（還沒週五），也會被收進來，
      close 會是「本週目前為止收盤」而非「週五收盤」，需自行注意
    """
    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        ohlcv = ohlcv.copy()
        ohlcv.index = pd.to_datetime(ohlcv.index)

    # 排序確保 resample 正確
    ohlcv = ohlcv.sort_index()

    weekly = pd.DataFrame({
        "open":   ohlcv["open"].resample("W-FRI").first(),
        "high":   ohlcv["high"].resample("W-FRI").max(),
        "low":    ohlcv["low"].resample("W-FRI").min(),
        "close":  ohlcv["close"].resample("W-FRI").last(),
        "volume": ohlcv["volume"].resample("W-FRI").sum(),
    })
    weekly = weekly.dropna(subset=["open", "close"])
    return weekly


# ============================================================
# 寶塔線訊號計算
# ============================================================
def calc_barchart_signals(
    close: pd.Series,
    mode: Literal["simple", "three_line_break"] = "three_line_break",
    threshold: int = DEFAULT_THRESHOLD,
) -> pd.Series:
    """
    計算寶塔線的「方向」：up / down / flat

    Parameters
    ----------
    close : 收盤價時序（依時間排序、無 NaN）
    mode :
        - "simple"         : 當日收 vs 昨收，方向直接是 up/down
        - "three_line_break": 連續 N 日同向才視為新趨勢（經典）
    threshold : 三日轉向的 N（預設 3）

    Returns
    -------
    pd.Series index=close.index, values ∈ {"up", "down", "flat"}
    """
    if mode == "simple":
        return _signals_simple(close)
    elif mode == "three_line_break":
        return _signals_three_line_break(close, threshold)
    else:
        raise ValueError(f"mode 必須是 'simple' 或 'three_line_break'，收到 '{mode}'")


def _signals_simple(close: pd.Series) -> pd.Series:
    """單日比較版：今日收 vs 昨日收"""
    diff = close.diff()
    sig = pd.Series("flat", index=close.index, dtype=object)
    sig[diff > 0] = "up"
    sig[diff < 0] = "down"
    # 第一筆 diff 是 NaN，保留為 flat
    return sig


def _signals_three_line_break(close: pd.Series, threshold: int) -> pd.Series:
    """
    三日轉向版（Three-Line Break）：

    規則簡化說明：
    - 維護「目前趨勢」（init = flat）
    - 從最後一根往前看：若「最後連續 N 根（含當下）都比前一根高」→ up
      若「最後連續 N 根都比前一根低」→ down
      否則保持 flat
    - 這個實作跟經典 Three-Line Break 略有不同（經典是看 N 根連續同色柱再決定反轉），
      對 trader 比較直觀：「連漲三天反應為 up」
    """
    if threshold < 1:
        raise ValueError(f"threshold 必須 >= 1，收到 {threshold}")

    diff = close.diff()  # 今天收 - 昨天收
    sig = pd.Series("flat", index=close.index, dtype=object)

    for i in range(len(close)):
        if i < threshold:
            continue
        # 看最近 threshold 根（含今天）的 diff
        window = diff.iloc[i - threshold + 1: i + 1]
        # 過濾掉 NaN
        window = window.dropna()
        if len(window) < threshold:
            continue
        if (window > 0).all():
            sig.iloc[i] = "up"
        elif (window < 0).all():
            sig.iloc[i] = "down"
        # 否則保持 flat
    return sig


# ============================================================
# 寶塔線 OHLC 視覺化資料
# ============================================================
@dataclass
class BarchartBar:
    """單根寶塔線的視覺化數值（給 plotly bar trace 用）"""
    date: pd.Timestamp
    base: float       # 柱底（min(prev_close, close)）
    height: float     # 柱高（abs(close - prev_close)）
    direction: str    # "up" / "down" / "flat"
    close: float
    prev_close: float


def build_barchart_bars(close: pd.Series, signals: pd.Series) -> pd.DataFrame:
    """
    從收盤價時序 + 方向訊號，組成 plotly bar trace 用的 DataFrame。

    Columns: date, base, height, direction, close, prev_close
    """
    prev = close.shift(1)
    df = pd.DataFrame({
        "date": close.index,
        "close": close.values,
        "prev_close": prev.values,
        "direction": signals.values,
    }).dropna(subset=["prev_close"])

    df["base"] = df[["close", "prev_close"]].min(axis=1)
    df["height"] = (df["close"] - df["prev_close"]).abs()
    # 持平（height=0）的 bar 高度補極小值，避免 plotly 漏畫
    df.loc[df["height"] == 0, "height"] = (close.max() - close.min()) * 1e-4
    return df.reset_index(drop=True)


# ============================================================
# 寶塔線趨勢分析
# ============================================================
@dataclass
class BarchartTrend:
    """寶塔線目前趨勢摘要"""
    current: str               # "up" / "down" / "flat"
    streak: int                # 目前已連續幾根同方向（從最近往前算）
    last_flip_date: pd.Timestamp | None  # 上次反轉日期
    last_flip_from: str | None  # 上次反轉前方向
    last_flip_to: str | None    # 上次反轉後方向
    n_up_total: int
    n_down_total: int
    n_flat_total: int


def analyze_barchart_trend(close: pd.Series, signals: pd.Series) -> BarchartTrend:
    """
    分析寶塔線的目前趨勢與反轉點。

    Parameters
    ----------
    close : 收盤價時序
    signals : calc_barchart_signals 的輸出

    Returns
    -------
    BarchartTrend dataclass
    """
    sig = signals.values
    idx = signals.index

    # 目前方向 = 最後一個非 flat
    current = "flat"
    for v in reversed(sig):
        if v in ("up", "down"):
            current = v
            break

    # streak：最近連續同方向根數（從尾端往前算，遇到不同方向就停）
    streak = 0
    for v in reversed(sig):
        if v == current:
            streak += 1
        elif v == "flat":
            continue
        else:
            break

    # 上次反轉：找到最後一個「方向變化」的 index
    last_flip_date = None
    last_flip_from = None
    last_flip_to = None
    # 走訪序列（從頭到尾），記最後一次變化
    prev_v = sig[0]
    for i, v in enumerate(sig):
        if v != prev_v and v != "flat" and prev_v != "flat":
            last_flip_date = idx[i]
            last_flip_from = prev_v
            last_flip_to = v
        if v != "flat":
            prev_v = v

    return BarchartTrend(
        current=current,
        streak=streak,
        last_flip_date=last_flip_date,
        last_flip_from=last_flip_from,
        last_flip_to=last_flip_to,
        n_up_total=int((sig == "up").sum()),
        n_down_total=int((sig == "down").sum()),
        n_flat_total=int((sig == "flat").sum()),
    )


# ============================================================
# 簡易 self-test
# ============================================================
if __name__ == "__main__":
    # 構造一個小時序測試
    sample = pd.Series(
        [100, 101, 102, 103, 102, 101, 100, 99, 98, 99, 100, 101, 102],
        index=pd.date_range("2024-01-01", periods=13),
    )
    print("=== simple ===")
    print(calc_barchart_signals(sample, mode="simple").tolist())
    print("=== three_line_break (3) ===")
    print(calc_barchart_signals(sample, mode="three_line_break", threshold=3).tolist())
    print("=== three_line_break (2) ===")
    print(calc_barchart_signals(sample, mode="three_line_break", threshold=2).tolist())

    print("\n=== weekly resample ===")
    daily = pd.DataFrame({
        "open":   [100, 101, 102, 103, 99, 100, 101],
        "high":   [101, 103, 104, 105, 100, 102, 103],
        "low":    [99, 100, 101, 99, 98, 99, 100],
        "close":  [101, 102, 103, 99, 99, 101, 102],
        "volume": [1000, 1100, 1200, 1300, 800, 900, 1000],
    }, index=pd.date_range("2024-01-01", periods=7))
    print(resample_to_weekly(daily))
