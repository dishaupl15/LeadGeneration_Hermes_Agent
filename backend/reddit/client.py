"""
reddit/client.py
─────────────────
Raw HTTP layer for the Reddit OAuth2 API.

Responsibilities
────────────────
  - Obtain and cache application-only OAuth2 access token
  - Execute authenticated search requests against reddit.com/search.json
  - Handle all HTTP-level errors gracefully (never raises)
  - Parse and normalise Reddit Listing responses into RedditPost objects
  - Log status without ever printing credentials

Auth flow used
──────────────
  "Application-only" OAuth2 (no user login required):
    POST https://www.reddit.com/api/v1/access_token
    Authorization: Basic base64(client_id:client_secret)
    Body: grant_type=client_credentials

  Token is cached in module-level state and refreshed when expired.

Isolation
─────────
  Only imports from: reddit/config.py, reddit/schemas.py + stdlib + httpx
"""
from __future__ import annotations

import base64
import time
from datetime import datetime
from typing import Optional

import httpx

from reddit.config import (
    REDDIT_API_BASE,
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_MAX_POSTS,
    REDDIT_REQUEST_TIMEOUT,
    REDDIT_TOKEN_URL,
    REDDIT_USER_AGENT,
    is_configured,
)
from reddit.schemas import RedditPost


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [REDDIT] {msg}", flush=True)


# ── Token cache ───────────────────────────────────────────────────────────────

_token:        Optional[str] = None
_token_expiry: float         = 0.0   # UNIX timestamp when token expires


def _token_valid() -> bool:
    """Return True if we have a non-expired cached token."""
    return bool(_token and time.time() < _token_expiry - 30)


def _clear_token() -> None:
    global _token, _token_expiry
    _token = None
    _token_expiry = 0.0


# ── OAuth2 token fetch ────────────────────────────────────────────────────────

async def get_access_token() -> tuple[Optional[str], Optional[str]]:
    """
    Obtain an application-only OAuth2 access token from Reddit.

    Returns (token, error_code):
      - token is the access token string on success, None on failure
      - error_code is None on success, or one of:
          "no_credentials" | "auth_failed" | "timeout" | "network_error" | "server_error"

    Caches the token in module-level state until it expires.
    Never raises.
    """
    global _token, _token_expiry

    if _token_valid():
        return _token, None

    if not is_configured():
        return None, "no_credentials"

    credentials = base64.b64encode(
        f"{REDDIT_CLIENT_ID}:{REDDIT_CLIENT_SECRET}".encode()
    ).decode()

    _log("Authenticating with Reddit OAuth2…")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(REDDIT_REQUEST_TIMEOUT),
            follow_redirects=True,
        ) as client:
            resp = await client.post(
                REDDIT_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "User-Agent":    REDDIT_USER_AGENT,
                    "Content-Type":  "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
    except httpx.TimeoutException:
        _log("Auth timeout")
        return None, "timeout"
    except httpx.RequestError as exc:
        _log(f"Auth network error: {exc}")
        return None, "network_error"
    except Exception as exc:
        _log(f"Auth unexpected error: {exc}")
        return None, "network_error"

    if resp.status_code == 401:
        _log("Auth failed (401) — check REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET")
        return None, "auth_failed"
    if resp.status_code >= 500:
        _log(f"Auth server error ({resp.status_code})")
        return None, "server_error"
    if not resp.is_success:
        _log(f"Auth HTTP {resp.status_code}")
        return None, f"http_{resp.status_code}"

    try:
        data = resp.json()
    except Exception:
        return None, "parse_error"

    token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3600))

    if not token:
        _log("Auth succeeded but no access_token in response")
        return None, "no_token"

    _token = token
    _token_expiry = time.time() + expires_in
    _log(f"Authentication successful (expires_in={expires_in}s)")
    return token, None


# ── Search posts ──────────────────────────────────────────────────────────────

async def search_reddit_posts(
    query: str,
    limit: int = 25,
    sort: str = "relevance",
    time_filter: str = "year",
) -> tuple[list[RedditPost], Optional[str]]:
    """
    Search Reddit for public submissions matching the query.

    Uses GET /search.json via the OAuth2 API.

    Returns (posts, error_code):
      - posts is a list of RedditPost objects (may be [])
      - error_code is None on success, or a string error code

    Parameters:
      query        — search query string
      limit        — max posts to fetch (capped at REDDIT_MAX_POSTS)
      sort         — "relevance" | "new" | "top" | "comments"
      time_filter  — "hour" | "day" | "week" | "month" | "year" | "all"

    Never raises.
    """
    token, err = await get_access_token()
    if err or not token:
        return [], err or "no_token"

    cap = min(limit, REDDIT_MAX_POSTS, 100)
    _log(f"Search → {query!r} (limit={cap}, sort={sort}, t={time_filter})")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(REDDIT_REQUEST_TIMEOUT),
            follow_redirects=True,
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent":    REDDIT_USER_AGENT,
            },
        ) as client:
            resp = await client.get(
                f"{REDDIT_API_BASE}/search.json",
                params={
                    "q":      query,
                    "type":   "link",          # submissions only
                    "sort":   sort,
                    "t":      time_filter,
                    "limit":  cap,
                    "restrict_sr": "false",    # search all of Reddit
                },
            )
    except httpx.TimeoutException:
        _log(f"Search timeout for {query!r}")
        return [], "timeout"
    except httpx.RequestError as exc:
        _log(f"Search network error: {exc}")
        return [], "network_error"
    except Exception as exc:
        _log(f"Search unexpected error: {exc}")
        return [], "network_error"

    if resp.status_code == 401:
        # Token may have expired mid-session — clear and signal caller to retry once
        _clear_token()
        _log("Search 401 — token expired, cleared")
        return [], "auth_failed"
    if resp.status_code == 429:
        _log("Search rate limited (429)")
        return [], "rate_limited"
    if resp.status_code >= 500:
        _log(f"Search server error ({resp.status_code})")
        return [], "server_error"
    if not resp.is_success:
        _log(f"Search HTTP {resp.status_code} for {query!r}")
        return [], f"http_{resp.status_code}"

    try:
        data = resp.json()
    except Exception as exc:
        _log(f"Search JSON parse error: {exc}")
        return [], "parse_error"

    children = (
        (data.get("data") or {}).get("children") or []
    )

    posts: list[RedditPost] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        kind = child.get("kind", "")
        post_data = child.get("data") or {}
        if not isinstance(post_data, dict):
            continue

        # Skip non-submissions (comments, subreddits)
        if kind not in ("t3", ""):
            continue

        post_id = post_data.get("id") or post_data.get("name", "")
        if not post_id:
            continue

        title    = (post_data.get("title") or "").strip()
        text     = (post_data.get("selftext") or "").strip()
        author   = post_data.get("author")
        subreddit = post_data.get("subreddit") or post_data.get("subreddit_name_prefixed", "").lstrip("r/")
        permalink = post_data.get("permalink", "")
        post_url  = f"https://www.reddit.com{permalink}" if permalink else (
            post_data.get("url") or ""
        )
        created_utc = float(post_data.get("created_utc") or 0)
        score       = int(post_data.get("score") or 0)
        num_comments= int(post_data.get("num_comments") or 0)

        # Skip deleted/removed posts
        if text in ("[deleted]", "[removed]") or author in ("None", None, "[deleted]"):
            pass  # keep the post but note author may be unknown

        if not title:
            continue

        posts.append(RedditPost(
            post_id=post_id,
            title=title,
            text=text if text not in ("[deleted]", "[removed]") else "",
            author=author if author not in (None, "None", "[deleted]") else None,
            subreddit=subreddit or "unknown",
            post_url=post_url,
            created_utc=created_utc,
            score=score,
            num_comments=num_comments,
            search_query=query,
        ))

    _log(f"Search returned {len(posts)} posts for {query!r}")
    return posts, None


# ── Probe auth (for auth-test endpoint) ──────────────────────────────────────

async def probe_auth() -> tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Attempt to obtain an OAuth2 token and verify identity.
    Returns (http_status, error_code, username_or_none).
    Never raises.
    """
    if not is_configured():
        return None, "no_credentials", None

    # Clear cached token so we always do a fresh test
    _clear_token()

    token, err = await get_access_token()

    if err or not token:
        _err_http_map = {
            "auth_failed":   401,
            "timeout":       None,
            "network_error": None,
            "server_error":  500,
        }
        return _err_http_map.get(err), err, None

    # Verify token by calling /api/v1/me (application-only tokens return limited info)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent":    REDDIT_USER_AGENT,
            },
        ) as client:
            resp = await client.get(f"{REDDIT_API_BASE}/api/v1/me")
    except Exception:
        # /api/v1/me may return 403 for app-only tokens — that is fine,
        # it still proves the token is valid
        return 200, None, None

    if resp.status_code in (200, 403):
        username = None
        try:
            me = resp.json()
            username = me.get("name")
        except Exception:
            pass
        return resp.status_code, None, username

    if resp.status_code == 401:
        _clear_token()
        return 401, "auth_failed", None

    return resp.status_code, None, None
