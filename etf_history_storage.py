#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
etf_history_storage.py — etfinfo 主動 ETF 每日 snapshot 存儲

因為 etfinfo.tw 不提供歷史 topChanges API（每次只回「與前一筆的差分」），
所以需要自己每天抓 summary 存進本地，累積成歷史。

存儲格式：JSON 檔，每天一份
  ~/.openclaw/ma_indicator_data/etfinfo_snapshots/{YYYY-MM-DD}.json

內容：
{
  "date": "2026-09-04",
  "saved_at": "2026-09-04T14:32:00",
  "summary": { ... 完整 etfinfo summary 原始 JSON ... }
}

提供：
- save_today_snapshot(): 抓今天 + 存檔
- load_recent_snapshots(days=30): 載入最近 N 天 snapshots
- aggregate_top_changes(days=30, action='increased'): 累積 N 天 topChanges
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import pandas as pd

from etfinfo_fetcher import fetch_active_summary


# ============================================================
# 常數
# ============================================================
SNAPSHOT_DIR = Path.home() / ".openclaw" / "ma_indicator_data" / "etfinfo_snapshots"


# ============================================================
# 存儲
# ============================================================
def _ensure_dir():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _path_for(date: str) -> Path:
    """date 格式 YYYY-MM-DD"""
    return SNAPSHOT_DIR / f"{date}.json"


def save_snapshot(summary: dict, date: Optional[str] = None) -> Path:
    """
    存 summary 進 JSON 檔。date 預設今天。
    如果當天已有 snapshot，覆蓋。
    回傳寫入的 Path。
    """
    _ensure_dir()
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    saved_at = datetime.now().isoformat(timespec="seconds")
    payload = {
        "date": date,
        "saved_at": saved_at,
        "anchor_date": summary.get("anchorDate"),
        "summary": summary,
    }
    p = _path_for(date)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def save_today_snapshot() -> Path:
    """抓今天 summary 存進去"""
    summary = fetch_active_summary()
    return save_snapshot(summary)


def load_snapshot(date: str) -> Optional[dict]:
    """讀某一天 snapshot"""
    p = _path_for(date)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def load_recent_snapshots(days: int = 30) -> list[dict]:
    """載入最近 N 天 snapshots（按日期舊到新排序）"""
    if not SNAPSHOT_DIR.exists():
        return []
    today = datetime.now().date()
    snapshots = []
    for i in range(days, 0, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        s = load_snapshot(d)
        if s is not None:
            snapshots.append(s)
    # 也加今天（如果有的話）
    today_str = today.strftime("%Y-%m-%d")
    s_today = load_snapshot(today_str)
    if s_today is not None and (not snapshots or snapshots[-1]["date"] != today_str):
        snapshots.append(s_today)
    return snapshots


# ============================================================
# 聚合分析
# ============================================================
def aggregate_top_changes(
    snapshots: list[dict],
    action: str = "increased",  # "increased" / "decreased" / "added" / "removed" / "all"
) -> pd.DataFrame:
    """
    累積 N 天 snapshots 的 topChanges 計算個股總異動量。

    Parameters
    ----------
    snapshots : list of {date, summary}
    action : 篩選的動作類型，'all' 表示全部

    Returns
    -------
    DataFrame with columns: stockCode, stockName, industry,
                            n_etfs, etf_list, total_shares_delta, total_weight_delta
        排序：total_shares_delta 絕對值大到小
    """
    if not snapshots:
        return pd.DataFrame()

    rows = []
    for snap in snapshots:
        date = snap["date"]
        for etf in snap["summary"].get("etfs", []):
            etf_code = etf["code"]
            etf_name = etf["name"]
            for change in etf.get("topChanges", []):
                rows.append({
                    "date": date,
                    "etf_code": etf_code,
                    "etf_name": etf_name,
                    "stock_code": change.get("code"),
                    "stock_name": change.get("name"),
                    "industry": change.get("industry"),
                    "type": change.get("type"),
                    "shares_delta": change.get("sharesDelta") or 0,
                    "weight_delta": change.get("weightDelta") or 0,
                })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    if action != "all":
        df = df[df["type"] == action]

    if df.empty:
        return df

    # industry 全部都是 None，pandas groupby 預設 dropna=True 會丟掉 None 群組
    # 改填空字串保留
    df["industry"] = df["industry"].fillna("—")

    # 依個股聚合（dropna=False 保留 None / 空字串 群組）
    agg = df.groupby(["stock_code", "stock_name", "industry"], dropna=False).agg(
        n_etfs=("etf_code", "nunique"),
        etf_list=("etf_code", lambda s: ", ".join(sorted(set(s)))),
        total_shares_delta=("shares_delta", "sum"),
        total_weight_delta=("weight_delta", "sum"),
        n_days=("date", "nunique"),
        last_date=("date", "max"),
    ).reset_index()

    agg["abs_shares"] = agg["total_shares_delta"].abs()
    agg = agg.sort_values("abs_shares", ascending=False).reset_index(drop=True)
    return agg


# ============================================================
# 統計資料
# ============================================================
def snapshot_stats() -> dict:
    """回傳目前 DB 狀態：總天數、最早/最晚、缺哪幾天"""
    if not SNAPSHOT_DIR.exists():
        return {"total": 0, "earliest": None, "latest": None, "dates": []}

    files = sorted(SNAPSHOT_DIR.glob("*.json"))
    if not files:
        return {"total": 0, "earliest": None, "latest": None, "dates": []}

    dates = [f.stem for f in files]
    return {
        "total": len(dates),
        "earliest": dates[0],
        "latest": dates[-1],
        "dates": dates,
    }


# ============================================================
# self-test
# ============================================================
if __name__ == "__main__":
    print("=== Snapshot DB 統計 ===")
    stats = snapshot_stats()
    print(f"  總天數: {stats['total']}")
    print(f"  最早: {stats['earliest']}")
    print(f"  最新: {stats['latest']}")

    if stats["total"] == 0:
        print()
        print("DB 是空的，先抓今天存進去…")
        p = save_today_snapshot()
        print(f"  ✓ saved: {p}")
    else:
        print()
        print("=== 過去 7 天加碼排行（top 10）===")
        snaps = load_recent_snapshots(days=7)
        df = aggregate_top_changes(snaps, action="increased")
        if df.empty:
            print("  無資料")
        else:
            for _, r in df.head(10).iterrows():
                print(f"  {r['stock_code']} {r['stock_name']} | {r['n_etfs']} 家 ETF | 累計 +{r['total_shares_delta']:,.0f} 張 | 權重 {r['total_weight_delta']:+.2f}%")
