"""
app/services/apollo_service.py
────────────────────────────────
Apollo.io company + founder enrichment.

Used as a SECONDARY provider in the waterfall:
  EMAIL:   Hunter → Apollo → Firecrawl/Serper
  FOUNDER: PDL    → Apollo → Website
  PHONE:   Google Places → Apollo → Firecrawl

Apollo free tier ONLY has these endpoints:
  - GET  /api/v1/auth/health               ✓ (connectivity check)
  - POST /api/v1/organizations/search      ✓ (returns phone, city, country, website)
  - POST /api/v1/mixed_people/search       ✗ 403 paid only
  - POST /api/v1/organizations/enrich      ✗ 403 paid only
  - POST /v1/contacts/search               ✗ 403 paid only

So we use ONLY organizations/search for:
  - Company phone
  - Company city/country verification
  - Founder search via q_organization_name + title filter (if available)

Strict rules:
  - PHONE:   prefer +91 for India/Pune; reject foreign numbers for Indian targets
  - EMAIL:   Apollo free tier does not return company email reliably — skip
  - FOUNDER: organizations/search does not return people — skip Apollo founder
  - Never fabricate data; return None if nothing found
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

_BASE    = "https://api.apollo.io"
_TIMEOUT = 10

# Personal email domains — reject
_PERSONAL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "yahoo.com", "yahoo.in", "hotmail.com",
    "outlook.com", "rediffmail.com", "icloud.com", "protonmail.com",
    "live.com", "msn.com", "aol.com",
})


def _get_key() -> str:
    """Read key fresh from env each call (supports runtime reload)."""
    return os.getenv("APOLLO_API_KEY", "").strip()


def _get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_TIMEOUT),
        limits=httpx.Limits(max_connections=10),
        follow_redirects=True,
    )


# ── Phone helpers ─────────────────────────────────────────────────────────────

def _is_indian_phone(phone: str) -> bool:
    stripped = phone.strip()
    digits = re.sub(r"\D", "", stripped)
    if stripped.startswith("+91") and len(digits) == 12:
        return True
    if digits.startswith("1800") and len(digits) >= 11:
        return True
    if digits.startswith("0") and 10 <= len(digits) <= 12:
        return True
    if len(digits) == 10 and digits[0] in "6789":
        if stripped.startswith("+91") or stripped.startswith("0"):
            return True
        if "91" in stripped and stripped.index("91") < 4:
            return True
        return False
    return False


def _is_foreign_phone(phone: str) -> bool:
    stripped = phone.strip()
    if stripped.startswith("+") and not stripped.startswith("+91"):
        return True
    digits = re.sub(r"\D", "", stripped)
    if digits.startswith("1") and len(digits) == 11 and not digits.startswith("1800"):
        return True
    if re.match(r"^\(\d{3}\)", stripped):
        return True
    return False


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [APOLLO] {msg}", flush=True)


# ── Internal: organizations/search (free tier) ────────────────────────────────

async def _org_search(company_name: str, domain: str = "") -> list[dict]:
    """
    POST /api/v1/organizations/search — free tier, returns phone/city/country.
    Searches by company name; domain used for result matching only.
    """
    key = _get_key()
    if not key:
        return []

    async with _get_client() as client:
        try:
            resp = await client.post(
                f"{_BASE}/api/v1/organizations/search",
                headers={
                    "X-Api-Key": key,
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
                json={"q_organization_name": company_name, "per_page": 5},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 401:
                _log(f"AUTH FAILED 401 — check APOLLO_API_KEY")
                return []
            if resp.status_code == 403:
                _log(f"403 endpoint not in plan: organizations/search")
                return []
            if resp.status_code == 429:
                _log(f"Rate limit hit — backing off")
                return []
            resp.raise_for_status()
            return resp.json().get("organizations") or []
        except httpx.TimeoutException:
            _log(f"Timeout searching {company_name!r}")
            return []
        except Exception as exc:
            _log(f"Error searching {company_name!r}: {exc}")
            return []


def _org_matches(org: dict, company_name: str, domain: str) -> bool:
    """
    Return True if Apollo org record is the same company as target.
    Checks domain (preferred) then name similarity.
    """
    # Domain match
    primary = (org.get("primary_domain") or "").lower().strip()
    website = (org.get("website_url") or "").lower().strip()
    website = website.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")

    if domain:
        dom_clean = domain.lower().replace("www.", "")
        if primary == dom_clean or primary.endswith("." + dom_clean):
            return True
        if website == dom_clean or website.endswith("." + dom_clean):
            return True

    # Name similarity — at least 60% word overlap
    co_words  = set(company_name.lower().split())
    org_words = set((org.get("name") or "").lower().split())
    # Remove noise words
    _noise = {"pvt", "ltd", "limited", "inc", "corp", "the", "a", "an"}
    co_words  -= _noise
    org_words -= _noise
    if co_words and org_words:
        overlap = len(co_words & org_words) / max(len(co_words), 1)
        if overlap >= 0.6:
            return True

    return False


# ── Public entry points ───────────────────────────────────────────────────────

async def find_phone(
    company_name: str,
    domain: str,
    prefer_india: bool = True,
) -> tuple[Optional[str], str, str]:
    """
    Find company phone via Apollo organizations/search (free tier).
    Returns (phone, source, status).
    """
    key = _get_key()
    if not key:
        return None, "", "skipped"

    orgs = await _org_search(company_name, domain)
    if not orgs:
        _log(f"company={company_name!r} — no orgs returned")
        return None, "", "apollo_no_data"

    source = "apollo.io"

    for org in orgs:
        if not _org_matches(org, company_name, domain):
            continue

        phone = (org.get("phone") or "").strip()
        if not phone:
            continue

        city    = (org.get("city")    or "").lower()
        country = (org.get("country") or "").lower()

        # For India companies, reject foreign phones
        if prefer_india and _is_foreign_phone(phone):
            _log(f"company={company_name!r} rejected foreign phone {phone!r}")
            continue

        if prefer_india and _is_indian_phone(phone):
            _log(f"company={company_name!r} domain={domain} status=HIT phone={phone!r}")
            return phone, source, "apollo_phone_indian"

        if not prefer_india:
            _log(f"company={company_name!r} domain={domain} status=HIT phone={phone!r}")
            return phone, source, "apollo_phone_present"

        # Last resort: non-Indian phone for India company — only if country matches
        if "india" in country or "pune" in city:
            _log(f"company={company_name!r} domain={domain} status=HIT phone={phone!r} (india-context)")
            return phone, source, "apollo_phone_india_context"

    _log(f"company={company_name!r} domain={domain} status=NO_HIT")
    return None, "", "apollo_no_phone"


async def find_email(
    company_name: str,
    domain: str,
) -> tuple[Optional[str], str, str]:
    """
    Apollo free tier does not reliably return company emails.
    Returns (None, '', 'skipped') always — caller falls through to next provider.
    """
    # Apollo free-tier organizations/search does not return email addresses
    # The organizations/enrich endpoint (which has email) requires paid plan (403)
    return None, "", "skipped"


async def find_founder(
    company_name: str,
    domain: str,
    city: str = "",
) -> tuple[Optional[str], str, str]:
    """
    Apollo free tier does not support people search (mixed_people/search is 403).
    Returns (None, '', 'skipped') always — caller falls through to PDL.
    """
    # mixed_people/search requires paid plan — always 403 on free tier
    return None, "", "skipped"
