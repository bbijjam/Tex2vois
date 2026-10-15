#!/usr/bin/env bash
# One-time setup for Tex2vois on macOS or Linux. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

say "1/3  Audio tools (ffmpeg, espeak-ng)"
if command -v ffmpeg >/dev/null && command -v espeak-ng >/dev/null; then
  echo "Already installed."
elif [[ "$(uname)" == "Darwin" ]]; then
  if ! command -v brew >/dev/null; then
    echo "Homebrew is needed to install ffmpeg and espeak-ng. Install it from https://brew.sh, then run ./setup.sh again."
    exit 1
  fi
  brew install ffmpeg espeak-ng
else
  echo "Please install them with your package manager, then run ./setup.sh again. On Ubuntu or Debian (and WSL):"
  echo "  sudo apt update && sudo apt install -y ffmpeg espeak-ng"
  exit 1
fi

say "2/3  uv (Python installer)"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
uv --version

say "3/3  Python 3.11 environment and Tex2vois (first time: about 1.5 GB, a few minutes)"
[[ -d .venv ]] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e .

say "Done. Start the app with:  ./run.sh"
