#!/bin/bash
# stop.command — 雙擊停止均線預測平台

PORT=8765
PID_FILE="/tmp/ma_indicator_streamlit.pid"

# 方法 1: 從 PID file 殺
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null
    sleep 1
    # 沒死就強制
    kill -9 "$PID" 2>/dev/null
  fi
  rm -f "$PID_FILE"
fi

# 方法 2: 用 port 兜底（PID file 失效 / 被砍過再啟動）
PIDS=$(lsof -ti tcp:$PORT 2>/dev/null)
if [ -n "$PIDS" ]; then
  echo "$PIDS" | xargs kill 2>/dev/null
  sleep 1
  echo "$PIDS" | xargs kill -9 2>/dev/null
fi

# 驗證
if lsof -ti tcp:$PORT > /dev/null 2>&1; then
  osascript -e 'display alert "停止失敗" message "Port '$PORT' 還是被佔著，請手動查看" as warning'
else
  osascript -e 'display notification "已停止" with title "均線預測平台" subtitle "Server 關閉"'
fi

exit 0
