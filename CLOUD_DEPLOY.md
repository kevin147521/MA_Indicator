# ☁️ Streamlit Cloud 部署指南（固定網址）

目標：部署到 Streamlit Community Cloud，拿到**永久固定網址**（`xxx.streamlit.app`），
**Mac 不用開、公司隨時能連**。

---

## 前置：產生 FinLab 憑證（在你的 Mac 上做一次）

FinLab 2.2.13+ 已經取消舊的 API token 方式，改用 OAuth。
官方針對「無瀏覽器的環境（伺服器、排程）」提供三個環境變數。

在 Terminal 執行：

```bash
python -m finlab token --env
```

會印出三行（**這三行要保密，不要貼到公開的地方**）。格式長這樣：

```bash
export FINLAB_REFRESH_TOKEN="<你的 refresh token>"
export FINLAB_SESSION_ID="<你的 session id>"
export FINLAB_API_KEY="<你的 api key>"
```

> ⚠️ 上面的 `<...>` 是佔位符，要用你實際跑出來的值替換。

**驗證方式**（確認這三個真的能用）：

```bash
eval "$(python -m finlab token --env)"   # 載入到當前 session
python -c "from finlab import data; print(data.get('world_index:close').shape)"
```

如果印出 `(2947, 35)` 之類的 shape，就對了。

---

## 部署步驟

### Step 1 — 把 repo 改成 public

免費版 Streamlit Cloud **只接受 public repo**。

1. 到 https://github.com/kevin147521/MA_Indicator/settings
2. 捲到最下面 **Danger Zone**
3. 選 **Change visibility → Public** → 確認

> ⚠️ 這會讓程式碼公開。但 `.gitignore` 已排除 `secrets.toml`，
> 憑證**不會**被推上去（我們用的是 Streamlit Cloud 的加密 secrets）。

### Step 2 — 開 Streamlit Cloud

1. 到 **https://share.streamlit.io** ← 從這裡進去，不是從 repo 頁面
2. 用 **GitHub 帳號**登入授權
3. 點 **"New app"** 或 **"Deploy a new app"**

### Step 3 — 選擇 repo

- **Repository**: `kevin147521/MA_Indicator`
- **Branch**: `main`
- **Main file path**: `app.py`

點 **Deploy**。

### Step 4 — 設定 FinLab 憑證（關鍵步驟）

部署後會給你一個網址 `https://xxx.streamlit.app`。

1. 進到那個網址
2. 右上角 **≡ 選單** → **Settings**
3. 切到 **Secrets** 分頁
4. 貼上這三行（把你剛才產生的真實值填進去）：

```toml
FINLAB_REFRESH_TOKEN = "<你的 refresh token>"
FINLAB_SESSION_ID   = "<你的 session id>"
FINLAB_API_KEY      = "<你的 api key>"
```

5. 按 **Save**
6. 點 **Rerun** 或等它自動重啟

---

## 完成後

你會有一個**永久固定網址**，長得像：

```
https://ma-indicator-xxxx.streamlit.app
```

- ✅ Mac 關了也能用（雲端在跑）
- ✅ 重開機網址不變
- ✅ 直接丟給同事，不用先開機

---

## 常見問題

### Q: 部署後頁面顯示 FinLab 登入失敗？

檢查 Secrets 有沒有設定三個值（**三個都要，一個都不能少**）。

### Q: 抓不到資料 / 顯示 NaN？

Streamlit Cloud 免費版有資源限制（記憶體 ~1GB）。
某些頁面（金包銀掃描全市場、基因策略組合）吃記憶體，可能會 OOM。
可以在 Settings → Advanced 調整 resource，但免費版上限較低。

### Q: 會不會洩漏我的 FinLab 帳號？

Secrets 是加密存在 Streamlit 的資料庫裡，**不會**出現在 repo。
但要確保：
- `.gitignore` 排除 `.streamlit/secrets.toml` ✅（已設定）
- 不要把 `python -m finlab token --env` 的輸出貼到 GitHub issue 或公開聊天

### Q: 怎麼更新線上版本？

本機改完 → `git push` → Streamlit Cloud 會自動偵測並重新部署。

### Q: 台灣/日本/韓國 FGI 的 2026-01-02 之前資料？

雲端版第一次啟動會現抓 FinLab，暖機期會現算，可能要等 1-2 分鐘。

---

## 與本機版並存

兩邊可以同時跑，不衝突：

| | 本機版 | 雲端版 |
|---|---|---|
| 網址 | `localhost:8765` / cloudflared tunnel | `xxx.streamlit.app` |
| 需要開 Mac | ✅ 要 | ❌ 不用 |
| 網址固定 | ❌ tunnel 會變 | ✅ 永久 |
| FinLab 認證 | `~/.finlab/credentials.json` | 三個 secrets |
| 更新 | 手動 restart | `git push` 自動 |