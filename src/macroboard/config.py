"""Filesystem layout and runtime settings."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # .../macroboard
DATA = ROOT / "data"
CACHE_DIR = DATA / "cache"
DB_PATH = Path(os.environ.get("MACRO_DB", DATA / "macroboard.db"))
WEB = ROOT / "web"

HOST = os.environ.get("MACRO_HOST", "127.0.0.1")
PORT = int(os.environ.get("MACRO_PORT", "8765"))

for _p in (DATA, CACHE_DIR):
    _p.mkdir(parents=True, exist_ok=True)
