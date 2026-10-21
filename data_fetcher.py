#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
data_fetcher.py — FinLab 抓台/港股日線資料（OHLCV）
"""
from __future__ import annotations


# ============================================================
# 港股熱門股清單 (finlab 沒有港股名稱字典, 只能 hardcode)
# ============================================================
HK_STOCK_NAMES = {
    # === 港股權值股 / 藍籌 ===
    "0700.HK": "騰訊控股",
    "9988.HK": "阿里巴巴",
    "3690.HK": "美團",
    "1810.HK": "小米集團",
    "0388.HK": "香港交易所",
    "1211.HK": "比亞迪股份",
    "9618.HK": "京東集團",
    "0941.HK": "中國移動",
    "9999.HK": "網易",
    "2318.HK": "中國平安",
    "1398.HK": "工商銀行",
    "0939.HK": "建設銀行",
    "0005.HK": "滙豐控股",
    "1299.HK": "友邦保險",
    "0883.HK": "中國海洋石油",
    "0857.HK": "中國石油股份",
    "2628.HK": "中國人壽",
    "0175.HK": "吉利汽車",
    "9992.HK": "泡泡瑪特",
    "1024.HK": "快手",
    "9616.HK": "東軟睿新",
    "2269.HK": "藥明生物",
    "2020.HK": "安踏體育",
    "0027.HK": "銀河娛樂",
    "0016.HK": "新鴻基地產",
    "0001.HK": "長和",
    "0002.HK": "中電控股",
    "0003.HK": "香港中華煤氣",
    "0011.HK": "恒生銀行",
    "0012.HK": "恒基地產",
    "0017.HK": "新世界發展",
    "0823.HK": "領展房託",
    "0066.HK": "港鐵公司",
    "0386.HK": "中國石油化工股份",
    "0688.HK": "中國海外發展",
    "0267.HK": "中信股份",
    "0006.HK": "電能實業",
    "0019.HK": "太古股份",
    # === 港股槓桿 / 反向 / 個股 ETF（finlab hk_price 7xxx 系列）===
    "7709.HK": "南方東英海力士正2",  # SK Hynix 2x Long
    "7588.HK": "南方東英恆生科技",  # 恆生科技 ETF
    "7489.HK": "南方東英黃金",  # 黃金 ETF
    "7226.HK": "恒生中國企業 ETF",
    "7261.HK": "華夏恆生科技",
    "7618.HK": "南方東英美國納指",
    "7630.HK": "南方東英恆指 ETF",
    "7656.HK": "南方東英恆生科技",
    "7666.HK": "南方東英恆生科技",
    "7687.HK": "南方東英美股 2x",
    "7688.HK": "南方東英美股反向",
    "7827.HK": "南方東英恆生科技 2x",
}


def _is_hk_stock(stock_id: str) -> bool:
    """判斷是否港股 (代號含 .HK)"""
    return ".HK" in str(stock_id).upper()


def get_hk_stock_name(stock_id: str) -> str:
    """查港股名稱, 找不到回 stock_id"""
    s = str(stock_id).strip().upper()
    return HK_STOCK_NAMES.get(s, stock_id)


# 中文名稱從 `security_categories` 拿（memory 裡有記）

import os
from pathlib import Path
import pandas as pd
from typing import Optional


def _finlab_env_creds() -> Optional[dict]:
    """
    取得 FinLab 三憑證 (REFRESH_TOKEN / SESSION_ID / API_KEY)。

    優先順序：
        1. Streamlit Cloud secrets
        2. 環境變數
        3. None（本機走 credentials.json / 互動登入）

    FinLab 2.2.13+ 已棄用舊版 api_token，改用瀏覽器 OAuth。
    官方文件：無瀏覽器環境（伺服器、排程）請執行
    `python -m finlab token --env` 產生這三個變數。
    """
    keys = ("FINLAB_REFRESH_TOKEN", "FINLAB_SESSION_ID", "FINLAB_API_KEY")

    # 1. Streamlit Cloud secrets
    try:
        import streamlit as st
        vals = {}
        for k in keys:
            v = st.secrets.get(k, None)
            if v:
                vals[k] = str(v)
        if len(vals) == 3:
            return vals
    except Exception:
        pass

    # 2. 環境變數
    vals = {}
    for k in keys:
        v = os.environ.get(k)
        if v:
            vals[k] = v
    if len(vals) == 3:
        return vals

    return None


def ensure_finlab_login():
    """
    統一 finlab login 入口（所有 page 都呼叫這個）。

    FinLab 2.2.13+ 認證順序：
        1. 三憑證（st.secrets 或環境變數）— 雲端/排程用
        2. ~/.finlab/credentials.json — 本機 OAuth 登入後自動產生
        3. finlab.login() 互動登入 — 首次本機使用
    """
    import finlab

    # 1. 三憑證（雲端部署）
    creds = _finlab_env_creds()
    if creds:
        os.environ.update(creds)
        return  # finlab 會自動讀環境變數

    # 2. credentials.json（finlab 2.x 自動讀）
    cred_path = Path.home() / ".finlab" / "credentials.json"
    if cred_path.exists():
        return

    # 3. 互動登入
    try:
        finlab.login()
    except Exception as e:
        raise RuntimeError(
            "FinLab 登入失敗。請確認以下其中一種方式：\n"
            "  1. 本機：執行 python -m finlab token --env 產生憑證，"
            "或執行 python -c 'import finlab; finlab.login()' 瀏覽器登入\n"
            "  2. Streamlit Cloud：在 Settings → Secrets 設定 "
            "FINLAB_REFRESH_TOKEN / FINLAB_SESSION_ID / FINLAB_API_KEY\n"
            f"\n原始錯誤：{e}"
        )


# === 舊版相容入口（有些模組 import 這個） ===
def _ensure_login():
    ensure_finlab_login()


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
    stock_id : 例如 "2330" / "0050" / "6488" / "0700.HK" / "9988.HK"
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

    港股 (代號含 ".HK"): 兩組 universe
        - `hk_fund_price:adj_*` (150 檔 ETF/槓桿/反向/個股 ETF, 如 7709.HK 南方東英海力士正2, 230 筆 2025-11-10 起)
        - `hk_price:adj_*` (2976 檔普通港股個股, 如 0700.HK 騰訊, 完整 2016-01-04 起)
        策略: 先查 fund_price, 沒再 fallback 到 price。
        ⚠️ 必須先 `data.set_market('hk')` + `data.reset_universe()` 才能查到 fund_price
        ⚠️ 對 fund_price 用 `force_download=True` 避免 finlab 內部 cache 殘留舊 1 筆結果
    """
    from finlab import data

    # 港股 → 優先 hk_fund_price (ETF/槓桿/反向), fallback hk_price (普通個股)
    if _is_hk_stock(stock_id):
        sid = str(stock_id).strip().upper()

        # 確保 finlab 切到港股市場 + reset universe (必要才能載到 hk_fund_price)
        try:
            data.set_market('hk')
            data.reset_universe()
        except Exception as e:
            print(f"[fetch_ohlcv] set_market/reset_universe 失敗: {e}")

        # 1) 優先 hk_fund_price (港股 ETF/槓桿/反向/個股 ETF)
        #    force_download=True 強制重抓，避免 finlab 內部 cache 殘留舊的 1 筆結果
        try:
            fund_close_wide = data.get("hk_fund_price:adj_close", force_download=True)
            print(f"[fetch_ohlcv] {sid} hk_fund_price:adj_close shape: {fund_close_wide.shape}, {sid} in cols: {sid in fund_close_wide.columns}")
            if sid in fund_close_wide.columns:
                close = fund_close_wide[sid].dropna().tail(days)
                print(f"[fetch_ohlcv] {sid} fund close 筆數: {len(close)}")
                if len(close) > 0:
                    open_w = data.get("hk_fund_price:adj_open", force_download=True)[sid].reindex(close.index)
                    high_w = data.get("hk_fund_price:adj_high", force_download=True)[sid].reindex(close.index)
                    low_w = data.get("hk_fund_price:adj_low", force_download=True)[sid].reindex(close.index)
                    try:
                        vol_w = data.get("hk_fund_price:volume", force_download=True)[sid].reindex(close.index)
                    except Exception:
                        vol_w = pd.Series([0] * len(close), index=close.index)
                    df = pd.DataFrame({
                        "close": close.values,
                        "open": open_w.values,
                        "high": high_w.values,
                        "low": low_w.values,
                        "volume": vol_w.values,
                    }, index=pd.to_datetime(close.index))
                    print(f"[fetch_ohlcv] {sid} ✅ fund_price 拿到 {len(df)} 筆, 起始 {df.index.min()}, 末值 {df['close'].iloc[-1]:.2f}")
                    return df.dropna(subset=["close"])
        except Exception as e:
            print(f"[fetch_ohlcv] {sid} hk_fund_price 失敗, fallback 到 hk_price: {e}")

        # 2) fallback hk_price (港股普通個股)
        try:
            close_wide = data.get("hk_price:adj_close", force_download=True)
            print(f"[fetch_ohlcv] {sid} fallback hk_price:adj_close shape: {close_wide.shape}, {sid} in cols: {sid in close_wide.columns}")
        except Exception:
            close_wide = data.get("hk_price:adj_close")
        if sid not in close_wide.columns:
            raise ValueError(f"找不到 {sid} 的港股價格資料（不在 fund_price 150 檔 + price {len(close_wide.columns)} 檔清單內）")
        close = close_wide[sid].dropna().tail(days)
        try:
            open_w = data.get("hk_price:adj_open", force_download=True)[sid].reindex(close.index)
            high_w = data.get("hk_price:adj_high", force_download=True)[sid].reindex(close.index)
            low_w = data.get("hk_price:adj_low", force_download=True)[sid].reindex(close.index)
        except Exception:
            open_w = data.get("hk_price:adj_open")[sid].reindex(close.index)
            high_w = data.get("hk_price:adj_high")[sid].reindex(close.index)
            low_w = data.get("hk_price:adj_low")[sid].reindex(close.index)
        try:
            vol_w = data.get("hk_price:volume")[sid].reindex(close.index)
        except Exception:
            vol_w = pd.Series([0] * len(close), index=close.index)
        df = pd.DataFrame({
            "close": close.values,
            "open": open_w.values,
            "high": high_w.values,
            "low": low_w.values,
            "volume": vol_w.values,
        }, index=pd.to_datetime(close.index))
        print(f"[fetch_ohlcv] {sid} ⚠️ price 拿到 {len(df)} 筆, 末值 {df['close'].iloc[-1]:.2f}")
        return df.dropna(subset=["close"])

    # 台股 (原本邏輯)
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
    """查中文名稱 (台股從 finlab name dict, 港股從 HK_STOCK_NAMES), 找不到就回 stock_id"""
    if _is_hk_stock(stock_id):
        return get_hk_stock_name(stock_id)
    sid = _to_short_id(stock_id)
    mapping = get_stock_name_map()
    return mapping.get(sid, stock_id)
