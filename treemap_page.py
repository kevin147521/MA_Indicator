#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
treemap_page.py — 台股市值 × 漲跌幅 treemap 模組

純函式 + Plotly Express treemap，方便 Streamlit 跟 notebook 共用。

設計：
1. size 可選 market_value（市值）/ turnover（成交金額）/ turnover_ratio（成交佔比）
2. color 預設 return_ratio（當日漲跌幅 %），可選其他 finlab 指標
3. 階層：country → market（sii/otc/etf）→ category（產業）→ stock_id_name
4. exclude_penny：可選過濾低價股（避免面額 1~5 元的極端例子把 treemap 拉爆）
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# === 預設參數 ===
DEFAULT_AREA = "market_value"            # treemap size 來源
DEFAULT_ITEM = "return_ratio"            # treemap color 來源
DEFAULT_CLIP = 10.0                      # 漲跌幅 ±10% clip（避免極端值壓縮色階）
DEFAULT_COLORS = "RdYlGn_r"              # 反轉：紅=漲、綠=跌（台股慣例）
DEFAULT_EXCLUDE_ETF = True               # 預設排除 ETF（範例 notebook 用 company_basic_info 就會漏 ETF）


# === 工具 ===
def _df_date_filter(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """過濾日期範圍（包含 start 跟 end 當天）"""
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df


# === 資料準備 ===
def build_treemap_data(
    start: str = None,
    end: str = None,
    item: str = "return_ratio",
    clip: float = DEFAULT_CLIP,
    exclude_etf: bool = DEFAULT_EXCLUDE_ETF,
    exclude_penny: bool = True,
    penny_threshold: float = 10.0,
) -> pd.DataFrame:
    """
    組裝 treemap 用的 DataFrame。

    Parameters
    ----------
    start, end : 'YYYY-MM-DD'，預設 = 昨天 / 兩天前（要避開「今天」因為 finlab 還沒收盤）
    item : color 用的指標，預設 'return_ratio'（當日漲跌幅 %）
            也可填 'turnover_ratio' 或 finlab 其他指標（會自動帶寬表欄位）
    clip : 把 item 的值 clip 到 ±clip，避免極端值壓縮色階
    exclude_etf : 是否排除 ETF / 權證 / 債券（公司基本資料表沒這些）
    exclude_penny : 是否排除低價股（收盤 < penny_threshold）
    penny_threshold : 低價股門檻

    Returns
    -------
    DataFrame with columns:
        stock_id, name, close, turnover, return_ratio, market_value, turnover_ratio,
        category, market, country, item_value (= item)
    """
    from data_fetcher import ensure_finlab_login
    ensure_finlab_login()

    from finlab import data

    close = data.get("price:收盤價")
    basic = data.get("company_basic_info")
    turnover = data.get("price:成交金額")

    # 防呆：如果 start > end 自動對調（避免 date_input 順序顛倒）
    if start and end and pd.Timestamp(start) > pd.Timestamp(end):
        start, end = end, start

    close_data = _df_date_filter(close, start, end)
    turnover_data = _df_date_filter(turnover, start, end)

    # 預設日期：end=昨天（最後一個交易日收盤），start=前一個交易日（算單日漲跌）
    if end is None:
        end = close.index[-1].strftime("%Y-%m-%d")
    if start is None:
        # 取 end 往前 1 個交易日的索引
        end_ts = pd.Timestamp(end)
        prev_idx = close.index.get_indexer([end_ts], method="ffill")[0]
        if prev_idx > 0:
            start = close.index[prev_idx - 1].strftime("%Y-%m-%d")
        else:
            start = close.index[0].strftime("%Y-%m-%d")

    # 重新過濾（確保 start / end 都正確）
    close_data = _df_date_filter(close, start, end)
    turnover_data = _df_date_filter(turnover, start, end)

    # 重新過濾（確保 start / end 都正確）
    close_data = _df_date_filter(close, start, end)
    turnover_data = _df_date_filter(turnover, start, end)

    if len(close_data) < 2:
        raise ValueError(f"start~end ({start} ~ {end}) 期間資料不足 2 天，無法算 return_ratio")

    # 累計成交金額（億）
    turnover_total = turnover_data.iloc[1:].sum() / 1e8

    # 漲跌幅 %：
    #   - 區間 >= 2 天 → 算累計漲跌（close[end] / close[start] - 1）
    #   - 區間剛好 1 天（單日）→ 算當日漲跌（close[end] / close[end 前一天] - 1）
    if len(close_data) >= 2:
        # 取基準日：
        # 如果 close_data 第一天 == start（user 自訂區間），用 start 當基準
        # 如果 start 是 end 往前 1 個交易日（單日模式預設值），用 start 當基準（結果一樣是單日漲跌）
        # 兩種情況下都用 close_data.iloc[0] 當基準最直觀
        base = close_data.iloc[0]
    else:
        base = close_data.iloc[-1]

    return_ratio = (close_data.iloc[-1] / base).dropna().replace([np.inf, -np.inf], 0)
    return_ratio = round((return_ratio - 1) * 100, 2)

    # 組合
    parts = [close_data.iloc[-1], turnover_total, return_ratio]
    cols = ["close", "turnover", "return_ratio"]

    # 自訂 item（如果跟預設不同）
    if item not in ("return_ratio", "turnover_ratio"):
        try:
            custom = _df_date_filter(data.get(item), start, end).iloc[-1].fillna(0)
            if clip is not None and clip > 0:
                custom = custom.clip(-clip, clip)
            parts.append(custom)
            cols.append("item_value")
        except Exception as e:
            raise ValueError(f"抓不到 finlab 指標 `{item}`：{e}")

    df = pd.concat(parts, axis=1).dropna()
    df.columns = cols
    # index 是 stock_id（column 名），reset_index 後變成 column
    df = df.reset_index()
    # 找第一個欄位（reset_index 帶出來的）改名成 stock_id
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "stock_id"})

    # 對齊 stock_id 型別（basic_info 是字串 "1101"、price 是 int 1101）
    df["stock_id"] = df["stock_id"].astype(str)

    # 合併公司基本資料
    bi = basic.copy()
    bi["stock_id"] = bi["stock_id"].astype(str)
    bi["name"] = bi["公司簡稱"]
    bi["category"] = bi["產業類別"].fillna("其他")
    bi["market"] = bi["市場別"].fillna("其他")
    bi["base"] = pd.to_numeric(bi["實收資本額(元)"], errors="coerce")

    df = df.merge(
        bi[["stock_id", "name", "category", "market", "base"]],
        on="stock_id",
        how="left",
    )

    # 排除沒對到公司資料的（ETF / 權證 / 債券，basic_info 沒有）
    if exclude_etf:
        df = df.dropna(subset=["name", "category", "market", "base"])
    else:
        df["name"] = df["name"].fillna(df["stock_id"])
        df["category"] = df["category"].fillna("其他")
        df["market"] = df["market"].fillna("其他")
        df["base"] = df["base"].fillna(0)

    # 排除低價股（容易把 treemap 拉爆）
    if exclude_penny:
        df = df[df["close"] >= penny_threshold]

    # 市值（億）= 實收資本額 / 10 * 收盤價 / 1e8
    df["market_value"] = round(df["base"] / 10 * df["close"] / 1e8, 2)
    # 排除市值 <= 0 的（資本額沒抓到）
    df = df[df["market_value"] > 0]

    # 成交佔比 %
    total_turnover = df["turnover"].sum()
    if total_turnover > 0:
        df["turnover_ratio"] = df["turnover"] / total_turnover * 100
    else:
        df["turnover_ratio"] = 0

    # 若有 item_value（自訂指標），做 clip
    if "item_value" in df.columns and clip is not None and clip > 0:
        df["item_value"] = df["item_value"].clip(-clip, clip)
        df["item_label"] = df["item_value"].round(2).astype(str)
    else:
        # 預設 return_ratio
        df["item_value"] = df["return_ratio"].clip(-clip, clip)
        df["item_label"] = df["return_ratio"].round(2).astype(str)

    df["country"] = "TW-Stock"
    # 標籤：股票代號 + 簡稱
    df["stock_id_name"] = df["stock_id"] + " " + df["name"]
    return df


# === 繪圖 ===
def plot_treemap(
    start: str = None,
    end: str = None,
    area_ind: str = DEFAULT_AREA,
    item: str = DEFAULT_ITEM,
    clip: float = DEFAULT_CLIP,
    color_scales: str = DEFAULT_COLORS,
    exclude_etf: bool = DEFAULT_EXCLUDE_ETF,
    exclude_penny: bool = True,
    width: int = 1600,
    height: int = 800,
) -> tuple[pd.DataFrame, go.Figure]:
    """
    畫台股 treemap。

    Returns
    -------
    (df, fig)：回傳資料跟 plotly figure，方便後續在 Streamlit / notebook 顯示
    """
    # 防呆：start > end 自動對調（保證 title 跟後續邏輯都用對調後的日期）
    if start and end and pd.Timestamp(start) > pd.Timestamp(end):
        start, end = end, start

    df = build_treemap_data(
        start=start,
        end=end,
        item=item,
        clip=clip,
        exclude_etf=exclude_etf,
        exclude_penny=exclude_penny,
    )

    if len(df) == 0:
        raise ValueError("沒有資料，請檢查日期範圍或排除條件")

    # color_continuous_midpoint
    if item == "return_ratio" or item == "turnover_ratio":
        midpoint = 0
    else:
        weights = df[area_ind].values if area_ind in df.columns else None
        if weights is not None and weights.sum() > 0:
            midpoint = float(np.average(df["item_value"], weights=weights))
        else:
            midpoint = float(df["item_value"].mean())

    fig = px.treemap(
        df,
        path=["country", "market", "category", "stock_id_name"],
        values=area_ind,
        color="item_value",
        color_continuous_scale=color_scales,
        color_continuous_midpoint=midpoint,
        custom_data=["item_label", "close", "turnover", "name", "category", "market"],
        title=(
            f"TW-Stock Market TreeMap ({start or 'auto'} ~ {end or 'auto'})"
            f" — area: {area_ind} | color: {item} | {len(df)} 檔"
        ),
        width=width,
        height=height,
    )

    fig.update_traces(
        textposition="middle center",
        textfont_size=18,
        texttemplate="%{label}<br>%{customdata[0]}%",
        hovertemplate=(
            "<b>%{label}</b><br>"
            "漲跌: %{customdata[0]}%<br>"
            "收盤: %{customdata[1]:.2f}<br>"
            "成交金額: %{customdata[2]:,.0f} 億<br>"
            "產業: %{customdata[4]}<br>"
            "市場: %{customdata[5]}"
            "<extra></extra>"
        ),
    )
    return df, fig


# === Streamlit 顯示 helper ===
def render_summary_stats(df: pd.DataFrame) -> dict:
    """
    計算簡單統計：上漲 / 下跌家數、平均漲跌、市值總和
    """
    up = int((df["return_ratio"] > 0).sum())
    down = int((df["return_ratio"] < 0).sum())
    flat = int((df["return_ratio"] == 0).sum())
    avg_return = float(df["return_ratio"].mean())
    total_mv = float(df["market_value"].sum())
    return {
        "上漲": up,
        "下跌": down,
        "持平": flat,
        "家數": len(df),
        "平均漲跌%": round(avg_return, 2),
        "總市值(億)": round(total_mv, 0),
    }
