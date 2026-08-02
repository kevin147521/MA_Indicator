#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
app.py — 台股分析平台（Streamlit）

啟動方式：
    /opt/anaconda3/envs/finlab3/bin/streamlit run app.py

功能頁面：
1. 「📈 均線預測」：選個股，看 K 線 + 4 條均線，預測下個交易日收盤後的均線落點
2. 「🗺️ 市值漲跌地圖」：全台股市值 × 漲跌幅 treemap，階層：市場 → 產業 → 個股
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

# 把同目錄加進 sys.path，避免 module not found
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ma_engine import (
    DEFAULT_MA_WINDOWS,
    DEFAULT_FLAT_THRESHOLD_PCT,
    predict_all_ma,
    build_chart_data,
    find_break_even_close,
)
from data_fetcher import fetch_ohlcv, get_stock_name, get_all_securities, ensure_finlab_login
from treemap_page import (
    plot_treemap,
    render_summary_stats,
)


# ============================================================
# 全市場清單（cache 1 小時，避免每個互動都重抓）
# ============================================================
@st.cache_data(ttl=3600, show_spinner="載入全市場清單中…")
def _load_securities() -> pd.DataFrame:
    return get_all_securities()


# 收藏清單存檔路徑（Finder 雙擊跑的場景也能寫）
FAVORITES_PATH = Path.home() / ".openclaw" / "ma_indicator_favorites.json"


def _load_favorites() -> list[str]:
    if FAVORITES_PATH.exists():
        try:
            return json.loads(FAVORITES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_favorites(favs: list[str]):
    FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_PATH.write_text(json.dumps(favs, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# Streamlit 設定
# ============================================================
st.set_page_config(
    page_title="台股均線預測平台",
    page_icon="📈",
    layout="wide",
)

# 統一 finlab login（雲端用 st.secrets、本地用 credentials.json）
try:
    ensure_finlab_login()
except Exception as _e:
    st.error(f"finlab login 失敗：`{_e}`")

st.title("📈 台股分析平台")
st.caption("用 FinLab 抓台股資料做均線預測 + 市值漲跌幅地圖分析。")

# ============================================================
# 頁面選擇（sidebar 最上層）
# ============================================================
with st.sidebar:
    st.header("📑 頁面")
    page = st.radio(
        "選擇功能",
        ["📈 均線預測", "🗺️ 市值漲跌地圖", "🧪 跌破站回回測", "💰 融資維持率", "🔄 資料更新"],
        label_visibility="collapsed",
        key="page_selector",
    )
    st.divider()


# ============================================================
# Treemap 頁面（早 return，不跑均線邏輯）
# ============================================================
def render_treemap_page():
    st.header("🗺️ 台股市值 × 漲跌幅地圖")
    st.caption("用 treemap 看台股全市場：方塊大小 = 市值/成交，顏色 = 漲跌幅。")

    # 控制面板
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        # 預設 end = 最後一個交易日
        from finlab import data as _data
        _close = _data.get("price:收盤價")
        default_end = _close.index[-1].strftime("%Y-%m-%d")
        # 往前推一個交易日算單日漲跌
        prev_idx = _close.index.get_indexer([pd.Timestamp(default_end)], method="ffill")[0]
        default_start = _close.index[max(prev_idx - 1, 0)].strftime("%Y-%m-%d")
        start_date = st.date_input("開始日期", value=pd.Timestamp(default_start))
        end_date = st.date_input("結束日期", value=pd.Timestamp(default_end))
    with col2:
        area_ind = st.selectbox(
            "方塊大小",
            options=["market_value", "turnover", "turnover_ratio"],
            format_func=lambda x: {
                "market_value": "市值（億）",
                "turnover": "成交金額（億）",
                "turnover_ratio": "成交佔比 %",
            }[x],
        )
    with col3:
        item = st.selectbox(
            "方塊顏色",
            options=["return_ratio", "turnover_ratio"],
            format_func=lambda x: {
                "return_ratio": "漲跌幅 %",
                "turnover_ratio": "成交佔比 %",
            }[x],
        )
        clip = st.slider(
            "漲跌 clip 範圍 (%)",
            min_value=3.0, max_value=20.0, value=10.0, step=1.0,
            help="把極端值 clip 在 ±這個值，避免色階被壓縮",
        )
    with col4:
        exclude_penny = st.checkbox(
            "排除低價股 (<10元)",
            value=True,
            help="低價股常會讓 treemap 被拉爆，預設排除",
        )
        color_scales = st.selectbox(
            "色階",
            options=["RdYlGn_r", "RdBu_r", "RdGy_r", "Viridis", "Cividis", "Temps"],
            index=0,
            help="預設 RdYlGn_r：紅=漲、綠=跌（台股慣例）；其他選項也有 _r 反轉版",
        )

    # 轉成字串
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # 抓資料 + 畫圖
    try:
        with st.spinner(f"抓 {start_str} ~ {end_str} 資料中…"):
            df, fig = plot_treemap(
                start=start_str,
                end=end_str,
                area_ind=area_ind,
                item=item,
                clip=clip,
                color_scales=color_scales,
                exclude_etf=True,  # basic_info 沒 ETF
                exclude_penny=exclude_penny,
            )
    except Exception as e:
        st.error(f"抓資料失敗：`{e}`")
        return

    # 統計
    stats = render_summary_stats(df)
    st.markdown("#### 📊 市場概況")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("上漲家數", stats["上漲"], delta=f"{stats['上漲']-stats['下跌']:+d} vs 下跌")
    m2.metric("下跌家數", stats["下跌"])
    m3.metric("持平家數", stats["持平"])
    m4.metric("總家數", stats["家數"])
    m5.metric("平均漲跌%", f"{stats['平均漲跌%']:+.2f}%")
    m6.metric("總市值", f"{stats['總市值(億)']:,.0f} 億")

    st.divider()

    # 圖
    st.plotly_chart(fig, width="stretch")

    st.divider()

    # Top 漲 / Top 跌表
    st.markdown("#### 🏆 排行")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**漲幅前 20**")
        top_up = df.nlargest(20, "return_ratio")[["stock_id_name", "close", "return_ratio", "market_value"]]
        st.dataframe(top_up, hide_index=True, width="stretch")
    with c2:
        st.markdown("**跌幅前 20**")
        top_dn = df.nsmallest(20, "return_ratio")[["stock_id_name", "close", "return_ratio", "market_value"]]
        st.dataframe(top_dn, hide_index=True, width="stretch")

    st.caption(
        f"資料時間：{start_str} ~ {end_str} ｜ "
        f"方塊大小 = {area_ind} ｜ 顏色 = {item} ｜ "
        f"排除 ETF 與低價股（<10元）"
    )


# 路由
if page == "🗺️ 市值漲跌地圖":
    render_treemap_page()
    st.stop()


# ============================================================
# 跌破站回回測頁面
# ============================================================
def render_breakout_backtest_page():
    from ma_breakout_backtest import (
        run_backtest, global_summary, fetch_close_df,
    )
    import plotly.express as px

    st.header("🧪 均線跌破 → 站回新高 回測")
    st.caption(
        "對上市股票（sii）跑「跌破均線後站回均線 + 突破前 20 日高點」的回測，"
        "看平均要幾天才會發生。"
    )

    # === 控制面板 ===
    col1, col2, col3 = st.columns(3)
    with col1:
        start_year = st.selectbox(
            "回測起始年",
            options=[2015, 2018, 2020, 2022, "全部"],
            index=2,
        )
        lookback_high = st.slider(
            "站回時要突破的前 N 日高點",
            min_value=10, max_value=60, value=20, step=5,
            help="站回均線那天，收盤也要 > 跌破前 N 日最高收盤才算數",
        )
    with col2:
        min_break_days = st.slider(
            "跌破定義（連續跌破幾天）",
            min_value=1, max_value=5, value=2, step=1,
            help="連續 N 天收盤 < 均線才算「真跌破」，過濾一日假跌破",
        )
        max_recover_days = st.slider(
            "最多追蹤天數",
            min_value=60, max_value=504, value=252, step=21,
            help="跌破後最多看幾天，超過就視為「未站回」",
        )
    with col3:
        ma_choice = st.multiselect(
            "要回測的均線",
            options=[5, 10, 20, 60],
            default=[5, 10, 20, 60],
        )
        run_btn = st.button("🚀 開始回測", type="primary", width="stretch")

    if not ma_choice:
        st.warning("請至少選一條均線")
        return

    # === 抓資料 + 跑回測 ===
    @st.cache_data(ttl=3600 * 6, show_spinner="抓上市收盤價中…")
    def _fetch_sii_close(start_year_opt):
        from finlab import data as _data
        basic = _data.get("company_basic_info")
        basic["stock_id"] = basic["stock_id"].astype(str)
        sii_ids = basic[basic["市場別"] == "sii"]["stock_id"].tolist()
        close_wide = _data.get("price:收盤價")
        available = [s for s in sii_ids if s in close_wide.columns]
        if start_year_opt == "全部":
            return close_wide[available].copy()
        return close_wide[available].loc[f"{start_year_opt}-01-01":].copy()

    if run_btn:
        # 清掉舊的結果 cache
        st.session_state.pop("backtest_events", None)

    if "backtest_events" not in st.session_state:
        try:
            with st.spinner("抓資料中…"):
                df = _fetch_sii_close(start_year)
            st.info(f"資料 shape: {df.shape[0]} 天 × {df.shape[1]} 檔")

            progress_bar = st.progress(0.0, text="回測進度")
            status = st.empty()

            def progress_cb(i, total):
                progress_bar.progress(min(i / total, 1.0), text=f"回測進度 {i}/{total} ({100*i/total:.0f}%)")

            events_df = run_backtest(
                df,
                ma_windows=ma_choice,
                lookback_high=lookback_high,
                max_recover_days=max_recover_days,
                min_break_days=min_break_days,
                progress_callback=progress_cb,
            )
            progress_bar.empty()
            status.empty()

            st.session_state["backtest_events"] = events_df
            st.session_state["backtest_globals"] = global_summary(events_df)
        except Exception as e:
            st.error(f"回測失敗：`{e}`")
            return

    events_df = st.session_state["backtest_events"]
    g = st.session_state["backtest_globals"]

    if len(events_df) == 0:
        st.warning("沒抓到任何事件，請調整參數")
        return

    # === 全市場彙總卡 ===
    st.markdown("#### 📈 全市場彙總（每條均線）")
    m_cols = st.columns(len(g))
    for i, row in g.iterrows():
        with m_cols[i]:
            st.metric(
                f"MA{row['ma_window']}",
                f"{row['median_recover_days']:.0f} 天",
                delta=f"命中率 {row['hit_rate']*100:.1f}%",
                help=(
                    f"中位數站回天數 {row['median_recover_days']} 天\n"
                    f"平均 {row['avg_recover_days']:.1f} 天\n"
                    f"25-75 分位: {row['p25_recover_days']}-{row['p75_recover_days']} 天\n"
                    f"事件數: {row['total_events']:,}\n"
                    f"站回: {row['recover_events']:,} / 未站回: {row['no_recover_events']:,}"
                ),
            )

    st.dataframe(g, hide_index=True, width="stretch")

    st.divider()

    # === 圖表：站回天數分佈 ===
    st.markdown("#### 📊 站回天數分佈")
    recovered = events_df.dropna(subset=["recover_days"]).copy()

    if len(recovered) == 0:
        st.warning("沒有任何站回事件")
    else:
        # histogram by MA
        fig_hist = px.histogram(
            recovered,
            x="recover_days",
            color="ma_window",
            nbins=50,
            barmode="overlay",
            opacity=0.6,
            title="站回天數分佈（按均線分組）",
            labels={"recover_days": "站回天數", "ma_window": "MA"},
        )
        fig_hist.update_layout(height=400)
        st.plotly_chart(fig_hist, width="stretch")

        # box plot
        fig_box = px.box(
            recovered,
            x="ma_window",
            y="recover_days",
            points=False,
            title="站回天數盒鬚圖（按均線）",
            labels={"ma_window": "均線", "recover_days": "站回天數"},
        )
        fig_box.update_layout(height=400)
        st.plotly_chart(fig_box, width="stretch")

    st.divider()

    # === 個別股票排行 ===
    st.markdown("#### 🏆 個別股票排行")
    c1, c2 = st.columns(2)
    with c1:
        ma_pick = st.selectbox("選均線", options=ma_choice, index=0)
    with c2:
        min_events = st.slider(
            "最少事件數",
            min_value=5, max_value=100, value=20, step=5,
            help="事件太少的不列入排行（避免單一事件主導）",
        )

    sub = events_df[events_df["ma_window"] == ma_pick].copy()
    # 個別股票彙總
    grp = sub.groupby("stock_id").agg(
        total_events=("recover_days", "size"),
        recover_events=("recover_days", "count"),
        median_recover_days=("recover_days", "median"),
        mean_recover_days=("recover_days", "mean"),
    ).reset_index()
    grp["hit_rate"] = grp["recover_events"] / grp["total_events"]
    grp = grp[grp["total_events"] >= min_events]
    grp = grp.sort_values("median_recover_days")

    # 補上中文名稱
    from data_fetcher import get_all_securities
    sec = get_all_securities()
    sec["stock_id_short"] = sec["stock_id"].astype(str)
    name_map = dict(zip(sec["stock_id_short"], sec["name"]))
    grp["name"] = grp["stock_id"].map(name_map).fillna(grp["stock_id"])

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**站回最快前 20**（中位數最少天）")
        fastest = grp.head(20)[["stock_id", "name", "total_events", "median_recover_days", "hit_rate"]]
        fastest.columns = ["代號", "名稱", "事件數", "中位天數", "命中率"]
        st.dataframe(fastest, hide_index=True, width="stretch")
    with c4:
        st.markdown("**站回最慢前 20**（中位數最多天）")
        slowest = grp.tail(20).sort_values("median_recover_days", ascending=False)[
            ["stock_id", "name", "total_events", "median_recover_days", "hit_rate"]
        ]
        slowest.columns = ["代號", "名稱", "事件數", "中位天數", "命中率"]
        st.dataframe(slowest, hide_index=True, width="stretch")

    st.divider()

    # === 事件明細表（下載用） ===
    with st.expander("📋 完整事件明細（可下載 CSV）", expanded=False):
        st.caption(f"共 {len(events_df):,} 筆事件")
        show_cols = ["stock_id", "ma_window", "break_date", "break_price", "ma_at_break",
                     "recover_date", "recover_days", "recover_price", "high_at_break"]
        st.dataframe(events_df[show_cols].head(500), hide_index=True, width="stretch")

        csv = events_df[show_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ 下載完整 CSV",
            data=csv,
            file_name="ma_breakout_events.csv",
            mime="text/csv",
        )


if page == "🧪 跌破站回回測":
    render_breakout_backtest_page()
    st.stop()


# ============================================================
# 融資維持率頁面
# ============================================================
def render_margin_page():
    from margin_page import plot_margin_trend, render_margin_summary
    import pandas as pd

    st.header("💰 台股大盤融資維持率")
    st.caption(
        "融資維持率 = 融資餘額市值 ÷ 融資總餘額。130% 是追繳 / 斷頭的常見警戒線。"
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        from finlab import data as _data
        _balance = _data.get("margin_balance:融資券總餘額")
        default_end = _balance.index[-1].strftime("%Y-%m-%d")
        end_date = st.date_input("結束日期", value=pd.Timestamp(default_end))
        default_start = (pd.Timestamp(default_end) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
        start_date = st.date_input("開始日期", value=pd.Timestamp(default_start))
    with col2:
        ma_window = st.slider("融資維持率均線", min_value=3, max_value=30, value=10, step=1)
    with col3:
        st.write("")
        st.write("")

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    try:
        with st.spinner(f"抓 {start_str} ~ {end_str} 融資資料中…"):
            summary = render_margin_summary(start=start_str, end=end_str)
            fig = plot_margin_trend(
                start=start_str, end=end_str,
                ma_window=ma_window, width=1500, height=800,
            )
    except Exception as e:
        st.error(f"抓資料失敗：`{e}`")
        return

    if not summary:
        st.warning("沒有資料，請檢查日期範圍")
        return

    st.markdown("#### 📊 最新概況")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("最新維持率", f"{summary['最新維持率']:.2f}%")
    c2.metric(
        "距離 130% 警戒",
        f"{summary['距離130%']:+.2f}%",
        delta=f"距警戒 {summary['距離130%']:.1f}%",
        delta_color="normal" if summary["距離130%"] > 0 else "inverse",
    )
    c3.metric("最新日期", summary["最新日期"])
    c4.metric("總融資餘額", f"{summary['總融資餘額(億)']:,.0f} 億")
    c5.metric(
        "上市買賣超",
        f"{summary['上市買賣超(億)']:+.0f} 億",
        delta=f"{summary['上市買賣超(億)']:+.0f}",
        delta_color="inverse" if summary["上市買賣超(億)"] > 0 else "normal",
    )
    c6.metric(
        "上櫃買賣超",
        f"{summary['上櫃買賣超(億)']:+.0f} 億",
        delta=f"{summary['上櫃買賣超(億)']:+.0f}",
        delta_color="inverse" if summary["上櫃買賣超(億)"] > 0 else "normal",
    )

    st.caption("💡 買賣超正值（紅）= 散戶加碼（借錢買更多），負值（綠）= 散戶還錢 / 賣出")
    st.divider()

    st.plotly_chart(fig, width="stretch")

    st.caption(
        f"資料區間：{start_str} ~ {end_str} ｜ "
        f"融資維持率均線：{ma_window} 日"
    )


if page == "💰 融資維持率":
    render_margin_page()
    st.stop()


# ============================================================
# 資料更新頁面
# ============================================================
def render_data_update_page():
    from data_update import (
        run_update, get_last_update_summary, load_status,
        DATA_SOURCES, STATUS_PATH,
    )
    import pandas as pd

    st.header("🔄 資料更新中心")
    st.caption(
        "每日 21:20 自動排程（launchd）+ 隨時可手動按。資料狀態寫到 "
        f"`{STATUS_PATH}`。"
    )

    # === 當前狀態 ===
    summary = get_last_update_summary()

    st.markdown("#### 📊 當前狀態")
    if not summary.get("has_data"):
        st.warning("從未更新過。請按下方按鈕執行首次更新。")
    else:
        # 解析時間
        finished = pd.Timestamp(summary["finished_at"])
        # 距今多久
        now = pd.Timestamp.now()
        delta = now - finished
        if delta.days >= 1:
            age_str = f"{delta.days} 天前"
        elif delta.seconds >= 3600:
            age_str = f"{delta.seconds // 3600} 小時前"
        elif delta.seconds >= 60:
            age_str = f"{delta.seconds // 60} 分鐘前"
        else:
            age_str = f"{delta.seconds} 秒前"

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("上次更新", age_str, delta=summary["finished_at"][:16])
        status_emoji = {
            "success": "✅", "partial": "⚠️", "failed": "❌"
        }.get(summary["overall_status"], "?")
        c2.metric("整體狀態", f"{status_emoji} {summary['overall_status']}")
        c3.metric("成功", f"{summary['n_success']}/{summary['n_total']}")
        c4.metric("耗時", f"{summary['total_elapsed_sec']:.1f}s")
        if summary.get("daily_usage_mb"):
            c5.metric(
                "當日流量",
                f"{summary['daily_usage_mb']:.0f}/{summary['daily_limit_mb']:.0f} MB",
            )
        else:
            c5.metric("當日流量", "（finlab 沒公開 quota API）")

    st.divider()

    # === 手動更新按鈕 ===
    st.markdown("#### 🚀 手動更新")

    c1, c2 = st.columns([1, 2])
    with c1:
        force = st.checkbox(
            "強制重抓（finlab cache 失效）",
            value=False,
            help="⚠️ 雲端部署預設關閉。勾選會從 finlab 拉新資料，可能在 1 分鐘內用掉 1000+ MB quota",
        )
        run_btn = st.button(
            "▶️ 立即更新資料",
            type="primary",
            width="stretch",
            disabled="updating" in st.session_state,
        )
    with c2:
        st.markdown(
            "- **不勾「強制重抓」**：用 finlab 內建 cache，速度快（<5 秒），但資料可能不是最新\n"
            "- **勾「強制重抓」**：真的從 finlab 拉新資料，耗時 1~2 分鐘、會扣 daily quota\n"
            "- 21:20 排程預設會強制重抓（要拿到當日收盤）"
        )

    if run_btn:
        st.session_state["updating"] = True
        progress = st.progress(0.0, text="開始更新…")
        status = st.empty()

        def cb(i, total, name=""):
            pct = (i + 1) / total
            progress.progress(min(pct, 1.0), text=f"({i+1}/{total}) {name}")

        # 簡化：streamlit progress 用單一條線
        try:
            status.info("⏳ 跑更新中，請稍候…")
            result = run_update(force=force)
            status.success(
                f"✅ 完成！{result.overall_status} "
                f"({sum(1 for s in result.sources if s.status == 'success')}/{len(result.sources)} 成功，"
                f"耗時 {result.total_elapsed_sec:.1f}s)"
            )
            progress.progress(1.0, text="完成")
        except Exception as e:
            status.error(f"❌ 更新失敗：`{e}`")
        finally:
            st.session_state.pop("updating", None)
        st.rerun()

    st.divider()

    # === 排程狀態 ===
    st.markdown("#### ⏰ 排程狀態")

    plist_path = Path.home() / "Library/LaunchAgents" / "ai.stockslaves.daily-data-update.plist"
    wrapper_path = Path.home() / ".openclaw" / "jobs" / "daily_data_update.sh"

    c1, c2, c3 = st.columns(3)
    plist_installed = plist_path.exists()
    c1.metric("plist", "✅ 已裝" if plist_installed else "❌ 未裝")
    c2.metric("wrapper script", "✅ 存在" if wrapper_path.exists() else "❌ 缺失")
    # 檢查 launchd 是否真的 load
    try:
        out = subprocess.run(
            ["launchctl", "list", "ai.stockslaves.daily-data-update"],
            capture_output=True, text=True, timeout=3,
        )
        loaded = "PID" in out.stdout or out.returncode == 0
    except Exception:
        loaded = False
    c3.metric("launchd 載入", "✅ 已載" if loaded else "❌ 未載")

    if not (plist_installed and wrapper_path.exists()):
        st.error("⚠️ 排程未完整安裝，請執行安裝步驟")
    elif not loaded:
        st.warning("⚠️ plist 在磁碟上但 launchd 沒載入。從 GUI 終端機跑：")
        st.code(
            f"launchctl bootstrap gui/$UID {plist_path}",
            language="bash",
        )
    else:
        st.success("✅ 排程已就緒。每個工作日 21:20 自動跑資料更新。")
        st.caption("想看 log：`tail -f ~/.openclaw/logs/daily_data_update.stdout.log`")

    st.divider()

    # === 細節：各資料源狀態 ===
    st.markdown("#### 📋 各資料源狀態")
    status_obj = load_status()
    if status_obj is None or len(status_obj.sources) == 0:
        st.info("尚無資料")
    else:
        # 用 group 聚合
        from collections import defaultdict
        groups = defaultdict(list)
        for s in status_obj.sources:
            groups[s.group].append(s)

        for group_name, items in groups.items():
            with st.expander(
                f"**{group_name}** ({sum(1 for s in items if s.status == 'success')}/{len(items)} 成功)",
                expanded=(group_name == "基本"),
            ):
                rows = []
                for s in items:
                    if s.status == "success":
                        rows.append({
                            "資料源": s.label,
                            "代號": s.name,
                            "狀態": "✅",
                            "筆數 × 欄數": f"{s.rows} × {s.cols}",
                            "耗時": f"{s.elapsed_sec:.2f}s",
                        })
                    else:
                        rows.append({
                            "資料源": s.label,
                            "代號": s.name,
                            "狀態": "❌",
                            "筆數 × 欄數": "—",
                            "耗時": f"{s.elapsed_sec:.2f}s",
                            "錯誤": s.error or "",
                        })
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.divider()

    # === 安裝 / 反安裝排程 ===
    st.markdown("#### 🔧 排程安裝")
    with st.expander("顯示安裝指令（一般不需手動跑）"):
        st.markdown("**1. 確認 plist 跟 wrapper 已建立：**")
        st.code(
            f"ls {plist_path}\nls {wrapper_path}",
            language="bash",
        )
        st.markdown("**2. 從 GUI 終端機載入排程（Mavis 跑會撞 TCC）：**")
        st.code(
            f"launchctl bootstrap gui/$UID {plist_path}",
            language="bash",
        )
        st.markdown("**3. 立即跑一次測試：**")
        st.code(
            f"launchctl kickstart -k gui/$UID/ai.stockslaves.daily-data-update",
            language="bash",
        )
        st.markdown("**4. 卸載排程：**")
        st.code(
            f"launchctl bootout gui/$UID/ai.stockslaves.daily-data-update",
            language="bash",
        )
        st.caption(
            "💡 launchd 操作常見的 TCC 問題：Mavis session 跑 `bootout/bootstrap` 會撞 permission，"
            "要從你自己的 GUI 終端機跑。"
        )


# 確保 subprocess 在 file top 引用
import subprocess
from pathlib import Path


if page == "🔄 資料更新":
    render_data_update_page()
    st.stop()


# ============================================================
# 以下是均線預測頁面（原本的內容）
# ============================================================
st.subheader("📈 均線預測")
st.caption("用 FinLab 抓台股資料，預測下個交易日收盤後均線會是跌破、持平、還是起漲。")

# ============================================================
# Sidebar - 設定區
# ============================================================
with st.sidebar:
    st.header("⚙️ 均線設定")

    # 熱門股快選
    POPULAR = {
        "台積電 2330": "2330",
        "鴻海 2317": "2317",
        "聯發科 2454": "2454",
        "台達電 2308": "2308",
        "長榮 2603": "2603",
        "0050 元大台灣50": "0050",
        "0056 元大高股息": "0056",
    }

    # 載入全市場清單（cache）
    try:
        with st.spinner("載入全市場清單…"):
            securities = _load_securities()
    except Exception as e:
        st.error(f"載入全市場清單失敗：`{e}`")
        st.stop()

    favorites = _load_favorites()

    # session_state 統一管理選股結果
    if "stock_id" not in st.session_state:
        st.session_state["stock_id"] = "2330"
        try:
            qp = st.query_params
            raw = None
            if hasattr(qp, "get"):
                raw = qp.get("stock")
            if raw is None and hasattr(qp, "stock"):
                raw = qp.stock
            if isinstance(raw, list):
                raw = raw[0] if raw else None
            if raw:
                st.session_state["stock_id"] = str(raw)
        except Exception:
            pass

    # --- 選股區 ---
    st.subheader("🔍 選股")

    # 分頁：熱門 / 收藏 / 全市場
    tab_hot, tab_fav, tab_all = st.tabs(["⭐ 熱門", "💖 收藏", "🌐 全市場"])

    stock_id = st.session_state["stock_id"]

    with tab_hot:
        popular_keys = list(POPULAR.keys())
        popular_vals = list(POPULAR.values())
        try:
            cur_idx = popular_vals.index(stock_id)
        except ValueError:
            cur_idx = 0
        st.radio(
            "熱門股",
            popular_keys,
            index=cur_idx,
            key="hot_pick",
            label_visibility="collapsed",
            bind="query-params",
        )
        # 從 session_state 讀 pick
        pick = st.session_state.get("hot_pick", "")
        current = st.session_state.get("stock_id", "")
        # 只在目前 stock_id 是熱門股之一時才覆寫（避免 streamlit default 覆蓋 URL 預設）
        if pick in popular_keys and current in popular_vals:
            new_id = popular_vals[popular_keys.index(pick)]
            if current != new_id:
                st.session_state["stock_id"] = new_id

    with tab_fav:
        if not favorites:
            st.info("還沒收藏任何股票。從全市場搜尋後點 ❤ 收藏。")
        else:
            sid_to_name = dict(zip(
                securities["stock_id"].astype(str),
                securities["name"].astype(str),
            ))
            fav_labels = [
                f"{sid_to_name.get(sid, '?')}  {sid}"
                for sid in favorites
            ]
            try:
                cur_idx = favorites.index(stock_id)
            except ValueError:
                cur_idx = 0
            st.radio(
                "收藏",
                fav_labels,
                index=cur_idx if 0 <= cur_idx < len(fav_labels) else 0,
                key="fav_pick",
                label_visibility="collapsed",
                bind="query-params",
            )
            # 從 session_state 讀 pick
            pick = st.session_state.get("fav_pick", "")
            current = st.session_state.get("stock_id", "")
            # 只在目前 stock_id 已在 favorites 內時才覆寫
            if pick in fav_labels and current in favorites:
                new_id = favorites[fav_labels.index(pick)]
                if current != new_id:
                    st.session_state["stock_id"] = new_id

    with tab_all:
        # 1) 關鍵字搜尋
        #    bind="query-params" 讓 Enter 後 streamlit 強制把 value 寫進 URL
        st.text_input(
            "搜尋（代號或中文）",
            placeholder="例如 3037 / 欣興 / 0050",
            key="all_search",
            label_visibility="collapsed",
            bind="query-params",
        )
        search = st.session_state.get("all_search", "").strip().lower()

        # 2) 市場類型過濾
        market_filter = st.multiselect(
            "市場",
            options=sorted(securities["market"].unique()),
            default=["sii", "otc", "etf"],
            key="all_markets",
            label_visibility="collapsed",
        )

        # 3) 套用過濾
        df_filtered = securities[securities["market"].isin(market_filter)].copy()

        if search:
            mask = (
                df_filtered["stock_id"].astype(str).str.lower().str.contains(search)
                | df_filtered["name"].astype(str).str.lower().str.contains(search)
            )
            df_filtered = df_filtered[mask]

        st.caption(f"符合 {len(df_filtered)} 檔（顯示前 200）")

        # ★ 搜尋精準命中 1 筆 → 自動設 stock_id
        #    bind="query-params" 讓 URL 同步，但 tab 沒被選中時 session_state 可能殘留舊值。
        #    用「URL 當前真的有這個 query param」當守護。
        if search and len(df_filtered) == 1:
            # 檢查 URL 真的有 all_search query param
            qp_has_search = False
            try:
                qp = st.query_params
                if hasattr(qp, "get"):
                    qp_search = qp.get("all_search")
                else:
                    qp_search = None
                if qp_search is not None:
                    qp_has_search = True
            except Exception:
                pass
            if qp_has_search:
                auto_id = str(df_filtered.iloc[0]["stock_id"])
                st.session_state["stock_id"] = auto_id

        # 4) 顯示成 label: "2330 台積電 [sii]"
        #    注意：security_categories 的 stock_id 已經是純數字
        df_filtered["label"] = (
            df_filtered["stock_id"].astype(str)
            + "  "
            + df_filtered["name"].astype(str)
            + "  ["
            + df_filtered["market"].astype(str)
            + "]"
        )

        if len(df_filtered) == 0:
            st.warning("找不到符合的股票")
        else:
            # 顯示 label，但 stock_id 從原 df 取
            df_show = df_filtered.head(200).copy()
            options = df_show["label"].tolist()
            # 預設 index 對齊目前 session_state["stock_id"]
            current = st.session_state.get("stock_id", "2330")
            default_idx = 0
            for i, sid_full in enumerate(df_show["stock_id"].astype(str).tolist()):
                if sid_full == current:
                    default_idx = i
                    break
            st.selectbox(
                "選個股",
                options,
                index=default_idx,
                key="all_pick",
                label_visibility="collapsed",
                bind="query-params",
            )
            # 從 session_state 讀 pick（不靠 widget return，避免 tab re-execute 拿不到值）
            pick = st.session_state.get("all_pick", "")
            # ★ 重要：只在「目前 stock_id 不在 options 裡」時才覆寫
            #    避免 streamlit 自動把 default option 寫進 session_state 時污染 stock_id
            current = st.session_state.get("stock_id", "")
            current_in_options = any(
                sid_full == current
                for sid_full in df_show["stock_id"].astype(str).tolist()
            )
            if pick and current_in_options and pick in df_show["label"].tolist():
                sel_row = df_show[df_show["label"] == pick].iloc[0]
                new_id = str(sel_row["stock_id"])
                if current != new_id:
                    st.session_state["stock_id"] = new_id

    st.divider()

    # --- 收藏 / 取消收藏當前股票 ---
    # 收藏清單用純數字（如 "2330"），比對時用同樣 key
    is_fav = stock_id in favorites
    if is_fav:
        if st.button("💔 取消收藏", width="stretch"):
            favorites.remove(stock_id)
            _save_favorites(favorites)
            st.rerun()
    else:
        if st.button("❤ 加入收藏", width="stretch"):
            if stock_id not in favorites:
                favorites.append(stock_id)
                _save_favorites(favorites)
            st.rerun()

    st.divider()

    chart_days = st.slider("K 線回看天數", min_value=60, max_value=250, value=120, step=20)

    flat_threshold = st.slider(
        "持平容忍門檻 (%)",
        min_value=0.05, max_value=2.0, value=DEFAULT_FLAT_THRESHOLD_PCT, step=0.05,
        help="變動幅度小於此門檻視為「持平」",
    )

    st.divider()
    st.markdown("**使用說明**")
    st.markdown(
        "1. 選股（或輸入代號）\n"
        "2. 看 K 線與現況均線\n"
        "3. 輸入你預測的明天收盤價\n"
        "4. 看 4 條均線是 🟢起漲 / 🟡持平 / 🔴跌破"
    )


# ============================================================
# 主畫面
# ============================================================
@st.cache_data(ttl=3600, show_spinner="FinLab 抓資料中…")
def _load(stock_id: str, days: int) -> pd.DataFrame:
    return fetch_ohlcv(stock_id, days=days + 60)  # 多抓 60 天給 MA60


# --- 重新讀取最新 stock_id（sidebar 內 tab_all 可能已更新）---
stock_id = st.session_state["stock_id"]

# --- 載入資料 ---
if not stock_id:
    st.info("👈 請從左邊選一支股票")
    st.stop()

try:
    with st.spinner(f"載入 {stock_id} 資料中…"):
        df = _load(stock_id, chart_days)
    name = get_stock_name(stock_id)
except Exception as e:
    st.error(f"抓資料失敗：`{e}`")
    st.stop()

if len(df) < 60:
    st.error(f"資料不足 60 筆（目前 {len(df)} 筆），無法計算 MA60")
    st.stop()

# 取最近 chart_days 天
df_view = df.tail(chart_days).copy()
close = df_view["close"]
last_date = df_view.index[-1]
last_close = float(close.iloc[-1])

# ============================================================
# Section 1: 現況概覽
# ============================================================
st.subheader(f"📊 {name} ({stock_id}) 現況")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("最後交易日", last_date.strftime("%Y-%m-%d"))
c2.metric("最新收盤價", f"{last_close:,.2f}")

# 現況均線
cur_mas = {}
for w in DEFAULT_MA_WINDOWS:
    cur_mas[w] = float(close.iloc[-w:].mean())

# 顯示 4 條現況均線
cols = st.columns(4)
for i, w in enumerate(DEFAULT_MA_WINDOWS):
    v = cur_mas[w]
    delta = (v / last_close - 1) * 100
    cols[i].metric(
        f"MA{w}",
        f"{v:,.2f}",
        f"{delta:+.2f}% vs 收盤",
        delta_color="normal" if delta >= 0 else "inverse",
    )

st.divider()

# ============================================================
# Section 2: 預測面板
# ============================================================
st.subheader("🔮 預測下個交易日收盤後的均線")

# 提示用：給使用者一個「持平參考價」（=目前視窗最舊那根收盤）
break_even_refs = {w: find_break_even_close(close, w) for w in DEFAULT_MA_WINDOWS}

with st.container():
    pc1, pc2 = st.columns([2, 1])
    with pc1:
        predicted_close = st.number_input(
            "預測下個交易日收盤價",
            min_value=0.0,
            value=float(last_close),
            step=0.5,
            format="%.2f",
            help="輸入你猜的明天收盤價，看看 4 條均線會怎麼反應",
        )
    with pc2:
        # Quick buttons
        st.write("快速帶入：")
        b1, b2, b3 = st.columns(3)
        if b1.button(f"+1% ({last_close*1.01:.2f})"):
            predicted_close = round(last_close * 1.01, 2)
            st.rerun()
        if b2.button("持平"):
            predicted_close = last_close
            st.rerun()
        if b3.button(f"-1% ({last_close*0.99:.2f})"):
            predicted_close = round(last_close * 0.99, 2)
            st.rerun()

# 跑預測
result = predict_all_ma(
    close=close,
    last_date=last_date,
    last_close=last_close,
    predicted_next_close=predicted_close,
    stock_id=stock_id,
    stock_name=name,
    flat_threshold_pct=flat_threshold,
)

# 整體訊號
signal_color = {"偏多": "🟢", "偏空": "🔴", "盤整": "🟡"}[result.overall_signal]
st.markdown(
    f"### 整體訊號：{signal_color} **{result.overall_signal}** "
    f"（分數 {result.overall_score:+d}/4，"
    f"起漲 {sum(1 for m in result.mas.values() if m.status=='起漲')} / "
    f"持平 {sum(1 for m in result.mas.values() if m.status=='持平')} / "
    f"跌破 {sum(1 for m in result.mas.values() if m.status=='跌破')}）"
)

# 4 條均線卡片
st.markdown("#### 各均線判定")
cols = st.columns(4)
for i, w in enumerate(DEFAULT_MA_WINDOWS):
    m = result.mas[w]
    with cols[i]:
        st.markdown(
            f"""
            <div style="border:2px solid {m.color};border-radius:12px;padding:12px;background:#0e1117;">
              <div style="color:#aaa;font-size:0.9em;">MA{w}</div>
              <div style="font-size:1.6em;font-weight:bold;">{m.current_value:,.2f}</div>
              <div style="color:#aaa;font-size:0.8em;">↓ 預測</div>
              <div style="font-size:1.6em;font-weight:bold;color:{m.color};">{m.predicted_value:,.2f}</div>
              <div style="margin-top:4px;font-size:1.1em;">{m.emoji} <b>{m.status}</b> ({m.delta_pct:+.2f}%)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# 持平參考價
with st.expander("💡 持平參考價（讓均線不變所需的收盤價）"):
    st.caption("下個交易日收在這個價，該均線會維持不變（純 SMA 數學推導）")
    ref_df = pd.DataFrame({
        "均線": [f"MA{w}" for w in DEFAULT_MA_WINDOWS],
        "持平參考價": [f"{break_even_refs[w]:,.2f}" for w in DEFAULT_MA_WINDOWS],
        "vs 現況收盤": [f"{(break_even_refs[w]/last_close - 1)*100:+.2f}%" for w in DEFAULT_MA_WINDOWS],
    })
    st.dataframe(ref_df, width="stretch", hide_index=True)

st.divider()

# ============================================================
# Section 3: K 線圖 + 均線（含預測延伸）
# ============================================================
st.subheader("🕯️ K 線圖 + 均線標註")

chart_df = build_chart_data(close, predicted_close, DEFAULT_MA_WINDOWS)

# 標記最後一日 + 預測日
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    row_heights=[0.75, 0.25],
)

# K 線：到倒數第二根為止（最後一根是預測的虛擬點）
fig.add_trace(
    go.Candlestick(
        x=df_view.index,
        open=df_view["open"], high=df_view["high"],
        low=df_view["low"], close=df_view["close"],
        name="K線",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ),
    row=1, col=1,
)

# 預測那根（虛擬 K 線，只有 close=預測收盤，OH 一律=close 視為十字）
pred_idx = chart_df.index[-1]
fig.add_trace(
    go.Candlestick(
        x=[pred_idx],
        open=[predicted_close], high=[predicted_close],
        low=[predicted_close], close=[predicted_close],
        name="🔮 預測",
        increasing=dict(line=dict(color="#ffeb3b", width=2)),
        decreasing=dict(line=dict(color="#ffeb3b", width=2)),
    ),
    row=1, col=1,
)

# 均線（畫到包含預測那一點）
ma_colors = {5: "#42a5f5", 10: "#ab47bc", 20: "#ffa726", 60: "#ef5350"}
for w in DEFAULT_MA_WINDOWS:
    fig.add_trace(
        go.Scatter(
            x=chart_df.index, y=chart_df[f"MA{w}"],
            name=f"MA{w}", line=dict(color=ma_colors[w], width=1.6),
        ),
        row=1, col=1,
    )

# Volume
volume_colors = ["#26a69a" if df_view["close"].iloc[i] >= df_view["open"].iloc[i] else "#ef5350"
                 for i in range(len(df_view))]
fig.add_trace(
    go.Bar(
        x=df_view.index, y=df_view["volume"],
        name="成交量", marker_color=volume_colors, opacity=0.6,
    ),
    row=2, col=1,
)

# 預測收盤的水平線
fig.add_hline(
    y=predicted_close, line_dash="dot", line_color="#ffeb3b",
    annotation_text=f"預測 {predicted_close:,.2f}",
    row=1, col=1,
)

# 現況收盤水平線（輔助）
fig.add_hline(
    y=last_close, line_dash="dot", line_color="#888",
    annotation_text=f"現況 {last_close:,.2f}",
    row=1, col=1,
)

fig.update_layout(
    height=650,
    xaxis_rangeslider_visible=False,
    template="plotly_dark",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
)
fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
fig.update_yaxes(title_text="價格", row=1, col=1)
fig.update_yaxes(title_text="量", row=2, col=1)

st.plotly_chart(fig, width="stretch")

# ============================================================
# Footer
# ============================================================
st.divider()
st.caption(
    "資料來源：FinLab ｜ "
    "判定門檻可在左側調整 ｜ "
    "預測為個人猜測，不構成投資建議"
)
