#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
portfolio_strategy.py — 基因策略組合 helper（從 Finlab組合策略_20260226.ipynb 抽出）

內容：
- `load_features()` — 統一抓原始資料 + 計算共同特徵（cell 1-6 共享的 ~300 行）
- `CONDITIONS`     — 41 個條件函式 (cond1-cond41)，每個 fn(features) 回傳 FinlabDataFrame
- `PRESET_COMBOS`  — 22 個歷史 best 組合（從 notebook cell 註解的 CAGR/MDD/Sortino/勝率抄出）
- `run_backtest()` — 跑 sim() 的 wrapper（去掉 upload=True 避免扣 quota）
- `monte_carlo_stress_test()` — 蒙地卡羅壓力測試 (cell 10)
- `omega_score()` — 對大盤的 Omega Ratio (cell 9)

用法 (在 portfolio_strategy_page.py)：
    features = load_features()
    active = {'cond1', 'cond4', 'cond24', 'cond25', 'cond31'}
    cond_all = combine_conditions(active, features)
    report = run_backtest(cond_all, features, position_limit=1/3)
    stats = monte_carlo_stress_test(report, iterations=1000)
"""
from __future__ import annotations

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import json
import numpy as np
import pandas as pd

from pathlib import Path

from finlab import data
from finlab.backtest import sim


# ============================================================
# 0. 共用特徵載入（cell 1-6 完全相同區段）
# ============================================================
def load_features():
    """
    抓 cell 1-6 共用的原始資料 + 計算派生特徵。
    第一次跑 ~30 秒，後續 cache 加速。

    Returns
    -------
    dict : {'close', 'volume', 'turnover', 'rev', 'rev_yoy_growth', ...,
            'rsi20', 'k', 'd', 'atr', 'adj_close', 'entry_volatility',
            'newhigh', '市值', 'big_holder_increasing', ...}
    """
    close = data.get('price:收盤價').index_str_to_date().fillna(0)
    volume = data.get('price:成交股數').index_str_to_date().fillna(0)
    turnover = data.get("price:成交金額").index_str_to_date().fillna(0)

    rev = data.get('monthly_revenue:當月營收').index_str_to_date().fillna(0)
    rev_yoy_growth = data.get('monthly_revenue:去年同月增減(%)').ffill().index_str_to_date().reindex(rev.index).ffill()
    rev_ffill = rev.ffill()

    股本_季 = data.get('financial_statement:股本').index_str_to_date().fillna(0)

    # 特徵
    rev_ma1 = rev_ffill.average(1)
    rev_ma2 = rev_ffill.average(2)
    rev_ma12 = rev_ffill.average(12)
    rev_ma24 = rev_ffill.average(24)

    rsv = (close - close.rolling(120).min()) / (close.rolling(120).max() - close.rolling(120).min())

    # 市值計算（含 par value adjustment）
    股本 = data.get('financial_statement:股本').ffill().index_str_to_date().reindex(股本_季.index).ffill()
    empty_df = pd.DataFrame(1, columns=close.columns, index=close.index)
    tse_par = data.get('par_value_change_tse:twse_par_value_change_divide_ratio')
    otc_par = data.get('par_value_change_otc:otc_par_value_change_divide_ratio')
    tse_divide_ratio = (empty_df * tse_par).fillna(1).cumprod()
    otc_divide_ratio = (empty_df * otc_par).fillna(1).cumprod()
    par_divide_ratio = tse_divide_ratio * otc_divide_ratio
    市值 = 股本 * close / 10 * 1000 * par_divide_ratio

    # 財報
    eps = data.get('financial_statement:每股盈餘').ffill().index_str_to_date().reindex(股本_季.index).ffill()
    營業利益率 = data.get("fundamental_features:營業利益率").ffill().index_str_to_date().reindex(股本_季.index).ffill()
    毛利率 = data.get('fundamental_features:營業毛利率').ffill().index_str_to_date().reindex(股本_季.index).ffill()

    # 技術指標
    rsi20 = data.indicator("RSI", timeperiod=20)
    k, d = data.indicator('STOCH', resample='D', timeperiod=14, fastk_period=9, slowk_period=3, slowd_period=3)
    atr = data.indicator('ATR', adjust_price=True, timeperiod=10)
    adj_close = data.get('etl:adj_close').index_str_to_date().fillna(0)
    entry_volatility = atr / adj_close
    newhigh = close.rolling(60, min_periods=1).max() == close

    market_value_closedate = data.get('etl:market_value').ffill().index_str_to_date().reindex(close.index).ffill()
    market_value_revdate = data.get('etl:market_value').ffill().index_str_to_date().reindex(rev.index).ffill()

    vol_ma5 = volume.average(5)
    vol_ma20 = volume.average(20)
    turnover_top = turnover.rank(axis=1, ascending=False)

    # 大戶籌碼
    inventory = data.get("inventory")
    inventory['持股分級'] = pd.to_numeric(inventory['持股分級'], errors='coerce')
    df_filtered = inventory[inventory['持股分級'].between(12, 15, inclusive='both')]
    result = df_filtered.groupby(['stock_id', 'date']).agg({'占集保庫存數比例': 'sum'}).reset_index().sort_values(['stock_id', 'date'])
    result['持股比例變動'] = result.groupby('stock_id')['占集保庫存數比例'].diff()
    big_holder_ratio_change = result.pivot_table(index='date', columns='stock_id', values='持股比例變動', fill_value=0)
    big_holder_increasing = big_holder_ratio_change.rolling(3).sum()

    return {
        'close': close, 'volume': volume, 'turnover': turnover,
        'rev': rev, 'rev_yoy_growth': rev_yoy_growth, 'rev_ffill': rev_ffill,
        '股本_季': 股本_季, '股本': 股本, '市值': 市值,
        'eps': eps, '營業利益率': 營業利益率, '毛利率': 毛利率,
        'rsi20': rsi20, 'k': k, 'd': d,
        'atr': atr, 'adj_close': adj_close, 'entry_volatility': entry_volatility,
        'newhigh': newhigh,
        'market_value_closedate': market_value_closedate, 'market_value_revdate': market_value_revdate,
        'vol_ma5': vol_ma5, 'vol_ma20': vol_ma20, 'turnover_top': turnover_top,
        'big_holder_increasing': big_holder_increasing,
        # 額外導出
        'rev_ma1': rev_ma1, 'rev_ma2': rev_ma2, 'rev_ma12': rev_ma12, 'rev_ma24': rev_ma24,
        'rsv': rsv,
        'cond12_rank': 市值.rank(axis=1, ascending=False) <= 300,
        'cond25_logic': newhigh.rolling(30).sum() > 0,
    }


# ============================================================
# 1. 41 個條件函式（每個 cond_X = lambda f: ...）
# ============================================================
# 用 lambda 取 features dict 計算條件，回傳 FinlabDataFrame bool
CONDITIONS = {
    'cond1':  lambda f: (f['rev_ma1']/f['rev_ma24']>1.2) & (f['rsv']>0.7) & (f['rsi20'].pct_change(13) > 0.02) & (f['營業利益率'] > 0),
    'cond2':  lambda f: f['rev_ma1']/f['rev_ma24']>1.2,
    'cond3':  lambda f: f['rev_ma2']/f['rev_ma24']>1.1,
    'cond4':  lambda f: f['rsi20'].ffill().pct_change(6) > 0.03,
    'cond5':  lambda f: f['rsi20'].ffill().pct_change(5) > 0.02,
    'cond6':  lambda f: f['rsi20'].pct_change(13) > 0.02,
    'cond7':  lambda f: f['rsv']>0.7,
    'cond8':  lambda f: f['營業利益率'] > 0,
    'cond9':  lambda f: f['營業利益率'] > -5,
    'cond10': lambda f: f['毛利率'] > 5,
    'cond11': lambda f: f['turnover'] >= f['turnover'].index_str_to_date().quantile_row(0.5),
    'cond12': lambda f: f['cond12_rank'],
    'cond13': lambda f: f['close'] > f['close'].shift(120),
    'cond14': lambda f: f['close'] > f['close'].shift(60),
    'cond15': lambda f: ((f['close'] > f['close'].average(200)) & (f['close'] > f['close'].average(150))),
    'cond16': lambda f: f['rev_yoy_growth'].average(2) > 20,
    'cond17': lambda f: (f['rev_yoy_growth'] > 5).sustain(12, 5),
    'cond18': lambda f: f['rev_yoy_growth'] < 500,
    'cond19': lambda f: f['rev_ffill'] > f['rev_ffill'].shift(6),
    'cond20': lambda f: f['eps'] > f['eps'].shift(4),
    'cond21': lambda f: f['k'] > 40,
    'cond22': lambda f: f['d'] > 20,
    'cond23': lambda f: f['entry_volatility'] <= 0.055,
    'cond24': lambda f: f['entry_volatility'] <= 0.06,
    'cond25': lambda f: f['cond25_logic'],
    'cond26': lambda f: (f['volume'] >= f['volume'].rolling(20).mean()*0.8).sustain(5, 2),
    'cond27': lambda f: f['close'].pct_change().rolling(230).kurt() > 0,
    'cond28': lambda f: f['close'] == f['close'].rolling(60).max(),
    'cond29': lambda f: f['big_holder_increasing'] > 0,
    'cond30': lambda f: f['close'] == f['close'].rolling(10).max(),
    'cond31': lambda f: f['close'] == f['close'].rolling(20).max(),
    'cond32': lambda f: (f['vol_ma5'] > f['vol_ma20'] * 1.1),
    'cond33': lambda f: f['turnover_top'] <= 200,
    'cond34': lambda f: (f['vol_ma5'] > f['vol_ma20'] * 1.5),
    'cond35': lambda f: f['turnover_top'] <= 300,
    'cond36': lambda f: (f['vol_ma5'] > f['vol_ma20'] * 2),
    'cond37': lambda f: (f['vol_ma5'] > f['vol_ma20'] * 1.8),
    'cond38': lambda f: (f['vol_ma5'] > f['vol_ma20'] * 2.5),
    'cond39': lambda f: f['market_value_revdate'] > f['market_value_closedate'].rolling(20).mean(),
    'cond40': lambda f: f['market_value_revdate'] > f['market_value_closedate'].rolling(50).mean(),
    'cond41': lambda f: f['market_value_revdate'] > f['market_value_closedate'].rolling(60).mean(),
}

# 條件中文標籤（給 Streamlit UI 用）
CONDITION_LABELS = {
    'cond1':  '營收爆發 + RSV 高 + RSI 漲 + 營業利益率>0',
    'cond2':  '近月營收/月24 > 1.2',
    'cond3':  '近2月營收/月24 > 1.1',
    'cond4':  'RSI 6日漲幅 > 3%',
    'cond5':  'RSI 5日漲幅 > 2%',
    'cond6':  'RSI 13日漲幅 > 2%',
    'cond7':  'RSV > 0.7（近 120 日接近新高）',
    'cond8':  '營業利益率 > 0',
    'cond9':  '營業利益率 > -5',
    'cond10': '毛利率 > 5%',
    'cond11': '成交金額 > 全市場中位數',
    'cond12': '市值排名前 300',
    'cond13': '收盤 > 120 日前收盤',
    'cond14': '收盤 > 60 日前收盤',
    'cond15': '收盤 > MA200 + MA150',
    'cond16': '近2月營收年增率平均 > 20%',
    'cond17': '近12個月有5個月營收年增 > 5%',
    'cond18': '營收年增率 < 500%（過濾泡沫股）',
    'cond19': '近月營收 > 6個月前',
    'cond20': 'EPS > 4 季前',
    'cond21': 'KD_K > 40',
    'cond22': 'KD_D > 20',
    'cond23': '進場波動率 ≤ 5.5%',
    'cond24': '進場波動率 ≤ 6%',
    'cond25': '近 30 日曾創 60 日新高',
    'cond26': '成交量 ≥ 20日均量 × 0.8 持續 5 日',
    'cond27': '近 230 日報酬峰度 > 0',
    'cond28': '收盤 = 60 日最高',
    'cond29': '大戶（持股 12-15 級）持股比例上升',
    'cond30': '收盤 = 10 日最高',
    'cond31': '收盤 = 20 日最高',
    'cond32': '5日均量 > 20日均量 × 1.1',
    'cond33': '成交金額排名前 200',
    'cond34': '5日均量 > 20日均量 × 1.5',
    'cond35': '成交金額排名前 300',
    'cond36': '5日均量 > 20日均量 × 2.0',
    'cond37': '5日均量 > 20日均量 × 1.8',
    'cond38': '5日均量 > 20日均量 × 2.5',
    'cond39': '營收日市值 > 收盤日市值 20日均',
    'cond40': '營收日市值 > 收盤日市值 50日均',
    'cond41': '營收日市值 > 收盤日市值 60日均',
}


# ============================================================
# 2. 22 個歷史 best 組合（從 notebook cell 1-6, 17, 18 註解放）
#    格式：{name, conditions: ['cond1', 'cond4', ...], stats: {CAGR, MDD, Sortino, 月損益, 月勝率}, source: "cell N"}
# ============================================================
PRESET_COMBOS = [
    {
        'name': '🏆 cond1 & cond4 & cond28 (CAGR 138.5%)',
        'conditions': ['cond1', 'cond4', 'cond28'],
        'stats': {'CAGR': 138.5, 'MDD': -22.9, 'Sortino': 5.0, 'Omega': 2.79, '勝率': 60.4, '月損益(萬)': 382, '月勝率': 79.8},
        'source': 'notebook cell 註解',
    },
    {
        'name': '🥇 cond1 & cond21 & cond30 & cond32 (CAGR 138.5%)',
        'conditions': ['cond1', 'cond21', 'cond30', 'cond32'],
        'stats': {'CAGR': 138.5, 'MDD': -23.4, 'Sortino': 5.33, 'Omega': 2.96, '勝率': 61.3, '月損益(萬)': 337, '月勝率': 82.1},
        'source': 'notebook cell 註解',
    },
    {
        'name': '🥈 cond1 & cond4 & cond30 & cond32 (CAGR 137%)',
        'conditions': ['cond1', 'cond4', 'cond30', 'cond32'],
        'stats': {'CAGR': 137.0, 'MDD': -22.2, 'Sortino': 5.29, 'Omega': 2.93, '勝率': 61.3, '月損益(萬)': 365, '月勝率': 83.3},
        'source': 'notebook cell 註解',
    },
    {
        'name': '🥉 cond1 & cond21 & cond23 & cond25 & cond30 (CAGR 130.7%)',
        'conditions': ['cond1', 'cond21', 'cond23', 'cond25', 'cond30'],
        'stats': {'CAGR': 130.7, 'MDD': -21.2, 'Sortino': 5.22, 'Omega': 2.93, '勝率': 61.4, '月損益(萬)': 361, '月勝率': 78.6},
        'source': 'notebook cell 註解',
    },
    {
        'name': 'cond1 & cond4 & cond25 & cond30 (CAGR 138.5%)',
        'conditions': ['cond1', 'cond4', 'cond25', 'cond30'],
        'stats': {'CAGR': 138.5, 'MDD': -29.5, 'Sortino': 5.26, 'Omega': 2.92, '勝率': 60.3, '月損益(萬)': 383, '月勝率': 82.1},
        'source': 'notebook cell 註解',
    },
    {
        'name': 'cond1 & cond4 & cond26 & cond28 (CAGR 132.7%)',
        'conditions': ['cond1', 'cond4', 'cond26', 'cond28'],
        'stats': {'CAGR': 132.7, 'MDD': -22.9, 'Sortino': 4.80, 'Omega': 2.71, '勝率': 59.7, '月損益(萬)': 380, '月勝率': 78.6},
        'source': 'notebook cell 註解',
    },
    {
        'name': 'cond1 & cond4 & cond24 & cond25 & cond30 (CAGR 137%)',
        'conditions': ['cond1', 'cond4', 'cond24', 'cond25', 'cond30'],
        'stats': {'CAGR': 137.0, 'MDD': -25.5, 'Sortino': 5.29, 'Omega': 2.96, '勝率': 62.3, '月損益(萬)': 380, '月勝率': 82.1},
        'source': 'notebook cell 註解',
    },
    {
        'name': 'cond1 & cond4 & cond24 & cond25 & cond31 (CAGR 136.1%)',
        'conditions': ['cond1', 'cond4', 'cond24', 'cond25', 'cond31'],
        'stats': {'CAGR': 136.1, 'MDD': -25.0, 'Sortino': 5.31, 'Omega': 2.94, '勝率': 62.8, '月損益(萬)': 370, '月勝率': 81.0},
        'source': 'notebook cell 註解',
    },
    {
        'name': 'cond1 & cond4 & cond24 & cond25 & cond30 & cond31 (CAGR 136.1%)',
        'conditions': ['cond1', 'cond4', 'cond24', 'cond25', 'cond30', 'cond31'],
        'stats': {'CAGR': 136.1, 'MDD': -25.0, 'Sortino': 5.31, 'Omega': 2.94, '勝率': 62.8, '月損益(萬)': 370, '月勝率': 81.0},
        'source': 'notebook cell 註解',
    },
    {
        'name': 'cond1 & cond4 & cond31 & cond32 (CAGR 133.8%)',
        'conditions': ['cond1', 'cond4', 'cond31', 'cond32'],
        'stats': {'CAGR': 133.8, 'MDD': -24.6, 'Sortino': 5.08, 'Omega': 2.84, '勝率': 61.3, '月損益(萬)': 353, '月勝率': 82.1},
        'source': 'notebook cell 註解',
    },
    # cell 17/18 的 12 條件最佳組合
    {
        'name': '🚀 12 條件最強 (CAGR 200.6%)',
        'conditions': ['cond2', 'cond5', 'cond6', 'cond7', 'cond8', 'cond11', 'cond12', 'cond15', 'cond16', 'cond19', 'cond21', 'cond22', 'cond24', 'cond25'],
        'stats': {'CAGR': 200.6, 'MDD': -27.9, 'Sortino': 6.41, 'Omega': 3.48, '勝率': 63.9, '月損益(萬)': 348, '月勝率': 0.0},
        'source': 'notebook cell 17 註解',
    },
    {
        'name': 'cond2 & cond5 & cond6 & cond7 & cond8 & cond11 & cond12 & cond16 & cond19 & cond21 & cond22 & cond24 (CAGR 200%)',
        'conditions': ['cond2', 'cond5', 'cond6', 'cond7', 'cond8', 'cond11', 'cond12', 'cond16', 'cond19', 'cond21', 'cond22', 'cond24'],
        'stats': {'CAGR': 200.0, 'MDD': -27.9, 'Sortino': 6.43, 'Omega': 3.49, '勝率': 64.0, '月損益(萬)': 351, '月勝率': 0.0},
        'source': 'notebook cell 17 註解',
    },
    {
        'name': 'cond1 & cond6 & cond8 & cond11 & cond12 & cond16 & cond21 & cond24 (CAGR 195%)',
        'conditions': ['cond1', 'cond6', 'cond8', 'cond11', 'cond12', 'cond16', 'cond21', 'cond24'],
        'stats': {'CAGR': 195.0, 'MDD': -23.5, 'Sortino': 6.37, 'Omega': 3.44, '勝率': 63.9, '月損益(萬)': 388, '月勝率': 0.0},
        'source': 'notebook cell 17 註解',
    },
    {
        'name': 'cond1 & cond6 & cond8 & cond10 & cond11 & cond12 & cond16 & cond21 & cond24 & cond25 (CAGR 171%)',
        'conditions': ['cond1', 'cond6', 'cond8', 'cond10', 'cond11', 'cond12', 'cond16', 'cond21', 'cond24', 'cond25'],
        'stats': {'CAGR': 171.0, 'MDD': -22.9, 'Sortino': 5.87, 'Omega': 3.24, '勝率': 62.0, '月損益(萬)': 390, '月勝率': 0.0},
        'source': 'notebook cell 17 註解',
    },
    {
        'name': 'cond1 & cond3 & cond6 & cond8 & cond10 & cond11 & cond12 & cond16 & cond22 & cond24 & cond25 (CAGR 164%)',
        'conditions': ['cond1', 'cond3', 'cond6', 'cond8', 'cond10', 'cond11', 'cond12', 'cond16', 'cond22', 'cond24', 'cond25'],
        'stats': {'CAGR': 164.0, 'MDD': -21.0, 'Sortino': 5.69, 'Omega': 3.16, '勝率': 61.1, '月損益(萬)': 415, '月勝率': 0.0},
        'source': 'notebook cell 17 註解',
    },
]


# ============================================================
# 2.5. Portfolio 預設組合（notebook cell 7-8 的 4 策略 1/4 權重）
# ============================================================
PORTFOLIO_PRESETS = [
    {
        'name': '組合 1 (notebook cell 7)',
        'description': '基因比對_營收KD值高_MDD低 + 策略2_Finlab + 均線型態_成交量成長_十日線以上 + 策略10_Finlab',
        'strategies': [
            {'name': '基因比對_營收KD值高_MDD低',     'conditions': ['cond2', 'cond6', 'cond7', 'cond8', 'cond9', 'cond12', 'cond13', 'cond15', 'cond16', 'cond19', 'cond22', 'cond25'], 'cell': '17', 'weight': 0.25},
            {'name': '策略2_Finlab',                  'conditions': ['cond1', 'cond4', 'cond24', 'cond25', 'cond31'],                                                                'cell': '2',  'weight': 0.25},
            {'name': '均線型態_成交量成長_十日線以上', 'conditions': ['cond1', 'cond2', 'cond6', 'cond8', 'cond13', 'cond19', 'cond26', 'cond30', 'cond32'],                                'cell': '6',  'weight': 0.25},
            {'name': '策略10_Finlab',                 'conditions': ['cond1', 'cond8', 'cond30', 'cond32'],                                                                          'cell': '5',  'weight': 0.25},
        ],
    },
    {
        'name': '組合 2 (notebook cell 8)',
        'description': '基因比對_營收KD值高_MDD低 + 策略2_Finlab + 策略4_Finlab + 策略8_Finlab',
        'strategies': [
            {'name': '基因比對_營收KD值高_MDD低', 'conditions': ['cond2', 'cond6', 'cond7', 'cond8', 'cond9', 'cond12', 'cond13', 'cond15', 'cond16', 'cond19', 'cond22', 'cond25'], 'cell': '17', 'weight': 0.25},
            {'name': '策略2_Finlab',              'conditions': ['cond1', 'cond4', 'cond24', 'cond25', 'cond31'],                                                                'cell': '2',  'weight': 0.25},
            {'name': '策略4_Finlab',              'conditions': ['cond1', 'cond4', 'cond28'],                                                                                      'cell': '3',  'weight': 0.25},
            {'name': '策略8_Finlab',              'conditions': ['cond1', 'cond4', 'cond24', 'cond25', 'cond31'],                                                                'cell': '4',  'weight': 0.25},
        ],
    },
]


def save_portfolio_data_version(version: str, data_version: dict) -> Path:
    """存資料版本到 V2 SQLite + JSON"""
    import sqlite3
    DB_PATH = Path.home() / ".openclaw" / "ma_indicator_data" / "portfolio_versions.db"
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_versions (
        version            TEXT PRIMARY KEY,
        date               TEXT NOT NULL,
        composition        TEXT,
        finlab_version     TEXT,
        raw_json           TEXT NOT NULL,
        n_strategies       INTEGER,
        portfolio_cagr     REAL,
        portfolio_mdd      REAL,
        portfolio_sortino  REAL,
        portfolio_sharpe   REAL,
        portfolio_calmar   REAL,
        omega_vs_market    REAL,
        created_at         TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    INSERT OR REPLACE INTO portfolio_versions (
        version, date, composition, finlab_version, raw_json,
        n_strategies, portfolio_cagr, portfolio_mdd, portfolio_sortino,
        portfolio_sharpe, portfolio_calmar, omega_vs_market
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        version, data_version['date'], data_version['composition'],
        data_version.get('finlab_version', '2.0.16'),
        json.dumps(data_version, ensure_ascii=False, indent=2),
        len(data_version['strategies']),
        data_version['portfolio_stats'].get('cagr'),
        data_version['portfolio_stats'].get('max_drawdown'),
        data_version['portfolio_stats'].get('daily_sortino'),
        data_version['portfolio_stats'].get('daily_sharpe'),
        data_version['portfolio_stats'].get('calmar'),
        data_version.get('omega_vs_market'),
    ))
    conn.commit()
    conn.close()

    # 同步存 JSON
    json_dir = Path("/Users/kevin/Desktop/排程運算/MA_Indicator/data/portfolio_versions")
    json_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_dir / f"{version}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data_version, f, ensure_ascii=False, indent=2)
    return json_path


def compose_portfolio(preset: dict, features: dict, progress_callback=None):
    """跑 preset 內每個策略 + 組合成 Portfolio"""
    from finlab.portfolio import Portfolio

    strategy_reports = {}
    strategy_stats = {}
    for i, s in enumerate(preset['strategies']):
        if progress_callback:
            progress_callback(i, len(preset['strategies']), f"跑 {s['name']} ({len(s['conditions'])} 條件)")
        report = run_backtest(s['conditions'], features, progress_callback=None)
        stats = extract_report_stats(report)
        strategy_reports[s['name']] = report
        strategy_stats[s['name']] = {
            'cagr': stats['annual_return'], 'total_return': stats['total_return'],
            'max_drawdown': stats['max_drawdown'], 'daily_sortino': stats['daily_sortino'],
            'daily_sharpe': stats['daily_sharpe'], 'calmar': stats['calmar'],
            'win_ratio': stats['win_ratio'],
            'cell': s.get('cell', '?'), 'n_conditions': len(s['conditions']),
            'conditions': s['conditions'],
        }

    if progress_callback:
        progress_callback(len(preset['strategies']), len(preset['strategies']), '組合 Portfolio...')

    port = Portfolio({
        s['name']: (strategy_reports[s['name']], s.get('weight', 1.0/len(preset['strategies'])))
        for s in preset['strategies']
    })
    port_stats = port.get_stats()

    return {
        'port': port,
        'strategy_stats': strategy_stats,
        'port_stats': port_stats,
    }


# ============================================================
# 3. 跑回測的 helper
# ============================================================
def combine_conditions(active_names: list[str], features: dict):
    """
    根據啟用的條件清單組合成 cond_all (AND of all)

    Parameters
    ----------
    active_names : e.g. ['cond1', 'cond4', 'cond24', 'cond25', 'cond31']
    features : load_features() 回傳的 dict

    Returns
    -------
    FinlabDataFrame bool
    """
    if not active_names:
        raise ValueError("至少要啟用一個條件")
    result = CONDITIONS[active_names[0]](features)
    for name in active_names[1:]:
        result = result & CONDITIONS[name](features)
    return result


def build_position(active_names: list[str], features: dict, nstocks_limit: int = 5):
    """
    從 cond 組合建出 position DataFrame（沿用 cell 1-6 的買賣邏輯）

    買入：cond_all 為 true 且 volume.average(6) > 200*1000，取 rev_yoy_growth 前 nstocks_limit 大
    賣出條件（沿用 cell）：rebalance (sell1) + close>2.1 倍 20 日前 持續 3 日 (sell2)
    """
    rev = features['rev']
    rev_yoy_growth = features['rev_yoy_growth']
    close = features['close']
    volume = features['volume']
    entry_volatility = features['entry_volatility']

    cond_all = combine_conditions(active_names, features)

    result = rev_yoy_growth * cond_all * (volume.average(6) > 200*1000)
    buy = result[result > 0].is_largest(nstocks_limit).reindex(rev.index_str_to_date().index, method='ffill')
    sell1 = buy.reindex(rev.index_str_to_date().index - pd.DateOffset(days=4), method='ffill')
    sell2 = (close/close.shift(20) > 2.1).sustain(3)
    sell_all = sell1 | sell2
    position = buy.hold_until(sell_all, nstocks_limit=nstocks_limit, rank=entry_volatility)
    return position


def run_backtest(
    active_names: list[str],
    features: dict,
    nstocks_limit: int = 5,
    position_limit: float = 1/3,
    fee_ratio: float = 1.425/1000*0.3,
    live_performance_start: str = '2020-01-05',
    progress_callback=None,
) -> object:
    """
    跑 sim() 回測

    Parameters
    ----------
    active_names : e.g. ['cond1', 'cond4', ...]
    features : load_features() 回傳的 dict
    nstocks_limit : 同時持有最多 N 檔（預設 5）
    position_limit : 單檔最大倉位（預設 1/3 = 33%）
    fee_ratio : 手續費率（預設 1.425/1000 * 0.3 = 0.0004275）
    live_performance_start : 模擬實盤起始日
    progress_callback : fn(step, total, message) 用於顯示進度

    Returns
    -------
    report object（finlab Report，有 .display()、.get_stats()、.trades 等）
    """
    if progress_callback:
        progress_callback(0, 3, '組合條件 → 建倉位')
    position = build_position(active_names, features, nstocks_limit=nstocks_limit)

    if progress_callback:
        progress_callback(1, 3, 'sim() 回測中（首次可能下載資料 1-5 分鐘）')

    report = sim(
        position.loc["2019":],
        position_limit=position_limit,
        fee_ratio=fee_ratio,
        mae_mfe_window=30,
        trade_at_price='open',
        upload=False,  # ⚠️ 不上傳 finlab cloud，省 daily quota
        name=f"strategy_{'_'.join(active_names)}",
        live_performance_start=live_performance_start,
    )

    if progress_callback:
        progress_callback(2, 3, '產生 stats')
    return report


# ============================================================
# 4. 蒙地卡羅壓力測試（cell 10 的 function 包裝）
# ============================================================
def monte_carlo_stress_test(report, iterations: int = 5000):
    """
    用 bootstrap 蒙地卡羅模擬抽取每日報酬路徑，計算 Sortino / Omega 的 4 個風險分位數
    （Notebook cell 10 的 function）

    Parameters
    ----------
    report : finlab Report
    iterations : int (預設 5000；notebook 用 10000，streamlit 介面用 5000 較快)

    Returns
    -------
    dict : {'sortino_p95': ..., 'sortino_p975': ..., ..., 'omega_p95': ..., ..., 'n_iterations': 5000}
    """
    try:
        returns = report.creturn.pct_change().dropna()
    except Exception:
        return None

    mc_sortino, mc_omega = [], []
    n_days = len(returns)

    for _ in range(iterations):
        sample = np.random.choice(returns, size=n_days, replace=True)
        # Sortino
        ann_ret = np.mean(sample) * 252
        down_ret = sample[sample < 0]
        down_std = np.sqrt(np.mean(down_ret**2)) * np.sqrt(252) if len(down_ret) > 0 else 0
        mc_sortino.append(ann_ret / down_std if down_std > 0 else 0)
        # Omega
        pos_s, neg_s = np.sum(sample[sample > 0]), np.abs(np.sum(sample[sample < 0]))
        mc_omega.append(pos_s / neg_s if neg_s > 0 else 10)

    # 4 個分位數
    q_points = [5, 2.5, 1, 0.3]  # 對應 95%, 97.5%, 99%, 99.7%

    s_vals = [float(np.percentile(mc_sortino, q)) for q in q_points]
    o_vals = [float(np.percentile(mc_omega, q)) for q in q_points]

    return {
        'sortino_p95': s_vals[0],
        'sortino_p975': s_vals[1],
        'sortino_p99': s_vals[2],
        'sortino_p997': s_vals[3],
        'omega_p95': o_vals[0],
        'omega_p975': o_vals[1],
        'omega_p99': o_vals[2],
        'omega_p997': o_vals[3],
        'n_iterations': iterations,
        'sortino_baseline': float(np.median(mc_sortino)),
        'omega_baseline': float(np.median(mc_omega)),
    }


# ============================================================
# 5. Omega Ratio 對大盤（cell 9 的 function）
# ============================================================
def omega_score_vs_benchmark(report):
    """
    計算策略的 Omega Ratio（對加權股價報酬指數），notebook cell 9
    """
    benchmark = data.get('benchmark_return:發行量加權股價報酬指數').squeeze()
    benchmark_returns = benchmark.pct_change()

    strat_returns = report.creturn.pct_change()
    aligned = pd.concat([strat_returns, benchmark_returns], axis=1).dropna()
    excess_ret = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    pos = excess_ret[excess_ret > 0].sum()
    neg = -excess_ret[excess_ret < 0].sum()
    if neg == 0:
        return float('inf')
    return float(pos / neg)


# ============================================================
# 6. Report utils
# ============================================================
def extract_report_stats(report) -> dict:
    """
    從 finlab report 抽關鍵指標（給 streamlit metric 用）

    finlab 2.0.16 get_stats() 回傳的 key:
    - cagr           (annual return as decimal, 1.25 = 125%)
    - total_return   (cumulative return as decimal)
    - max_drawdown   (negative decimal)
    - daily_sharpe
    - daily_sortino
    - daily_mean / daily_vol / daily_skew / daily_kurt
    - win_ratio      (single trade win %)
    - win_year_perc  (positive year %)
    - calmar
    """
    try:
        stats = report.get_stats()
    except Exception:
        stats = {}

    return {
        'daily_sortino': stats.get('daily_sortino', None),
        'annual_return': stats.get('cagr', None),  # finlab key 是 cagr 不是 annual_return
        'total_return': stats.get('total_return', None),
        'max_drawdown': stats.get('max_drawdown', None),
        'daily_sharpe': stats.get('daily_sharpe', None),
        'calmar': stats.get('calmar', None),
        'win_ratio': stats.get('win_ratio', None),
        'win_year_perc': stats.get('win_year_perc', None),
        'all_stats': stats,
    }
