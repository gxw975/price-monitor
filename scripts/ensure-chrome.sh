#!/bin/bash

CHROME_USER_DATA="/home/lab-admin/.config/google-chrome-profile-manual"
CHROME_BIN="/usr/bin/google-chrome-stable"
CDP_PORT=9223
MAX_WAIT=30

export DISPLAY=:0
export XAUTHORITY="/run/user/1000/.mutter-Xwaylandauth.47UFP3"

check_chrome_running() {
  pgrep -f "chrome.*${CHROME_USER_DATA}" > /dev/null 2>&1
}

check_cdp_ready() {
  curl -s "http://127.0.0.1:${CDP_PORT}/json/version" > /dev/null 2>&1
}

launch_chrome() {
  pkill -f "chrome.*${CHROME_USER_DATA}" 2>/dev/null || true
  sleep 2
  rm -rf /tmp/com.google.Chrome.* /tmp/.org.chromium.* 2>/dev/null

  "$CHROME_BIN" \
    --no-sandbox \
    --disable-gpu \
    --disable-software-rasterizer \
    --disable-dev-shm-usage \
    --disable-blink-features=AutomationControlled \
    --start-maximized \
    --user-data-dir="$CHROME_USER_DATA" \
    --remote-debugging-port=$CDP_PORT \
    --remote-allow-origins=* \
    about:blank &

  for i in $(seq 1 $MAX_WAIT); do
    sleep 1
    if check_cdp_ready; then
      echo "$(date): Chrome CDP ready after ${i}s"
      return 0
    fi
  done
  echo "$(date): WARNING - Chrome CDP not ready after ${MAX_WAIT}s"
  return 1
}

if ! check_chrome_running || ! check_cdp_ready; then
  launch_chrome
fi

while true; do
  sleep 15
  if ! check_chrome_running; then
    echo "$(date): Chrome died, restarting..."
    launch_chrome
  fi
done
