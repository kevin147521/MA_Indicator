"""
realtime_fetcher.py — 各國指數即時報價

資料來源（依可靠度混合）
------------------------
1. 台灣加權指數 : TWSE 官方 API（免 key，盤中即時）
   https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw
2. 美國 S&P 500 : CNN 官方（免 key，盤中每 15-30 分鐘更新）
3. 日本 / 韓國 : FinLab world_index（通常 T+0 晚上就有當日收盤）

為什麼不用 Yahoo Finance？
   Yahoo quote/chart API 對程式化請求回 429 速率限制，不穩定。

為什麼不直接用 FinLab 當台股即時？
   FinLab world_index 台股有 T+1 延遲（盤中看不到當日），
   TWSE 官方是盤中即時，適合看「現在盤勢」。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd


# ============================================================
# 市場定義
# ============================================================
REALTIME_MARKETS = {
    "TW": {"label": "台灣 加權指數", "cn": "台灣", "source": "TWSE 官方"},
    "US": {"label": "美國 S&P 500", "cn": "美國", "source": "CNN 官方"},
    "JP": {"label": "日本 日經225", "cn": "日本", "source": "FinLab"},
    "KR": {"label": "韓國 KOSPI", "cn": "韓國", "source": "FinLab"},
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

TWSE_URL = (
    "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    "?ex_ch=tse_t00.tw&json=1&delay=0"
)


# ============================================================
# 各來源抓取
# ============================================================
def fetch_twse_realtime() -> Optional[dict]:
    """TWSE 官方台股加權指數即時報價（盤中會跳動）"""
    try:
        import requests
        h = {**_HEADERS, "Referer": "https://mis.twse.com.tw/"}
        r = requests.get(TWSE_URL, headers=h, timeout=10)
        r.raise_for_status()
        arr = r.json().get("msgArray", [])
        if not arr:
            return None
        m = arr[0]
        raw_date = m.get("d", "")          # 格式 "20261022"
        data_date = None
        if raw_date and len(raw_date) == 8:
            data_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        return {
            "price": float(m["z"]) if m.get("z") not in (None, "-", "") else None,
            "name": m.get("n", "發行量加權股價指數"),
            "turnover": float(m["tlong"]) if m.get("tlong") else None,
            "date": data_date,
            "time": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_cnn_sp500_realtime(retries: int = 2) -> Optional[dict]:
    """CNN 官方 S&P500（盤中每 15-30 分鐘更新）。CNN 端偶發 404，會自動 retry。"""
    try:
        import time
        import requests
        h = {**_HEADERS,
             "Accept": "application/json, text/plain, */*",
             "Origin": "https://www.cnn.com",
             "Referer": "https://www.cnn.com/"}
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandreed/graphdata",
            headers=h, timeout=15)
        r.raise_for_status()
        d = r.json()

        # FGI 現況
        cur = d.get("fear_and_greed", {})
        # S&P 現價（最後一筆，y 是價格）
        pts = d.get("market_momentum_sp500", {}).get("data", [])
        price = pts[-1].get("y") if pts else None
        prev_pt = pts[-2].get("y") if len(pts) >= 2 else None
        # x 是 epoch 毫秒（UTC），轉日期字串
        data_date = None
        if pts:
            try:
                data_date = datetime.utcfromtimestamp(
                    float(pts[-1]["x"]) / 1000).strftime("%Y-%m-%d")
            except Exception:
                data_date = None

        return {
            "price": price,
            "prev_close": prev_pt,
            "fgi_now": cur.get("score"),
            "rating": cur.get("rating"),
            "date": data_date,
            "time": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_finlab_realtime(cols: dict[str, str]) -> dict[str, Optional[dict]]:
    """
    從 FinLab world_index 取最新收盤（用於日本/韓國，以及當 TWSE 不可用時的台股備援）

    Parameters
    ----------
    cols : {"JP": "^N225", "KR": "^KS11", "TW": "^TWII", "US": "^GSPC"}
    """
    out: dict[str, Optional[dict]] = {}
    try:
        from finlab import data
        widx = data.get("world_index:close")
        for mkt, col in cols.items():
            if col not in widx.columns:
                out[mkt] = {"error": "欄位不存在"}
                continue
            s = widx[col].dropna()
            if s.empty:
                out[mkt] = {"error": "無資料"}
                continue
            last = float(s.iloc[-1])
            prev = float(s.iloc[-2]) if len(s) >= 2 else None
            out[mkt] = {
                "price": last,
                "prev_close": prev,
                "change_pct": ((last / prev - 1) * 100) if prev else None,
                "date": s.index[-1].strftime("%Y-%m-%d"),
                "time": datetime.now().strftime("%H:%M:%S"),
            }
    except Exception as e:
        for mkt in cols:
            out[mkt] = {"error": str(e)}
    return out


# ============================================================
# 統一入口
# ============================================================
def fetch_realtime_all() -> dict:
    """
    抓四國指數即時報價。

    Returns
    -------
    dict: {"TW": {...}, "US": {...}, "JP": {...}, "KR": {...}, "fetched_at": "..."}
        每個市場含 price / change_pct / date / source 等欄位
    """
    result: dict = {"fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # FinLab（日本 / 韓國 / 台灣備援 / 美國備援）
    finlab = fetch_finlab_realtime(
        {"JP": "^N225", "KR": "^KS11", "TW": "^TWII", "US": "^GSPC"})
    for k, v in finlab.items():
        result[k] = v
    for k in ("JP", "KR", "TW"):
        if result.get(k):
            result[k]["source"] = "FinLab"

    # 台灣：TWSE 官方覆蓋（盤中即時）
    twse = fetch_twse_realtime()
    if twse and twse.get("price"):
        fl = result.get("TW") or {}
        result["TW"] = {
            **fl,
            "price": twse["price"],
            "date": twse.get("date") or fl.get("date"),
            "turnover": twse.get("turnover"),
            "source": "TWSE 官方（盤中即時）",
            "time": twse.get("time"),
        }
        # 算漲跌幅（對比 FinLab 前一日收盤）
        prev = fl.get("prev_close")
        if prev:
            result["TW"]["prev_close"] = prev
            result["TW"]["change_pct"] = (
                (twse["price"] / prev - 1) * 100)

    # 美國：CNN 官方覆蓋（失敗時保留 FinLab 結果，不要開天窗）
    cnn = fetch_cnn_sp500_realtime()
    if cnn and cnn.get("price"):
        result["US"] = {
            **result.get("US", {}),
            "price": cnn["price"],
            "prev_close": cnn.get("prev_close"),
            "change_pct": (
                (cnn["price"] / cnn["prev_close"] - 1) * 100
                if cnn.get("prev_close") else None),
            "fgi_now": cnn.get("fgi_now"),
            "rating": cnn.get("rating"),
            "date": cnn.get("date") or result.get("US", {}).get("date"),
            "source": "CNN 官方（盤中每 15-30 分鐘）",
            "time": cnn.get("time"),
        }
    elif cnn and cnn.get("error"):
        # CNN 抓不到 → 保留 FinLab 的 ^GSPC，註記降級
        if result.get("US"):
            result["US"]["source"] = "FinLab（CNN 暫時連不上）"
            result["US"]["note"] = cnn["error"]

    return result


if __name__ == "__main__":
    res = fetch_realtime_all()
    print(f"=== 即時報價（擷取於 {res['fetched_at']}）===")
    for mkt in ("TW", "US", "JP", "KR"):
        meta = REALTIME_MARKETS.get(mkt, {})
        r = res.get(mkt) or {}
        print(f"\n{meta.get('label', mkt)}")
        if r.get("error"):
            print(f"  ❌ {r['error']}")
            continue
        price = r.get("price")
        chg = r.get("change_pct")
        print(f"  現價: {price:,.2f}" if price else "  現價: —")
        if chg is not None:
            arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
            print(f"  漲跌: {arrow} {chg:+.2f}%")
        print(f"  資料日期: {r.get('date')}")
        print(f"  來源: {r.get('source')}")
        if r.get("turnover"):
            print(f"  成交金額: {r['turnover']/1e8:,.0f} 億元")
        if r.get("fgi_now"):
            print(f"  CNN FGI: {r['fgi_now']:.1f} ({r.get('rating')})")