"""
reddit/routes.py
─────────────────
FastAPI router for the standalone Reddit lead-generation module.

Endpoints
─────────
  GET  /reddit/health          — Module health / credentials check
  GET  /reddit/auth-test       — Live OAuth2 authentication probe
  POST /reddit/search-leads    — Search Reddit and return raw lead candidates
                                 (without MongoDB persistence)

The heavy pipeline endpoint (POST /leads/generate-reddit) that persists leads
to MongoDB lives in src/routes/leads.py and re-uses the functions here.

Isolation contract: only imports from reddit/* + stdlib + pydantic + fastapi.
"""
from __future__ import annotations

from fastapi import APIRouter

from reddit.client import probe_auth
from reddit.config import (
    REDDIT_MAX_POSTS,
    REDDIT_MAX_QUERIES,
    REDDIT_REQUEST_TIMEOUT,
    client_id_hint,
    is_configured,
    status_message,
)
from reddit.schemas import (
    RedditAuthTestResponse,
    RedditHealthResponse,
    RedditSearchInput,
    RedditSearchResult,
)
from reddit.search import run_reddit_search

router = APIRouter(prefix="/reddit", tags=["Reddit"])


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [REDDIT] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# GET /reddit/health
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/health",
    summary="Reddit module health check",
    response_model=RedditHealthResponse,
)
async def reddit_health() -> RedditHealthResponse:
    """
    Return whether the Reddit module is configured and ready.
    Does NOT make a live network call — only checks credentials presence.
    """
    configured = is_configured()
    return RedditHealthResponse(
        module="reddit",
        configured=configured,
        status="ready" if configured else "no_credentials",
        message=status_message(),
        max_posts=REDDIT_MAX_POSTS,
        max_queries=REDDIT_MAX_QUERIES,
        timeout_seconds=REDDIT_REQUEST_TIMEOUT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /reddit/auth-test
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/auth-test",
    summary="Live Reddit OAuth2 authentication test",
    response_model=RedditAuthTestResponse,
)
async def reddit_auth_test() -> RedditAuthTestResponse:
    """
    Attempt a live OAuth2 token fetch and optionally verify identity.
    Always returns a JSON response — never raises 5xx for auth failures.
    """
    configured = is_configured()
    if not configured:
        return RedditAuthTestResponse(
            REDDIT_CONFIGURED=False,
            REDDIT_CLIENT_ID_HINT="(not set)",
            REDDIT_HTTP_STATUS=None,
            REDDIT_AUTHENTICATION="FAILED",
            username=None,
            message="REDDIT_CLIENT_ID and/or REDDIT_CLIENT_SECRET not set in .env",
        )

    http_status, error, username = await probe_auth()

    if error:
        _log(f"Auth test failed: {error}")
        return RedditAuthTestResponse(
            REDDIT_CONFIGURED=True,
            REDDIT_CLIENT_ID_HINT=client_id_hint(),
            REDDIT_HTTP_STATUS=http_status,
            REDDIT_AUTHENTICATION="FAILED",
            username=None,
            message=f"Authentication failed: {error}",
        )

    _log(f"Auth test succeeded (username={username!r})")
    return RedditAuthTestResponse(
        REDDIT_CONFIGURED=True,
        REDDIT_CLIENT_ID_HINT=client_id_hint(),
        REDDIT_HTTP_STATUS=http_status or 200,
        REDDIT_AUTHENTICATION="SUCCESS",
        username=username,
        message="Reddit OAuth2 authentication successful",
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /reddit/search-leads
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/search-leads",
    summary="Search Reddit for lead candidates (no MongoDB persistence)",
    response_model=RedditSearchResult,
)
async def reddit_search_leads(payload: RedditSearchInput) -> RedditSearchResult:
    """
    Search Reddit for public posts matching category + location.

    Returns raw lead candidates — does NOT save to MongoDB.
    Use POST /leads/generate-reddit for the full pipeline with deduplication
    and MongoDB persistence.

    Rate limits: Reddit allows ~100 OAuth2 API calls / minute for script apps.
    The module automatically retries once on token expiry (401).

    Error codes returned in the `error` field (never raises 5xx):
      no_credentials  — REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set
      auth_failed     — invalid credentials
      rate_limited    — 429 from Reddit API
      timeout         — network timeout
      network_error   — other connectivity error
    """
    if not is_configured():
        _log("Search rejected — credentials not configured")
        return RedditSearchResult(
            success=False,
            category=payload.category,
            location=payload.location,
            error="no_credentials",
        )

    _log(f"Search started — category={payload.category!r} location={payload.location!r} limit={payload.limit}")

    result = await run_reddit_search(
        category=payload.category,
        location=payload.location,
        limit=payload.limit,
    )

    candidates = result.get("candidates", [])
    _log(
        f"Search complete — posts={result['posts_discovered']} "
        f"candidates={len(candidates)} elapsed={result['elapsed_seconds']}s"
    )

    return RedditSearchResult(
        success=result.get("error") is None,
        category=payload.category,
        location=payload.location,
        queries_run=result.get("queries_run", 0),
        posts_discovered=result.get("posts_discovered", 0),
        candidates=candidates,
        candidates_found=len(candidates),
        elapsed_seconds=result.get("elapsed_seconds", 0.0),
        error=result.get("error"),
    )
