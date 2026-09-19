#!/bin/bash
# start_big_player.command — 雙擊啟動「💰 大戶買賣力」獨立頁面
# 路徑：~/Desktop/排程運算/MA_Indicator/start_big_player.command
#
# Port 8767（不跟 V1 主介面 8765 / V2 8766 衝突）
# Log: /tmp/ma_big_player_streamlit.log

cd "$(dirname "$0")"

PORT=8767
APP="big_player_app.py"
LOG="/tmp/ma_big_player_streamlit.log"
PY="/opt/anaconda3/envs/finlab3/bin/python"
STREAMLIT="/opt/anaconda3/envs/finlab3/bin/streamlit"

if [ ! -x "$STREAMLIT" ]; then
  osascript -e 'display alert "找不到 streamlit" message "請確認 /opt/anaconda3/envs/finlab3/bin/streamlit 是否存在" as critical'
  exit 1
fi

# 檢查 port 有沒有人佔用
if lsof -ti tcp:$PORT > /dev/null 2>&1; then
  CHOICE=$(osascript -e 'button returned of (display alert "Port '$PORT' 已被佔用" message "可能之前啟動的還在跑，要直接覆蓋嗎？" buttons {"取消", "強制重啟"} default button "強制重啟" cancel button "取消")')
  if [ "$CHOICE" != "強制重啟" ]; then
    exit 0
  fi
  lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null
  sleep 1
fi

# 開瀏覽器（背景延遲，等 server 起來再開）
(sleep 3 && open "http://127.0.0.1:$PORT") &

# 啟動 streamlit
nohup "$STREAMLIT" run "$APP" \
  --server.port $PORT \
  --server.headless true \
  --server.address 127.0.0.1 \
  --browser.gatherUsageStats false \
  > "$LOG" 2>&1 &

echo $! > "/tmp/ma_big_player_streamlit.pid"

osascript -e 'display notification "Streamlit 已啟動於 http://127.0.0.1:'$PORT'" with title "大戶買賣力獨立頁" subtitle "不影響 V1/V2"'

exit 0
