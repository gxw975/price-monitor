#!/bin/bash

CHROME_USER_DATA="/home/lab-admin/chrome-user-data"
CHROME_BIN="/usr/bin/google-chrome-stable"
OPENCLI_BIN="/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
PROFILE="zu4794g4"
MAX_WAIT=60
XVFB_DISPLAY=:99

check_chrome_running() {
  pgrep -f "chrome.*${CHROME_USER_DATA}" > /dev/null 2>&1
}

check_profile_connected() {
  "$OPENCLI_BIN" profile list 2>/dev/null | grep -q "$PROFILE.*connected"
}

ensure_xvfb() {
  if pgrep -f "Xvfb ${XVFB_DISPLAY}" > /dev/null 2>&1; then
    return 0
  fi
  pkill -f "Xvfb" 2>/dev/null || true
  sleep 1
  Xvfb "$XVFB_DISPLAY" -screen 0 1920x1080x24 -ac +extension RANDR &
  sleep 1
  if ! pgrep -f "Xvfb ${XVFB_DISPLAY}" > /dev/null 2>&1; then
    echo "$(date): ERROR - Xvfb failed to start"
    return 1
  fi
  echo "$(date): Xvfb started on ${XVFB_DISPLAY}"
  return 0
}

launch_chrome() {
  pkill -f "chrome.*${CHROME_USER_DATA}" 2>/dev/null || true
  sleep 1

  ensure_xvfb || return 1

  export DISPLAY="$XVFB_DISPLAY"

  "$CHROME_BIN" \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --window-size=1920,1080 \
    --remote-debugging-port=9222 \
    --remote-allow-origins=* \
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

cleanup() {
  echo "$(date): ensure-chrome exiting, cleaning up..."
  pkill -f "Xvfb ${XVFB_DISPLAY}" 2>/dev/null || true
}

trap cleanup EXIT

if ! check_chrome_running || ! check_profile_connected; then
  launch_chrome
fi

ensure_xvfb

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
