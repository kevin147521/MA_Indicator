#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
big_player.py — 大戶買賣力指標（從 FinLab 集保公開資料推算）

⚠️ 重要說明
============
finlab 公開資料只有 inventory（集保庫存分級）+ price/volume，
**沒有逐筆「特大單/大單/中單/小單」資料**。

本模組用以下代理指標估算「大戶買賣力」：
- 大戶 (持股分級 12-15) 週頻持有股數變化 ＝ 大戶週淨買股數
- 大戶買賣比 (%) ＝ 大戶淨買 / (大戶淨買 + 大戶淨賣) 的絕對值
- 大戶差比 (%)   ＝ (大戶淨買 - 大戶淨賣) / 該週成交量 × 100
- 大戶買賣力 (代理) ＝ 5 週累計淨買股數 × 換手率加權

⚠️ 指標僅供研究參考，跟券商逐筆大單資料會有差異。
"""
from __future__ import annotations

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import pandas as pd
import numpy as np

from finlab import data


# ============================================================
# 0. 集保庫存 → 大戶週頻持有股數
# ============================================================
def _get_big_holder_weekly(stock_id: str) -> pd.DataFrame:
    """
    從 finlab inventory 抽大戶 (持股分級 12-15) 週頻資料：
    columns: date, 人數, 持有股數, 占集保庫存數比例
    """
    inv = data.get('inventory')
    inv = inv.copy()
    inv['持股分級'] = pd.to_numeric(inv['持股分級'], errors='coerce').astype('Int64')

    # 大戶 = 12-15 (約 400 張以上)
    big = inv[inv['持股分級'].between(12, 15, inclusive='both')]
    s = big[big['stock_id'] == stock_id]

    if s.empty:
        return pd.DataFrame(columns=['date', '人數', '持有股數', '占集保庫存數比例'])

    weekly = s.groupby('date').agg({
        '人數': 'sum',
        '持有股數': 'sum',
        '占集保庫存數比例': 'sum',
    }).reset_index().sort_values('date')
    return weekly.reset_index(drop=True)


def _get_volume(stock_id: str) -> pd.Series:
    """個股成交股數"""
    vol = data.get('price:成交股數')
    if stock_id in vol.columns:
        return vol[stock_id].dropna()
    return pd.Series(dtype=float)


# ============================================================
# 1. 大戶週頻淨買股數
# ============================================================
def calc_big_player_weekly(stock_id: str) -> pd.DataFrame:
    """
    計算個股大戶週頻指標
    columns: date, 大戶人數, 大戶持有股數, 大戶持股比例, 成交量, 大戶淨買股數,
             大戶買賣比%, 大戶差比%, 大戶買賣力_代理
    """
    weekly = _get_big_holder_weekly(stock_id)
    if weekly.empty:
        return weekly

    weekly = weekly.set_index('date')
    weekly['大戶淨買股數'] = weekly['持有股數'].diff()  # 正=買超, 負=賣超
    weekly['大戶淨買比例_pp'] = weekly['占集保庫存數比例'].diff() * 100  # pp

    # 對齊成交量（週頻總和）— 用 W-FRI 對齊 inventory 的週五日期
    vol = _get_volume(stock_id)
    weekly_vol = vol.resample('W-FRI').sum().to_frame('成交量')
    weekly = weekly.join(weekly_vol, how='left')
    weekly['成交量'] = weekly['成交量'].fillna(0)

    # 大戶買賣比 (%)：大戶活動度 = |淨買| / 成交量（越接近 100 代表大戶越活躍）
    weekly['大戶買賣比%'] = np.where(
        weekly['成交量'] > 0,
        weekly['大戶淨買股數'].abs() / weekly['成交量'] * 100,
        0
    )

    # 大戶差比 (%)：方向 = 淨買 / 成交量（正=大戶買超，負=大戶賣超）
    weekly['大戶差比%'] = np.where(
        weekly['成交量'] > 0,
        weekly['大戶淨買股數'] / weekly['成交量'] * 100,  # 帶正負號
        0
    )

    # 大戶買賣力 (代理)：5 週累計淨買股數 / 5 週累計成交量
    net_5w = weekly['大戶淨買股數'].rolling(5).sum()
    vol_5w = weekly['成交量'].rolling(5).sum()
    weekly['大戶買賣力_代理%'] = np.where(
        vol_5w > 0,
        net_5w / vol_5w * 100,
        0
    )

    return weekly.reset_index()


# ============================================================
# 2. 判斷族群訊號 (領先/改善/落後/弱化)
# ============================================================
def classify_signal(big_buy_ratio: float, big_diff_ratio: float) -> str:
    """
    根據「大戶買賣比」(主力參與程度 X) 與「大戶差比」(買超力道 Y) 分類：
    - 領先區 (Leading):  X ≥ 70% AND Y ≥ 20%
    - 改善區 (Improving): X < 70% AND Y ≥ 20%
    - 弱化區 (Weakening): X ≥ 70% AND Y < 20%
    - 落後區 (Lagging):  X < 70% AND Y < 20%

    Parameters
    ----------
    big_buy_ratio : float (%) - 大戶買賣比
    big_diff_ratio : float (%) - 大戶差比（取絕對值）
    """
    # 差比用絕對值（看買超或賣超的力道）
    y = abs(big_diff_ratio)
    x = big_buy_ratio
    if x >= 70 and y >= 20:
        return "🟢 領先區 (Leading)"
    elif x < 70 and y >= 20:
        return "🔵 改善區 (Improving)"
    elif x >= 70 and y < 20:
        return "🟠 弱化區 (Weakening)"
    else:
        return "🔴 落後區 (Lagging)"


# ============================================================
# 3. 強度判斷 (基於大戶差比)
# ============================================================
def classify_strength(diff_ratio: float) -> str:
    """
    根據大戶差比判斷強弱：
    - 強勢 (>20% 買超)
    - 中性 (-20% ~ 20%)
    - 弱勢 (<-20% 賣超)
    """
    if diff_ratio > 20:
        return "🟢 強勢（買超力道強）"
    elif diff_ratio < -20:
        return "🔴 弱勢（賣超力道強）"
    else:
        return "🟡 中性（接近平衡）"


# ============================================================
# 4. 主動抓多檔個股比較 (optional)
# ============================================================
def compare_stocks(stock_ids: list[str]) -> pd.DataFrame:
    """多檔個股的最新一週大戶指標比較"""
    rows = []
    for sid in stock_ids:
        try:
            weekly = calc_big_player_weekly(sid)
            if weekly.empty or len(weekly) < 2:
                rows.append({'stock_id': sid, 'data': False})
                continue
            last = weekly.iloc[-1]
            prev = weekly.iloc[-2]
            delta = last['大戶淨買股數'] - prev['大戶淨買股數']
            rows.append({
                'stock_id': sid,
                'data': True,
                '最新大戶持股%': last['占集保庫存數比例'],
                '本週淨買股數': last['大戶淨買股數'],
                '本週大戶買賣比%': last['大戶買賣比%'],
                '本週大戶差比%': last['大戶差比%'],
                '訊號': classify_signal(last['大戶買賣比%'], last['大戶差比%']),
            })
        except Exception as e:
            rows.append({'stock_id': sid, 'data': False, 'error': str(e)})
    return pd.DataFrame(rows)
