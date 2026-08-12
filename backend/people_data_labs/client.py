"""
people_data_labs/client.py
───────────────────────────
Raw async HTTP client for the PDL Person Search API.

Authentication
──────────────
  Header:  X-Api-Key: <PDL_API_KEY>
  The key is read fresh from config on every call so it always reflects
  the currently loaded value (important for tests that patch the env).

Error states returned to callers
─────────────────────────────────
  (data, auth_failed, rate_limited)

  auth_failed=True  → 401 received; callers MUST stop issuing further requests
  rate_limited=True → 429 received; callers should back off
  data=[]           → zero records (could be empty result OR an error)

  A 401 is NEVER silently converted to "0 contacts" — auth_failed propagates.

Rules
─────
  - Never log the API key or any auth header value.
  - Only log key presence + length (safe).
  - Never raise — always return a tuple.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from people_data_labs.config import (
    PDL_BASE_URL,
    PDL_TIMEOUT_SECONDS,
    is_configured,
    key_length,
)


# ── Module-level credits-exhausted flag ───────────────────────────────────────
# Set to True on first 402 response. Prevents wasting API calls when PDL has
# confirmed there are no credits left for this billing period.
_pdl_credits_exhausted: bool = False


def _mark_credits_exhausted() -> None:
    global _pdl_credits_exhausted
    _pdl_credits_exhausted = True
    _log("PDL credits exhausted — flagged. All further PDL calls will be skipped.")


def is_credits_exhausted() -> bool:
    """Return True if a 402 was received from PDL in this process lifetime."""
    return _pdl_credits_exhausted


def reset_credits_flag() -> None:
    """Reset the credits-exhausted flag (call at start of each pipeline run)."""
    global _pdl_credits_exhausted
    _pdl_credits_exhausted = False


# ── Internal logger ───────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [PDL] {msg}", flush=True)


# ── HTTP client factory ───────────────────────────────────────────────────────

def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(PDL_TIMEOUT_SECONDS),
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        follow_redirects=True,
    )


def _make_headers() -> dict[str, str]:
    """
    Build auth headers using the CURRENT key from config.
    Never logged — only the key length is logged separately.
    """
    from people_data_labs.config import PDL_API_KEY  # re-import each call (testability)
    return {
        "X-Api-Key": PDL_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ── Person Search ─────────────────────────────────────────────────────────────

async def person_search(
    query: dict[str, Any],
    size: int = 10,
    data_include: str | None = None,
) -> tuple[list[dict], bool, bool]:
    """
    POST /v5/person/search

    Args:
        query:        Elasticsearch query dict.
        size:         Max records to return (1–100).
        data_include: Optional comma-separated field list (PDL data_include param).

    Returns:
        (data, auth_failed, rate_limited)

        data         – list of person dicts (empty on any failure)
        auth_failed  – True when PDL returned 401
        rate_limited – True when PDL returned 429

    Never raises. Callers must check auth_failed and stop further PDL calls
    when it is True.
    """
    if not is_configured():
        _log(f"API key not configured (key_length={key_length()}) — skipping person/search")
        return [], False, False

    payload: dict[str, Any] = {
        "query":  query,
        "size":   max(1, min(size, 100)),
        "pretty": False,
    }
    if data_include:
        payload["data_include"] = data_include

    url      = f"{PDL_BASE_URL}/person/search"
    attempt  = 0
    max_att  = 2   # one retry on timeout only

    while attempt < max_att:
        attempt += 1
        async with _make_client() as client:
            try:
                resp = await client.post(url, headers=_make_headers(), json=payload)
            except httpx.TimeoutException:
                _log(f"Timeout on person/search (attempt {attempt}/{max_att})")
                if attempt < max_att:
                    await asyncio.sleep(1.5)
                    continue
                return [], False, False
            except httpx.RequestError as exc:
                _log(f"Network error on person/search: {type(exc).__name__}")
                return [], False, False

        # ── Status handling ────────────────────────────────────────────────
        if resp.status_code == 200:
            try:
                body    = resp.json()
                data    = body.get("data") or []
                total   = body.get("total", len(data))
                _log(f"person/search HTTP 200 — returned={len(data)} total={total}")
                return data, False, False
            except Exception as exc:
                _log(f"JSON parse error: {exc}")
                return [], False, False

        if resp.status_code == 404:
            # Empty result — normal, not an error
            _log("person/search HTTP 404 — no matching records")
            return [], False, False

        if resp.status_code == 400:
            _log(f"Bad query (400): {resp.text[:300]}")
            return [], False, False

        if resp.status_code == 401:
            # Auth failure — MUST propagate so callers stop immediately
            _log("Authentication failed (401) — PDL key is invalid or revoked")
            _log(f"  key_length={key_length()}  configured={is_configured()}")
            _log("  Check/regenerate key at https://dashboard.peopledatalabs.com/api-keys")
            _log("  PDL disabled for the remainder of this pipeline run")
            return [], True, False   # auth_failed=True

        if resp.status_code == 402:
            _log("PDL credits exhausted (402) — stopping all further PDL calls")
            # Return a sentinel tuple: ([], False, False) but the caller (person_search
            # in people_search.py) checks the log and continues.  We signal exhaustion
            # via a module-level flag so the second tier is skipped immediately.
            _mark_credits_exhausted()
            return [], False, False

        if resp.status_code == 403:
            _log("Access forbidden (403) — check account permissions")
            return [], False, False

        if resp.status_code == 429:
            _log(f"Rate limited (429) — waiting before retry {attempt}/{max_att}")
            if attempt < max_att:
                await asyncio.sleep(3.0)
                continue
            return [], False, True   # rate_limited=True

        _log(f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}")
        return [], False, False

    return [], False, False
