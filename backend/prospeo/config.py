"""
prospeo/config.py
──────────────────
Configuration for the Prospeo module.

Loading is DETERMINISTIC:
  - .env resolved from <this file>/../../.env  →  backend/.env
  - utf-8-sig encoding strips any accidental UTF-8 BOM
  - Strips whitespace from PROSPEO_API_KEY
  - Never prints the key — only logs presence + length
  - Does NOT depend on the current working directory
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Deterministic .env resolution ────────────────────────────────────────────
_THIS_DIR    = Path(__file__).resolve().parent   # backend/prospeo/
_BACKEND_DIR = _THIS_DIR.parent                  # backend/
_ENV_PATH    = _BACKEND_DIR / ".env"

load_dotenv(dotenv_path=str(_ENV_PATH), override=True, encoding="utf-8-sig")

# ── API ───────────────────────────────────────────────────────────────────────
PROSPEO_API_KEY: str       = os.getenv("PROSPEO_API_KEY", "").strip()
PROSPEO_BASE_URL: str      = "https://api.prospeo.io"
PROSPEO_SEARCH_URL: str    = f"{PROSPEO_BASE_URL}/search-person"
PROSPEO_BULK_URL: str      = f"{PROSPEO_BASE_URL}/bulk-enrich-person"
PROSPEO_ACCOUNT_URL: str   = f"{PROSPEO_BASE_URL}/account-information"

# ── Limits ────────────────────────────────────────────────────────────────────
PROSPEO_MAX_CONTACTS_PER_COMPANY: int = int(
    os.getenv("PROSPEO_MAX_CONTACTS_PER_COMPANY", "2")
)
PROSPEO_TIMEOUT_SECONDS: float = float(
    os.getenv("PROSPEO_TIMEOUT_SECONDS", "30")
)

# How many candidates to pull from Search Person before ranking & enriching
PROSPEO_SEARCH_PAGE_SIZE: int = 10


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Return True if PROSPEO_API_KEY is present and non-empty."""
    return bool(PROSPEO_API_KEY)


def key_length() -> int:
    """Return the API key length (safe to log)."""
    return len(PROSPEO_API_KEY)


def status_message() -> str:
    """Human-readable status — never reveals the key value."""
    if is_configured():
        return f"Prospeo configured (key_length={key_length()})"
    return f"Prospeo not configured — set PROSPEO_API_KEY in {_ENV_PATH}"
