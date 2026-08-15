"""
hunter/config.py
─────────────────
Configuration for the standalone Hunter.io module.

Environment variables:
  HUNTER_API_KEY   — Hunter.io API key (required)
  HUNTER_TIMEOUT   — HTTP timeout in seconds (default 12)
  HUNTER_MAX_RESULTS — max contacts per domain-search call (default 10)

The real key is NEVER hardcoded or logged.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Deterministic .env resolution ─────────────────────────────────────────────
_THIS_DIR    = Path(__file__).resolve().parent   # backend/hunter/
_BACKEND_DIR = _THIS_DIR.parent                  # backend/
_ENV_PATH    = _BACKEND_DIR / ".env"

load_dotenv(dotenv_path=str(_ENV_PATH), override=False, encoding="utf-8-sig")

# ── API config ────────────────────────────────────────────────────────────────
HUNTER_BASE_URL: str = "https://api.hunter.io/v2"
HUNTER_TIMEOUT: float = float(os.getenv("HUNTER_TIMEOUT", "12"))
HUNTER_MAX_RESULTS: int = int(os.getenv("HUNTER_MAX_RESULTS", "10"))


def get_api_key() -> str:
    """Always read fresh from env — never cache at module level."""
    return os.getenv("HUNTER_API_KEY", "").strip()


def is_configured() -> bool:
    """Return True when HUNTER_API_KEY is set to a non-empty value."""
    return bool(get_api_key())


def key_hint() -> str:
    """Return a safe hint of the API key — never the full value."""
    key = get_api_key()
    if not key:
        return "(not set)"
    return key[:4] + "…" + key[-2:]
