#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"

export HOST
export PORT

local_ips() {
  if command -v ipconfig.exe >/dev/null 2>&1; then
    ipconfig.exe \
      | awk -F: '/IPv4 Address|IPv4 地址/ { gsub(/^[ \t\r]+|[ \t\r]+$/, "", $2); if ($2 != "") print $2 }' \
      | sort -u
    return
  fi

  if command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | tr ' ' '\n' | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/'
  fi
}

echo "Print service is starting..."
echo
echo "Bind address : http://${HOST}:${PORT}"
echo "Local access : http://localhost:${PORT}"
for ip in $(local_ips); do
  echo "LAN access   : http://${ip}:${PORT}"
done
echo
echo "Press Ctrl+C to stop."
echo
uv run waitress-serve --host="$HOST" --port="$PORT" app:app
