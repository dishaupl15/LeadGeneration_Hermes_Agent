"""
google_maps/routes.py
──────────────────────
FastAPI router for the isolated Google Maps lead-generation module.

Mounted at /maps-leads/ in app/main.py.

Endpoints
─────────
GET  /maps-leads/health                  API key + module status
GET  /maps-leads/states                  List all Indian states
GET  /maps-leads/districts/{state}       List districts for a state
POST /maps-leads/generate                Run discovery
DELETE /maps-leads/seen/{state}/{cat}    Clear cross-request seen cache for a scope

This router DOES NOT import from:
  - app/services/  (CompanyEnrich, Serper, Firecrawl, Hermes, …)
  - src/routes/leads.py
  - tools/leadgen.py
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, status

from google_maps.config import GOOGLE_MAPS_API_KEY
from google_maps.discovery import discover_businesses
from google_maps.geography import get_all_states, get_districts
from google_maps.schemas import (
    DistrictsResponse,
    MapLeadsRequest,
    MapLeadsResponse,
    StatesResponse,
)
from google_maps.seen_store import clear_session, count_seen

router = APIRouter(
    prefix="/maps-leads",
    tags=["Google Maps Leads"],
)


def _log(msg: str) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [GOOGLE_MAPS] {msg}", flush=True)


# ── Health ────────────────────────────────────────────────────────────────────

@router.get(
    "/health",
    summary="Google Maps module health check",
    response_model=dict,
    tags=["Google Maps Leads"],
)
def maps_health():
    """Returns API key status and readiness of the Google Maps module."""
    configured = bool(GOOGLE_MAPS_API_KEY)
    return {
        "module":       "google_maps",
        "api_key_set":  configured,
        "status":       "ready" if configured else "no_key",
        "message": (
            "GOOGLE_MAPS_API_KEY is configured — module is ready."
            if configured
            else (
                "GOOGLE_MAPS_API_KEY is not set. "
                "Add it to backend/.env and restart the server."
            )
        ),
    }


# ── Geography helpers ─────────────────────────────────────────────────────────

@router.get(
    "/states",
    summary="List all searchable Indian states",
    response_model=StatesResponse,
    tags=["Google Maps Leads"],
)
def list_states():
    """Return sorted list of all states that have geographic subdivision data."""
    return StatesResponse(states=get_all_states())


@router.get(
    "/districts/{state}",
    summary="List districts for a given state",
    response_model=DistrictsResponse,
    tags=["Google Maps Leads"],
)
def list_districts(
    state: str = Path(..., example="Maharashtra", description="State name (case-insensitive)"),
):
    """Return all districts/cities configured for the given state."""
    districts = get_districts(state)
    if not districts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State '{state}' not found or has no district data.",
        )
    return DistrictsResponse(state=state, districts=districts)


# ── Seen-cache management ─────────────────────────────────────────────────────

@router.delete(
    "/seen",
    summary="Clear cross-request seen-cache for a scope",
    response_model=dict,
    tags=["Google Maps Leads"],
)
async def clear_seen_cache(
    category: str = Query(..., example="construction"),
    state:    str = Query(..., example="Maharashtra"),
    district: str = Query("",  example="Pune"),
):
    """
    Clear the in-memory (and optionally MongoDB) seen-cache for the given
    category + state + district.  Use this to allow re-discovering companies
    that were returned in previous requests.
    """
    before = await count_seen(category, state, district)
    await clear_session(category, state, district)
    return {
        "cleared":  True,
        "category": category,
        "state":    state,
        "district": district or "(all)",
        "ids_cleared": before,
    }


# ── Main discovery endpoint ───────────────────────────────────────────────────

@router.post(
    "/generate",
    summary="Discover businesses via Google Maps for a category and state/district",
    response_model=MapLeadsResponse,
    status_code=status.HTTP_200_OK,
    tags=["Google Maps Leads"],
)
async def generate_map_leads(payload: MapLeadsRequest):
    """
    Discover real businesses from Google Maps (Places API New).

    Flow
    ────
    1. Resolve state + district → geographic localities.
    2. Build multiple targeted queries per locality.
    3. Call Google Places Text Search (paginated) for each query.
    4. Deduplicate by place_id (primary) and name/website/phone (secondary).
    5. Skip place_ids seen in previous requests (when exclude_seen=true).
    6. Stop the moment target unique businesses are collected.
    7. Return businesses with name, address, phone, website, Maps URI.

    No existing pipeline (CompanyEnrich/Serper/Firecrawl/Hermes) is called.
    """
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google Maps module is not configured. "
                "Add GOOGLE_MAPS_API_KEY=<your_key> to backend/.env and restart."
            ),
        )

    _log(f"POST /maps-leads/generate | "
         f"category={payload.category!r} state={payload.state!r} "
         f"district={payload.district!r} target={payload.target} "
         f"exclude_seen={payload.exclude_seen}")

    try:
        businesses, stats = await discover_businesses(
            category=payload.category,
            state=payload.state,
            district=payload.district,
            target=payload.target,
            exclude_seen=payload.exclude_seen,
        )
    except Exception as exc:
        _log(f"Discovery error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Maps discovery error: {type(exc).__name__}: {exc}",
        )

    if stats.target_reached:
        message = f"Target of {payload.target} reached — {len(businesses)} unique businesses returned."
    elif stats.exhausted:
        message = (
            f"All search areas exhausted — found {len(businesses)} unique businesses "
            f"(target was {payload.target})."
        )
    else:
        message = (
            f"Query limit reached — found {len(businesses)} unique businesses "
            f"(target was {payload.target})."
        )

    return MapLeadsResponse(
        success=True,
        category=payload.category,
        state=payload.state,
        district=payload.district,
        target=payload.target,
        total=len(businesses),
        businesses=businesses,
        stats=stats,
        message=message,
    )
