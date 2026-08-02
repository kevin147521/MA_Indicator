#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
ma_breakout_backtest.py — 均線跌破 / 站回新高 回測模組

邏輯：
1. 對每檔股票計算 5/10/20/60 日 SMA
2. 偵測「跌破」事件：某天收盤 < SMA（從前一天 close >= SMA 變成 close < SMA）
3. 對每個跌破事件，往後看「站回」事件：close > SMA 且 close > 跌破日前 20 個交易日的最高收盤
4. 記錄「站回天數」（跌破日 → 站回日的差距）

輸出：
- events_df: 每一個跌破 / 站回事件（含天數）
- summary_df: 每檔股票 × 每條均線的彙總（平均天數、中位數、命中率）
- global_summary: 全市場彙總
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ma_engine import calc_sma_series


# === 預設參數 ===
DEFAULT_MA_WINDOWS = [5, 10, 20, 60]
DEFAULT_LOOKBACK_HIGH = 20  # 站回時要突破的前 N 日高點


@dataclass
class BreakEvent:
    """單一跌破 / 站回事件"""
    stock_id: str
    ma_window: int
    break_date: pd.Timestamp       # 跌破日
    break_price: float             # 跌破日收盤
    ma_at_break: float             # 跌破當天均線值
    recover_date: Optional[pd.Timestamp]  # 站回日（若 max_lookback 內未站回則 None）
    recover_days: Optional[int]    # 站回天數（若無站回則 None）
    recover_price: Optional[float] # 站回日收盤
    high_at_break: float           # 跌破前 20 日最高收盤（用來判斷新高）


def detect_break_events_for_stock(
    close: pd.Series,
    ma_window: int,
    lookback_high: int = DEFAULT_LOOKBACK_HIGH,
    max_recover_days: int = 252,  # 最多看一年（一年沒站回就不算了）
    min_break_days: int = 2,  # 跌破定義：連續 N 天收盤 < 均線（預設 2 天）
) -> list[BreakEvent]:
    """
    對單檔單條均線偵測所有跌破 / 站回事件。

    Parameters
    ----------
    close : 收盤價 series（index 必須是 datetime）
    ma_window : SMA 週期
    lookback_high : 站回時要突破的前 N 日最高收盤
    max_recover_days : 跌破後最多看幾天（避免無限循環）
    min_break_days : 「跌破」定義：連續 N 天收盤 < 均線才算（過濾一日假跌破）

    Returns
    -------
    list[BreakEvent]
    """
    if len(close) < ma_window + lookback_high + 5:
        return []

    sma = calc_sma_series(close, ma_window)
    events: list[BreakEvent] = []

    below = (close < sma).fillna(False)

    # 連續跌破 min_break_days 才算「真跌破」
    # 跌破起點 = 連續跌破區塊的第一天
    # 用 rolling sum 偵測「連續 min_break_days 都跌破」的第 1 天
    rolling_below = below.astype(int).rolling(window=min_break_days, min_periods=min_break_days).sum()
    # rolling sum == min_break_days 表示這天（含往前 min_break_days-1 天）都跌破
    # 但要確認是「第一個跌破日」，所以前一天 rolling sum 應該 < min_break_days
    qualifies = rolling_below == min_break_days
    prev_qualifies = qualifies.shift(1, fill_value=False)
    is_break_start = qualifies & (~prev_qualifies)

    break_indices = np.where(is_break_start.values)[0]
    if len(break_indices) == 0:
        return []

    close_arr = close.values
    sma_arr = sma.values
    dates = close.index
    n = len(close)

    for idx in break_indices:
        if idx < lookback_high:
            continue
        # 太接近尾端（追蹤空間 < 30 天）視為不完整事件
        if n - idx < 30:
            continue

        break_date = dates[idx]
        break_price = float(close_arr[idx])
        ma_at_break = float(sma_arr[idx])
        high_at_break = float(close_arr[idx - lookback_high:idx].max())

        # 往後找站回日：close > sma AND close > high_at_break
        recover_date = None
        recover_days = None
        recover_price = None

        end_idx = min(idx + max_recover_days, n)
        for j in range(idx + 1, end_idx):
            c = float(close_arr[j])
            s = float(sma_arr[j])
            if not np.isnan(s) and c > s and c > high_at_break:
                recover_date = dates[j]
                recover_days = j - idx
                recover_price = c
                break

        events.append(BreakEvent(
            stock_id=str(close.name) if close.name else "unknown",
            ma_window=ma_window,
            break_date=break_date,
            break_price=break_price,
            ma_at_break=ma_at_break,
            recover_date=recover_date,
            recover_days=recover_days,
            recover_price=recover_price,
            high_at_break=high_at_break,
        ))
    return events


def run_backtest(
    close_df: pd.DataFrame,
    ma_windows: list[int] = None,
    lookback_high: int = DEFAULT_LOOKBACK_HIGH,
    max_recover_days: int = 252,
    min_break_days: int = 2,
    progress_callback=None,
) -> pd.DataFrame:
    """
    對 close_df（columns=stock_id, index=date）跑全市場回測。

    Returns
    -------
    DataFrame: 每一個事件的紀錄
        columns: stock_id, ma_window, break_date, break_price, ma_at_break,
                 recover_date, recover_days, recover_price, high_at_break
    """
    if ma_windows is None:
        ma_windows = DEFAULT_MA_WINDOWS

    rows = []
    total = len(close_df.columns)
    for i, sid in enumerate(close_df.columns):
        close_s = close_df[sid].copy()
        close_s.name = sid
        close_s = close_s.dropna()
        if len(close_s) < max(ma_windows) + lookback_high + 30:
            if progress_callback:
                progress_callback(i + 1, total)
            continue
        for w in ma_windows:
            evs = detect_break_events_for_stock(
                close_s, w,
                lookback_high=lookback_high,
                max_recover_days=max_recover_days,
                min_break_days=min_break_days,
            )
            for ev in evs:
                rows.append({
                    "stock_id": ev.stock_id,
                    "ma_window": ev.ma_window,
                    "break_date": ev.break_date,
                    "break_price": ev.break_price,
                    "ma_at_break": ev.ma_at_break,
                    "recover_date": ev.recover_date,
                    "recover_days": ev.recover_days,
                    "recover_price": ev.recover_price,
                    "high_at_break": ev.high_at_break,
                })
        if progress_callback and (i + 1) % 50 == 0:
            progress_callback(i + 1, total)
    if progress_callback:
        progress_callback(total, total)
    return pd.DataFrame(rows)


def summarize_events(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    對事件 DataFrame 彙總：
    - 每個 (stock_id, ma_window)：總事件數、站回數、命中率、平均 / 中位數站回天數
    """
    if len(events_df) == 0:
        return pd.DataFrame()

    grp = events_df.groupby(["stock_id", "ma_window"])
    summary = grp.agg(
        total_events=("recover_days", "size"),
        recover_events=("recover_days", "count"),
        avg_recover_days=("recover_days", "mean"),
        median_recover_days=("recover_days", "median"),
        min_recover_days=("recover_days", "min"),
        max_recover_days=("recover_days", "max"),
    ).reset_index()
    summary["hit_rate"] = summary["recover_events"] / summary["total_events"]
    summary["avg_recover_days"] = summary["avg_recover_days"].round(2)
    summary["median_recover_days"] = summary["median_recover_days"].round(1)
    summary["hit_rate"] = summary["hit_rate"].round(4)
    return summary


def global_summary(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    全市場彙總：每條均線的整體站回天數分佈。
    """
    if len(events_df) == 0:
        return pd.DataFrame()

    rows = []
    for w, grp in events_df.groupby("ma_window"):
        recovered = grp.dropna(subset=["recover_days"])
        total = len(grp)
        n_recover = len(recovered)
        rows.append({
            "ma_window": w,
            "total_events": total,
            "recover_events": n_recover,
            "no_recover_events": total - n_recover,
            "hit_rate": round(n_recover / total, 4) if total else 0,
            "avg_recover_days": round(recovered["recover_days"].mean(), 2) if n_recover else None,
            "median_recover_days": round(recovered["recover_days"].median(), 1) if n_recover else None,
            "p25_recover_days": round(recovered["recover_days"].quantile(0.25), 1) if n_recover else None,
            "p75_recover_days": round(recovered["recover_days"].quantile(0.75), 1) if n_recover else None,
        })
    return pd.DataFrame(rows)


# === Streamlit 快取 helper ===
def fetch_close_df(stock_ids: list[str] = None) -> pd.DataFrame:
    """
    從 finlab 抓收盤價，回傳 wide DataFrame（columns=stock_id, index=date）。
    若 stock_ids 為 None，抓全市場。
    """
    from data_fetcher import ensure_finlab_login
    ensure_finlab_login()

    from finlab import data
    close_wide = data.get("price:收盤價")
    if stock_ids:
        # 只留交集
        available = [s for s in stock_ids if s in close_wide.columns]
        return close_wide[available].copy()
    return close_wide.copy()