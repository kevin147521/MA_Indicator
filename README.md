# 台股分析平台 (MA_Indicator) 📊

個人用的台股量化分析平台，**Streamlit + FinLab**，**11 個頁面**。

V2 (備份用) 在 [MA_Indicator_V2](../MA_Indicator_V2) 子資料夾（5 個核心 page 簡化版）。

---

## 🚀 快速啟動 (公司用)

```bash
# 1. Clone repo
git clone https://github.com/kevin147521/MA_Indicator.git
cd MA_Indicator

# 2. 建立 finlab3 conda env (跟 dev 環境一致)
conda create -n finlab3 python=3.13 -y
conda activate finlab3
pip install -r requirements.txt

# 3. 設定 finlab 登入 (選一種)
#    (a) 互動登入:  python -c "import finlab; finlab.login()"
#    (b) 環境變數:  export FINLAB_API_TOKEN=your_token
#    (c) 加密檔:    python -c "from finlab_config import login_finlab; login_finlab()"

# 4. 啟動 streamlit
streamlit run app.py --server.port 8765 --server.headless true
# 開瀏覽器 http://localhost:8765
```

公司用建議：
- 用 **`ngrok` / `cloudflared` tunnel** 從公司外部訪問 (參考 `~/.openclaw/jobs/holders-public.sh` SOP)
- 或在 **公司內網 server** 跑 `nohup streamlit run app.py` + 開放 port

---

## 📑 11 個 Pages (sidebar radio)

### 1. 📈 **均線預測** — 個股 K 線 + 5/10/20/60 MA
- 預測下個交易日收盤後均線
- 支援日K/週K 切換
- 寶塔線 (單日/三日轉向) 對照

### 2. 🗺️ **市值漲跌地圖** — 全台股 treemap
- 階層：市場 → 產業 → 個股
- 方塊大小 = 市值 / 顏色 = 漲跌幅 (台股紅漲綠跌)
- 排行 sub-tab: 漲幅前 20 / 跌幅前 20 (含當日/3日 成交金額)

### 3. 📊 **主動 ETF 持股** — etfinfo.tw 公開 API
- 40 檔主動 ETF + 117 個股加碼排行
- 26 共識訊號 + 20 產業資金流 + 今日異動

### 4. 📊 **被動 ETF 追蹤** — 26 檔台股主流被動 ETF
- 折溢價 + 持股

### 5. 🔍 **均線收復** — 全市場掃描
- 「曾跌破 MA，後續收復且 MA60 往上」個股
- 含 K 線展開 + 市值排序

### 6. 🧪 **跌破站回回測**
- 跌破 N MA 後要幾天才能站回並創新高

### 7. 💰 **融資維持率**
- 大盤融資維持率 + 上市/上櫃融資餘額 + 買賣超

### 8. 🧬 **基因策略組合** — 從 FinLab notebook 抽出
- 📚 預設組合: 16 個 best cond combo (CAGR 138.5%~200.6%)
- 🧪 自訂組合: 41 個條件按 9 個分類 checkbox 自由勾選
- 💼 Portfolio 組合: 4 策略 1/4 等權重
- 🎲 蒙地卡羅壓力測試: bootstrap 95/97.5/99/99.7% 分位 Sortino/Omega 衰減

### 9. 💹 **主力訊號** (重寫) — 融資買賣代理 + 三大法人
- 融資買賣 (margin_transactions) 當「主力 / 槓桿買方」代理
- 三大法人: 外資/投信/自營商 當日/3日/5日 累計淨買超
- 個股查詢 + 全市場掃描 + 整體市值排名

⚠️ finlab 公開資料**沒有**「逐筆大單/特大單/內外盤」，本頁用融資淨買當代理指標，跟券商逐筆大單會有差異，僅供研究參考。

### 10. 📐 **金包銀形態掃描** (新式形態學 SOP)
- **日K 模式**: K 線 + 60/120/240 MA 夾擊 + 量縮 + 突破 + 長紅 4 條件評分
- **60分K 模式**: 用 finlab 內建 `tw_price_60min:*` (從 2026-01-02 起, 187 個交易日, 935 根)
  - 預設 SOP 60/120/240 棒 (對應日K 60/120/240MA 概念)
  - MA 60 (短線) / 120 (中線) / 240 (長線)
  - 4 種訊號: 🟢 突破表態 / 🟢 突破後回踩 / 🟡 量縮整理 / ⚪ 觀察
- 完整明細表: 收盤 + 當日/3日 漲跌% + 當日/3日 金額(億) + 張數 + MA + 夾擊帶寬度 + 突破 + 三大法人
- **📊 個股量價技術表**: 從 scan 結果或手動輸入個股代號，顯示 60分K K棒 + MA + 成交量 (5 個關鍵指標 + scan 結果對照)

### 11. 🔄 **資料更新**
- 手動按鈕 + launchd 21:20 自動排程 (Finlab 日頻 + 60分K)
- finlab OAuth/cert 認證統一從 `finlab_config.login_finlab()`

---

## 🔐 Finlab 登入統一入口

`finlab_config.py` 三級優先：
1. `FINLAB_API_TOKEN` 環境變數
2. `~/.finlab/credentials.json` (Fernet 加密, chmod 600)
3. 互動登入 (第一次會問)

`Streamlit Cloud` deploy 可用 `st.secrets["FINLAB_API_TOKEN"]` (見 `data_fetcher.py`)。

---

## 📦 技術棧

- **Python 3.13** (conda env `finlab3`)
- **Streamlit >= 1.30** — Web UI
- **finlab >= 2.2.11** — 台股資料 API (注意：2026-10-14 升級消 "Your version is 2.2.10" 警告)
- **Plotly >= 5.18** — K 線圖 / treemap / 量價技術表
- **pandas / numpy**

---

## 📁 專案結構

```
MA_Indicator/
├── app.py                          # Streamlit 主入口 (含 11 個 page 路由)
├── golden_silver.py                # 金包銀型態演算法 (日K + 60分K scan)
├── golden_silver_page.py           # 金包銀 page UI (含個股量價技術表)
├── kbar_fetcher.py                 # 60分K 抓取 (用 finlab 內建 tw_price_60min)
├── big_player.py / big_player_page.py
├── ma_engine.py / ma_recovery_scanner.py
├── portfolio_strategy.py / portfolio_strategy_page.py
├── etf_holdings_page.py / passive_etf_page.py
├── margin_page.py
├── data_fetcher.py / data_update.py
├── barchart_engine.py / ma_breakout_backtest.py
├── finlab_config.py                # 統一登入入口
├── requirements.txt
├── .gitignore                      # 過濾 .log / .command / .feather / .env
├── pages/_v1_compat/               # V2 共用 module (B 方案備份)
├── data/                           # 快取 (gitignored)
└── logs/                           # 本機 log (gitignored)
```

---

## ⚠️ 已知限制

- **finlab 沒有** 逐筆大單/特大單/內外盤 → 主力訊號 page 用融資買賣當代理
- **60分K finlab 內建** 從 2026-01-02 起, 187 個交易日, 935 根 (5 根/天, 10:00/11:00/12:00/13:00/13:33)
- **中小型股** finlab `tw_minute` 90 天回溯會報 "Request between 1 and 31 days" (覆蓋率不足, 用 7 天範圍 fallback)
- **finlab `tw_price_60min:成交量`** 5 根加總 ≠ 整天, 算整天金額用日頻 `price:成交股數 × price:收盤價`

---

## 📝 Changelog (重要 commit)

- `cfb1e53` V1 60分K 每日增量 (reverted: 改用 finlab 內建)
- `7897227` 金包銀 page 加 60分K 模式
- `60bc1d0` 金包銀明細表加三大法人 9 欄
- `5698504` 金包銀 page (新式形態學 SOP)
- `16ec3b0` 主力訊號 page 重寫
- `3e1c027` 整體市值排名加當日成交金額
- (2026-10-14) finlab `tw_price_60min` 從 9/1 擴展到 1/2 (完整 SOP 60/120/240 支援)
- (2026-10-14) 金包銀加 6 個欄位: 當日/3日 漲跌% / 金額(億) / 張數
- (2026-10-14) 加 📊 個股量價技術表 (K 棒 + MA + 成交量)
- (2026-10-14) 加 當日/3日 成交金額(億) 到市值漲跌地圖 + 金包銀完整明細表

---

## 🔒 隱私

- ✅ 無 API key / token / 密碼 hardcode (都用 `st.secrets` / env / `finlab_config`)
- ✅ `.gitignore` 過濾 `.streamlit/secrets.toml` / `*.log` / `*.feather` / `.env`
- ✅ 用戶端登入 finlab 走 OAuth 流程, 不存個資
