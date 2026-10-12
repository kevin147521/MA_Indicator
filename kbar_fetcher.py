"""
kbar_fetcher.py — 個股 60分K 抓取 (用 finlab tw_minute API)

來源: Finlab CLI 官方提供 `data.get(f'tw_minute:{stock_id}', start=..., end=...)`
- 1 分 K 資料, 單次最多 31 天 (程式自動分段)
- resample 60min 聚合成 60分K
- 全市場有 (1800 檔個股都有, 包含 ETF/權證)
- @lru_cache + @st.cache_data 避免重抓 (finlab 抓每段 8-40s 很慢)

注意: finlab 2.0.20 對 tw_minute 的用量可能會計入 daily quota (5000MB/day)
"""
import pandas as pd
from typing import Optional
from functools import lru_cache


@lru_cache(maxsize=128)
def _fetch_minute_kbar_cached(stock_id: str, start: str, end: str) -> str:
    """lru_cache 抓 1 分 K, 回傳 JSON 字串"""
    from finlab import data as _finlab_data
    chunks = []
    s = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while s <= end_ts:
        e = min(s + pd.Timedelta(days=30), end_ts)
        chunks.append(_finlab_data.get(
            f'tw_minute:{stock_id}',
            start=s.strftime('%Y-%m-%d'),
            end=e.strftime('%Y-%m-%d'),
        ))
        s = e + pd.Timedelta(days=1)
    df = pd.concat(chunks, ignore_index=True)
    return df.to_json(orient='split', date_format='iso')


def fetch_minute_kbar(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """
    抓個股 1 分 K 資料 (finlab tw_minute API) — 自動 lru_cache 避免重抓

    Args:
        stock_id: 股票代號 (e.g. '2330')
        start: 起始日 'YYYY-MM-DD'
        end: 結束日 'YYYY-MM-DD'

    Returns:
        DataFrame columns: stock_id, trade_date, timestamp, session,
                           open, high, low, close, volume, tick_count, vwap
    """
    import io
    raw = _fetch_minute_kbar_cached(stock_id, start, end)
    return pd.read_json(io.StringIO(raw), orient='split')


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


def fetch_60min_kbar(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """
    一站式: 抓 1 分 K + resample 成 60分K (lru_cache)

    Args:
        stock_id: 股票代號
        start: 起始日
        end: 結束日

    Returns:
        DataFrame 60分K, index=DatetimeIndex
    """
    minute_df = fetch_minute_kbar(stock_id, start, end)
    return resample_to_60min(minute_df)


# Streamlit 整合: cache_data 30 分鐘 (額外一層 cache 在 streamlit 內)
def make_st_cached_fetcher():
    """在 streamlit page 內用 @st.cache_data 包這個"""
    import streamlit as st

    @st.cache_data(ttl=1800, show_spinner="抓 60分K 資料...")
    def _cached(stock_id: str, start: str, end: str) -> str:
        df = fetch_60min_kbar(stock_id, start, end)
        return df.to_json(orient='split', date_format='iso')

    def wrapper(stock_id: str, start: str, end: str) -> pd.DataFrame:
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
    df = fetch_60min_kbar('2330', '2026-10-01', '2026-10-08')
    print(f"2330 60分K (首次): {time.time()-t0:.1f}s, {len(df)} 根")
    t0 = time.time()
    df2 = fetch_60min_kbar('2330', '2026-10-01', '2026-10-08')
    print(f"2330 60分K (cache): {time.time()-t0:.3f}s, {len(df2)} 根")
    print(f"前 3 筆:\n{df.head(3)}")
