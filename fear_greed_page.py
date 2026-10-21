"""
fear_greed_page.py — Fear & Greed Index Dashboard

美 / 台 / 韓 / 日 四大市場恐慌貪婪指數對照

資料來源：
    - 美國 FGI + 組件 : CNN 官方 API（feargreedchart.com）
    - 台/日/韓 FGI   : 自算（CNN 同架構 5 組件模型，見 fear_greed_fetcher.py）
    - 四大指數 + VIX : FinLab `world_index:close`

版面：
    1. FGI Timeline 對照圖（四國折線 + 恐慌/中立/貪婪背景色帶）
    2. 各國指數水位表（含當日漲跌幅）
    3. 組件分解長條圖
    4. FGI 歷史明細表（含下載 CSV）
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from fear_greed_fetcher import (
    MARKETS,
    FGI_BANDS,
    fgi_to_color,
    fgi_to_rating,
    load_fgi_data,
)


# ============================================================
# 資料載入
# ============================================================
@st.cache_data(ttl=1800, show_spinner="載入 Fear & Greed 資料…")
def _load():
    try:
        return load_fgi_data()
    except Exception as e:
        try:
            from data_fetcher import ensure_finlab_login
            ensure_finlab_login()
            load_fgi_data.clear() if hasattr(load_fgi_data, "clear") else None
            return load_fgi_data()
        except Exception as e2:
            st.error(f"載入 Fear & Greed 資料失敗：{e} / {e2}")
            st.stop()


# ============================================================
# 圖表：FGI Timeline
# ============================================================
def _add_fgi_bands(fig: go.Figure) -> go.Figure:
    """加恐慌/中立/貪婪背景色帶（y 軸 0-100）"""
    for lo, hi, en, cn in FGI_BANDS:
        # 顏色：越恐慌越紅、越貪婪越綠（跟 CNN 一致）
        if en == "Extreme Fear":
            rgba = "rgba(192,57,43,0.14)"
        elif en == "Fear":
            rgba = "rgba(230,126,34,0.12)"
        elif en == "Neutral":
            rgba = "rgba(241,196,15,0.10)"
        elif en == "Greed":
            rgba = "rgba(139,195,74,0.12)"
        else:
            rgba = "rgba(39,174,96,0.14)"
        fig.add_hrect(y0=lo, y1=hi, line_width=0, fillcolor=rgba,
                      layer="below", annotation_text=cn, annotation_position="left",
                      annotation_font_size=10,
                      annotation_font_color="rgba(120,120,120,0.55)")

    # 中線 50
    fig.add_hline(y=50, line_width=1, line_dash="dash",
                  line_color="rgba(150,150,150,0.6)")
    return fig


def _plot_fgi_timeline(fgi: pd.DataFrame, start=None, end=None,
                       markets: list[str] | None = None) -> go.Figure:
    """四國 FGI 折線對照圖"""
    df = fgi.copy()
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    if markets:
        keep = [m for m in markets if m in df.columns]
        df = df[keep]

    fig = go.Figure()
    for mkt in df.columns:
        meta = MARKETS.get(mkt, {"label": mkt, "color": "#888888"})
        s = df[mkt].dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines+markers",
            name=f"{meta['label']} ({s.iloc[-1]:.0f})",
            line=dict(color=meta["color"], width=2.5),
            marker=dict(size=4),
            hovertemplate=f"<b>{meta['label']}</b><br>"
                          "日期: %{x|%Y-%m-%d}<br>"
                          "FGI: %{y:.1f}<extra></extra>",
        ))
        # 末端標籤
        fig.add_annotation(
            x=s.index[-1], y=s.iloc[-1],
            text=f" {s.iloc[-1]:.0f}",
            showarrow=False, xanchor="left",
            font=dict(color=meta["color"], size=13, family="Arial Black"),
        )

    _add_fgi_bands(fig)

    fig.update_layout(
        title="美 / 台 / 韓 / 日 恐懼貪婪指數對照 — 越低越恐懼",
        height=520,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=10, r=55, t=75, b=30),
        yaxis=dict(title="Fear & Greed 指數 (0-100)", range=[0, 105],
                   gridcolor="rgba(200,200,200,0.3)"),
        xaxis=dict(gridcolor="rgba(200,200,200,0.2)"),
        plot_bgcolor="white",
    )
    return fig


# ============================================================
# 圖表：組件分解
# ============================================================
def _market_components(comp: pd.DataFrame, market: str) -> pd.DataFrame:
    """從攤平的 comp DataFrame 取出單一市場的組件欄位（欄位名格式 '市場::組件'）"""
    if comp.empty:
        return pd.DataFrame()
    cols = [c for c in comp.columns
            if str(c).split("::")[0] == market]
    if not cols:
        return pd.DataFrame()
    return comp[cols].rename(columns=lambda c: str(c).split("::")[-1])


def _plot_components(comp: pd.DataFrame, market: str) -> go.Figure | None:
    """單一市場的組件分解長條圖"""
    sub = _market_components(comp, market).dropna(how="all")
    if sub.empty:
        st.warning(f"{MARKETS.get(market, {}).get('label', market)} 暫無組件資料")
        return None

    latest = sub.iloc[-1]
    latest_date = sub.index[-1]

    fig = go.Figure()
    colors = [fgi_to_color(v) for v in latest.values]
    fig.add_trace(go.Bar(
        x=list(latest.index), y=list(latest.values),
        marker_color=colors,
        text=[f"{v:.0f}" for v in latest.values],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>分數: %{y:.1f}<extra></extra>",
    ))
    fig.add_hline(y=50, line_dash="dash", line_color="rgba(150,150,150,0.6)")
    fig.add_hrect(y0=0, y1=24, line_width=0, fillcolor="rgba(192,57,43,0.10)",
                  layer="below")
    fig.add_hrect(y0=75, y1=100, line_width=0, fillcolor="rgba(39,174,96,0.10)",
                  layer="below")

    meta = MARKETS.get(market, {"label": market})
    fig.update_layout(
        title=f"{meta['label']} 組件分解（{latest_date:%Y-%m-%d}）",
        height=340,
        yaxis=dict(title="組件分數 (0-100)", range=[0, 118]),
        xaxis=dict(title=""),
        showlegend=False,
        margin=dict(l=10, r=10, t=55, b=30),
        plot_bgcolor="white",
    )
    return fig


# ============================================================
# 圖表：指數水位走勢
# ============================================================
def _plot_index_trend(index_df: pd.DataFrame, start=None, end=None) -> go.Figure:
    """四大指數累計報酬率對比（normalize 到 100）"""
    df = index_df.copy()
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    cols = ["^GSPC", "^TWII", "^N225", "^KS11"]
    cols = [c for c in cols if c in df.columns]

    fig = go.Figure()
    for c in cols:
        s = df[c].dropna()
        if s.empty:
            continue
        norm = s / s.iloc[0] * 100
        meta = next((m for m in MARKETS.values() if m["idx"] == c), {})
        label = meta.get("label", c)
        fig.add_trace(go.Scatter(
            x=norm.index, y=norm.values, mode="lines",
            name=f"{label} ({norm.iloc[-1] - 100:+.1f}%)",
            line=dict(color=meta.get("color", "#888"), width=2),
            hovertemplate=f"<b>{label}</b><br>%{{x|%Y-%m-%d}}<br>"
                          "相對報酬: %{y:.1f}%<extra></extra>",
        ))
    fig.add_hline(y=100, line_dash="dash", line_color="rgba(150,150,150,0.5)")

    fig.update_layout(
        title="四大指數相對報酬走勢（區間起點 = 100）",
        height=380, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis=dict(title="相對報酬 (起點=100)"),
        margin=dict(l=10, r=10, t=75, b=30),
        plot_bgcolor="white",
    )
    return fig


# ============================================================
# 各國指數水位表
# ============================================================
def _build_index_table(index_df: pd.DataFrame, fgi: pd.DataFrame,
                       rating_cn: pd.DataFrame) -> pd.DataFrame:
    """組裝各國指數水位 + FGI 表格"""
    rows = []
    for mkt, meta in MARKETS.items():
        col = meta["idx"]
        if col not in index_df.columns:
            continue
        s = index_df[col].dropna()
        if s.empty:
            continue

        # 取有 FGI 的最後一個日期（對齊）
        fgi_col = fgi[mkt].dropna() if mkt in fgi.columns else pd.Series(dtype=float)
        if not fgi_col.empty:
            fgi_date = fgi_col.index[-1]
            # 找當日或之前最近的指數值
            s_aligned = s[s.index <= fgi_date]
            score = fgi_col.iloc[-1]
            rating = rating_cn[mkt].dropna()
            r_txt = rating.iloc[-1] if not rating.empty else "—"
        else:
            s_aligned = s
            score, r_txt = None, "—"

        if s_aligned.empty:
            continue
        last_val = s_aligned.iloc[-1]
        prev_val = s_aligned.iloc[-2] if len(s_aligned) >= 2 else None
        chg = ((last_val / prev_val - 1) * 100) if prev_val else None

        rows.append({
            "市場": meta["cn"],
            "指數": meta["label"].split(" ")[-1],
            "FGI": f"{score:.0f}" if score is not None else "—",
            "狀態": r_txt,
            "指數水位": f"{last_val:,.2f}",
            "當日漲跌": f"{chg:+.2f}%" if chg is not None else "—",
            "日期": s_aligned.index[-1].strftime("%Y-%m-%d"),
        })

    return pd.DataFrame(rows)


# ============================================================
# 主 render 函式
# ============================================================
def render_fear_greed_page():
    st.title("😱 恐懼貪婪指數 Dashboard")
    st.caption(
        "美 / 台 / 韓 / 日 四大市場恐慌貪婪指數對照 — "
        "美國用 CNN 官方資料，台/日/韓用同架構模型自算。"
        "**越低越恐懼，越高越貪婪。**"
    )

    bundle = _load()
    fgi = bundle["fgi"]
    index_df = bundle["index"]
    comp = bundle["comp"]
    rating_cn = bundle["rating_cn"]

    if fgi.empty:
        st.error("沒有 Fear & Greed 資料，請檢查網路或 finlab 連線")
        st.stop()

    # ---------- 控制列 ----------
    st.markdown("---")
    c1, c2, c3 = st.columns([1.2, 1.5, 2])

    with c1:
        fgi_min = fgi.index.min()
        fgi_max = fgi.index.max()
        st.caption(f"資料範圍：{fgi_min:%Y-%m-%d} ~ {fgi_max:%Y-%m-%d}")

    with c2:
        range_opts = {
            "全部": (None, None),
            "近 3 個月": (fgi_max - pd.Timedelta(days=92), None),
            "近 6 個月": (fgi_max - pd.Timedelta(days=183), None),
            "2026 下半年": ("2026-07-01", None),
            "2026 上半年": (None, "2026-06-30"),
        }
        range_sel = st.selectbox("時間範圍", list(range_opts.keys()), index=0)
        rs, re_ = range_opts[range_sel]

    with c3:
        available = [m for m in MARKETS if m in fgi.columns and fgi[m].notna().any()]
        mkt_labels = {MARKETS[m]["label"]: m for m in available}
        picked_labels = st.multiselect(
            "顯示市場", options=list(mkt_labels.keys()),
            default=list(mkt_labels.keys()),
        )
        picked = [mkt_labels[l] for l in picked_labels]

    if not picked:
        st.warning("請至少選一個市場")
        st.stop()

    # ---------- 1. FGI Timeline ----------
    st.markdown("---")
    st.subheader("📈 恐慌貪婪指數時間軸")
    fig = _plot_fgi_timeline(fgi, start=rs, end=re_, markets=picked)
    st.plotly_chart(fig, use_container_width=True)

    # ---------- 2. 各國指數水位表 ----------
    st.markdown("---")
    st.subheader("📊 各國指數水位")
    idx_tbl = _build_index_table(index_df, fgi, rating_cn)
    if not idx_tbl.empty:
        st.dataframe(
            idx_tbl, use_container_width=True, hide_index=True,
            column_config={
                "當日漲跌": st.column_config.TextColumn("當日漲跌"),
            },
        )
        st.caption(f"資料時間：{pd.Timestamp.now():%Y-%m-%d %H:%M:%S}（台北時間）")
        st.caption(
            f"資料來源：美國 = CNN 官方（{bundle.get('fgi_us_source', '—')}）· "
            "台/日/韓 = 自算 · 指數 = FinLab"
        )

    # ---------- 3. 組件分解 ----------
    st.markdown("---")
    st.subheader("🧩 組件分解")
    st.caption("每個組件都是 0-100 分；分數越高代表該面向越『貪婪』。")

    sel_market = st.selectbox(
        "選市場看組件",
        options=picked,
        format_func=lambda m: MARKETS.get(m, {}).get("label", m),
    )
    comp_fig = _plot_components(comp, sel_market)
    if comp_fig is not None:
        st.plotly_chart(comp_fig, use_container_width=True)

        # 組件歷史小圖
        sub = _market_components(comp, sel_market).dropna(how="all")
        if not sub.empty and len(sub) > 3:
            st.caption("組件分數歷史走勢")
            h_fig = go.Figure()
            for c in sub.columns:
                h_fig.add_trace(go.Scatter(
                    x=sub.index, y=sub[c], mode="lines", name=c,
                    hovertemplate=f"<b>{c}</b><br>%{{x|%Y-%m-%d}}<br>"
                                  "%{y:.1f}<extra></extra>",
                ))
            h_fig.add_hline(y=50, line_dash="dash",
                            line_color="rgba(150,150,150,0.5)")
            h_fig.update_layout(
                height=320, hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                yaxis=dict(title="分數", range=[0, 105]),
                margin=dict(l=10, r=10, t=55, b=30),
                plot_bgcolor="white",
            )
            st.plotly_chart(h_fig, use_container_width=True)

    # ---------- 4. 指數相對報酬 ----------
    st.markdown("---")
    st.subheader("📉 四大指數相對報酬")
    idx_fig = _plot_index_trend(index_df, start=rs, end=re_)
    st.plotly_chart(idx_fig, use_container_width=True)

    # ---------- 5. 歷史明細表 ----------
    st.markdown("---")
    with st.expander("📋 FGI 歷史明細表（含下載）", expanded=False):
        tbl = fgi.copy()
        for mkt in tbl.columns:
            tbl[f"{mkt} 狀態"] = rating_cn[mkt]
        tbl = tbl.sort_index(ascending=False)
        tbl.index = tbl.index.strftime("%Y-%m-%d")
        tbl.index.name = "日期"
        st.dataframe(tbl.round(1), use_container_width=True)

        csv = fgi.to_csv().encode("utf-8-sig")
        st.download_button(
            "⬇️ 下載 FGI 歷史 CSV", data=csv,
            file_name=f"fear_greed_{pd.Timestamp.now():%Y%m%d}.csv",
            mime="text/csv",
        )

    # ---------- 說明 ----------
    st.markdown("---")
    with st.expander("ℹ️ FGI 是怎麼算的？", expanded=False):
        st.markdown(
            """
**美國（CNN 官方）**
- 直接使用 CNN Fear & Greed Index 官方 API（feargreedchart.com）
- 官方由 7 個組件加權而成：波動率（VIX）、市場動能、股價強度、股價廣度、Put/Call 比率、垃圾債需求、避險需求

**台灣 / 日本 / 韓國（自算）**
- 沒有官方版本，用與 CNN 同架構的 **5 組件模型**計算：
  1. **動能 Momentum**（20 日報酬率的 120 日百分位）
  2. **強度 Strength**（收盤 vs MA50）
  3. **趨勢 Trend**（MA20 vs MA60 多空排列）
  4. **波動 Volatility**（20 日實現波動率，反向：波動高 = 恐慌）
  5. **量能 Volume**（20 日均量 / 60 日均量）
- 每個組件等權重 20%，加權平均即為 FGI

**⚠️ 重要提醒**
- 美國用官方值、台日韓用自算值，**兩者口徑不同**，適合看「趨勢方向」與「相對冷熱」，
  但不宜直接做絕對值比較（例如「台灣 FGI 51 比美國 23 更樂觀」這種推論要小心）。
- 台日韓的自算值會與 CNN 官方法則有落差，數字僅供參考。
            """
        )