"""
google_maps/discovery.py
─────────────────────────
Core Google Maps lead-discovery engine.

Algorithm
─────────
1.  Load previously-seen place IDs from MongoDB (cross-request dedup).
2.  Resolve state + district → ordered list of search areas (localities).
3.  For each area (sequential to enable early stopping):
      a. Build multiple category-specific search queries.
      b. For each query (sequential):
           - Call fetch_all_pages() → raw places + api call count.
           - Normalise each place → MapBusiness.
           - Skip if place_id seen (this request OR previous requests).
           - Skip on secondary dedup: normalised name+address, website domain, phone.
           - Accept and mark_seen().
           - Log progress with the required format.
           - STOP immediately once target is reached.
4.  Hard cap: MAX_QUERIES_PER_REQUEST limits total API calls regardless of target.
5.  Return (businesses, stats).

Isolation: ZERO imports from app/services/, src/routes/, or tools/.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Optional
from urllib.parse import urlparse

from google_maps.config import MAX_CONCURRENCY, MAX_QUERIES_PER_REQUEST
from google_maps.geography import resolve_areas
from google_maps.places_client import fetch_all_pages
from google_maps.schemas import MapBusiness, MapLeadsStats
from google_maps.seen_store import is_seen, load_from_db, mark_seen


# ── Logging helper ────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [GOOGLE_MAPS] {msg}", flush=True)


# ── Category → search phrases ─────────────────────────────────────────────────
# Each entry provides distinct phrases that return DIFFERENT results from Google.
# Keep phrases concrete and industry-specific to avoid irrelevant results.

_CATEGORY_PHRASES: dict[str, list[str]] = {
    # ── AI / Artificial Intelligence ─────────────────────────────────────────
    # Use SPECIFIC phrases so Google Maps returns relevant businesses.
    # Generic "AI" matches unrelated businesses with "AI" in their Hindi/local
    # name. Phrases like "artificial intelligence company" are far more precise.
    "ai": [
        "artificial intelligence company",
        "AI software company",
        "machine learning company",
        "deep learning company",
        "AI technology company",
        "AI solutions company",
        "AI startup",
        "AI services company",
        "generative AI company",
        "NLP company",
        "computer vision company",
        "intelligent automation company",
        "AI consulting firm",
        "AI platform company",
        "data science company",
    ],
    "artificial intelligence": [
        "artificial intelligence company",
        "AI software company",
        "machine learning company",
        "AI technology company",
        "AI solutions company",
        "AI startup",
        "generative AI company",
        "intelligent automation company",
        "AI consulting firm",
        "data science company",
    ],
    "machine learning": [
        "machine learning company",
        "AI machine learning startup",
        "data science company",
        "deep learning company",
        "AI software company",
    ],
    "real estate":      [
        "real estate company",
        "property developer",
        "builder developer",
        "housing developer",
        "realty company",
        "real estate developer",
    ],
    "technology":       ["IT company", "technology company", "software company", "tech startup"],
    "it":               ["IT company", "software company", "information technology services", "IT services company"],
    "fintech":          ["fintech company", "financial technology company", "digital payments company", "payments startup"],
    "healthcare":       ["hospital", "healthcare company", "multispecialty clinic", "medical center", "diagnostics center"],
    "pharma":           [
        "pharmaceutical company",
        "pharma company",
        "drug manufacturer",
        "medicine manufacturer",
        "pharma manufacturing",
    ],
    "manufacturing":    [
        "manufacturing company",
        "industrial manufacturer",
        "engineering manufacturer",
        "fabrication company",
        "precision engineering",
    ],
    "construction":     [
        "construction company",
        "construction contractor",
        "building contractor",
        "civil contractor",
        "infrastructure company",
        "real estate developer",
    ],
    "education":        ["school", "college", "education company", "coaching institute", "training center", "academy"],
    "logistics":        ["logistics company", "transport company", "freight company", "courier service", "supply chain company"],
    "automotive":       ["automobile dealer", "car dealer", "auto components manufacturer", "vehicle manufacturer"],
    "retail":           ["retail store", "supermarket", "departmental store", "retail chain", "consumer goods company"],
    "e-commerce":       ["ecommerce company", "online retail company", "d2c brand"],
    "hospitality":      ["hotel", "resort", "hospitality company", "accommodation provider"],
    "travel":           ["travel agency", "tour operator", "holiday company", "travel company"],
    "energy":           ["solar energy company", "power company", "renewable energy company", "electrical contractor"],
    "agriculture":      ["agriculture company", "agribusiness company", "farming company", "fertilizer company", "agri input"],
    "media":            ["media company", "news agency", "digital media company", "publishing house"],
    "finance":          ["financial services company", "investment company", "nbfc", "wealth management company"],
    "insurance":        ["insurance company", "insurance broker"],
    "consulting":       ["consulting firm", "management consultancy", "business consulting firm"],
    "legal":            ["law firm", "legal services firm", "advocate office"],
    "marketing":        ["marketing agency", "digital marketing company", "advertising agency"],
    "biotech":          ["biotechnology company", "biotech firm", "life sciences company", "biopharma"],
    "cybersecurity":    ["cybersecurity company", "information security company", "IT security firm"],
    "saas":             ["SaaS company", "cloud software company", "software platform company"],
    "aerospace":        ["aerospace company", "aviation company", "defense company"],
    "telecommunications": ["telecom company", "internet service provider", "broadband company"],
    "food":             ["food processing company", "food manufacturing company", "food company", "beverage company"],
    "textile":          ["textile company", "garment manufacturer", "apparel company", "fabric manufacturer"],
    "chemicals":        ["chemical company", "specialty chemicals company", "chemical manufacturer"],
}


def _get_phrases(category: str) -> list[str]:
    """Return search phrases for a category. Falls back to generic phrases."""
    cat = category.lower().strip()

    # Alias map: normalise common variant spellings to a canonical key
    _ALIAS: dict[str, str] = {
        "ai": "ai",
        "artificial intelligence": "artificial intelligence",
        "machine learning": "machine learning",
        "ml": "machine learning",
        "deep learning": "machine learning",
        "generative ai": "ai",
        "gen ai": "ai",
        "nlp": "ai",
        "real estate": "real estate",
        "realty": "real estate",
        "property": "real estate",
        "it": "it",
        "information technology": "it",
        "software": "it",
        "tech": "technology",
        "technology": "technology",
        "fintech": "fintech",
        "financial technology": "fintech",
        "healthcare": "healthcare",
        "health": "healthcare",
        "pharma": "pharma",
        "pharmaceutical": "pharma",
        "pharmaceuticals": "pharma",
        "manufacturing": "manufacturing",
        "fabrication": "manufacturing",
        "industrial": "manufacturing",
        "construction": "construction",
        "contractor": "construction",
        "civil": "construction",
        "education": "education",
        "edtech": "education",
        "logistics": "logistics",
        "transport": "logistics",
        "automotive": "automotive",
        "automobile": "automotive",
        "auto": "automotive",
        "retail": "retail",
        "fmcg": "retail",
        "agriculture": "agriculture",
        "agri": "agriculture",
        "agro": "agriculture",
        "farming": "agriculture",
        "media": "media",
        "entertainment": "media",
        "finance": "finance",
        "insurance": "insurance",
        "consulting": "consulting",
        "legal": "legal",
        "marketing": "marketing",
        "biotech": "biotech",
        "biotechnology": "biotech",
        "life sciences": "biotech",
        "cybersecurity": "cybersecurity",
        "cyber security": "cybersecurity",
        "saas": "saas",
        "aerospace": "aerospace",
        "telecommunications": "telecommunications",
        "telecom": "telecommunications",
        "food": "food",
        "food and beverage": "food",
        "f&b": "food",
        "textile": "textile",
        "garment": "textile",
        "apparel": "textile",
        "chemicals": "chemicals",
        "chemical": "chemicals",
        "energy": "energy",
        "solar": "energy",
        "renewable energy": "energy",
        "hospitality": "hospitality",
        "hotel": "hospitality",
        "travel": "travel",
        "ecommerce": "e-commerce",
        "e-commerce": "e-commerce",
    }

    # Resolve alias
    resolved = _ALIAS.get(cat, cat)

    if resolved in _CATEGORY_PHRASES:
        return _CATEGORY_PHRASES[resolved]

    # Substring match against canonical keys
    for key, phrases in _CATEGORY_PHRASES.items():
        if key in resolved or resolved in key:
            return phrases

    # Generic fallback — use category name + common qualifiers
    # Wrap in quotes to force Google Maps to treat it as a literal phrase
    return [
        f'"{category}" company',
        f'"{category}" services',
        f'"{category}" startup',
        f'"{category}" solutions',
    ]


def _build_queries(category: str, area: str, state: str) -> list[str]:
    """
    Build unique, non-duplicate search query strings for this (category, area, state).

    Format: "<phrase> in <area>, <state>, India"
    """
    phrases = _get_phrases(category)
    # Avoid repeating the state name if already in area
    if state and state.lower() not in area.lower():
        location = f"{area}, {state}, India"
    else:
        location = f"{area}, India"

    seen_q: set[str] = set()
    queries: list[str] = []
    for phrase in phrases:
        q = f"{phrase} in {location}"
        if q not in seen_q:
            queries.append(q)
            seen_q.add(q)
    return queries


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalise_place(raw: dict, query: str, area: str) -> Optional[MapBusiness]:
    """Convert a raw API place dict into a MapBusiness. Returns None if unusable."""
    place_id = (raw.get("id") or "").strip()
    if not place_id:
        return None

    display = raw.get("displayName") or {}
    name = (display.get("text") or "").strip()
    if not name:
        return None

    address      = (raw.get("formattedAddress") or "").strip()
    intl_phone   = (raw.get("internationalPhoneNumber") or "").strip()
    natl_phone   = (raw.get("nationalPhoneNumber") or "").strip()
    phone        = intl_phone or natl_phone or None
    website      = (raw.get("websiteUri") or "").strip() or None
    maps_uri     = (raw.get("googleMapsUri") or "").strip() or None
    primary_type = (raw.get("primaryType") or "").strip() or None

    loc = raw.get("location") or {}
    lat = loc.get("latitude")
    lng = loc.get("longitude")

    # Skip permanently closed businesses
    if raw.get("businessStatus") == "CLOSED_PERMANENTLY":
        return None

    return MapBusiness(
        place_id=place_id,
        name=name,
        address=address,
        phone=phone,
        website=website,
        google_maps_uri=maps_uri,
        primary_type=primary_type,
        latitude=lat,
        longitude=lng,
        source="google_maps",
        search_query=query,
        search_area=area,
    )


# ── Secondary deduplication keys ──────────────────────────────────────────────

def _normalised_name(name: str) -> str:
    """Lowercase, strip punctuation, remove common suffixes for name comparison."""
    n = name.lower()
    n = re.sub(r'[^\w\s]', ' ', n)
    n = re.sub(r'\b(pvt|ltd|private|limited|llp|inc|llc|and|the|co)\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def _website_domain(url: str) -> str:
    """Extract the bare domain from a URL for dedup comparison."""
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
        domain = parsed.netloc.lower().lstrip("www.")
        return domain
    except Exception:
        return url.lower().strip()


def _digits_only(phone: str) -> str:
    """Strip non-digit characters for phone comparison."""
    return re.sub(r'\D', '', phone or '')


# ── Main discovery function ───────────────────────────────────────────────────

async def discover_businesses(
    category:     str,
    state:        str,
    district:     Optional[str],
    target:       int,
    exclude_seen: bool = True,
) -> tuple[list[MapBusiness], MapLeadsStats]:
    """
    Discover unique businesses from Google Maps.

    Processing is SEQUENTIAL per area and per query so that:
      • Early stopping works the moment target is reached.
      • Cost is minimised — no over-fetching.
      • Logging is clean and ordered.

    Returns (businesses, stats).
    """
    t0 = time.monotonic()
    stats = MapLeadsStats()

    # ── Resolve geography ──────────────────────────────────────────────────────
    areas = resolve_areas(state, district or "")
    if not areas:
        areas = [district or state]
    stats.areas_list = list(areas)

    # ── Log start ──────────────────────────────────────────────────────────────
    _log("Request started")
    _log(f"Category: {category}")
    _log(f"State: {state}")
    _log(f"District: {district or '(all districts)'}")
    _log(f"Target: {target}")
    _log(f"Resolved search areas ({len(areas)}): {areas}")

    # ── Load previously-seen IDs from DB ───────────────────────────────────────
    if exclude_seen:
        loaded = await load_from_db(category, state, district or "")
        if loaded:
            _log(f"Loaded {loaded} previously-seen place IDs from DB (will skip duplicates)")

    # ── Per-request dedup stores ───────────────────────────────────────────────
    # Primary: place_id (authoritative)
    seen_place_ids: set[str] = set()
    # Secondary: protects against same business under slightly different IDs
    seen_norm_names: set[str]    = set()
    seen_domains:    set[str]    = set()
    seen_phones:     set[str]    = set()

    results:        list[MapBusiness] = []
    queries_done = 0

    # ── Semaphore for concurrent HTTP calls ────────────────────────────────────
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    # ── Sequential area + query loop ───────────────────────────────────────────
    for area in areas:
        if len(results) >= target:
            break
        if queries_done >= MAX_QUERIES_PER_REQUEST:
            _log(f"MAX_QUERIES_PER_REQUEST={MAX_QUERIES_PER_REQUEST} reached — stopping")
            break

        _log(f"Locality: {area}")
        queries = _build_queries(category, area, state)
        stats.areas_searched += 1

        for query in queries:
            if len(results) >= target:
                break
            if queries_done >= MAX_QUERIES_PER_REQUEST:
                _log(f"Query cap reached ({MAX_QUERIES_PER_REQUEST}) — stopping")
                break

            _log(f"Query: {query}")
            queries_done += 1
            stats.queries_executed += 1

            async with sem:
                raw_places, api_calls = await fetch_all_pages(
                    text_query=query,
                    area_label=area,
                )

            stats.total_api_calls  += api_calls
            stats.total_raw_results += len(raw_places)

            _log(f"Raw results: {len(raw_places)}")

            new_this_query      = 0
            dupes_this_query    = 0
            prev_seen_this_query = 0

            for raw in raw_places:
                if len(results) >= target:
                    break

                biz = _normalise_place(raw, query, area)
                if biz is None:
                    continue

                # ── Primary dedup: place_id (this request) ─────────────────────
                if biz.place_id in seen_place_ids:
                    dupes_this_query += 1
                    stats.duplicates_removed += 1
                    continue

                # ── Cross-request dedup: place_id seen before ──────────────────
                if exclude_seen and await is_seen(biz.place_id, category, state, district or ""):
                    prev_seen_this_query += 1
                    stats.previously_seen += 1
                    seen_place_ids.add(biz.place_id)  # cache locally
                    continue

                # ── Secondary dedup: normalised name ───────────────────────────
                norm_name = _normalised_name(biz.name)
                if norm_name and norm_name in seen_norm_names:
                    dupes_this_query += 1
                    stats.secondary_dupes += 1
                    continue

                # ── Secondary dedup: website domain ────────────────────────────
                if biz.website:
                    domain = _website_domain(biz.website)
                    if domain and domain in seen_domains:
                        dupes_this_query += 1
                        stats.secondary_dupes += 1
                        continue

                # ── Secondary dedup: phone digits ──────────────────────────────
                if biz.phone:
                    digits = _digits_only(biz.phone)
                    if len(digits) >= 7 and digits in seen_phones:
                        dupes_this_query += 1
                        stats.secondary_dupes += 1
                        continue

                # ── Accept ─────────────────────────────────────────────────────
                seen_place_ids.add(biz.place_id)
                if norm_name:
                    seen_norm_names.add(norm_name)
                if biz.website:
                    d = _website_domain(biz.website)
                    if d:
                        seen_domains.add(d)
                if biz.phone:
                    dig = _digits_only(biz.phone)
                    if len(dig) >= 7:
                        seen_phones.add(dig)

                results.append(biz)
                new_this_query += 1

                # Mark in cross-request store
                if exclude_seen:
                    await mark_seen(biz.place_id, biz.name, category, state, district or "")

            _log(
                f"New unique results: {new_this_query} | "
                f"Duplicates skipped: {dupes_this_query} | "
                f"Previously seen: {prev_seen_this_query}"
            )
            _log(f"Progress: {len(results)}/{target}")

            if len(results) >= target:
                _log("Target reached")
                break

        if len(results) >= target:
            break

    # ── Final stats ────────────────────────────────────────────────────────────
    stats.with_phone    = sum(1 for b in results if b.phone)
    stats.with_website  = sum(1 for b in results if b.website)
    stats.target_reached = len(results) >= target
    stats.exhausted     = (not stats.target_reached) and (queries_done < MAX_QUERIES_PER_REQUEST)
    stats.elapsed_seconds = round(time.monotonic() - t0, 2)

    _log(
        f"COMPLETE — "
        f"returned={len(results)} | "
        f"target={target} | "
        f"api_calls={stats.total_api_calls} | "
        f"raw={stats.total_raw_results} | "
        f"dupes={stats.duplicates_removed} | "
        f"secondary_dupes={stats.secondary_dupes} | "
        f"prev_seen={stats.previously_seen} | "
        f"with_phone={stats.with_phone} | "
        f"with_website={stats.with_website} | "
        f"areas_searched={stats.areas_searched} | "
        f"queries={stats.queries_executed} | "
        f"elapsed={stats.elapsed_seconds}s"
    )

    return results, stats
