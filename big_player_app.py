#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
big_player_app.py — 💹 主力訊號 獨立 Streamlit 頁面

用途：單獨啟動此檔案，瀏覽器直接打開 http://127.0.0.1:8767 就能看到
（不必經過 V1 主介面的 sidebar 切換）

啟動方式：
    /opt/anaconda3/envs/finlab3/bin/streamlit run big_player_app.py --server.port 8767

⚠️ finlab 沒有逐筆「特大單/大單/內外盤/三大法人」資料，
本頁用融資買賣 (margin_transactions) 當代理指標，僅供研究參考。
"""
from __future__ import annotations

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st

from big_player_page import render_big_player_page


# ============================================================
# Page config（獨立頁面設定）
# ============================================================
st.set_page_config(
    page_title="主力訊號（融資買賣代理）",
    page_icon="💹",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# Optional sidebar 簡介
# ============================================================
with st.sidebar:
    st.header("💹 主力訊號")
    st.caption(
        "從 FinLab 融資買賣 (margin_transactions) 推算主力籌碼指標。"
    )
    st.markdown("""
**⚠️ 重要說明**

原始「主力 / 大戶買賣力」定義 = **當天逐筆內外盤方向**。

finlab 公開資料沒這資料：
- ❌ `price:內外盤` / `price:外盤量` / `price:內盤量`
- ❌ `institutional_investors:三大法人買賣超` / 外資 / 投信 / 自營商

**唯一可用日頻買賣方向 = 融資買賣**：
- 融資買進 / 融資賣出 / 融券買進 / 融券賣出

⚠️ 跟券商逐筆大單資料會有差異，僅供研究參考。

---

**啟動方式**

```bash
/opt/anaconda3/envs/finlab3/bin/streamlit run big_player_app.py \\
    --server.port 8767 --server.headless true
```
""")
    st.divider()
    st.caption("💡 直接關閉此頁不影響 V1 主介面 (port 8765) 或 V2 (port 8766)")


# ============================================================
# Render 主力訊號頁面
# ============================================================
render_big_player_page()

