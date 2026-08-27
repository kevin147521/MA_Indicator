#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
ma_recovery_scanner.py — 全市場「均線收復」個股掃描

目標：找「曾經跌破 5/10/20/60 MA，後續陸續站回均線，且長期均線往上」的個股
（V 轉 / U 轉 / 黃金交叉後續漲型態）

條件（全部都要滿足）：
1. 過去 N 日內，close 曾經 < 5MA（跌破短線均線）
2. 過去 N 日內，close 曾經 < 10MA
3. 過去 N 日內，close 曾經 < 20MA
4. 過去 N 日內，close 曾經 < 60MA（跌破長期均線 — 最重要）
5. 目前 close > 5MA（站回短線）
6. 目前 close > 10MA
7. 目前 close > 20MA
8. 目前 close > 60MA（全部站回）
9. MA60 向上：ma60.iloc[-1] > ma60.iloc[-lookback]（長期趨勢往上）

排序鍵：
- MA60 斜率（過去 20 日變化 %）— 越陡越強
- close 距 MA20 距離 % — 越遠越強（突破強度）
- 近期 20 日漲幅 — 越大越強
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional


# ============================================================
# 預設參數
# ============================================================
DEFAULT_LOOKBACK = 60          # 過去 60 日內曾經跌破
DEFAULT_MA_WINDOWS = [5, 10, 20, 60]
DEFAULT_MA60_SLOPE_LOOKBACK = 20  # 算 MA60 斜率用 20 日前對比


def calc_mas(close: pd.Series, windows: list[int] = None) -> pd.DataFrame:
    """計算多條 SMA"""
    if windows is None:
        windows = DEFAULT_MA_WINDOWS
    df = pd.DataFrame({"close": close})
    for w in windows:
        df[f"MA{w}"] = close.rolling(window=w, min_periods=w).mean()
    return df


def check_recovery(
    close: pd.Series,
    lookback: int = DEFAULT_LOOKBACK,
    ma_windows: list[int] = None,
    ma60_slope_lookback: int = DEFAULT_MA60_SLOPE_LOOKBACK,
) -> dict:
    """
    對單一個股時間序列檢查「均線收復」條件

    Parameters
    ----------
    close : 收盤價時序（依時間排序、無 NaN，至少 lookback+max(ma_windows)+5 根）
    lookback : 過去 N 日內要曾經跌破所有 MA
    ma_windows : 要檢查的均線週期
    ma60_slope_lookback : MA60 斜率計算的對比天數

    Returns
    -------
    dict with:
      - passed: bool（全部條件是否滿足）
      - reasons: list[str]（未通過的條件名稱）
      - stats: dict（每股數值：MA60 斜率、距 MA20 距離、近期漲幅、跌破日期等）
    """
    if ma_windows is None:
        ma_windows = DEFAULT_MA_WINDOWS

    if len(close) < lookback + max(ma_windows) + 5:
        return {"passed": False, "reasons": ["資料不足"], "stats": {}}

    # 計算 MA
    df = calc_mas(close, ma_windows)
    cur = df.iloc[-1]
    window = df.iloc[-(lookback + 1):-1]  # 過去 lookback 日（不含今日）

    reasons = []
    stats = {}

    # 條件 1-4: 過去 N 日曾經跌破
    broke_dates = {}
    for w in ma_windows:
        broke_below = (window["close"] < window[f"MA{w}"])
        if not broke_below.any():
            reasons.append(f"過去 {lookback} 日未跌破 MA{w}")
        else:
            broke_dates[w] = broke_below.idxmax()  # 最後一次跌破日期

    # 條件 5-8: 目前站回
    for w in ma_windows:
        if cur["close"] <= cur[f"MA{w}"]:
            reasons.append(f"目前 close ≤ MA{w}")

    # 條件 9: MA60 向上
    if len(df) > ma60_slope_lookback:
        ma60_now = cur["MA60"]
        ma60_before = df["MA60"].iloc[-(ma60_slope_lookback + 1)]
        if pd.isna(ma60_now) or pd.isna(ma60_before):
            reasons.append("MA60 NaN")
            ma60_slope = 0
        else:
            ma60_slope = (ma60_now - ma60_before) / ma60_before * 100
            if ma60_slope <= 0:
                reasons.append(f"MA60 向下（{ma60_slope:+.2f}%）")
    else:
        ma60_slope = 0
        reasons.append("MA60 斜率資料不足")

    # 統計值（給排序用）
    if pd.notna(cur["MA20"]):
        dist_to_ma20 = (cur["close"] - cur["MA20"]) / cur["MA20"] * 100
    else:
        dist_to_ma20 = 0
    if len(close) >= 20:
        recent_20_return = (close.iloc[-1] / close.iloc[-20] - 1) * 100
    else:
        recent_20_return = 0
    if len(close) >= 60:
        recent_60_return = (close.iloc[-1] / close.iloc[-60] - 1) * 100
    else:
        recent_60_return = 0

    stats = {
        "ma60_slope_20d": ma60_slope,
        "dist_to_ma20_pct": dist_to_ma20,
        "recent_20_return": recent_20_return,
        "recent_60_return": recent_60_return,
        "last_break_ma5_date": broke_dates.get(5),
        "last_break_ma10_date": broke_dates.get(10),
        "last_break_ma20_date": broke_dates.get(20),
        "last_break_ma60_date": broke_dates.get(60),
        "current_close": float(cur["close"]),
        "current_ma5": float(cur["MA5"]) if pd.notna(cur["MA5"]) else None,
        "current_ma10": float(cur["MA10"]) if pd.notna(cur["MA10"]) else None,
        "current_ma20": float(cur["MA20"]) if pd.notna(cur["MA20"]) else None,
        "current_ma60": float(cur["MA60"]) if pd.notna(cur["MA60"]) else None,
    }

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "stats": stats,
    }


def scan_market(
    close_wide: pd.DataFrame,
    lookback: int = DEFAULT_LOOKBACK,
    ma_windows: list[int] = None,
    ma60_slope_lookback: int = DEFAULT_MA60_SLOPE_LOOKBACK,
    min_data_len: Optional[int] = None,
) -> pd.DataFrame:
    """
    對全市場 wide close DataFrame 跑 scan。

    Parameters
    ----------
    close_wide : wide DataFrame（index=date, columns=stock_id）
    lookback : 過去 N 日內曾跌破
    ma_windows : 要檢查的均線
    ma60_slope_lookback : MA60 斜率天數
    min_data_len : 個股最少要有幾筆資料才納入

    Returns
    -------
    DataFrame with columns: stock_id, passed, reasons, + 統計欄位
    """
    if ma_windows is None:
        ma_windows = DEFAULT_MA_WINDOWS
    if min_data_len is None:
        min_data_len = lookback + max(ma_windows) + 10

    rows = []
    for sid in close_wide.columns:
        s = close_wide[sid].dropna()
        if len(s) < min_data_len:
            continue
        result = check_recovery(
            s, lookback=lookback, ma_windows=ma_windows,
            ma60_slope_lookback=ma60_slope_lookback,
        )
        if result["passed"]:
            row = {"stock_id": str(sid), "passed": True, "reasons": ""}
            row.update(result["stats"])
            rows.append(row)

    return pd.DataFrame(rows)


# ============================================================
# self-test
# ============================================================
if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 構造一個 U 轉序列測試
    np.random.seed(42)
    n = 200
    # 前 100 日下跌、後 100 日上漲
    trend = np.concatenate([
        np.linspace(100, 60, 100),  # 跌
        np.linspace(60, 110, 100),  # 漲
    ])
    noise = np.random.randn(n) * 2
    close = pd.Series(trend + noise)
    close.index = pd.date_range("2024-01-01", periods=n)

    print("=== U 轉序列測試 ===")
    r = check_recovery(close, lookback=80, ma60_slope_lookback=20)
    print(f"  passed: {r['passed']}")
    print(f"  reasons: {r['reasons']}")
    print(f"  stats:")
    for k, v in r["stats"].items():
        print(f"    {k}: {v}")

    # 構造一個無聊的上升序列測試（沒跌破過）
    uptrend = pd.Series(100 + np.arange(150) * 0.5 + np.random.randn(150) * 1)
    uptrend.index = pd.date_range("2024-01-01", periods=150)
    print("\n=== 純上升序列測試（應該不通過）===")
    r2 = check_recovery(uptrend, lookback=60)
    print(f"  passed: {r2['passed']}")
    print(f"  reasons: {r2['reasons']}")
