#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
etf_holdings_page.py — 主動式 ETF 持股追蹤（從 etfinfo.tw 公開 API）

頁面 4 區塊：
1. 今日概況 — totalEtfs / changedEtfs / 加減碼金額
2. 個股加碼/減碼排行 — flowRankings（117 個股，可篩選加/減/共識）
3. 共識訊號 — consensusSignals（多家 ETF 同進同出）
4. 產業資金流 — industryNetFlows

+ 兩個查詢工具：
- 個股查詢：輸入股票代號，看被哪些主動 ETF 持有
- ETF 查詢：輸入 ETF 代號，看完整持股

資料更新：每次 page rerun 自動抓（API 公開、不需登入、不耗 finlab quota）
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from etfinfo_fetcher import (
    fetch_active_summary,
    fetch_etf_detail,
    get_stock_etf_holders,
)


# ============================================================
# Streamlit 頁面
# ============================================================
def render_active_etf_page():
    st.header("📊 主動式 ETF 持股追蹤")
    st.caption(
        "資料來源：etfinfo.tw 公開 API（盤後 14:00 更新當日 snapshot）。"
        "紅色 = 加碼、綠色 = 減碼（台股慣例）。"
    )

    # 載入主頁 summary（streamlit 自動 cache 整個 function）
    @st.cache_data(ttl=1800, show_spinner="抓 etfinfo.tw 資料中…")
    def _load_summary():
        return fetch_active_summary()

    try:
        summary = _load_summary()
    except Exception as e:
        st.error(f"❌ 抓 etfinfo.tw 失敗：`{e}`")
        return

    hero = summary.get("hero", {})
    etfs = summary.get("etfs", [])
    flow_rankings = summary.get("flowRankings", [])
    consensus_signals = summary.get("consensusSignals", [])
    industry_flows = summary.get("industryNetFlows", [])
    sync_status = summary.get("syncStatus", {})
    anchor_date = summary.get("anchorDate", "—")

    # === 區塊 1: 今日概況 ===
    st.subheader(f"📈 今日概況（{anchor_date}）")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("主動 ETF 總數", hero.get("totalEtfs", 0))
    c2.metric("有變化 ETF", hero.get("changedEtfs", 0))
    c3.metric("淨加碼家數", hero.get("netBuyEtfs", 0))
    c4.metric("淨減碼家數", hero.get("netSellEtfs", 0))
    c5.metric(
        "總加碼金額",
        f"{hero.get('grossBuyAmount', 0)/1e8:+.1f} 億",
    )
    c6.metric(
        "總減碼金額",
        f"{hero.get('grossSellAmount', 0)/1e8:+.1f} 億",
    )

    # 同步狀態
    if sync_status:
        synced = sync_status.get("syncedEtfs", 0)
        stale = sync_status.get("staleEtfs", 0)
        total = sync_status.get("totalEtfs", 0)
        st.caption(
            f"📡 同步狀態：{synced}/{total} 已更新（{stale} 檔過期，"
            f"可能還沒拿到當日持股 snapshot）"
        )

    st.divider()

    # === 區塊 2: 個股加碼/減碼排行 ===
    st.subheader("🔥 個股加碼/減碼排行")
    st.caption(
        f"共 {len(flow_rankings)} 檔個股有變化，"
        f"點開看哪些主動 ETF 同步進場 / 退場。"
    )

    if not flow_rankings:
        st.info("無個股加碼/減碼資料")
    else:
        # 篩選器
        col1, col2, col3 = st.columns(3)
        with col1:
            direction = st.radio(
                "方向",
                options=["全部", "加碼", "減碼"],
                index=0,
                horizontal=True,
                key="flow_direction",
            )
        with col2:
            top_n = st.slider("顯示前 N 名", 5, 117, 30, 5)
        with col3:
            min_etfs = st.slider(
                "最少 ETF 家數",
                1, 10, 1,
                help="只顯示被 N 家以上 ETF 同時加減碼的個股（過濾單一動作）",
            )

        # 排序 + 篩選
        df_flow = pd.DataFrame(flow_rankings)
        df_flow["netAmountYi"] = df_flow["netAmount"] / 1e8  # 億
        df_flow["absAmount"] = df_flow["netAmount"].abs()

        if direction == "加碼":
            df_show = df_flow[df_flow["netAmount"] > 0].copy()
        elif direction == "減碼":
            df_show = df_flow[df_flow["netAmount"] < 0].copy()
        else:
            df_show = df_flow.copy()

        df_show = df_show[df_show["issuerCount"] >= min_etfs]
        df_show = df_show.sort_values("absAmount", ascending=False).head(top_n)

        # 顯示
        if len(df_show) == 0:
            st.info("沒有符合條件的個股")
        else:
            show_cols = ["stockCode", "stockName", "industry", "netAmountYi", "netShares", "issuerCount"]
            df_disp = df_show[show_cols].copy()
            df_disp.columns = ["代號", "名稱", "產業", "淨額(億)", "淨張數", "ETF家數"]
            # 顏色：加碼紅、減碼綠
            def color_amount(v):
                color = "#ef5350" if v > 0 else "#26a69a" if v < 0 else "#888"
                return f"color: {color}; font-weight: 600"

            st.dataframe(
                df_disp.style.format({
                    "淨額(億)": "{:+.2f}",
                    "淨張數": "{:+,.0f}",
                    "ETF家數": "{:d}",
                }).map(color_amount, subset=["淨額(億)"]),
                width="stretch",
                hide_index=True,
            )

            # 個股展開
            with st.expander("💡 點開任一個股看是哪幾家 ETF"):
                stock_choice = st.selectbox(
                    "選個股",
                    options=df_show["stockCode"].tolist(),
                    format_func=lambda c: f"{c} {df_show[df_show['stockCode']==c]['stockName'].iloc[0]}",
                    key="flow_stock_pick",
                )
                if stock_choice:
                    _render_stock_holders(stock_choice, df_show)

    st.divider()

    # === 區塊 3: 共識訊號 ===
    st.subheader("📡 共識訊號（多家 ETF 同步動作）")
    st.caption(
        "buyCount / sellCount 是「該個股今天被幾家主動 ETF 加碼 / 減碼」。"
        "netSignal = buy - sell，正值偏多、負值偏空。"
    )

    if not consensus_signals:
        st.info("無共識訊號")
    else:
        df_cs = pd.DataFrame(consensus_signals)
        df_cs["absSignal"] = df_cs["netSignal"].abs()
        df_cs = df_cs.sort_values("absSignal", ascending=False).head(20)

        # 用條狀圖
        fig = go.Figure()
        df_cs["color"] = df_cs["netSignal"].apply(
            lambda x: "#ef5350" if x > 0 else "#26a69a"
        )
        df_cs["label"] = df_cs["stockCode"] + " " + df_cs["stockName"]

        fig.add_trace(go.Bar(
            y=df_cs["label"],
            x=df_cs["netSignal"],
            orientation="h",
            marker_color=df_cs["color"],
            text=df_cs["netSignal"],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>netSignal: %{x}<br>買:%{customdata[0]} / 賣:%{customdata[1]}<extra></extra>",
            customdata=df_cs[["buyCount", "sellCount"]].values,
        ))

        fig.update_layout(
            template="plotly_dark",
            height=max(400, len(df_cs) * 25),
            margin=dict(l=10, r=10, t=30, b=10),
            yaxis=dict(autorange="reversed"),
            xaxis=dict(title="淨訊號 (買-賣)", zerolinecolor="#888", zerolinewidth=2),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")

        # 完整表
        with st.expander("📋 完整共識表（26 個）"):
            df_show = df_cs[["stockCode", "stockName", "buyCount", "sellCount", "netSignal", "isStrong"]].copy()
            df_show.columns = ["代號", "名稱", "買進家數", "賣出家數", "淨訊號", "強訊號"]
            st.dataframe(df_show, width="stretch", hide_index=True)

    st.divider()

    # === 區塊 4: 產業資金流 ===
    st.subheader("🏭 產業資金流")
    st.caption("當日主動式 ETF 對各產業的淨加減碼金額。")

    if not industry_flows:
        st.info("無產業資金流")
    else:
        df_ind = pd.DataFrame(industry_flows)
        df_ind = df_ind.sort_values("netAmount", ascending=True)  # 由小到大（最大減碼在頂）
        df_ind["netAmountYi"] = df_ind["netAmount"] / 1e8
        df_ind["color"] = df_ind["netAmount"].apply(
            lambda x: "#ef5350" if x > 0 else "#26a69a"
        )

        fig = go.Figure(go.Bar(
            y=df_ind["industry"],
            x=df_ind["netAmountYi"],
            orientation="h",
            marker_color=df_ind["color"],
            text=df_ind["netAmountYi"].apply(lambda v: f"{v:+.1f}"),
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>淨額: %{x:+.1f} 億<br>個股數: %{customdata}<extra></extra>",
            customdata=df_ind["stockCount"],
        ))
        fig.update_layout(
            template="plotly_dark",
            height=max(400, len(df_ind) * 28),
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis=dict(title="淨額 (億)", zerolinecolor="#888", zerolinewidth=2),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")

    st.divider()

    # === 區塊 5: 個股查詢（看被哪些主動 ETF 持有） ===
    st.subheader("🔍 個股查詢：看被哪些主動 ETF 持有")

    @st.cache_data(ttl=3600, show_spinner="抓個股資料中…")
    def _load_etfs():
        # 拿所有 ETF 簡表
        return [
            {
                "code": e["code"],
                "name": e["name"],
                "issuer": e.get("issuer"),
                "dividendFrequency": e.get("dividendFrequency"),
                "changeCount": e.get("changeCount", 0),
                "netAmount": e.get("netAmount", 0),
            }
            for e in etfs
        ]

    etfs_slim = _load_etfs()
    df_etfs = pd.DataFrame(etfs_slim)
    df_etfs = df_etfs.sort_values("changeCount", ascending=False)

    c1, c2 = st.columns([3, 1])
    with c1:
        stock_query = st.text_input(
            "輸入股票代號（4 位數字）",
            value="",
            max_chars=10,
            placeholder="例如 2330（台積電） / 2303（聯電）",
            key="stock_query",
        )
    with c2:
        st.write("")
        st.write("")
        lookup_btn = st.button("查詢", type="primary", width="stretch")

    if stock_query and (lookup_btn or len(stock_query) >= 4):
        _render_stock_detail(stock_query.strip(), flow_rankings)

    st.divider()

    # === 區塊 6: ETF 查詢（看完整持股） ===
    st.subheader("🔍 ETF 查詢：看完整持股")
    c1, c2 = st.columns([3, 1])
    with c1:
        etf_options = [f"{e['code']} {e['name']}" for e in etfs_slim]
        etf_pick_label = st.selectbox(
            "選 ETF",
            options=etf_options,
            index=0,
            key="etf_pick",
        )
    with c2:
        st.write("")
        st.write("")
        etf_lookup_btn = st.button("查持股", type="primary", width="stretch")

    etf_pick = etf_pick_label.split(" ")[0] if etf_pick_label else None
    if etf_pick and (etf_lookup_btn or etf_pick):
        _render_etf_detail(etf_pick)


# ============================================================
# 區塊 helper
# ============================================================
def _render_stock_holders(stock_code: str, df_show: pd.DataFrame):
    """展開顯示單一個股被哪些 ETF 持有 / 動作"""
    row = df_show[df_show["stockCode"] == stock_code].iloc[0]
    etf_details = row.get("etfDetails", [])
    if not etf_details:
        st.info(f"{stock_code} 沒有 ETF 異動明細")
        return

    # 從 etfs 拿名稱
    @st.cache_data(ttl=3600)
    def _name_map():
        s = fetch_active_summary()
        return {e["code"]: e["name"] for e in s.get("etfs", [])}

    name_map = _name_map()

    df = pd.DataFrame(etf_details)
    df["name"] = df["etfCode"].map(name_map).fillna(df["etfCode"])
    df["amountMil"] = df["amount"] / 1e6
    df["color"] = df["type"].apply(
        lambda t: {"added": "#ef5350", "decreased": "#26a69a",
                   "removed": "#888", "increased": "#ef5350"}.get(t, "#888")
    )
    type_emoji = {
        "added": "🆕 新增", "removed": "❌ 移除",
        "increased": "📈 加碼", "decreased": "📉 減碼",
    }
    df["動作"] = df["type"].map(type_emoji).fillna(df["type"])

    st.markdown(f"**{row['stockCode']} {row['stockName']}** — 被 **{len(df)}** 家主動 ETF 動作：")
    cols = ["etfCode", "name", "動作", "sharesDelta", "amountMil"]
    df_show2 = df[cols].rename(columns={
        "etfCode": "ETF", "name": "名稱",
        "sharesDelta": "張數變化", "amountMil": "金額(百萬)",
    })

    def color_amount(v):
        return "color: #ef5350; font-weight: 600" if v > 0 else "color: #26a69a; font-weight: 600" if v < 0 else ""

    st.dataframe(
        df_show2.style.format({
            "張數變化": "{:+,.0f}",
            "金額(百萬)": "{:+,.1f}",
        }).map(color_amount, subset=["金額(百萬)"]),
        width="stretch",
        hide_index=True,
    )


def _render_stock_detail(stock_code: str, flow_rankings: list):
    """個股查詢：找該個股被哪些 ETF 持有 + 今日動作"""
    # 從 flowRankings 找（只找有變化的）
    holders_in_summary = get_stock_etf_holders(stock_code)

    # 同步查 39 檔 ETF 完整持股（找「被持有但今天沒動作」的）
    @st.cache_data(ttl=1800, show_spinner=f"掃 {stock_code} 在 39 檔主動 ETF 的完整持股…")
    def _scan_all_etf_holdings(stock_code_inner: str) -> dict:
        """回傳 {etf_code: shares} 給 stock_code（被持有的所有 ETF，不分有無變化）"""
        s = fetch_active_summary()
        result = {}
        for etf in s.get("etfs", []):
            try:
                detail = fetch_etf_detail(etf["code"])
                stocks = detail.get("holdings", {}).get("stocks", [])
                for stk in stocks:
                    if stk.get("code") == stock_code_inner:
                        result[etf["code"]] = {
                            "shares": stk.get("shares", 0),
                            "weight": stk.get("weight", 0),
                            "etf_name": etf.get("name"),
                        }
                        break
            except Exception:
                continue
        return result

    all_holdings = _scan_all_etf_holdings(stock_code)

    st.markdown(f"### {stock_code} 持股查詢結果")

    if not all_holdings and not holders_in_summary:
        st.warning(f"沒有任何主動式 ETF 持有 {stock_code}")
        return

    # 合併：有變化 + 靜止持有
    df_holders = pd.DataFrame([
        {
            "etfCode": k,
            "etfName": v["etfName"],
            "shares": v["shares"],
            "weight": v["weight"],
        }
        for k, v in all_holdings.items()
    ])

    # 對應到 flowRankings 的 etfDetails
    if holders_in_summary:
        df_changes = pd.DataFrame(holders_in_summary)
        df_changes = df_changes.rename(columns={"etfCode": "etfCode"})
        df_changes["sharesDelta"] = df_changes["sharesDelta"].fillna(0)
        df_changes["amountDeltaMil"] = df_changes["amount"].fillna(0) / 1e6
        df_changes["action"] = df_changes["type"].map({
            "added": "🆕 新增", "removed": "❌ 移除",
            "increased": "📈 加碼", "decreased": "📉 減碼",
        }).fillna(df_changes["type"])
    else:
        df_changes = pd.DataFrame(columns=["etfCode", "sharesDelta", "amount", "type", "action"])

    # 合併：left join
    if not df_holders.empty:
        df_merged = df_holders.merge(
            df_changes[["etfCode", "sharesDelta", "amount", "type", "action"]],
            on="etfCode", how="left",
        )
    else:
        df_merged = pd.DataFrame()

    df_merged["sharesDelta"] = df_merged["sharesDelta"].fillna(0)
    df_merged["amount"] = df_merged["amount"].fillna(0)
    df_merged["action"] = df_merged["action"].fillna("— 今日無動作")
    df_merged = df_merged.sort_values("weight", ascending=False)

    # Summary
    n_total = len(df_merged)
    n_changed = (df_merged["action"] != "— 今日無動作").sum()
    total_weight = df_merged["weight"].sum()
    st.markdown(
        f"- 被 **{n_total}** 家主動式 ETF 持有，合計權重 **{total_weight:.1f}%**"
    )
    if n_changed > 0:
        st.markdown(f- "今日 **{n_changed}** 家有動作（加碼 / 減碼 / 新增 / 移除）")

    # 顯示
    cols = ["etfCode", "etfName", "weight", "shares", "sharesDelta", "amount", "action"]
    df_show = df_merged[cols].copy()
    df_show.columns = ["ETF", "名稱", "權重%", "持股(股)", "今日張數變化", "今日金額(元)", "動作"]

    def color_amount(v):
        if v > 0: return "color: #ef5350; font-weight: 600"
        if v < 0: return "color: #26a69a; font-weight: 600"
        return ""

    st.dataframe(
        df_show.style.format({
            "權重%": "{:.2f}",
            "持股(股)": "{:,.0f}",
            "今日張數變化": "{:+,.0f}",
            "今日金額(元)": "{:+,.0f}",
        }).map(color_amount, subset=["今日金額(元)"]),
        width="stretch",
        hide_index=True,
    )


def _render_etf_detail(etf_code: str):
    """ETF 查詢：顯示完整持股 + 今日異動"""
    @st.cache_data(ttl=1800, show_spinner=f"抓 {etf_code} 持股中…")
    def _load_etf(code):
        return fetch_etf_detail(code)

    try:
        detail = _load_etf(etf_code)
    except Exception as e:
        st.error(f"❌ 抓 {etf_code} 失敗：`{e}`")
        return

    info = detail.get("info", {})
    latest = detail.get("latestMarket", {})
    holdings = detail.get("holdings", {})
    stocks = holdings.get("stocks", [])
    return_stats = detail.get("returnStats", {})

    # Header
    st.markdown(f"### {info.get('code')} {info.get('name')}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("發行商", info.get("issuer", "—"))
    c2.metric("經理人", info.get("manager", "—"))
    c3.metric("管理費", f"{info.get('managementFee', 0):.2f}%")
    c4.metric("上市日", info.get("launchDate", "—"))

    c1, c2, c3, c4 = st.columns(4)
    if latest:
        c1.metric("最新淨值", f"{latest.get('nav', 0):.2f}")
        c2.metric("市價", f"{latest.get('price', 0):.2f}")
        c3.metric("折溢價", f"{latest.get('premium', 0):+.2f}%")
        c4.metric("規模(億)", f"{latest.get('aum', 0)/1e8:.1f}")
    c1, c2, c3 = st.columns(3)
    c1.metric("1Y 報酬", f"{return_stats.get('return1Y', 0):+.2f}%")
    c2.metric("3Y 報酬", f"{return_stats.get('return3Y', 0):+.2f}%")
    c3.metric("殖利率", f"{detail.get('trailingYield', 0):.2f}%")

    st.caption(f"📅 持股 snapshot: {holdings.get('snapshotDate')} ｜ 資料源: {holdings.get('source')}")

    st.divider()

    # 完整持股表
    st.markdown("#### 完整持股")
    if not stocks:
        st.info("無持股資料")
        return

    df = pd.DataFrame(stocks)
    df["weight"] = df["weight"].astype(float)
    df["shares"] = df["shares"].astype(int)
    df = df.sort_values("weight", ascending=False)
    df = df.reset_index(drop=True)

    st.metric("持股檔數", len(df))
    st.metric("權重合計", f"{df['weight'].sum():.2f}%")

    df_show = df[["code", "name", "weight", "shares"]].copy()
    df_show.columns = ["代號", "名稱", "權重%", "持股(股)"]
    st.dataframe(
        df_show.style.format({"權重%": "{:.2f}", "持股(股)": "{:,.0f}"}),
        width="stretch", hide_index=True,
    )

    # 權重圓餅圖
    if len(df) > 0:
        st.divider()
        st.markdown("#### 前 10 大持股")
        top10 = df.head(10).copy()
        other = pd.DataFrame([{
            "name": "其他", "weight": df["weight"].iloc[10:].sum(),
        }])
        if other["weight"].iloc[0] > 0:
            top10 = pd.concat([top10[["name", "weight"]], other], ignore_index=True)
        else:
            top10 = top10[["name", "weight"]]

        fig = go.Figure(go.Pie(
            labels=top10["name"], values=top10["weight"],
            hole=0.4, marker=dict(line=dict(color="#0e1117", width=2)),
        ))
        fig.update_layout(
            template="plotly_dark",
            height=400,
            showlegend=True,
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig, width="stretch")
