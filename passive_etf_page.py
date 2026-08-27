#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
passive_etf_page.py — 被動式 ETF 追蹤（台股主流 20+ 檔）

etfinfo.tw 沒有「被動 ETF 清單」summary endpoint，只有單檔 detail。
所以用預設熱門清單 + `/api/etf/{code}` 抓詳細（`info.managementStyle == "passive"`）。

頁面 4 區塊：
1. 被動 ETF 清單 — 管理費 / 規模 / 折溢價 / 1Y 報酬（表格 + 篩選器）
2. 折溢價排行 — 找出套利機會（折價/溢價幅度）
3. 個股查詢 — 輸入股票代號，看被哪些被動 ETF 持有 + 權重
4. ETF 查詢 — 輸入代號，看完整持股（共用 etfinfo_fetcher.fetch_etf_detail）

Cache 策略：每檔 ETF detail cache 1 小時（避免重複打 API）
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from etfinfo_fetcher import fetch_etf_detail


# ============================================================
# 預設熱門被動 ETF 清單（手動維護台股主流被動 ETF）
# 欄位：code, name, category, description
# category 用來做側邊篩選
# ============================================================
DEFAULT_PASSIVE_ETFS = [
    # 市值型 / 大盤型
    ("0050", "元大台灣50", "市值", "追蹤臺灣50指數，權值股"),
    ("0052", "富邦台灣50", "市值", "追蹤臺灣50指數"),
    ("0051", "元大中型100", "市值", "追蹤臺灣中型100指數"),
    ("006208", "富邦台50", "市值", "追蹤臺灣50指數，費用較低"),
    ("00692", "富邦公司治理100", "市值", "公司治理100指數"),
    ("006201", "元大櫃買50", "市值", "上櫃50指數"),
    # 高股息
    ("0056", "元大高股息", "高股息", "追蹤臺灣高股息指數"),
    ("00878", "國泰永續高股息", "高股息", "MSCI ESG永續高股息精選30"),
    ("00919", "群益台灣精選高息", "高股息", "精選高息指數"),
    ("00929", "復華台灣科技優息", "高股息", "科技優息指數（高股息+科技）"),
    ("00900", "富邦特選高股息30", "高股息", "特選高股息30指數"),
    ("00701", "國泰低波動高股息30", "高股息", "低波動高股息30指數"),
    # 科技 / 半導體 / 主題
    ("0053", "元大電子", "科技", "電子類股指數"),
    ("00881", "國泰台灣5G+", "科技", "台灣5G通訊指數"),
    ("00892", "富邦台灣半導體", "科技", "台灣半導體指數"),
    ("00891", "中信台灣智慧50", "科技", "台灣智慧50指數"),
    ("00903", "富邦台灣5G", "科技", "台灣5G指數"),
    ("00757", "統一FANG+", "科技", "FANG+ 指數（美股科技）"),
    # ESG / 主題
    ("00850", "元大臺灣ESG永續", "ESG", "臺灣ESG永續指數"),
    # 海外股票
    ("00646", "元大S&P500", "海外", "S&P 500指數"),
    ("00662", "富邦NASDAQ", "海外", "NASDAQ-100指數"),
    # 債券型
    ("00679B", "元大美債20年", "債券", "美國20年期公債"),
    ("00687B", "國泰20年美債", "債券", "美國20年期公債"),
    ("00772B", "中信高評級公司債", "債券", "投資級美元公司債"),
    ("00865B", "國泰投資級公司債", "債券", "美元投資級公司債"),
    ("00937B", "復華20年美債", "債券", "美國20年期公債"),
]


# ============================================================
# Helper：抓一檔被動 ETF 的詳細資料（cache 1 小時）
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def _load_passive_etf_detail(etf_code: str) -> dict | None:
    """抓被動 ETF 詳細，回傳 None 表示不是被動 ETF 或抓不到"""
    try:
        d = fetch_etf_detail(etf_code)
    except Exception:
        return None
    info = d.get("info", {})
    mgmt = info.get("managementStyle")
    # 只收 managementStyle == "passive" 的（排除主動）
    if mgmt != "passive":
        return None
    return d


def _load_all_passive_overview() -> list[dict]:
    """抓預設清單的 overview 資料（info + latestMarket + returnStats）"""
    rows = []
    for code, name, category, desc in DEFAULT_PASSIVE_ETFS:
        d = _load_passive_etf_detail(code)
        if d is None:
            continue
        info = d.get("info", {})
        latest = d.get("latestMarket", {})
        ret = d.get("returnStats", {})
        rows.append({
            "code": code,
            "name": name,
            "category": category,
            "description": desc,
            "issuer": info.get("issuer"),
            "manager": info.get("manager"),
            "managementFee": info.get("managementFee"),
            "trackingIndex": info.get("trackingIndex"),
            "dividendFrequency": info.get("dividendFrequency"),
            "launchDate": info.get("launchDate"),
            "price": latest.get("price"),
            "nav": latest.get("nav"),
            "premium": latest.get("premium"),
            "aum": latest.get("aum"),
            "beneficiaries": latest.get("beneficiaries"),
            "return1Y": ret.get("return1Y"),
            "return3Y": ret.get("return3Y"),
            "return5Y": ret.get("return5Y"),
            "trailingYield": d.get("trailingYield"),
            "snapshotDate": d.get("holdings", {}).get("snapshotDate"),
        })
    return rows


# ============================================================
# Streamlit 頁面
# ============================================================
def render_passive_etf_page():
    st.header("📊 被動式 ETF 追蹤")
    st.caption(
        "台股主流被動 ETF 20+ 檔（市值型 / 高股息 / 科技 / 債券 / 海外）。"
        "資料來源：etfinfo.tw 公開 API（盤後更新）。"
        "紅色 = 溢價、綠色 = 折價（台股慣例，溢價代表買貴了、折價代表買便宜了）。"
    )

    # === 載入所有被動 ETF overview ===
    with st.spinner("載入被動 ETF 清單中…（從 etfinfo.tw 抓 25+ 檔）"):
        rows = _load_all_passive_overview()

    if not rows:
        st.error("❌ 抓不到任何被動 ETF 資料，請檢查 etfinfo.tw API")
        return

    df_all = pd.DataFrame(rows)

    # === 區塊 1: 被動 ETF 清單 ===
    st.subheader(f"📋 被動 ETF 清單（{len(df_all)} 檔）")

    # 篩選器
    c1, c2 = st.columns([1, 2])
    with c1:
        cat_filter = st.multiselect(
            "類型",
            options=sorted(df_all["category"].unique()),
            default=sorted(df_all["category"].unique()),
            key="passive_cat_filter",
        )
    with c2:
        sort_by = st.selectbox(
            "排序依據",
            options=["aum(億)", "1Y 報酬", "管理費", "折溢價", "受益人"],
            index=0,
            key="passive_sort",
        )

    df_show = df_all[df_all["category"].isin(cat_filter)].copy()

    # 排序欄位預處理
    if sort_by == "aum(億)":
        df_show["_sort"] = df_show["aum"].fillna(0) / 1e8
    elif sort_by == "1Y 報酬":
        df_show["_sort"] = pd.to_numeric(df_show["return1Y"], errors="coerce").fillna(-9999)
    elif sort_by == "管理費":
        df_show["_sort"] = df_show["managementFee"].fillna(99)
    elif sort_by == "折溢價":
        df_show["_sort"] = df_show["premium"].fillna(0).abs()
    else:
        df_show["_sort"] = df_show["beneficiaries"].fillna(0)

    df_show = df_show.sort_values("_sort", ascending=(sort_by in ["管理費"]))

    # 顯示表格
    display_cols = [
        "code", "name", "category", "issuer", "trackingIndex",
        "price", "nav", "premium", "aum", "return1Y",
        "managementFee", "beneficiaries", "trailingYield",
    ]
    df_disp = df_show[display_cols].copy()
    df_disp.columns = [
        "代號", "名稱", "類型", "發行商", "追蹤指數",
        "市價", "淨值", "折溢價%", "規模(億)", "1Y報酬%",
        "管理費%", "受益人", "殖利率%",
    ]

    # 格式化
    def fmt_aum(v):
        if pd.isna(v) or v is None: return "—"
        return f"{v/1e8:,.0f}"
    def fmt_premium(v):
        if pd.isna(v) or v is None: return "—"
        return f"{v:+.2f}%"
    def fmt_return(v):
        if pd.isna(v) or v is None: return "N/A"
        return f"{v:+.2f}%"
    def fmt_pct_small(v):
        if pd.isna(v) or v is None: return "—"
        return f"{v:.2f}%"
    def fmt_beneficiaries(v):
        if pd.isna(v) or v is None: return "—"
        return f"{v:,.0f}"

    for c, fmt in [
        ("市價", lambda v: "—" if pd.isna(v) else f"{v:.2f}"),
        ("淨值", lambda v: "—" if pd.isna(v) else f"{v:.2f}"),
        ("規模(億)", fmt_aum),
        ("折溢價%", fmt_premium),
        ("1Y報酬%", fmt_return),
        ("管理費%", fmt_pct_small),
        ("受益人", fmt_beneficiaries),
        ("殖利率%", fmt_pct_small),
    ]:
        df_disp[c] = df_disp[c].apply(fmt)

    def color_premium(v):
        if v == "—": return ""
        try:
            num = float(v.replace("%", "").replace("+", ""))
        except Exception:
            return ""
        if num > 0.5: return "color: #ef5350; font-weight: 600"
        if num < -0.5: return "color: #26a69a; font-weight: 600"
        return ""

    st.dataframe(
        df_disp.style.map(color_premium, subset=["折溢價%"]),
        width="stretch",
        hide_index=True,
    )

    st.divider()

    # === 區塊 2: 折溢價排行（套利機會） ===
    st.subheader("💰 折溢價排行（套利機會）")
    st.caption("溢價 > 0.5% 表示買貴了、折價 < -0.5% 表示買便宜了。")

    df_premium = df_all[["code", "name", "premium", "price", "nav"]].copy()
    df_premium["premium"] = pd.to_numeric(df_premium["premium"], errors="coerce")
    df_premium = df_premium.dropna(subset=["premium"])
    df_premium = df_premium.sort_values("premium", ascending=False)

    if len(df_premium) > 0:
        # 找出顯著折溢價的（abs > 0.5%）
        significant = df_premium[df_premium["premium"].abs() > 0.5]
        if len(significant) > 0:
            st.markdown(
                f"**{len(significant)} 檔有顯著折溢價**"
            )
            for _, r in significant.iterrows():
                emoji = "🔴 溢價" if r["premium"] > 0 else "🟢 折價"
                st.markdown(
                    f"- {emoji} **{r['code']} {r['name']}**："
                    f"{r['premium']:+.2f}%（市價 {r['price']:.2f} / 淨值 {r['nav']:.2f}）"
                )
        else:
            st.info("目前所有被動 ETF 折溢價都在 ±0.5% 內，無明顯套利機會")

        # 折溢價長條圖
        df_premium["color"] = df_premium["premium"].apply(
            lambda v: "#ef5350" if v > 0 else "#26a69a"
        )
        df_premium["label"] = df_premium["code"] + " " + df_premium["name"]

        fig = go.Figure(go.Bar(
            y=df_premium["label"],
            x=df_premium["premium"],
            orientation="h",
            marker_color=df_premium["color"],
            text=df_premium["premium"].apply(lambda v: f"{v:+.2f}%"),
            textposition="outside",
        ))
        fig.update_layout(
            template="plotly_dark",
            height=max(400, len(df_premium) * 25),
            margin=dict(l=10, r=10, t=30, b=10),
            yaxis=dict(autorange="reversed"),
            xaxis=dict(title="折溢價 %", zerolinecolor="#888", zerolinewidth=2),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")

    st.divider()

    # === 區塊 3: 個股查詢（被哪些被動 ETF 持有） ===
    st.subheader("🔍 個股查詢：被哪些被動 ETF 持有")
    st.caption("掃預設 25 檔被動 ETF 的完整持股，找出持有該個股的 ETF + 權重")

    c1, c2 = st.columns([3, 1])
    with c1:
        stock_query = st.text_input(
            "輸入股票代號",
            value="",
            max_chars=10,
            placeholder="例如 2330（台積電，會被 0050 / 006208 / 00692 / 0051 / 00850 等持有）",
            key="passive_stock_query",
        )
    with c2:
        st.write("")
        st.write("")
        lookup_btn = st.button("查詢", type="primary", width="stretch")

    if stock_query and (lookup_btn or len(stock_query) >= 4):
        _render_passive_stock_holders(stock_query.strip())

    st.divider()

    # === 區塊 4: ETF 查詢（完整持股） ===
    st.subheader("🔍 ETF 查詢：完整持股")

    c1, c2 = st.columns([3, 1])
    with c1:
        etf_options = [
            f"{code} {name}" for code, name, _, _ in DEFAULT_PASSIVE_ETFS
        ]
        etf_pick_label = st.selectbox(
            "選 ETF",
            options=etf_options,
            index=0,
            key="passive_etf_pick",
        )
    with c2:
        st.write("")
        st.write("")
        st.caption("從預設清單中選")

    etf_pick = etf_pick_label.split(" ")[0] if etf_pick_label else None
    if etf_pick:
        _render_passive_etf_detail(etf_pick)


# ============================================================
# Helper functions
# ============================================================
def _render_passive_stock_holders(stock_code: str):
    """個股查詢：掃預設清單找出該個股被哪些被動 ETF 持有"""
    with st.spinner(f"掃 25 檔被動 ETF 找 {stock_code}…"):
        holders = []
        for code, name, category, desc in DEFAULT_PASSIVE_ETFS:
            d = _load_passive_etf_detail(code)
            if d is None:
                continue
            stocks = d.get("holdings", {}).get("stocks", [])
            for stk in stocks:
                if stk.get("code") == stock_code:
                    holders.append({
                        "etfCode": code,
                        "etfName": name,
                        "category": category,
                        "weight": stk.get("weight", 0),
                        "shares": stk.get("shares", 0),
                        "trackingIndex": d.get("info", {}).get("trackingIndex"),
                    })
                    break

    st.markdown(f"### {stock_code} 被動式 ETF 持有查詢")

    if not holders:
        st.warning(f"{stock_code} 不在預設 25 檔被動 ETF 的持股內")
        return

    df = pd.DataFrame(holders).sort_values("weight", ascending=False)
    total_weight = df["weight"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("持有 ETF 數", len(df))
    c2.metric("權重合計", f"{total_weight:.2f}%")
    c3.metric("最高權重", f"{df['weight'].iloc[0]:.2f}%（{df['etfCode'].iloc[0]}）")

    # 顯示
    df_show = df[["etfCode", "etfName", "category", "weight", "shares", "trackingIndex"]].copy()
    df_show.columns = ["代號", "名稱", "類型", "權重%", "持股(股)", "追蹤指數"]

    def color_weight(v):
        if v >= 5: return "color: #ef5350; font-weight: 600"
        if v >= 1: return "color: #ffa726"
        return ""

    st.dataframe(
        df_show.style.format({
            "權重%": "{:.2f}",
            "持股(股)": "{:,.0f}",
        }).map(color_weight, subset=["權重%"]),
        width="stretch",
        hide_index=True,
    )


def _render_passive_etf_detail(etf_code: str):
    """顯示被動 ETF 詳細（info + 市值 + 持股 + 報酬）"""
    d = _load_passive_etf_detail(etf_code)
    if d is None:
        st.error(f"❌ {etf_code} 抓不到或不是被動 ETF")
        return

    info = d.get("info", {})
    latest = d.get("latestMarket", {})
    holdings = d.get("holdings", {})
    stocks = holdings.get("stocks", [])
    ret = d.get("returnStats", {})

    def fmt_pct(v, plus=True):
        if v is None: return "N/A"
        sign = "+" if plus and v > 0 else ""
        return f"{sign}{v:.2f}%"
    def fmt_num(v, dec=2):
        if v is None: return "N/A"
        return f"{v:,.{dec}f}"

    # Header
    st.markdown(f"### {info.get('code')} {info.get('name')}")
    st.caption(f"📌 追蹤指數：**{info.get('trackingIndex', '—')}**")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("發行商", info.get("issuer") or "—")
    c2.metric("經理人", info.get("manager") or "—")
    c3.metric("管理費", f"{info.get('managementFee'):.2f}%" if info.get("managementFee") is not None else "N/A")
    c4.metric("上市日", info.get("launchDate") or "—")

    c1, c2, c3, c4 = st.columns(4)
    if latest:
        c1.metric("最新淨值", fmt_num(latest.get("nav")))
        c2.metric("市價", fmt_num(latest.get("price")))
        c3.metric("折溢價", fmt_pct(latest.get("premium")))
        aum = latest.get("aum")
        c4.metric("規模(億)", f"{aum/1e8:,.0f}" if aum else "N/A")

    c1, c2, c3 = st.columns(3)
    c1.metric("1Y 報酬", fmt_pct(ret.get("return1Y")))
    c2.metric("3Y 報酬", fmt_pct(ret.get("return3Y")))
    c3.metric("殖利率", fmt_pct(d.get("trailingYield"), plus=False))

    st.caption(f"📅 持股 snapshot: {holdings.get('snapshotDate')} ｜ 資料源: {holdings.get('source')}")
    st.divider()

    # 完整持股
    st.markdown(f"#### 完整持股（{len(stocks)} 檔）")
    if not stocks:
        st.info("無持股資料")
        return

    df = pd.DataFrame(stocks)
    df["weight"] = df["weight"].astype(float)
    df["shares"] = df["shares"].astype(int)
    df = df.sort_values("weight", ascending=False).reset_index(drop=True)

    c1, c2 = st.columns(2)
    c1.metric("持股檔數", len(df))
    c2.metric("權重合計", f"{df['weight'].sum():.2f}%")

    df_show = df[["code", "name", "weight", "shares"]].copy()
    df_show.columns = ["代號", "名稱", "權重%", "持股(股)"]
    st.dataframe(
        df_show.style.format({"權重%": "{:.2f}", "持股(股)": "{:,.0f}"}),
        width="stretch", hide_index=True,
    )

    # 前 10 大圓餅圖
    st.divider()
    st.markdown("#### 前 10 大持股")
    top10 = df.head(10).copy()
    other_w = df["weight"].iloc[10:].sum()
    if other_w > 0:
        top10 = pd.concat([
            top10[["name", "weight"]],
            pd.DataFrame([{"name": "其他", "weight": other_w}]),
        ], ignore_index=True)
    else:
        top10 = top10[["name", "weight"]]

    fig = go.Figure(go.Pie(
        labels=top10["name"], values=top10["weight"],
        hole=0.4, marker=dict(line=dict(color="#0e1117", width=2)),
    ))
    fig.update_layout(
        template="plotly_dark", height=400,
        showlegend=True, margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, width="stretch")
