"""
app/services/pdl_service.py
────────────────────────────
People Data Labs (PDL) — company + person enrichment.

Waterfall roles:
  FOUNDER  (primary): PDL → Apollo → Website
  ADDRESS  (fallback): Google Places → Firecrawl → PDL

API docs: https://docs.peopledatalabs.com/docs/overview

Confirmed working PDL query patterns (from live API tests):
  /company/enrich   — works, returns location with city/region/country/postal
  /person/search    — only works with job_title_levels (enum) filter
                      NOT with match/should queries on job_title text field

Founder search uses job_title_levels:
  "owner"   → proprietor / sole owner
  "c_suite" → CEO, CTO, CFO, COO, etc.
  "partner" → managing partner, founder-partner
  "founder" → explicit founder title (PDL enum value)
  "director" → board-level (higher threshold required)

Then filters Python-side by actual title text to reject generic directors/VPs.

Location validation for PDL address:
  When requested city is Pune, reject any address whose country is not India.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

_BASE    = "https://api.peopledatalabs.com/v5"
_TIMEOUT = 12

# ── Founder title qualification (Python-side after PDL level filter) ──────────

# Titles that qualify as founder/leader
_QUALIFY_TITLES: tuple[str, ...] = (
    "founder",
    "co-founder", "cofounder", "co founder",
    "owner", "proprietor",
    "ceo", "chief executive",
    "managing director", " md ",
    "chairman", "chairperson",
    "president",
    "promoter",
    "managing partner",
)

# Standalone titles that do NOT qualify (unless combined with a qualifier above)
_DISQUALIFY_ALONE: frozenset[str] = frozenset({
    "director", "independent director", "non-executive director",
    "vice president", "vp", "svp", "evp",
    "manager", "head", "lead", "associate",
    "analyst", "consultant", "engineer",
    "officer",   # bare "officer" is too generic
})

# PDL job_title_levels enum values that can indicate leadership
# These are the ONLY levels that work as PDL filter values
_LEADER_LEVELS: list[str] = ["owner", "c_suite", "partner", "founder"]


def _qualifies_as_founder(title: str) -> bool:
    if not title:
        return False
    tl = title.lower().strip()
    return any(qt in tl for qt in _QUALIFY_TITLES)


def _disqualifies_as_founder(title: str) -> bool:
    if not title:
        return True
    tl = title.lower().strip()
    if _qualifies_as_founder(title):
        return False
    return any(dq in tl for dq in _DISQUALIFY_ALONE)


# ── Location validation ────────────────────────────────────────────────────────

# Pune area sub-locations that count as Pune presence
_PUNE_LOCALITIES: frozenset[str] = frozenset({
    "pune", "pimpri", "chinchwad", "pcmc", "hinjewadi", "kharadi",
    "magarpatta", "viman nagar", "baner", "wakad", "kothrud", "hadapsar",
    "yerwada", "aundh", "koregaon", "kalyani nagar", "wanowrie",
    "kondhwa", "nibm", "warje", "katraj", "wagholi", "undri",
    "deccan", "shivajinagar", "camp", "peth",
})


def _location_is_valid_for_city(city_out: str, state_out: str, country_out: str,
                                  requested_city: str) -> bool:
    """
    Return True if PDL location is compatible with the requested city.
    For Pune queries: country must be India; city/state must match.
    For non-specific queries: accept anything.
    """
    if not requested_city:
        return True

    req = requested_city.lower().strip()

    # Must be India for Pune queries
    if req in ("pune", "pimpri", "pimpri-chinchwad"):
        if country_out and country_out.lower() not in ("india", "in"):
            return False
        # Check if city or state mentions pune area
        combined = f"{city_out} {state_out}".lower()
        if any(loc in combined for loc in _PUNE_LOCALITIES):
            return True
        if "maharashtra" in combined:
            return True
        # If city is blank but country is India, accept (company is Indian)
        if not city_out and country_out.lower() in ("india", "in"):
            return True
        return False

    return True


# ── Company matching ──────────────────────────────────────────────────────────

def _company_matches(person: dict, company_name: str, domain: str) -> bool:
    """Return True if PDL person's current employer is the target company."""
    cur_company = (person.get("job_company_name") or "").lower().strip()
    cur_website = (person.get("job_company_website") or "").lower().strip()
    cur_website = cur_website.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")

    # Domain match (authoritative)
    if domain and cur_website:
        dom_clean = domain.lower().replace("www.", "")
        if cur_website == dom_clean or cur_website.endswith("." + dom_clean):
            return True

    # Name similarity (word overlap ≥ 55%)
    if cur_company and company_name:
        co_words = set(company_name.lower().split())
        cu_words = set(cur_company.split())
        _noise = {"pvt", "ltd", "limited", "inc", "corp", "the", "group"}
        co_words -= _noise
        cu_words -= _noise
        if co_words and cu_words:
            overlap = len(co_words & cu_words) / max(len(co_words), 1)
            if overlap >= 0.55:
                return True

    return False


def _log(tag: str, msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


def _get_key() -> str:
    return os.getenv("PDL_API_KEY", "").strip()


def _get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_TIMEOUT),
        limits=httpx.Limits(max_connections=10),
        follow_redirects=True,
    )


# ── Person search using job_title_levels (the only working PDL filter) ────────

async def _person_search_by_levels(
    company_name: str,
    domain: str,
    levels: list[str],
    size: int = 10,
) -> list[dict]:
    """
    POST /person/search using job_title_levels enum filter.
    This is the ONLY query format that works reliably for PDL person search.
    Returns list of PDL person dicts.
    """
    key = _get_key()
    if not key:
        return []

    must_clauses: list[dict] = []

    # Company constraint: prefer domain (more precise)
    if domain:
        must_clauses.append({"term": {"job_company_website": domain}})
    elif company_name:
        must_clauses.append({"match": {"job_company_name": company_name}})
    else:
        return []

    # Level filter
    if levels:
        must_clauses.append({"terms": {"job_title_levels": levels}})

    query = {"bool": {"must": must_clauses}}

    async with _get_client() as client:
        try:
            resp = await client.post(
                f"{_BASE}/person/search",
                headers={"X-Api-Key": key},
                json={"query": query, "size": size, "pretty": False},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 404:
                return []
            if resp.status_code == 400:
                _log("PDL", f"Query error 400: {resp.text[:200]}")
                return []
            if resp.status_code in (401, 402, 403):
                _log("PDL", f"Auth/quota error {resp.status_code}")
                return []
            resp.raise_for_status()
            return resp.json().get("data") or []
        except httpx.TimeoutException:
            _log("PDL", f"Timeout searching {company_name!r}")
            return []
        except Exception as exc:
            _log("PDL", f"Error searching {company_name!r}: {exc}")
            return []


async def _company_enrich(domain: str) -> dict:
    """GET /company/enrich?website=<domain> — returns company location, etc."""
    key = _get_key()
    if not key or not domain:
        return {}
    async with _get_client() as client:
        try:
            resp = await client.get(
                f"{_BASE}/company/enrich",
                headers={"X-Api-Key": key},
                params={"website": domain},
                timeout=_TIMEOUT,
            )
            if resp.status_code in (404, 402):
                return {}
            resp.raise_for_status()
            return resp.json() or {}
        except Exception:
            return {}


# ── Public entry points ───────────────────────────────────────────────────────

async def find_founder(
    company_name: str,
    domain: str,
    city: str = "",
) -> tuple[Optional[str], str, str]:
    """
    Find the founder/CEO/owner of a company via PDL person search.

    Uses job_title_levels filter (the only working PDL query format).
    Then Python-side filters by actual title text to reject generic roles.

    Returns (founder_name, source, verification_status).
    """
    key = _get_key()
    if not key:
        return None, "", "skipped"

    source = "people-data-labs.com"

    # Search with leadership-level filter — one call gets all candidates
    people = await _person_search_by_levels(
        company_name, domain,
        levels=_LEADER_LEVELS,
        size=10,
    )

    _log("PDL", f"company={company_name!r} domain={domain} person_search found={len(people)}")

    # Priority order: founder > owner > c_suite > partner
    TITLE_PRIORITY = {
        "founder": 1, "co-founder": 1, "cofounder": 1,
        "owner": 2, "proprietor": 2,
        "ceo": 3, "chief executive": 3,
        "managing director": 4, "chairman": 4, "president": 4,
        "managing partner": 5,
    }

    def _priority(person: dict) -> int:
        t = (person.get("job_title") or "").lower()
        for kw, pri in TITLE_PRIORITY.items():
            if kw in t:
                return pri
        return 99

    # Sort by priority
    people_sorted = sorted(people, key=_priority)

    for person in people_sorted:
        # Must work at target company
        if not _company_matches(person, company_name, domain):
            _log("PDL", f"  skip {person.get('first_name')} {person.get('last_name')} — company mismatch "
                        f"(co={person.get('job_company_website')})")
            continue

        title = (person.get("job_title") or "").strip()

        if not _qualifies_as_founder(title):
            _log("PDL", f"  skip {person.get('first_name')} {person.get('last_name')} — title not qualifying: {title!r}")
            continue
        if _disqualifies_as_founder(title):
            _log("PDL", f"  skip {person.get('first_name')} {person.get('last_name')} — disqualified: {title!r}")
            continue

        first = (person.get("first_name") or "").strip()
        last  = (person.get("last_name")  or "").strip()
        full  = f"{first} {last}".strip() if (first or last) else (person.get("full_name") or "").strip()

        if len(full.split()) < 2:
            continue

        # Reject names that look like company names
        full_lower = full.lower()
        if any(w in full_lower for w in ("ltd", "limited", "pvt", "inc", "corp", "group",
                                          "realty", "builders", "developers", "technologies",
                                          "solutions", "services")):
            continue

        _log("PDL", f"  HIT: {full!r} | title={title!r} | levels={person.get('job_title_levels')}")
        return full, source, "pdl_verified"

    _log("PDL", f"company={company_name!r} — no qualifying founder found")
    return None, "", "pdl_not_found"


async def find_company_address(
    domain: str,
    company_name: str = "",
    requested_city: str = "",
) -> tuple[Optional[str], str, str, str, str]:
    """
    Enrich company address via PDL company/enrich.

    For Pune queries: rejects any address not in India.
    Returns (full_address, city, state, country, status).
    """
    key = _get_key()
    if not key:
        return None, "", "", "", "skipped"

    org = await _company_enrich(domain)
    if not org:
        _log("PDL", f"company_enrich domain={domain} — no data")
        return None, "", "", "", "pdl_no_data"

    hq = org.get("location") or org.get("headquarters") or {}
    if isinstance(hq, str):
        # PDL returned a string address — parse it
        return hq, "", "", "", "pdl_address_string"

    city_out    = (hq.get("locality") or hq.get("metro") or "").strip()
    state_out   = (hq.get("region") or "").strip()
    country_out = (hq.get("country") or "").strip()
    postal      = (hq.get("postal_code") or "").strip()
    street      = (hq.get("street_address") or "").strip()

    # Location validation — don't accept wrong-country addresses for Pune queries
    if not _location_is_valid_for_city(city_out, state_out, country_out, requested_city):
        _log("PDL", f"company_enrich domain={domain} — location rejected: "
                    f"{city_out},{state_out},{country_out} (requested: {requested_city})")
        return None, "", "", "", "pdl_location_mismatch"

    parts = [p for p in [street, city_out, state_out, postal, country_out] if p]
    full_address = ", ".join(parts) if parts else None

    if not full_address:
        return None, "", "", "", "pdl_empty_address"

    _log("PDL", f"company_enrich domain={domain} — address: {full_address[:60]}")
    return full_address, city_out, state_out, country_out, "pdl_address_verified"
