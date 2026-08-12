"""
contactout/client.py
─────────────────────
Raw async HTTP client for the ContactOut REST API.

Authentication
──────────────
  Header:  token: <CONTACTOUT_API_TOKEN>
           authorization: basic
  Token is read fresh from config on every call (never cached at module level
  so tests can patch the env).

Error states — every function returns (result, error_code):
  result     – dict/list on success, None on failure
  error_code – None on success; one of:
               "auth_failed"     → 400 bad credentials / invalid headers
               "bad_request"     → 401 bad request / invalid input
               "no_credits"      → 403 out of credits
               "no_access"       → 403 no access to endpoint
               "rate_limited"    → 429
               "server_error"    → 5xx
               "timeout"         → request timed out
               "network_error"   → connection failure
               "not_configured"  → token empty

Notes
─────
  Per the ContactOut docs the HTTP status / error mapping is unusual:
    400 = bad credentials or invalid headers
    401 = bad request or invalid input
    403 = out of credits OR no access to endpoint
    429 = rate limit

  A 400 credential error is NEVER silently converted to empty results.
  Callers MUST check error_code and stop further requests on auth_failed.
  Never log the token or auth header value.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from contactout.config import (
    CONTACTOUT_STATS_URL,
    CONTACTOUT_TIMEOUT_SECONDS,
    is_configured,
    token_length,
)


# ── Logger ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [CONTACTOUT] {msg}", flush=True)


# ── Headers ───────────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    """
    Build auth headers. Token is never logged.
    ContactOut requires both 'authorization: basic' and 'token: <key>'.
    """
    from contactout.config import CONTACTOUT_API_TOKEN  # fresh read each call
    return {
        "authorization": "basic",
        "token":          CONTACTOUT_API_TOKEN,
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


# ── HTTP client factory ───────────────────────────────────────────────────────

def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(CONTACTOUT_TIMEOUT_SECONDS),
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        follow_redirects=True,
    )


# ── Error-code parser ─────────────────────────────────────────────────────────

def _parse_error(resp: httpx.Response) -> str:
    """Map a non-200 ContactOut response to a standard error_code string."""
    sc = resp.status_code
    if sc == 429:
        return "rate_limited"
    if sc >= 500:
        return "server_error"
    if sc == 400:
        # ContactOut uses 400 for bad credentials
        try:
            body = resp.json()
            msg  = str(body.get("message") or "").lower()
        except Exception:
            msg = ""
        if "credential" in msg or "header" in msg or "unauthorized" in msg:
            return "auth_failed"
        return "auth_failed"   # treat all 400s as auth issue (per docs)
    if sc == 401:
        return "bad_request"
    if sc == 403:
        try:
            msg = str(resp.json().get("message") or "").lower()
        except Exception:
            msg = resp.text.lower()
        if "credit" in msg:
            return "no_credits"
        return "no_access"
    return "unknown_error"


# ── Stats endpoint (auth test — free) ─────────────────────────────────────────

async def get_stats() -> tuple[dict | None, str | None]:
    """
    GET /v1/stats  — free call used as auth test.
    Returns (stats_dict, None) on success or (None, error_code) on failure.
    """
    if not is_configured():
        _log(f"API token not configured (token_length={token_length()}) — skipping")
        return None, "not_configured"

    async with _make_client() as client:
        try:
            resp = await client.get(CONTACTOUT_STATS_URL, headers=_headers())
        except httpx.TimeoutException:
            _log("Timeout on /v1/stats")
            return None, "timeout"
        except httpx.RequestError as exc:
            _log(f"Network error on /v1/stats: {type(exc).__name__}")
            return None, "network_error"

    if resp.status_code == 200:
        try:
            body = resp.json()
            return body.get("usage") or body, None
        except Exception:
            return {}, None

    error_code = _parse_error(resp)
    if error_code == "auth_failed":
        _log("Authentication failed (400) — check CONTACTOUT_API_TOKEN")
        _log(f"  token_length={token_length()}")
        _log("  Request a valid token at https://contactout.com/meeting")
    else:
        _log(f"/v1/stats error: {error_code} (HTTP {resp.status_code})")
    return None, error_code


# ── People Search ─────────────────────────────────────────────────────────────

async def people_search(
    payload: dict[str, Any],
) -> tuple[dict | None, str | None]:
    """
    POST /v1/people/search

    Args:
        payload: Full ContactOut search payload dict.

    Returns:
        (body_dict, error_code)
        body_dict  – parsed response on success (has 'profiles', 'metadata')
        error_code – None on success; error string on failure

    Never raises. A 400 auth error is returned as error_code="auth_failed".
    """
    if not is_configured():
        _log(f"API token not configured (token_length={token_length()}) — skipping search")
        return None, "not_configured"

    from contactout.config import CONTACTOUT_SEARCH_URL

    async with _make_client() as client:
        try:
            resp = await client.post(
                CONTACTOUT_SEARCH_URL,
                headers=_headers(),
                json=payload,
            )
        except httpx.TimeoutException:
            _log("Timeout on /v1/people/search")
            return None, "timeout"
        except httpx.RequestError as exc:
            _log(f"Network error on /v1/people/search: {type(exc).__name__}")
            return None, "network_error"

    if resp.status_code == 200:
        try:
            body     = resp.json()
            sc       = body.get("status_code", 200)
            profiles = body.get("profiles", {})
            meta     = body.get("metadata", {})
            total    = meta.get("total_results", 0) if isinstance(meta, dict) else 0
            # profiles can be a dict (keyed by LinkedIn URL) or a list
            if isinstance(profiles, dict):
                n_profiles = len(profiles)
            elif isinstance(profiles, list):
                n_profiles = len(profiles)
            else:
                n_profiles = 0
            _log(
                f"/v1/people/search HTTP 200 — "
                f"profiles={n_profiles} "
                f"total={total} "
                f"inner_status={sc}"
            )
            return body, None
        except Exception as exc:
            _log(f"JSON parse error on /v1/people/search: {exc}")
            return None, "server_error"

    error_code = _parse_error(resp)
    if error_code == "auth_failed":
        _log("Authentication failed (400) — token invalid or bad headers")
        _log(f"  token_length={token_length()}  configured={is_configured()}")
        _log("  ContactOut disabled for this pipeline run")
    elif error_code == "rate_limited":
        retry_after = resp.headers.get("retry-after", "unknown")
        _log(f"Rate limited (429) — retry after {retry_after}s")
    elif error_code in ("no_credits", "no_access"):
        _log(f"Access denied (403): {error_code}")
    else:
        try:
            detail = resp.json().get("message", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        _log(f"/v1/people/search error: {error_code} — {detail}")
    return None, error_code
