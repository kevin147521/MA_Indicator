# 台股分析平台 (MA_Indicator)

個人用的台股量化分析平台，Streamlit + FinLab 5 個頁面：

1. **📈 均線預測** — 個股 K 線 + 5/10/20/60 MA，預測下個交易日收盤後均線
2. **🗺️ 市值漲跌地圖** — 全台股 treemap（市值/成交 vs 漲跌幅，台股配色）
3. **🧪 跌破站回回測** — 跌破 N MA 後要幾天才能站回並創新高
4. **💰 融資維持率** — 大盤融資維持率 + 上市/上櫃融資餘額 + 買賣超
5. **🔄 資料更新** — 手動按鈕 + launchd 21:20 自動排程

---

## 本地啟動

```bash
# 1. 確認 finlab 登入（會自動讀 ~/.finlab/credentials.json）
/opt/anaconda3/envs/finlab3/bin/python -c "import finlab; finlab.login()"

# 2. 啟動 streamlit
./start.command
# 或：/opt/anaconda3/envs/finlab3/bin/streamlit run app.py
```

開瀏覽器到 `http://127.0.0.1:8765`

---

## 對外發佈（Streamlit Community Cloud）

**前置**：
1. GitHub 帳號
2. 註冊 https://share.streamlit.io/
3. FinLab API token（或 finlab_config 模組，本機的 `~/.finlab/credentials.json` 在雲端不能直接用）

### 部署步驟

1. **推到 GitHub**
   ```bash
   cd ~/Desktop/排程運算/MA_Indicator
   git init  # 第一次
   git add .
   git commit -m "init"
   git remote add origin https://github.com/<你的帳號>/MA_Indicator.git
   git push -u origin main
   ```

2. **連結 Streamlit Cloud**
   - https://share.streamlit.io/ → New app
   - Repo：選剛推的 MA_Indicator
   - Branch：main
   - Main file path：`app.py`
   - Advanced settings → Python version：3.13（或 finlab 2.0.13 支援的版本）

3. **設定 Secrets**（finlab API token）
   - 點 app → Settings → Secrets
   - 貼上：
     ```toml
     FINLAB_API_TOKEN = "your_finlab_token_here"
     ```
   - 怎麼拿 token：登入 https://finlab.finance → Settings → API Token

4. **Deploy**
   - 點 Deploy
   - 第一次會跑 `pip install -r requirements.txt`（3~5 分鐘）
   - 之後 streamlit 會把 URL 給你，像 `https://<user>-ma-indicator.streamlit.app`

### 雲端限制 & 注意事項

- **1 GB RAM**：均線頁、treemap 頁 OK；「全市場均線回測」1089 檔 OK（前面實測），但「下載 58 萬筆事件 CSV」會 OOM，已用 `@st.dataframe(...head(500))` 限制
- **5000 MB/day quota**：`🔄 資料更新` 預設 `force=false`，**不會扣 quota**。勾「強制重抓」會在 1 分鐘內用 1000+ MB，每天只能用幾次
- **不要部署後馬上點「強制重抓」**：第一次部署 streamlit cloud 沒有 finlab cache，會從 finlab 抓 15 個 data source，**直接燒光 daily quota**
- **推薦流程**：部署完先到 `🔄 資料更新` 點「▶️ 立即更新」**不勾強制重抓**，用 finlab 內建 cache 跑（<5 秒），純顯示「已就緒」狀態

---

## 專案結構

```
MA_Indicator/
├── app.py                       # Streamlit 主程式（5 個 page 路由）
├── ma_engine.py                 # 均線計算純函式
├── ma_breakout_backtest.py      # 跌破/站回事件偵測
├── margin_page.py               # 融資維持率
├── treemap_page.py              # 全市場 treemap
├── data_fetcher.py              # finlab 抓資料 + ensure_finlab_login
├── data_update.py               # 排程手動 finlab 資料更新
├── start.command                # 本機雙擊啟動
├── stop.command                 # 本機雙擊停止
├── requirements.txt             # Python 套件
└── .gitignore                   # 排除 __pycache__ / .streamlit/secrets
```

---

## 開發注意事項

- `data_fetcher.ensure_finlab_login()` 是所有 page 抓資料前的統一入口
  - 本地：讀 `~/.finlab/credentials.json`（finlab 2.x 自動處理）
  - 雲端：讀 `st.secrets["FINLAB_API_TOKEN"]`
  - 都找不到才 fall back 到 `finlab.login()` 互動
- `treemap_page.return_ratio` 基準日 = `close_data.iloc[0]`（區間累計），不要用 `iloc[-2]`（會誤算單日）
- `margin_page.build_margin_data` / `plot_margin_trend` 都有 `start > end` 自動 swap（避免 plotly 噴 index out of bounds）

---

## FinLab login 設定細節

`ensure_finlab_login()` 順序（**雲端跟本地都通用**）：

1. `from finlab_config import login_finlab`（自定模組，本地專用）
2. `st.secrets["FINLAB_API_TOKEN"]`（**Streamlit Cloud 設這裡**）
3. `os.environ["FINLAB_API_TOKEN"]`（環境變數，CLI 用）
4. `~/.finlab/credentials.json`（finlab 2.x 自動讀，本機有跑過 `finlab.login()` 就有）
5. `finlab.login()` 互動登入（fallback）
