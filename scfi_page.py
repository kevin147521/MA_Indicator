#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
scfi_page.py — SCFI (上海出口集裝箱運價指數) 頁面

混合模式：
- 歷史：從 user 上傳的 CSV seed（任何來源：MacroMicro / SSE 中文版 / 手動）
- 每週新增：按「抓最新一週」打 SSE 公開 API（只會拿到綜合指數，分航線要登入）
- 全部資料存：~/.openclaw/ma_indicator_data/scfi_history.csv

CSV 欄位順序（依 scfi_fetcher.COLUMN_ORDER）：
  date, SCFI_T, SCFI_L1, SCFI_L2, ..., SCFI_L31, source

source: "SSE" (自動抓) / "manual" (手動) / "csv_upload" (上傳)
"""
from __future__ import annotations

from pathlib import Path
import io
from typing import Optional

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from scfi_fetcher import (
    SCFI_LINES,
    fetch_latest_scfi,
    to_csv_row,
    COLUMN_ORDER,
)


# ============================================================
# 資料存取
# ============================================================
DATA_DIR = Path.home() / ".openclaw" / "ma_indicator_data"
DATA_PATH = DATA_DIR / "scfi_history.csv"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_history() -> pd.DataFrame:
    """讀歷史 CSV。沒檔案就回空 DataFrame。"""
    if not DATA_PATH.exists():
        return pd.DataFrame(columns=COLUMN_ORDER)
    df = pd.read_csv(DATA_PATH, dtype={"date": str})
    if "source" not in df.columns:
        df["source"] = "csv_upload"
    # 確保所有航線欄位存在
    for col in SCFI_LINES.keys():
        if col not in df.columns:
            df[col] = None
    # 排序
    df = df.sort_values("date").reset_index(drop=True)
    return df


def save_history(df: pd.DataFrame):
    """存歷史 CSV。"""
    _ensure_data_dir()
    df_out = df.copy()
    # 強制欄位順序
    for col in COLUMN_ORDER:
        if col not in df_out.columns:
            df_out[col] = None
    df_out = df_out[COLUMN_ORDER]
    df_out.to_csv(DATA_PATH, index=False)


def add_week(row: dict) -> tuple[pd.DataFrame, bool]:
    """
    新增一週資料。如果該日期已存在就覆蓋。
    回傳 (新 df, 是否真的新增了)
    """
    df = load_history()
    date = row["date"]
    is_new = date not in df["date"].values
    if is_new:
        new_row = pd.DataFrame([row])
        df = pd.concat([df, new_row], ignore_index=True)
    else:
        for k, v in row.items():
            df.loc[df["date"] == date, k] = v
    df = df.sort_values("date").reset_index(drop=True)
    save_history(df)
    return df, is_new


def delete_week(date: str) -> pd.DataFrame:
    """刪除指定日期那一週。"""
    df = load_history()
    df = df[df["date"] != date].reset_index(drop=True)
    save_history(df)
    return df


def replace_all(df_new: pd.DataFrame) -> pd.DataFrame:
    """整個替換（CSV 上傳用）。"""
    save_history(df_new)
    return df_new


# ============================================================
# 圖表
# ============================================================
def _line_labels() -> list[tuple[str, str, str]]:
    """回傳 (dataItemType, 中文標籤, 單位) 的 list，給 UI 顯示用。"""
    return [(k, v[0], v[2]) for k, v in SCFI_LINES.items()]


def plot_comprehensive(df: pd.DataFrame, window: int = 4) -> go.Figure:
    """
    綜合指數折線圖 + N 週移動平均。
    """
    fig = go.Figure()

    if len(df) == 0:
        fig.update_layout(
            template="plotly_dark",
            annotations=[dict(text="無資料", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper", font=dict(size=20, color="#888"))],
        )
        return fig

    df_v = df.copy()
    df_v["date"] = pd.to_datetime(df_v["date"])
    df_v = df_v.sort_values("date")

    # 綜合指數
    fig.add_trace(go.Scatter(
        x=df_v["date"], y=df_v["SCFI_T"],
        name="綜合指數", mode="lines+markers",
        line=dict(color="#42a5f5", width=2.5),
        marker=dict(size=5),
    ))

    # N 週均線
    if window > 1 and len(df_v) >= window:
        ma = df_v["SCFI_T"].rolling(window=window, min_periods=window).mean()
        fig.add_trace(go.Scatter(
            x=df_v["date"], y=ma,
            name=f"MA{window}",
            line=dict(color="#ffa726", width=1.8, dash="dash"),
        ))

    # 週漲跌標註
    if len(df_v) >= 2:
        diffs = df_v["SCFI_T"].diff()
        colors = ["#26a69a" if d < 0 else "#ef5350" for d in diffs.fillna(0)]  # 台股：紅漲綠跌
        fig.add_trace(go.Bar(
            x=df_v["date"], y=diffs,
            name="週漲跌", marker_color=colors, opacity=0.25,
            yaxis="y2",
        ))

    fig.update_layout(
        title="SCFI 綜合指數走勢",
        template="plotly_dark",
        height=450,
        hovermode="x unified",
        yaxis=dict(title="指數"),
        yaxis2=dict(title="週漲跌", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def plot_lines_grid(df: pd.DataFrame, selected: list[str], height: int = 800) -> go.Figure:
    """
    15 條分航線小倍數圖（每條一個 subplot）。
    """
    n = len(selected)
    if n == 0:
        return None

    # 動態算 rows（每行 3 個）
    cols = 3 if n >= 3 else n
    rows = (n + cols - 1) // cols

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=[f"{SCFI_LINES[k][0]}" for k in selected],
        vertical_spacing=0.06,
        horizontal_spacing=0.06,
    )

    df_v = df.copy()
    df_v["date"] = pd.to_datetime(df_v["date"])
    df_v = df_v.sort_values("date")

    for i, key in enumerate(selected):
        r, c = i // cols + 1, i % cols + 1
        zh, en, unit = SCFI_LINES[key]
        # 顏色用 unit 區分：TEU 藍、FEU 橘、Index 綠
        color = {"USD/TEU": "#42a5f5", "USD/FEU": "#ffa726", "Index": "#26a69a"}.get(unit, "#ab47bc")
        fig.add_trace(
            go.Scatter(
                x=df_v["date"], y=df_v[key],
                mode="lines+markers", name=zh,
                line=dict(color=color, width=1.6),
                marker=dict(size=3),
                showlegend=False,
            ),
            row=r, col=c,
        )
        fig.update_yaxes(title_text=unit, row=r, col=c, title_font_size=9)

    fig.update_layout(
        title=f"分航線運價走勢（{n} 條）",
        template="plotly_dark",
        height=height,
        hovermode="x unified",
    )
    return fig


# ============================================================
# 統計
# ============================================================
def render_summary(df: pd.DataFrame) -> dict:
    """最新一週概況 metric"""
    if len(df) == 0 or df["SCFI_T"].isna().all():
        return {}
    df_v = df.copy()
    df_v["date"] = pd.to_datetime(df_v["date"])
    df_v = df_v.sort_values("date")
    latest = df_v.iloc[-1]
    prev = df_v.iloc[-2] if len(df_v) >= 2 else None

    comprehensive = float(latest["SCFI_T"]) if pd.notna(latest["SCFI_T"]) else None
    prev_val = float(prev["SCFI_T"]) if prev is not None and pd.notna(prev["SCFI_T"]) else None
    diff = (comprehensive - prev_val) if (comprehensive and prev_val) else None
    pct = (diff / prev_val * 100) if (diff and prev_val) else None

    all_vals = df_v["SCFI_T"].dropna()
    hi = float(all_vals.max())
    lo = float(all_vals.min())
    avg = float(all_vals.mean())

    return {
        "date": str(latest["date"])[:10],
        "comprehensive": comprehensive,
        "diff": diff,
        "pct": pct,
        "hi": hi,
        "lo": lo,
        "avg": avg,
        "hi_date": str(df_v.loc[df_v["SCFI_T"].idxmax(), "date"])[:10],
        "lo_date": str(df_v.loc[df_v["SCFI_T"].idxmin(), "date"])[:10],
        "n": len(df_v),
    }


# ============================================================
# Streamlit page
# ============================================================
def render_scfi_page():
    st.header("📦 SCFI 上海出口集裝箱運價指數")
    st.caption(
        "上海航運交易所每週五 15:00 公佈的即期運價指數。紅色 = 上漲、綠色 = 下跌（台股慣例）。"
    )

    # === 載入歷史 ===
    df = load_history()
    has_data = len(df) > 0

    # === 頂部概況 ===
    if has_data:
        s = render_summary(df)
        if s:
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("最新日期", s["date"])
            c2.metric("綜合指數", f"{s['comprehensive']:,.2f}")
            if s["pct"] is not None:
                c3.metric("週漲跌", f"{s['diff']:+.2f}", delta=f"{s['pct']:+.2f}%", delta_color="inverse")
            else:
                c3.metric("週漲跌", "—")
            c4.metric("歷史最高", f"{s['hi']:,.0f}", delta=s["hi_date"])
            c5.metric("歷史最低", f"{s['lo']:,.0f}", delta=s["lo_date"])
            c6.metric("資料筆數", f"{s['n']} 週")
    else:
        st.warning("⚠️ 還沒有任何資料。請到下方「手動上傳 CSV」或「手動新增一週」起步，或按「抓最新一週」補當週綜合指數。")

    st.divider()

    # === 控制區（用 tabs 分類操作） ===
    tab_chart, tab_fetch, tab_manual, tab_data = st.tabs([
        "📈 走勢圖", "🌐 抓資料", "✏️ 手動", "📋 資料表"
    ])

    # ---------- 走勢圖 tab ----------
    with tab_chart:
        if not has_data:
            st.info("請先到「手動」或「抓資料」tab 灌入歷史")
            return

        ma_window = st.slider("綜合指數均線（週）", min_value=2, max_value=12, value=4, step=1)

        fig = plot_comprehensive(df, window=ma_window)
        st.plotly_chart(fig, width="stretch")

        st.divider()

        # 分航線圖
        st.markdown("#### 分航線走勢")
        # 列出有資料的航線（至少有 3 個非空值才顯示）
        candidate_lines = [k for k in SCFI_LINES.keys() if k != "SCFI_T"]
        available = [k for k in candidate_lines if df[k].notna().sum() >= 3]
        if not available:
            st.info("分航線資料不足（需要至少 3 週非空值）。請上傳含分航線的 CSV。")
        else:
            default_pick = available[:6]  # 預設選前 6 條
            selected = st.multiselect(
                "選要看哪些航線",
                options=available,
                default=default_pick,
                format_func=lambda k: f"{SCFI_LINES[k][0]} ({SCFI_LINES[k][2]})",
            )
            if selected:
                # 動態算高度（每行 250px）
                n_rows = (len(selected) + 2) // 3
                fig_lines = plot_lines_grid(df, selected, height=max(400, n_rows * 250))
                if fig_lines:
                    st.plotly_chart(fig_lines, width="stretch")

    # ---------- 抓資料 tab ----------
    with tab_fetch:
        st.markdown("#### 從 SSE 抓最新一週")
        st.caption(
            "打 [en.sse.net.cn/indices/scfinew.jsp](https://en.sse.net.cn/indices/scfinew.jsp) "
            "的公開 API。**只會拿到當週綜合指數**（分航線境外未登入請求會回 null，"
            "要 SSE 付費會員才能拿）。歷史從 CSV seed 補。"
        )

        c1, c2 = st.columns([1, 2])
        with c1:
            fetch_btn = st.button("🌐 抓 SSE 最新一週", type="primary", width="stretch")
        with c2:
            st.caption("每週五 15:00（台北時間）發布，當天或週末按即可。")

        if fetch_btn:
            try:
                with st.spinner("抓 SSE 中…"):
                    result = fetch_latest_scfi()
                row = to_csv_row(result)
                df_new, is_new = add_week(row)
                st.success(
                    f"✅ {result.date} 綜合指數 {result.values.get('SCFI_T'):,.2f} "
                    f"（{'(新的一週)' if is_new else '(覆蓋現有資料)'}）"
                )
                if not result.has_lines:
                    st.info(
                        f"ℹ️ 分航線資料沒拿到（0/20）。SSE 公開 API 對未登入用戶只回綜合指數。"
                        f"如需分航線請到中文版 https://www.sse.net.cn/index/singleIndex?indexType=scfi 手動複製貼上。"
                    )
                st.rerun()
            except Exception as e:
                st.error(f"❌ 抓取失敗：`{e}`")

        # 顯示已抓過的 SSE 資料
        st.divider()
        st.markdown("#### 已從 SSE 抓過的週次")
        sse_df = df[df["source"] == "SSE"]
        if len(sse_df) == 0:
            st.info("尚無")
        else:
            st.dataframe(
                sse_df[["date", "SCFI_T"]].rename(columns={
                    "date": "日期", "SCFI_T": "綜合指數"
                }),
                width="stretch", hide_index=True,
            )

    # ---------- 手動 tab ----------
    with tab_manual:
        st.markdown("#### A. 上傳歷史 CSV")
        st.caption(
            "從任何來源下載的 SCFI CSV（MacroMicro / SSE 中文版 / TradingEconomics / 自己維護的試算表）。"
            "欄位名稱要對到：date 必填，加上 SCFI_T (綜合指數) 跟任何 SCFI_L1~L31 航線代號。"
            "沒填的欄位會留空，不影響其他資料。"
        )

        uploaded = st.file_uploader("選擇 CSV 檔", type=["csv"], key="scfi_csv_upload")
        if uploaded is not None:
            try:
                df_up = pd.read_csv(uploaded, dtype={"date": str})
                # 基本驗證
                if "date" not in df_up.columns:
                    st.error("❌ CSV 必須有 `date` 欄位")
                else:
                    # 把沒見過的欄位標 source=csv_upload
                    for col in df_up.columns:
                        if col not in COLUMN_ORDER and col not in ("date", "source"):
                            st.warning(f"⚠️ 未知欄位 `{col}` 會被忽略")
                    df_up["source"] = df_up.get("source", "csv_upload")
                    # 強制欄位
                    for col in COLUMN_ORDER:
                        if col not in df_up.columns:
                            df_up[col] = None
                    df_up = df_up[COLUMN_ORDER]
                    st.dataframe(df_up.head(5), width="stretch")
                    n_new = (df_up["date"].astype(str).isin(df["date"].astype(str)) == False).sum()
                    st.info(f"預計新增 {n_new} 筆新資料，覆蓋 {len(df_up) - n_new} 筆既有資料。")
                    if st.button("✅ 確認匯入（會覆蓋現有資料）", type="primary"):
                        df_combined = pd.concat([df, df_up], ignore_index=True)
                        df_combined = df_combined.drop_duplicates(subset="date", keep="last")
                        df_combined = df_combined.sort_values("date").reset_index(drop=True)
                        replace_all(df_combined)
                        st.success(f"✅ 匯入完成！總共 {len(df_combined)} 週資料。")
                        st.rerun()
            except Exception as e:
                st.error(f"❌ CSV 解析失敗：`{e}`")

        st.divider()

        st.markdown("#### B. 手動新增單週")
        st.caption("當週資料還沒出、或 SSE 抓不到時手動補。")

        with st.form("add_one_week"):
            col_date, col_source = st.columns([1, 1])
            with col_date:
                manual_date = st.date_input("日期", value=pd.Timestamp.today().normalize())
            with col_source:
                st.write("")  # spacer

            st.markdown("**綜合指數（必填）**")
            manual_comp = st.number_input("SCFI_T 綜合指數", min_value=0.0, value=2000.0, step=10.0, format="%.2f")

            st.markdown("**分航線運價（選填，沒資料就跳過）**")
            manual_lines = {}
            # 分 3 欄排
            line_list = _line_labels()
            for i in range(1, len(line_list)):  # skip SCFI_T
                key, zh, unit = line_list[i]
                manual_lines[key] = None  # placeholder

            # 用 expanders 折疊起來免得太長
            with st.expander("展開填分航線運價（可選）", expanded=False):
                for i in range(0, len(line_list) - 1, 3):
                    cols = st.columns(3)
                    for j in range(3):
                        idx = i + j + 1
                        if idx >= len(line_list):
                            break
                        key, zh, unit = line_list[idx]
                        with cols[j]:
                            manual_lines[key] = st.number_input(
                                f"{zh} ({unit})",
                                min_value=0.0, value=0.0, step=10.0, format="%.2f",
                                key=f"manual_{key}",
                            )

            submitted = st.form_submit_button("➕ 新增這一週", type="primary", width="stretch")
            if submitted:
                row = {"date": manual_date.strftime("%Y-%m-%d"), "source": "manual", "SCFI_T": manual_comp}
                for k, v in manual_lines.items():
                    row[k] = v if v and v > 0 else None
                df_new, is_new = add_week(row)
                st.success(f"✅ {manual_date.strftime('%Y-%m-%d')} 已新增（{'(新)' if is_new else '(覆蓋)'}）")
                st.rerun()

        st.divider()

        st.markdown("#### C. 下載現有資料 / 範本")
        if has_data:
            csv_buf = io.StringIO()
            df.to_csv(csv_buf, index=False)
            st.download_button(
                "⬇️ 下載現有 CSV",
                data=csv_buf.getvalue().encode("utf-8"),
                file_name=f"scfi_history_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                width="stretch",
            )

        # 範本
        st.caption("**CSV 範本**（下載後填值上傳）：")
        sample = pd.DataFrame([{
            "date": "2024-01-05",
            "SCFI_T": 2030.0,
            "SCFI_L1": 2150.0,    # 歐洲 20ft
            "SCFI_L3": 1900.0,    # 美西 40ft
            "SCFI_L4": 2400.0,    # 美東 40ft
            "SCFI_L12": 800.0,    # 東南亞 20ft
            "source": "manual",
        }])
        for col in COLUMN_ORDER:
            if col not in sample.columns:
                sample[col] = None
        sample = sample[COLUMN_ORDER]
        st.download_button(
            "⬇️ 下載 CSV 範本",
            data=sample.to_csv(index=False).encode("utf-8"),
            file_name="scfi_template.csv",
            mime="text/csv",
        )

    # ---------- 資料表 tab ----------
    with tab_data:
        if not has_data:
            st.info("尚無資料")
            return

        st.markdown("#### 完整資料表")
        # 只顯示有資料的欄位（避免一堆 NaN 欄位干擾）
        useful_cols = ["date", "SCFI_T"] + [k for k in SCFI_LINES.keys() if k != "SCFI_T" and df[k].notna().any()]
        show_df = df[useful_cols].copy()
        show_df = show_df.sort_values("date", ascending=False)
        # 改欄位名為中文
        rename = {"date": "日期", "SCFI_T": "綜合指數", "source": "來源"}
        for k, (zh, en, unit) in SCFI_LINES.items():
            if k in show_df.columns:
                rename[k] = zh
        show_df = show_df.rename(columns=rename)
        st.dataframe(show_df, width="stretch", hide_index=True)

        # 刪除單週
        st.divider()
        st.markdown("#### 刪除單週（打錯修正用）")
        c1, c2 = st.columns([3, 1])
        with c1:
            date_to_delete = st.selectbox(
                "選要刪的日期",
                options=df["date"].tolist()[::-1],  # 最新在前
            )
        with c2:
            st.write("")
            st.write("")
            if st.button("🗑️ 刪除", type="secondary"):
                df_new = delete_week(date_to_delete)
                st.success(f"已刪除 {date_to_delete}")
                st.rerun()

        st.divider()
        st.caption(f"資料存檔位置：`{DATA_PATH}`")
