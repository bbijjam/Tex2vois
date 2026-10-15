#!/usr/bin/env bash
# One-time setup for Tex2vois on macOS or Linux. Safe to run again.
# Needs no administrator password: everything goes into this folder and ~/.local/bin (uv).
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

say "1/2  uv (Python installer)"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
uv --version

say "2/2  Python 3.11 environment and Tex2vois (first time: about 1.5 GB, a few minutes)"
[[ -d .venv ]] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e .

say "Done. Start the app with:  ./run.sh"
