#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
etfinfo_fetcher.py — ETF資訊網 (etfinfo.tw) API wrapper

公開 endpoints（不需要登入）：
- GET https://www.etfinfo.tw/api/active/summary
  - 39 檔主動 ETF 完整資料（含 topChanges 每檔異動個股）
  - 117 個股加碼/減碼排行（含 etfDetails 哪家 ETF）
  - 26 個共識訊號（多家 ETF 同進同出）
  - 20 個產業資金流
  - syncStatus / anchorDate
- GET https://www.etfinfo.tw/api/etf/{code}
  - info（基本資料）+ holdings.stocks（完整持股）+ latestMarket（市值/折溢價）
  - + dividends / returnStats / trailingYield

注意：
- 不用 Playwright，直接 requests 抓 JSON
- 網站是 Nuxt SSR，內部 API 公開
- 沒有 rate limit 文件，但建議不要高頻打
- 盤後 14:00 左右更新當日 snapshot
"""
from __future__ import annotations

import requests
from typing import Optional
from dataclasses import dataclass


# ============================================================
# 常數
# ============================================================
API_BASE = "https://www.etfinfo.tw/api"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.etfinfo.tw/active",
    # 強制只用 gzip/deflate，避免 etfinfo server 回 br (brotli) 觸發
    # Python requests 的 brotli decoder 在某些 chunked response 會失敗
    # (brotli: decoder process called with data when 'can_accept_more_data()' is False)
    "Accept-Encoding": "gzip, deflate",
}

TIMEOUT = 15  # seconds


# ============================================================
# Endpoints
# ============================================================
def fetch_active_summary(timeout: int = TIMEOUT) -> dict:
    """
    抓主頁 summary。

    回傳 dict：
    - hero: dict（totalEtfs / changedEtfs / grossBuyAmount / topConsensusBuy / ...）
    - etfs: list（39 檔主動 ETF，每檔含 topChanges 個股異動）
    - flowRankings: list（117 個股加碼/減碼排行，每個股含 etfDetails 哪家 ETF）
    - consensusSignals: list（共識訊號）
    - industryNetFlows: list（產業資金流）
    - syncStatus: dict（更新狀態）
    - anchorDate / updatedAt / latestMarketDate

    失敗丟 RuntimeError。
    """
    url = f"{API_BASE}/active/summary"
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data and data.get("error"):
        raise RuntimeError(f"etfinfo API error: {data.get('statusMessage', data)}")

    return data


def fetch_etf_detail(etf_code: str, timeout: int = TIMEOUT) -> dict:
    """
    抓單檔主動 ETF 詳細資料（info + holdings + latestMarket + dividends + returnStats）。

    失敗丟 RuntimeError。
    """
    url = f"{API_BASE}/etf/{etf_code}"
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data and data.get("error"):
        raise RuntimeError(f"etfinfo API error: {data.get('statusMessage', data)}")

    return data


# ============================================================
# 便利函式
# ============================================================
def get_hero_summary() -> dict:
    """從 summary 拿 hero dict"""
    data = fetch_active_summary()
    return data.get("hero", {})


def get_etf_list() -> list:
    """從 summary 拿 39 檔主動 ETF 簡表（不含 topChanges）"""
    data = fetch_active_summary()
    return [
        {
            "code": e["code"],
            "name": e["name"],
            "issuer": e.get("issuer"),
            "dividendFrequency": e.get("dividendFrequency"),
            "launchDate": e.get("launchDate"),
            "changeCount": e.get("changeCount", 0),
            "netAmount": e.get("netAmount", 0),
            "price": e.get("price"),
        }
        for e in data.get("etfs", [])
    ]


def get_stock_etf_holders(stock_code: str) -> list[dict]:
    """
    從 summary.flowRankings 找該個股被哪些 ETF 加減碼。

    注意：只回傳「當日有變化」的個股。無變化的個股在 flowRankings 不會出現。
    若需要「被持有但今天沒動作」的清單，要用 fetch_etf_detail 拿完整 holdings。
    """
    data = fetch_active_summary()
    for r in data.get("flowRankings", []):
        if r.get("stockCode") == stock_code:
            return r.get("etfDetails", [])
    return []


# ============================================================
# self-test
# ============================================================
if __name__ == "__main__":
    print("=== Test 1: fetch_active_summary ===")
    summary = fetch_active_summary()
    print(f"  anchorDate: {summary.get('anchorDate')}")
    print(f"  etfs count: {len(summary.get('etfs', []))}")
    print(f"  flowRankings: {len(summary.get('flowRankings', []))}")
    print(f"  consensusSignals: {len(summary.get('consensusSignals', []))}")
    print(f"  industryNetFlows: {len(summary.get('industryNetFlows', []))}")
    print(f"  syncStatus: {summary.get('syncStatus')}")

    hero = summary.get("hero", {})
    print(f"\n  hero.totalEtfs: {hero.get('totalEtfs')}")
    print(f"  hero.changedEtfs: {hero.get('changedEtfs')}")
    print(f"  hero.grossBuyAmount: {hero.get('grossBuyAmount')}")
    print(f"  hero.topConsensusBuy:")
    for x in hero.get("topConsensusBuy", []):
        print(f"    {x['stockCode']} {x['stockName']} | {x['etfCount']} 家 | {x['amount']/1e8:+.1f} 億")

    print("\n=== Test 2: fetch_etf_detail ===")
    detail = fetch_etf_detail("00400A")
    info = detail.get("info", {})
    holdings = detail.get("holdings", {})
    print(f"  ETF: {info.get('code')} {info.get('name')}")
    print(f"  issuer: {info.get('issuer')}, manager: {info.get('manager')}")
    print(f"  launchDate: {info.get('launchDate')}")
    stocks = holdings.get("stocks", [])
    print(f"  holdings count: {len(stocks)}")
    if stocks:
        for s in stocks[:5]:
            print(f"    {s['code']} {s['name']} | {s['weight']}% | {s['shares']:,} 股")

    print("\n=== Test 3: get_stock_etf_holders(2303 聯電) ===")
    holders = get_stock_etf_holders("2303")
    print(f"  持有 ETF 家數: {len(holders)}")
    for h in holders[:5]:
        print(f"    {h['etfCode']} | {h['sharesDelta']:,} 股 | {h['amount']/1e6:+.1f} 百萬 | {h['type']}")
