"""
reddit/config.py
─────────────────
Configuration for the standalone Reddit lead-generation module.

Loading is DETERMINISTIC:
  - .env resolved from <this file>/../.env  →  backend/.env
  - utf-8-sig encoding strips any accidental UTF-8 BOM
  - Strips whitespace from all credential values
  - Never prints secrets — only logs presence + length
  - Does NOT depend on the current working directory

Reddit API access
─────────────────
  This module uses Reddit's official OAuth2 "application-only" (script)
  authentication flow — no user login required, no HTML scraping.

  Required:
    1. Create a Reddit app at https://www.reddit.com/prefs/apps
       Type: "script"
    2. Copy client_id (under app name) and client_secret
    3. Set a descriptive user_agent (Reddit requires this)

  Environment variables:
    REDDIT_CLIENT_ID       — Reddit application client ID
    REDDIT_CLIENT_SECRET   — Reddit application client secret
    REDDIT_USER_AGENT      — e.g. "LeadCRM/1.0 by YourRedditUsername"
    REDDIT_REQUEST_TIMEOUT — HTTP timeout in seconds (default 15)
    REDDIT_MAX_POSTS       — Max posts per query to fetch (default 25)
    REDDIT_MAX_QUERIES     — Max search queries per generate call (default 6)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Deterministic .env resolution ────────────────────────────────────────────
_THIS_DIR    = Path(__file__).resolve().parent   # backend/reddit/
_BACKEND_DIR = _THIS_DIR.parent                  # backend/
_ENV_PATH    = _BACKEND_DIR / ".env"

load_dotenv(dotenv_path=str(_ENV_PATH), override=True, encoding="utf-8-sig")

# ── Reddit OAuth2 credentials ─────────────────────────────────────────────────
REDDIT_CLIENT_ID:     str = os.getenv("REDDIT_CLIENT_ID",     "").strip()
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
REDDIT_USER_AGENT:    str = os.getenv(
    "REDDIT_USER_AGENT",
    "LeadCRM-RedditModule/1.0"
).strip()

# ── API base ──────────────────────────────────────────────────────────────────
REDDIT_API_BASE:  str = "https://oauth.reddit.com"
REDDIT_TOKEN_URL: str = "https://www.reddit.com/api/v1/access_token"

# ── Limits ────────────────────────────────────────────────────────────────────
REDDIT_REQUEST_TIMEOUT: float = float(
    os.getenv("REDDIT_REQUEST_TIMEOUT", "15")
)
REDDIT_MAX_POSTS: int = int(
    os.getenv("REDDIT_MAX_POSTS", "25")
)
REDDIT_MAX_QUERIES: int = int(
    os.getenv("REDDIT_MAX_QUERIES", "6")
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Return True when both REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set."""
    return bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)


def client_id_hint() -> str:
    """Return a safe hint of the client ID (never the full value)."""
    if not REDDIT_CLIENT_ID:
        return "(not set)"
    return REDDIT_CLIENT_ID[:4] + "…" + REDDIT_CLIENT_ID[-2:]


def status_message() -> str:
    """Human-readable status — never reveals credential values."""
    if is_configured():
        return (
            f"Reddit configured "
            f"(client_id={client_id_hint()}, "
            f"user_agent={REDDIT_USER_AGENT!r})"
        )
    return (
        f"Reddit not configured — "
        f"set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in {_ENV_PATH}"
    )
