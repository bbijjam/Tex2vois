#!/usr/bin/env bash
# Start the Tex2vois web app and open it in your browser. Press Ctrl+C to stop.
set -euo pipefail
cd "$(dirname "$0")"
[[ -x .venv/bin/python ]] || { echo "Run ./setup.sh first."; exit 1; }
PORT="${GRADIO_SERVER_PORT:-7860}"
URL="http://127.0.0.1:${PORT}"
echo "Starting Tex2vois at ${URL}  (the first start downloads the voice, about 330 MB)"
(
  for _ in $(seq 1 180); do
    if curl -s -o /dev/null "$URL"; then
      if command -v open >/dev/null; then open "$URL"; elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1; fi
      echo "Open ${URL} in your browser if it did not open by itself."
      break
    fi
    sleep 1
  done
) &
GRADIO_SERVER_PORT="$PORT" exec .venv/bin/python app.py
