#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
big_player_page.py — V1 第 9 個 page「💹 主力訊號（融資買賣代理）」

⚠️ 重要說明 (2026-09-19 重寫)
==============================
原始「主力 / 大戶買賣力」定義 = **當天逐筆內外盤方向**
(外盤量 - 內盤量) 或「特大單+大單 買進 - 賣出」。

**finlab 公開資料限制**（實測確認）：
- ❌ `price:內外盤` / `price:外盤量` / `price:內盤量`  → not found
- ❌ `institutional_investors:三大法人買賣超` / 外資 / 投信 / 自營商 → not found
- ❌ `institutional_investors:借券` → not found

**唯一可用的「日頻買賣方向」資料：**
- ✅ `margin_transactions:融資買進` / `融資賣出` / `融券買進` / `融券賣出`

融資 = 投資人借錢買股票（加槓桿看多），所以融資淨買的方向
被當作「主力 / 槓桿買方」的方向代理指標。

⚠️ 此為**代理指標**，跟券商逐筆大單資料會有差異，僅供研究參考。
   集保 (inventory) 是「誰持有」週頻資料，不是「當天買賣」日頻方向，
   早期版本誤用集保當大戶買賣力代理是錯誤的，本版已修正。

兩大功能：
1. **🎯 個股主力訊號**：選個股，看融資買賣日頻指標 + 5 日累計代理
2. **📊 全市場主力力道掃描**：市值前 300 大 + 融資淨增加 + 股價上漲
   → 排名「主力力道% = 融資淨買(股) / 成交量(股)」Top 30
"""
from __future__ import annotations

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import big_player as bp
from data_fetcher import get_all_securities
from finlab import data as _finlab_data


# ============================================================
# Cache helpers
# ============================================================
@st.cache_data(ttl=3600, show_spinner="計算個股融資買賣指標…")
def _cached_daily(stock_id: str) -> str:
    df = bp.calc_big_player_weekly(stock_id)
    if df.empty:
        return pd.DataFrame().to_json(orient='split', date_format='iso')
    return df.to_json(orient='split', date_format='iso')


def _get_daily(stock_id: str) -> pd.DataFrame:
    raw = _cached_daily(stock_id)
    df = pd.read_json(raw, orient='split')
    if df.empty:
        return df
    df['date'] = pd.to_datetime(df['date'])
    return df


@st.cache_data(ttl=3600)
def _cached_security_names() -> dict:
    secs = get_all_securities()
    return dict(zip(secs['stock_id'].astype(str), secs['name']))


# ============================================================
# Page render — 兩大 tab
# ============================================================
def render_big_player_page():
    st.header("💹 主力訊號（融資買賣代理）")
    st.caption(
        "從 FinLab **融資買賣** (margin_transactions) 推算主力籌碼指標。"
        "⚠️ finlab 沒有逐筆「特大單/大單/內外盤/三大法人」資料，本頁用融資淨買當代理指標，"
        "跟券商逐筆大單會有差異，僅供研究參考。"
    )

    tab_individual, tab_scan = st.tabs([
        "🎯 個股主力訊號",
        "📊 全市場主力力道掃描",
    ])

    with tab_individual:
        _render_individual_tab()

    with tab_scan:
        _render_scan_tab()


# ============================================================
# Tab 1: 個股詳細
# ============================================================
def _render_individual_tab():
    name_map = _cached_security_names()
    POPULAR = {
        "2330 台積電": "2330",
        "2317 鴻海": "2317",
        "2454 聯發科": "2454",
        "2308 台達電": "2308",
        "2603 長榮": "2603",
        "3529 力旺": "3529",
        "6488 環球晶": "6488",
        "8996 高力": "8996",
        "4979 華星光": "4979",
        "2409 友達": "2409",
    }
    POPULAR_LABELS = list(POPULAR.keys())

    all_stocks = [(sid, name) for sid, name in name_map.items() if name]
    all_stocks_sorted = sorted(all_stocks, key=lambda x: int(x[0]) if x[0].isdigit() else 99999)
    options = POPULAR_LABELS + [f"{sid} {name}" for sid, name in all_stocks_sorted[:300]]

    col_pick, col_range = st.columns([2, 1])
    with col_pick:
        default_idx = 0  # 預設 2330
        selected = st.selectbox(
            "選擇個股",
            options=range(len(options)),
            format_func=lambda i: options[i],
            index=default_idx,
            key="bp_stock_select",
        )
        if selected < len(POPULAR_LABELS):
            stock_id = POPULAR[POPULAR_LABELS[selected]]
            label = POPULAR_LABELS[selected]
        else:
            stock_id = options[selected].split(" ")[0]
            label = options[selected]

    with col_range:
        range_label = st.pills(
            "時間範圍",
            options=["1M", "3M", "6M", "1Y", "全部"],
            default="3M",
            key="bp_range_pills",
            label_visibility="visible",
        )

    if not stock_id:
        st.info("👈 請選擇個股")
        return

    try:
        df = _get_daily(stock_id)
    except Exception as e:
        st.error(f"❌ 無法取得 {stock_id} 的融資買賣資料：`{e}`")
        return

    if df.empty or len(df) < 5:
        st.warning(f"⚠️ {stock_id} 融資資料不足（{len(df)} 天）")
        return

    # 過濾時間範圍
    if range_label != "全部":
        days_map = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
        cutoff_date = df['date'].max() - pd.Timedelta(days=days_map[range_label])
        view = df[df['date'] >= cutoff_date].reset_index(drop=True)
    else:
        view = df

    if view.empty:
        view = df.tail(20).reset_index(drop=True)

    last = view.iloc[-1]
    prev = view.iloc[-2] if len(view) > 1 else last

    # ============ metric cards ============
    st.divider()
    st.markdown(f"### 📊 {label} — 主力訊號 ({last['date'].strftime('%Y-%m-%d')})")

    mc = st.columns(5)
    mc[0].metric("融資買進", f"{last['融資買進(張)']:,.0f} 張",
                 delta=f"{(last['融資買進(張)'] - prev['融資買進(張)']):+,.0f}",
                 delta_color="normal")
    mc[1].metric("融資賣出", f"{last['融資賣出(張)']:,.0f} 張",
                 delta=f"{(last['融資賣出(張)'] - prev['融資賣出(張)']):+,.0f}",
                 delta_color="inverse")
    mc[2].metric("**融資淨買**", f"{last['融資淨買(張)']:+,.0f} 張",
                 delta=("買超" if last['融資淨買(張)'] > 0 else "賣超"))
    mc[3].metric("成交量", f"{last['成交量(股)']/1e6:.2f} M 股")
    mc[4].metric("主力力道 %", f"{last['融資力_5日累計%']:+.2f}%",
                 help="5日累計融資淨買 / 5日累計成交量 (中期主力力道)")

    mc2 = st.columns(3)
    mc2[0].metric(
        "💹 融資買賣比% (當日力道)",
        f"{last['融資買賣比%']:.2f}%",
        delta=f"vs 5 日平均 {view['融資買賣比%'].tail(5).mean():.2f}%",
        delta_color="off",
        help="融資買進 / (融資買進+融資賣出) × 100，>50%=買方主導，<50%=賣方主導",
    )
    mc2[1].metric(
        "📊 5 日累計淨買",
        f"{last['融資力_5日累計淨買(張)']:+,.0f} 張",
        delta=f"{(last['融資力_5日累計淨買(張)'] - prev['融資力_5日累計淨買(張)']):+,.0f}",
        delta_color="off",
        help="5 日累計融資淨買 (張) — 中期方向",
    )
    mc2[2].metric(
        "📉 融券淨增",
        f"{last['融券淨增(張)']:+,.0f} 張",
        delta=("放空加碼" if last['融券淨增(張)'] > 0 else "空單回補"),
        delta_color="inverse" if last['融券淨增(張)'] > 0 else "normal",
        help="融券賣出 - 融券買進 (正=放空加碼，負=空單回補)",
    )

    # 訊號 + 強弱
    st.divider()
    signal = last['訊號']
    strength = last['強弱']
    sig_col, str_col, note_col = st.columns([1, 1, 2])
    sig_col.markdown(f"**族群訊號**\n\n## {signal}")
    str_col.markdown(f"**強弱判斷**\n\n## {strength}")
    note_col.markdown(
        f"**判讀**\n\n"
        f"- 融資買賣比 = **{last['融資買賣比%']:.1f}%** ({'買方主導' if last['融資買賣比%'] > 50 else '賣方主導'})\n"
        f"- 5 日累計融資淨買 = **{last['融資力_5日累計淨買(張)']:+,.0f} 張**\n"
        f"- 主力力道 (5日) = **{last['融資力_5日累計%']:+.2f}%**\n"
    )

    # ============ Time series 圖 ============
    st.divider()
    st.markdown("#### 📈 融資買賣指標時間序列")

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.40, 0.30, 0.30],
        subplot_titles=("融資買賣比 (%)", "融資淨買 (張)", "主力力道 5 日累計 (%)"),
    )

    # Row 1: 融資買賣比
    fig.add_trace(go.Scatter(
        x=view['date'], y=view['融資買賣比%'],
        name='買賣比', line=dict(color='#42a5f5', width=2),
        fill='tozeroy', fillcolor='rgba(66,165,245,0.15)',
        hovertemplate='%{x|%Y-%m-%d}<br>買賣比: %{y:.2f}%<extra></extra>',
    ), row=1, col=1)
    fig.add_hline(y=50, line_dash='dot', line_color='gray', line_width=1, row=1, col=1,
                  annotation_text="50% 平衡", annotation_position="right")
    fig.add_hline(y=60, line_dash='dash', line_color='#26a69a', line_width=1, row=1, col=1,
                  annotation_text="60% 買方強勢", annotation_position="right")
    fig.add_hline(y=40, line_dash='dash', line_color='#ef5350', line_width=1, row=1, col=1,
                  annotation_text="40% 賣方強勢", annotation_position="right")

    # Row 2: 融資淨買
    colors = ['#26a69a' if v >= 0 else '#ef5350' for v in view['融資淨買(張)']]
    fig.add_trace(go.Bar(
        x=view['date'], y=view['融資淨買(張)'],
        name='淨買 (張)', marker_color=colors,
        hovertemplate='%{x|%Y-%m-%d}<br>淨買: %{y:+,.0f} 張<extra></extra>',
    ), row=2, col=1)

    # Row 3: 主力力道 5 日累計
    force_colors = ['#26a69a' if v >= 0 else '#ef5350' for v in view['融資力_5日累計%']]
    fig.add_trace(go.Bar(
        x=view['date'], y=view['融資力_5日累計%'],
        name='主力力道 (5日)', marker_color=force_colors,
        hovertemplate='%{x|%Y-%m-%d}<br>主力力道: %{y:+.2f}%<extra></extra>',
    ), row=3, col=1)
    fig.add_hline(y=1.5, line_dash='dash', line_color='#26a69a', line_width=1, row=3, col=1,
                  annotation_text="+1.5% 主力進場", annotation_position="right")
    fig.add_hline(y=-1.5, line_dash='dash', line_color='#ef5350', line_width=1, row=3, col=1,
                  annotation_text="-1.5% 主力撤離", annotation_position="right")

    fig.update_layout(
        height=750,
        hovermode='x unified',
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    fig.update_yaxes(title_text="買賣比 %", row=1, col=1, range=[0, 100])
    fig.update_yaxes(title_text="淨買 (張)", row=2, col=1)
    fig.update_yaxes(title_text="主力力道 %", row=3, col=1)
    st.plotly_chart(fig, width="stretch")

    # ============ 最近 N 日明細表 ============
    st.divider()
    st.markdown("#### 📋 最近 20 日明細")
    recent = view.tail(20).copy()
    recent['方向'] = recent['融資淨買(張)'].apply(lambda x: '🟢 買超' if x > 0 else '🔴 賣超')
    display_cols = ['date', '融資買進(張)', '融資賣出(張)', '融資淨買(張)',
                    '融資買賣比%', '成交量(股)', '融資力_5日累計%', '融資力_5日累計淨買(張)',
                    '融券淨增(張)', '訊號', '強弱', '方向']
    display_df = recent[display_cols].copy()
    display_df.columns = ['日期', '融資買進', '融資賣出', '融資淨買',
                          '買賣比%', '成交量', '主力力道%', '5日累計淨買',
                          '融券淨增', '訊號', '強弱', '方向']
    # 格式化
    display_df['融資買進'] = display_df['融資買進'].apply(lambda x: f"{x:,.0f}")
    display_df['融資賣出'] = display_df['融資賣出'].apply(lambda x: f"{x:,.0f}")
    display_df['融資淨買'] = display_df['融資淨買'].apply(lambda x: f"{x:+,.0f}")
    display_df['買賣比%'] = display_df['買賣比%'].apply(lambda x: f"{x:.2f}%")
    display_df['成交量'] = display_df['成交量'].apply(lambda x: f"{int(x):,}")
    display_df['主力力道%'] = display_df['主力力道%'].apply(lambda x: f"{x:+.2f}%")
    display_df['5日累計淨買'] = display_df['5日累計淨買'].apply(lambda x: f"{x:+,.0f}")
    display_df['融券淨增'] = display_df['融券淨增'].apply(lambda x: f"{x:+,.0f}")
    st.dataframe(display_df.iloc[::-1], hide_index=True, width="stretch", height=500)

    # ============ 公式說明 ============
    with st.expander("📐 指標公式說明"):
        st.markdown("""
### 為什麼用「融資買賣」？

**原始「主力 / 大戶買賣力」定義** = 當天逐筆內外盤方向 (特大單+大單 買進 - 賣出)

**finlab 公開資料沒這資料**（實測 2026-09-19）：
- ❌ `price:內外盤` / `price:外盤量` / `price:內盤量` → not found
- ❌ `institutional_investors:三大法人買賣超` / 外資 / 投信 / 自營商 → not found

**唯一可用的日頻買賣方向 = 融資買賣**：
- 融資 = 投資人借錢買股票（加槓桿看多）
- 融資淨買 > 0 → 槓桿買方加碼
- 融資淨買 < 0 → 槓桿買方還錢 / 停損賣出

⚠️ 此為**代理指標**，跟券商逐筆大單資料會有差異，僅供研究參考。

### 指標計算

| 指標 | 公式 | 意義 |
|---|---|---|
| **融資淨買 (張)** | `融資買進 - 融資賣出` | 當天槓桿買方方向（正=買超, 負=賣超） |
| **融資買賣比 %** | `融資買進 / (融資買進 + 融資賣出) × 100` | 當天買賣力道（50%=平衡, >50%=買方主導） |
| **主力力道 % (5日累計)** | `5日累計融資淨買(股) / 5日累計成交量(股) × 100` | 短期主力力道佔成交量比例 |
| **融券淨增 (張)** | `融券賣出 - 融券買進` | 放空者方向（正=加碼, 負=回補） |

### 族群訊號分類

- 🟢 **主力進場**:  主力力道 > +1.5% 且 買賣比 > 55%
- 🔵 **主力調節**:  主力力道 > +1.5% 且 買賣比 ≤ 55%
- 🟠 **主力減碼**:  -1.5% ≤ 主力力道 ≤ +1.5% 且 買賣比 > 60%
- 🔴 **主力撤離**:  主力力道 < -1.5%
- ⚪ **盤整觀望**:  其他

### 強弱判斷（基於融資買賣比）

- 🟢 **買方強勢**: > 60%
- 🟡 **中性**:    40% ~ 60%
- 🔴 **賣方強勢**: < 40%

### 資料來源

- FinLab `margin_transactions:融資買進` / `融資賣出` / `融券買進` / `融券賣出`
""")


# ============================================================
# Tab 2: 全市場主力力道掃描
# ============================================================
@st.cache_data(ttl=1800, show_spinner="掃描全市場主力力道中…")
def _scan_main_force(market_cap_top: int = 300,
                     min_force_pct: float = 0.0,
                     require_price_up: bool = True,
                     require_margin_net_buy: bool = True) -> pd.DataFrame:
    """
    掃描「市值前 N 大 + 融資淨增加 + 股價上漲」個股，計算主力力道%

    Returns:
        DataFrame with columns:
            stock_id, 名稱, 市場, 產業, 市值(億),
            融資買進(張), 融資賣出(張), 融資淨買(張),
            成交量(張), 主力力道%, 漲跌幅%
    """
    secs = get_all_securities()
    pure_secs = secs[secs['market'].isin(['sii', 'otc'])].copy()
    pure_secs['stock_id'] = pure_secs['stock_id'].astype(str)

    # 市值
    mv = _finlab_data.get('etl:market_value')
    mv_last = mv.iloc[-1]
    mv_last.index = mv_last.index.astype(str)
    mv_pure = mv_last[mv_last.index.isin(pure_secs['stock_id'])].dropna()
    mv_top = mv_pure.nlargest(market_cap_top)

    # 融資買賣
    mb = _finlab_data.get('margin_transactions:融資買進')
    ms = _finlab_data.get('margin_transactions:融資賣出')
    last_date = mb.index[-1]
    mb_today = mb.loc[last_date]; mb_today.index = mb_today.index.astype(str)
    ms_today = ms.loc[last_date]; ms_today.index = ms_today.index.astype(str)

    # 成交量
    vol = _finlab_data.get('price:成交股數')
    vol_today = vol.loc[last_date] if last_date in vol.index else vol.iloc[-1]
    vol_today.index = vol_today.index.astype(str)

    # 漲跌
    close = _finlab_data.get('price:收盤價')
    close_today = close.loc[last_date] if last_date in close.index else close.iloc[-1]
    prev_idx = close.index.get_loc(last_date) - 1 if last_date in close.index else -2
    close_yesterday = close.iloc[prev_idx]
    close_today.index = close_today.index.astype(str)
    close_yesterday.index = close_yesterday.index.astype(str)
    ret = (close_today / close_yesterday - 1) * 100

    df = pd.DataFrame({
        'stock_id': mv_top.index,
        '市值(億)': (mv_top.values / 1e8).round(1),
    })
    name_map = dict(zip(pure_secs['stock_id'], pure_secs['name']))
    df['名稱'] = df['stock_id'].map(name_map).fillna('?')

    # 從 company_basic_info 取產業別
    basic = _finlab_data.get('company_basic_info')
    basic['stock_id'] = basic['stock_id'].astype(str)
    industry_map = dict(zip(basic['stock_id'], basic['產業類別']))
    df['產業'] = df['stock_id'].map(industry_map).fillna('?')
    df['市場'] = df['stock_id'].map(dict(zip(pure_secs['stock_id'], pure_secs['market']))).fillna('?')

    df['融資買進(張)'] = df['stock_id'].map(mb_today).fillna(0).round(0)
    df['融資賣出(張)'] = df['stock_id'].map(ms_today).fillna(0).round(0)
    df['融資淨買(張)'] = df['stock_id'].map((mb_today - ms_today)).fillna(0).round(0)
    df['成交量(張)'] = (df['stock_id'].map(vol_today).fillna(0) / 1000).round(0)
    df['漲跌幅%'] = df['stock_id'].map(ret).fillna(0).round(2)

    # 主力力道%
    df['主力力道%'] = np.where(
        df['成交量(張)'] > 0,
        (df['融資淨買(張)'] * 1000) / (df['成交量(張)'] * 1000) * 100,
        0
    ).round(2)

    # 過濾條件
    if require_margin_net_buy:
        df = df[df['融資淨買(張)'] > 0]
    if require_price_up:
        df = df[df['漲跌幅%'] > 0]
    df = df[df['主力力道%'] >= min_force_pct]

    df = df.sort_values('主力力道%', ascending=False).reset_index(drop=True)
    df.attrs['scan_date'] = last_date.strftime('%Y-%m-%d')
    df.attrs['n_total_top'] = market_cap_top
    return df


def _render_scan_tab():
    st.markdown("### 📊 全市場主力力道掃描")
    st.caption(
        "掃描「市值前 N 大 + 融資淨增加 + 股價上漲」的個股，"
        "計算「主力力道% = 融資淨買(股) / 成交量(股) × 100」，排名最高 30 檔。"
    )

    # ============ 控制面板 ============
    col1, col2, col3 = st.columns(3)
    with col1:
        market_cap_top = st.selectbox(
            "市值前幾大",
            options=[100, 200, 300, 500],
            index=2,  # 預設 300
            key="scan_mv_top",
        )
    with col2:
        min_force = st.slider(
            "主力力道 % 門檻",
            min_value=0.0, max_value=20.0, value=0.0, step=0.5,
            key="scan_min_force",
            help="0% = 全列, 5% = 中度主力以上, 10% = 主力主導以上",
        )
    with col3:
        require_up = st.checkbox(
            "只列「股價上漲」",
            value=True,
            key="scan_require_up",
            help="勾選 = 漲跌幅>0 才列",
        )
        require_buy = st.checkbox(
            "只列「融資淨增加」",
            value=True,
            key="scan_require_buy",
            help="勾選 = 融資淨買>0 才列",
        )

    if st.button("🚀 重新掃描", type="primary", key="scan_refresh"):
        st.cache_data.clear()
        st.rerun()

    # ============ 跑 scan ============
    with st.spinner("掃描中…"):
        df = _scan_main_force(
            market_cap_top=market_cap_top,
            min_force_pct=min_force,
            require_price_up=require_up,
            require_margin_net_buy=require_buy,
        )

    scan_date = df.attrs.get('scan_date', '?')
    st.caption(
        f"📅 資料日期 **{scan_date}** ｜ "
        f"掃描市值前 {df.attrs.get('n_total_top', 300)} 大 ｜ "
        f"符合條件 **{len(df)} 檔**"
    )

    if df.empty:
        st.warning("沒有符合條件的個股，請放寬篩選條件")
        return

    # ============ 統計指標 ============
    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("符合條件", f"{len(df)} 檔")
    m2.metric("主力力道 ≥ 10%", f"{(df['主力力道%'] >= 10).sum()} 檔",
              help="主力主導 (融資買盤佔當日成交 10%+)")
    m3.metric("主力力道 5~10%", f"{((df['主力力道%'] >= 5) & (df['主力力道%'] < 10)).sum()} 檔",
              help="中度主力")
    m4.metric("平均主力力道", f"{df['主力力道%'].mean():.2f}%")
    m5.metric("最高主力力道", f"{df['主力力道%'].max():.2f}%",
              delta=df.iloc[0]['名稱'])

    # ============ Top 30 主力力道排名 ============
    st.divider()
    st.markdown("#### 🏆 主力力道% 排名 (Top 30)")

    top30 = df.head(30).copy()
    # 視覺化 bar
    top30_disp = top30[['stock_id', '名稱', '產業', '市值(億)',
                          '融資淨買(張)', '成交量(張)', '主力力道%', '漲跌幅%']].copy()
    top30_disp['主力力道%'] = top30_disp['主力力道%'].apply(lambda x: f"{x:.2f}%")
    top30_disp['漲跌幅%'] = top30_disp['漲跌幅%'].apply(lambda x: f"{x:+.2f}%")

    # Plotly horizontal bar
    fig_bar = go.Figure()
    colors = ['#26a69a' if v >= 5 else '#42a5f5' if v >= 2 else '#ffa726'
              for v in top30['主力力道%']]
    fig_bar.add_trace(go.Bar(
        y=top30['名稱'] + ' (' + top30['stock_id'] + ')',
        x=top30['主力力道%'],
        orientation='h',
        marker_color=colors,
        text=[f"{v:.2f}%" for v in top30['主力力道%']],
        textposition='outside',
        hovertemplate='%{y}<br>主力力道: %{x:.2f}%<extra></extra>',
    ))
    fig_bar.update_layout(
        height=700,
        title="主力力道% 排名 Top 30 (顏色: 🟢≥10% 🔵5-10% 🟠<5%)",
        xaxis_title="主力力道 %",
        yaxis=dict(autorange='reversed'),
        margin=dict(l=120),
    )
    st.plotly_chart(fig_bar, width="stretch")

    # 明細表
    st.markdown("#### 📋 完整明細表")
    display_df = df[['stock_id', '名稱', '市場', '產業', '市值(億)',
                      '融資買進(張)', '融資賣出(張)', '融資淨買(張)',
                      '成交量(張)', '主力力道%', '漲跌幅%']].copy()
    display_df['融資買進(張)'] = display_df['融資買進(張)'].apply(lambda x: f"{int(x):,}")
    display_df['融資賣出(張)'] = display_df['融資賣出(張)'].apply(lambda x: f"{int(x):,}")
    display_df['融資淨買(張)'] = display_df['融資淨買(張)'].apply(lambda x: f"{int(x):+,}")
    display_df['成交量(張)'] = display_df['成交量(張)'].apply(lambda x: f"{int(x):,}")
    display_df['主力力道%'] = display_df['主力力道%'].apply(lambda x: f"{x:.2f}%")
    display_df['漲跌幅%'] = display_df['漲跌幅%'].apply(lambda x: f"{x:+.2f}%")
    st.dataframe(display_df, hide_index=True, width="stretch", height=600)

    # ============ CSV 下載 ============
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"⬇️ 下載完整清單 ({len(df)} 檔 CSV)",
        data=csv_bytes,
        file_name=f"main_force_scan_{scan_date.replace('-', '')}.csv",
        mime="text/csv",
        key="scan_download_csv",
    )

    # ============ 力道分佈說明 ============
    with st.expander("📐 主力力道% 公式 & 解讀"):
        st.markdown("""
### 主力力道 % 公式

```
主力力道% = 融資淨買(股) / 成交量(股) × 100
         = (融資買進 - 融資賣出) × 1000 / (成交量 × 1000) × 100
         = (融資買進 - 融資賣出) / 成交量 × 100  (張 = 1000 股)
```

### 解讀

| 主力力道% | 意義 |
|---|---|
| **≥ 10%** | 🔥 主力主導 — 當日融資買盤佔成交 10% 以上，槓桿買方真進場 |
| **5% ~ 10%** | 💪 中度主力 — 融資買盤是當日主要驅動力之一 |
| **2% ~ 5%** | 👀 輕度主力 — 融資買盤輕微，但方向正向 |
| **< 2%** | 📊 微量主力 — 融資買盤散戶化，上漲主要是其他買盤推動 |

### ⚠️ 注意

- 「主力力道%」反映的是「融資買盤佔當日成交的比重」，**不是資金總量**
- 高主力力道% + 低成交量 = 主力掛單沒人接（小心）
- 低主力力道% + 高成交量 = 大戶用現金（非融資）買的，沒被這指標抓到
- 集保庫存分級資料（早版錯誤指標）已棄用，那是「誰持有」週頻，不是「當天買賣」
""")
