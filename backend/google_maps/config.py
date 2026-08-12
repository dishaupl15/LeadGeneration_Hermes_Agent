"""
google_maps/config.py
──────────────────────
All configuration for the Google Maps module loaded ONLY from environment
variables.  No secrets are ever hard-coded here.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── API key — loaded from .env, never hard-coded ──────────────────────────────
GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")

# ── API endpoint (Places API New) ─────────────────────────────────────────────
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# ── Pagination ────────────────────────────────────────────────────────────────
# Google Places API (New) max pageSize = 20
PLACES_PAGE_SIZE: int = int(os.getenv("GMAPS_PAGE_SIZE", "20"))

# Maximum pages to fetch per (query, area) pair — controls cost per query
MAX_PAGES_PER_QUERY: int = int(os.getenv("GMAPS_MAX_PAGES", "3"))

# Hard ceiling: max total API calls per single /maps-leads/generate request
MAX_QUERIES_PER_REQUEST: int = int(os.getenv("GMAPS_MAX_QUERIES_PER_REQUEST", "200"))

# ── HTTP settings ─────────────────────────────────────────────────────────────
HTTP_TIMEOUT: float  = float(os.getenv("GMAPS_HTTP_TIMEOUT", "15"))

# Max concurrent HTTP calls to Google at once
MAX_CONCURRENCY: int = int(os.getenv("GMAPS_MAX_CONCURRENCY", "3"))

# Pause between paginated requests (Google recommends a small delay)
PAGE_PAUSE_SECONDS: float = float(os.getenv("GMAPS_PAGE_PAUSE", "0.3"))

# ── Field mask — ONLY request fields we actually use (controls billing) ───────
# primaryType is cheaper than listing all types and gives the most relevant tag.
FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.nationalPhoneNumber,"
    "places.internationalPhoneNumber,"
    "places.websiteUri,"
    "places.primaryType,"
    "places.location,"
    "places.googleMapsUri,"
    "places.businessStatus,"
    "nextPageToken"
)

# ── Cross-request deduplication ───────────────────────────────────────────────
# MongoDB collection name for tracking seen place IDs (isolated from leads collection)
SEEN_COLLECTION_NAME: str = os.getenv("GMAPS_SEEN_COLLECTION", "google_maps_seen")
