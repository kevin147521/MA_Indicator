#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
data_fetcher.py — FinLab 抓台股日線資料（OHLCV）

注意：
- 使用 finlab_data 的 data.get()，會走快取（feather），同一支股票重複拉很快
- 統一用 `session` 簡稱當 stock_id 欄位（FinLab 已經是這個格式）
- 中文名稱從 `security_categories` 拿（memory 裡有記）
"""
from __future__ import annotations

import os
from pathlib import Path
import pandas as pd
from typing import Optional


def ensure_finlab_login():
    """
    統一 finlab login 入口（所有 page 都呼叫這個）。

    順序（雲端/本地都通用）：
        1. finlab_config 模組（自定，本地常用）
        2. st.secrets["FINLAB_API_TOKEN"]（Streamlit Cloud 設定）
        3. os.environ["FINLAB_API_TOKEN"]（環境變數）
        4. ~/.finlab/credentials.json（finlab 2.x 自動寫，自動讀）
        5. finlab.login() 互動登入（fallback）
    """
    import finlab

    # 1. finlab_config 模組
    try:
        from finlab_config import login_finlab
        login_finlab()
        return
    except ImportError:
        pass

    # 2. Streamlit Cloud secrets
    try:
        import streamlit as st
        if "FINLAB_API_TOKEN" in st.secrets:
            finlab.login(api_token=st.secrets["FINLAB_API_TOKEN"])
            return
    except Exception:
        pass

    # 3. 環境變數
    token = os.environ.get("FINLAB_API_TOKEN")
    if token:
        finlab.login(api_token=token)
        return

    # 4. credentials.json（finlab 2.x 自動讀）
    cred_path = Path.home() / ".finlab" / "credentials.json"
    if cred_path.exists():
        # finlab 2.x 自動讀這個檔
        return

    # 5. 互動登入
    try:
        finlab.login()
    except Exception as e:
        raise RuntimeError(
            "找不到任何 finlab login 方式（finlab_config / "
            "st.secrets / FINLAB_API_TOKEN / ~/.finlab/credentials.json）："
            f"{e}"
        )


# === FinLab login（沿用統一入口） ===
def _ensure_login():
    try:
        from finlab_config import login_finlab
        login_finlab()
    except ImportError:
        # 沒有 finlab_config 就自己走硬編碼 / 環境變數
        import os
        import finlab
        token = os.environ.get("FINLAB_API_TOKEN")
        if token:
            finlab.login(api_token=token)
        else:
            # 沒 token 就 raise 給上層
            raise RuntimeError(
                "找不到 FINLAB_API_TOKEN 環境變數，也沒有 finlab_config 模組。"
                "請在 ~/.finlab/credentials.json 設定或 export FINLAB_API_TOKEN。"
            )


def get_stock_name_map() -> dict[str, str]:
    """
    回傳 {stock_id: 中文簡稱}，排除興櫃（rotc）。
    包含 ETF / 權證 / 債券 ETF 等衍生商品。
    """
    from finlab import data
    cat = data.get("security_categories")
    cat = cat[cat["market"] != "rotc"]
    return dict(zip(cat["stock_id"], cat["name"]))


def get_all_securities() -> pd.DataFrame:
    """
    回傳全市場標的清單（排除興櫃），含中文簡稱與 market。

    Columns: stock_id, name, market, category
    用途：app.py 做成「全市場搜尋」下拉。
    """
    from finlab import data
    cat = data.get("security_categories")
    cat = cat[cat["market"] != "rotc"].copy()
    # 整理欄位順序
    cols = [c for c in ["stock_id", "name", "market", "category"] if c in cat.columns]
    return cat[cols].reset_index(drop=True)


def fetch_ohlcv(stock_id: str, days: int = 120) -> pd.DataFrame:
    """
    抓取指定股票近 N 個交易日的 OHLCV。

    Parameters
    ----------
    stock_id : 例如 "2330" / "0050" / "6488"
    days : 取最近幾個交易日

    Returns
    -------
    DataFrame index=date, columns=[open, high, low, close, volume]

    Note:
        FinLab 兩種索引規則要注意：
        1. `data.get("price:*")` wide DF 欄位名是**純數字**（如 "2330"）
        2. `data.get("price:*", sid)` 帶前綴呼叫也可以（"tse_2330" / "otc_6488"）
        3. `security_categories` 也是**純數字**
        統一在內部轉成純數字處理。
    """
    from finlab import data

    # 統一轉成純數字
    sid_short = _to_short_id(stock_id)

    # wide DF 抓整個市場，再取單欄
    close_wide = data.get("price:收盤價")
    if sid_short not in close_wide.columns:
        raise ValueError(f"找不到 {sid_short} 的價格資料（不在 {len(close_wide.columns)} 檔清單內）")
    close = close_wide[sid_short].dropna().tail(days)

    open_w = data.get("price:開盤價")[sid_short].reindex(close.index)
    high_w = data.get("price:最高價")[sid_short].reindex(close.index)
    low_w = data.get("price:最低價")[sid_short].reindex(close.index)
    vol_w = data.get("price:成交股數")[sid_short].reindex(close.index)

    df = pd.DataFrame({
        "close": close.values,
        "open": open_w.values,
        "high": high_w.values,
        "low": low_w.values,
        "volume": vol_w.values,
    }, index=pd.to_datetime(close.index))
    df = df.dropna(subset=["close"])
    return df


def _to_short_id(stock_id: str) -> str:
    """把 'tse_2330' / 'otc_6488' / '2330' 統一變 '2330' / '6488'"""
    s = str(stock_id).strip()
    if "_" in s:
        s = s.split("_", 1)[-1]
    return s


def get_stock_name(stock_id: str) -> str:
    """查中文名稱，找不到就回 stock_id"""
    sid = _to_short_id(stock_id)
    mapping = get_stock_name_map()
    return mapping.get(sid, stock_id)
