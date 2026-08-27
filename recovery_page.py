#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
recovery_page.py — 全市場「均線收復」個股搜尋

目的：找「曾經跌破 5MA/10MA/20MA/60MA，後續又陸續站回均線，且長期均線往上」的個股
（V 轉 / U 轉 / 黃金交叉後續漲型態）

頁面 3 區塊：
1. 控制區 — 回看天數、最低市值、成交量門檻、要不要排除 ETF/權證
2. 全市場概況 — 多少檔通過掃描
3. 清單表格 — 排序 / 篩選 / 個股展開
4. 個股 K 線 + 4 條 MA（展開）
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ma_recovery_scanner import (
    check_recovery,
    scan_market,
    DEFAULT_LOOKBACK,
    DEFAULT_MA_WINDOWS,
)
from data_fetcher import (
    ensure_finlab_login,
    get_stock_name,
)


# ============================================================
# 載入全市場收盤價（用 finlab + 一些 cache）
# ============================================================
@st.cache_data(ttl=3600, show_spinner="載入全市場收盤價中…（從 finlab）")
def _load_close_wide(market: str = "sii", days: int = 250) -> pd.DataFrame:
    """從 finlab 抓全市場 wide close DF"""
    from finlab import data
    if market == "sii":
        with data.universe(market="TSE"):
            close = data.get("price:收盤價")
    elif market == "otc":
        with data.universe(market="OTC"):
            close = data.get("price:收盤價")
    elif market == "all":
        close = data.get("price:收盤價")
    else:
        close = data.get("price:收盤價")
    return close.tail(days)


@st.cache_data(ttl=3600, show_spinner="載入全市場成交量中…")
def _load_volume_wide(market: str = "sii", days: int = 250) -> pd.DataFrame:
    from finlab import data
    if market == "sii":
        with data.universe(market="TSE"):
            vol = data.get("price:成交股數")
    elif market == "otc":
        with data.universe(market="OTC"):
            vol = data.get("price:成交股數")
    else:
        vol = data.get("price:成交股數")
    return vol.tail(days)


# ============================================================
# Streamlit 頁面
# ============================================================
def render_recovery_page():
    st.header("🔍 均線收復個股搜尋")
    st.caption(
        "找「曾經跌破 5/10/20/60 MA，後續又陸續站回均線，且長期均線（MA60）往上」的個股。"
        "V 轉 / U 轉 / 黃金交叉後續漲型態。"
    )

    # === 控制區 ===
    with st.container():
        col1, col2, col3 = st.columns(3)
        with col1:
            market = st.radio(
                "市場範圍",
                options=["sii (上市)", "otc (上櫃)", "all (全部)"],
                index=0,
                key="recovery_market",
            )
            market_code = market.split(" ")[0]
        with col2:
            lookback = st.slider(
                "回看天數（過去 N 日內要跌破過）",
                min_value=20, max_value=120, value=60, step=10,
                key="recovery_lookback",
                help="過去 N 日內要曾經跌破所有 4 條均線",
            )
            ma60_slope = st.slider(
                "MA60 斜率回看天數",
                min_value=5, max_value=60, value=20, step=5,
                key="recovery_ma60_slope",
                help="比較 N 日前的 MA60 跟現在的 MA60，必須往上",
            )
        with col3:
            min_avg_volume = st.number_input(
                "最低 20 日均量 (張)",
                min_value=0, value=500, step=100,
                key="recovery_min_vol",
                help="過濾量太小的冷門股，0 = 不過濾",
            )
            exclude_etf = st.checkbox(
                "排除 ETF/權證 (etfinfo security_categories)",
                value=True,
                key="recovery_excl_etf",
            )

    st.divider()

    # === 載入資料 ===
    try:
        ensure_finlab_login()
    except Exception as e:
        st.error(f"❌ finlab login 失敗：`{e}`")
        return

    try:
        close_wide = _load_close_wide(market_code, days=lookback + 90)
        vol_wide = _load_volume_wide(market_code, days=lookback + 90)
    except Exception as e:
        st.error(f"❌ 抓 finlab 資料失敗：`{e}`")
        return

    if close_wide.empty:
        st.warning("⚠️ 沒抓到任何 close 資料")
        return

    # 排除 ETF/權證（從 etfinfo security_categories）
    if exclude_etf:
        try:
            cat = _load_security_categories()
            etf_or_warrant = cat[cat["market"].isin(["etf", "warrant", "rotc", "other_securities"])]["stock_id"].astype(str).tolist()
            keep_cols = [c for c in close_wide.columns if c not in etf_or_warrant]
            close_wide = close_wide[keep_cols]
            vol_wide = vol_wide[keep_cols]
        except Exception as e:
            st.warning(f"⚠️ 無法排除 ETF/權證：`{e}`")

    st.caption(f"掃描範圍：{len(close_wide.columns)} 檔個股（{close_wide.index[0].date()} ~ {close_wide.index[-1].date()}）")

    # 最低成交量過濾
    if min_avg_volume > 0:
        avg_vol = vol_wide.tail(20).mean()
        # vol_wide 是股數，要除以 1000 換張
        avg_vol_zhang = avg_vol / 1000
        keep = avg_vol_zhang[avg_vol_zhang >= min_avg_volume].index
        before = len(close_wide.columns)
        close_wide = close_wide[keep]
        st.caption(f"  最低 20 日均量過濾（≥{min_avg_volume} 張）：{before} → {len(close_wide.columns)} 檔")

    # === 跑掃描 ===
    @st.cache_data(ttl=1800, show_spinner="跑均線收復掃描中…")
    def _run_scan(close_hash, lookback_v, slope_v):
        # close_hash 用來區分不同 close_wide（避免 cache 用錯）
        return scan_market(
            close_wide,
            lookback=lookback_v,
            ma60_slope_lookback=slope_v,
        )

    with st.spinner(f"掃描 {len(close_wide.columns)} 檔個股…"):
        df_result = _run_scan(close_wide.to_csv().encode(), lookback, ma60_slope)

    # === 概況 ===
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("掃描個股數", f"{len(close_wide.columns)} 檔")
    c2.metric("通過均線收復", f"{len(df_result)} 檔", delta=f"{len(df_result)/max(len(close_wide.columns),1)*100:.1f}%")
    if len(df_result) > 0:
        c3.metric("MA60 平均斜率", f"{df_result['ma60_slope_20d'].mean():+.2f}%")
        c4.metric("距 MA20 平均", f"{df_result['dist_to_ma20_pct'].mean():+.2f}%")
    else:
        c3.metric("MA60 平均斜率", "—")
        c4.metric("距 MA20 平均", "—")

    st.divider()

    if len(df_result) == 0:
        st.warning("⚠️ 沒有任何個股通過條件。試著放寬條件（回看天數拉長 / MA60 斜率拉短 / 最低量降低）")
        return

    # === 排序 + 篩選 ===
    col1, col2, col3 = st.columns(3)
    with col1:
        sort_by = st.selectbox(
            "排序依據",
            options=["MA60 斜率", "距 MA20 距離", "近期 20 日漲幅", "近期 60 日漲幅"],
            index=0,
            key="recovery_sort",
        )
    with col2:
        top_n = st.slider("顯示前 N 名", 5, min(50, len(df_result)), min(20, len(df_result)), 5)
    with col3:
        min_slope = st.slider("MA60 斜率下限 (%)", 0.0, 5.0, 0.0, 0.1)

    sort_col = {
        "MA60 斜率": "ma60_slope_20d",
        "距 MA20 距離": "dist_to_ma20_pct",
        "近期 20 日漲幅": "recent_20_return",
        "近期 60 日漲幅": "recent_60_return",
    }[sort_by]

    df_show = df_result[df_result["ma60_slope_20d"] >= min_slope].copy()
    df_show = df_show.sort_values(sort_col, ascending=False).head(top_n)

    # === 補中文名稱 ===
    name_map = {}
    for sid in df_show["stock_id"]:
        try:
            name_map[sid] = get_stock_name(sid)
        except Exception:
            name_map[sid] = sid
    df_show["name"] = df_show["stock_id"].map(name_map).fillna(df_show["stock_id"])

    # === 顯示清單 ===
    st.subheader(f"📋 通過個股清單（{len(df_show)} 檔）")

    display_cols = [
        "stock_id", "name", "current_close",
        "current_ma5", "current_ma10", "current_ma20", "current_ma60",
        "ma60_slope_20d", "dist_to_ma20_pct",
        "recent_20_return", "recent_60_return",
    ]
    df_disp = df_show[display_cols].copy()
    df_disp.columns = [
        "代號", "名稱", "收盤",
        "MA5", "MA10", "MA20", "MA60",
        "MA60 斜率%", "距 MA20%",
        "20日漲幅%", "60日漲幅%",
    ]

    def fmt(v, plus=False, dec=2):
        if pd.isna(v) or v is None: return "—"
        sign = "+" if plus and v > 0 else ""
        return f"{sign}{v:.{dec}f}"

    for c in ["收盤", "MA5", "MA10", "MA20", "MA60"]:
        df_disp[c] = df_disp[c].apply(lambda v: fmt(v, dec=2))
    for c in ["MA60 斜率%", "距 MA20%", "20日漲幅%", "60日漲幅%"]:
        df_disp[c] = df_disp[c].apply(lambda v: fmt(v, plus=True, dec=2))

    def color_pos(v):
        if v == "—": return ""
        try:
            num = float(v.replace("%", "").replace("+", ""))
        except Exception:
            return ""
        if num > 0: return "color: #ef5350; font-weight: 600"
        if num < 0: return "color: #26a69a"
        return ""

    st.dataframe(
        df_disp.style.map(color_pos, subset=["MA60 斜率%", "距 MA20%", "20日漲幅%", "60日漲幅%"]),
        width="stretch",
        hide_index=True,
    )

    st.divider()

    # === 個股展開 K 線 ===
    st.subheader("📈 個股 K 線展開（看收復過程）")
    st.caption("從清單選一檔看 K 線 + 4 條 MA + 收復過程標註")

    c1, c2 = st.columns([3, 1])
    with c1:
        stock_pick = st.selectbox(
            "選個股",
            options=df_show["stock_id"].tolist(),
            format_func=lambda c: f"{c} {name_map.get(c, '')}",
            key="recovery_pick",
        )
    with c2:
        st.write("")
        st.write("")
        st.caption("K 線 + 4 條 MA + 收復標註")

    if stock_pick:
        _render_stock_chart(stock_pick, close_wide, lookback)


# ============================================================
# 個股 K 線 + 收復過程標註
# ============================================================
def _render_stock_chart(stock_id: str, close_wide: pd.DataFrame, lookback: int):
    if stock_id not in close_wide.columns:
        st.error(f"找不到 {stock_id}")
        return

    s = close_wide[stock_id].dropna()
    if len(s) < 70:
        st.error(f"{stock_id} 資料不足")
        return

    # 計算 MA
    from ma_recovery_scanner import calc_mas
    df = calc_mas(s)

    # 標記收復事件
    recovery_info = check_recovery(s, lookback=lookback)

    # 畫圖
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.75, 0.25],
    )

    # 收盤折線
    fig.add_trace(go.Scatter(
        x=df.index, y=df["close"],
        name="收盤", mode="lines+markers",
        line=dict(color="#42a5f5", width=2),
        marker=dict(size=4),
    ), row=1, col=1)

    # 4 條 MA
    ma_colors = {5: "#26a69a", 10: "#ab47bc", 20: "#ffa726", 60: "#ef5350"}
    for w in [5, 10, 20, 60]:
        fig.add_trace(go.Scatter(
            x=df.index, y=df[f"MA{w}"],
            name=f"MA{w}", mode="lines",
            line=dict(color=ma_colors[w], width=1.5),
        ), row=1, col=1)

    # 標記跌破最後一天（每條 MA）
    annotations = []
    for w in [5, 10, 20, 60]:
        last_break = recovery_info["stats"].get(f"last_break_ma{w}_date")
        if last_break is not None and last_break in df.index:
            row_y = df.loc[last_break, f"MA{w}"]
            annotations.append(dict(
                x=last_break, y=row_y,
                xref="x", yref="y",
                text=f"破 MA{w}<br>{last_break.strftime('%m/%d')}",
                showarrow=True, arrowhead=2, arrowcolor=ma_colors[w],
                ax=0, ay=-30,
                font=dict(size=9, color=ma_colors[w]),
                bgcolor="rgba(0,0,0,0.5)",
            ))

    # 標記收復日（每條 MA 第一次 close > MA 的日期）
    for w in [5, 10, 20, 60]:
        recovery_date = None
        for i in range(len(df)):
            if pd.notna(df[f"MA{w}"].iloc[i]) and df["close"].iloc[i] > df[f"MA{w}"].iloc[i]:
                # 找收復後第一個就一直站在之上的
                if i + 1 < len(df) and (df["close"].iloc[i+1:] > df[f"MA{w}"].iloc[i+1:]).all():
                    recovery_date = df.index[i]
                    break
        if recovery_date is not None and recovery_date in df.index:
            row_y = df.loc[recovery_date, "close"]
            annotations.append(dict(
                x=recovery_date, y=row_y,
                xref="x", yref="y",
                text=f"✅ 收復 MA{w}<br>{recovery_date.strftime('%m/%d')}",
                showarrow=True, arrowhead=2, arrowcolor="#26a69a",
                ax=0, ay=30,
                font=dict(size=9, color="#26a69a"),
                bgcolor="rgba(0,0,0,0.5)",
            ))

    # Volume（用股數）
    # 這裡簡化只畫 close 變化，volume 之後可加
    fig.update_layout(
        template="plotly_dark",
        height=600,
        title=f"{stock_id} K 線 + 4 條 MA（收復過程標註）",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        annotations=annotations,
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_yaxes(title_text="價格", row=1, col=1)
    fig.update_yaxes(title_text="（保留）", row=2, col=1, showticklabels=False)

    st.plotly_chart(fig, width="stretch")

    # 統計
    stats = recovery_info["stats"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("MA60 斜率（20日）", f"{stats.get('ma60_slope_20d', 0):+.2f}%")
    c2.metric("距 MA20", f"{stats.get('dist_to_ma20_pct', 0):+.2f}%")
    c3.metric("20日漲幅", f"{stats.get('recent_20_return', 0):+.2f}%")
    c4.metric("60日漲幅", f"{stats.get('recent_60_return', 0):+.2f}%")

    if recovery_info["reasons"]:
        st.warning(f"⚠️ 此股已不通過條件：`{', '.join(recovery_info['reasons'])}`（可能今天剛跌破）")


# ============================================================
# Helper
# ============================================================
@st.cache_data(ttl=3600)
def _load_security_categories():
    from finlab import data
    cat = data.get("security_categories")
    cat["stock_id"] = cat["stock_id"].astype(str)
    return cat
