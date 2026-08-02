#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
margin_page.py — 台股大盤融資維持率趨勢圖

參考 /Users/kevin/Desktop/雜項研究/maintenance_margin.ipynb Cell 5

核心公式：
    融資維持率 = (融資今日餘額 × 收盤價 × 1000).sum() / (上市融資交易金額 + 上櫃融資交易金額)

子圖：
    Row 1: 融資維持率 (line + 10MA) + 大盤指數 (次座標)
    Row 2: 上市融資餘額 (area) + 上市融資買賣超 (紅綠 bar, 次座標)
    Row 3: 上櫃融資餘額 (area) + 上櫃融資買賣超 (紅綠 bar, 次座標)
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_margin_data(
    start: str = None,
    end: str = None,
    ma_window: int = 10,
) -> dict:
    """
    抓融資相關資料 + 計算各指標。
    """
    from data_fetcher import ensure_finlab_login
    ensure_finlab_login()

    from finlab import data

    margin = data.get("margin_transactions:融資今日餘額")
    balance_raw = data.get("margin_balance:融資券總餘額")
    close = data.get("price:收盤價")

    # 對齊 index
    balance = balance_raw.loc[margin.index.intersection(balance_raw.index)].copy()

    # 上市/上櫃 融資買賣超（億）
    balance["上市融資買賣超"] = (
        (balance["上市融資交易金額"] - balance["上市融資交易金額"].shift()).fillna(0) / 1e8
    )
    balance["上櫃融資買賣超"] = (
        (balance["上櫃融資交易金額"] - balance["上櫃融資交易金額"].shift()).fillna(0) / 1e8
    )

    # 大盤指數
    benchmark = data.get("market_transaction_info:收盤指數")["TAIEX"].squeeze()

    # 融資總餘額（金額）
    margin_total_amount = balance[["上市融資交易金額", "上櫃融資交易金額"]].sum(axis=1)
    # 融資餘額市值（融資張數 × 收盤價 × 1000）
    margin_market_value = (margin * close * 1000).sum(axis=1)
    # 維持率
    margin_rate = margin_market_value / margin_total_amount

    # 過濾日期（如果 start > end 自動對調，避免 plotly 噴 index out of bounds）
    if start and end and pd.Timestamp(start) > pd.Timestamp(end):
        start, end = end, start
    if start:
        margin_rate = margin_rate.loc[margin_rate.index >= pd.Timestamp(start)]
        margin_total_amount = margin_total_amount.loc[margin_total_amount.index >= pd.Timestamp(start)]
        benchmark = benchmark.loc[benchmark.index >= pd.Timestamp(start)]
        balance = balance.loc[balance.index >= pd.Timestamp(start)]
    if end:
        margin_rate = margin_rate.loc[margin_rate.index <= pd.Timestamp(end)]
        margin_total_amount = margin_total_amount.loc[margin_total_amount.index <= pd.Timestamp(end)]
        benchmark = benchmark.loc[benchmark.index <= pd.Timestamp(end)]
        balance = balance.loc[balance.index <= pd.Timestamp(end)]

    return {
        "margin_rate": margin_rate,
        "margin_rate_ma": margin_rate.rolling(ma_window).mean(),
        "benchmark": benchmark,
        "balance": balance,
        "tse_balance": balance["上市融資交易金額"],
        "otc_balance": balance["上櫃融資交易金額"],
        "tse_balance_change": balance["上市融資買賣超"],
        "otc_balance_change": balance["上櫃融資買賣超"],
    }


def plot_margin_trend(
    start: str = None,
    end: str = None,
    ma_window: int = 10,
    width: int = 1500,
    height: int = 800,
) -> go.Figure:
    """
    畫融資維持率 + 上市/上櫃融資餘額 + 買賣超 三層圖。
    """
    # 防呆：start > end 自動對調（跟 treemap_page.py 一致）
    if start and end and pd.Timestamp(start) > pd.Timestamp(end):
        start, end = end, start

    data = build_margin_data(start=start, end=end, ma_window=ma_window)

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": True}],
            [{"secondary_y": True}],
        ],
        subplot_titles=(
            "融資維持率",
            "上市融資餘額",
            "上櫃融資餘額",
        ),
    )

    date_index = data["margin_rate"].index
    benchmark_values = data["benchmark"].reindex(date_index)

    # Row 1: 維持率 + 大盤
    fig.add_trace(
        go.Scatter(
            x=date_index, y=benchmark_values,
            name="台灣加權指數",
            line=dict(width=3, color="navy"),
        ),
        secondary_y=False, row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=date_index, y=data["margin_rate"].values,
            name="融資維持率",
            line=dict(color="orange"),
        ),
        secondary_y=True, row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=date_index, y=data["margin_rate_ma"].values,
            name=f"融資維持率_MA{ma_window}",
            line=dict(color="red", width=2),
        ),
        secondary_y=True, row=1, col=1,
    )

    # Row 2: 上市融資餘額 + 買賣超
    fig.add_trace(
        go.Scatter(
            x=date_index, y=data["tse_balance"],
            fill="tozeroy",
            line=dict(width=0.5, color="#efd267"),
            name="上市融資餘額",
        ),
        secondary_y=False, row=2, col=1,
    )
    fig.add_trace(
        go.Bar(
            x=date_index, y=data["tse_balance_change"],
            marker_color=data["tse_balance_change"].apply(
                lambda s: "red" if s > 0 else "green"
            ),
            name="上市融資買賣超",
            opacity=0.6,
        ),
        secondary_y=True, row=2, col=1,
    )

    # Row 3: 上櫃融資餘額 + 買賣超
    fig.add_trace(
        go.Scatter(
            x=date_index, y=data["otc_balance"],
            fill="tozeroy",
            line=dict(width=0.5, color="#efd267"),
            name="上櫃融資餘額",
        ),
        secondary_y=False, row=3, col=1,
    )
    fig.add_trace(
        go.Bar(
            x=date_index, y=data["otc_balance_change"],
            marker_color=data["otc_balance_change"].apply(
                lambda s: "red" if s > 0 else "green"
            ),
            name="上櫃融資買賣超",
            opacity=0.6,
        ),
        secondary_y=True, row=3, col=1,
    )

    # 隱藏假日空日期
    from finlab import data as _data
    close = _data.get("price:收盤價")
    dt_all = pd.date_range(start=date_index[0], end=date_index[-1])
    dt_obs = [d.strftime("%Y-%m-%d") for d in pd.to_datetime(close.index)]
    dt_breaks = [d for d in dt_all.strftime("%Y-%m-%d").tolist() if d not in dt_obs]
    fig.update_xaxes(rangebreaks=[dict(values=dt_breaks)])

    fig.update_layout(
        width=width,
        height=height,
        title="台股大盤融資指標",
        title_font_color="navy",
        title_font_size=20,
        hovermode="x unified",
        yaxis=dict(title="台股大盤指數", showgrid=False),
        yaxis2=dict(title="融資維持率"),
        yaxis3=dict(title="上市融資累計餘額", showgrid=False),
        yaxis4=dict(title="買賣超(億)"),
        yaxis5=dict(title="上櫃融資累計餘額", showgrid=False),
        yaxis6=dict(title="買賣超(億)"),
        showlegend=True,
        xaxis=dict(
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(count=1, label="YTD", step="year", stepmode="todate"),
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(count=3, label="3y", step="year", stepmode="backward"),
                    dict(step="all"),
                ])
            ),
            type="date",
        ),
        xaxis2=dict(type="date"),
        xaxis3=dict(
            rangeslider=dict(visible=True),
            type="date",
        ),
    )
    return fig


def render_margin_summary(start: str = None, end: str = None) -> dict:
    """
    簡單統計：最新維持率、距離 130% 警戒線、買賣超方向。
    """
    data = build_margin_data(start=start, end=end)
    rate = data["margin_rate"].dropna()
    if len(rate) == 0:
        return {}

    last_rate = float(rate.iloc[-1])
    last_date = rate.index[-1]
    last_balance = float(data["tse_balance"].iloc[-1] + data["otc_balance"].iloc[-1])
    last_tse_chg = float(data["tse_balance_change"].iloc[-1])
    last_otc_chg = float(data["otc_balance_change"].iloc[-1])

    return {
        "最新維持率": round(last_rate * 100, 2),
        "最新日期": last_date.strftime("%Y-%m-%d"),
        "距離130%": round((last_rate * 100) - 130, 2),
        "總融資餘額(億)": round(last_balance / 1e8, 0),
        "上市買賣超(億)": round(last_tse_chg, 2),
        "上櫃買賣超(億)": round(last_otc_chg, 2),
    }
