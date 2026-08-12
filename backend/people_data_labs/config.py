"""
people_data_labs/config.py
──────────────────────────
Configuration constants for the PDL module.

Key loading is DETERMINISTIC:
  - Always reads .env from <this_file>/../../.env  (i.e. backend/.env)
  - Uses utf-8-sig encoding to strip any accidental UTF-8 BOM
  - Strips whitespace from the key
  - Never prints the key value — only logs its presence and length
  - Does NOT depend on the current working directory
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Deterministic .env path ───────────────────────────────────────────────────
# This file lives at  backend/people_data_labs/config.py
# backend/.env        is at  <this_file>/../.env
_THIS_DIR   = Path(__file__).resolve().parent          # backend/people_data_labs/
_BACKEND_DIR = _THIS_DIR.parent                        # backend/
_ENV_PATH    = _BACKEND_DIR / ".env"

# Load (override=True so re-imports pick up any .env changes; utf-8-sig strips BOM)
load_dotenv(dotenv_path=str(_ENV_PATH), override=True, encoding="utf-8-sig")

# ── API ───────────────────────────────────────────────────────────────────────
PDL_API_KEY: str = os.getenv("PDL_API_KEY", "").strip()
PDL_BASE_URL: str = "https://api.peopledatalabs.com/v5"

# ── Limits (configurable via env) ─────────────────────────────────────────────
PDL_MAX_CONTACTS_PER_COMPANY: int = int(os.getenv("PDL_MAX_CONTACTS_PER_COMPANY", "2"))
PDL_TIMEOUT_SECONDS: float = float(os.getenv("PDL_TIMEOUT_SECONDS", "15"))

# How many raw PDL candidates to fetch per role tier
PDL_SEARCH_PAGE_SIZE: int = 10


def is_configured() -> bool:
    """Return True if PDL_API_KEY is present (non-empty after stripping)."""
    return bool(PDL_API_KEY)


def key_length() -> int:
    """Return the length of the loaded key (safe to log)."""
    return len(PDL_API_KEY)


def status_message() -> str:
    """Human-readable config status — never reveals the key value."""
    if is_configured():
        return f"PDL configured (key_length={key_length()})"
    return f"PDL not configured — set PDL_API_KEY in {_ENV_PATH}"
