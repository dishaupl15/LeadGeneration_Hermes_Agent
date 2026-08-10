"""
app/services/google_places_service.py
───────────────────────────────────────
Google Places API (New) — business phone + address enrichment.

Used as the PRIMARY provider for phone and address in the waterfall:
  PHONE:   Google Places → Apollo → Firecrawl
  ADDRESS: Google Places → Website → PDL

API reference:
  Text Search (New): https://developers.google.com/maps/documentation/places/web-service/text-search
  Place Details:     https://developers.google.com/maps/documentation/places/web-service/place-details

Environment:
  GOOGLE_MAPS_API_KEY  — from https://console.cloud.google.com/

Matching rules:
  - Google result name must be similar to company_name (word overlap ≥ 50%).
  - Location must match the expected city/country.
  - Phone: prefer +91 numbers for Indian companies.
  - Address: use formatted_address from Google (authoritative).
  - Do NOT accept a business in a different city or country.
  - Do NOT accept addresses containing "RERA", "plot", "survey no" patterns
    (these are property addresses, not office addresses).
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
_TEXT_SEARCH_URL    = "https://places.googleapis.com/v1/places:searchText"
_TIMEOUT            = 10

# ── Reject patterns for addresses ─────────────────────────────────────────────
_ADDRESS_REJECT_RE = re.compile(
    r'(?i)(rera\s*(?:no|number|reg|registration)?|'
    r'survey\s+no\.?|s\.no|plot\s+no\.?|khasra\s+no\.?|'
    r'village\s+\w+\s+tehsil|'
    r'adjacent\s+to|opposite\s+to|near\s+(?:the\s+)?)',
)

# ── Phone helpers ─────────────────────────────────────────────────────────────

def _is_indian_phone(phone: str) -> bool:
    """Return True only for unambiguously Indian phone numbers."""
    stripped = phone.strip()
    digits = re.sub(r"\D", "", stripped)
    if stripped.startswith("+91") and len(digits) == 12:
        return True
    if digits.startswith("1800") and len(digits) >= 11:
        return True
    if digits.startswith("0") and 10 <= len(digits) <= 12:
        return True
    # Mobile 10-digit: only if explicitly prefixed +91 or 0
    if len(digits) == 10 and digits[0] in "6789":
        if stripped.startswith("+91") or stripped.startswith("0"):
            return True
        if "91" in stripped and stripped.index("91") < 4:
            return True
        return False
    return False


def _is_foreign_phone(phone: str) -> bool:
    """Return True for numbers that are clearly non-Indian international numbers."""
    stripped = phone.strip()
    if stripped.startswith("+") and not stripped.startswith("+91"):
        return True
    digits = re.sub(r"\D", "", stripped)
    if digits.startswith("1") and len(digits) == 11 and not digits.startswith("1800"):
        return True
    if re.match(r"^\(\d{3}\)", stripped):
        return True
    return False


# ── Name matching ─────────────────────────────────────────────────────────────

def _name_matches(candidate: str, target: str, threshold: float = 0.5) -> bool:
    """
    Return True if candidate business name sufficiently matches target.
    Uses word-overlap similarity.
    """
    if not candidate or not target:
        return False
    cand_words   = set(re.sub(r'[^\w\s]', '', candidate.lower()).split())
    target_words = set(re.sub(r'[^\w\s]', '', target.lower()).split())
    # Remove very common words that add noise
    _STOP = {"the", "a", "an", "and", "of", "for", "in", "at", "on", "pvt", "ltd", "limited"}
    cand_words   -= _STOP
    target_words -= _STOP
    if not cand_words or not target_words:
        return False
    overlap = len(cand_words & target_words) / max(len(target_words), 1)
    return overlap >= threshold


def _location_matches(result_address: str, expected_city: str) -> bool:
    """Return True if the result address contains the expected city."""
    if not expected_city:
        return True  # Can't verify — accept
    return expected_city.lower() in result_address.lower()


# ── Shared async client ───────────────────────────────────────────────────────

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT),
            limits=httpx.Limits(max_connections=10),
            follow_redirects=True,
        )
    return _client


# ── Internal API wrapper ──────────────────────────────────────────────────────

async def _text_search(
    text_query: str,
    language_code: str = "en",
    max_results: int = 3,
) -> list[dict]:
    """
    POST /places:searchText  — Google Places Text Search (New).
    Returns list of place dicts with name, formattedAddress, nationalPhoneNumber,
    internationalPhoneNumber, websiteUri.
    """
    if not GOOGLE_MAPS_API_KEY:
        return []
    client = _get_client()
    try:
        resp = await client.post(
            _TEXT_SEARCH_URL,
            headers={
                "Content-Type":    "application/json",
                "X-Goog-Api-Key":  GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": (
                    "places.displayName,places.formattedAddress,"
                    "places.nationalPhoneNumber,places.internationalPhoneNumber,"
                    "places.websiteUri,places.id"
                ),
            },
            json={
                "textQuery":    text_query,
                "languageCode": language_code,
                "pageSize":     max_results,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("places") or []
    except Exception:
        return []


# ── Public entry points ───────────────────────────────────────────────────────

async def find_phone_and_address(
    company_name: str,
    city:         str = "Pune",
    state:        str = "",
    country:      str = "India",
    prefer_india: bool = True,
) -> tuple[Optional[str], Optional[str], str, str, str, str]:
    """
    Search Google Places for a business and return its phone + address.

    Returns:
        (phone, address, city_out, state_out, country_out, status)

    Tries two search queries:
      1. "{company_name}, {city}"
      2. "{company_name}, {city}, {state}" (if state provided)
    """
    if not GOOGLE_MAPS_API_KEY:
        return None, None, "", "", "", "skipped"

    # Build search queries
    queries = [f"{company_name}, {city}"]
    if state:
        queries.append(f"{company_name}, {city}, {state}")
    if country and country.lower() != "india":
        queries.append(f"{company_name}, {country}")

    for query in queries:
        places = await _text_search(query, max_results=3)

        for place in places:
            # Extract fields
            place_name    = (place.get("displayName") or {}).get("text", "")
            address       = (place.get("formattedAddress") or "").strip()
            intl_phone    = (place.get("internationalPhoneNumber") or "").strip()
            natl_phone    = (place.get("nationalPhoneNumber") or "").strip()
            website       = (place.get("websiteUri") or "").strip()

            # Skip if name doesn't match the target company
            if not _name_matches(place_name, company_name):
                continue

            # Skip if location doesn't match
            if not _location_matches(address, city):
                continue

            # Reject RERA/project addresses
            if _ADDRESS_REJECT_RE.search(address):
                continue

            # Choose best phone
            phone_out = None
            if prefer_india:
                # Try international +91 first, then national
                if intl_phone and _is_indian_phone(intl_phone):
                    phone_out = intl_phone
                elif natl_phone and _is_indian_phone(natl_phone):
                    phone_out = natl_phone
                elif intl_phone and not _is_foreign_phone(intl_phone):
                    phone_out = intl_phone
                # Skip if only foreign numbers found for Indian target
            else:
                phone_out = intl_phone or natl_phone or None

            # Parse city/state/country from formatted address
            addr_parts = [p.strip() for p in address.split(",")]
            city_out    = city
            state_out   = state
            country_out = country

            # Google formats: "Street, City, State Postal, Country"
            if len(addr_parts) >= 3:
                country_out = addr_parts[-1].strip()
                # Try to find city and state in the middle parts
                for part in reversed(addr_parts[1:-1]):
                    part = part.strip()
                    # Strip postal codes
                    part_clean = re.sub(r'\b\d{5,6}\b', '', part).strip()
                    if part_clean and not city_out:
                        city_out = part_clean
                    elif part_clean and not state_out:
                        state_out = part_clean

            status = "google_places_verified"
            if not phone_out:
                status = "google_places_address_only"

            return phone_out, address or None, city_out, state_out, country_out, status

    return None, None, "", "", "", "google_places_no_match"
