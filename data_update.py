#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
data_update.py — 每日 finlab 資料更新模組

設計：
1. 定義要刷的資料源清單（基本 + 公司基本 + 進階 + 大盤/融資）
2. 對每個 data source 呼叫 data.get()，記錄是否成功 / 資料筆數 / 耗時
3. 結果寫到 ~/.openclaw/data_update_status.json（給網頁讀）
4. 從 finlab API 抓「剩餘流量」（quota），顯示在網頁

Note: finlab 2.x 有內建 daily usage 統計，但要用 session info API
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# === 狀態檔路徑 ===
STATUS_PATH = Path.home() / ".openclaw" / "data_update_status.json"

# === 資料源分組 ===
DATA_SOURCES = {
    "基本": [
        ("price:收盤價", "收盤價"),
        ("price:開盤價", "開盤價"),
        ("price:最高價", "最高價"),
        ("price:最低價", "最低價"),
        ("price:成交股數", "成交股數"),
        ("price:成交金額", "成交金額"),
    ],
    "公司基本": [
        ("company_basic_info", "公司基本資料"),
        ("security_categories", "全市場清單"),
        ("benchmark_return:發行量加權股價報酬指數", "大盤報酬指數"),
    ],
    "融資券 + 大盤": [
        ("margin_transactions:融資今日餘額", "融資今日餘額"),
        ("margin_balance:融資券總餘額", "融資券總餘額"),
        ("market_transaction_info:收盤指數", "大盤收盤指數"),
    ],
    "進階": [
        ("monthly_revenue:當月營收", "月營收"),
        ("margin_transactions:融資使用率", "融資使用率"),
        ("etl:adj_close", "還原收盤價"),
    ],
}


@dataclass
class SourceResult:
    name: str           # "price:收盤價"
    label: str          # "收盤價"
    group: str          # "基本"
    status: str         # "success" / "error" / "skipped"
    error: Optional[str] = None
    rows: Optional[int] = None
    cols: Optional[int] = None
    elapsed_sec: float = 0.0


@dataclass
class UpdateResult:
    started_at: str           # ISO format
    finished_at: str
    total_elapsed_sec: float
    sources: list[SourceResult]
    daily_usage_mb: Optional[float] = None
    daily_limit_mb: Optional[float] = None
    overall_status: str = "success"   # "success" / "partial" / "failed"


def _ensure_login():
    """統一入口（從 data_fetcher 拿）"""
    from data_fetcher import ensure_finlab_login
    ensure_finlab_login()


def _safe_get(name: str, label: str, group: str, force: bool = False) -> SourceResult:
    """抓單一資料源，包 try/except 避免一個壞全部壞"""
    from finlab import data
    started = time.time()
    try:
        df = data.get(name, force_download=force)
        elapsed = time.time() - started
        if df is None or len(df) == 0:
            return SourceResult(
                name=name, label=label, group=group,
                status="error", error="empty dataframe",
                elapsed_sec=round(elapsed, 2),
            )
        return SourceResult(
            name=name, label=label, group=group,
            status="success",
            rows=len(df),
            cols=len(df.columns) if hasattr(df, "columns") else 0,
            elapsed_sec=round(elapsed, 2),
        )
    except Exception as e:
        elapsed = time.time() - started
        return SourceResult(
            name=name, label=label, group=group,
            status="error",
            error=str(e)[:200],
            elapsed_sec=round(elapsed, 2),
        )


def _try_get_daily_usage() -> tuple[Optional[float], Optional[float]]:
    """嘗試抓 finlab daily usage（mb / limit_mb）"""
    try:
        from finlab import data
        # finlab 2.x 沒有公開 API，但 session login 時有印
        # 折衷辦法：讀 finlab session info（如果有 login response）
        import finlab
        # 從 login state 抓
        if hasattr(finlab, "login"):
            # finlab 內部有 _session 存 token
            session = getattr(finlab, "_session", None) or getattr(finlab, "session", None)
            if session and hasattr(session, "get"):
                resp = session.get("https://finlab.finance/api/v1/user/quota")
                if resp.status_code == 200:
                    j = resp.json()
                    return j.get("used_mb"), j.get("limit_mb")
    except Exception:
        pass
    return None, None


def run_update(
    groups: list[str] = None,
    force: bool = False,
) -> UpdateResult:
    """
    跑一輪資料更新。

    Parameters
    ----------
    groups : 要更新的分組，None = 全部
    force : 是否強制重新下載（finlab 內部 cache 失效）
    """
    if groups is None:
        groups = list(DATA_SOURCES.keys())

    _ensure_login()
    start_dt = datetime.now()
    sources: list[SourceResult] = []

    for group in groups:
        if group not in DATA_SOURCES:
            continue
        for name, label in DATA_SOURCES[group]:
            res = _safe_get(name, label, group, force=force)
            sources.append(res)

    end_dt = datetime.now()
    used, limit = _try_get_daily_usage()

    # 判斷整體狀態
    n_ok = sum(1 for s in sources if s.status == "success")
    n_err = sum(1 for s in sources if s.status == "error")
    if n_err == 0:
        overall = "success"
    elif n_ok == 0:
        overall = "failed"
    else:
        overall = "partial"

    result = UpdateResult(
        started_at=start_dt.isoformat(timespec="seconds"),
        finished_at=end_dt.isoformat(timespec="seconds"),
        total_elapsed_sec=round((end_dt - start_dt).total_seconds(), 2),
        sources=sources,
        daily_usage_mb=used,
        daily_limit_mb=limit,
        overall_status=overall,
    )
    # 存狀態
    _save_status(result)
    return result


def _save_status(result: UpdateResult):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_status() -> Optional[UpdateResult]:
    """讀上次更新狀態（給網頁顯示用）"""
    if not STATUS_PATH.exists():
        return None
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        # 反序列化
        sources = [SourceResult(**s) for s in data.pop("sources", [])]
        return UpdateResult(sources=sources, **data)
    except Exception:
        return None


def get_last_update_summary() -> dict:
    """給網頁快速查詢用"""
    st = load_status()
    if st is None:
        return {"has_data": False}
    return {
        "has_data": True,
        "started_at": st.started_at,
        "finished_at": st.finished_at,
        "total_elapsed_sec": st.total_elapsed_sec,
        "overall_status": st.overall_status,
        "n_success": sum(1 for s in st.sources if s.status == "success"),
        "n_error": sum(1 for s in st.sources if s.status == "error"),
        "n_total": len(st.sources),
        "daily_usage_mb": st.daily_usage_mb,
        "daily_limit_mb": st.daily_limit_mb,
    }


# === CLI 入口（給 launchd wrapper 呼叫） ===
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", nargs="*", default=None,
                        help="要更新的分組（不指定 = 全部）")
    parser.add_argument("--force", action="store_true", help="強制重新下載")
    parser.add_argument("--quiet", action="store_true", help="安靜模式（只印結果）")
    args = parser.parse_args()

    result = run_update(groups=args.groups, force=args.force)

    print(f"=== 更新完成：{result.overall_status} ===")
    print(f"耗時: {result.total_elapsed_sec:.1f}s")
    print(f"成功: {sum(1 for s in result.sources if s.status == 'success')}/{len(result.sources)}")
    if result.daily_usage_mb:
        print(f"當日用量: {result.daily_usage_mb:.0f}/{result.daily_limit_mb:.0f} MB")

    if not args.quiet:
        for s in result.sources:
            icon = "✅" if s.status == "success" else "❌"
            extra = f"({s.rows}×{s.cols}, {s.elapsed_sec}s)" if s.status == "success" else f"({s.error})"
            print(f"  {icon} [{s.group}] {s.label}: {extra}")
