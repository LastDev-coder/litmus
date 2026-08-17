#!/usr/bin/env bash
#
# One-command setup + launch for litmus.
#
#   ./start.sh              install everything, then open the local web UI
#   ./start.sh inspect x    install (if needed), then run any CLI command
#   ./start.sh --version    (etc.)
#
# The first run installs into a local .venv; later runs are instant. Nothing is
# installed globally and nothing leaves your machine.
set -euo pipefail
cd "$(dirname "$0")"

echo "litmus :: preparing environment (first run installs; later runs are instant)"

if command -v uv >/dev/null 2>&1; then
  # uv is fastest and can fetch a suitable Python automatically.
  [ -d .venv ] || uv venv --python 3.12 .venv
  uv pip install --quiet -e ".[code]"
else
  # Fall back to the standard library venv + pip. Find a Python 3.11+.
  PY=""
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "error: Python 3.11+ was not found." >&2
    echo "  Easiest fix - install uv (it will fetch Python for you):" >&2
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "  Or install Python 3.11+ directly (macOS: brew install python@3.12)." >&2
    exit 1
  fi
  [ -d .venv ] || "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -e ".[code]"
fi

echo "litmus :: ready"
BIN=".venv/bin/litmus"

if [ "$#" -gt 0 ]; then
  exec "$BIN" "$@"
else
  echo "litmus :: launching the web UI (Ctrl-C to stop)"
  exec "$BIN" serve
fi
