#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
big_player_page.py — 第 10 個 V1 page「💰 大戶買賣力」

從 finlab inventory（集保）公開資料推算大戶買賣力指標。

⚠️ finlab 公開資料只有 inventory（集保庫存分級）+ price/volume，
**沒有逐筆「特大單/大單」資料**。本頁用集保大戶持股變化 + 成交量當代理指標，
跟券商逐筆大單資料會有差異，僅供研究參考。

指標：
1. 大戶買賣比 (%)：|大戶淨買| / 成交量 (大戶活動度，越接近 100% 越活躍)
2. 大戶差比 (%)：大戶淨買 / 成交量 (正=淨買超，負=淨賣超)
3. 大戶買賣力_代理 (5週累計)：5 週累計淨買 / 5 週累計成交量

族群訊號 (基於「買賣比」X「差比」):
- 🟢 領先區: 買賣比 ≥ 70% AND |差比| ≥ 20%
- 🔵 改善區: 買賣比 < 70% AND |差比| ≥ 20%
- 🟠 弱化區: 買賣比 ≥ 70% AND |差比| < 20%
- 🔴 落後區: 買賣比 < 70% AND |差比| < 20%
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


# ============================================================
# Cache: 個股大戶週頻指標（1 小時 cache）
# ============================================================
@st.cache_data(ttl=3600, show_spinner="計算大戶週頻指標…")
def _cached_weekly(stock_id: str) -> pd.DataFrame:
    return bp.calc_big_player_weekly(stock_id).to_json(orient='split', date_format='iso')


def _get_weekly(stock_id: str) -> pd.DataFrame:
    raw = _cached_weekly(stock_id)
    df = pd.read_json(raw, orient='split')
    df['date'] = pd.to_datetime(df['date'])
    return df


@st.cache_data(ttl=3600)
def _cached_security_names() -> dict:
    secs = get_all_securities()
    return dict(zip(secs['stock_id'].astype(str), secs['name']))


# ============================================================
# Page render
# ============================================================
def render_big_player_page():
    st.header("💰 大戶買賣力")
    st.caption(
        "從 FinLab 集保 (inventory) 公開資料推算大戶週頻買賣力指標。"
        "⚠️ finlab 沒有逐筆「特大單/大單」資料，這是 **代理指標** 僅供研究參考。"
    )

    # ============ 個股選擇 ============
    name_map = _cached_security_names()
    # 熱門股清單
    POPULAR = {
        "2330 台積電": "2330", "2317 鴻海": "2317", "2454 聯發科": "2454",
        "2308 台達電": "2308", "2603 長榮": "2603", "0050 元大台灣50": "0050",
        "0056 元大高股息": "0056",
    }
    POPULAR_LABELS = list(POPULAR.keys())

    # 全市場清單（隨機 50 檔熱門）
    all_stocks = [(sid, name) for sid, name in name_map.items() if name]
    all_stocks_sorted = sorted(all_stocks, key=lambda x: int(x[0]) if x[0].isdigit() else 99999)
    # 取前 300 檔（避免 dropdown 卡頓）
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
            default="6M",
            key="bp_range_pills",
            label_visibility="visible",
        )

    if not stock_id:
        st.info("👈 請選擇個股")
        return

    # ============ 取大戶週頻資料 ============
    try:
        weekly = _get_weekly(stock_id)
    except Exception as e:
        st.error(f"❌ 無法取得 {stock_id} 的大戶資料：`{e}`")
        return

    if weekly.empty or len(weekly) < 4:
        st.warning(f"⚠️ {stock_id} 集保資料不足（{len(weekly)} 週）")
        return

    # 過濾時間範圍
    if range_label != "全部":
        days_map = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
        cutoff_date = weekly['date'].max() - pd.Timedelta(days=days_map[range_label])
        weekly_view = weekly[weekly['date'] >= cutoff_date].reset_index(drop=True)
    else:
        weekly_view = weekly

    if weekly_view.empty:
        weekly_view = weekly.tail(8).reset_index(drop=True)

    last = weekly_view.iloc[-1]
    prev = weekly_view.iloc[-2] if len(weekly_view) > 1 else last

    # ============ 5+3 metric cards ============
    st.divider()
    st.markdown(f"### 📊 {label} — 大戶指標 ({last['date'].strftime('%Y-%m-%d')})")

    mc = st.columns(5)
    mc[0].metric("大戶持股比例", f"{last['占集保庫存數比例']:.2f}%",
                 delta=f"{(last['占集保庫存數比例'] - prev['占集保庫存數比例']):+.2f}pp",
                 delta_color="normal")
    mc[1].metric("大戶人數", f"{last['人數']:,}",
                 delta=f"{int(last['人數'] - prev['人數']):+d}",
                 delta_color="normal")
    mc[2].metric("大戶持有股數", f"{last['持有股數']/1e8:.2f} 億股",
                 delta=f"{(last['持有股數'] - prev['持有股數'])/1e6:+.2f}M",
                 delta_color="normal")
    mc[3].metric("本週大戶淨買股數", f"{last['大戶淨買股數']/1e6:+.2f}M 股",
                 delta=f"大戶 {'買超' if last['大戶淨買股數'] > 0 else '賣超'}")
    mc[4].metric("本週成交量", f"{last['成交量']/1e6:.1f}M 股")

    mc2 = st.columns(3)
    mc2[0].metric(
        "💹 大戶買賣比% (活動度)",
        f"{last['大戶買賣比%']:.2f}%",
        delta=f"vs 5 週平均 {weekly_view['大戶買賣比%'].tail(5).mean():.2f}%",
        delta_color="off",
        help="|大戶淨買| / 成交量，越接近 100% 代表大戶越活躍",
    )
    mc2[1].metric(
        "📊 大戶差比% (方向)",
        f"{last['大戶差比%']:+.2f}%",
        delta=f"{bp.classify_strength(last['大戶差比%'])}",
        delta_color="normal" if last['大戶差比%'] > 0 else "inverse",
        help="大戶淨買 / 成交量 (正=買超, 負=賣超)",
    )
    mc2[2].metric(
        "💪 大戶買賣力 (5 週累計代理)",
        f"{last['大戶買賣力_代理%']:+.2f}%",
        delta="代理指標 (5週淨買累計/5週成交量)",
        delta_color="off",
        help="5 週累計淨買股數 / 5 週累計成交量",
    )

    # 訊號 + 強度
    st.divider()
    signal = bp.classify_signal(last['大戶買賣比%'], last['大戶差比%'])
    strength = bp.classify_strength(last['大戶差比%'])
    sig_col, str_col, note_col = st.columns([1, 1, 2])
    sig_col.markdown(f"**族群訊號**\n\n## {signal}")
    str_col.markdown(f"**強弱判斷**\n\n## {strength}")
    note_col.markdown(
        f"**判讀**\n\n"
        f"- 大戶買賣比 = **{last['大戶買賣比%']:.1f}%** ({'≥70% 主力高度參與' if last['大戶買賣比%'] >= 70 else '50-70% 主力介入' if last['大戶買賣比%'] >= 50 else '<50% 主力參與低'})\n"
        f"- 大戶差比 = **{last['大戶差比%']:+.1f}%** ({'買超' if last['大戶差比%'] > 0 else '賣超'}力道)\n"
        f"- 5 週累計買賣力 = **{last['大戶買賣力_代理%']:+.1f}%**\n"
    )

    # ============ Time series 圖 ============
    st.divider()
    st.markdown("#### 📈 大戶週頻指標時間序列")

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.45, 0.30, 0.25],
        subplot_titles=("大戶持股比例 (%)", "大戶淨買股數 (M 股)", "大戶買賣比 / 差比 (%)"),
    )

    # Row 1: 大戶持股比例
    fig.add_trace(go.Scatter(
        x=weekly_view['date'], y=weekly_view['占集保庫存數比例'],
        name='大戶持股 %', line=dict(color='#26a69a', width=2),
        hovertemplate='%{x|%Y-%m-%d}<br>大戶持股: %{y:.2f}%<extra></extra>',
    ), row=1, col=1)

    # Row 2: 大戶淨買股數 (M 股)
    colors = ['#26a69a' if v >= 0 else '#ef5350' for v in weekly_view['大戶淨買股數']]
    fig.add_trace(go.Bar(
        x=weekly_view['date'], y=weekly_view['大戶淨買股數']/1e6,
        name='淨買股數 (M)', marker_color=colors,
        hovertemplate='%{x|%Y-%m-%d}<br>淨買: %{y:+.2f}M 股<extra></extra>',
    ), row=2, col=1)

    # Row 3: 大戶買賣比 + 大戶差比
    fig.add_trace(go.Scatter(
        x=weekly_view['date'], y=weekly_view['大戶買賣比%'],
        name='買賣比 (活動度)', line=dict(color='#42a5f5', width=2),
        hovertemplate='%{x|%Y-%m-%d}<br>買賣比: %{y:.2f}%<extra></extra>',
    ), row=3, col=1)
    fig.add_trace(go.Scatter(
        x=weekly_view['date'], y=weekly_view['大戶差比%'],
        name='差比 (方向)', line=dict(color='#ffa726', width=2, dash='dot'),
        hovertemplate='%{x|%Y-%m-%d}<br>差比: %{y:+.2f}%<extra></extra>',
    ), row=3, col=1)
    fig.add_hline(y=0, line_dash='dot', line_color='gray', line_width=1, row=3, col=1)
    fig.add_hline(y=20, line_dash='dash', line_color='#26a69a', line_width=1, row=3, col=1,
                  annotation_text="強勢 20%", annotation_position="right")
    fig.add_hline(y=-20, line_dash='dash', line_color='#ef5350', line_width=1, row=3, col=1,
                  annotation_text="弱勢 -20%", annotation_position="right")

    fig.update_layout(
        height=700,
        hovermode='x unified',
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    fig.update_yaxes(title_text="大戶持股 %", row=1, col=1)
    fig.update_yaxes(title_text="淨買股數 (M)", row=2, col=1)
    fig.update_yaxes(title_text="買賣比 / 差比 %", row=3, col=1)
    st.plotly_chart(fig, width="stretch")

    # ============ 最近 N 週明細表 ============
    st.divider()
    st.markdown("#### 📋 最近 12 週明細")
    recent = weekly_view.tail(12).copy()
    recent['方向'] = recent['大戶差比%'].apply(lambda x: '🟢 買超' if x > 0 else '🔴 賣超')
    recent['訊號'] = recent.apply(
        lambda r: bp.classify_signal(r['大戶買賣比%'], r['大戶差比%']), axis=1
    )
    display_cols = ['date', '占集保庫存數比例', '人數', '持有股數', '大戶淨買股數',
                    '成交量', '大戶買賣比%', '大戶差比%', '方向', '訊號']
    display_df = recent[display_cols].copy()
    display_df.columns = ['日期', '大戶持股%', '大戶人數', '大戶持有股數',
                          '淨買股數', '成交量', '買賣比%', '差比%', '方向', '訊號']
    # 格式化數字
    display_df['大戶持股%'] = display_df['大戶持股%'].apply(lambda x: f"{x:.2f}%")
    display_df['大戶人數'] = display_df['大戶人數'].apply(lambda x: f"{int(x):,}")
    display_df['大戶持有股數'] = display_df['大戶持有股數'].apply(lambda x: f"{int(x):,}")
    display_df['淨買股數'] = display_df['淨買股數'].apply(lambda x: f"{int(x):+,}")
    display_df['成交量'] = display_df['成交量'].apply(lambda x: f"{int(x):,}")
    display_df['買賣比%'] = display_df['買賣比%'].apply(lambda x: f"{x:.2f}%")
    display_df['差比%'] = display_df['差比%'].apply(lambda x: f"{x:+.2f}%")
    st.dataframe(display_df.iloc[::-1], hide_index=True, width="stretch", height=420)

    # ============ 公式說明 (放在最下方 expander) ============
    with st.expander("📐 指標公式說明"):
        st.markdown("""
### 大戶定義
- **持股分級 12-15**：約 400 張以上
- 對應券商術語的「大戶」或「主力」

### 指標計算（從 FinLab 公開資料推算）

**⚠️ 注意：finlab 公開資料只有 inventory（集保庫存分級）+ price/volume，
沒有逐筆「特大單/大單」資料。本頁用代理指標估算。**

| 指標 | 公式 | 意義 |
|---|---|---|
| **大戶週淨買股數** | `大戶持有股數[t] - 大戶持有股數[t-1]` | 本週大戶實際持股變化（正=買超, 負=賣超） |
| **大戶買賣比 %** | `|大戶淨買| / 該週成交量 × 100` | 大戶活動度（0 = 完全沒大戶動, 越接近 100% 越活躍） |
| **大戶差比 %** | `大戶淨買 / 該週成交量 × 100` | 大戶淨買方向（正=買超, 負=賣超） |
| **大戶買賣力 (5週累計代理)** | `5 週累計淨買 / 5 週累計成交量 × 100` | 中期趨勢代理指標 |

### 族群訊號判斷（基於「買賣比」X「差比」象限）
- 🟢 **領先區**：買賣比 ≥ 70% 且 |差比| ≥ 20%
- 🔵 **改善區**：買賣比 < 70% 且 |差比| ≥ 20%
- 🟠 **弱化區**：買賣比 ≥ 70% 且 |差比| < 20%
- 🔴 **落後區**：買賣比 < 70% 且 |差比| < 20%

### 強弱判斷（基於大戶差比）
- 🟢 **強勢**：差比 > +20%
- 🟡 **中性**：-20% ≤ 差比 ≤ +20%
- 🔴 **弱勢**：差比 < -20%

### 資料來源
- FinLab `data.get('inventory')` — 集保庫存分級資料（週頻更新）
- FinLab `data.get('price:成交股數')` — 日頻成交量
""")
