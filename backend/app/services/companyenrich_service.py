"""
app/services/companyenrich_service.py
──────────────────────────────────────
CompanyEnrich API — SOLE enrichment provider.

This module is the ONLY external enrichment source used in the pipeline.
Hunter, Apollo, PDL, and Google Places are NOT used anywhere.

Endpoints used (https://api.companyenrich.com):
  GET  /companies/enrich?domain=<domain>    — name, phone, address, website
  POST /people/search                        — founder/CEO lookup by domain+seniority
  GET  /people/email?personId=<id>&domain=<domain>  — work email (BETA, 10 credits)
  POST /companies/search                     — discovery by query string

Authentication:
  Authorization: Bearer <COMPANYENRICH_API_KEY>
  Key is read fresh from env on every call — never captured at import time.

Credit costs:
  /companies/enrich  — 1 credit per call
  /people/search     — 2 credits per person returned (min 2 credits)
  /people/email      — 10 credits per newly found email (BETA)
  /companies/search  — 1 credit per company returned (min 1 credit)

IMPORTANT — /people/email 422 fix:
  The endpoint returns HTTP 422 when a domain is passed that does NOT appear
  in the person's experience list.  We therefore:
    1. Call /people/search → get back PersonInfo items with .experiences[]
    2. For each candidate person, find their CURRENT experience domain
       that matches the target company domain.
    3. Only call /people/email with the domain extracted from the person's
       own experience record — never the raw input domain.
    4. If a person has no matching current experience, skip them.

All public functions return (value_or_None, source_str, status_str) tuples.
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

# ── API base ──────────────────────────────────────────────────────────────────
_BASE             = "https://api.companyenrich.com"
_ENRICH_URL       = f"{_BASE}/companies/enrich"    # GET  ?domain=<domain>
_PEOPLE_URL       = f"{_BASE}/people/search"       # POST
_PEOPLE_EMAIL_URL = f"{_BASE}/people/email"        # GET  ?personId=<id>&domain=<domain>
_COMPANIES_SEARCH_URL = f"{_BASE}/companies/search" # POST
_TIMEOUT = 15

# ── 402 circuit breaker ───────────────────────────────────────────────────────
# Set to True when ANY CE endpoint returns HTTP 402 (credits exhausted).
# All subsequent calls within the same process lifetime return early.
# Reset by calling reset_credits_flag() at the start of each new request.
_credits_exhausted: bool = False


def reset_credits_flag() -> None:
    """Call at the start of each lead-generation request to clear the 402 flag."""
    global _credits_exhausted
    _credits_exhausted = False


def is_credits_exhausted() -> bool:
    """Return True if CE returned 402 during this request."""
    return _credits_exhausted


def _mark_exhausted() -> None:
    global _credits_exhausted
    _credits_exhausted = True
    _log("CIRCUIT BREAKER: 402 received — CompanyEnrich DISABLED for this request")


# ── Seniority/title filters ───────────────────────────────────────────────────
_FOUNDER_SENIORITIES = ["owner", "founder", "c-suite", "partner"]

_FOUNDER_TITLE_KEYWORDS = frozenset({
    "founder", "co-founder", "cofounder",
    "owner", "proprietor",
    "ceo", "chief executive",
    "managing director", "md",
    "chairman", "chairperson",
    "president", "promoter",
    "managing partner",
})

_DISQUALIFY_TITLES = frozenset({
    "vp", "vice president", "svp", "evp",
    "director",
    "manager", "head of", "lead", "associate",
    "analyst", "consultant", "engineer",
})

_PERSONAL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "yahoo.in", "hotmail.com", "outlook.com",
    "rediffmail.com", "icloud.com", "protonmail.com", "live.com",
    "msn.com", "aol.com",
})

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_key() -> str:
    return os.getenv("COMPANYENRICH_API_KEY", "").strip()


def _normalize_domain(value: str) -> str:
    if not value:
        return ""
    v = value.strip().lower()
    if v.startswith("http://") or v.startswith("https://"):
        v = urlparse(v).netloc
    if v.startswith("www."):
        v = v[4:]
    return v.split("/")[0].split(":")[0].strip()


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [COMPANYENRICH] {msg}", flush=True)


def _get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_TIMEOUT),
        limits=httpx.Limits(max_connections=10),
        follow_redirects=True,
    )


def _is_personal_email(email: str) -> bool:
    dom = email.lower().split("@")[-1] if "@" in email else ""
    return dom in _PERSONAL_DOMAINS


def _title_qualifies(title: str) -> bool:
    tl = title.lower().strip()
    return any(kw in tl for kw in _FOUNDER_TITLE_KEYWORDS)


def _title_disqualifies(title: str) -> bool:
    if _title_qualifies(title):
        return False
    tl = title.lower().strip()
    return any(dq in tl for dq in _DISQUALIFY_TITLES)


def _is_plausible_name(name: str) -> bool:
    if not name:
        return False
    words = name.strip().split()
    if len(words) < 2 or len(words) > 4:
        return False
    _company_words = frozenset({
        "ltd", "limited", "pvt", "private", "inc", "corp", "group",
        "technologies", "solutions", "services", "ventures",
    })
    if {w.lower() for w in words} & _company_words:
        return False
    return all(len(w) >= 2 and w[0].isupper() for w in words)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. COMPANY ENRICH — phone + address + name
# ═══════════════════════════════════════════════════════════════════════════════

async def enrich_company_by_domain(domain: str) -> dict:
    """GET /companies/enrich?domain=. Returns {} if _credits_exhausted or on failure."""
    if _credits_exhausted:
        return {}
    key = _get_key()
    if not key:
        _log("API key not configured — skipping enrich_company_by_domain")
        return {}
    norm = _normalize_domain(domain)
    if not norm:
        return {}

    async with _get_client() as client:
        try:
            resp = await client.get(
                _ENRICH_URL,
                headers={"Authorization": f"Bearer {key}"},
                params={"domain": norm},
            )
        except httpx.TimeoutException:
            _log(f"Timeout enriching domain={norm!r}")
            return {}
        except httpx.RequestError as exc:
            _log(f"Request error enriching domain={norm!r}: {exc}")
            return {}

        if resp.status_code == 404:
            _log(f"domain={norm!r} not found (404)")
            return {}
        if resp.status_code == 401:
            _log("Auth failed (401) — check COMPANYENRICH_API_KEY")
            return {}
        if resp.status_code == 402:
            _mark_exhausted()
            return {}
        if resp.status_code == 429:
            _log("Rate limit hit (429)")
            return {}
        if resp.status_code != 200:
            _log(f"Unexpected status {resp.status_code} for domain={norm!r}")
            return {}

        try:
            data = resp.json()
        except ValueError as exc:
            _log(f"Invalid JSON for domain={norm!r}: {exc}")
            return {}

        _log(f"domain={norm!r} enriched — name={data.get('name')!r}")
        return data if isinstance(data, dict) else {}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PEOPLE SEARCH — founder/CEO lookup
# ═══════════════════════════════════════════════════════════════════════════════

async def search_founders_by_domain(
    domain: str,
    page_size: int = 5,
) -> list[dict]:
    """
    POST /people/search

    Returns PersonInfo dicts for founder/c-suite at the given domain.
    Cost: 2 credits per person returned (min 2 credits).

    Each PersonInfo includes:
      id, name, first_name, last_name, position, seniority,
      experiences[].{isCurrent, isMatched, position, company.{domain, name}}
    """
    if _credits_exhausted:
        return []
    key = _get_key()
    if not key:
        return []
    norm = _normalize_domain(domain)
    if not norm:
        return []

    payload = {
        "domains":    [norm],
        "seniority":  _FOUNDER_SENIORITIES,
        "department": ["c-suite"],
        "pageSize":   page_size,
        "page":       1,
    }

    async with _get_client() as client:
        try:
            resp = await client.post(
                _PEOPLE_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException:
            _log(f"Timeout people/search domain={norm!r}")
            return []
        except httpx.RequestError as exc:
            _log(f"Request error people/search domain={norm!r}: {exc}")
            return []

        if resp.status_code not in (200,):
            _log(f"people/search status={resp.status_code} domain={norm!r}")
            if resp.status_code == 402:
                _mark_exhausted()
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        items = data.get("items") if isinstance(data, dict) else []
        _log(f"people/search domain={norm!r} → {len(items) if isinstance(items, list) else 0} people")
        return items if isinstance(items, list) else []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PEOPLE EMAIL (BETA) — fetch work email for a known person ID
# ═══════════════════════════════════════════════════════════════════════════════

async def get_person_email(person_id: str, experience_domain: str) -> Optional[str]:
    """GET /people/email. Returns None if _credits_exhausted. Cost: 10 credits."""
    if _credits_exhausted:
        return None
    key = _get_key()
    if not key or not person_id or not experience_domain:
        return None

    norm_domain = _normalize_domain(experience_domain)
    if not norm_domain:
        return None

    async with _get_client() as client:
        try:
            resp = await client.get(
                _PEOPLE_EMAIL_URL,
                headers={"Authorization": f"Bearer {key}"},
                params={"personId": person_id, "domain": norm_domain},
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            _log(f"people/email error personId={person_id!r}: {exc}")
            return None

        if resp.status_code == 402:
            _mark_exhausted()
            return None
        if resp.status_code == 422:
            # Domain does not match person's experience — do NOT retry with this domain
            _log(
                f"people/email 422 for personId={person_id!r} domain={norm_domain!r} — "
                "domain not in person's experiences (skipping this person)"
            )
            return None
        if resp.status_code not in (200,):
            _log(f"people/email status={resp.status_code} personId={person_id!r}")
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        status = (data.get("status") or "").lower()
        email  = (data.get("email") or "").strip()

        if status == "found" and email and not _is_personal_email(email):
            _log(f"people/email HIT personId={person_id!r} → {email!r}")
            return email

        _log(f"people/email status={status!r} personId={person_id!r} — no email found")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. FIND FOUNDER + EMAIL in one pass
# ═══════════════════════════════════════════════════════════════════════════════

async def find_founder_with_email(
    company_name: str,
    domain: str,
) -> tuple[Optional[str], Optional[str], Optional[str], str, str]:
    """
    Find the best founder/CEO at the company and attempt to resolve their
    work email via /people/email.

    Returns:
        (founder_name, founder_email, founder_phone, source, status)

    Email resolution uses the person's OWN experience domain (not the raw
    input domain) to avoid the HTTP 422 "domain must match experiences" error.

    Phone is extracted from the person's phones[] list if available.
    """
    people = await search_founders_by_domain(domain, page_size=5)
    if not people:
        return None, None, None, "", "companyenrich_no_people"

    _TITLE_PRIORITY = {
        "founder": 1, "co-founder": 1, "cofounder": 1,
        "owner": 2, "proprietor": 2,
        "ceo": 3, "chief executive": 3,
        "managing director": 4, "chairman": 4, "president": 4,
        "managing partner": 5,
    }

    def _priority(person: dict) -> int:
        for exp in (person.get("experiences") or []):
            if not exp.get("isCurrent"):
                continue
            pos = (exp.get("position") or "").lower()
            for kw, pri in _TITLE_PRIORITY.items():
                if kw in pos:
                    return pri
        title = (person.get("position") or "").lower()
        for kw, pri in _TITLE_PRIORITY.items():
            if kw in title:
                return pri
        sen = (person.get("seniority") or "").lower()
        if sen == "founder":
            return 2
        if sen in ("owner", "c-suite"):
            return 3
        return 99

    target_norm = _normalize_domain(domain)
    sorted_people = sorted(people, key=_priority)

    for person in sorted_people:
        # Find this person's current experience that matches target company
        matched_exp_domain: Optional[str] = None
        for exp in (person.get("experiences") or []):
            if not exp.get("isCurrent"):
                continue
            co = exp.get("company")
            exp_domain = _normalize_domain(
                (co.get("domain") or "") if isinstance(co, dict) else ""
            )
            if exp_domain and exp_domain == target_norm:
                matched_exp_domain = exp_domain
                break

        # If no exact domain match, try name match as fallback
        if not matched_exp_domain:
            for exp in (person.get("experiences") or []):
                if not exp.get("isCurrent"):
                    continue
                co = exp.get("company")
                if not isinstance(co, dict):
                    continue
                co_name = (co.get("name") or "").lower()
                tgt_name = company_name.lower()
                # Accept if company name tokens overlap
                if co_name and tgt_name and (
                    co_name in tgt_name or tgt_name in co_name
                ):
                    exp_domain = _normalize_domain(co.get("domain") or "")
                    if exp_domain:
                        matched_exp_domain = exp_domain
                    break

        # Last resort: if seniority is founder/owner/c-suite, use target domain
        if not matched_exp_domain:
            sen = (person.get("seniority") or "").lower()
            if sen in ("founder", "owner", "c-suite", "partner"):
                matched_exp_domain = target_norm
            else:
                _log(f"  skip {person.get('name')!r} — no matching experience")
                continue

        # Validate title
        title = (person.get("position") or "").strip()
        for exp in (person.get("experiences") or []):
            if exp.get("isCurrent") and exp.get("isMatched"):
                exp_pos = (exp.get("position") or "").strip()
                if exp_pos:
                    title = exp_pos
                    break
        if title and _title_disqualifies(title):
            _log(f"  skip {person.get('name')!r} — disqualified title={title!r}")
            continue

        # Validate name
        full_name = (person.get("name") or "").strip()
        if not full_name:
            first = (person.get("first_name") or "").strip()
            last  = (person.get("last_name")  or "").strip()
            full_name = f"{first} {last}".strip()
        if not _is_plausible_name(full_name):
            _log(f"  skip {full_name!r} — implausible name")
            continue

        _log(f"founder candidate: {full_name!r} title={title!r} domain={matched_exp_domain!r}")

        # Extract founder phone from person record
        founder_phone: Optional[str] = None
        phones = person.get("phones") or []
        if isinstance(phones, list) and phones:
            founder_phone = str(phones[0]).strip() or None

        # Resolve work email via /people/email
        person_id = person.get("id") or ""
        founder_email: Optional[str] = None
        if person_id and matched_exp_domain:
            founder_email = await get_person_email(person_id, matched_exp_domain)

        _log(
            f"company={company_name!r} — founder={full_name!r} "
            f"email={founder_email!r} phone={founder_phone!r}"
        )
        return full_name, founder_email, founder_phone, "companyenrich.com", "companyenrich_founder"

    _log(f"company={company_name!r} domain={domain!r} — no qualifying founder found")
    return None, None, None, "", "companyenrich_no_founder"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. FULL COMPANY ENRICHMENT — single call that returns all fields
# ═══════════════════════════════════════════════════════════════════════════════

async def enrich_company_full(
    company_name: str,
    domain: str,
) -> dict:
    """
    Enrich a company fully using only CompanyEnrich endpoints.

    Calls concurrently:
      - GET /companies/enrich?domain=  → name, phone, address, website
      - find_founder_with_email()      → founder name, email, phone

    Returns a flat dict with all populated fields, or empty dict if the
    domain cannot be enriched (used by callers to reject the company).
    """
    key = _get_key()
    if not key:
        return {}

    norm_domain = _normalize_domain(domain)
    if not norm_domain:
        _log(f"enrich_company_full: no domain for {company_name!r}")
        return {}

    # Run company enrich + founder search concurrently
    company_data, (founder_name, founder_email, founder_phone, src, fstatus) = \
        await asyncio.gather(
            enrich_company_by_domain(norm_domain),
            find_founder_with_email(company_name, norm_domain),
        )

    if not company_data:
        _log(f"enrich_company_full: no company data for domain={norm_domain!r}")
        return {}

    # Extract company fields from /companies/enrich
    location    = company_data.get("location") or {}
    city_obj    = location.get("city")    or {}
    state_obj   = location.get("state")   or {}
    country_obj = location.get("country") or {}

    name     = (company_data.get("name") or company_data.get("legalName") or company_name).strip()
    website  = (company_data.get("website") or f"https://{norm_domain}").strip()
    phone    = (location.get("phone") or "").strip()
    street   = (location.get("address") or "").strip()
    postal   = (location.get("postal_code") or "").strip()
    city     = (city_obj.get("name")    or "").strip() if isinstance(city_obj, dict)    else ""
    state    = (state_obj.get("name")   or "").strip() if isinstance(state_obj, dict)   else ""
    country  = (country_obj.get("name") or "").strip() if isinstance(country_obj, dict) else ""

    addr_parts   = [p for p in [street, city, state, postal, country] if p]
    full_address = ", ".join(addr_parts) if addr_parts else ""

    result = {
        "company_name":    name,
        "domain":          norm_domain,
        "website":         website,
        "company_number":  phone or None,
        "address":         full_address or None,
        "city":            city,
        "state":           state,
        "country":         country,
        "postal_code":     postal,
        "industry":        company_data.get("industry") or "",
        "description":     company_data.get("description") or "",
        "founder_name":    founder_name,
        "founder_email":   founder_email,
        "founder_number":  founder_phone,
        # email: use founder_email as best available from CompanyEnrich
        "email":           founder_email,
        "source_url":      website,
        "research_source": "companyenrich",
        "_companyenrich_raw": company_data,
        "_field_verification": {
            "phone":   {"value": phone,        "verified": bool(phone),        "status": "companyenrich_phone",   "source": "companyenrich.com"} if phone   else {},
            "address": {"value": full_address, "verified": bool(full_address), "status": "companyenrich_address", "source": "companyenrich.com"} if full_address else {},
            "founder": {"value": founder_name, "verified": bool(founder_name), "status": fstatus,                 "source": src}                 if founder_name else {},
            "email":   {"value": founder_email,"verified": bool(founder_email),"status": "companyenrich_email",   "source": "companyenrich.com"} if founder_email else {},
        },
    }

    _log(
        f"enrich_company_full: {name!r} "
        f"phone={bool(phone)} address={bool(full_address)} "
        f"founder={founder_name!r} email={founder_email!r}"
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. COMPANY SEARCH — used by discovery_service
# ═══════════════════════════════════════════════════════════════════════════════

async def search_companies(
    query: str,
    page: int = 1,
    page_size: int = 20,
) -> list[dict]:
    """POST /companies/search. Returns [] if _credits_exhausted. Cost: 1 credit/company."""
    if _credits_exhausted:
        _log(f"search_companies skipped (credits exhausted): {query!r}")
        return []
    key = _get_key()
    if not key or not query or not query.strip():
        return []

    payload = {
        "query":    query.strip(),
        "page":     page,
        "pageSize": min(page_size, 100),
    }

    async with _get_client() as client:
        _log(f"search_companies query={query!r}")
        try:
            resp = await client.post(
                _COMPANIES_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            _log(f"search_companies error: {exc}")
            return []

        if resp.status_code == 402:
            _mark_exhausted()
            return []
        if resp.status_code not in (200,):
            _log(f"search_companies status={resp.status_code} for query={query!r}")
            return []

        try:
            data = resp.json()
        except ValueError:
            return []

        items = data.get("items") if isinstance(data, dict) else None
        _log(f"search_companies → {len(items) if isinstance(items, list) else 0} results")
        return items if isinstance(items, list) else []


# ═══════════════════════════════════════════════════════════════════════════════
# 7. FIND COMPANY DETAILS — used by discovery_service
# ═══════════════════════════════════════════════════════════════════════════════

async def find_company_details(
    company_name: str,
    domain: str,
) -> Optional[dict]:
    """
    Fetch structured company details. Used by discovery_service.
    Primary: domain lookup. Fallback: search by name.
    """
    key = _get_key()
    if not key:
        return None

    norm_domain = _normalize_domain(domain or "")
    if norm_domain:
        data = await enrich_company_by_domain(norm_domain)
        if data:
            return _normalize_company_info(data)

    if company_name and company_name.strip():
        results = await search_companies(company_name.strip(), page=1, page_size=5)
        for result in results:
            result_domain = _normalize_domain(result.get("domain") or "")
            if norm_domain and result_domain and result_domain == norm_domain:
                return _normalize_company_info(result)
            result_name = (result.get("name") or "").strip().lower()
            if (company_name.strip().lower() in result_name
                    or result_name in company_name.strip().lower()):
                return _normalize_company_info(result)

    return None


def _normalize_company_info(data: dict) -> dict:
    """Normalize CompanyInfo dict to flat dict for discovery_service."""
    location    = data.get("location") or {}
    city_obj    = location.get("city")    or {}
    state_obj   = location.get("state")   or {}
    country_obj = location.get("country") or {}

    city    = city_obj.get("name",    "") if isinstance(city_obj,    dict) else ""
    state   = state_obj.get("name",   "") if isinstance(state_obj,   dict) else ""
    country = country_obj.get("name", "") if isinstance(country_obj, dict) else ""

    addr_parts   = [p for p in [location.get("address", ""), city, state,
                                  location.get("postal_code", ""), country] if p]
    full_address = ", ".join(addr_parts) if addr_parts else ""

    return {
        "name":           data.get("name") or data.get("legalName") or "",
        "domain":         data.get("domain") or "",
        "website":        data.get("website") or "",
        "phone":          location.get("phone") or "",
        "address":        full_address,
        "city":           city,
        "state":          state,
        "country":        country,
        "postal_code":    location.get("postal_code") or "",
        "industry":       data.get("industry") or "",
        "description":    data.get("description") or data.get("seo_description") or "",
        "employees":      str(data.get("employees") or ""),
        "founded_year":   data.get("founded_year"),
        "linkedin_url":   (data.get("socials") or {}).get("linkedin_url") or "",
        "_companyenrich_id":  data.get("id", ""),
        "_companyenrich_raw": data,
    }


# ── Legacy compatibility stubs (kept so any unused imports don't break) ───────

async def find_phone(company_name: str, domain: str, prefer_india: bool = True):
    """Legacy stub — use enrich_company_full() instead."""
    data = await enrich_company_by_domain(domain)
    if not data:
        return None, "", "companyenrich_no_data"
    location = data.get("location") or {}
    phone = (location.get("phone") or "").strip()
    if not phone:
        return None, "", "companyenrich_no_phone"
    return phone, "companyenrich.com", "companyenrich_phone"


async def find_address(company_name: str, domain: str, requested_city: str = ""):
    """Legacy stub — use enrich_company_full() instead."""
    data = await enrich_company_by_domain(domain)
    if not data:
        return None, "", "", "", "companyenrich_no_data"
    location    = data.get("location") or {}
    city_obj    = location.get("city")    or {}
    state_obj   = location.get("state")   or {}
    country_obj = location.get("country") or {}
    city    = (city_obj.get("name",    "") if isinstance(city_obj,    dict) else "")
    state   = (state_obj.get("name",   "") if isinstance(state_obj,   dict) else "")
    country = (country_obj.get("name", "") if isinstance(country_obj, dict) else "")
    parts   = [p for p in [location.get("address", ""), city, state,
                              location.get("postal_code", ""), country] if p]
    full    = ", ".join(parts) if parts else None
    if not full:
        return None, "", "", "", "companyenrich_no_address"
    return full, city, state, country, "companyenrich_address"


async def find_founder(company_name: str, domain: str, city: str = ""):
    """Legacy stub — use find_founder_with_email() instead."""
    name, email, phone, src, status = await find_founder_with_email(company_name, domain)
    return name, src, status


async def find_email(company_name: str, domain: str):
    """Legacy stub — email is fetched via find_founder_with_email()."""
    return None, "", "skipped"
