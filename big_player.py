#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
big_player.py — 主力訊號指標（從 FinLab 融資買賣公開資料推算）

⚠️ 重要說明 (2026-09-19 重寫)
===============================
原始「主力 / 大戶買賣力」定義 = **當天逐筆內外盤方向**
(外盤量 - 內盤量) 或「特大單+大單 買進 - 賣出」。

**finlab 公開資料有以下限制**（實測 2026-09-19 確認）：
- ❌ `price:內外盤` / `price:外盤量` / `price:內盤量`  → not found
- ❌ `institutional_investors:三大法人買賣超` / 外資買賣超 / 投信 / 自營商 → not found
- ❌ `institutional_investors:借券` → not found
- ❌ `margin_transactions:融資餘額` / `融券餘額` → not found

**唯一可用的「日頻買賣方向」資料：**
- ✅ `margin_transactions:融資買進` (2480 檔, 4348 天)
- ✅ `margin_transactions:融資賣出`
- ✅ `margin_transactions:融券買進`
- ✅ `margin_transactions:融券賣出`

融資 = 投資人借錢買股票（加槓桿看多），所以：
- 融資淨買 > 0 → 槓桿買方加碼（視為「主力加碼」訊號）
- 融資淨買 < 0 → 槓桿買方還錢 / 停損賣出（視為「主力撤離」訊號）
- 融券淨增 > 0 → 放空者加碼（與融資反向）

⚠️ 此為**代理指標**，跟券商逐筆大單資料會有差異，僅供研究參考。
   集保 (inventory) 是「誰持有」週頻資料，不是「當天買賣」日頻方向，
   早期版本誤用集保當大戶買賣力代理是錯誤的，本版已修正。

指標定義
--------
1. **融資淨買 (張)** = 融資買進 - 融資賣出
   - 正：槓桿買方當天加碼
   - 負：槓桿買方當天賣出 / 還錢

2. **融資買賣比 %** = 融資買進 / (融資買進 + 融資賣出) × 100
   - 50% = 平衡, >50% = 買方主導, <50% = 賣方主導
   - 反映「當天融資交易中買方 vs 賣方的相對力道」

3. **融資力 % (5日累計代理)** = 5日累計融資淨買 / 5日累計成交量 × 100
   - 短期主力 (槓桿買方) 籌碼累積方向

4. **融券淨增 (張)** = 融券賣出 - 融券買進
   - 正：放空者加碼
   - 負：空單回補 / 軋空

5. **融資力 5 日累計淨買 (張)** = 5日累計融資淨買 (絕對張數)

訊號分類 (基於「融資力 X 融資買賣比」象限)：
- 🟢 主力進場:  融資力 > +1.5% AND 買賣比 > 55%
- 🔵 主力調節:  融資力 > +1.5% AND 買賣比 ≤ 55%
- 🟠 主力減碼:  -1.5% ≤ 融資力 ≤ +1.5% AND 買賣比 > 60% (買方強但加碼速度放緩)
- 🔴 主力撤離:  融資力 < -1.5%
- ⚪ 盤整觀望:  其他

強弱判斷 (基於融資買賣比)：
- 🟢 買方強勢: > 60%
- 🟡 中性:    40% ~ 60%
- 🔴 賣方強勢: < 40%
"""
from __future__ import annotations

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import pandas as pd
import numpy as np

from finlab import data


# ============================================================
# 0. 抓融資買賣 / 融券 資料 (4 個欄位)
# ============================================================
def _get_margin_data():
    """
    抓 4 個欄位，回傳 dict of DataFrame (columns=stock_id, index=date)

    ⚠️ Streamlit cache 在 page 端用，這裡不包避免 module-level import streamlit
    """
    margin_buy = data.get('margin_transactions:融資買進')   # 融資買進 (張)
    margin_sell = data.get('margin_transactions:融資賣出')  # 融資賣出 (張)
    short_buy = data.get('margin_transactions:融券買進')    # 融券買進 (張) — 空單回補
    short_sell = data.get('margin_transactions:融券賣出')   # 融券賣出 (張) — 新增放空
    return {
        'margin_buy': margin_buy,
        'margin_sell': margin_sell,
        'short_buy': short_buy,
        'short_sell': short_sell,
    }


def _get_volume(stock_id: str) -> pd.Series:
    """個股成交股數（不是張！）"""
    vol = data.get('price:成交股數')
    if stock_id in vol.columns:
        return vol[stock_id].dropna()
    return pd.Series(dtype=float)


# ============================================================
# 1. 日頻融資買賣指標
# ============================================================
def calc_big_player_weekly(stock_id: str) -> pd.DataFrame:
    """
    計算個股主力訊號（日頻）

    ⚠️ 函數名保留舊名 `calc_big_player_weekly` 為相容性，實際指標是日頻。

    columns: date,
             融資買進(張), 融資賣出(張), 融資淨買(張),
             融資買賣比%, 成交量(股),
             融資力_5日累計%, 融資力_5日累計淨買(張),
             融券買進(張), 融券賣出(張), 融券淨增(張),
             訊號, 強弱

    Returns empty DataFrame if stock_id not in 融資買進 columns
    """
    md = _get_margin_data()
    mb: pd.DataFrame = md['margin_buy']
    ms: pd.DataFrame = md['margin_sell']
    sb: pd.DataFrame = md['short_buy']
    ss: pd.DataFrame = md['short_sell']

    if stock_id not in mb.columns:
        return pd.DataFrame()

    margin_buy = mb[stock_id].dropna()
    margin_sell = ms[stock_id].dropna() if stock_id in ms.columns else pd.Series(0, index=margin_buy.index)
    short_buy_s = sb[stock_id].dropna() if stock_id in sb.columns else pd.Series(0, index=margin_buy.index)
    short_sell_s = ss[stock_id].dropna() if stock_id in ss.columns else pd.Series(0, index=margin_buy.index)

    df = pd.DataFrame({
        'date': margin_buy.index,
        '融資買進(張)': margin_buy.values,
        '融資賣出(張)': margin_sell.reindex(margin_buy.index, fill_value=0).values,
        '融券買進(張)': short_buy_s.reindex(margin_buy.index, fill_value=0).values,
        '融券賣出(張)': short_sell_s.reindex(margin_buy.index, fill_value=0).values,
    })
    df['融資淨買(張)'] = df['融資買進(張)'] - df['融資賣出(張)']
    df['融券淨增(張)'] = df['融券賣出(張)'] - df['融券買進(張)']

    # 融資買賣比 % — 反映當天融資交易中買賣雙方力道
    total_margin = df['融資買進(張)'] + df['融資賣出(張)']
    df['融資買賣比%'] = np.where(
        total_margin > 0,
        df['融資買進(張)'] / total_margin * 100,
        50.0  # 沒融資交易 → 當平衡
    )

    # 對齊成交量（日頻，不 resample）
    vol = _get_volume(stock_id)
    vol = vol.reindex(df['date'], fill_value=0)
    df['成交量(股)'] = vol.values

    # 融資力 5 日累計代理指標
    net_5d = df['融資淨買(張)'].rolling(5).sum()
    vol_5d = df['成交量(股)'].rolling(5).sum()
    # 融資淨買單位是「張」, 成交量單位是「股」, 要先把淨買轉成股 (×1000)
    df['融資力_5日累計%'] = np.where(
        vol_5d > 0,
        net_5d * 1000 / vol_5d * 100,  # 淨買(張) × 1000 = 股
        0
    )
    df['融資力_5日累計淨買(張)'] = net_5d

    # 訊號 + 強弱
    df['訊號'] = df.apply(
        lambda r: classify_signal(r['融資力_5日累計%'], r['融資買賣比%']),
        axis=1
    )
    df['強弱'] = df['融資買賣比%'].apply(classify_strength)

    return df.reset_index(drop=True)


# 為了 page 端 import 方便，別名
calc_main_force_daily = calc_big_player_weekly


# ============================================================
# 2. 訊號分類 (基於「融資力 X 融資買賣比」象限)
# ============================================================
def classify_signal(margin_force_pct: float, margin_buy_ratio: float) -> str:
    """
    Parameters
    ----------
    margin_force_pct : float (%) - 融資力 5日累計代理 (5日淨買 / 5日成交量 × 100)
    margin_buy_ratio : float (%) - 融資買賣比 (融資買進 / (融資買進+融資賣出) × 100)
    """
    x = margin_buy_ratio    # 當天買賣力道
    y = margin_force_pct    # 5 日累計方向

    if y > 1.5 and x > 55:
        return "🟢 主力進場"
    elif y > 1.5 and x <= 55:
        return "🔵 主力調節"
    elif -1.5 <= y <= 1.5 and x > 60:
        return "🟠 主力減碼"
    elif y < -1.5:
        return "🔴 主力撤離"
    else:
        return "⚪ 盤整觀望"


# ============================================================
# 3. 強弱判斷 (基於融資買賣比)
# ============================================================
def classify_strength(buy_ratio: float) -> str:
    """
    融資買賣比 > 60%  → 買方強勢
    40% ~ 60%        → 中性
    < 40%             → 賣方強勢
    """
    if buy_ratio > 60:
        return "🟢 買方強勢"
    elif buy_ratio < 40:
        return "🔴 賣方強勢"
    else:
        return "🟡 中性"


# ============================================================
# 4. 多檔個股比較
# ============================================================
def compare_stocks(stock_ids: list[str]) -> pd.DataFrame:
    """多檔個股的最新一日主力指標比較"""
    rows = []
    for sid in stock_ids:
        try:
            df = calc_big_player_weekly(sid)
            if df.empty or len(df) < 2:
                rows.append({'stock_id': sid, 'data': False})
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2]
            rows.append({
                'stock_id': sid,
                'data': True,
                '最新融資淨買(張)': last['融資淨買(張)'],
                '最新融資買賣比%': last['融資買賣比%'],
                '融資力_5日累計%': last['融資力_5日累計%'],
                '訊號': last['訊號'],
                '強弱': last['強弱'],
            })
        except Exception as e:
            rows.append({'stock_id': sid, 'data': False, 'error': str(e)})
    return pd.DataFrame(rows)
