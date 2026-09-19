#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
big_player_app.py — 💰 大戶買賣力 獨立 Streamlit 頁面

用途：單獨啟動此檔案，瀏覽器直接打開 http://127.0.0.1:8767 就能看到
（不必經過 V1 主介面的 10 個 page sidebar 切換）

啟動方式：
    /opt/anaconda3/envs/finlab3/bin/streamlit run big_player_app.py --server.port 8767

⚠️ finlab 沒有逐筆「特大單/大單」資料，此頁用集保庫存分級變化 + 成交量
當代理指標，僅供研究參考。
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
    page_title="大戶買賣力｜FinLab 集保代理指標",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# Optional sidebar 簡介
# ============================================================
with st.sidebar:
    st.header("💰 大戶買賣力")
    st.caption(
        "從 FinLab 集保 (inventory) 公開資料推算大戶週頻買賣力指標。"
    )
    st.markdown("""
**⚠️ 重要說明**

finlab 公開資料只有 inventory（集保庫存分級）+ price/volume，
**沒有逐筆「特大單/大單/中單/小單」資料**。

本頁用以下代理指標估算「大戶買賣力」：

- **大戶** = 持股分級 12-15 (約 400 張以上)
- **大戶買賣比** = `|大戶淨買| / 成交量` (大戶活動度)
- **大戶差比** = `大戶淨買 / 成交量` (大戶淨買方向)
- **5 週累計買賣力** = `5 週累計淨買 / 5 週累計成交量`

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
# Render 大戶買賣力頁面
# ============================================================
render_big_player_page()
