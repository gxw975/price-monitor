#!/bin/bash
# Chrome 守护进程 — 确保 Chrome 在 DISPLAY=:0 上运行
# 使用纯物理操作模式（零CDP），永久禁用 --remote-debugging-port
#
# Chrome 启动参数（永久固化，只保留这6个）:
#   --start-maximized
#   --no-first-run
#   --restore-last-session=false
#   --disable-session-crashed-bubble
#   --disable-crash-reporter
#   --ozone-platform=x11

CHROME_USER_DATA="/home/lab-admin/.config/google-chrome"
CHROME_BIN="/usr/bin/google-chrome-stable"
MAX_WAIT=30

export DISPLAY=:0
export XAUTHORITY="/run/user/1000/.mutter-Xwaylandauth.47UFP3"

check_chrome_running() {
  pgrep -f "chrome.*${CHROME_USER_DATA}" > /dev/null 2>&1
}

check_chrome_window() {
  # 检查Chrome窗口是否已出现
  xdotool search --class "google-chrome" > /dev/null 2>&1
}

launch_chrome() {
  echo "$(date): [Chrome] Starting Chrome (no CDP mode)..."

  # 优雅关闭旧实例
  pkill -TERM -f "chrome.*${CHROME_USER_DATA}" 2>/dev/null || true
  sleep 3
  if pgrep -f "chrome.*${CHROME_USER_DATA}" > /dev/null 2>&1; then
    echo "$(date): [Chrome] TERM failed, force killing..."
    pkill -KILL -f "chrome.*${CHROME_USER_DATA}" 2>/dev/null || true
    sleep 1
  fi

  # 清理临时文件
  rm -rf /tmp/com.google.Chrome.* /tmp/.org.chromium.* 2>/dev/null
  rm -f "${CHROME_USER_DATA}/SingletonLock" \
        "${CHROME_USER_DATA}/SingletonCookie" \
        "${CHROME_USER_DATA}/SingletonSocket" \
        "${CHROME_USER_DATA}/Default/SingletonLock" \
        "${CHROME_USER_DATA}/Default/SingletonCookie" \
        "${CHROME_USER_DATA}/Default/SingletonSocket" 2>/dev/null

  # 修复Preferences中的崩溃标记（防止"要恢复页面吗"弹窗）
  if [ -f "${CHROME_USER_DATA}/Default/Preferences" ]; then
    sed -i 's/"exit_type":"crashed"/"exit_type":"Normal"/' "${CHROME_USER_DATA}/Default/Preferences" 2>/dev/null
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' "${CHROME_USER_DATA}/Default/Preferences" 2>/dev/null
  fi

  # 修复权限
  sudo chown -R lab-admin:lab-admin "${CHROME_USER_DATA}" 2>/dev/null

  # ═══ 永久固化的6个启动参数（绝不含 --remote-debugging-port）═══
  "$CHROME_BIN" \
    --user-data-dir="$CHROME_USER_DATA" \
    --start-maximized \
    --no-first-run \
    --restore-last-session=false \
    --disable-session-crashed-bubble \
    --disable-crash-reporter \
    --ozone-platform=x11 \
    "https://www.taobao.com" &

  # 等待Chrome窗口出现
  for i in $(seq 1 $MAX_WAIT); do
    sleep 1
    if check_chrome_window; then
      echo "$(date): [Chrome] Window ready after ${i}s"
      return 0
    fi
  done
  echo "$(date): [Chrome] WARNING - Window not found after ${MAX_WAIT}s"
  return 1
}

# ── 主循环 ──
if ! check_chrome_running; then
  launch_chrome
fi

while true; do
  sleep 15
  if ! check_chrome_running; then
    echo "$(date): [Chrome] Process died, restarting..."
    launch_chrome
  fi
done
