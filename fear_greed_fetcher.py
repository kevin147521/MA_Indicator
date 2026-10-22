#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
fear_greed_fetcher.py — Fear & Greed Index 資料抓取 + 計算

資料來源
--------
1. 美國 FGI + 組件分解 : CNN 官方 API
   https://production.dataviz.cnn.io/index/fearandgreed/graphdata
   （免註冊、免 key、JSON 回傳 252 筆歷史 + 10 個組件）
2. 四大指數 + VIX     : FinLab `world_index:close`
   - ^GSPC   S&P 500
   - ^TWII   台灣加權指數
   - ^N225   日本日經 225
   - ^KS11   韓國 KOSPI
   - ^VIX    恐慌指數（台日韓用各自本國波動率替代）

台/日/韓 FGI：CNN 沒有官方版本，用與 CNN 同架構的 5 組件模型自算
（每組件等權重 20%，每個組件內再各自 map 到 0-100）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# 常數設定
# ============================================================
DATA_DIR = Path(__file__).resolve().parent / "data" / "fear_greed"
FGI_HISTORY_FILE = DATA_DIR / "fgi_history.parquet"
COMPONENT_FILE = DATA_DIR / "fgi_components.parquet"
INDEX_FILE = DATA_DIR / "index_levels.parquet"

START_DATE = "2026-01-02"

# ★ 台/日/韓 FGI 是滾動百分位，需要往前多抓至少 window 天才有 2026-01-02 的值
#   FGI 顯示起點仍為 START_DATE，但計算用的指數要多抓一年
WARMUP_DAYS = 400  # ≈ 1.1 年，扣掉 120 日窗口仍足夠涵蓋 2026-01-02
WARMUP_START = "2024-12-01"

CNN_GRAPH_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.cnn.com",
    "Referer": "https://www.cnn.com/",
}

# 市場定義：(顯示名, 中文名, finlab world_index 代號, 顏色)
MARKETS = {
    "US": {"label": "美國 S&P 500", "cn": "美國", "idx": "^GSPC", "color": "#E8453C"},
    "TW": {"label": "台灣 加權指數", "cn": "台灣", "idx": "^TWII", "color": "#1F77B4"},
    "KR": {"label": "韓國 KOSPI", "cn": "韓國", "idx": "^KS11", "color": "#7D3C98"},
    "JP": {"label": "日本 日經225", "cn": "日本", "idx": "^N225", "color": "#E6890C"},
}

# FGI 分級門檻（跟 CNN 一致）
FGI_BANDS = [
    (0, 24, "Extreme Fear", "極度恐慌"),
    (25, 44, "Fear", "恐慌"),
    (45, 55, "Neutral", "中立"),
    (56, 74, "Greed", "貪婪"),
    (75, 100, "Extreme Greed", "極度貪婪"),
]


# ============================================================
# 工具函式
# ============================================================
def fgi_to_rating(score: float) -> tuple[str, str]:
    """FGI 分數 → (英文 rating, 中文 rating)"""
    if pd.isna(score):
        return "—", "—"
    for lo, hi, en, cn in FGI_BANDS:
        if lo <= score <= hi:
            return en, cn
    return "—", "—"


def fgi_to_color(score: float) -> str:
    """FGI 分數 → 顏色（綠=恐慌 / 紅=貪婪）"""
    if pd.isna(score):
        return "#9E9E9E"
    if score <= 24:
        return "#C0392B"
    if score <= 44:
        return "#E67E22"
    if score <= 55:
        return "#F1C40F"
    if score <= 74:
        return "#8BC34A"
    return "#27AE60"


def _rank_pct(series: pd.Series, ascending: bool = True) -> pd.Series:
    """把 series 轉成 0-100 的百分位分數"""
    r = series.rank(pct=True, ascending=ascending)
    return (r * 100).clip(0, 100)


def _rolling_percentile(series: pd.Series, window: int = 250,
                        ascending: bool = True,
                        min_periods: int = 20) -> pd.Series:
    """滾動窗口百分位（用來算 volatility / momentum 之類）"""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    vals = series.values
    n = len(vals)
    for i in range(n):
        lo = max(0, i - window + 1)
        w = vals[lo:i + 1]
        w = w[~np.isnan(w)]
        if len(w) < min_periods or np.isnan(vals[i]):
            continue
        if ascending:
            pct = (w <= vals[i]).sum() / len(w) * 100
        else:
            pct = (w >= vals[i]).sum() / len(w) * 100
        out.iloc[i] = pct
    return out


# ============================================================
# 1) CNN 官方 FGI（美國）+ 組件
# ============================================================
# CNN 10 個組件 key → 中文名 / 短名
CNN_COMPONENTS = {
    "market_momentum_sp500": ("市場動能", "動能"),
    "market_momentum_sp125": ("動能(125日)", "動能125"),
    "stock_price_strength": ("股價強度", "強度"),
    "stock_price_breadth": ("股價廣度", "廣度"),
    "put_call_options": ("_put/Call 比率", "PutCall"),
    "market_volatility_vix": ("市場波動(VIX)", "波動"),
    "market_volatility_vix_50": ("波動(VIX 50日)", "波動50"),
    "junk_bond_demand": ("垃圾債需求", "垃圾債"),
    "safe_haven_demand": ("避險需求", "避險"),
}


def fetch_cnn_fgi() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """
    抓 CNN 官方 Fear & Greed Index（美國）+ 各組件歷史 + S&P500 價格序列。

    ★ 為什麼要多回傳 S&P500：
        finlab `world_index:close` 的 ^GSPC 有 T+1 延遲（例如今天 00:49 只到昨天收盤），
        但 CNN 自己的 `market_momentum_sp500` 已經帶今天盤中/收盤價。
        拿 CNN 的當美股即時來源，畫圖/表格才不會慢一拍。

    Returns
    -------
    (fgi_df, comp_df, sp500)
        fgi_df : index=date, columns=[score, rating]
        comp_df: index=date, columns=[組件中文短名, ...] 每組件 0-100
        sp500  : index=date, values=float — CNN 來源的 S&P500 收盤價
    """
    import requests

    r = requests.get(CNN_GRAPH_URL, headers=CNN_HEADERS, timeout=30)
    r.raise_for_status()
    payload = r.json()

    # --- FGI 總分歷史 ---
    hist = payload.get("fear_and_greed_historical", {})
    rows = hist.get("data", [])
    fgi_df = pd.DataFrame(
        {
            "score": [p.get("y") for p in rows],
            "rating": [p.get("rating") for p in rows],
        },
        index=pd.to_datetime([p["x"] for p in rows], unit="ms", utc=True)
        .tz_localize(None)
        .normalize(),  # x 已是 UTC，直接取日期
    )
    fgi_df = fgi_df[~fgi_df.index.duplicated(keep="last")].sort_index()
    fgi_df.index.name = "date"

    # --- 各組件歷史 ---
    comp_dict = {}
    for key, (cn_name, short_name) in CNN_COMPONENTS.items():
        blk = payload.get(key)
        if not blk:
            continue
        pts = blk.get("data", [])
        if not pts:
            continue
        idx = (
            pd.to_datetime([p["x"] for p in pts], unit="ms", utc=True)
            .tz_localize(None)
            .normalize()  # x 已是 UTC
        )
        s = pd.Series([p.get("y") for p in pts], index=idx, name=short_name)
        s = s[~s.index.duplicated(keep="last")]
        comp_dict[short_name] = s

    comp_df = pd.DataFrame(comp_dict).sort_index()
    comp_df.index.name = "date"

    # --- CNN 來源的 S&P500 價格（比 finlab 即時，win=用來覆蓋 ^GSPC）---
    sp500 = pd.Series(dtype=float, name="^GSPC")
    mm = payload.get("market_momentum_sp500", {})
    pts = mm.get("data", [])
    if pts:
        sp_idx = (
            pd.to_datetime([p["x"] for p in pts], unit="ms", utc=True)
            .tz_localize(None)
            .normalize()  # x 已是 UTC
        )
        sp500 = pd.Series([p.get("y") for p in pts], index=sp_idx, name="^GSPC")
        sp500 = sp500[~sp500.index.duplicated(keep="last")].sort_index()
        sp500 = sp500[sp500 > 0]  # 濾掉 API 偶發的 0 值

    return fgi_df, comp_df, sp500


# ============================================================
# 2) 指數水位（FinLab world_index）
# ============================================================
def fetch_index_levels(start: str = WARMUP_START) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    抓四大指數 + VIX 水位 + 各指數成交量。

    ★ start 預設給 WARMUP_START（2024-12-01），比顯示區間早，
      讓 120 日滾動百分位在 2026-01-02 就已有值。

    Returns (close_df, volume_df)
        close_df : index=date, columns=[^GSPC, ^TWII, ^N225, ^KS11, ^VIX]
        volume_df: index=date, columns=[^TWII, ^N225, ^KS11] (量能組件用)
    """
    from finlab import data

    widx = data.get("world_index:close")
    cols = ["^GSPC", "^TWII", "^N225", "^KS11", "^VIX"]
    cols = [c for c in cols if c in widx.columns]
    # 轉成一般 pandas DataFrame 才能自由改 index（FinlabDataFrame 禁止）
    df = pd.DataFrame(widx.loc[start:, cols]).copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "date"

    # 成交量（給台/日/韓量能組件用）
    try:
        vidx = data.get("world_index:volume")
        vcols = [c for c in ["^TWII", "^N225", "^KS11"] if c in vidx.columns]
        vdf = pd.DataFrame(vidx.loc[start:, vcols]).copy()
        vdf.index = pd.to_datetime(vdf.index).tz_localize(None).normalize()
        vdf = vdf[~vdf.index.duplicated(keep="last")].sort_index()
        vdf.index.name = "date"
    except Exception:
        vdf = pd.DataFrame(index=df.index)

    return df, vdf


# ============================================================
# 3) 台/日/韓 FGI 自算（CNN 同架構 5 組件）
# ============================================================
def compute_market_fgi(close: pd.Series, vol_proxy: Optional[pd.Series] = None,
                       window: int = 120, min_periods: int = 40) -> tuple[pd.Series, pd.DataFrame]:
    """
    用 CNN 同架構的 5 組件模型計算單一市場的 FGI。

    組件（各 20%）
    -----
    1. 動能 Momentum  : 20 日報酬率（越高越貪婪）
    2. 強度 Strength  : 收盤 vs MA50（站上 = 貪婪）
    3. 趨勢 Trend     : MA20 vs MA60（多头排列 = 貪婪）
    4. 波動 Volatility: 20 日實現波動率（越低越貪婪，反向）
    5. 量能 Volume    : 20 日成交量 / 60 日均量（放量 = 貪婪）

    Parameters
    ----------
    close      : 收盤價 Series
    vol_proxy  : 成交量 Series（台/日/韓用成交量，美國用 VIX 替代故可 None）
    window     : 百分位計算窗口（預設 120 日，2026 年資料才夠算）
    min_periods: 窗口內至少要有多少筆才輸出（預設 40）

    Returns
    -------
    (fgi, components)
        fgi        : 0-100 Series
        components : DataFrame 含 5 個組件（皆 0-100）
    """
    c = close.astype(float)
    ret20 = c.pct_change(20) * 100
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    ma60 = c.rolling(60).mean()
    vol20 = c.pct_change().rolling(20).std() * np.sqrt(252) * 100

    comp = pd.DataFrame(index=c.index)

    # 1) 動能：20 日報酬率 → 滾動百分位
    comp["動能"] = _rolling_percentile(ret20, window, ascending=True, min_periods=min_periods)

    # 2) 強度：close/MA50 - 1 → 滾動百分位
    strength = (c / ma50 - 1) * 100
    comp["強度"] = _rolling_percentile(strength, window, ascending=True, min_periods=min_periods)

    # 3) 趨勢：MA20/MA60 - 1 → 滾動百分位
    trend = (ma20 / ma60 - 1) * 100
    comp["趨勢"] = _rolling_percentile(trend, window, ascending=True, min_periods=min_periods)

    # 4) 波動：實現波動率反向（波動越高越恐慌）
    comp["波動"] = _rolling_percentile(vol20, window, ascending=False, min_periods=min_periods)

    # 5) 量能：20 日均量 / 60 日均量
    if vol_proxy is not None:
        v = vol_proxy.astype(float).reindex(c.index)
        vol_ratio = v.rolling(20).mean() / v.rolling(60).mean()
        comp["量能"] = _rolling_percentile(vol_ratio, window, ascending=True, min_periods=min_periods)
    else:
        comp["量能"] = np.nan

    fgi = comp.mean(axis=1, skipna=False)
    return fgi, comp


def compute_all_fgi(index_df: pd.DataFrame,
                    volume_df: Optional[pd.DataFrame] = None,
                    window: int = 120) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    對台/日/韓三個市場計算 FGI + 組件分解。

    Returns (fgi_df, comp_df)
        fgi_df : index=date, columns=[TW, KR, JP]
        comp_df: MultiIndex columns (market, component)
    """
    fgi_parts, comp_parts = {}, {}

    for mkt, meta in MARKETS.items():
        if mkt == "US":
            continue  # 美國用 CNN 官方
        col = meta["idx"]
        if col not in index_df.columns:
            continue
        s = index_df[col].dropna()
        # 量能：world_index volume 欄
        v = volume_df[col] if (volume_df is not None and col in volume_df.columns) else None
        fgi_s, comp_df = compute_market_fgi(s, vol_proxy=v, window=window)
        fgi_parts[mkt] = fgi_s
        for c in comp_df.columns:
            comp_parts[(mkt, c)] = comp_df[c]

    fgi_df = pd.DataFrame(fgi_parts).sort_index()
    fgi_df.index.name = "date"
    comp_out = pd.DataFrame(comp_parts).sort_index()
    comp_out.index.name = "date"
    return fgi_df, comp_out


# ============================================================
# 4) 統一抓取入口 + 落地 parquet
# ============================================================
def fetch_all(start: str = START_DATE, force: bool = False,
              save: bool = True) -> dict:
    """
    抓全部資料（CNN FGI + 組件 + 指數水位 + 自算台日韓 FGI）並落地 parquet。

    Returns dict:
        index   : 指數水位 DataFrame
        fgi     : FGI 總分 DataFrame (index=date, cols=[US, TW, KR, JP])
        rating  : FGI rating DataFrame
        comp    : 組件分解 DataFrame (美國=CNN 官方, 台日韓=自算)
        fgi_us_source : "CNN 官方"
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # --- 指數水位（一定要重抓：FGI 依賴最新一天，舊 cache 會讓值停滯）---
    index_df, volume_df = fetch_index_levels()

    # --- CNN 官方 FGI + 組件 + CNN 來源的 S&P500 ---
    cnn_err = None
    cnn_sp500 = pd.Series(dtype=float)
    try:
        cnn_fgi, cnn_comp, cnn_sp500 = fetch_cnn_fgi()
    except Exception as e:
        cnn_err = str(e)
        cnn_fgi, cnn_comp = pd.DataFrame(), pd.DataFrame()

    # ★ 用 CNN 的 S&P500 補上 finlab 的落後（finlab T+1，CNN 有當日）
    #   策略：CNN 的資料一律覆蓋 finlab 同日期的值 + 補上 finlab 沒有的日期
    if not cnn_sp500.empty and "^GSPC" in index_df.columns:
        merged = index_df["^GSPC"].copy()
        for d, v in cnn_sp500.items():
            merged[d] = v
        merged = merged.sort_index()
        index_df["^GSPC"] = merged

    # --- 自算台日韓 ---
    tw_kr_jp_fgi, tw_kr_jp_comp = compute_all_fgi(index_df, volume_df)

    # --- 合併 FGI ---
    fgi_parts = {}
    if not cnn_fgi.empty:
        fgi_parts["US"] = cnn_fgi["score"]
    for c in tw_kr_jp_fgi.columns:
        fgi_parts[c] = tw_kr_jp_fgi[c]
    fgi_df = pd.DataFrame(fgi_parts).sort_index()
    fgi_df.index.name = "date"
    fgi_df = fgi_df.dropna(how="all")
    # ★ 裁到顯示起點（指數保留 warmup 資料，FGI 只顯示 START_DATE 起）
    fgi_df = fgi_df[fgi_df.index >= pd.Timestamp(start)]

    # --- 合併 rating ---
    rating_cn = fgi_df.apply(lambda col: col.map(lambda v: fgi_to_rating(v)[1]))
    rating_en = fgi_df.apply(lambda col: col.map(lambda v: fgi_to_rating(v)[0]))

    # --- 合併組件（美國 CNN 官方 + 台日韓自算）---
    comp_out = {}
    if not cnn_comp.empty:
        for c in cnn_comp.columns:
            comp_out[("US", c)] = cnn_comp[c]
    for c in tw_kr_jp_comp.columns:
        comp_out[c] = tw_kr_jp_comp[c]
    comp_df = pd.DataFrame(comp_out).sort_index()
    comp_df.index.name = "date"
    comp_df = comp_df[comp_df.index >= pd.Timestamp(start)]
    # 台/日/韓組件欄位名（避免跟美國 CNN 組件混淆）
    comp_df.columns = [
        (mkt, c) if mkt == "US" else (mkt, f"自算{c}")
        for mkt, c in comp_df.columns
    ]
    # parquet 不支援 MultiIndex column，攤平成 "市場::組件"
    comp_df.columns = [f"{mkt}::{c}" for mkt, c in comp_df.columns]

    result = {
        "index": index_df,
        "fgi": fgi_df,
        "rating_cn": rating_cn,
        "rating_en": rating_en,
        "comp": comp_df,
        "fgi_us_source": "CNN 官方" if not cnn_fgi.empty else "CNN 抓取失敗",
        "cnn_error": cnn_err,
    }

    if save:
        index_df.to_parquet(INDEX_FILE)
        fgi_df.to_parquet(FGI_HISTORY_FILE)
        comp_df.to_parquet(COMPONENT_FILE)

    return result


def load_fgi_data(start: str = START_DATE) -> dict:
    """
    讀取本地 parquet（不存在或過期則自動抓）。
    給 Streamlit page 用。

    ★ 每日資料靠 launchd 排程 `fear_greed_fetcher.py` 在 20:20 更新（工作日）。
      這裡只是保險：如果 parquet 檔是「昨天以前的」，就現場重抓一次
      （例如使用者週末沒跑排程、或排程失敗了）。
    """
    need_fetch = True
    if INDEX_FILE.exists() and FGI_HISTORY_FILE.exists():
        try:
            age_hours = (datetime.now() - datetime.fromtimestamp(
                FGI_HISTORY_FILE.stat().st_mtime)).total_seconds() / 3600
            need_fetch = age_hours > 30  # 30 小時以上重抓（涵蓋週末）
        except Exception:
            need_fetch = True

    if need_fetch:
        return fetch_all(start=start, force=False, save=True)
    else:
        index_df = pd.read_parquet(INDEX_FILE)
        index_df.index = pd.to_datetime(index_df.index)
        fgi_df = pd.read_parquet(FGI_HISTORY_FILE)
        fgi_df.index = pd.to_datetime(fgi_df.index)
        comp_df = pd.read_parquet(COMPONENT_FILE)
        comp_df.index = pd.to_datetime(comp_df.index)
        rating_cn = fgi_df.apply(lambda col: col.map(lambda v: fgi_to_rating(v)[1]))
        rating_en = fgi_df.apply(lambda col: col.map(lambda v: fgi_to_rating(v)[0]))
        return {
            "index": index_df,
            "fgi": fgi_df,
            "rating_cn": rating_cn,
            "rating_en": rating_en,
            "comp": comp_df,
            "fgi_us_source": "CNN 官方",
            "cnn_error": None,
        }


if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    ap = argparse.ArgumentParser(description="抓取 / 更新 Fear & Greed Index 資料")
    ap.add_argument("--force", action="store_true",
                    help="強制重抓（預設就是重抓，此參數保留相容性）")
    args = ap.parse_args()

    try:
        from data_fetcher import ensure_finlab_login
        ensure_finlab_login()
    except Exception:
        pass

    res = fetch_all(force=True, save=True)
    print("=== 抓取完成 ===")
    print(f"更新時間: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"落地目錄: {DATA_DIR}")
    print(f"FGI 來源（美國）: {res['fgi_us_source']}")
    if res["cnn_error"]:
        print(f"  CNN 錯誤: {res['cnn_error']}")
    print(f"\nFGI 範圍: {res['fgi'].index.min()} ~ {res['fgi'].index.max()}")
    print(f"FGI 筆數: {len(res['fgi'])}")
    print(f"\n各欄位:")
    for c in res["fgi"].columns:
        s = res["fgi"][c].dropna()
        if len(s):
            rating = res["rating_cn"][c].dropna()
            r_txt = rating.iloc[-1] if len(rating) else "—"
            print(f"  {c} ({MARKETS.get(c, {}).get('cn', c)}): {len(s)} 筆, "
                  f"最新 {s.index[-1]:%Y-%m-%d} = {s.iloc[-1]:.1f} ({r_txt})")
    print(f"\n指數水位:")
    for c in res["index"].columns:
        s = res["index"][c].dropna()
        print(f"  {c}: {len(s)} 筆, 末值 {s.iloc[-1]:,.2f}")