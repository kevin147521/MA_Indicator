#!/bin/bash
# start.command — 雙擊啟動均線預測平台
# 路徑：~/Desktop/排程運算/MA_Indicator/start.command

# 切到本檔所在目錄（雙擊 Finder 跑時預設是 $HOME，這樣保險）
cd "$(dirname "$0")"

# 固定 port（之後 stop.command 才能找得到）
PORT=8765
APP="app.py"
LOG="/tmp/ma_indicator_streamlit.log"

# 找 finlab3 的 python（沿用 .py 第一行慣例）
PY="/opt/anaconda3/envs/finlab3/bin/python"
STREAMLIT="/opt/anaconda3/envs/finlab3/bin/streamlit"

# 先檢查 streamlit 有沒有裝好
if [ ! -x "$STREAMLIT" ]; then
  osascript -e 'display alert "找不到 streamlit" message "請確認 /opt/anaconda3/envs/finlab3/bin/streamlit 是否存在" as critical'
  exit 1
fi

# 檢查 port 有沒有人佔用，佔了先叫使用者決定
if lsof -ti tcp:$PORT > /dev/null 2>&1; then
  CHOICE=$(osascript -e 'button returned of (display alert "Port '$PORT' 已被佔用" message "可能之前啟動的還在跑，要直接覆蓋嗎？" buttons {"取消", "強制重啟"} default button "強制重啟" cancel button "取消")')
  if [ "$CHOICE" != "強制重啟" ]; then
    exit 0
  fi
  # 砍掉舊的
  lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null
  sleep 1
fi

# 開瀏覽器（背景延遲，等 server 起來再開）
(sleep 3 && open "http://127.0.0.1:$PORT") &

# 啟動 streamlit（nohup + & 讓 script 結束後 server 還在跑）
nohup "$STREAMLIT" run "$APP" \
  --server.port $PORT \
  --server.headless true \
  --server.address 127.0.0.1 \
  --browser.gatherUsageStats false \
  > "$LOG" 2>&1 &

# 把 PID 寫到檔案，方便 stop.command 用
echo $! > "/tmp/ma_indicator_streamlit.pid"

osascript -e 'display notification "Streamlit 已啟動於 http://127.0.0.1:'$PORT'" with title "均線預測平台" subtitle "開瀏覽器看吧"'

exit 0
