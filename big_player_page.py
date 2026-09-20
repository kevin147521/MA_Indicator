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


@st.cache_data(ttl=600, show_spinner="抓個股收盤價+漲跌…")
def _cached_security_with_price() -> dict:
    """
    回傳 dict: stock_id -> {name, close, change_pct, change_sign}
    close = 當日收盤價
    change_pct = 當日漲跌 %
    change_sign = 🟢 (漲) / 🔴 (跌) / ⚪ (持平)
    """
    from finlab import data as _d
    secs = get_all_securities()
    secs['stock_id'] = secs['stock_id'].astype(str)
    name_map = dict(zip(secs['stock_id'], secs['name']))

    close = _d.get('price:收盤價')
    last_idx = close.index.get_loc(close.index[-1])
    close_today = close.iloc[last_idx]
    close_yest = close.iloc[max(0, last_idx - 1)]

    # 對齊 stock_id
    close_today.index = close_today.index.astype(str)
    close_yest.index = close_yest.index.astype(str)

    out = {}
    for sid in secs['stock_id']:
        c = float(close_today.get(sid, 0)) if sid in close_today.index else 0
        y = float(close_yest.get(sid, 0)) if sid in close_yest.index else 0
        if c == 0 or y == 0:
            continue
        pct = (c / y - 1) * 100
        if pct > 0.001:
            sign = "🟢"
        elif pct < -0.001:
            sign = "🔴"
        else:
            sign = "⚪"
        out[sid] = {
            'name': name_map.get(sid, '?'),
            'close': c,
            'change_pct': pct,
            'change_sign': sign,
        }
    return out


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
    price_map = _cached_security_with_price()  # stock_id -> {name, close, change_pct, change_sign}

    def _fmt_option(sid: str, default_name: str = None) -> str:
        """格式化個股選項: "台積電 (2330) ¥1,025 +4.67% 🟢" """
        if sid in price_map:
            p = price_map[sid]
            return f"{p['name']} ({sid}) ¥{p['close']:,.0f} {p['change_pct']:+.2f}% {p['change_sign']}"
        return f"{default_name or '?'} ({sid})"

    POPULAR = {
        "2330": "台積電",
        "2317": "鴻海",
        "2454": "聯發科",
        "2308": "台達電",
        "2603": "長榮",
        "3529": "力旺",
        "6488": "環球晶",
        "8996": "高力",
        "4979": "華星光",
        "2409": "友達",
    }
    POPULAR_SIDS = list(POPULAR.keys())
    POPULAR_OPTIONS = [_fmt_option(sid, POPULAR[sid]) for sid in POPULAR_SIDS]

    # 全市場清單
    all_stocks = [(sid, info['name']) for sid, info in price_map.items() if info['name']]
    all_stocks_sorted = sorted(all_stocks, key=lambda x: int(x[0]) if x[0].isdigit() else 99999)
    sid_to_name = dict(all_stocks_sorted)

    # ============ 個股查詢 (text_input 為主) ============
    st.markdown("### 🔍 個股查詢")

    # 解析搜尋輸入
    search_input = st.text_input(
        "代號或名稱",
        value=st.session_state.get("bp_search_input_v2", ""),
        placeholder="輸入 例如: 2330 / 台積電 / TSMC",
        key="bp_search_input_v2",
        label_visibility="collapsed",
        help="直接輸入代號或名稱查詢，支援部分匹配。按 Enter 自動套用。",
    )

    matched_sid = None
    matched_label = None
    if search_input and search_input.strip():
        sq = search_input.strip().lower()
        # 1. 代號精確匹配 (優先)
        if sq in sid_to_name:  # 代號完全相等
            matched_sid = sq
        # 2. 代號部分匹配
        if not matched_sid:
            for sid in sid_to_name.keys():
                if sq in sid.lower():
                    matched_sid = sid
                    break
        # 3. 名稱部分匹配
        if not matched_sid:
            for sid, name in sid_to_name.items():
                if sq in name.lower():
                    matched_sid = sid
                    break
        if matched_sid:
            matched_label = _fmt_option(matched_sid, sid_to_name.get(matched_sid, '?'))

    # 時間範圍 (在第二行)
    range_label = st.pills(
        "時間範圍",
        options=["1M", "3M", "6M", "1Y", "全部"],
        default="3M",
        key="bp_range_pills",
    )

    st.divider()

    if matched_sid:
        # ✅ 搜尋輸入有效: 自動顯示該股資料
        stock_id = matched_sid
        label = matched_label
        st.success(f"✅ 查詢到: **{label}**")
    else:
        # ❌ 搜尋無效 (或空): fallback 到 dropdown (熱門股)
        if search_input and search_input.strip():
            st.error(f"❌ 找不到「{search_input}」— 請用下方熱門股清單或重新輸入")
        col_l, col_r = st.columns([3, 1])
        with col_l:
            selected = st.selectbox(
                "熱門股清單",
                options=range(len(POPULAR_OPTIONS)),
                format_func=lambda i: POPULAR_OPTIONS[i],
                index=0,
                key="bp_stock_select_v2",
                label_visibility="collapsed",
            )
            stock_id = POPULAR_SIDS[selected]
            label = POPULAR_OPTIONS[selected]
        with col_r:
            st.caption("💡 輸入上方的**代號或名稱**即可快速查詢任意個股")

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

    # 從 label 拆出中文名稱 (去掉 ¥ 漲跌 後綴)
    import re as _re
    name_match = _re.match(r'^(.+?)\s*\(\d+\)', label)
    display_name = name_match.group(1) if name_match else label

    # ============ metric cards ============
    st.divider()
    st.markdown(f"### 📊 {display_name} ({stock_id}) — 主力訊號 ({last['date'].strftime('%Y-%m-%d')})")
    # 顯示當前股價/漲跌 (從 price_map 抓最新)
    if stock_id in price_map:
        p = price_map[stock_id]
        st.markdown(
            f"**最新收盤：¥{p['close']:,.2f}** ｜ "
            f"**漲跌：{p['change_pct']:+.2f}% {p['change_sign']}**"
        )

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
                     min_volume_lots: int = 2000,
                     min_force_pct: float = 0.0,
                     min_margin_net_buy_lots: int = 0,
                     min_price_chg_pct: float = 0.0,
                     market_filter: tuple = ('sii', 'otc'),
                     min_vol_change_pct: float = 0.0,
                     vol_change_filter_types: tuple = ()) -> pd.DataFrame:
    """
    掃描個股，計算主力力道%

    ⚠️ finlab 沒有三大法人 (外資/投信/自營商) 買賣超資料。
    本頁用「融資買方」當代理指標 — 反映「當天/3天/5天槓桿買方累積力道」。
    雖非三大法人，但能看出短期主力 (含投信基金、自營商避險、散戶槓桿)
    的累積買盤方向。

    Parameters
    ----------
    market_cap_top : int
        取市值前 N 大
    min_volume_lots : int
        最小當日成交量（張）門檻
    min_force_pct : float
        主力力道% 門檻 (>= 才列)
    min_margin_net_buy_lots : int
        最小融資淨買（張）門檻
    min_price_chg_pct : float
        最小漲跌幅 (%) 門檻
    market_filter : tuple of str
        市場別 ('sii', 'otc')

    Returns
    -------
    DataFrame with columns:
        stock_id, 名稱, 市場, 產業, 市值(億),
        融資買進(張), 融資賣出(張), 融資淨買(張),
        成交量(張), 主力力道%, 主力力道3日%, 主力力道5日%,
        融資力3日累計, 融資力5日累計, 漲跌幅%
    """
    secs = get_all_securities()
    pure_secs = secs[secs['market'].isin(list(market_filter))].copy()
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
    last_idx = mb.index.get_loc(last_date)

    # 當天
    mb_today = mb.iloc[last_idx]; mb_today.index = mb_today.index.astype(str)
    ms_today = ms.iloc[last_idx]; ms_today.index = ms_today.index.astype(str)
    net_today = (mb_today - ms_today)

    # 3 日累計 (當天 + 前 2 個交易日)
    mb_3d = mb.iloc[max(0, last_idx - 2):last_idx + 1].sum()
    ms_3d = ms.iloc[max(0, last_idx - 2):last_idx + 1].sum()
    mb_3d.index = mb_3d.index.astype(str)
    ms_3d.index = ms_3d.index.astype(str)
    net_3d = (mb_3d - ms_3d)

    # 5 日累計 (當天 + 前 4 個交易日)
    mb_5d = mb.iloc[max(0, last_idx - 4):last_idx + 1].sum()
    ms_5d = ms.iloc[max(0, last_idx - 4):last_idx + 1].sum()
    mb_5d.index = mb_5d.index.astype(str)
    ms_5d.index = ms_5d.index.astype(str)
    net_5d = (mb_5d - ms_5d)

    # 成交量 (當天 / 3 日 / 5 日累計 + 對比基準)
    vol = _finlab_data.get('price:成交股數')
    if last_date in vol.index:
        last_vol_idx = vol.index.get_loc(last_date)
    else:
        last_vol_idx = len(vol) - 1
    vol_1d = vol.iloc[last_vol_idx]
    vol_3d = vol.iloc[max(0, last_vol_idx - 2):last_vol_idx + 1].sum()
    vol_5d = vol.iloc[max(0, last_vol_idx - 4):last_vol_idx + 1].sum()
    # 基準期成交量 (前 1 日 / 前 3 日 / 前 5 日)
    vol_prev1d = vol.iloc[max(0, last_vol_idx - 1)] if last_vol_idx - 1 >= 0 else vol_1d
    vol_prev3d = vol.iloc[max(0, last_vol_idx - 5):max(0, last_vol_idx - 2)].sum() if last_vol_idx - 2 >= 0 else vol_3d
    vol_prev5d = vol.iloc[max(0, last_vol_idx - 9):max(0, last_vol_idx - 4)].sum() if last_vol_idx - 4 >= 0 else vol_5d
    # N 個交易日前的單日成交量
    vol_3d_ago = vol.iloc[max(0, last_vol_idx - 3)] if last_vol_idx - 3 >= 0 else vol_1d
    vol_5d_ago = vol.iloc[max(0, last_vol_idx - 5)] if last_vol_idx - 5 >= 0 else vol_1d
    vol_1d.index = vol_1d.index.astype(str)
    vol_3d.index = vol_3d.index.astype(str)
    vol_5d.index = vol_5d.index.astype(str)
    vol_prev1d.index = vol_prev1d.index.astype(str)
    vol_prev3d.index = vol_prev3d.index.astype(str)
    vol_prev5d.index = vol_prev5d.index.astype(str)
    vol_3d_ago.index = vol_3d_ago.index.astype(str)
    vol_5d_ago.index = vol_5d_ago.index.astype(str)

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

    # 融資買進/賣出/淨買
    df['融資買進(張)'] = df['stock_id'].map(mb_today).fillna(0).round(0)
    df['融資賣出(張)'] = df['stock_id'].map(ms_today).fillna(0).round(0)
    df['融資淨買(張)'] = df['stock_id'].map(net_today).fillna(0).round(0)
    df['成交量(張)'] = (df['stock_id'].map(vol_1d).fillna(0) / 1000).round(0)
    # 改用 price_map 取漲跌幅 (跟收盤價同來源，避免重算)
    price_map = _cached_security_with_price()
    df['收盤價'] = df['stock_id'].map(price_map).apply(
        lambda x: x.get('close', 0) if isinstance(x, dict) else 0
    )
    df['漲跌幅%'] = df['stock_id'].map(price_map).apply(
        lambda x: x.get('change_pct', 0) if isinstance(x, dict) else 0
    )

    # 3 日累計
    df['融資力3日累計(張)'] = df['stock_id'].map(net_3d).fillna(0).round(0)
    df['成交量3日(張)'] = (df['stock_id'].map(vol_3d).fillna(0) / 1000).round(0)
    df['主力力道3日%'] = np.where(
        df['成交量3日(張)'] > 0,
        (df['融資力3日累計(張)'] * 1000) / (df['成交量3日(張)'] * 1000) * 100,
        0
    ).round(2)

    # 5 日累計
    df['融資力5日累計(張)'] = df['stock_id'].map(net_5d).fillna(0).round(0)
    df['成交量5日(張)'] = (df['stock_id'].map(vol_5d).fillna(0) / 1000).round(0)
    df['主力力道5日%'] = np.where(
        df['成交量5日(張)'] > 0,
        (df['融資力5日累計(張)'] * 1000) / (df['成交量5日(張)'] * 1000) * 100,
        0
    ).round(2)

    # 主力力道% 當天
    df['主力力道%'] = np.where(
        df['成交量(張)'] > 0,
        (df['融資淨買(張)'] * 1000) / (df['成交量(張)'] * 1000) * 100,
        0
    ).round(2)

    # === 成交量增幅 (5 種) ===
    vol_prev1d_map = (df['stock_id'].map(vol_prev1d).fillna(0) / 1000).round(0)
    vol_prev3d_map = (df['stock_id'].map(vol_prev3d).fillna(0) / 1000).round(0)
    vol_prev5d_map = (df['stock_id'].map(vol_prev5d).fillna(0) / 1000).round(0)
    vol_3d_ago_map = (df['stock_id'].map(vol_3d_ago).fillna(0) / 1000).round(0)
    vol_5d_ago_map = (df['stock_id'].map(vol_5d_ago).fillna(0) / 1000).round(0)

    # 1) 單日成交量增% = 今日 / 昨日 - 1
    df['成交量單日增%'] = np.where(
        vol_prev1d_map > 0,
        (df['成交量(張)'] / vol_prev1d_map - 1) * 100,
        0
    ).round(2)
    # 2) 3 日累計成交量增% = 近 3 日累計 / 前 3 日累計 - 1
    df['成交量3日累計增%'] = np.where(
        vol_prev3d_map > 0,
        (df['成交量3日(張)'] / vol_prev3d_map - 1) * 100,
        0
    ).round(2)
    # 3) 5 日累計成交量增% = 近 5 日累計 / 前 5 日累計 - 1
    df['成交量5日累計增%'] = np.where(
        vol_prev5d_map > 0,
        (df['成交量5日(張)'] / vol_prev5d_map - 1) * 100,
        0
    ).round(2)
    # 4) 較 3 日前單日成交量增% = 今日 / 3 日前單日 - 1
    df['成交量較3日前增%'] = np.where(
        vol_3d_ago_map > 0,
        (df['成交量(張)'] / vol_3d_ago_map - 1) * 100,
        0
    ).round(2)
    # 5) 較 5 日前單日成交量增% = 今日 / 5 日前單日 - 1
    df['成交量較5日前增%'] = np.where(
        vol_5d_ago_map > 0,
        (df['成交量(張)'] / vol_5d_ago_map - 1) * 100,
        0
    ).round(2)

    # 過濾條件（先篩再排）
    df = df[df['成交量(張)'] >= min_volume_lots]
    df = df[df['融資淨買(張)'] >= min_margin_net_buy_lots]
    df = df[df['漲跌幅%'] >= min_price_chg_pct]
    df = df[df['主力力道%'] >= min_force_pct]

    # 成交量增幅過濾 (AND 邏輯：選的時間視角都要 ≥門檻)
    vol_change_col_map = {
        '單日 (vs 昨日)': '成交量單日增%',
        '3 日累計 (vs 前 3 日)': '成交量3日累計增%',
        '5 日累計 (vs 前 5 日)': '成交量5日累計增%',
        '較 3 日前 (單日)': '成交量較3日前增%',
        '較 5 日前 (單日)': '成交量較5日前增%',
    }
    if vol_change_filter_types and min_vol_change_pct != 0:
        for vtype in vol_change_filter_types:
            col = vol_change_col_map.get(vtype)
            if col:
                df = df[df[col] >= min_vol_change_pct]

    df = df.sort_values('主力力道%', ascending=False).reset_index(drop=True)
    df.attrs['scan_date'] = last_date.strftime('%Y-%m-%d')
    df.attrs['n_total_top'] = market_cap_top
    df.attrs['filter_summary'] = {
        '市值前 N 大': market_cap_top,
        '市場別': '+'.join(market_filter),
        '最小成交量 (張)': f'≥ {min_volume_lots:,}',
        '最小融資淨買 (張)': f'≥ {min_margin_net_buy_lots:,}' if min_margin_net_buy_lots > 0 else '不限',
        '最小漲跌幅 (%)': f'≥ {min_price_chg_pct:+.1f}%' if min_price_chg_pct != 0 else '不限',
        '主力力道% 門檻': f'≥ {min_force_pct:.1f}%' if min_force_pct > 0 else '不限',
        '成交量增幅 (%)': (
            f'≥ {min_vol_change_pct:+.1f}% ({", ".join(vol_change_filter_types)})'
            if vol_change_filter_types and min_vol_change_pct != 0 else '不限'
        ),
    }
    # 加 市值排名 + 5 日平均成交金額 (顯示用)
    df = _enrich_df_with_market_rank_and_amount(df)
    return df


# ============================================================
# Tab 2 (副): 三大法人買賣超掃描
# ============================================================
@st.cache_data(ttl=1800, show_spinner="掃描三大法人買賣超中…")
def _scan_institutional(market_cap_top: int = 300,
                        min_volume_lots: int = 2000,
                        min_inst_net_lots: int = 0,
                        min_price_chg_pct: float = 0.0,
                        market_filter: tuple = ('sii', 'otc'),
                        min_vol_change_pct: float = 0.0,
                        vol_change_filter_types: tuple = ()) -> pd.DataFrame:
    """
    掃描個股的三大法人 (外資/投信/自營商) 買賣超

    ✅ 真實三大法人資料 (finlab `institutional_investors_trading_summary:*`)

    Parameters
    ----------
    market_cap_top : int
        取市值前 N 大
    min_volume_lots : int
        最小當日成交量（張）門檻，過濾量能過小的個股
    min_inst_net_lots : int
        最小三大法人合計淨買（張）門檻 (>= 才列)。預設 0 = 不限
    min_price_chg_pct : float
        最小漲跌幅 (%) 門檻
    market_filter : tuple of str
        市場別 ('sii', 'otc')

    Returns
    -------
    DataFrame with columns:
        stock_id, 名稱, 市場, 產業, 市值(億),
        外資買賣超(張), 投信買賣超(張), 自營商買賣超(張), 三大法人合計(張),
        外資3日累計, 投信3日累計, 自營商3日累計, 三大法人合計3日,
        外資5日累計, 投信5日累計, 自營商5日累計, 三大法人合計5日,
        外資力道%, 投信力道%, 自營商力道%, 三大法人力道%, (3日/5日 同),
        成交量(張), 漲跌幅%
    """
    secs = get_all_securities()
    pure_secs = secs[secs['market'].isin(list(market_filter))].copy()
    pure_secs['stock_id'] = pure_secs['stock_id'].astype(str)

    # 市值
    mv = _finlab_data.get('etl:market_value')
    mv_last = mv.iloc[-1]
    mv_last.index = mv_last.index.astype(str)
    mv_pure = mv_last[mv_last.index.isin(pure_secs['stock_id'])].dropna()
    mv_top = mv_pure.nlargest(market_cap_top)

    # 三大法人買賣超 (淨額)
    foreign = _finlab_data.get('institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)')
    trust = _finlab_data.get('institutional_investors_trading_summary:投信買賣超股數')
    dealer = _finlab_data.get('institutional_investors_trading_summary:自營商買賣超股數(自行買賣)')
    last_date = foreign.index[-1]
    last_idx = foreign.index.get_loc(last_date)

    # 當天
    f_1d = foreign.iloc[last_idx]; f_1d.index = f_1d.index.astype(str)
    t_1d = trust.iloc[last_idx]; t_1d.index = t_1d.index.astype(str)
    d_1d = dealer.iloc[last_idx]; d_1d.index = d_1d.index.astype(str)

    # 3 日累計 (張 → 股 ÷ 1000 轉成「張」)
    f_3d = foreign.iloc[max(0, last_idx - 2):last_idx + 1].sum()
    t_3d = trust.iloc[max(0, last_idx - 2):last_idx + 1].sum()
    d_3d = dealer.iloc[max(0, last_idx - 2):last_idx + 1].sum()
    f_3d.index = f_3d.index.astype(str)
    t_3d.index = t_3d.index.astype(str)
    d_3d.index = d_3d.index.astype(str)

    # 5 日累計
    f_5d = foreign.iloc[max(0, last_idx - 4):last_idx + 1].sum()
    t_5d = trust.iloc[max(0, last_idx - 4):last_idx + 1].sum()
    d_5d = dealer.iloc[max(0, last_idx - 4):last_idx + 1].sum()
    f_5d.index = f_5d.index.astype(str)
    t_5d.index = t_5d.index.astype(str)
    d_5d.index = d_5d.index.astype(str)

    # 成交量 (當天 / 3 日 / 5 日累計 + 對比基準)
    vol = _finlab_data.get('price:成交股數')
    if last_date in vol.index:
        last_vol_idx = vol.index.get_loc(last_date)
    else:
        last_vol_idx = len(vol) - 1
    vol_1d = vol.iloc[last_vol_idx]
    vol_3d = vol.iloc[max(0, last_vol_idx - 2):last_vol_idx + 1].sum()
    vol_5d = vol.iloc[max(0, last_vol_idx - 4):last_vol_idx + 1].sum()
    vol_prev1d = vol.iloc[max(0, last_vol_idx - 1)] if last_vol_idx - 1 >= 0 else vol_1d
    vol_prev3d = vol.iloc[max(0, last_vol_idx - 5):max(0, last_vol_idx - 2)].sum() if last_vol_idx - 2 >= 0 else vol_3d
    vol_prev5d = vol.iloc[max(0, last_vol_idx - 9):max(0, last_vol_idx - 4)].sum() if last_vol_idx - 4 >= 0 else vol_5d
    vol_3d_ago = vol.iloc[max(0, last_vol_idx - 3)] if last_vol_idx - 3 >= 0 else vol_1d
    vol_5d_ago = vol.iloc[max(0, last_vol_idx - 5)] if last_vol_idx - 5 >= 0 else vol_1d
    vol_1d.index = vol_1d.index.astype(str)
    vol_3d.index = vol_3d.index.astype(str)
    vol_5d.index = vol_5d.index.astype(str)
    vol_prev1d.index = vol_prev1d.index.astype(str)
    vol_prev3d.index = vol_prev3d.index.astype(str)
    vol_prev5d.index = vol_prev5d.index.astype(str)
    vol_3d_ago.index = vol_3d_ago.index.astype(str)
    vol_5d_ago.index = vol_5d_ago.index.astype(str)

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

    basic = _finlab_data.get('company_basic_info')
    basic['stock_id'] = basic['stock_id'].astype(str)
    industry_map = dict(zip(basic['stock_id'], basic['產業類別']))
    df['產業'] = df['stock_id'].map(industry_map).fillna('?')
    df['市場'] = df['stock_id'].map(dict(zip(pure_secs['stock_id'], pure_secs['market']))).fillna('?')

    # === 三大法人淨買 (張) ===
    # 注意：法人買賣超原始是「股」 (例如 6039352.0 = 603.9 萬股 = 6039 張)
    # 為方便閱讀，除以 1000 轉成「張」
    df['外資買賣超(張)'] = (df['stock_id'].map(f_1d).fillna(0) / 1000).round(1)
    df['投信買賣超(張)'] = (df['stock_id'].map(t_1d).fillna(0) / 1000).round(1)
    df['自營商買賣超(張)'] = (df['stock_id'].map(d_1d).fillna(0) / 1000).round(1)
    df['三大法人合計(張)'] = df['外資買賣超(張)'] + df['投信買賣超(張)'] + df['自營商買賣超(張)']

    # 3 日累計
    df['外資3日累計(張)'] = (df['stock_id'].map(f_3d).fillna(0) / 1000).round(1)
    df['投信3日累計(張)'] = (df['stock_id'].map(t_3d).fillna(0) / 1000).round(1)
    df['自營商3日累計(張)'] = (df['stock_id'].map(d_3d).fillna(0) / 1000).round(1)
    df['三大法人合計3日(張)'] = df['外資3日累計(張)'] + df['投信3日累計(張)'] + df['自營商3日累計(張)']

    # 5 日累計
    df['外資5日累計(張)'] = (df['stock_id'].map(f_5d).fillna(0) / 1000).round(1)
    df['投信5日累計(張)'] = (df['stock_id'].map(t_5d).fillna(0) / 1000).round(1)
    df['自營商5日累計(張)'] = (df['stock_id'].map(d_5d).fillna(0) / 1000).round(1)
    df['三大法人合計5日(張)'] = df['外資5日累計(張)'] + df['投信5日累計(張)'] + df['自營商5日累計(張)']

    df['成交量(張)'] = (df['stock_id'].map(vol_1d).fillna(0) / 1000).round(0)
    df['成交量3日(張)'] = (df['stock_id'].map(vol_3d).fillna(0) / 1000).round(0)
    df['成交量5日(張)'] = (df['stock_id'].map(vol_5d).fillna(0) / 1000).round(0)
    df['漲跌幅%'] = df['stock_id'].map(ret).fillna(0).round(2)

    # 改用 price_map 取收盤價 + 漲跌幅 (跟其他欄位同來源)
    price_map = _cached_security_with_price()
    df['收盤價'] = df['stock_id'].map(price_map).apply(
        lambda x: x.get('close', 0) if isinstance(x, dict) else 0
    )
    df['漲跌幅%'] = df['stock_id'].map(price_map).apply(
        lambda x: x.get('change_pct', 0) if isinstance(x, dict) else 0
    )

    # === 成交量增幅 (5 種) ===
    vol_prev1d_map = (df['stock_id'].map(vol_prev1d).fillna(0) / 1000).round(0)
    vol_prev3d_map = (df['stock_id'].map(vol_prev3d).fillna(0) / 1000).round(0)
    vol_prev5d_map = (df['stock_id'].map(vol_prev5d).fillna(0) / 1000).round(0)
    vol_3d_ago_map = (df['stock_id'].map(vol_3d_ago).fillna(0) / 1000).round(0)
    vol_5d_ago_map = (df['stock_id'].map(vol_5d_ago).fillna(0) / 1000).round(0)
    df['成交量單日增%'] = np.where(
        vol_prev1d_map > 0,
        (df['成交量(張)'] / vol_prev1d_map - 1) * 100, 0
    ).round(2)
    df['成交量3日累計增%'] = np.where(
        vol_prev3d_map > 0,
        (df['成交量3日(張)'] / vol_prev3d_map - 1) * 100, 0
    ).round(2)
    df['成交量5日累計增%'] = np.where(
        vol_prev5d_map > 0,
        (df['成交量5日(張)'] / vol_prev5d_map - 1) * 100, 0
    ).round(2)
    df['成交量較3日前增%'] = np.where(
        vol_3d_ago_map > 0,
        (df['成交量(張)'] / vol_3d_ago_map - 1) * 100, 0
    ).round(2)
    df['成交量較5日前增%'] = np.where(
        vol_5d_ago_map > 0,
        (df['成交量(張)'] / vol_5d_ago_map - 1) * 100, 0
    ).round(2)

    # === 法人力道% (法人淨買股 / 當日成交量股) ===
    # 法人買賣超單位 = 張, 成交量單位 = 張, 直接除
    for col, num_col, den_col in [
        ('外資力道%', '外資買賣超(張)', '成交量(張)'),
        ('投信力道%', '投信買賣超(張)', '成交量(張)'),
        ('自營商力道%', '自營商買賣超(張)', '成交量(張)'),
        ('三大法人力道%', '三大法人合計(張)', '成交量(張)'),
    ]:
        df[col] = np.where(
            df[den_col] > 0,
            df[num_col] / df[den_col] * 100,
            0
        ).round(2)

    # 3 日力道%
    for col, num_col, den_col in [
        ('外資力道3日%', '外資3日累計(張)', '成交量3日(張)'),
        ('投信力道3日%', '投信3日累計(張)', '成交量3日(張)'),
        ('自營商力道3日%', '自營商3日累計(張)', '成交量3日(張)'),
        ('三大法人力道3日%', '三大法人合計3日(張)', '成交量3日(張)'),
    ]:
        df[col] = np.where(
            df[den_col] > 0,
            df[num_col] / df[den_col] * 100,
            0
        ).round(2)

    # 5 日力道%
    for col, num_col, den_col in [
        ('外資力道5日%', '外資5日累計(張)', '成交量5日(張)'),
        ('投信力道5日%', '投信5日累計(張)', '成交量5日(張)'),
        ('自營商力道5日%', '自營商5日累計(張)', '成交量5日(張)'),
        ('三大法人力道5日%', '三大法人合計5日(張)', '成交量5日(張)'),
    ]:
        df[col] = np.where(
            df[den_col] > 0,
            df[num_col] / df[den_col] * 100,
            0
        ).round(2)

    # 過濾
    df = df[df['成交量(張)'] >= min_volume_lots]
    df = df[df['三大法人合計(張)'] >= min_inst_net_lots]
    df = df[df['漲跌幅%'] >= min_price_chg_pct]

    # 成交量增幅過濾 (AND 邏輯)
    vol_change_col_map = {
        '單日 (vs 昨日)': '成交量單日增%',
        '3 日累計 (vs 前 3 日)': '成交量3日累計增%',
        '5 日累計 (vs 前 5 日)': '成交量5日累計增%',
        '較 3 日前 (單日)': '成交量較3日前增%',
        '較 5 日前 (單日)': '成交量較5日前增%',
    }
    if vol_change_filter_types and min_vol_change_pct != 0:
        for vtype in vol_change_filter_types:
            col = vol_change_col_map.get(vtype)
            if col:
                df = df[df[col] >= min_vol_change_pct]

    # 預設排序：三大法人力道% 當天降冪
    df = df.sort_values('三大法人力道%', ascending=False).reset_index(drop=True)
    df.attrs['scan_date'] = last_date.strftime('%Y-%m-%d')
    df.attrs['n_total_top'] = market_cap_top
    df.attrs['filter_summary'] = {
        '市值前 N 大': market_cap_top,
        '市場別': '+'.join(market_filter),
        '最小成交量 (張)': f'≥ {min_volume_lots:,}',
        '最小三大法人合計 (張)': f'≥ {min_inst_net_lots:,}' if min_inst_net_lots > 0 else '不限',
        '最小漲跌幅 (%)': f'≥ {min_price_chg_pct:+.1f}%' if min_price_chg_pct != 0 else '不限',
        '成交量增幅 (%)': (
            f'≥ {min_vol_change_pct:+.1f}% ({", ".join(vol_change_filter_types)})'
            if vol_change_filter_types and min_vol_change_pct != 0 else '不限'
        ),
    }
    # 加 市值排名 + 5 日平均成交金額 (顯示用)
    df = _enrich_df_with_market_rank_and_amount(df)
    return df


# ============================================================
# 主力 scan 共用 enrich: 加 市值排名 + 5 日平均成交金額
# ============================================================
def _enrich_df_with_market_rank_and_amount(df: pd.DataFrame) -> pd.DataFrame:
    """
    給主力 scan 結果 df 加 4 個欄位 (在排序前/後都可):

    - 市值排名: 該股在全市場 (etl:market_value) 的市值排名 (1=最大)
    - 當日成交金額(億): 成交量(張) × 收盤價 / 1e8 (當日)
    - 平均成交金額(5日)(億): 5 日累計成交量(張) × 平均收盤價 / 5 / 1e8
    - 當日 vs 5 日均量比: 當日 / 5 日均 - 1 (%, 判斷量增/縮)

    假設 df 內已有 '成交量5日(張)' 與 '成交量(張)' 與 '收盤價' (主力 scan 都有)
    """
    mv = _finlab_data.get('etl:market_value')
    mv_last = mv.iloc[-1]
    last_date = mv.index[-1]
    mv_last.index = mv_last.index.astype(str)

    # 1) 市值排名 (全市場)
    full_market_rank = mv_last.rank(method='min', ascending=False).astype('Int64')
    df['市值排名'] = df['stock_id'].map(full_market_rank).fillna(9999).astype('Int64')

    # 2) 5 日平均收盤價 + 5 日平均成交金額
    close = _finlab_data.get('price:收盤價')
    if last_date in close.index:
        last_close_idx = close.index.get_loc(last_date)
    else:
        last_close_idx = len(close) - 1
    avg_close_5d = close.iloc[max(0, last_close_idx - 4):last_close_idx + 1].mean(axis=0)
    avg_close_5d.index = avg_close_5d.index.astype(str)
    df['平均收盤價(5日)'] = df['stock_id'].map(avg_close_5d).fillna(0).round(2)
    if '成交量5日(張)' in df.columns:
        df['平均成交金額(5日)(億)'] = np.where(
            df['平均收盤價(5日)'] > 0,
            (df['成交量5日(張)'] * 1000 * df['平均收盤價(5日)'] / 5 / 1e8),
            0
        ).round(2)

    # 3) 當日成交金額 (億) = 成交量(張) × 1000 × 收盤價 / 1e8
    if '成交量(張)' in df.columns and '收盤價' in df.columns:
        df['當日成交金額(億)'] = np.where(
            df['收盤價'] > 0,
            (df['成交量(張)'] * 1000 * df['收盤價'] / 1e8),
            0
        ).round(2)

    # 4) 當日 vs 5 日均量比 (%) — 判斷量增/縮
    if '當日成交金額(億)' in df.columns and '平均成交金額(5日)(億)' in df.columns:
        df['當日vs5日量增%'] = np.where(
            df['平均成交金額(5日)(億)'] > 0,
            (df['當日成交金額(億)'] / df['平均成交金額(5日)(億)'] - 1) * 100,
            0
        ).round(2)

    return df


# ============================================================
# 整體市值排名 scan (純台股結構，無篩選)
# ============================================================
@st.cache_data(ttl=1800, show_spinner="抓整體市值前 N 大...")
def _scan_market_cap_ranking(top_n: int = 100,
                             market_filter: tuple = ('sii', 'otc')) -> pd.DataFrame:
    """
    純按市值排序的台股排行榜

    顯示: 排名 / 代號 / 名稱 / 市場 / 產業 / 市值 / 收盤價 / 漲跌 / 成交量 / 量增 / 三大法人力道%
    不套用任何「主力進場」篩選 — 純台股結構視角
    """
    secs = get_all_securities()
    pure_secs = secs[secs['market'].isin(list(market_filter))].copy()
    pure_secs['stock_id'] = pure_secs['stock_id'].astype(str)

    # 市值
    mv = _finlab_data.get('etl:market_value')
    mv_last = mv.iloc[-1]
    last_date = mv.index[-1]
    mv_last.index = mv_last.index.astype(str)
    mv_pure = mv_last[mv_last.index.isin(pure_secs['stock_id'])].dropna()
    mv_top = mv_pure.nlargest(top_n)

    df = pd.DataFrame({
        '排名': range(1, len(mv_top) + 1),
        'stock_id': mv_top.index,
        '市值(億)': (mv_top.values / 1e8).round(1),
    })

    # 名稱 / 市場 / 產業
    name_map = dict(zip(pure_secs['stock_id'], pure_secs['name']))
    market_map = dict(zip(pure_secs['stock_id'], pure_secs['market']))
    df['名稱'] = df['stock_id'].map(name_map).fillna('?')
    df['市場'] = df['stock_id'].map(market_map).fillna('?')

    basic = _finlab_data.get('company_basic_info')
    basic['stock_id'] = basic['stock_id'].astype(str)
    industry_map = dict(zip(basic['stock_id'], basic['產業類別']))
    df['產業'] = df['stock_id'].map(industry_map).fillna('?')

    # 收盤價 + 漲跌幅%
    price_map = _cached_security_with_price()
    df['收盤價'] = df['stock_id'].map(price_map).apply(
        lambda x: x.get('close', 0) if isinstance(x, dict) else 0
    )
    df['漲跌幅%'] = df['stock_id'].map(price_map).apply(
        lambda x: x.get('change_pct', 0) if isinstance(x, dict) else 0
    )

    # 成交量 + 量增 (5 種)
    vol = _finlab_data.get('price:成交股數')
    last_vol_idx = vol.index.get_loc(last_date)
    vol_1d = vol.iloc[last_vol_idx]; vol_1d.index = vol_1d.index.astype(str)
    vol_prev1d = vol.iloc[max(0, last_vol_idx - 1)]
    vol_prev1d.index = vol_prev1d.index.astype(str)
    vol_prev3d = vol.iloc[max(0, last_vol_idx - 5):max(0, last_vol_idx - 2)].sum() if last_vol_idx - 2 >= 0 else vol_1d
    vol_prev3d.index = vol_prev3d.index.astype(str)
    vol_prev5d = vol.iloc[max(0, last_vol_idx - 9):max(0, last_vol_idx - 4)].sum() if last_vol_idx - 4 >= 0 else vol_1d
    vol_prev5d.index = vol_prev5d.index.astype(str)
    vol_3d = vol.iloc[max(0, last_vol_idx - 2):last_vol_idx + 1].sum()
    vol_3d.index = vol_3d.index.astype(str)
    vol_5d = vol.iloc[max(0, last_vol_idx - 4):last_vol_idx + 1].sum()
    vol_5d.index = vol_5d.index.astype(str)

    vol_prev1d_map = df['stock_id'].map(vol_prev1d).fillna(0)
    vol_prev3d_map = df['stock_id'].map(vol_prev3d).fillna(0)
    vol_prev5d_map = df['stock_id'].map(vol_prev5d).fillna(0)
    vol_3d_ago_map = df['stock_id'].map(vol.iloc[max(0, last_vol_idx - 3)]).fillna(0)
    vol_5d_ago_map = df['stock_id'].map(vol.iloc[max(0, last_vol_idx - 5)]).fillna(0)

    df['成交量(張)'] = (df['stock_id'].map(vol_1d).fillna(0) / 1000).round(0)
    df['成交量3日(張)'] = (df['stock_id'].map(vol_3d).fillna(0) / 1000).round(0)
    df['成交量5日(張)'] = (df['stock_id'].map(vol_5d).fillna(0) / 1000).round(0)

    df['成交量單日增%'] = np.where(
        vol_prev1d_map > 0,
        ((df['stock_id'].map(vol_1d).fillna(0) / vol_prev1d_map) - 1) * 100,
        0
    ).round(2)
    df['成交量3日累計增%'] = np.where(
        vol_prev3d_map > 0,
        ((df['stock_id'].map(vol_3d).fillna(0) / vol_prev3d_map) - 1) * 100,
        0
    ).round(2)
    df['成交量5日累計增%'] = np.where(
        vol_prev5d_map > 0,
        ((df['stock_id'].map(vol_5d).fillna(0) / vol_prev5d_map) - 1) * 100,
        0
    ).round(2)
    df['成交量較3日前增%'] = np.where(
        vol_3d_ago_map > 0,
        ((df['stock_id'].map(vol_1d).fillna(0) / vol_3d_ago_map) - 1) * 100,
        0
    ).round(2)
    df['成交量較5日前增%'] = np.where(
        vol_5d_ago_map > 0,
        ((df['stock_id'].map(vol_1d).fillna(0) / vol_5d_ago_map) - 1) * 100,
        0
    ).round(2)

    # === 過去 5 日平均成交金額 ===
    # 平均金額 ≈ 5 日累計 (張) × 5 日平均收盤價 / 5 / 1e8 (億)
    close = _finlab_data.get('price:收盤價')
    if last_date in close.index:
        last_close_idx = close.index.get_loc(last_date)
    else:
        last_close_idx = len(close) - 1
    avg_close_5d = close.iloc[max(0, last_close_idx - 4):last_close_idx + 1].mean(axis=0)
    avg_close_5d.index = avg_close_5d.index.astype(str)
    df['平均收盤價(5日)'] = df['stock_id'].map(avg_close_5d).fillna(0).round(2)
    # 5 日累計 (張) × 1000 (股) × 5 日平均收盤價 / 5 / 1e8 = 億
    df['平均成交金額(5日)(億)'] = np.where(
        df['平均收盤價(5日)'] > 0,
        (df['成交量5日(張)'] * 1000 * df['平均收盤價(5日)'] / 5 / 1e8),
        0
    ).round(2)

    # === 當日成交金額 (億) + 當日 vs 5 日量增 % ===
    # 當日 (張) × 1000 (股) × 當日收盤價 / 1e8 = 億
    df['當日成交金額(億)'] = np.where(
        df['收盤價'] > 0,
        (df['成交量(張)'] * 1000 * df['收盤價'] / 1e8),
        0
    ).round(2)
    # 量增 %: (當日 / 5 日均 - 1) × 100
    df['當日vs5日量增%'] = np.where(
        df['平均成交金額(5日)(億)'] > 0,
        ((df['當日成交金額(億)'] / df['平均成交金額(5日)(億)']) - 1) * 100,
        0
    ).round(2)

    # 三大法人 (當天)
    f = _finlab_data.get('institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)').iloc[-1]
    t = _finlab_data.get('institutional_investors_trading_summary:投信買賣超股數').iloc[-1]
    d = _finlab_data.get('institutional_investors_trading_summary:自營商買賣超股數(自行買賣)').iloc[-1]
    f.index = f.index.astype(str)
    t.index = t.index.astype(str)
    d.index = d.index.astype(str)

    df['外資買賣超(張)'] = (df['stock_id'].map(f).fillna(0) / 1000).round(1)
    df['投信買賣超(張)'] = (df['stock_id'].map(t).fillna(0) / 1000).round(1)
    df['自營商買賣超(張)'] = (df['stock_id'].map(d).fillna(0) / 1000).round(1)
    df['三大法人合計(張)'] = df['外資買賣超(張)'] + df['投信買賣超(張)'] + df['自營商買賣超(張)']
    df['三大法人力道%'] = np.where(
        df['成交量(張)'] > 0,
        df['三大法人合計(張)'] / df['成交量(張)'] * 100,
        0
    ).round(2)

    df.attrs['scan_date'] = last_date.strftime('%Y-%m-%d')
    df.attrs['total_market_cap'] = mv_pure.sum() / 1e8  # 億
    df.attrs['top_n'] = top_n
    return df


def _render_market_cap_ranking_tab():
    """整體市值排名 UI (純台股結構視角)"""
    st.caption(
        "💡 **整體市值排名** = 純按市值排序全市場個股，不套用主力篩選。"
        "看台股龍頭結構 + 當日整體狀態 (股價/漲跌/量增/三大法人力道)。"
    )

    # 控制面板
    col1, col2, col3 = st.columns(3)
    with col1:
        top_n = st.selectbox(
            "顯示前 N 大",
            options=[30, 50, 100, 200, 300],
            index=2,  # 預設 100
            key="mc_top_n",
            help="用 etl:market_value 最新一日排序",
        )
    with col2:
        market_filter = st.multiselect(
            "市場別",
            options=['sii', 'otc'],
            default=['sii', 'otc'],
            key="mc_market",
            format_func=lambda x: {'sii': '上市 (sii)', 'otc': '上櫃 (otc)'}.get(x, x),
        )
    with col3:
        st.write("")
        st.caption("💡 切換上市/上櫃看不同結構")

    if not market_filter:
        st.warning("請至少選一個市場")
        return

    with st.spinner("抓市值前 N 大 + 三大法人 + 量增…"):
        df = _scan_market_cap_ranking(
            top_n=top_n,
            market_filter=tuple(market_filter),
        )

    scan_date = df.attrs.get('scan_date', '?')
    total_mv = df.attrs.get('total_market_cap', 0)

    # ============ 摘要卡 ============
    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("資料日期", scan_date)
    m2.metric("全市場市值", f"{total_mv:,.0f} 億")
    m3.metric(f"前 {top_n} 檔合計", f"{df['市值(億)'].sum():,.0f} 億",
              delta=f"{df['市值(億)'].sum() / total_mv * 100:.1f}% 佔比")
    m4.metric("上漲家數", f"{(df['漲跌幅%'] > 0).sum()} 檔")
    m5.metric("下跌家數", f"{(df['漲跌幅%'] < 0).sum()} 檔")

    # ============ 明細表 ============
    st.divider()
    st.markdown(f"#### 📊 整體市值前 {top_n} 大 (純按市值排序)")

    display_df = df[['排名', 'stock_id', '名稱', '市場', '產業',
                       '市值(億)', '平均成交金額(5日)(億)', '當日成交金額(億)', '當日vs5日量增%', '收盤價', '漲跌幅%',
                       '成交量(張)', '成交量單日增%', '成交量3日累計增%', '成交量5日累計增%',
                       '成交量較3日前增%', '成交量較5日前增%',
                       '外資買賣超(張)', '投信買賣超(張)', '自營商買賣超(張)',
                       '三大法人合計(張)', '三大法人力道%']].copy()

    # 格式化
    for col in ['成交量(張)', '成交量3日(張)', '成交量5日(張)']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}")
    display_df['收盤價'] = display_df['收盤價'].apply(lambda x: f"{x:,.2f}")
    for col in display_df.columns:
        if '(張)' in col and col not in ['成交量(張)', '成交量3日(張)', '成交量5日(張)']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:+,.1f}")
        elif '力道%' in col or '增%' in col or col == '漲跌幅%':
            display_df[col] = display_df[col].apply(lambda x: f"{x:+.2f}%")
    display_df['市值(億)'] = display_df['市值(億)'].apply(lambda x: f"{x:,.1f}")
    if '市值排名' in display_df.columns:
        display_df['市值排名'] = display_df['市值排名'].apply(lambda x: str(int(x)))
    if '平均成交金額(5日)(億)' in display_df.columns:
        display_df['平均成交金額(5日)(億)'] = display_df['平均成交金額(5日)(億)'].apply(lambda x: f"{x:.2f}")

    st.dataframe(display_df, hide_index=True, width="stretch", height=600)

    # ============ CSV 下載 ============
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"⬇️ 下載整體市值前 {top_n} 大 (CSV)",
        data=csv_bytes,
        file_name=f"market_cap_top{top_n}_{scan_date.replace('-', '')}.csv",
        mime="text/csv",
        key="mc_download_csv",
    )

    # ============ 公式說明 ============
    with st.expander("📐 整體市值排名公式說明"):
        st.markdown("""
### 排名規則
- **純按 `etl:market_value` 最新一日市值降冪排序**
- **不套用任何主力篩選** — 想看台股結構就用這個 tab
- 想看「主力進場篩選」請切回 🔥 主力掃描 tab

### 顯示欄位
| 欄位 | 公式 |
|---|---|
| 市值(億) | `etl:market_value` ÷ 1e8 |
| 收盤價 | `price:收盤價` 最新一日 |
| 漲跌幅% | 今日 / 昨日 - 1 |
| 成交量(張) | 今日成交量 ÷ 1000 |
| 成交量單日增% | 今日 / 昨日 - 1 |
| 成交量 3 日累計增% | 近 3 日累計 / 前 3 日累計 - 1 |
| 成交量 5 日累計增% | 近 5 日累計 / 前 5 日累計 - 1 |
| 成交量較 3 日前增% | 今日 / 3 日前單日 - 1 |
| 成交量較 5 日前增% | 今日 / 5 日前單日 - 1 |
| 外資/投信/自營商買賣超(張) | finlab 三大法人 ÷ 1000 |
| 三大法人力道% | 三大法人合計 / 成交量 × 100 |

### 使用情境
- 看台股市值龍頭 (前 10 名一定是 2330 / 2317 / 2454 等大型權值股)
- 觀察權值股當日狀態 (價格、漲跌、量、法人動作)
- 對照主力掃描的「主力進場」訊號是否跟大盤同步
""")


def _render_scan_tab():
    st.markdown("### 📊 全市場掃描")
    st.caption(
        "兩種視角：🔥 主力掃描 (有篩選條件) 或 📊 整體市值排名 (純台股結構)。"
    )

    subtab_scan, subtab_market_cap = st.tabs([
        "🔥 主力掃描 (有篩選)",
        "📊 整體市值排名 (全市場)",
    ])

    with subtab_scan:
        _render_scan_subtab()

    with subtab_market_cap:
        _render_market_cap_ranking_tab()


def _render_scan_subtab():
    """原本的融資/三大法人主力掃描 (有篩選條件)"""
    # 掃描類型 radio — 切換「融資代理 / 三大法人」
    scan_type = st.radio(
        "📊 掃描類型",
        options=['融資代理 (融資買方力道)', '🏛️ 三大法人 (外資/投信/自營商)'],
        index=0,
        key="scan_type",
        horizontal=True,
        help=(
            "融資代理 = 反映槓桿交易者 (含投信基金、自營商避險、散戶融資) 的累積買盤\n"
            "三大法人 = finlab 真正的三大法人買賣超 (外資/投信/自營商 各自獨立排名)"
        ),
    )

    if '三大法人' in scan_type:
        _render_institutional_scan()
    else:
        _render_margin_scan()


# ============================================================
# 融資代理 scan UI (原本的 _render_scan_tab 主體)
# ============================================================
def _render_margin_scan():
    st.info(
        "💡 **融資代理指標**：當 finlab 沒有逐筆大單/內外盤資料時，"
        "用「融資買方力道」當代理，反映「槓桿交易者」累積買盤方向。"
        "⚠️ 無法區分投信 vs 自營 vs 散戶 (要看真正法人請切到「三大法人」tab)。"
    )

    # 排名依據 radio (預設當天)
    rank_by = st.radio(
        "📊 排名依據",
        options=['當天主力力道%', '3 日累計主力力道%', '5 日累計主力力道%'],
        index=0,
        key="scan_rank_by",
        horizontal=True,
        help=(
            "當天 = 當日融資淨買 / 當日成交量\n"
            "3 日累計 = 近 3 日累計融資淨買 / 近 3 日累計成交量\n"
            "5 日累計 = 近 5 日累計融資淨買 / 近 5 日累計成交量"
        ),
    )

    # ============ 控制面板 ============
    with st.expander("⚙️ 篩選條件", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            market_cap_top = st.selectbox(
                "市值前幾大",
                options=[100, 200, 300, 500, 1000],
                index=2,  # 預設 300
                key="scan_mv_top",
                help="用 etl:market_value 最新一日排序",
            )
            market_filter = st.multiselect(
                "市場別",
                options=['sii', 'otc'],
                default=['sii', 'otc'],
                key="scan_market",
                format_func=lambda x: {'sii': '上市 (sii)', 'otc': '上櫃 (otc)'}.get(x, x),
                help="上市/上櫃可多選，預設全選",
            )

        with col2:
            min_volume_lots = st.slider(
                "📊 最小當日成交量 (張)",
                min_value=0, max_value=50000, value=2000, step=500,
                key="scan_min_vol",
                help=(
                    "過濾量能過小的個股，避免主力力道% 被虛胖。\n"
                    "預設 2000 張 = 約 200 萬股，剔除冷門股。\n"
                    "設 0 = 不限"
                ),
            )
            min_force = st.slider(
                "💪 主力力道 % 門檻 (當天)",
                min_value=0.0, max_value=20.0, value=0.0, step=0.5,
                key="scan_min_force",
                help=(
                    "過濾用「當天主力力道%」(不是 3 日/5 日累計)。\n"
                    "0% = 全列, 5% = 中度主力以上, 10% = 主力主導以上"
                ),
            )

        with col3:
            min_margin_net_buy = st.number_input(
                "💹 最小融資淨買 (張)",
                min_value=0, value=0, step=100,
                key="scan_min_net_buy",
                help="預設 0 = 不限。設 100 = 只列融資淨買 ≥ 100 張",
            )
            min_price_chg = st.number_input(
                "📈 最小漲跌幅 (%)",
                min_value=-10.0, max_value=10.0, value=0.0, step=0.5,
                key="scan_min_chg",
                help="預設 0 = 含下跌。設 5 = 只列漲 ≥ 5%。設 -3 = 含跌 ≤ 3%",
            )

        # 成交量增幅篩選 (第 4 行)
        col4, col5 = st.columns([2, 1])
        with col4:
            min_vol_change = st.slider(
                "📈 最小成交量增幅 (%)",
                min_value=-80, max_value=500, value=0, step=10,
                key="scan_min_vol_change",
                help=(
                    "成交量增幅門檻，套用於下方選擇的時間視角。\n"
                    "0% = 不限, 50% = 量增 ≥50%, 100% = 量增 ≥100% (翻倍)\n"
                    "-30% = 縮量 ≥30% (過濾量能萎縮股)"
                ),
            )
            vol_change_types = st.multiselect(
                "📊 成交量增幅套用於",
                options=['單日 (vs 昨日)', '3 日累計 (vs 前 3 日)', '5 日累計 (vs 前 5 日)',
                         '較 3 日前 (單日)', '較 5 日前 (單日)'],
                default=['單日 (vs 昨日)'],
                key="scan_vol_change_types",
                help="勾選的視角都要 ≥門檻 (AND 邏輯)",
            )

        col_btn1, col_btn2, _ = st.columns([1, 1, 4])
        with col_btn1:
            run_btn = st.button("🚀 重新掃描", type="primary", key="scan_refresh")
        with col_btn2:
            # 預設推薦條件 — 用 callback (因為 widget 已 instantiate 不能直接改 session_state)
            def _apply_preset():
                st.session_state["scan_min_vol"] = 5000
                st.session_state["scan_min_force"] = 3.0
                st.session_state["scan_min_chg"] = 2.0
                st.session_state["scan_min_vol_change"] = 30
                st.session_state["scan_vol_change_types"] = ['單日 (vs 昨日)']
            st.button(
                "⭐ 用推薦條件",
                key="scan_preset",
                help="成交量 ≥ 5000 張 + 主力力道 ≥ 3% + 漲 ≥ 2%",
                on_click=_apply_preset,
            )

    # ============ 跑 scan ============
    if not market_filter:
        st.warning("請至少選一個市場")
        return

    if run_btn:
        st.cache_data.clear()
        st.rerun()

    with st.spinner("掃描中…"):
        df = _scan_main_force(
            market_cap_top=market_cap_top,
            min_volume_lots=min_volume_lots,
            min_force_pct=min_force,
            min_margin_net_buy_lots=min_margin_net_buy,
            min_price_chg_pct=min_price_chg,
            market_filter=tuple(market_filter),
            min_vol_change_pct=min_vol_change,
            vol_change_filter_types=tuple(vol_change_types),
        )

    scan_date = df.attrs.get('scan_date', '?')
    filter_summary = df.attrs.get('filter_summary', {})
    filter_text = " ｜ ".join([f"{k}={v}" for k, v in filter_summary.items()])
    st.caption(
        f"📅 資料日期 **{scan_date}** ｜ 符合條件 **{len(df)} 檔**\n\n"
        f"⚙️ {filter_text}"
    )

    if df.empty:
        st.warning("沒有符合條件的個股，請放寬篩選條件（例如降低成交量門檻或主力力道%）")
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
    # 依 rank_by 選擇排序欄位
    rank_col_map = {
        '當天主力力道%': '主力力道%',
        '3 日累計主力力道%': '主力力道3日%',
        '5 日累計主力力道%': '主力力道5日%',
    }
    rank_col = rank_col_map[rank_by]

    # 重新排序（依使用者選的時間範圍）
    df_sorted = df.sort_values(rank_col, ascending=False).reset_index(drop=True)

    st.divider()
    st.markdown(f"#### 🏆 {rank_by} 排名 (Top 30)")

    top30 = df_sorted.head(30).copy()
    # 加上股價/漲跌到 y-axis label
    price_map = _cached_security_with_price()
    def _bar_label(sid, name):
        return f"{name} ({sid})"
    bar_labels = [_bar_label(r['stock_id'], r['名稱']) for _, r in top30.iterrows()]
    # 抓每個 bar 的 hover info (含股價/漲跌)
    hover_prices = []
    for _, r in top30.iterrows():
        sid = r['stock_id']
        if sid in price_map:
            p = price_map[sid]
            hover_prices.append(f"¥{p['close']:,.0f} ({p['change_pct']:+.2f}% {p['change_sign']})")
        else:
            hover_prices.append("")

    # Plotly horizontal bar
    fig_bar = go.Figure()
    colors = ['#26a69a' if v >= 10 else '#42a5f5' if v >= 5 else '#ffa726'
              for v in top30[rank_col]]
    fig_bar.add_trace(go.Bar(
        y=bar_labels,
        x=top30[rank_col],
        orientation='h',
        marker_color=colors,
        text=[f"{v:.2f}%" for v in top30[rank_col]],
        textposition='outside',
        hovertemplate=(
            '<b>%{customdata[2]} (%{customdata[3]})</b><br>'
            f'收盤: %{{customdata[4]}}<br>'
            f'{rank_by}: %{{x:.2f}}%<br>'
            '融資淨買: %{customdata[0]:+,} 張<br>'
            '成交量: %{customdata[1]:,} 張<extra></extra>'
        ),
        customdata=top30[['融資淨買(張)', '成交量(張)', '名稱', 'stock_id']].assign(
            _=hover_prices
        ).values,
    ))
    fig_bar.update_layout(
        height=800,
        title=f"{rank_by} 排名 Top 30 (hover 看股價/漲跌) (顏色: 🟢≥10% 🔵5-10% 🟠<5%)",
        xaxis_title=rank_by,
        yaxis=dict(autorange='reversed'),
        margin=dict(l=120),
    )
    st.plotly_chart(fig_bar, width="stretch")

    # 明細表（含當天 / 3 日 / 5 日三視角 + 5 種成交量增幅）
    st.markdown("#### 📋 完整明細表（含當天 / 3 日 / 5 日三視角 + 5 種成交量增幅）")
    display_df = df[['市值排名', 'stock_id', '名稱', '市場', '產業', '市值(億)',
                      '平均成交金額(5日)(億)', '當日成交金額(億)', '當日vs5日量增%', '收盤價', '漲跌幅%',
                      '融資買進(張)', '融資賣出(張)', '融資淨買(張)',
                      '成交量(張)', '成交量單日增%', '成交量較3日前增%', '成交量較5日前增%',
                      '主力力道%',
                      '融資力3日累計(張)', '成交量3日(張)', '成交量3日累計增%', '主力力道3日%',
                      '融資力5日累計(張)', '成交量5日(張)', '成交量5日累計增%', '主力力道5日%']].copy()
    # 格式化
    for col in ['融資買進(張)', '融資賣出(張)', '成交量(張)', '成交量3日(張)', '成交量5日(張)']:
        display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}")
    for col in ['融資淨買(張)', '融資力3日累計(張)', '融資力5日累計(張)']:
        display_df[col] = display_df[col].apply(lambda x: f"{int(x):+,}")
    for col in ['主力力道%', '主力力道3日%', '主力力道5日%',
                '成交量單日增%', '成交量3日累計增%', '成交量5日累計增%',
                '成交量較3日前增%', '成交量較5日前增%', '漲跌幅%']:
        display_df[col] = display_df[col].apply(lambda x: f"{x:+.2f}%")
    display_df['收盤價'] = display_df['收盤價'].apply(lambda x: f"{x:,.2f}")
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
- **必須搭配成交量門檻看**：高主力力道% + 低成交量 = 主力掛單沒人接（小心冷門股虛胖）
- 低主力力道% + 高成交量 = 大戶用現金（非融資）買的，沒被這指標抓到
- 集保庫存分級資料（早版錯誤指標）已棄用，那是「誰持有」週頻，不是「當天買賣」
""")


# ============================================================
# 三大法人 scan UI (新功能)
# ============================================================
def _render_institutional_scan():
    """三大法人買賣超 scan UI"""
    st.success(
        "✅ **真實三大法人資料** (finlab `institutional_investors_trading_summary:*`)。"
        "資料從 2012-05-02 起，3,521 個交易日，2,699 檔個股。"
    )

    # 排名類型 (合計 / 個別)
    inst_rank_type = st.radio(
        "🏛️ 排名類型",
        options=['合計 (三大法人)', '外資', '投信', '自營商'],
        index=0,
        key="inst_rank_type",
        horizontal=True,
        help=(
            "合計 = 外資+投信+自營商 一起算\n"
            "個別 = 各自獨立排名 (例如單看外資 10 日累計買超最多)"
        ),
    )
    # 時間視角
    time_window = st.radio(
        "📅 時間視角",
        options=['當天', '3 日累計', '5 日累計'],
        index=0,
        key="inst_time_window",
        horizontal=True,
    )

    # ============ 控制面板 ============
    with st.expander("⚙️ 篩選條件", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            market_cap_top = st.selectbox(
                "市值前幾大",
                options=[100, 200, 300, 500, 1000],
                index=2,
                key="inst_mv_top",
                help="用 etl:market_value 最新一日排序",
            )
            market_filter = st.multiselect(
                "市場別",
                options=['sii', 'otc'],
                default=['sii', 'otc'],
                key="inst_market",
                format_func=lambda x: {'sii': '上市 (sii)', 'otc': '上櫃 (otc)'}.get(x, x),
            )

        with col2:
            min_volume_lots = st.slider(
                "📊 最小當日成交量 (張)",
                min_value=0, max_value=50000, value=2000, step=500,
                key="inst_min_vol",
                help="過濾量能過小的個股，避免法人力道% 被虛胖",
            )

        with col3:
            min_inst_net = st.number_input(
                "🏛️ 最小三大法人合計淨買 (張)",
                min_value=0, value=0, step=100,
                key="inst_min_net",
                help="預設 0 = 不限。設 500 = 只列三大法人合計淨買 ≥ 500 張",
            )
            min_price_chg = st.number_input(
                "📈 最小漲跌幅 (%)",
                min_value=-10.0, max_value=10.0, value=0.0, step=0.5,
                key="inst_min_chg",
                help="預設 0 = 含下跌。設 5 = 只列漲 ≥ 5%",
            )

        # 成交量增幅篩選 (第 4 行)
        col4, col5 = st.columns([2, 1])
        with col4:
            min_vol_change = st.slider(
                "📈 最小成交量增幅 (%)",
                min_value=-80, max_value=500, value=0, step=10,
                key="inst_min_vol_change",
                help="套用於下方選擇的時間視角。0% = 不限",
            )
            vol_change_types = st.multiselect(
                "📊 成交量增幅套用於",
                options=['單日 (vs 昨日)', '3 日累計 (vs 前 3 日)', '5 日累計 (vs 前 5 日)',
                         '較 3 日前 (單日)', '較 5 日前 (單日)'],
                default=['單日 (vs 昨日)'],
                key="inst_vol_change_types",
            )

        col_btn1, col_btn2, _ = st.columns([1, 1, 4])
        with col_btn1:
            run_btn = st.button("🚀 重新掃描", type="primary", key="inst_refresh")
        with col_btn2:
            def _apply_inst_preset():
                st.session_state["inst_min_vol"] = 5000
                st.session_state["inst_min_net"] = 500
                st.session_state["inst_min_chg"] = 1.0
                st.session_state["inst_min_vol_change"] = 30
                st.session_state["inst_vol_change_types"] = ['單日 (vs 昨日)']
            st.button(
                "⭐ 用推薦條件",
                key="inst_preset",
                help="成交量 ≥ 5000 張 + 三大法人淨買 ≥ 500 張 + 漲 ≥ 1% + 量增 ≥30%",
                on_click=_apply_inst_preset,
            )

    if not market_filter:
        st.warning("請至少選一個市場")
        return

    if run_btn:
        st.cache_data.clear()
        st.rerun()

    with st.spinner("掃描三大法人中…"):
        df = _scan_institutional(
            market_cap_top=market_cap_top,
            min_volume_lots=min_volume_lots,
            min_inst_net_lots=min_inst_net,
            min_price_chg_pct=min_price_chg,
            market_filter=tuple(market_filter),
            min_vol_change_pct=min_vol_change,
            vol_change_filter_types=tuple(vol_change_types),
        )

    if df.empty:
        st.warning("沒有符合條件的個股，請放寬篩選條件")
        return

    # 決定排名欄位
    type_col_map = {
        ('合計 (三大法人)', '當天'): '三大法人力道%',
        ('合計 (三大法人)', '3 日累計'): '三大法人力道3日%',
        ('合計 (三大法人)', '5 日累計'): '三大法人力道5日%',
        ('外資', '當天'): '外資力道%',
        ('外資', '3 日累計'): '外資力道3日%',
        ('外資', '5 日累計'): '外資力道5日%',
        ('投信', '當天'): '投信力道%',
        ('投信', '3 日累計'): '投信力道3日%',
        ('投信', '5 日累計'): '投信力道5日%',
        ('自營商', '當天'): '自營商力道%',
        ('自營商', '3 日累計'): '自營商力道3日%',
        ('自營商', '5 日累計'): '自營商力道5日%',
    }
    rank_col = type_col_map[(inst_rank_type, time_window)]
    rank_title = f"{inst_rank_type} 力道% 排名 ({time_window})"

    scan_date = df.attrs.get('scan_date', '?')
    filter_summary = df.attrs.get('filter_summary', {})
    filter_text = " ｜ ".join([f"{k}={v}" for k, v in filter_summary.items()])
    st.caption(
        f"📅 資料日期 **{scan_date}** ｜ 符合條件 **{len(df)} 檔**\n\n"
        f"⚙️ {filter_text}"
    )

    # ============ 統計指標 ============
    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("符合條件", f"{len(df)} 檔")
    # 根據排名類型顯示對應統計
    if inst_rank_type == '合計 (三大法人)':
        stat_col = rank_col
        stat_label = "三大法人力道"
    elif inst_rank_type == '外資':
        stat_col = rank_col
        stat_label = "外資力道"
    elif inst_rank_type == '投信':
        stat_col = rank_col
        stat_label = "投信力道"
    else:
        stat_col = rank_col
        stat_label = "自營商力道"
    m2.metric(f"{stat_label} ≥ 10%", f"{(df[stat_col] >= 10).sum()} 檔")
    m3.metric(f"{stat_label} 5~10%", f"{((df[stat_col] >= 5) & (df[stat_col] < 10)).sum()} 檔")
    m4.metric(f"平均{stat_label}", f"{df[stat_col].mean():.2f}%")
    m5.metric(f"最高{stat_label}", f"{df[stat_col].max():.2f}%",
              delta=df.iloc[0]['名稱'])

    # ============ Top 30 排名 ============
    df_sorted = df.sort_values(rank_col, ascending=False).reset_index(drop=True)

    st.divider()
    st.markdown(f"#### 🏆 {rank_title} (Top 30)")

    top30 = df_sorted.head(30).copy()
    # 加上股價/漲跌到 y-axis label (hover 顯示)
    price_map = _cached_security_with_price()
    def _bar_label(sid, name):
        return f"{name} ({sid})"
    bar_labels = [_bar_label(r['stock_id'], r['名稱']) for _, r in top30.iterrows()]
    hover_prices = []
    for _, r in top30.iterrows():
        sid = r['stock_id']
        if sid in price_map:
            p = price_map[sid]
            hover_prices.append(f"¥{p['close']:,.0f} ({p['change_pct']:+.2f}% {p['change_sign']})")
        else:
            hover_prices.append("")

    fig_bar = go.Figure()
    colors = ['#26a69a' if v >= 10 else '#42a5f5' if v >= 5 else '#ffa726'
              for v in top30[rank_col]]
    # 自訂 hover
    if inst_rank_type == '合計 (三大法人)':
        net_col = f'三大法人合計(張)' if time_window == '當天' else f'三大法人合計{time_window[0]}日累計(張)'
        name_h = f"{inst_rank_type} 力道%"
    else:
        # 外資/投信/自營
        if inst_rank_type == '外資':
            net_col = f'外{inst_rank_type}買賣超(張)' if time_window == '當天' else f'外{inst_rank_type}{time_window[0]}日累計(張)'
        elif inst_rank_type == '投信':
            net_col = f'投信買賣超(張)' if time_window == '當天' else f'投信{time_window[0]}日累計(張)'
        else:
            net_col = f'自營商買賣超(張)' if time_window == '當天' else f'自營商{time_window[0]}日累計(張)'
        name_h = f"{inst_rank_type} 力道%"

    fig_bar.add_trace(go.Bar(
        y=bar_labels,
        x=top30[rank_col],
        orientation='h',
        marker_color=colors,
        text=[f"{v:.2f}%" for v in top30[rank_col]],
        textposition='outside',
        hovertemplate=(
            '<b>%{customdata[2]} (%{customdata[3]})</b><br>'
            f'收盤: %{{customdata[4]}}<br>'
            f'{name_h}: %{{x:.2f}}%<br>'
            f'{inst_rank_type}淨買: %{{customdata[0]:+,}} 張<br>'
            '成交量: %{customdata[1]:,} 張<extra></extra>'
        ),
        customdata=top30[[net_col, '成交量(張)', '名稱', 'stock_id']].assign(
            _=hover_prices
        ).values,
    ))
    fig_bar.update_layout(
        height=800,
        title=f"{rank_title} Top 30 (hover 看股價/漲跌) (顏色: 🟢≥10% 🔵5-10% 🟠<5%)",
        xaxis_title=rank_title,
        yaxis=dict(autorange='reversed'),
        margin=dict(l=120),
    )
    st.plotly_chart(fig_bar, width="stretch")

    # ============ 明細表（含 4 個法人 × 3 時間視角） ============
    st.markdown("#### 📋 完整明細表（4 法人 × 3 時間視角）")
    display_cols = [
        '市值排名', 'stock_id', '名稱', '市場', '產業', '市值(億)',
        '平均成交金額(5日)(億)', '當日成交金額(億)', '當日vs5日量增%', '收盤價', '漲跌幅%',
        '外資買賣超(張)', '投信買賣超(張)', '自營商買賣超(張)', '三大法人合計(張)',
        '成交量(張)', '成交量單日增%', '成交量較3日前增%', '成交量較5日前增%',
        '外資力道%', '投信力道%', '自營商力道%', '三大法人力道%',
        '外資3日累計(張)', '投信3日累計(張)', '自營商3日累計(張)', '三大法人合計3日(張)',
        '成交量3日(張)', '成交量3日累計增%',
        '外資力道3日%', '投信力道3日%', '自營商力道3日%', '三大法人力道3日%',
        '外資5日累計(張)', '投信5日累計(張)', '自營商5日累計(張)', '三大法人合計5日(張)',
        '成交量5日(張)', '成交量5日累計增%',
        '外資力道5日%', '投信力道5日%', '自營商力道5日%', '三大法人力道5日%',
    ]
    display_df = df[display_cols].copy()
    # 格式化
    for col in ['成交量(張)', '成交量3日(張)', '成交量5日(張)']:
        display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}")
    display_df['收盤價'] = display_df['收盤價'].apply(lambda x: f"{x:,.2f}")
    if '市值排名' in display_df.columns:
        display_df['市值排名'] = display_df['市值排名'].apply(lambda x: str(int(x)))
    if '平均成交金額(5日)(億)' in display_df.columns:
        display_df['平均成交金額(5日)(億)'] = display_df['平均成交金額(5日)(億)'].apply(lambda x: f"{x:.2f}")
    if '當日成交金額(億)' in display_df.columns:
        display_df['當日成交金額(億)'] = display_df['當日成交金額(億)'].apply(lambda x: f"{x:.2f}")
    if '當日vs5日量增%' in display_df.columns:
        display_df['當日vs5日量增%'] = display_df['當日vs5日量增%'].apply(lambda x: f"{x:+.2f}%")
    # 5 種成交量增幅欄位名稱（明確白名單，避免跟「當日vs5日量增%」已格式化字串重複 format）
    VOL_CHANGE_COLS = ['成交量單日增%', '成交量3日累計增%', '成交量5日累計增%',
                       '成交量較3日前增%', '成交量較5日前增%']
    for col in display_cols:
        if '(張)' in col and col not in ['成交量(張)', '成交量3日(張)', '成交量5日(張)']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:+,.1f}")
        elif '力道%' in col or col == '漲跌幅%' or col in VOL_CHANGE_COLS:
            display_df[col] = display_df[col].apply(lambda x: f"{x:+.2f}%")
    st.dataframe(display_df, hide_index=True, width="stretch", height=600)

    # ============ CSV 下載 ============
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"⬇️ 下載三大法人掃描 ({len(df)} 檔 CSV)",
        data=csv_bytes,
        file_name=f"three_inst_scan_{scan_date.replace('-', '')}.csv",
        mime="text/csv",
        key="inst_download_csv",
    )

    # ============ 公式說明 ============
    with st.expander("📐 法人力道% 公式 & 資料來源"):
        st.markdown("""
### 三大法人力道 % 公式

```
法人力道% = 法人淨買(股) / 成交量(股) × 100
         = 法人買賣超(股) / 成交量(股) × 100
         = 法人買賣超(張) / 成交量(張) × 100  (張 = 1000 股)
```

### 解讀

| 法人力道% | 意義 |
|---|---|
| **≥ 10%** | 🔥 法人主導 — 當日該法人買盤佔成交 10% 以上 |
| **5% ~ 10%** | 💪 中度法人 — 法人買盤是當日主要驅動力之一 |
| **2% ~ 5%** | 👀 輕度法人 — 法人買盤輕微，但方向正向 |
| **< 2%** | 📊 微量法人 — 法人買盤不顯著 |

### 資料來源

| 法人類別 | finlab key | 原始單位 | 備註 |
|---|---|---|---|
| **外資** | `institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)` | 股 | 不含外資自營商 (避險) |
| **投信** | `institutional_investors_trading_summary:投信買賣超股數` | 股 | 投信發行基金 |
| **自營商** | `institutional_investors_trading_summary:自營商買賣超股數(自行買賣)` | 股 | 券商自有資金 (不含避險) |

### ⚠️ 注意

- 「法人力道%」反映的是「法人買盤佔當日成交的比重」，**不是資金總量**
- **必須搭配成交量門檻看**：高力道% + 低成交量 = 法人掛單沒人接（小心冷門股虛胖）
- 低力道% + 高成交量 = 大戶用現金（非融資）買的，沒被這指標抓到
- 個股「三大法人合計」= 外資 + 投信 + 自營商 (不含外資自營商避險、券商避險)
""")

