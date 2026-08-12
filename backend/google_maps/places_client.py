"""
google_maps/places_client.py
─────────────────────────────
Thin async wrapper around the Google Places API (New).

Responsibilities
────────────────
  • POST /places:searchText with correct headers, field mask, auth.
  • Paginate via nextPageToken up to MAX_PAGES_PER_QUERY.
  • Return (raw_places: list[dict], api_calls_made: int).
  • Log every API call — NEVER logs the API key.
  • Handle all HTTP errors safely.

Zero imports from the existing lead-gen pipeline.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from google_maps.config import (
    GOOGLE_MAPS_API_KEY,
    PLACES_TEXT_SEARCH_URL,
    PLACES_PAGE_SIZE,
    MAX_PAGES_PER_QUERY,
    HTTP_TIMEOUT,
    FIELD_MASK,
    PAGE_PAUSE_SECONDS,
)


def _log(msg: str) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [GOOGLE_MAPS] {msg}", flush=True)


# ── Shared async client (one per process) ────────────────────────────────────
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(HTTP_TIMEOUT),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
            follow_redirects=True,
        )
    return _client


# ── Single-page API call ──────────────────────────────────────────────────────

async def _text_search_one_page(
    text_query: str,
    page_token: Optional[str] = None,
) -> dict:
    """
    POST /places:searchText — one page.

    Returns the raw JSON dict on success, or {} on any failure.
    NEVER logs the API key.
    """
    if not GOOGLE_MAPS_API_KEY:
        _log("GOOGLE_MAPS_API_KEY not set — skipping API call")
        return {}

    headers = {
        "Content-Type":     "application/json",
        "X-Goog-Api-Key":   GOOGLE_MAPS_API_KEY,   # key in header, NOT in URL
        "X-Goog-FieldMask": FIELD_MASK,
    }

    body: dict = {
        "textQuery":    text_query,
        "languageCode": "en",
        "pageSize":     PLACES_PAGE_SIZE,
    }

    if page_token:
        body["pageToken"] = page_token

    client = _get_client()
    try:
        resp = await client.post(
            PLACES_TEXT_SEARCH_URL,
            headers=headers,
            json=body,
        )

        # Log status without revealing the key
        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 400:
            _log(f"API Error 400 (bad request) for query={text_query!r}: {resp.text[:300]}")
            return {}
        if resp.status_code == 401:
            _log("API Error 401 — API key is invalid or missing. Check GOOGLE_MAPS_API_KEY in .env")
            return {}
        if resp.status_code == 403:
            _log(
                "API Error 403 — Places API (New) is not enabled for this project, "
                "or billing is not set up. Enable it at https://console.cloud.google.com/"
            )
            return {}
        if resp.status_code == 429:
            _log("API Error 429 — rate limited. Waiting 2 seconds before continuing.")
            await asyncio.sleep(2)
            return {}

        resp.raise_for_status()
        return {}

    except httpx.TimeoutException:
        _log(f"Timeout on query={text_query!r}")
        return {}
    except httpx.HTTPStatusError as exc:
        _log(f"HTTP {exc.response.status_code} on query={text_query!r}")
        return {}
    except Exception as exc:
        _log(f"Unexpected error on query={text_query!r}: {type(exc).__name__}: {exc}")
        return {}


# ── Multi-page fetch ──────────────────────────────────────────────────────────

async def fetch_all_pages(
    text_query: str,
    area_label: str = "",
) -> tuple[list[dict], int]:
    """
    Fetch all pages for a single (query, area) combination.

    Stops when:
      • nextPageToken is absent (no more results), OR
      • MAX_PAGES_PER_QUERY pages have been fetched.

    Returns:
        (raw_places, api_calls_made)
        raw_places    — flat list of place dicts from all pages
        api_calls_made — number of HTTP calls made (for stats)
    """
    all_places: list[dict] = []
    page_token: Optional[str] = None
    api_calls = 0

    for page_num in range(1, MAX_PAGES_PER_QUERY + 1):
        _log(
            f"Query: {text_query!r} | "
            f"Locality: {area_label!r} | "
            f"Page: {page_num}/{MAX_PAGES_PER_QUERY}"
        )

        response = await _text_search_one_page(text_query, page_token=page_token)
        api_calls += 1

        places_this_page = response.get("places") or []
        all_places.extend(places_this_page)

        _log(
            f"Raw results: {len(places_this_page)} | "
            f"Running total raw: {len(all_places)} | "
            f"Locality: {area_label!r}"
        )

        page_token = response.get("nextPageToken")
        if not page_token:
            break

        # Short pause between pages (per Google guidance)
        if page_num < MAX_PAGES_PER_QUERY:
            await asyncio.sleep(PAGE_PAUSE_SECONDS)

    return all_places, api_calls
