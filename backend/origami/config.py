"""
origami/config.py
──────────────────
Configuration for the standalone Origami module.

Loading is DETERMINISTIC:
  - .env resolved from <this file>/../.env  →  backend/.env
  - utf-8-sig encoding strips any accidental UTF-8 BOM
  - Strips whitespace from ORIGAMI_API_KEY
  - Never prints the key value — only logs presence + length
  - Does NOT depend on the current working directory

Environment variables
──────────────────────
  ORIGAMI_API_KEY          required  — your Origami dashboard API key
  ORIGAMI_BASE_URL         optional  — default https://api.origami.ai/v1
  ORIGAMI_TIMEOUT_SECONDS  optional  — default 20
  ORIGAMI_MAX_CONTACTS     optional  — default 8
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Deterministic .env resolution ────────────────────────────────────────────
_THIS_DIR    = Path(__file__).resolve().parent   # backend/origami/
_BACKEND_DIR = _THIS_DIR.parent                  # backend/
_ENV_PATH    = _BACKEND_DIR / ".env"

load_dotenv(dotenv_path=str(_ENV_PATH), override=True, encoding="utf-8-sig")

# ── API ───────────────────────────────────────────────────────────────────────
ORIGAMI_API_KEY: str  = os.getenv("ORIGAMI_API_KEY", "").strip()
ORIGAMI_BASE_URL: str = os.getenv("ORIGAMI_BASE_URL", "https://api.origami.ai/v1").rstrip("/")

# ── Limits ────────────────────────────────────────────────────────────────────
ORIGAMI_TIMEOUT_SECONDS: float = float(os.getenv("ORIGAMI_TIMEOUT_SECONDS", "20"))
ORIGAMI_MAX_CONTACTS: int      = int(os.getenv("ORIGAMI_MAX_CONTACTS", "8"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Return True if ORIGAMI_API_KEY is present and non-empty."""
    return bool(ORIGAMI_API_KEY)


def key_length() -> int:
    """Return the key length (safe to log — never reveals the value)."""
    return len(ORIGAMI_API_KEY)


def status_message() -> str:
    """Human-readable status — never reveals the key value."""
    if is_configured():
        return f"Origami configured (key_length={key_length()})"
    return f"Origami not configured — set ORIGAMI_API_KEY in {_ENV_PATH}"
