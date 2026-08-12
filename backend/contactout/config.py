"""
contactout/config.py
─────────────────────
Configuration for the ContactOut module.

Loading is DETERMINISTIC:
  - .env resolved from <this file>/../.env  →  backend/.env
  - utf-8-sig encoding strips any accidental UTF-8 BOM
  - Strips whitespace from CONTACTOUT_API_TOKEN
  - Never prints the token — only logs presence + length
  - Does NOT depend on the current working directory
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Deterministic .env resolution ────────────────────────────────────────────
_THIS_DIR    = Path(__file__).resolve().parent   # backend/contactout/
_BACKEND_DIR = _THIS_DIR.parent                  # backend/
_ENV_PATH    = _BACKEND_DIR / ".env"

load_dotenv(dotenv_path=str(_ENV_PATH), override=True, encoding="utf-8-sig")

# ── API ───────────────────────────────────────────────────────────────────────
CONTACTOUT_API_TOKEN: str  = os.getenv("CONTACTOUT_API_TOKEN", "").strip()
CONTACTOUT_BASE_URL:  str  = "https://api.contactout.com"
CONTACTOUT_SEARCH_URL: str = f"{CONTACTOUT_BASE_URL}/v1/people/search"
CONTACTOUT_STATS_URL:  str = f"{CONTACTOUT_BASE_URL}/v1/stats"

# ── Limits ────────────────────────────────────────────────────────────────────
CONTACTOUT_MAX_CONTACTS_PER_COMPANY: int = int(
    os.getenv("CONTACTOUT_MAX_CONTACTS_PER_COMPANY", "2")
)
CONTACTOUT_TIMEOUT_SECONDS: float = float(
    os.getenv("CONTACTOUT_TIMEOUT_SECONDS", "15")
)

# How many raw profiles to request from ContactOut per page
# ContactOut returns up to 10 per call on most plans; raise if your plan allows more
CONTACTOUT_PAGE_SIZE: int = int(
    os.getenv("CONTACTOUT_PAGE_SIZE", "10")
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Return True if CONTACTOUT_API_TOKEN is present and non-empty."""
    return bool(CONTACTOUT_API_TOKEN)


def token_length() -> int:
    """Return the token length (safe to log)."""
    return len(CONTACTOUT_API_TOKEN)


def status_message() -> str:
    """Human-readable status — never reveals the token value."""
    if is_configured():
        return f"ContactOut configured (token_length={token_length()})"
    return f"ContactOut not configured — set CONTACTOUT_API_TOKEN in {_ENV_PATH}"
