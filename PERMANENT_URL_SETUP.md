# 🌐 永久網址 + 本機託管完整手冊

目標：讓這台 Mac 當 host，提供**永久固定網址**、**無流量限制**、**FinLab 不用定期更新 token**。

---

## 📌 現在的狀態（2026-10-25 已完成）

| 項目 | 狀態 |
|---|---|
| **永久網址** | ✅ **`https://ma.kevin14752.com`**（Cloudflare named tunnel，永不變）|
| **入口頁** | ✅ `https://kevin147521.github.io/fomo-archive/` → 「台股量化分析平台」卡片 |
| **卡片連結指向** | ✅ `https://ma.kevin14752.com` |
| **本機 Streamlit** | ✅ launchd 管理，開機自啟 + 崩潰重啟 |
| **本機 tunnel** | ✅ quick tunnel（網址會變）|
| **FinLab 認證** | ✅ `~/.finlab/credentials.json` 自動續期，**不用手動更新** |

### 為什麼 Streamlit Cloud 不是最佳解

| 限制 | 影響 |
|---|---|
| 記憶體 1GB | 金包銀全市場掃描會 OOM |
| 閒置 3 天休眠 | 同事第一次開要等 1-2 分鐘 |
| 共享 0.5 CPU | 抓 FinLab 資料慢 |
| **FinLab 憑證會過期** | 要定期去 Streamlit secrets 換三個 token ❌ |

**本機跑完全沒這些問題** — 記憶體 unlimited、FinLab session 自動續期（實測驗證過）。

---

## ✅ 已完成的設定紀錄（2026-10-25）

- 網域：`kevin14752.com`（nameserver: clay.ns.cloudflare.com / bailey.ns.cloudflare.com）
- Tunnel：`ma-indicator`，ID `1064122b-6d7e-485f-9b4d-67cc347a799f`
- 設定檔：`~/.cloudflared/config.yml` → `ma.kevin14752.com` → `http://localhost:8765`
- launchd：`ai.stockslaves.cf-tunnel-named`（開機自啟 + 崩潰重啟）
- 憑證：`~/.cloudflared/cert.pem` + `~/.cloudflared/1064122b-*.json`（**勿外流**）
- 舊的 quick tunnel（`ai.stockslaves.cf-tunnel`）已停用，保留作備援

## 📖 原始設定流程（重跑用）

### Step 1 — 註冊網域

**建議 Cloudflare Registrar**（成本價，無註冊商加價，DNS 與 tunnel 都在同一個地方）

1. 到 https://dash.cloudflare.com 註冊／登入（免費）
2. **Register a Domain** → 搜尋想要的網域
3. 建議網域：`ma-量化.com` 不好記，推薦 `fomo-量化.tw` 或英文 `fomosoc.tw` / `fomo-tools.com`
   - `.com` ~NT$400/年、`.tw` ~NT$800/年、`.dev`/`.app` 較便宜
4. 付款

### Step 2 — 把網域指向 Cloudflare

1. Cloudflare 後台 → 選網域 → **Overview** → 會給你 2 個 nameserver
   ```
   例如: anna.ns.cloudflare.com
         brian.ns.cloudflare.com
   ```
2. 到網域註冊商（Cloudflare Registrar 就直接在 **Account → Domain Details → Nameservers** 改）
3. 把 nameserver 改成上面兩個
4. **等 DNS 傳播，通常 5 分鐘～數小時**

### Step 3 — 一鍵設定 tunnel

```bash
bash ~/.openclaw/jobs/setup_named_tunnel.sh <你的網域> ma
```

例如網域是 `fomo-tools.com`：

```bash
bash ~/.openclaw/jobs/setup_named_tunnel.sh fomo-tools.com ma
```

腳本會自動完成：
1. `cloudflared tunnel login`（開瀏覽器授權 → 選你的網域）
2. 建立 tunnel `ma-indicator`
3. 寫 `~/.cloudflared/config.yml`（指向 `localhost:8765`）
4. `tunnel route dns` 綁 `ma.fomo-tools.com`
5. 裝好 launchd（開機自啟 + 崩潰重啟）
6. 驗證網址

**完成後永久網址**：
```
https://ma.fomo-tools.com
```

---

## 🔄 換掉入口頁的連結

網域搞定後，把 `fomo-archive/index.html` 裡的連結換掉：

```bash
cd ~/.mavis/tmp/fomo-archive
# 或重新下載
curl -s https://raw.githubusercontent.com/kevin147521/fomo-archive/main/index.html -o index.html
```

把
```html
href="https://kevin-taiwan-stocks.streamlit.app"
```
改成
```html
href="https://ma.fomo-tools.com"
```

然後用 GitHub API 提交（repo 1.7GB，不要用 git clone）：

```bash
python3 - << 'PY'
import base64, json, os, urllib.request
TOKEN = "你的 GitHub PAT"
api = "https://api.github.com/repos/kevin147521/fomo-archive/contents/index.html"
h = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json"}
with urllib.request.urlopen(urllib.request.Request(api, headers=h), timeout=30) as r:
    sha = json.load(r)["sha"]
new = open("index.html", "rb").read()
data = json.dumps({
    "message": "chore: 入口連結改為永久網域",
    "content": base64.b64encode(new).decode(),
    "branch": "main", "sha": sha,
}).encode()
req = urllib.request.Request(api, data=data, method="PUT",
    headers={**h, "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=90) as r:
    print("✓ 已提交:", json.load(r)["commit"]["sha"][:7])
PY
```

---

## 🔧 日常維運

```bash
# 看目前網址
head -1 ~/.openclaw/CURRENT_TUNNEL_URL.txt

# 服務狀態
launchctl list | grep -E "ai.stockslaves.(streamlit|cf-tunnel)"

# 重啟 streamlit
launchctl kickstart -k gui/$UID/ai.stockslaves.streamlit

# 重啟 tunnel
launchctl kickstart -k gui/$UID/ai.stockslaves.cf-tunnel-named

# 看 tunnel log
tail -f ~/.openclaw/logs/cf-tunnel-named.stderr.log

# 停掉對外通道
launchctl bootout gui/$UID/ai.stockslaves.cf-tunnel-named
```

---

## ⚠️ 注意事項

### 1. Mac 必須開著
本機託管的本質就是「你的電腦當伺服器」。Mac 關了就斷。
- 已設定 `sleep 0`（接電源不自動睡眠）✅
- **合上蓋子仍會睡** → 插假充電線，或 `sudo pmset -a disablesleep 1`

### 2. 網路中斷
Cloudflare tunnel 會自動重連（KeepAlive），網網重連後網址不變（named tunnel 的優點）。

### 3. FinLab quota
共用 5000 MB/天。每日 20:20 排程會抓一次 FGI 資料。

---

## 📁 相關檔案

| 檔案 | 說明 |
|---|---|
| `~/Library/LaunchAgents/ai.stockslaves.streamlit.plist` | Streamlit 服務 |
| `~/Library/LaunchAgents/ai.stockslaves.cf-tunnel.plist` | quick tunnel（備援）|
| `~/Library/LaunchAgents/ai.stockslaves.cf-tunnel-named.plist` | named tunnel（永久）|
| `~/.openclaw/jobs/run_streamlit.sh` | Streamlit 啟動腳本 |
| `~/.openclaw/jobs/cf_tunnel.sh` | quick tunnel 腳本 |
| `~/.openclaw/jobs/setup_named_tunnel.sh` | **named tunnel 設定腳本** |
| `~/.openclaw/jobs/daily_data_update.sh` | 每日資料更新（20:20）|
| `~/.openclaw/CURRENT_TUNNEL_URL.txt` | 目前網址 |
| `~/.cloudflared/config.yml` | tunnel 設定 |
