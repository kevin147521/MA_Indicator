"""
kbar_fetcher.py — 個股 60分K 抓取 (用 finlab tw_price_60min 內建)

來源: Finlab 內建 `data.get('tw_price_60min:{open/high/low/close/volume}')`
- 全市場 60分K, 5 根/天 (10:00/11:00/12:00/13:00/13:33 收盤)
- 歷史從 2026-09-01 起 (finlab 2026-10-12 重建後, 5 個 key 都有資料)
- 抓取超快 2-3 秒 / 全市場 2414 檔
- 配額 5 個 key × 6MB = 30MB/次, 5GB/day 內 OK
- @st.cache_data 30 分鐘避免重抓 (配額小但 streamlit 還是會一直 query)

注意: finlab 2.2.10 → 2.2.11 升版可消除 "Your version is 2.2.10" 警告 (但不影響功能)
"""
import pandas as pd
from typing import Optional
from functools import lru_cache
from pathlib import Path


# finlab 內建 tw_price_60min:* 5 個 keys 對應欄位
FIELDS_MAP = {
    'open': '開盤價',
    'high': '最高價',
    'low': '最低價',
    'close': '收盤價',
    'volume': '成交量',
}
# finlab tw_price_60min 歷史起點 (2026-10-14 重建後從 2026-01-02 起, 187 個交易日)
MIN_START_DATE = '2026-01-02'


def fetch_60min_kbar(stock_id: str, start: str = MIN_START_DATE, end: Optional[str] = None) -> pd.DataFrame:
    """
    一站式: 從 finlab tw_price_60min:* 拿單檔 60分K (5 個欄位)

    Args:
        stock_id: 股票代號 (e.g. '2330')
        start: 起始日 'YYYY-MM-DD' (預設 '2026-09-01')
        end: 結束日 'YYYY-MM-DD' (預設 None = 抓到最新)

    Returns:
        DataFrame index=DatetimeIndex, columns=[open, high, low, close, volume]
    """
    from finlab import data
    k = pd.DataFrame({col: data.get(f'tw_price_60min:{name}')[stock_id]
                       for col, name in FIELDS_MAP.items()}).loc[start:end]
    k = k.dropna(how='all')
    return k


def resample_to_60min(minute_df: pd.DataFrame) -> pd.DataFrame:
    """
    把 1 分 K resample 成 60分K (open=first, high=max, low=min, close=last, volume=sum)

    Args:
        minute_df: fetch_minute_kbar() 的結果 (含 timestamp 欄)

    Returns:
        DataFrame index=DatetimeIndex (Asia/Taipei), columns=[open, high, low, close, volume]
    """
    if minute_df.empty:
        return pd.DataFrame()

    return (minute_df.set_index('timestamp')
                       .resample('60min')
                       .agg({'open': 'first', 'high': 'max', 'low': 'min',
                             'close': 'last', 'volume': 'sum'})
                       .dropna(subset=['open']))


# Streamlit 整合: cache_data 30 分鐘 (額外一層 cache 在 streamlit 內)
def make_st_cached_fetcher():
    """在 streamlit page 內用 @st.cache_data 包這個"""
    import streamlit as st

    @st.cache_data(ttl=1800, show_spinner="抓 60分K 資料...")
    def _cached(stock_id: str, start: str, end: Optional[str]) -> str:
        df = fetch_60min_kbar(stock_id, start, end)
        return df.to_json(orient='split', date_format='iso')

    def wrapper(stock_id: str, start: str = MIN_START_DATE, end: Optional[str] = None) -> pd.DataFrame:
        raw = _cached(stock_id, start, end)
        df = pd.read_json(raw, orient='split')
        if df.empty:
            return df
        df.index = pd.to_datetime(df.index)
        return df

    return wrapper


if __name__ == '__main__':
    # smoke test
    import time
    t0 = time.time()
    df = fetch_60min_kbar('2330', '2026-09-15')
    print(f"2330 60分K (首次): {time.time()-t0:.1f}s, {len(df)} 根")
    t0 = time.time()
    df2 = fetch_60min_kbar('2330', '2026-09-15')
    print(f"2330 60分K (lru_cache): {time.time()-t0:.3f}s, {len(df2)} 根")
    print(f"前 3 筆:\n{df.head(3)}")
    print(f"後 3 筆:\n{df.tail(3)}")


# ============================================================
# 整合: 統一入口給金包銀 page 用 (從 finlab tw_price_60min 拿)
# ============================================================
def get_stock_60min(stock_id: str, days_back: int = 30) -> tuple[pd.DataFrame, str]:
    """
    取得個股 60分K 資料 (finlab 內建 tw_price_60min)

    Args:
        stock_id: 股票代號
        days_back: 從今天往前抓幾天 (預設 30, 但 finlab tw_price_60min 從 2026-09-01 起)

    Returns:
        (df, source) — source 是 'finlab_60min_builtin'
    """
    from datetime import datetime, timedelta
    end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')  # 避免 finlab not_ready
    start_date = (datetime.now() - timedelta(days=days_back + 5)).strftime('%Y-%m-%d')
    # finlab tw_price_60min 歷史從 2026-09-01 起, 不能給太早
    start_date = max(start_date, MIN_START_DATE)

    df = fetch_60min_kbar(stock_id, start_date, end_date)
    return df, 'finlab_60min_builtin'
