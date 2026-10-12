#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
kbar_daily_increment.py — V1 60分K 每日增量更新 (FinLab tw_minute)

用途:
    - 每天 21:30 跑一次, 抓「過去 5 天」的 1 分 K
    - 為什麼抓 5 天: 1 分 K 要 13:30 收市後才完整, 前幾天可能資料還在補
    - 1800 檔 8 workers 預估 75-90 分鐘
    - 存兩種格式:
        - per-stock parquet: data/kbars_60min_incremental/{stock_id}.parquet (歷史累積)
        - wide feather:     data/kbars_60min_incremental_wide/{field}.feather (回測用)

執行:
    /opt/anaconda3/envs/finlab3/bin/python kbar_daily_increment.py
    或 launchd 排程 (ai.stockslaves.v1-60min-kbar-daily.plist)

注意: 大量用 finlab 2.0.20 tw_minute 會計入 daily quota (5000MB/day)
    1800 檔 × 5 天 × 0.1MB ≈ 900MB 增量, OK
"""
import sys
import os
import time
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 讓 finlab_config import
from finlab_config import login_finlab
login_finlab()

from finlab import data as _finlab_data
import pandas as pd
import numpy as np

# ============ 設定 ============
DATA_DIR = Path(__file__).resolve().parent / 'data' / 'kbars_60min_incremental'
WIDE_DIR = Path(__file__).resolve().parent / 'data' / 'kbars_60min_incremental_wide'
DATA_DIR.mkdir(parents=True, exist_ok=True)
WIDE_DIR.mkdir(parents=True, exist_ok=True)

WORKERS = 8
DAYS_BACK = 7   # 抓過去 7 天 (含週末緩衝, 確保當天收市後的補資料能撈到)
TOP_N = 1800    # 全市場約 1800 檔
CHUNK_DAYS = 30  # finlab tw_minute 單次最多 31 天, 用 30 安全

# 1 分 K → 60分K 聚合 (open=first, high=max, low=min, close=last, volume=sum)
RESAMPLE_AGG = {'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'}


def get_stock_universe() -> list[str]:
    """抓全市場個股清單 (前 TOP_N 大, 排除 ETF/權證)"""
    secs = _finlab_data.get('security_categories')
    pure = secs[(secs['market'] != 'rotc') & (secs['market'] != 'etf')].copy()
    pure['stock_id'] = pure['stock_id'].astype(str)

    mv = _finlab_data.get('etl:market_value')
    mv_last = mv.iloc[-1]
    mv_last.index = mv_last.index.astype(str)
    # 只留有市值且在個股清單內的
    valid_sids = set(pure['stock_id'])
    mv_dict = {sid: v for sid, v in mv_last.to_dict().items() if sid in valid_sids and v > 0}
    sorted_mv = sorted(mv_dict.items(), key=lambda x: x[1], reverse=True)
    return [s for s, _ in sorted_mv[:TOP_N]]


def fetch_one_stock_minute(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """抓 1 檔 1 分 K (含錯誤重試)"""
    from finlab import data as _finlab_data
    for attempt in range(3):
        try:
            chunks = []
            s = pd.Timestamp(start)
            end_ts = pd.Timestamp(end)
            while s <= end_ts:
                e = min(s + pd.Timedelta(days=CHUNK_DAYS), end_ts)
                chunks.append(_finlab_data.get(
                    f'tw_minute:{stock_id}',
                    start=s.strftime('%Y-%m-%d'),
                    end=e.strftime('%Y-%m-%d'),
                ))
                s = e + pd.Timedelta(days=1)
            return pd.concat(chunks, ignore_index=True)
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    return pd.DataFrame()


def resample_to_60min(minute_df: pd.DataFrame) -> pd.DataFrame:
    """1 分 K → 60分K"""
    if minute_df.empty:
        return pd.DataFrame()
    return (minute_df.set_index('timestamp')
                       .resample('60min')
                       .agg(RESAMPLE_AGG)
                       .dropna(subset=['open']))


def merge_with_existing(stock_id: str, new_k60: pd.DataFrame) -> pd.DataFrame:
    """合併新抓的 60分K 跟既有 parquet (去重, 保留新資料)"""
    path = DATA_DIR / f'{stock_id}.parquet'
    if not path.exists() or path.stat().st_size < 100:
        return new_k60
    try:
        existing = pd.read_parquet(path)
        if existing.empty:
            return new_k60
        # 合併 + 去重 (以 index = timestamp 為 key, 保留新值)
        combined = pd.concat([existing, new_k60])
        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
        return combined
    except Exception:
        return new_k60


def save_per_stock(stock_id: str, df: pd.DataFrame):
    """存 per-stock parquet"""
    if df.empty:
        return
    path = DATA_DIR / f'{stock_id}.parquet'
    df.to_parquet(path)


def build_wide_format(stock_ids: list[str]):
    """從所有 per-stock parquet 重建 wide feather (6 欄: open/high/low/close/volume)"""
    print(f"   重建 wide feather ({len(stock_ids)} 檔)...")
    fields = ['open', 'high', 'low', 'close', 'volume']
    wide_dfs = {}
    for field in fields:
        wide_dfs[field] = pd.DataFrame()

    for i, sid in enumerate(stock_ids, 1):
        path = DATA_DIR / f'{sid}.parquet'
        if not path.exists() or path.stat().st_size < 100:
            continue
        try:
            df = pd.read_parquet(path)
            if df.empty:
                continue
            for field in fields:
                if field in df.columns:
                    wide_dfs[field][sid] = df[field]
        except Exception:
            continue
        if i % 200 == 0:
            print(f"      {i}/{len(stock_ids)}")

    # 寫 feather
    for field, df in wide_dfs.items():
        if df.empty:
            continue
        path = WIDE_DIR / f'{field}.feather'
        df.reset_index().rename(columns={'index': 'ts'}).to_feather(path)
        print(f"   寫 {path.name}: shape={df.shape}")


def main():
    """主流程"""
    start_ts = time.time()
    print(f"=== V1 60分K 每日增量 ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")
    print(f"   WORKERS={WORKERS}, DAYS_BACK={DAYS_BACK}, TOP_N={TOP_N}")
    print()

    # 1. 抓個股清單
    print("1. 抓個股清單...")
    stock_ids = get_stock_universe()
    print(f"   共 {len(stock_ids)} 檔")

    # 2. 計算日期範圍
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=DAYS_BACK + 5)).strftime('%Y-%m-%d')
    print(f"2. 日期範圍: {start_date} ~ {end_date}")
    print()

    # 3. 平行抓 1 分 K + resample 60分K + 合併 + 存
    print(f"3. 平行抓 + 存 (8 workers)...")
    success = 0
    failed = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(
                lambda sid=sid: (sid, _process_one(sid, start_date, end_date))
            ): sid
            for sid in stock_ids
        }
        for i, future in enumerate(as_completed(futures), 1):
            try:
                sid, ok = future.result(timeout=120)
                if ok:
                    success += 1
                else:
                    failed.append(sid)
            except Exception as e:
                failed.append(futures[future])
            if i % 50 == 0:
                print(f"   進度: {i}/{len(stock_ids)}, 成功 {success}, 失敗 {len(failed)}")

    elapsed = time.time() - start_ts
    print(f"\n   抓取完成: 成功 {success}/{len(stock_ids)}, 失敗 {len(failed)}, 耗時 {elapsed/60:.1f} 分鐘")
    if failed:
        print(f"   失敗清單 (前 10): {failed[:10]}")
    print()

    # 4. 重建 wide feather
    print("4. 重建 wide feather...")
    build_wide_format(stock_ids)

    total_elapsed = time.time() - start_ts
    print(f"\n=== 完成! 總耗時 {total_elapsed/60:.1f} 分鐘 ===")


def _process_one(stock_id: str, start_date: str, end_date: str) -> tuple[str, bool]:
    """抓 1 檔 + 合併 + 存 (thread worker)"""
    try:
        minute_df = fetch_one_stock_minute(stock_id, start_date, end_date)
        k60 = resample_to_60min(minute_df)
        merged = merge_with_existing(stock_id, k60)
        save_per_stock(stock_id, merged)
        return (stock_id, True)
    except Exception as e:
        # print(f"      失敗 {stock_id}: {e}")  # 太吵, 累積到最後報告
        return (stock_id, False)


if __name__ == '__main__':
    main()
