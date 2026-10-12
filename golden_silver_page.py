"""
golden_silver_page.py — V1 第 10 個 page「📐 金包銀掃描」UI

新式形態學 SOP (參考 Gemini 整理):
    「金包銀」= K 棒被下方 60MA 與上方 120MA/240MA 夾擊的壓縮型態

4 條件評分:
    1) 夾擊: 收盤在 60MA 與 min(120MA, 240MA) 之間
    2) 量縮: 5 日均量 < 60 日均量 × 80%
    3) 突破: 收盤 > 120MA / 240MA (突破 1% 視為有效)
    4) 長紅 K 線: 實體佔整體 K 棒 ≥ 60%

訊號:
    🟢 突破表態 (夾擊 + 現在突破 + 長紅)
    🟢 突破後回踩 (夾擊 + 量縮 + 近 5 日內曾突破)
    🟡 量縮整理 (夾擊 + 量縮 — 準備突破的盤整)
    ⚪ 觀察 (夾擊但沒量縮)
    🔴 不符 (沒在夾擊區)
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from finlab import data as _finlab_data
from golden_silver import (
    scan_golden_silver,
    DEFAULT_TOLERANCE_PCT,
    DEFAULT_VOL_SHRINK_RATIO,
    DEFAULT_BREAK_THRESHOLD,
    compute_mas,
)


@st.cache_data(ttl=3600, show_spinner="抓 K 線 + 計算 4 條均線…")
def _cached_kline_data():
    """抓 5 個 K 線/量資料 + 市值 + 證券清單"""
    close = _finlab_data.get('price:收盤價')
    open_ = _finlab_data.get('price:開盤價')
    high = _finlab_data.get('price:最高價')
    low = _finlab_data.get('price:最低價')
    vol = _finlab_data.get('price:成交股數')
    mv = _finlab_data.get('etl:market_value')
    secs = _finlab_data.get('security_categories')

    # 純股票 (排除 ETF/權證/rotc)
    pure = secs[(secs['market'] != 'rotc') & (secs['market'] != 'etf')].copy()
    pure['stock_id'] = pure['stock_id'].astype(str)

    # 市值最近一天
    mv_last = mv.iloc[-1]
    mv_last.index = mv_last.index.astype(str)
    mv_map = mv_last.to_dict()

    name_map = dict(zip(pure['stock_id'], pure['name']))
    market_map = dict(zip(pure['market'].unique(), pure['market'].unique()))
    market_map = dict(zip(pure['stock_id'], pure['market']))

    industry_map = {}
    try:
        basic = _finlab_data.get('company_basic_info')
        if 'stock_id' in basic.columns and '產業類別' in basic.columns:
            basic['stock_id'] = basic['stock_id'].astype(str)
            industry_map = dict(zip(basic['stock_id'], basic['產業類別']))
    except Exception:
        pass

    # 三大法人 (key prefix 修正為 institutional_investors_trading_summary:)
    inst_outer = _finlab_data.get('institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)')
    inst_trust = _finlab_data.get('institutional_investors_trading_summary:投信買賣超股數')
    inst_dealer = _finlab_data.get('institutional_investors_trading_summary:自營商買賣超股數(自行買賣)')
    # 對齊 stock_id dtype
    for d in [inst_outer, inst_trust, inst_dealer]:
        d.columns = d.columns.astype(str)

    return {
        'close': close, 'open': open_, 'high': high, 'low': low, 'vol': vol,
        'mv_map': mv_map, 'name_map': name_map, 'market_map': market_map,
        'industry_map': industry_map, 'pure_stocks': pure,
        'institutional_data': {
            'foreign': inst_outer,
            'trust': inst_trust,
            'dealer': inst_dealer,
        },
    }


@st.cache_data(ttl=1800, show_spinner="掃 60分K 金包銀型態（每檔抓 30 天 1 分 K, 首次較慢）…")
def _cached_scan_60min(
    market_cap_top: int,
    market_filter: tuple,
    ma_fast: int,
    ma_mid: int,
    ma_slow: int,
    vol_fast: int,
    vol_slow: int,
    days_back: int,
    tolerance_pct: float,
    vol_shrink_ratio: float,
    break_threshold: float,
    min_score: int = 1,
) -> pd.DataFrame:
    """60分K 金包銀 scan (用 finlab tw_minute 抓 1 分 K + resample 60min)"""
    from golden_silver import scan_golden_silver_60min
    from finlab import data as _finlab_data

    secs = _finlab_data.get('security_categories')
    pure = secs[(secs['market'] != 'rotc') & (secs['market'] != 'etf')].copy()
    pure['stock_id'] = pure['stock_id'].astype(str)

    mv = _finlab_data.get('etl:market_value')
    mv_last = mv.iloc[-1]
    mv_last.index = mv_last.index.astype(str)
    mv_map = mv_last.to_dict()
    name_map = dict(zip(pure['stock_id'], pure['name']))
    market_map = dict(zip(pure['stock_id'], pure['market']))

    industry_map = {}
    try:
        basic = _finlab_data.get('company_basic_info')
        if 'stock_id' in basic.columns and '產業類別' in basic.columns:
            basic['stock_id'] = basic['stock_id'].astype(str)
            industry_map = dict(zip(basic['stock_id'], basic['產業類別']))
    except Exception:
        pass

    # 三大法人 (日頻, 對齊 60分K 最後一日)
    inst_outer = _finlab_data.get('institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)')
    inst_trust = _finlab_data.get('institutional_investors_trading_summary:投信買賣超股數')
    inst_dealer = _finlab_data.get('institutional_investors_trading_summary:自營商買賣超股數(自行買賣)')
    for d in [inst_outer, inst_trust, inst_dealer]:
        d.columns = d.columns.astype(str)
    institutional_data = {'foreign': inst_outer, 'trust': inst_trust, 'dealer': inst_dealer}

    # 市值前 N 大
    pure_filtered = pure[pure['market'].isin(list(market_filter))]
    mv_top = {sid: v for sid, v in mv_map.items()
              if v > 0 and sid in pure_filtered['stock_id'].values}
    sorted_mv = sorted(mv_top.items(), key=lambda x: x[1], reverse=True)
    stock_ids = [s for s, _ in sorted_mv[:market_cap_top]]

    df = scan_golden_silver_60min(
        stock_ids=stock_ids,
        market_cap_map=mv_map,
        name_map=name_map,
        market_map=market_map,
        industry_map=industry_map,
        institutional_data=institutional_data,
        ma_fast=ma_fast, ma_mid=ma_mid, ma_slow=ma_slow,
        vol_fast=vol_fast, vol_slow=vol_slow,
        days_back=days_back,
        tolerance_pct=tolerance_pct,
        vol_shrink_ratio=vol_shrink_ratio,
        break_threshold=break_threshold,
    )
    if min_score > 0 and not df.empty:
        df = df[df['訊號分數'] >= min_score].copy()
    return df


@st.cache_data(ttl=1800, show_spinner="掃金包銀型態…")
def _cached_scan(
    market_cap_top: int,
    market_filter: tuple,
    tolerance_pct: float,
    vol_shrink_ratio: float,
    break_threshold: float,
    min_score: int = 1,
) -> pd.DataFrame:
    """掃全市場金包銀型態"""
    data = _cached_kline_data()
    pure = data['pure_stocks']
    pure_filtered = pure[pure['market'].isin(list(market_filter))]

    # 市值前 N 大
    mv_top_dict = {sid: v for sid, v in data['mv_map'].items() if v > 0 and sid in pure_filtered['stock_id'].values}
    sorted_mv = sorted(mv_top_dict.items(), key=lambda x: x[1], reverse=True)
    stock_ids = [s for s, _ in sorted_mv[:market_cap_top]]

    df = scan_golden_silver(
        stock_ids=stock_ids,
        close_df=data['close'],
        open_df=data['open'],
        high_df=data['high'],
        low_df=data['low'],
        vol_df=data['vol'],
        market_cap_map=data['mv_map'],
        market_map=data['market_map'],
        name_map=data['name_map'],
        industry_map=data['industry_map'],
        institutional_data=data['institutional_data'],
        tolerance_pct=tolerance_pct,
        vol_shrink_ratio=vol_shrink_ratio,
        break_threshold=break_threshold,
    )
    # 過濾最低分數
    df = df[df['訊號分數'] >= min_score].copy()
    return df


def render_golden_silver_page():
    """📐 金包銀形態掃描 page (V1 第 10 個)"""
    st.header("📐 金包銀形態掃描")
    st.caption(
        "從 FinLab K 線 + 4 條均線偵測「金包銀」壓縮型態。"
        "本頁參考新式形態學 SOP：股價在 60MA 與 120MA/240MA 夾擊下 + 量縮 = 突破前的盤整訊號。"
    )

    # ============ 資料頻率 toggle ============
    freq = st.radio(
        "📊 資料頻率",
        options=['日K (預設, 4785 交易日)', '60分K (FinLab tw_minute, 30 天)'],
        index=0,
        key="gs_freq",
        horizontal=True,
        help="日K = 用 finlab 日頻 (歷史 4785 天); 60分K = 用 finlab tw_minute (30 天 ~ 120 根 60分K, 較敏感)",
    )
    is_60min = '60分K' in freq

    # ============ 控制面板 ============
    with st.expander("⚙️ 篩選條件", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            market_cap_top = st.selectbox(
                "市值前幾大",
                options=[50, 100, 200, 300],
                index=1,
                key="gs_mv_top",
                help="用 etl:market_value 最新一日排序 (60分K 模式建議 ≤ 200, 抓取較慢)",
            )
            market_filter = st.multiselect(
                "市場別",
                options=['sii', 'otc'],
                default=['sii', 'otc'],
                key="gs_market",
                format_func=lambda x: {'sii': '上市 (sii)', 'otc': '上櫃 (otc)'}.get(x, x),
            )
        with col2:
            if is_60min:
                tolerance_pct = st.slider(
                    "🎯 夾擊容差 (%)",
                    min_value=0.3, max_value=5.0, value=1.0, step=0.1,
                    key="gs_tolerance",
                    help="60分K 較敏感, 預設 ±1% (比日K 3% 嚴格)"
                )
            else:
                tolerance_pct = st.slider(
                    "🎯 夾擊容差 (%)",
                    min_value=1.0, max_value=10.0, value=3.0, step=0.5,
                    key="gs_tolerance",
                    help="收盤在 60MA 上下 tolerance% 內都算「夾擊下緣」"
                )
            vol_shrink_ratio = st.slider(
                "📉 量縮門檻 (短/長 量比 < )",
                min_value=0.5, max_value=1.0, value=0.8, step=0.05,
                key="gs_vol_ratio",
                help="日K=5日/60日; 60分K=24根/60根 (≈1日/2.5日)"
            )
        with col3:
            if is_60min:
                break_threshold = st.slider(
                    "🚀 突破門檻 (收盤/上蓋 MA > )",
                    min_value=1.00, max_value=1.05, value=1.005, step=0.001,
                    key="gs_break",
                    help="60分K 0.5% 即算突破 (比日K 1% 敏感)"
                )
            else:
                break_threshold = st.slider(
                    "🚀 突破門檻 (收盤/上蓋 MA > )",
                    min_value=1.00, max_value=1.10, value=1.01, step=0.005,
                    key="gs_break",
                    help="1.01 = 收盤要 > 上蓋 MA × 1.01 算有效突破"
                )
            min_score = st.slider(
                "⭐ 最低訊號分數 (0-4)",
                min_value=0, max_value=4, value=1, step=1,
                key="gs_min_score",
                help="0=全部 / 1=至少 1 條件 / 4=全部條件"
            )

    if not market_filter:
        st.warning("請選擇至少一個市場別")
        return

    if is_60min:
        df = _cached_scan_60min(
            market_cap_top=market_cap_top,
            market_filter=tuple(market_filter),
            ma_fast=60, ma_mid=60, ma_slow=60,
            vol_fast=24, vol_slow=60, days_back=30,
            tolerance_pct=tolerance_pct,
            vol_shrink_ratio=vol_shrink_ratio,
            break_threshold=break_threshold,
            min_score=min_score,
        )
    else:
        df = _cached_scan(
            market_cap_top=market_cap_top,
            market_filter=tuple(market_filter),
            tolerance_pct=tolerance_pct,
            vol_shrink_ratio=vol_shrink_ratio,
            break_threshold=break_threshold,
            min_score=min_score,
        )

    if df.empty:
        st.warning("沒有符合條件的個股，請放寬篩選條件")
        return

    # ============ 統計指標 ============
    st.divider()
    if is_60min:
        last_data_time = df['資料時間'].max() if not df.empty and '資料時間' in df.columns else None
        last_data_str = last_data_time.strftime('%Y-%m-%d %H:%M') if pd.notna(last_data_time) else '?'
        st.caption(
            f"📅 資料時間 **{last_data_str}** (60分K) ｜ 符合條件 **{len(df)} 檔**"
        )
    else:
        st.caption(
            f"📅 資料日期 **{_get_last_date()}** ｜ 符合條件 **{len(df)} 檔**"
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("符合條件", f"{len(df)} 檔")
    m2.metric("🟢 突破表態", f"{(df['訊號'] == '🟢 突破表態').sum()} 檔")
    m3.metric("🟢 突破後回踩", f"{(df['訊號'] == '🟢 突破後回踩').sum()} 檔")
    m4.metric("🟡 量縮整理", f"{(df['訊號'] == '🟡 量縮整理').sum()} 檔")
    m5.metric("⚪ 觀察", f"{(df['訊號'] == '⚪ 觀察').sum()} 檔")

    # ============ Top chart (訊號分數排名) ============
    st.divider()
    st.markdown("#### 🏆 訊號分數排名 (Top 30)")

    df_sorted = df.sort_values('訊號分數', ascending=False).reset_index(drop=True)
    top30 = df_sorted.head(30).copy()

    # bar chart: 訊號分數 (0-4) + 顏色依訊號
    color_map = {
        '🟢 突破表態': '#26a69a',
        '🟢 突破後回踩': '#42a5f5',
        '🟡 量縮整理': '#ffa726',
        '⚪ 觀察': '#9e9e9e',
    }
    bar_colors = [color_map.get(lbl, '#9e9e9e') for lbl in top30['訊號']]

    # y-axis label: 名稱 (stock_id)
    bar_labels = [f"{r['名稱']} ({r['stock_id']})" for _, r in top30.iterrows()]

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        y=bar_labels,
        x=top30['訊號分數'],
        orientation='h',
        marker_color=bar_colors,
        text=[f"{s} 分" for s in top30['訊號分數']],
        textposition='outside',
        hovertemplate=(
            '<b>%{y}</b><br>'
            '訊號分數: %{x} / 4<br>'
            '訊號: %{customdata[0]}<br>'
            '收盤: %{customdata[1]:.2f}<br>'
            '60MA: %{customdata[2]:.2f} (%{customdata[3]:+.2f}%)<br>'
            '夾擊帶寬度: %{customdata[4]:.2f}%<br>'
            '量縮比: %{customdata[5]:.3f}<extra></extra>'
        ),
        customdata=top30[['訊號', '收盤', '60MA', '60MA距離%', '夾擊帶寬度%', '量縮比']].values,
    ))
    fig_bar.update_layout(
        height=700,
        title="Top 30 訊號分數排名 (顏色: 🟢突破表態 🟢突破後回踩 🟡量縮整理 ⚪觀察)",
        xaxis=dict(title="訊號分數 (0-4)", range=[0, 4.5]),
        yaxis=dict(autorange='reversed'),
        margin=dict(l=130),
    )
    st.plotly_chart(fig_bar, width="stretch")

    # ============ 完整明細表 ============
    st.divider()
    st.markdown("#### 📋 完整明細表")
    if is_60min:
        # 60分K 模式: 動態取得 MA 欄位名 (ma_fast/ma_mid/ma_slow)
        ma_fast_col = f'MA{df.attrs.get("ma_fast", 60)}' if hasattr(df, 'attrs') else 'MA60'
        ma_mid_col = f'MA{df.attrs.get("ma_mid", 60)}' if hasattr(df, 'attrs') else 'MA60'
        ma_slow_col = f'MA{df.attrs.get("ma_slow", 60)}' if hasattr(df, 'attrs') else 'MA60'
        vol_fast_col = next((c for c in df.columns if c.startswith('量MA') and c.endswith('(根)')), '量MA24(根)')
        vol_slow_col = next((c for c in df.columns if c.startswith('量MA') and c != vol_fast_col), '量MA60(根)')
        # 取 ma_fast 對應距離欄
        dist_col = f'MA{ma_fast_col[2:]}距離%'

        display_df = df_sorted[[
            'stock_id', '名稱', '市場', '產業', '市值(億)', '資料時間',
            '收盤', ma_fast_col, ma_mid_col, ma_slow_col, 'upper_ma',
            '夾擊帶寬度%', dist_col, '上蓋距離%',
            vol_fast_col, vol_slow_col, '量縮比',
            f'突破MA{ma_mid_col[2:]}', f'突破MA{ma_slow_col[2:]}', '近5日內突破', '實體長紅',
            '外陸資當日', '外陸資3日', '外陸資5日',
            '投信當日', '投信3日', '投信5日',
            '自營商當日', '自營商3日', '自營商5日',
            '訊號', '訊號分數',
        ]].copy()
    else:
        display_df = df_sorted[[
            'stock_id', '名稱', '市場', '產業', '市值(億)',
            '收盤', '60MA', '120MA', '240MA', 'upper_ma',
            '夾擊帶寬度%', '60MA距離%', '上蓋距離%',
            '5日均量(張)', '60日均量(張)', '量縮比',
            '突破120MA', '突破240MA', '近5日內突破', '實體長紅',
            '外陸資當日', '外陸資3日', '外陸資5日',
            '投信當日', '投信3日', '投信5日',
            '自營商當日', '自營商3日', '自營商5日',
            '訊號', '訊號分數',
        ]].copy()
    # 格式化
    ma_cols = [c for c in display_df.columns if c.startswith('MA') and c != 'MA60距離%' and '(' not in c]
    for col in ma_cols + ['upper_ma']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"{x:,.2f}")
    display_df['收盤'] = display_df['收盤'].apply(lambda x: f"{x:,.2f}")
    for col in ['夾擊帶寬度%', '60MA距離%', '上蓋距離%']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"{x:+.2f}%")
    # 60分K 模式的 MA 距離欄 (MA60距離% 已處理, MA{N}距離% 也要處理)
    for col in display_df.columns:
        if col.startswith('MA') and col.endswith('距離%'):
            display_df[col] = display_df[col].apply(lambda x: f"{x:+.2f}%")
    display_df['量縮比'] = display_df['量縮比'].apply(lambda x: f"{x:.3f}")
    for col in ['5日均量(張)', '60日均量(張)']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}")
    for col in [c for c in display_df.columns if c.startswith('量MA') and c.endswith('(根)')]:
        display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}")
    for col in ['突破120MA', '突破240MA', '近5日內突破', '實體長紅']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: '✅' if x else '—')
    for col in [c for c in display_df.columns if c.startswith('突破MA')]:
        display_df[col] = display_df[col].apply(lambda x: '✅' if x else '—')
    # 三大法人 9 欄 (張, 帶正負號)
    for col in ['外陸資當日', '外陸資3日', '外陸資5日',
                '投信當日', '投信3日', '投信5日',
                '自營商當日', '自營商3日', '自營商5日']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"{x:+,.0f}")
    display_df['市值(億)'] = display_df['市值(億)'].apply(lambda x: f"{x:,.0f}")
    if is_60min and '資料時間' in display_df.columns:
        display_df['資料時間'] = display_df['資料時間'].apply(
            lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notna(x) else '?'
        )
    st.dataframe(display_df, hide_index=True, width="stretch", height=600)

    # ============ CSV 下載 ============
    csv_bytes = df_sorted.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"⬇️ 下載完整清單 ({len(df)} 檔 CSV)",
        data=csv_bytes,
        file_name=f"golden_silver_scan_{_get_last_date().replace('-', '')}.csv",
        mime="text/csv",
        key="gs_download_csv",
    )

    # ============ 公式說明 + 進出場 SOP ============
    with st.expander("📐 公式說明 & 新式形態學 SOP (進出場 + 停損停利)"):
        st.markdown("""
### 「金包銀」型態定義

```
夾擊 = 60MA < 收盤 < min(120MA, 240MA)  (容差 ±tolerance%)
        ↓
    4 條件評分 (各 1 分, 滿分 4)
    1) 夾擊: 收盤在 [60MA - tol%, upper_ma + tol%] 內
    2) 量縮: 5 日均量 / 60 日均量 < vol_shrink_ratio
    3) 突破: 收盤 > min(120MA, 240MA) × break_threshold
    4) 長紅: (收-開) / (高-低) ≥ 60%
```

### 訊號判定

| 訊號 | 條件 | 意義 |
|---|---|---|
| 🟢 **突破表態** | 夾擊 + 現在突破 + 長紅 K | 多方正式表態, 動能轉強 |
| 🟢 **突破後回踩** | 夾擊 + 量縮 + 近 5 日內曾突破 | 突破後回測下緣, 二度進場機會 |
| 🟡 **量縮整理** | 夾擊 + 量縮 (但還沒突破) | 準備突破中的盤整, 觀察清單 |
| ⚪ **觀察** | 夾擊但沒量縮 | 中性, 等待確認 |
| 🔴 **不符** | 不在夾擊區 | 排除 |

---

### 🎯 進場 SOP

**兩種進場策略**:

1. **支撐佈局 (左側/區間整理)**:
   - 股價拉回測試 60MA 支撐時, 若能守住且量縮 → 進場
   - 預期股價在 60MA ~ 120MA/240MA 間震盪

2. **突破表態 (右側確認)**:
   - K 棒帶量實體長紅 K 突破 120MA 或 240MA 蓋頭反壓 → 進場
   - 預期均線扭轉為多頭排列

### 🛑 停損 SOP

| 情境 | 停損點 |
|---|---|
| 區間佈局 | 收盤帶量跌破 60MA → 紀律出場 |
| 突破後拉回 | 跌破突破 K 線最低點 → 誘多可能, 先退場 |

### 🎁 停利/出場 SOP

| 情境 | 出場策略 |
|---|---|
| 帳面獲利 15-20% | 分批了結 1/3 或 1/2, 鎖住利潤 |
| 極短線飆股 | 沿 5MA 或前一日低點防守 |
| 波段強勢股 | 沿 10MA 防守, 沒帶量跌破就一路抱 |
| 反轉訊號 | 拉回 3-4 天不過前波高點, 短均線蓋頭反壓, A 型反轉 → 全數出場 |

### ⚠️ 注意事項

- 「金包銀」是型態偵測, **不是進場訊號保證**, 還需搭配趨勢、產業、基本面
- 量縮不代表一定會突破, 也可能往下變盤
- 60MA 是最重要的底部保護墊, 跌破就該出場觀望
- 容差 tolerance% 預設 3%, 抓得太緊可能漏, 抓得太鬆容易誤判
""")


@st.cache_data(ttl=3600)
def _get_last_date() -> str:
    """抓 close 最新日期"""
    close = _finlab_data.get('price:收盤價')
    return str(close.index[-1].strftime('%Y-%m-%d'))


if __name__ == '__main__':
    print("golden_silver_page module loaded OK")
