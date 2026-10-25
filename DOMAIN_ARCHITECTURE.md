# 🌐 kevin14752.com — 專案網域架構

三個永久網址，全部跑在這台 Mac 上，透過 Cloudflare Named Tunnel 對外。

---

## 網址一覽

| 網址 | 服務 | Port | 說明 |
|---|---|---|---|
| `https://all.kevin14752.com` | **專案彙整入口** | 8502 | 密碼鎖（`kevin` / `kevin888`）|
| `https://ma.kevin14752.com` | 台股分析平台 | 8765 | MA_Indicator，12 個 page |
| `https://collect.kevin14752.com` | 集保大戶持股查詢 | 8501 | holders_app |
| `https://kevin147521.github.io/fomo-archive/` | FOMO 文章索引 | — | GitHub Pages（靜態）|

**另外**：`https://kevin-taiwan-stocks.streamlit.app` → Streamlit Cloud 版（備援，非主力）

---

## 架構圖

```
                 網際網
                    │
        ┌───────────┴───────────┐
        │  Cloudflare Edge      │
        │  (DNS + TLS + 流量)     │
        └───────────┬───────────┘
                    │  Named Tunnel (單一 tunnel, 多 hostname)
                    │
    ┌───────────────┼───────────────┐
    │               │               │
    ▼               ▼               ▼
ma.kevin…     collect.kevin…   all.kevin…
:8765              :8501            :8502
    │               │               │
    ▼               ▼               ▼
MA_Indicator   holders_app    all_portal
(12 pages)    (集保大戶)     (靜態 + Basic Auth)
```

---

## 服務管理

四個 launchd 服務，**開機自啟 + 崩潰自動重啟**：

| 服務名 | 作用 | 專案 |
|---|---|---|
| `ai.stockslaves.streamlit` | 台股分析平台 | `/Users/kevin/Desktop/排程運算/MA_Indicator` |
| `ai.stockslaves.holders-streamlit` | 集保大戶持股 | `/Users/kevin/Desktop/排程運算/holders_app` |
| `ai.stockslaves.all-portal` | 彙整入口 | `~/.openclaw/jobs/serve_all_portal.py` |
| `ai.stockslaves.cf-tunnel-named` | Cloudflare Tunnel | `~/.cloudflared/config.yml` |
| `ai.stockslaves.daily-data-update` | 每日 20:20 資料更新 | 排程 |

### 常用指令

```bash
# 全部服務狀態
launchctl list | grep ai.stockslaves

# 單獨重啟
launchctl kickstart -k gui/$UID/ai.stockslaves.streamlit
launchctl kickstart -k gui/$UID/ai.stockslaves.holders-streamlit
launchctl kickstart -k gui/$UID/ai.stockslaves.all-portal
launchctl kickstart -k gui/$UID/ai.stockslaves.cf-tunnel-named

# 健康檢查
curl -s -o /dev/null -w "%{http_code}\n" https://ma.kevin14752.com
curl -s -o /dev/null -w "%{http_code}\n" https://collect.kevin14752.com
curl -s -o /dev/null -w "%{http_code}\n" -u kevin:kevin888 https://all.kevin14752.com

# 看 log
tail -f ~/.openclaw/logs/holders-streamlit.stderr.log
tail -f ~/.openclaw/logs/all-portal.stderr.log
tail -f ~/.openclaw/logs/cf-tunnel-named.stderr.log
```

---

## 新增第 4 個網域的做法

1. 在 `~/.cloudflared/config.yml` 的 ingress 加一段（放在 `http_status:404` **之前**）：
   ```yaml
     - hostname: new.kevin14752.com
       service: http://localhost:8503
   ```
2. 綁 DNS：
   ```bash
   cloudflared tunnel route dns 1064122b-6d7e-485f-9b4d-67cc347a799f new.kevin14752.com
   ```
3. 重啟 tunnel：
   ```bash
   launchctl kickstart -k gui/$UID/ai.stockslaves.cf-tunnel-named
   ```

---

## 密碼鎖說明

`all.kevin14752.com` 用 **HTTP Basic Auth**（伺服器端驗證）。

- 帳號：`kevin`
- 密碼：`kevin888`
- 儲存位置：`~/.openclaw/jobs/serve_all_portal.py` 的 `PASSWORD_SHA256`（SHA-256，不存明文）

### 改密碼

```bash
# 1. 算新 hash
python3 -c "import hashlib; print(hashlib.sha256(b'新密碼'.encode()).hexdigest())"

# 2. 貼到 serve_all_portal.py 的 PASSWORD_SHA256

# 3. 重啟
launchctl kickstart -k gui/$UID/ai.stockslaves.all-portal
```

⚠️ **realm 欄位不能放中文** — HTTP header 只支援 latin-1，放中文會讓伺服器直接崩（已踩過）。

---

## ⚠️ 注意事項

### 1. Mac 必須開著
本機託管的本質。已設定 `sleep 0`（接電源不自動睡眠），但**合上蓋子仍會睡**。
需要合蓋使用：`sudo pmset -a disablesleep 1`

### 2. 憑證位置（勿外流、勿推 GitHub）
- `~/.cloudflared/cert.pem` — Cloudflare 帳號憑證
- `~/.cloudflared/1064122b-6d7e-485f-9b4d-67cc347a799f.json` — tunnel 憑證

### 3. FinLab 認證
本機走 `~/.finlab/credentials.json` 的 OAuth session，**會自動續期，不用手動更新**。
（這是選本機託管而非 Streamlit Cloud 的主因之一。）

### 4. 端口對照
- 8765 — MA_Indicator
- 8501 — holders_app
- 8502 — all_portal
- 8765 也被舊的 quick tunnel 用過，現在 named tunnel 取代

---

## 相關檔案

| 檔案 | 說明 |
|---|---|
| `~/.cloudflared/config.yml` | Tunnel 設定（三個 hostname → 三個 port）|
| `~/.openclaw/jobs/serve_all_portal.py` | 彙整入口伺服器（Basic Auth）|
| `~/.openclaw/jobs/all_portal/index.html` | 彙整入口頁面 |
| `~/.openclaw/jobs/run_streamlit.sh` | MA_Indicator 啟動腳本 |
| `~/.openclaw/jobs/run_holders_streamlit.sh` | holders_app 啟動腳本 |
| `~/.openclaw/jobs/setup_named_tunnel.sh` | tunnel 設定腳本 |
| `~/Library/LaunchAgents/ai.stockslaves.*.plist` | 四個服務設定 |
| `~/.openclaw/logs/*.log` | 各種日誌 |
