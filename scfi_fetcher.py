#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
scfi_fetcher.py — SCFI (上海出口集裝箱運價指數) 抓取

公開資料源：
- 上海航運交易所英文版 https://en.sse.net.cn/indices/scfinew.jsp
- 公開 AJAX endpoint：GET /currentIndex?indexName=scfi
  - 當週 + 上週數據（綜合指數 + 21 條航線的 currentContent）
  - 歷史查詢 /singleIndex/scfi?date=... 要付費訂閱會員（500 error）
- 自動 fallback：抓到分航線 currentContent 全 null（要登入）就只回綜合指數

21 個 dataItemType 對照（從 SSE 英文版 response 整理）：
  SCFI_T   綜合指數
  SCFI_L1  歐洲 20ft    SCFI_L27 歐洲 40ft
  SCFI_L2  地中海 20ft  SCFI_L28 地中海 40ft
  SCFI_L3  美西 40ft    SCFI_L4  美東 40ft
  SCFI_L5  波紅 20ft    SCFI_L31 印巴 20ft
  SCFI_L6  澳新 20ft    SCFI_L7  西非 20ft
  SCFI_L8  南非 20ft    SCFI_L9  南美 20ft
  SCFI_L10 日本關西 20ft SCFI_L11 日本關東 20ft
  SCFI_L12 東南亞 20ft  SCFI_L13 韓國 20ft
  SCFI_L25 中南美 20ft  SCFI_L26 東非 20ft
  SCFI_L29 南美 40ft    SCFI_L30 中南美 40ft
"""
from __future__ import annotations

import requests
from typing import Dict, Optional
from dataclasses import dataclass


# ============================================================
# 常數
# ============================================================
SSE_API_LATEST = "https://en.sse.net.cn/currentIndex?indexName=scfi"
SSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://en.sse.net.cn/indices/scfinew.jsp",
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# 21 條航線 mapping：(中文標籤, 英文標籤, 單位)
SCFI_LINES: Dict[str, tuple] = {
    "SCFI_T":   ("綜合指數",                  "Comprehensive Index",                                  "Index"),
    "SCFI_L1":  ("歐洲 20ft（基本港）",         "Europe 20ft (Base port)",                               "USD/TEU"),
    "SCFI_L2":  ("地中海 20ft（基本港）",       "Mediterranean 20ft (Base port)",                        "USD/TEU"),
    "SCFI_L3":  ("美西 40ft（基本港）",         "USWC 40ft (Base port)",                                 "USD/FEU"),
    "SCFI_L4":  ("美東 40ft（基本港）",         "USEC 40ft (Base port)",                                 "USD/FEU"),
    "SCFI_L5":  ("波斯灣 20ft（迪拜）",         "Persian Gulf and Red Sea 20ft (Dubai)",                 "USD/TEU"),
    "SCFI_L6":  ("澳新 20ft（墨爾本）",         "Australia/New Zealand 20ft (Melbourne)",                "USD/TEU"),
    "SCFI_L7":  ("西非 20ft（拉哥斯）",         "West Africa 20ft (Lagos)",                              "USD/TEU"),
    "SCFI_L8":  ("南非 20ft（德班）",           "South Africa 20ft (Durban)",                            "USD/TEU"),
    "SCFI_L9":  ("南美 20ft（桑托斯）",         "South America 20ft (Santos)",                           "USD/TEU"),
    "SCFI_L10": ("日本關西 20ft（基本港）",     "West Japan 20ft (Base port)",                           "USD/TEU"),
    "SCFI_L11": ("日本關東 20ft（基本港）",     "East Japan 20ft (Base port)",                           "USD/TEU"),
    "SCFI_L12": ("東南亞 20ft（新加坡）",       "Southeast Asia 20ft (Singapore)",                       "USD/TEU"),
    "SCFI_L13": ("韓國 20ft（釜山）",           "Korea 20ft (Pusan)",                                    "USD/TEU"),
    "SCFI_L25": ("中南美 20ft（曼薩尼約）",     "Central/South America West Coast 20ft (Manzanillo)",    "USD/TEU"),
    "SCFI_L26": ("東非 20ft（蒙巴薩）",         "East Africa 20ft (Mombasa)",                            "USD/TEU"),
    "SCFI_L27": ("歐洲 40ft（基本港）",         "Europe 40ft (Base port)",                               "USD/FEU"),
    "SCFI_L28": ("地中海 40ft（基本港）",       "Mediterranean 40ft (Base port)",                        "USD/FEU"),
    "SCFI_L29": ("南美 40ft（桑托斯）",         "South America 40ft (Santos)",                           "USD/FEU"),
    "SCFI_L30": ("中南美 40ft（曼薩尼約）",     "Central/South America West Coast 40ft (Manzanillo)",    "USD/FEU"),
    "SCFI_L31": ("印巴 20ft（納瓦謝瓦）",       "India and Pakistan 20ft (Nhava Sheva)",                 "USD/TEU"),
}

# 欄位順序（綜合 + 20 條航線，date 在最前，source 在最後）
COLUMN_ORDER = ["date"] + list(SCFI_LINES.keys()) + ["source"]


# ============================================================
# 抓取
# ============================================================
@dataclass
class SCFIResult:
    """單週抓取結果"""
    date: str                       # YYYY-MM-DD 當週日期
    last_date: Optional[str]        # YYYY-MM-DD 上週日期
    values: Dict[str, Optional[float]]  # dataItemType → 數值（null 表示 SSE 沒回 = 要登入）
    source: str                     # "SSE"

    @property
    def has_lines(self) -> bool:
        """是否有分航線資料（綜合以外至少有 1 條非 null）"""
        n = sum(1 for k, v in self.values.items() if k != "SCFI_T" and v is not None)
        return n > 0

    @property
    def n_lines_filled(self) -> int:
        return sum(1 for k, v in self.values.items() if k != "SCFI_T" and v is not None)


def fetch_latest_scfi(timeout: int = 10) -> SCFIResult:
    """
    抓 SSE 公開 API 拿當週 SCFI。

    注意：
    - 公開 endpoint 只回當週 + 上週綜合指數
    - 分航線的 currentContent 在境外未登入請求通常為 null（SSE 鎖登入會員）
    - 失敗時丟 RuntimeError
    """
    resp = requests.get(SSE_API_LATEST, headers=SSE_HEADERS, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("status") != 1:
        raise RuntimeError(f"SSE API 回傳非成功狀態：{payload.get('msg', payload)}")

    inner = payload["data"]
    values: Dict[str, Optional[float]] = {}
    for line in inner.get("lineDataList", []):
        item_type = line.get("dataItemTypeName")
        if item_type not in SCFI_LINES:
            # 未知航線類型：跳過但保留在 log
            continue
        values[item_type] = line.get("currentContent")

    return SCFIResult(
        date=inner["currentDate"],
        last_date=inner.get("lastDate"),
        values=values,
        source="SSE",
    )


def to_csv_row(result: SCFIResult) -> Dict[str, object]:
    """SCFIResult → 一行 CSV 用的 dict"""
    row: Dict[str, object] = {"date": result.date, "source": result.source}
    for k in SCFI_LINES.keys():
        v = result.values.get(k)
        row[k] = v if v is not None else ""  # 空字串在 pandas 會變 NaN
    return row


# ============================================================
# self-test
# ============================================================
if __name__ == "__main__":
    import json
    r = fetch_latest_scfi()
    print(f"當週: {r.date}  上週: {r.last_date}")
    print(f"綜合指數: {r.values.get('SCFI_T')}")
    print(f"分航線填值: {r.n_lines_filled} / 20")
    for k, (zh, en, unit) in SCFI_LINES.items():
        v = r.values.get(k)
        if v is not None:
            print(f"  {k:9s} {zh:25s} {v:>10.2f} {unit}")
