# 🌐 遠端連線使用說明

## 一、公司要用的網址在哪？

隨時打開這個檔案看最新網址：

```
~/.openclaw/CURRENT_TUNNEL_URL.txt
```

快速看（Terminal）：

```bash
head -1 ~/.openclaw/CURRENT_TUNNEL_URL.txt
```

**公司電腦**：開瀏覽器貼上網址 → 就能用整個互動網頁（均線預測、ETF、金包銀掃描、FGI Dashboard…）

---

## 二、網址會變，why？

用的是 **Cloudflare quick tunnel**（免註冊免帳號），特性是：

| | 狀態 |
|---|---|
| 開機自動啟動 | ✅ 已設定 |
| 斷線自動重連 | ✅ 已設定（KeepAlive，實測 45 秒內恢復）|
| 網址固定 | ❌ **每次重啟會換** |

換網址的三種情況：
1. Mac 重開機
2. cloudflared 被殺掉後自動重連
3. 網路斷線重連

---

## 三、Mac 剛開機怎麼做？

**答案是：什麼都不用做。** 三個服務全部設成 launchd 自動啟動：

| 服務 | 作用 | 開機自動啟動 | 崩潰自動重啟 |
|---|---|---|---|
| `ai.stockslaves.streamlit` | Streamlit 本體 (port 8765) | ✅ | ✅ |
| `ai.stockslaves.cf-tunnel` | Cloudflare 對外通道 | ✅ | ✅ |
| `ai.stockslaves.daily-data-update` | 每日 20:20 更新資料 | — | — |

三個都是 `RunAtLoad=true` + `KeepAlive=true`，開機就會自己起來。

### 那還要開著電腦嗎？

**要。** 這是架構上的限制：網址是你的 Mac 轉出去的，Mac 關了就斷。

| 狀態 | 網頁能不能用 |
|---|---|
| Mac 開著 + 接電源 | ✅ 可以 |
| Mac 開著 + 接電源 + **合上蓋子** | ❌ **會睡著就斷** |
| Mac 睡著 / 關機 | ❌ 斷 |
| Mac 重開機 | ✅ 但**網址會變** |

### ⚠️ 兩件要注意的事

**1. 合上筆電蓋子會斷**
你目前的設定（`pmset -g custom` 顯示 `sleep 0`）是「接電源時不自動睡眠」，
但**合上蓋子還是會睡**。如果你要合蓋使用，需要插一個 dummy 電源（USB-C 接頭的假充電線），
或是設定「閉蓋不睡」：

```bash
sudo pmset -a disablesleep 1   # 需要密碼
```

**2. 網址會變**
Mac 重開機後網址一定會變。開會前先看：

```bash
head -1 ~/.openclaw/CURRENT_TUNNEL_URL.txt
```

---

## 四、怎麼確認現在是好的？

```bash
# 1. streamlit 活著嗎
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765
#   → 200 才對

# 2. tunnel 活著嗎
curl -s -o /dev/null -w "%{http_code}\n" $(head -1 ~/.openclaw/CURRENT_TUNNEL_URL.txt)

# 3. 看 log
tail -20 ~/.openclaw/logs/cf-tunnel-ma-indicator.stdout.log
```

---

## 五、想改成永久固定網址？

現在的做法能用，但如果想要「固定網址、Mac 重開也不變」，有兩條路：

### 方案 A：Streamlit Community Cloud（免費，推薦）

**好處**：網址永久固定（`xxx.streamlit.app`）、不用開 Mac、公司直接開

**前提**：
1. 程式碼推到 GitHub（**必須 public**，免費版限制）
2. FinLab API token 放進 Streamlit secrets

**步驟**：
1. 去 https://share.streamlit.io 登入 GitHub（⚠️ 不是從 repo 頁面點進去，很多人卡在這）
2. 選 "Deploy a new app" → 選你的 GitHub repo
3. 到 App settings → Secrets → 加 `FINLAB_API_TOKEN`
4. Deploy

**注意**：token 會存在雲端，且 repo 程式碼會公開

### 方案 B：Cloudflare Named Tunnel（需網域）

**好處**：網址固定（如 `ma.yourdomain.com`）、可綁自己的網域

**前提**：Cloudflare 帳號 + 一個網域（~NT$100/年）

---

## 六、Troubleshooting

### 公司開不起來 / 顯示 can't reach
1. 確認 Mac 沒睡（`caffeinate` 可以防止睡眠）
2. 看 `CURRENT_TUNNEL_URL.txt` 有沒有更新
3. 公司那邊試試無痕視窗（有時 DNS 快取）

### tunnel 一直重連
多半是 streamlit 沒跑。先開 streamlit 再開 tunnel。

### 想暫時關掉對外通道（不想被連）
```bash
launchctl bootout gui/$UID/ai.stockslaves.cf-tunnel
```

### 想恢復
```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/ai.stockslaves.cf-tunnel.plist
```

---

## 相關檔案

| 檔案 | 說明 |
|---|---|
| `~/Library/LaunchAgents/ai.stockslaves.streamlit.plist` | Streamlit 服務設定 |
| `~/Library/LaunchAgents/ai.stockslaves.cf-tunnel.plist` | tunnel 服務設定 |
| `~/Library/LaunchAgents/ai.stockslaves.daily-data-update.plist` | 每日資料更新 |
| `~/.openclaw/jobs/run_streamlit.sh` | Streamlit 啟動腳本 |
| `~/.openclaw/jobs/cf_tunnel.sh` | tunnel 啟動腳本（抓網址寫檔）|
| `~/.openclaw/CURRENT_TUNNEL_URL.txt` | **目前網址** |
| `~/.openclaw/logs/streamlit-ma-indicator.*.log` | Streamlit 日誌 |
| `~/.openclaw/logs/cf-tunnel-ma-indicator.*.log` | tunnel 日誌 |

## 手動操作速查

```bash
# 看目前網址
head -1 ~/.openclaw/CURRENT_TUNNEL_URL.txt

# 查看所有服務
launchctl list | grep ai.stockslaves

# 重啟 streamlit
launchctl kickstart -k gui/$UID/ai.stockslaves.streamlit

# 重啟 tunnel（網址會變）
launchctl kickstart -k gui/$UID/ai.stockslaves.cf-tunnel

# 暫停對外通道
launchctl bootout gui/$UID/ai.stockslaves.cf-tunnel
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/ai.stockslaves.cf-tunnel.plist

# 停掉 streamlit（會省記憶體，但網頁就不能用）
launchctl bootout gui/$UID/ai.stockslaves.streamlit
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/ai.stockslaves.streamlit.plist
```

⚠️ **踩坑紀錄**：`launchctl bootout` 之後要用 `bootstrap` 重新載入，
但非 GUI session（Mavis/agent）有時會遇到 `Bootstrap failed: 5: Input/output error`（TCC 權限）。
遇到就重試一次，通常第二次會成功。