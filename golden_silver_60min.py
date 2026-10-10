"""
golden_silver_60min.py — 「金包銀 60分K 版」核心計算 (V1 第 11 個 page 用)

跟 golden_silver.py (日K) 差異:
- 資料源: shioaji 60分K (per-stock parquet + wide feather)
- MA 期間用「根數」而非「日數」:
  - 60根 ≈ 2.5 日 (短線)
  - 120根 ≈ 5 日 (中短線)
  - 240根 ≈ 10 日 (中線)
  - UI 可調 (預設 60/120/240)
- 量縮: 24 根 (≈1 日) / 240 根 (≈10 日) 比率
- 突破: 收盤 > max(MA_mid, MA_long) × 1.005 (0.5% 即算突破, 因為 60 分 K 較敏感)
- 三大法人 不算 (永豐純 K 棒, 沒法人資料; 要看法人請用日 K 金包銀 page)

資料讀取: 透過 shioaji_kbar/scripts/backtest_data_loader.py 的 KBarLoader
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 加 shioaji_kbar/scripts 到 sys.path 方便 import KBarLoader
SHIOAJI_KBAR_SCRIPTS = Path('/Users/kevin/Desktop/排程運算/shioaji_kbar/scripts')
if str(SHIOAJI_KBAR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHIOAJI_KBAR_SCRIPTS))


# 預設門檻常數
DEFAULT_TOLERANCE_PCT = 1.0  # 容差 ±1% (60分K 較敏感, 比日K 3% 嚴格)
DEFAULT_VOL_SHRINK_RATIO = 0.8
DEFAULT_BREAK_THRESHOLD = 1.005  # 0.5% 即算突破
DEFAULT_MA_PERIODS = (60, 120, 240)  # 60 分 K 棒根數
DEFAULT_VOL_FAST = 24  # ≈ 1 日 (1 日有 4 根 H1)
DEFAULT_VOL_SLOW = 240  # ≈ 10 日


def get_kbar_loader():
    """取得 KBarLoader (per-stock + wide feather 雙格式自動找最新)"""
    from backtest_data_loader import KBarLoader
    return KBarLoader()


def compute_mas_root(close_wide: pd.DataFrame, periods=(60, 120, 240)) -> dict:
    """
    算多條 MA (wide format, 欄=股票, 列=時間)
    period 單位是「60分K 根數」
    """
    return {p: close_wide.rolling(p, min_periods=p).mean() for p in periods}


def compute_vol_ma_root(vol_wide: pd.DataFrame, periods=(24, 240)) -> dict:
    """算成交量 MA (wide format)"""
    return {p: vol_wide.rolling(p, min_periods=p).mean() for p in periods}


def detect_compression_root(
    close: pd.Series,
    ma_fast: pd.Series,
    ma_mid: pd.Series,
    ma_slow: pd.Series,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> pd.DataFrame:
    """
    60分K 版「金包銀夾擊」型態偵測 (1 檔)

    Args:
        close: 收盤價 (1D Series, index=datetime)
        ma_fast/ma_mid/ma_slow: 對應的均線 (1D Series)
        tolerance_pct: 容差 (%), 收盤在 ma_fast 上下 tolerance% 內都算「壓縮下緣」

    Returns:
        DataFrame with columns:
        - close, ma_fast, ma_mid, ma_slow, upper_ma
        - band_width_pct: 夾擊帶寬度 (上蓋 - 下蓋) / 下蓋 × 100
        - dist_to_fast_pct: 收盤對 ma_fast 距離 %
        - dist_to_upper_pct: 收盤對上蓋 MA 距離 %
        - is_compressed: 是否在夾擊帶內 (且 MA 順序正確)
    """
    # 上蓋 = 較高壓力線 (max mid, slow)
    upper_ma = pd.concat([ma_mid, ma_slow], axis=1).max(axis=1)
    upper_ma.name = 'upper_ma'

    out = pd.DataFrame({
        'close': close,
        'ma_fast': ma_fast,
        'ma_mid': ma_mid,
        'ma_slow': ma_slow,
        'upper_ma': upper_ma,
    })
    out['band_width_pct'] = (out['upper_ma'] - out['ma_fast']) / out['ma_fast'] * 100
    out['dist_to_fast_pct'] = (out['close'] - out['ma_fast']) / out['ma_fast'] * 100
    out['dist_to_upper_pct'] = (out['upper_ma'] - out['close']) / out['close'] * 100

    cond1 = out['dist_to_fast_pct'] >= -tolerance_pct
    cond2 = out['dist_to_upper_pct'] >= -tolerance_pct
    cond3 = out['band_width_pct'] > 0
    out['is_compressed'] = cond1 & cond2 & cond3
    return out


def detect_volume_shrink_root(
    vol_fast: pd.Series,
    vol_slow: pd.Series,
    threshold: float = DEFAULT_VOL_SHRINK_RATIO,
) -> pd.Series:
    """量縮: vol_fast / vol_slow < threshold (預設 24根 / 240根 < 0.8)"""
    ratio = vol_fast / vol_slow
    return ratio < threshold


def detect_breakout_root(
    close: pd.Series,
    ma_mid: pd.Series,
    ma_slow: pd.Series,
    threshold: float = DEFAULT_BREAK_THRESHOLD,
) -> pd.DataFrame:
    """突破: 收盤 > ma_mid × threshold 或 > ma_slow × threshold"""
    out = pd.DataFrame({'close': close, 'ma_mid': ma_mid, 'ma_slow': ma_slow})
    out['break_mid'] = out['close'] > out['ma_mid'] * threshold
    out['break_slow'] = out['close'] > out['ma_slow'] * threshold
    out['is_breakout'] = out['break_mid'] | out['break_slow']
    out['recent_break_5d'] = out['is_breakout'].rolling(20, min_periods=1).max().astype(bool)  # 20 根 ≈ 5 個交易日
    out['recent_break_20d'] = out['is_breakout'].rolling(80, min_periods=1).max().astype(bool)  # 80 根 ≈ 20 個交易日
    return out


def is_long_kbar_root(open_: float, close: float, low: float, high: float, body_ratio: float = 0.6) -> bool:
    """實體長紅 K 線"""
    if close <= open_:
        return False
    total_range = high - low
    if total_range <= 0:
        return False
    body = close - open_
    return (body / total_range) >= body_ratio


def classify_signal_root(
    is_compressed: bool,
    is_vol_shrink: bool,
    is_breakout_now: bool,
    is_long_red: bool,
    recent_break_5d: bool = False,
    recent_break_20d: bool = False,
) -> tuple[str, int]:
    """4 條件 → 訊號 + 分數 (0-4)"""
    score = int(is_compressed) + int(is_vol_shrink) + int(is_breakout_now) + int(is_long_red)

    if not is_compressed:
        return ('🔴 不符', score)
    if is_breakout_now and is_long_red:
        return ('🟢 突破表態', score)
    if is_vol_shrink and (recent_break_5d or is_breakout_now):
        return ('🟢 突破後回踩', score)
    if is_vol_shrink:
        return ('🟡 量縮整理', score)
    return ('⚪ 觀察', score)


# ============================================================
# 全市場掃描 (60 分 K 版, 主入口)
# ============================================================
def scan_golden_silver_60min(
    stock_ids: list[str],
    kbar_loader,
    market_cap_map: dict,
    name_map: dict,
    market_map: dict,
    industry_map: dict,
    ma_fast: int = 60,
    ma_mid: int = 120,
    ma_slow: int = 240,
    vol_fast: int = 24,
    vol_slow: int = 240,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    vol_shrink_ratio: float = DEFAULT_VOL_SHRINK_RATIO,
    break_threshold: float = DEFAULT_BREAK_THRESHOLD,
    long_red_body_ratio: float = 0.6,
) -> pd.DataFrame:
    """
    60分K 版「金包銀」全市場掃描

    Args:
        stock_ids: 要掃的個股清單
        kbar_loader: KBarLoader 物件 (從 shioaji_kbar/scripts/backtest_data_loader.py)
        ma_fast/ma_mid/ma_slow: 3 條 MA 根數 (預設 60/120/240 = 2.5/5/10 日)
        vol_fast/vol_slow: 量縮比較的 2 條 vol MA 根數
        tolerance_pct: 夾擊容差 (%)
        vol_shrink_ratio: 量縮門檻
        break_threshold: 突破門檻
        long_red_body_ratio: 長紅 K 線實體佔比

    Returns:
        DataFrame 每檔一列, 欄位:
        - stock_id, 名稱, 市場, 產業, 市值(億)
        - 收盤, MA_fast, MA_mid, MA_slow, upper_ma
        - 夾擊帶寬度%, MA_fast距離%, 上蓋距離%
        - vol_fast(根均量), vol_slow(根均量), 量縮比
        - 突破mid, 突破slow, 近5日內突破 (20根), 實體長紅
        - 訊號, 訊號分數
    """
    rows = []
    for sid in stock_ids:
        try:
            df = kbar_loader.read_stock(sid)
        except FileNotFoundError:
            continue

        if df is None or df.empty or len(df) < ma_slow:
            continue

        # 確保欄位齊全
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col not in df.columns:
                continue

        # 取收盤序列
        close_s = df['Close']
        open_s = df['Open']
        high_s = df['High']
        low_s = df['Low']
        vol_s = df['Volume']

        # 算 MA
        ma_fast_s = close_s.rolling(ma_fast, min_periods=ma_fast).mean()
        ma_mid_s = close_s.rolling(ma_mid, min_periods=ma_mid).mean()
        ma_slow_s = close_s.rolling(ma_slow, min_periods=ma_slow).mean()
        vol_fast_s = vol_s.rolling(vol_fast, min_periods=vol_fast).mean()
        vol_slow_s = vol_s.rolling(vol_slow, min_periods=vol_slow).mean()

        if pd.isna(ma_fast_s.iloc[-1]) or pd.isna(ma_mid_s.iloc[-1]) or pd.isna(ma_slow_s.iloc[-1]):
            continue

        last_idx = df.index[-1]
        last_close = float(close_s.iloc[-1])
        ma_fast_last = float(ma_fast_s.iloc[-1])
        ma_mid_last = float(ma_mid_s.iloc[-1])
        ma_slow_last = float(ma_slow_s.iloc[-1])
        vol_fast_last = float(vol_fast_s.iloc[-1]) if not pd.isna(vol_fast_s.iloc[-1]) else 0
        vol_slow_last = float(vol_slow_s.iloc[-1]) if not pd.isna(vol_slow_s.iloc[-1]) else 0
        vol_ratio = vol_fast_last / vol_slow_last if vol_slow_last > 0 else 1.0

        # 夾擊
        comp_df = detect_compression_root(
            close_s, ma_fast_s, ma_mid_s, ma_slow_s,
            tolerance_pct=tolerance_pct,
        )
        last_comp = comp_df.iloc[-1]
        is_compressed = bool(last_comp['is_compressed'])

        # 量縮
        is_vol_shrink = detect_volume_shrink_root(vol_fast_s, vol_slow_s, threshold=vol_shrink_ratio).iloc[-1]

        # 突破
        bo_df = detect_breakout_root(close_s, ma_mid_s, ma_slow_s, threshold=break_threshold)
        last_bo = bo_df.iloc[-1]
        is_break_mid = bool(last_bo['break_mid'])
        is_break_slow = bool(last_bo['break_slow'])
        is_breakout = is_break_mid or is_break_slow
        recent_break_5d = bool(last_bo['recent_break_5d'])
        recent_break_20d = bool(last_bo['recent_break_20d'])

        # 實體長紅 K 線
        is_long_red = is_long_kbar_root(
            float(open_s.iloc[-1]), last_close,
            float(low_s.iloc[-1]), float(high_s.iloc[-1]),
            body_ratio=long_red_body_ratio,
        )

        # 訊號
        label, score = classify_signal_root(
            is_compressed, is_vol_shrink, is_breakout, is_long_red,
            recent_break_5d=recent_break_5d, recent_break_20d=recent_break_20d,
        )

        if not is_compressed:
            continue

        rows.append({
            'stock_id': sid,
            '名稱': name_map.get(sid, '?'),
            '市場': market_map.get(sid, '?'),
            '產業': industry_map.get(sid, '?'),
            '市值(億)': round(market_cap_map.get(sid, 0) / 1e8, 1) if market_cap_map.get(sid, 0) > 0 else 0,
            '資料時間': last_idx,
            '收盤': last_close,
            f'MA{ma_fast}': round(ma_fast_last, 2),
            f'MA{ma_mid}': round(ma_mid_last, 2),
            f'MA{ma_slow}': round(ma_slow_last, 2),
            'upper_ma': round(max(ma_mid_last, ma_slow_last), 2),
            '夾擊帶寬度%': round(last_comp['band_width_pct'], 2),
            f'MA{ma_fast}距離%': round(last_comp['dist_to_fast_pct'], 2),
            '上蓋距離%': round(last_comp['dist_to_upper_pct'], 2),
            f'量MA{vol_fast}(根)': round(vol_fast_last, 0),
            f'量MA{vol_slow}(根)': round(vol_slow_last, 0),
            '量縮比': round(vol_ratio, 3),
            f'突破MA{ma_mid}': is_break_mid,
            f'突破MA{ma_slow}': is_break_slow,
            '近5日內突破': recent_break_5d,
            '實體長紅': is_long_red,
            '訊號': label,
            '訊號分數': score,
        })

    return pd.DataFrame(rows)


if __name__ == '__main__':
    print("golden_silver_60min module loaded OK")
    print(f"DEFAULT_MA_PERIODS = {DEFAULT_MA_PERIODS} (根, 60分K)")
    print(f"  MA60 ≈ 2.5 日, MA120 ≈ 5 日, MA240 ≈ 10 日")
