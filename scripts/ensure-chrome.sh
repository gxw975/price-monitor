#!/bin/bash

CHROME_USER_DATA="/home/lab-admin/chrome-user-data"
CHROME_BIN="/usr/bin/google-chrome-stable"
OPENCLI_BIN="/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
PROFILE="zu4794g4"
MAX_WAIT=60

check_chrome_running() {
  pgrep -f "chrome.*${CHROME_USER_DATA}" > /dev/null 2>&1
}

check_profile_connected() {
  "$OPENCLI_BIN" profile list 2>/dev/null | grep -q "$PROFILE.*connected"
}

launch_chrome() {
  pkill -f "chrome.*${CHROME_USER_DATA}" 2>/dev/null || true
  sleep 1

  "$CHROME_BIN" \
    --headless=new \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --window-size=1920,1080 \
    --remote-debugging-port=9222 \
    --user-data-dir="$CHROME_USER_DATA" \
    --profile-directory=Default \
    --no-first-run \
    --no-default-browser-check \
    about:blank &

  for i in $(seq 1 $MAX_WAIT); do
    sleep 1
    if check_profile_connected; then
      echo "$(date): zu4794g4 connected after ${i}s"
      return 0
    fi
  done
  echo "$(date): WARNING - Chrome started but extension not connected after ${MAX_WAIT}s"
  return 1
}

# Initial launch
if ! check_chrome_running || ! check_profile_connected; then
  launch_chrome
fi

# Monitor loop - check every 15 seconds
while true; do
  sleep 15
  if ! check_chrome_running; then
    echo "$(date): Chrome died, restarting..."
    launch_chrome
  elif ! check_profile_connected; then
    echo "$(date): Profile disconnected, restarting Chrome..."
    launch_chrome
  fi
done
