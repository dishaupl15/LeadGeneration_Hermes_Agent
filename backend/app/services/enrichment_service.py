"""
app/services/enrichment_service.py
────────────────────────────────────
Multi-source waterfall enrichment engine.

Called AFTER discovery (Serper + Firecrawl + verify_service).

Waterfall order:
  EMAIL   : Hunter → Apollo(skipped-free) → keep Firecrawl value
  FOUNDER : PDL → Apollo(skipped-free) → keep Firecrawl value
  PHONE   : Google Places(if key) → Apollo → keep Firecrawl value
  ADDRESS : Google Places(if key) → PDL → keep Firecrawl value

Provider status (from live diagnostic):
  Hunter       : key present but MAY be invalid — validate on first use
  Apollo       : key present; organizations/search works (phone only)
  PDL          : key present; company/enrich + person/search(levels) work
  Google Places: key MISSING — always skipped

Key fix: provider keys read FRESH from env on every enrichment run
         (not captured at module import time).
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from app.services import hunter_service        as _hunter
from app.services import apollo_service        as _apollo
from app.services import pdl_service           as _pdl
from app.services import google_places_service as _gplaces
from app.services.verify_service import _is_plausible_person_name

# ── Configuration ─────────────────────────────────────────────────────────────
_ENRICH_SEM_SIZE  = 5      # max companies enriched simultaneously
_COMPANY_TIMEOUT  = 14.0   # max seconds per company enrichment
_CACHE_TTL        = 3600   # 1-hour domain cache TTL

# ── Domain-level TTL cache ────────────────────────────────────────────────────
_DOMAIN_CACHE: dict[str, dict] = {}


def _cache_get(domain: str) -> Optional[dict]:
    if not domain:
        return None
    entry = _DOMAIN_CACHE.get(domain)
    if not entry:
        return None
    if time.monotonic() - entry.get("_cached_at", 0) > _CACHE_TTL:
        del _DOMAIN_CACHE[domain]
        return None
    return entry


def _cache_set(domain: str, data: dict) -> None:
    if not domain:
        return
    _DOMAIN_CACHE[domain] = {**data, "_cached_at": time.monotonic()}


# ── Stats (reset per pipeline run) ────────────────────────────────────────────
class _EnrichStats:
    def __init__(self):
        self.hunter_calls = self.apollo_calls = self.pdl_calls = self.google_places_calls = 0
        self.hunter_hits  = self.apollo_hits  = self.pdl_hits  = self.google_places_hits  = 0
        self.cache_hits   = 0

_stats = _EnrichStats()


def reset_stats() -> None:
    global _stats
    _stats = _EnrichStats()


def get_stats() -> dict:
    return {
        "hunter_calls": _stats.hunter_calls,        "hunter_hits": _stats.hunter_hits,
        "apollo_calls": _stats.apollo_calls,         "apollo_hits": _stats.apollo_hits,
        "pdl_calls":    _stats.pdl_calls,            "pdl_hits":    _stats.pdl_hits,
        "google_places_calls": _stats.google_places_calls,
        "google_places_hits":  _stats.google_places_hits,
        "cache_hits":   _stats.cache_hits,
    }


def _log(tag: str, msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


# ── Provider key helpers (fresh read each time) ───────────────────────────────

def _hunter_key()  -> str: return os.getenv("HUNTER_API_KEY",     "").strip()
def _apollo_key()  -> str: return os.getenv("APOLLO_API_KEY",      "").strip()
def _pdl_key()     -> str: return os.getenv("PDL_API_KEY",         "").strip()
def _gplaces_key() -> str: return os.getenv("GOOGLE_MAPS_API_KEY", "").strip()


def _provider_status() -> dict:
    """Return dict of provider enabled/disabled status."""
    return {
        "Hunter":        bool(_hunter_key()),
        "Apollo":        bool(_apollo_key()),
        "PDL":           bool(_pdl_key()),
        "Google Places": bool(_gplaces_key()),
    }


# ── Field-already-verified checks ─────────────────────────────────────────────

def _email_verified(company: dict) -> bool:
    """
    Return True only if email was verified by an external provider or
    explicitly confirmed domain-match. An email that was merely found
    by Firecrawl but not yet verified is NOT considered verified here
    — we should still try Hunter/Apollo to get a better-verified value.
    """
    fv = company.get("_field_verification") or {}
    e  = fv.get("email") or {}
    st = e.get("status", "")
    # Only skip if already enriched by an external provider
    external_verified_statuses = {
        "hunter_valid", "hunter_accept_all", "hunter_domain_match",
        "apollo_org_email", "cache_verified",
        "found_gap",   # from verify_service gap search — accepted
    }
    if bool(company.get("email")) and st in external_verified_statuses:
        return True
    # "verified_domain" from verify_service is also strong
    if bool(company.get("email")) and st == "verified_domain":
        return True
    return False


def _phone_verified(company: dict) -> bool:
    fv = company.get("_field_verification") or {}
    st = (fv.get("phone") or {}).get("status", "")
    return bool(company.get("company_number")) and st not in (
        "", "not_found", "rejected_foreign_for_india_domain",
        "not_publicly_found", "verified_present",
    )


def _address_verified(company: dict) -> bool:
    fv = company.get("_field_verification") or {}
    st = (fv.get("address") or {}).get("status", "")
    return bool(company.get("address")) and st not in (
        "", "not_found", "rejected_paragraph", "rejected_no_location",
    )


def _founder_verified(company: dict) -> bool:
    fv = company.get("_field_verification") or {}
    st = (fv.get("founder") or {}).get("status", "")
    return bool(company.get("founder_name")) and st not in (
        "", "null_input", "rejected", "rejected_invalid_name",
    )


def _is_india(company: dict) -> bool:
    domain  = (company.get("domain") or "").lower()
    country = (company.get("country") or "").lower()
    if domain.endswith(".in") or domain.endswith(".co.in"):
        return True
    if "india" in country:
        return True
    return True  # default for Pune pipeline


# ── Field update helpers ───────────────────────────────────────────────────────

def _set_email(company: dict, email: str, source: str, status: str) -> dict:
    c = dict(company)
    c["email"] = email
    c["email_source"] = source  # track source for audit
    emails = list(c.get("emails") or [])
    if email not in emails:
        emails.insert(0, email)
    c["emails"] = emails
    fv = dict(c.get("_field_verification") or {})
    fv["email"] = {"value": email, "verified": True, "status": status, "source": source}
    c["_field_verification"] = fv
    return c


def _set_founder(company: dict, name: str, source: str, status: str) -> dict:
    if not _is_plausible_person_name(name):
        _log("WATERFALL[FOUNDER]", f"Rejected implausible name: {name!r}")
        return company
    c = dict(company)
    c["founder_name"] = name
    c["founder_source"] = source  # track source for audit
    fv = dict(c.get("_field_verification") or {})
    fv["founder"] = {"value": name, "verified": True, "status": status, "source": source}
    c["_field_verification"] = fv
    return c


def _set_phone(company: dict, phone: str, source: str, status: str) -> dict:
    c = dict(company)
    c["company_number"] = phone
    c["phone_source"] = source  # track source for audit
    phones = list(c.get("phones") or [])
    if phone not in phones:
        phones.insert(0, phone)
    c["phones"] = phones
    fv = dict(c.get("_field_verification") or {})
    fv["phone"] = {"value": phone, "verified": True, "status": status, "source": source}
    c["_field_verification"] = fv
    return c


def _set_address(company: dict, address: str, city: str,
                  state: str, country: str, source: str, status: str) -> dict:
    c = dict(company)
    c["address"] = address
    c["address_source"] = source  # track source for audit
    if city:    c["city"]    = city
    if state:   c["state"]   = state
    if country: c["country"] = country
    fv = dict(c.get("_field_verification") or {})
    fv["address"] = {"value": address, "verified": True, "status": status, "source": source}
    c["_field_verification"] = fv
    return c


def _recalculate_confidence(company: dict) -> float:
    fv    = company.get("_field_verification") or {}
    score = 0.0
    if company.get("email"):          score += 0.30
    if company.get("company_number"): score += 0.25
    if company.get("address"):        score += 0.10
    if company.get("founder_name"):   score += 0.10
    if company.get("domain"):         score += 0.05
    pages = len((company.get("pages_visited") or {}).get("success", []))
    if pages >= 2:                    score += 0.10
    verified = sum(1 for v in fv.values() if isinstance(v, dict) and v.get("verified"))
    if verified >= 3:                 score += 0.10
    return round(min(score, 1.0), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# WATERFALL: EMAIL — Hunter → (Apollo skipped free) → keep Firecrawl value
# ═══════════════════════════════════════════════════════════════════════════════

async def _waterfall_email(company: dict) -> dict:
    """
    EMAIL waterfall: Hunter domain-search → Hunter email-finder → Firecrawl/Serper contact-page value.
    Apollo free tier does not return emails — skip.
    Accepts ONLY company-domain emails. Rejects personal/disposable.
    """
    if _email_verified(company):
        return company

    name   = company.get("company_name", "")
    domain = company.get("domain", "")

    # ── Hunter domain-search (primary) ────────────────────────────────────────
    if _hunter_key() and domain:
        try:
            _stats.hunter_calls += 1
            email, src, status = await _hunter.find_email(name, domain)
            if email:
                _stats.hunter_hits += 1
                _log("WATERFALL[EMAIL]", f"{name} → Hunter HIT: {email} [{status}]")
                return _set_email(company, email, src, status)
            else:
                _log("WATERFALL[EMAIL]", f"{name} → Hunter MISS [{status}]")
        except Exception as exc:
            _log("WATERFALL[EMAIL]", f"{name} → Hunter error: {exc}")

    # ── Apollo: free tier does not return emails reliably — skip ──────────────
    # apollo.io organizations/search does not include email address in free tier

    # ── Firecrawl scraped value (already in company dict) ────────────────────
    existing = company.get("email")
    if existing:
        # Validate it's a company-domain email (not personal)
        edom = existing.split("@")[-1].lower() if "@" in existing else ""
        personal = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                    "rediffmail.com", "icloud.com", "protonmail.com", "live.com"}
        if edom in personal:
            _log("WATERFALL[EMAIL]", f"{name} → Firecrawl email {existing!r} is personal — discarding")
            company = dict(company)
            company["email"] = None
        else:
            _log("WATERFALL[EMAIL]", f"{name} → keeping Firecrawl email: {existing}")
            return company
    else:
        _log("WATERFALL[EMAIL]", f"{name} → no email found from any source")
    return company


# ═══════════════════════════════════════════════════════════════════════════════
# WATERFALL: FOUNDER — PDL → (Apollo skipped free) → keep Firecrawl value
# ═══════════════════════════════════════════════════════════════════════════════

async def _waterfall_founder(company: dict) -> dict:
    """
    FOUNDER waterfall: PDL → Apollo (skipped on free tier) → Firecrawl scraped value.
    Uses strict name validation at every step.
    """
    if _founder_verified(company):
        return company

    name   = company.get("company_name", "")
    domain = company.get("domain", "")
    city   = company.get("city", "")

    # ── PDL (primary) ─────────────────────────────────────────────────────────
    if _pdl_key():
        try:
            _stats.pdl_calls += 1
            founder, src, status = await _pdl.find_founder(name, domain, city)
            if founder:
                _stats.pdl_hits += 1
                _log("WATERFALL[FOUNDER]", f"{name} → PDL HIT: {founder!r} [{status}]")
                return _set_founder(company, founder, src, status)
            else:
                _log("WATERFALL[FOUNDER]", f"{name} → PDL MISS [{status}]")
        except Exception as exc:
            _log("WATERFALL[FOUNDER]", f"{name} → PDL error: {exc}")

    # ── Apollo: mixed_people/search is 403 on free tier — skip ───────────────

    # ── Firecrawl scraped value (already in company dict) ────────────────────
    existing = company.get("founder_name")
    if existing:
        _log("WATERFALL[FOUNDER]", f"{name} → keeping Firecrawl founder: {existing}")
    else:
        _log("WATERFALL[FOUNDER]", f"{name} → no founder found from any source")
    return company


# ═══════════════════════════════════════════════════════════════════════════════
# WATERFALL: PHONE — Google Places → Apollo → keep Firecrawl value
# ═══════════════════════════════════════════════════════════════════════════════

async def _waterfall_phone(company: dict) -> dict:
    """PHONE waterfall: Google Places (if key) → Apollo → Firecrawl → PDL."""
    if _phone_verified(company):
        return company

    name  = company.get("company_name", "")
    dom   = company.get("domain", "")
    city  = company.get("city", "Pune") or "Pune"
    state = company.get("state", "")
    is_india = _is_india(company)

    # ── Google Places (primary — currently no key, fast skip) ────────────────
    if _gplaces_key():
        try:
            _stats.google_places_calls += 1
            phone, address, city_o, state_o, country_o, status = \
                await _gplaces.find_phone_and_address(name, city, state, prefer_india=is_india)
            if phone or address:
                _stats.google_places_hits += 1
            if phone:
                _log("WATERFALL[PHONE]", f"{name} → GPlaces HIT: {phone} [{status}]")
                return _set_phone(company, phone, "google_places", status)
        except Exception as exc:
            _log("WATERFALL[PHONE]", f"{name} → GPlaces error: {exc}")

    # ── Apollo organizations/search (free tier, returns phone) ───────────────
    if _apollo_key():
        try:
            _stats.apollo_calls += 1
            phone, src, status = await _apollo.find_phone(name, dom, prefer_india=is_india)
            if phone:
                _stats.apollo_hits += 1
                _log("WATERFALL[PHONE]", f"{name} → Apollo HIT: {phone} [{status}]")
                return _set_phone(company, phone, src, status)
            else:
                _log("WATERFALL[PHONE]", f"{name} → Apollo MISS [{status}]")
        except Exception as exc:
            _log("WATERFALL[PHONE]", f"{name} → Apollo error: {exc}")

    # ── Firecrawl scraped value ───────────────────────────────────────────────
    existing = company.get("company_number")
    if existing:
        # For India companies, reject foreign numbers from Firecrawl
        from app.services.verify_service import _is_foreign_number, _is_indian_number
        if is_india and _is_foreign_number(existing):
            _log("WATERFALL[PHONE]", f"{name} → Firecrawl phone {existing!r} is foreign — discarding for India company")
            company = dict(company)
            company["company_number"] = None
            # Also clean from phones list
            company["phones"] = [p for p in (company.get("phones") or []) if not _is_foreign_number(p)]
        else:
            _log("WATERFALL[PHONE]", f"{name} → keeping Firecrawl phone: {existing}")
            return company

    # ── PDL company/enrich (final fallback) ───────────────────────────────────
    # PDL company/enrich doesn't return phone directly but we can check anyway
    # (PDL person records sometimes have phone; not reliable — skip)

    _log("WATERFALL[PHONE]", f"{name} → no phone found from any source")
    return company


# ═══════════════════════════════════════════════════════════════════════════════
# WATERFALL: ADDRESS — Google Places → PDL → keep Firecrawl value
# ═══════════════════════════════════════════════════════════════════════════════

async def _waterfall_address(company: dict, requested_city: str = "") -> dict:
    """ADDRESS waterfall: Google Places (if key) → PDL → Firecrawl website value."""
    if _address_verified(company):
        return company

    name  = company.get("company_name", "")
    dom   = company.get("domain", "")
    city  = company.get("city", "") or requested_city or "Pune"
    state = company.get("state", "")

    # ── Google Places (primary — currently no key, fast skip) ────────────────
    if _gplaces_key():
        try:
            _stats.google_places_calls += 1
            phone, address, city_o, state_o, country_o, status = \
                await _gplaces.find_phone_and_address(name, city, state, prefer_india=_is_india(company))
            if phone or address:
                _stats.google_places_hits += 1
            if address:
                _log("WATERFALL[ADDR]", f"{name} → GPlaces HIT: {address[:60]} [{status}]")
                return _set_address(company, address,
                                    city_o or city, state_o or state,
                                    country_o or "India",
                                    "google_places", status)
        except Exception as exc:
            _log("WATERFALL[ADDR]", f"{name} → GPlaces error: {exc}")

    # ── PDL company/enrich ───────────────────────────────────────────────────
    if _pdl_key() and dom:
        try:
            _stats.pdl_calls += 1
            address, city_o, state_o, country_o, status = \
                await _pdl.find_company_address(dom, name, requested_city=requested_city or city)
            if address:
                _stats.pdl_hits += 1
                _log("WATERFALL[ADDR]", f"{name} → PDL HIT: {address[:60]} [{status}]")
                return _set_address(company, address,
                                    city_o or city, state_o or state,
                                    country_o or "India",
                                    "people-data-labs.com", status)
            else:
                _log("WATERFALL[ADDR]", f"{name} → PDL MISS [{status}]")
        except Exception as exc:
            _log("WATERFALL[ADDR]", f"{name} → PDL error: {exc}")

    # ── Firecrawl scraped value ───────────────────────────────────────────────
    existing = company.get("address")
    if existing:
        # Validate the existing Firecrawl address contains a location signal
        from app.services.verify_service import verify_address_local
        clean_addr, vstatus = verify_address_local(existing, dom)
        if clean_addr and vstatus == "verified_location":
            # For Pune queries: reject addresses that are clearly non-Pune cities
            _req_city = (requested_city or "").lower()
            if _req_city in ("pune", "pimpri", "pimpri-chinchwad"):
                # Check if address mentions non-Pune major city and NO Pune mention
                non_pune = {"mumbai", "delhi", "bangalore", "bengaluru",
                            "hyderabad", "chennai", "kolkata", "noida", "gurugram"}
                addr_lower = clean_addr.lower()
                mentions_pune = any(kw in addr_lower for kw in (
                    "pune", "pimpri", "chinchwad", "hinjewadi", "kharadi",
                    "baner", "wakad", "hadapsar", "magarpatta", "kothrud",
                    "viman", "koregaon", "aundh", "shivajinagar"
                ))
                mentions_non_pune = any(c in addr_lower for c in non_pune)
                if not mentions_pune and mentions_non_pune:
                    _log("WATERFALL[ADDR]", f"{name} → Firecrawl address is non-Pune city, discarding: {clean_addr[:50]}")
                    company = dict(company)
                    company["address"] = None
                    return company
            _log("WATERFALL[ADDR]", f"{name} → keeping Firecrawl address: {clean_addr[:50]}")
            company = dict(company)
            company["address"] = clean_addr
            return company
        else:
            _log("WATERFALL[ADDR]", f"{name} → Firecrawl address failed validation [{vstatus}]: {existing[:50]}")
    else:
        _log("WATERFALL[ADDR]", f"{name} → no address found from any source")
    return company


# ═══════════════════════════════════════════════════════════════════════════════
# PER-COMPANY ENRICHMENT ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

async def _enrich_one(company: dict, requested_city: str = "") -> dict:
    """
    Enrich one company: run all waterfalls concurrently.
    Google Places is called ONCE and shared between phone+address waterfalls.
    """
    name   = company.get("company_name", "?")
    domain = company.get("domain", "")

    # Domain cache check
    if domain:
        cached = _cache_get(domain)
        if cached:
            _stats.cache_hits += 1
            _log("WATERFALL[CACHE]", f"{name} → cache hit for {domain}")
            updated = dict(company)
            if not _email_verified(updated) and cached.get("email"):
                src = (cached.get("_field_verification") or {}).get("email", {}).get("source", "cache")
                st  = (cached.get("_field_verification") or {}).get("email", {}).get("status", "cache_verified")
                updated = _set_email(updated, cached["email"], src, st)
            if not _phone_verified(updated) and cached.get("phone"):
                src = (cached.get("_field_verification") or {}).get("phone", {}).get("source", "cache")
                st  = (cached.get("_field_verification") or {}).get("phone", {}).get("status", "cache_verified")
                updated = _set_phone(updated, cached["phone"], src, st)
            if not _address_verified(updated) and cached.get("address"):
                src = (cached.get("_field_verification") or {}).get("address", {}).get("source", "cache")
                st  = (cached.get("_field_verification") or {}).get("address", {}).get("status", "cache_verified")
                updated = _set_address(updated, cached["address"],
                    cached.get("city", "") or updated.get("city", ""),
                    cached.get("state", "") or updated.get("state", ""),
                    cached.get("country", "") or updated.get("country", "India"),
                    src, st)
            if not _founder_verified(updated) and cached.get("founder"):
                src = (cached.get("_field_verification") or {}).get("founder", {}).get("source", "cache")
                st  = (cached.get("_field_verification") or {}).get("founder", {}).get("status", "cache_verified")
                updated = _set_founder(updated, cached["founder"], src, st)
            updated["confidence"] = _recalculate_confidence(updated)
            return updated

    need_email   = not _email_verified(company)
    need_founder = not _founder_verified(company)
    need_phone   = not _phone_verified(company)
    need_address = not _address_verified(company)

    _log("WATERFALL", (
        f"{name}: need email={need_email} founder={need_founder} "
        f"phone={need_phone} address={need_address}"
    ))

    # Run all independent waterfalls concurrently
    tasks, labels = [], []
    if need_email:
        tasks.append(_waterfall_email(company)); labels.append("email")
    if need_founder:
        tasks.append(_waterfall_founder(company)); labels.append("founder")
    if need_phone:
        tasks.append(_waterfall_phone(company)); labels.append("phone")
    if need_address:
        tasks.append(_waterfall_address(company, requested_city)); labels.append("address")

    if not tasks:
        return company

    results = await asyncio.gather(*tasks, return_exceptions=True)

    updated = dict(company)
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            _log("WATERFALL", f"{name} → {label} exception: {result}")
            continue
        if not isinstance(result, dict):
            continue

        if label == "email":
            # Only update if result has an email AND current dict doesn't already have one
            if result.get("email") and not updated.get("email"):
                updated["email"]  = result["email"]
                updated["emails"] = result.get("emails", updated.get("emails", []))
                updated["email_source"] = result.get("email_source", "")
                fv = dict(updated.get("_field_verification") or {})
                rfv = result.get("_field_verification") or {}
                if "email" in rfv:
                    fv["email"] = rfv["email"]
                updated["_field_verification"] = fv

        elif label == "founder":
            if result.get("founder_name") and not updated.get("founder_name"):
                updated["founder_name"] = result["founder_name"]
                updated["founder_source"] = result.get("founder_source", "")
                fv  = dict(updated.get("_field_verification") or {})
                rfv = result.get("_field_verification") or {}
                if "founder" in rfv:
                    fv["founder"] = rfv["founder"]
                updated["_field_verification"] = fv

        elif label == "phone":
            if result.get("company_number") and not updated.get("company_number"):
                updated["company_number"] = result["company_number"]
                updated["phones"] = result.get("phones", updated.get("phones", []))
                updated["phone_source"] = result.get("phone_source", "")
                fv  = dict(updated.get("_field_verification") or {})
                rfv = result.get("_field_verification") or {}
                if "phone" in rfv:
                    fv["phone"] = rfv["phone"]
                updated["_field_verification"] = fv

        elif label == "address":
            if result.get("address") and not updated.get("address"):
                updated["address"] = result["address"]
                for f in ("city", "state", "country"):
                    if result.get(f):
                        updated[f] = result[f]
                updated["address_source"] = result.get("address_source", "")
                fv  = dict(updated.get("_field_verification") or {})
                rfv = result.get("_field_verification") or {}
                if "address" in rfv:
                    fv["address"] = rfv["address"]
                updated["_field_verification"] = fv

    updated["confidence"] = _recalculate_confidence(updated)

    # Cache result
    if domain:
        _cache_set(domain, {
            "email":   updated.get("email"),
            "phone":   updated.get("company_number"),
            "address": updated.get("address"),
            "city":    updated.get("city", ""),
            "state":   updated.get("state", ""),
            "country": updated.get("country", ""),
            "founder": updated.get("founder_name"),
            "_field_verification": updated.get("_field_verification", {}),
        })

    return updated


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def enrich_all_companies(
    companies: list[dict],
    requested_city: str = "",
) -> list[dict]:
    """
    Run waterfall enrichment for all companies concurrently.
    Logs provider status at start of every run.
    """
    if not companies:
        return companies

    reset_stats()

    # Log provider status at start of every run
    ps = _provider_status()
    _log("PROVIDERS", "Provider availability at enrichment start:")
    for provider, enabled in ps.items():
        status = "ENABLED" if enabled else "DISABLED (no key)"
        _log("PROVIDERS", f"  {provider}: {status}")

    active = [p for p, enabled in ps.items() if enabled]
    if not active:
        _log("WATERFALL", "No enrichment providers configured — only Firecrawl data will be used")
        return companies

    _log("WATERFALL", (
        f"Starting enrichment: {len(companies)} companies | "
        f"providers={active} | city={requested_city!r} | concurrency={_ENRICH_SEM_SIZE}"
    ))
    t0 = time.monotonic()

    sem = asyncio.Semaphore(_ENRICH_SEM_SIZE)

    async def _bounded(c: dict) -> dict:
        async with sem:
            try:
                return await asyncio.wait_for(
                    _enrich_one(c, requested_city=requested_city),
                    timeout=_COMPANY_TIMEOUT,
                )
            except asyncio.TimeoutError:
                _log("WATERFALL", f"Timeout enriching {c.get('company_name','?')}")
                return c
            except Exception as exc:
                _log("WATERFALL", f"Error enriching {c.get('company_name','?')}: {exc}")
                return c

    results = await asyncio.gather(*[_bounded(c) for c in companies], return_exceptions=True)

    out: list[dict] = []
    for original, result in zip(companies, results):
        if isinstance(result, Exception):
            _log("WATERFALL", f"gather error for {original.get('company_name','?')}: {result}")
            out.append(original)
        else:
            out.append(result)

    elapsed = round(time.monotonic() - t0, 1)
    n  = len(out)
    st = get_stats()

    _log("ENRICHMENT SUMMARY", (
        f"Complete in {elapsed}s | "
        f"email={sum(1 for c in out if c.get('email'))}/{n} | "
        f"phone={sum(1 for c in out if c.get('company_number'))}/{n} | "
        f"address={sum(1 for c in out if c.get('address'))}/{n} | "
        f"founder={sum(1 for c in out if c.get('founder_name'))}/{n}"
    ))
    _log("ENRICHMENT SUMMARY", (
        f"Hunter={st['hunter_calls']}(hits={st['hunter_hits']}) | "
        f"Apollo={st['apollo_calls']}(hits={st['apollo_hits']}) | "
        f"PDL={st['pdl_calls']}(hits={st['pdl_hits']}) | "
        f"GPlaces={st['google_places_calls']}(hits={st['google_places_hits']}) | "
        f"cache_hits={st['cache_hits']}"
    ))

    return out
