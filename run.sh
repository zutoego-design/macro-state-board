#!/usr/bin/env bash
# Minimal launcher for macOS/Linux: same stages as run.ps1.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src"
export PYTHONIOENCODING=utf-8
PY="${MACRO_PYTHON:-python3}"
$PY -c "import sys; assert sys.version_info >= (3,10)" || { echo "need python 3.10+"; exit 1; }
$PY -m pip install -q --disable-pip-version-check fastapi "uvicorn[standard]" || true
$PY -m macroboard init
[ -f data/macroboard.db ] || $PY -m macroboard refresh
echo "board: http://127.0.0.1:${MACRO_PORT:-8765}/"
exec $PY -m macroboard serve --port "${MACRO_PORT:-8765}"
