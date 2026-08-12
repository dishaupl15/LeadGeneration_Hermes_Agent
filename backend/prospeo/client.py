"""
prospeo/client.py
──────────────────
Raw async HTTP client for the Prospeo REST API.

Endpoints used
──────────────
  GET  /account-information  → auth test (free, 0 credits)
  POST /search-person        → find person_ids by company + title filters
  POST /bulk-enrich-person   → reveal email + mobile for up to 50 person_ids

Authentication
──────────────
  Header:  X-KEY: <PROSPEO_API_KEY>
  Key is read fresh from config on every call — never cached at module level
  so tests can patch the env.

Return conventions
──────────────────
  Every function returns a tuple:  (result, error_code)

  result     – parsed dict/list on success, None on failure
  error_code – None on success; one of:
               "auth_failed"    → 400 INVALID_API_KEY
               "rate_limited"   → 429
               "no_credits"     → 400 INSUFFICIENT_CREDITS
               "no_results"     → 400 NO_RESULTS  (search-person specific)
               "invalid_request"→ 400 INVALID_REQUEST / INVALID_FILTERS
               "server_error"   → 5xx or INTERNAL_ERROR
               "timeout"        → request timed out
               "network_error"  → connection failure

  A 400 INVALID_API_KEY is NEVER silently converted to an empty result.
  Callers MUST check error_code == "auth_failed" and stop further requests.

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

from prospeo.config import (
    PROSPEO_ACCOUNT_URL,
    PROSPEO_BULK_URL,
    PROSPEO_SEARCH_URL,
    PROSPEO_TIMEOUT_SECONDS,
    is_configured,
    key_length,
)


# ── Per-second rate-limit enforcer ────────────────────────────────────────────
# Prospeo enforces x-second-rate-limit: 1 globally across ALL endpoints.
# We use an asyncio.Lock so only one coroutine fires a request at a time,
# plus a mandatory 1.15s gap between any two calls.

import time as _time

_last_request_at: float = 0.0
_MIN_INTERVAL_SECONDS: float = 1.20   # > 1s to account for clock drift
_rate_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Return (creating if needed) the module-level rate-limit lock."""
    global _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    return _rate_lock


async def _wait_for_rate_limit() -> None:
    """
    Acquire the rate-limit lock and sleep until 1.20s has passed since
    the previous Prospeo HTTP call.  Releases the lock only when the
    caller is ready to fire — caller must call _mark_request_done() right
    after the HTTP response to release timing correctly.
    """
    global _last_request_at
    lock = _get_lock()
    async with lock:
        elapsed = _time.monotonic() - _last_request_at
        if elapsed < _MIN_INTERVAL_SECONDS:
            wait = _MIN_INTERVAL_SECONDS - elapsed
            await asyncio.sleep(wait)
        # Stamp the time NOW, while we still hold the lock, so the next
        # waiter measures from this moment.
        _last_request_at = _time.monotonic()


def _mark_request_done() -> None:
    """No-op — timing is now stamped inside _wait_for_rate_limit."""
    pass


# ── Logger ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [PROSPEO] {msg}", flush=True)


# ── Headers ───────────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    """Build auth headers. Key is never logged."""
    from prospeo.config import PROSPEO_API_KEY  # fresh read each call
    return {
        "X-KEY": PROSPEO_API_KEY,
        "Content-Type": "application/json",
    }


# ── HTTP client factory ───────────────────────────────────────────────────────

def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(PROSPEO_TIMEOUT_SECONDS),
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        follow_redirects=True,
    )


# ── Error-code parser ─────────────────────────────────────────────────────────

def _parse_error(resp: httpx.Response) -> str:
    """Map a non-200 Prospeo response to a standard error_code string."""
    if resp.status_code == 429:
        return "rate_limited"
    if resp.status_code >= 500:
        return "server_error"
    # Prospeo returns 400 for almost everything; check error_code field
    try:
        body = resp.json()
        ec = (body.get("error_code") or "").upper()
    except Exception:
        ec = ""
    if ec == "INVALID_API_KEY":
        return "auth_failed"
    if ec == "INSUFFICIENT_CREDITS":
        return "no_credits"
    if ec == "NO_RESULTS":
        return "no_results"
    if ec in ("INVALID_FILTERS", "INVALID_REQUEST"):
        return "invalid_request"
    if ec in ("INTERNAL_ERROR", "SERVICE_TEMPORARILY_UNAVAILABLE"):
        return "server_error"
    if ec == "PLAN_REQUIRED":
        return "plan_required"
    return "unknown_error"


# ── Account information (auth test — 0 credits) ───────────────────────────────

async def get_account_info() -> tuple[dict | None, str | None]:
    """
    GET /account-information
    Free call — used as a low-cost authentication test.
    Returns (info_dict, None) on success or (None, error_code) on failure.
    """
    if not is_configured():
        _log(f"API key not configured (key_length={key_length()}) — skipping")
        return None, "not_configured"

    async with _make_client() as client:
        try:
            resp = await client.get(PROSPEO_ACCOUNT_URL, headers=_headers())
        except httpx.TimeoutException:
            _log("Timeout on /account-information")
            return None, "timeout"
        except httpx.RequestError as exc:
            _log(f"Network error on /account-information: {type(exc).__name__}")
            return None, "network_error"

    if resp.status_code == 200:
        try:
            body = resp.json()
            if body.get("error") is False:
                return body.get("response", {}), None
        except Exception:
            pass
        return None, "server_error"

    error_code = _parse_error(resp)
    if error_code == "auth_failed":
        _log("Authentication failed (INVALID_API_KEY) — check PROSPEO_API_KEY")
        _log(f"  key_length={key_length()}  configured={is_configured()}")
        _log("  Update key at https://prospeo.io/api-keys")
    else:
        _log(f"/account-information error: {error_code} (HTTP {resp.status_code})")
    return None, error_code


# ── Search Person ─────────────────────────────────────────────────────────────

async def search_person(
    filters: dict[str, Any],
    page: int = 1,
) -> tuple[list[dict], int, str | None]:
    """
    POST /search-person

    Args:
        filters: Prospeo filter dict (company.websites, person_job_title, etc.)
        page:    Result page (default 1; 25 results per page).

    Returns:
        (results, total_count, error_code)
        results     – list of {person, company} dicts (empty on any failure)
        total_count – total matched (from pagination.total_count)
        error_code  – None on success; error string on failure

    "no_results" is returned as error_code="no_results" with empty list,
    NOT treated as a generic error.
    """
    if not is_configured():
        _log(f"API key not configured (key_length={key_length()}) — skipping search")
        return [], 0, "not_configured"

    payload: dict[str, Any] = {"filters": filters, "page": page}

    await _wait_for_rate_limit()   # enforce 1-call/second global limit
    async with _make_client() as client:
        try:
            resp = await client.post(
                PROSPEO_SEARCH_URL, headers=_headers(), json=payload
            )
        except httpx.TimeoutException:
            _log("Timeout on /search-person")
            return [], 0, "timeout"
        except httpx.RequestError as exc:
            _log(f"Network error on /search-person: {type(exc).__name__}")
            return [], 0, "network_error"

    _mark_request_done()   # record time immediately after HTTP call

    if resp.status_code == 200:
        try:
            body    = resp.json()
            results = body.get("results") or []
            total   = (body.get("pagination") or {}).get("total_count", len(results))
            _log(f"/search-person HTTP 200 — page={page} returned={len(results)} total={total}")
            return results, total, None
        except Exception as exc:
            _log(f"JSON parse error on /search-person: {exc}")
            return [], 0, "server_error"

    error_code = _parse_error(resp)
    if error_code == "no_results":
        _log("/search-person — no matching people found")
        return [], 0, "no_results"
    if error_code == "auth_failed":
        _log("Authentication failed (INVALID_API_KEY) on /search-person")
        _log(f"  key_length={key_length()}  configured={is_configured()}")
        _log("  Prospeo disabled for this pipeline run")
    else:
        try:
            body   = resp.json()
            # Prospeo puts the human-readable detail in "message";
            # "filter_error" is a secondary field sometimes present.
            detail = (
                body.get("message")
                or body.get("filter_error")
                or resp.text[:200]
            )
        except Exception:
            detail = resp.text[:200]
        _log(f"/search-person error: {error_code} — {detail}")
    return [], 0, error_code


# ── Bulk Enrich Person ────────────────────────────────────────────────────────

async def bulk_enrich_person(
    records: list[dict[str, Any]],
    enrich_mobile: bool = True,
    only_verified_email: bool = False,
) -> tuple[list[dict], int, str | None]:
    """
    POST /bulk-enrich-person

    Args:
        records:             List of enrichment record dicts. Each must have at
                             least an "identifier" key plus matching data (e.g.
                             {"identifier": "1", "person_id": "abc123..."}).
        enrich_mobile:       Request mobile enrichment (costs extra credit).
        only_verified_email: Only return records with a verified email.

    Returns:
        (matched, total_cost, error_code)
        matched    – list of {"identifier", "person", "company"} dicts
        total_cost – Prospeo's reported credit cost
        error_code – None on success; error string on failure
    """
    if not is_configured():
        _log(f"API key not configured (key_length={key_length()}) — skipping bulk enrich")
        return [], 0, "not_configured"

    if not records:
        return [], 0, None

    payload: dict[str, Any] = {
        "data":                records[:50],   # Prospeo hard limit
        "enrich_mobile":       enrich_mobile,
        "only_verified_email": only_verified_email,
    }

    # Prospeo enforces x-second-rate-limit: 1 (one call/second) globally.
    # _wait_for_rate_limit() ensures ≥1.15s gap from the last API call
    # (search_person), so we never hit 429 on the first attempt.
    _MAX_RETRIES  = 4
    _DEFAULT_WAIT = 1.2

    for attempt in range(1, _MAX_RETRIES + 1):
        await _wait_for_rate_limit()   # enforce 1-call/second before every attempt
        async with _make_client() as client:
            try:
                resp = await client.post(
                    PROSPEO_BULK_URL, headers=_headers(), json=payload
                )
            except httpx.TimeoutException:
                _log(f"Timeout on /bulk-enrich-person (attempt {attempt}/{_MAX_RETRIES})")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_DEFAULT_WAIT * attempt)
                    continue
                return [], 0, "timeout"
            except httpx.RequestError as exc:
                _log(f"Network error on /bulk-enrich-person: {type(exc).__name__}")
                return [], 0, "network_error"

        _mark_request_done()   # record time right after HTTP response received

        if resp.status_code == 200:
            try:
                body        = resp.json()
                matched     = body.get("matched") or []
                total_cost  = body.get("total_cost", 0)
                not_matched = body.get("not_matched") or []
                invalid_dp  = body.get("invalid_datapoints") or []
                _log(
                    f"/bulk-enrich-person HTTP 200 — "
                    f"matched={len(matched)} "
                    f"not_matched={len(not_matched)} "
                    f"invalid={len(invalid_dp)} "
                    f"cost={total_cost}"
                )
                return matched, total_cost, None
            except Exception as exc:
                _log(f"JSON parse error on /bulk-enrich-person: {exc}")
                return [], 0, "server_error"

        error_code = _parse_error(resp)

        if error_code == "rate_limited":
            # Use the most precise header available, prefer x-second-reset-seconds
            # then x-minute-reset-seconds, then fall back to exponential backoff.
            hdr_sec  = resp.headers.get("x-second-reset-seconds")
            hdr_min  = resp.headers.get("x-minute-reset-seconds")
            if hdr_sec:
                try:
                    wait = max(float(hdr_sec) + 0.3, _DEFAULT_WAIT)
                except (ValueError, TypeError):
                    wait = _DEFAULT_WAIT * (2 ** (attempt - 1))
            elif hdr_min:
                try:
                    wait = max(float(hdr_min) + 0.3, _DEFAULT_WAIT)
                except (ValueError, TypeError):
                    wait = _DEFAULT_WAIT * (2 ** (attempt - 1))
            else:
                wait = _DEFAULT_WAIT * (2 ** (attempt - 1))

            if attempt < _MAX_RETRIES:
                _log(
                    f"/bulk-enrich-person rate_limited (429) — "
                    f"attempt {attempt}/{_MAX_RETRIES}, waiting {wait:.1f}s"
                )
                await asyncio.sleep(wait)
                continue
            else:
                _log(f"/bulk-enrich-person rate_limited — all {_MAX_RETRIES} attempts exhausted")
                return [], 0, error_code

        if error_code == "auth_failed":
            _log("Authentication failed (INVALID_API_KEY) on /bulk-enrich-person")
            return [], 0, error_code

        if error_code == "no_credits":
            _log("/bulk-enrich-person — Prospeo credits exhausted")
            return [], 0, error_code

        # Other non-retryable error
        _log(f"/bulk-enrich-person error: {error_code} (HTTP {resp.status_code})")
        return [], 0, error_code

    return [], 0, "rate_limited"
