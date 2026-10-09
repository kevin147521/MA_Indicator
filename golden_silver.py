"""
golden_silver.py — 「金包銀」型態掃描 (V1 第 10 個 page 用)

定義 (參考 Gemini 整理的新式形態學 SOP):
    「金包銀」= K 棒被下方 60MA (季線) 與上方 120MA/240MA (半年線/年線) 夾擊的壓縮型態。
    多空夾擊 + 量縮 → 變盤前的整理; 帶量突破上蓋 → 進場訊號。

核心計算:
    - 4 條 MA: 5MA / 20MA / 60MA / 120MA / 240MA
    - 夾擊偵測: 收盤價站上 60MA 但未站上 min(120MA, 240MA) (容差帶內)
    - 量縮: 近 5 日均量 < 近 60 日均量 × 0.8
    - 突破偵測: 今日收盤 > 120MA × 1.01 (突破 1% 視為有效)
    - 強弱訊號: 4 個條件各打 1 分, 總分 0-4
"""
import pandas as pd
import numpy as np
from typing import Optional


# 預設門檻常數
DEFAULT_TOLERANCE_PCT = 3.0  # 容差 ±3% (股價在 60MA 上下 3% 內都算「夾擊帶下緣」)
DEFAULT_VOL_SHRINK_RATIO = 0.8  # 量縮: 5日均量 / 60日均量 < 0.8
DEFAULT_BREAK_THRESHOLD = 1.01  # 突破: 收盤 > 上蓋 MA × 1.01
DEFAULT_MA_PERIODS = [5, 20, 60, 120, 240]


def compute_mas(close: pd.DataFrame, periods=(5, 20, 60, 120, 240)) -> dict:
    """
    算多條 MA (回傳 dict: period -> DataFrame)
    自動處理 NaN (前 N 天不足期數時 NaN)
    """
    return {p: close.rolling(p, min_periods=p).mean() for p in periods}


def compute_vol_ma(vol: pd.DataFrame, periods=(5, 20, 60)) -> dict:
    """算成交量 MA"""
    return {p: vol.rolling(p, min_periods=p).mean() for p in periods}


def detect_compression(
    close: pd.Series,
    ma60: pd.Series,
    ma120: pd.Series,
    ma240: pd.Series,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> pd.DataFrame:
    """
    偵測「金包銀夾擊」型態。

    Args:
        close: 收盤價 (1D Series, index=date)
        ma60/ma120/ma240: 對應的均線 (1D Series)
        tolerance_pct: 容差 (%), 收盤在 60MA 上下 tolerance% 內都算「壓縮下緣」

    Returns:
        DataFrame with columns:
        - close: 收盤價
        - ma60/ma120/ma240
        - upper_ma: max(ma120, ma240) 實際作為上蓋 (取較高壓力線)
        - band_width_pct: 夾擊帶寬度 (上蓋 - 下蓋) / 下蓋 × 100
        - dist_to_ma60_pct: 收盤對 60MA 距離 %
        - dist_to_upper_pct: 收盤對上蓋 MA 距離 %
        - is_compressed: 是否在夾擊帶內 (且 MA 順序正確)
    """
    # 上蓋 = 較高的壓力線 (max 120MA / 240MA)
    upper_ma = pd.concat([ma120, ma240], axis=1).max(axis=1)
    upper_ma.name = 'upper_ma'

    out = pd.DataFrame({
        'close': close,
        'ma60': ma60,
        'ma120': ma120,
        'ma240': ma240,
        'upper_ma': upper_ma,
    })
    out['band_width_pct'] = (out['upper_ma'] - out['ma60']) / out['ma60'] * 100
    out['dist_to_ma60_pct'] = (out['close'] - out['ma60']) / out['ma60'] * 100
    out['dist_to_upper_pct'] = (out['upper_ma'] - out['close']) / out['close'] * 100

    # 夾擊條件:
    # 1) 收盤在 60MA 上方 (or 容忍帶內 tolerance_pct) — 站穩下緣
    # 2) 收盤在 upper_ma 下方 (or 容忍帶內 tolerance_pct) — 未突破上緣
    # 3) MA 順序: ma60 < upper_ma (60MA 在上蓋下方, 有夾擊空間)
    cond1 = out['dist_to_ma60_pct'] >= -tolerance_pct
    cond2 = out['dist_to_upper_pct'] >= -tolerance_pct
    cond3 = out['band_width_pct'] > 0
    out['is_compressed'] = cond1 & cond2 & cond3

    return out


def detect_volume_shrink(vol5: pd.Series, vol60: pd.Series, threshold: float = DEFAULT_VOL_SHRINK_RATIO) -> pd.Series:
    """
    偵測量縮: 5日均量 < 60日均量 × threshold
    回傳 bool Series
    """
    ratio = vol5 / vol60
    return ratio < threshold


def detect_breakout(close: pd.Series, ma120: pd.Series, ma240: pd.Series, threshold: float = DEFAULT_BREAK_THRESHOLD) -> pd.DataFrame:
    """
    偵測「突破 K 線」: 收盤 > ma120 × threshold (突破 120MA) 或 > ma240 × threshold (突破 240MA)

    Returns:
        DataFrame with bool columns:
        - break_120: 突破 120MA
        - break_240: 突破 240MA
        - is_breakout: 任一突破
        - recent_break_5d: 近 5 日內任一突破 (突破後回踩)
        - recent_break_20d: 近 20 日內任一突破
    """
    out = pd.DataFrame({
        'close': close,
        'ma120': ma120,
        'ma240': ma240,
    })
    out['break_120'] = out['close'] > out['ma120'] * threshold
    out['break_240'] = out['close'] > out['ma240'] * threshold
    out['is_breakout'] = out['break_120'] | out['break_240']
    # 近期曾突破 (rolling 5/20 日內任一突破)
    out['recent_break_5d'] = out['is_breakout'].rolling(5, min_periods=1).max().astype(bool)
    out['recent_break_20d'] = out['is_breakout'].rolling(20, min_periods=1).max().astype(bool)
    return out


def detect_break_above_ma(close: pd.Series, ma: pd.Series) -> pd.Series:
    """
    偵測「曾站上 MA」: 收盤 > MA (純穿越, 不加 threshold)
    用於判斷「近期是否曾經站上 120MA / 240MA」

    Args:
        close: 收盤價
        ma: 對應均線 (e.g. ma120 / ma240)
    Returns:
        bool Series
    """
    return (close > ma).fillna(False)


def is_long_kbar(open_: float, close: float, low: float, high: float, body_ratio: float = 0.6) -> bool:
    """
    判斷是否為「實體長紅 K 線」(收 > 開 且 實體佔整體 K 棒範圍 ≥ body_ratio)
    """
    if close <= open_:
        return False
    total_range = high - low
    if total_range <= 0:
        return False
    body = close - open_
    return (body / total_range) >= body_ratio


def classify_signal(
    is_compressed: bool,
    is_vol_shrink: bool,
    is_breakout_now: bool,
    is_long_red: bool,
    recent_break_5d: bool = False,
    recent_break_20d: bool = False,
) -> tuple[str, int]:
    """
    綜合 4 條件 → 訊息 + 分數 (0-4)

    Returns:
        (label, score)
        label: '🟢 突破表態' / '🟡 量縮整理' / '⚪ 觀察' / '🔴 不符'
        score: 0-4 (夾擊+量縮+現在突破+曾突破 = 4 分)
    """
    # 突破分: 0 (沒突破) / 0.5 (近期 5 日) / 1 (現在)
    breakout_score = 0
    if is_breakout_now:
        breakout_score = 1
    elif recent_break_5d:
        breakout_score = 0.5
    elif recent_break_20d:
        breakout_score = 0.25

    # 訊號分 (0-4 整數)
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
# 全市場掃描 (主入口)
# ============================================================
def scan_golden_silver(
    stock_ids: list[str],
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    vol_df: pd.DataFrame,
    market_cap_map: dict,
    market_map: dict,
    name_map: dict,
    industry_map: dict,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    vol_shrink_ratio: float = DEFAULT_VOL_SHRINK_RATIO,
    break_threshold: float = DEFAULT_BREAK_THRESHOLD,
    long_red_body_ratio: float = 0.6,
) -> pd.DataFrame:
    """
    掃描全市場「金包銀」型態股票

    Args:
        stock_ids: 要掃的個股清單 (純股票)
        close_df/open_df/high_df/low_df/vol_df: finlab 抓的 5 個 K 線/量資料 (columns=stock_id, index=date)
        market_cap_map / market_map / name_map / industry_map: 對應的 metadata
        tolerance_pct: 夾擊容差 (%)
        vol_shrink_ratio: 量縮門檻 (5日/60日 量比 < 此值)
        break_threshold: 突破門檻 (收盤 / 上蓋 MA > 此值算突破)
        long_red_body_ratio: 長紅 K 線實體佔比

    Returns:
        DataFrame 每檔一列, 欄位:
        - stock_id, 名稱, 市場, 產業, 市值(億)
        - 收盤, 60MA, 120MA, 240MA, upper_ma
        - 夾擊帶寬度%, 60MA距離%, 上蓋距離%
        - 5日均量, 60日均量, 量縮比
        - 突破120, 突破240, 實體長紅
        - 訊號, 訊號分數 (0-4)
    """
    # 算 MA
    mas = compute_mas(close_df, periods=(5, 20, 60, 120, 240))
    mas_vol = compute_vol_ma(vol_df, periods=(5, 60))

    rows = []
    for sid in stock_ids:
        if sid not in close_df.columns:
            continue
        # 取該股序列 (最後一天)
        close_s = close_df[sid].dropna()
        open_s = open_df[sid].dropna() if sid in open_df.columns else pd.Series(dtype=float)
        high_s = high_df[sid].dropna() if sid in high_df.columns else pd.Series(dtype=float)
        low_s = low_df[sid].dropna() if sid in low_df.columns else pd.Series(dtype=float)
        vol_s = vol_df[sid].dropna() if sid in vol_df.columns else pd.Series(dtype=float)

        if len(close_s) < 240:  # 至少 240 天才能算 240MA
            continue

        last_date = close_s.index[-1]
        last_close = float(close_s.iloc[-1])
        ma60_last = float(mas[60][sid].loc[last_date])
        ma120_last = float(mas[120][sid].loc[last_date])
        ma240_last = float(mas[240][sid].loc[last_date])
        ma20_last = float(mas[20][sid].loc[last_date])

        if any(pd.isna([ma60_last, ma120_last, ma240_last])):
            continue

        # 夾擊偵測
        comp_df = detect_compression(
            close_s, mas[60][sid], mas[120][sid], mas[240][sid],
            tolerance_pct=tolerance_pct,
        )
        last_comp = comp_df.iloc[-1]
        is_compressed = bool(last_comp['is_compressed'])

        # 量縮
        vol5_last = float(mas_vol[5][sid].loc[last_date]) if not pd.isna(mas_vol[5][sid].loc[last_date]) else 0
        vol60_last = float(mas_vol[60][sid].loc[last_date]) if not pd.isna(mas_vol[60][sid].loc[last_date]) else 0
        vol_ratio = vol5_last / vol60_last if vol60_last > 0 else 1.0
        is_vol_shrink = vol_ratio < vol_shrink_ratio

        # 突破
        bo_df = detect_breakout(close_s, mas[120][sid], mas[240][sid], threshold=break_threshold)
        last_bo = bo_df.iloc[-1]
        is_break_120 = bool(last_bo['break_120'])
        is_break_240 = bool(last_bo['break_240'])
        is_breakout = is_break_120 or is_break_240
        recent_break_5d = bool(last_bo['recent_break_5d'])
        recent_break_20d = bool(last_bo['recent_break_20d'])

        # 實體長紅 K 線 (今日)
        if not open_s.empty and not high_s.empty and not low_s.empty:
            is_long_red = is_long_kbar(
                float(open_s.iloc[-1]), last_close,
                float(low_s.iloc[-1]), float(high_s.iloc[-1]),
                body_ratio=long_red_body_ratio,
            )
        else:
            is_long_red = False

        # 訊號 + 分數
        label, score = classify_signal(
            is_compressed, is_vol_shrink, is_breakout, is_long_red,
            recent_break_5d=recent_break_5d, recent_break_20d=recent_break_20d,
        )

        # 沒夾擊的股票不加入結果 (「金包銀」核心是「夾擊」, 不算夾擊就不算金包銀)
        if not is_compressed:
            continue

        rows.append({
            'stock_id': sid,
            '名稱': name_map.get(sid, '?'),
            '市場': market_map.get(sid, '?'),
            '產業': industry_map.get(sid, '?'),
            '市值(億)': round(market_cap_map.get(sid, 0) / 1e8, 1) if market_cap_map.get(sid, 0) > 0 else 0,
            '收盤': last_close,
            '60MA': round(ma60_last, 2),
            '120MA': round(ma120_last, 2),
            '240MA': round(ma240_last, 2),
            'upper_ma': round(min(ma120_last, ma240_last), 2),
            '夾擊帶寬度%': round(last_comp['band_width_pct'], 2),
            '60MA距離%': round(last_comp['dist_to_ma60_pct'], 2),
            '上蓋距離%': round(last_comp['dist_to_upper_pct'], 2),
            '5日均量(張)': round(vol5_last / 1000, 1) if vol5_last > 0 else 0,
            '60日均量(張)': round(vol60_last / 1000, 1) if vol60_last > 0 else 0,
            '量縮比': round(vol_ratio, 3),
            '突破120MA': is_break_120,
            '突破240MA': is_break_240,
            '近5日內突破': recent_break_5d,
            '實體長紅': is_long_red,
            '訊號': label,
            '訊號分數': score,
        })

    return pd.DataFrame(rows)


if __name__ == '__main__':
    # smoke test
    print("golden_silver module loaded OK")
    print(f"DEFAULT_TOLERANCE_PCT = {DEFAULT_TOLERANCE_PCT}")
    print(f"DEFAULT_VOL_SHRINK_RATIO = {DEFAULT_VOL_SHRINK_RATIO}")
    print(f"DEFAULT_BREAK_THRESHOLD = {DEFAULT_BREAK_THRESHOLD}")
