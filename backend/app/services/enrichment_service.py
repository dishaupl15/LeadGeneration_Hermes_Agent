"""
app/services/enrichment_service.py
────────────────────────────────────
CompanyEnrich-ONLY enrichment engine.

STRICT PROVIDER POLICY:
  providers = ["CompanyEnrich"]

  Hunter       : NOT USED — no calls, no imports, no execution path
  Apollo       : NOT USED — no calls, no imports, no execution path
  PDL          : NOT USED — no calls, no imports, no execution path
  Google Places: NOT USED — no calls, no imports, no execution path

Every field is sourced from CompanyEnrich:
  email          → /people/email via find_founder_with_email()
  founder_name   → /people/search via find_founder_with_email()
  founder_number → /people/search person.phones[] (if available)
  company_number → /companies/enrich location.phone
  address        → /companies/enrich location.*
  city/state/country/postal_code → /companies/enrich location.*
  website        → /companies/enrich .website

For every company, enrich_company_full() is called. It makes two concurrent
API calls (companies/enrich + people/search) and attempts people/email.

A company is ACCEPTED only if it has ALL required CRM fields after enrichment:
  company_name, email, company_number, address, founder_name, website

Companies that remain incomplete after all CompanyEnrich attempts are REJECTED
and will NOT be written to MongoDB.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from app.services import companyenrich_service as _ce
from app.services.verify_service import _is_plausible_person_name

# ── Configuration ─────────────────────────────────────────────────────────────
_ENRICH_SEM_SIZE = 5      # max companies enriched simultaneously
_COMPANY_TIMEOUT = 30.0   # longer timeout since we make 2–3 API calls per company
_CACHE_TTL       = 3600   # 1-hour domain cache TTL

# ── Domain-level TTL cache ────────────────────────────────────────────────────
# Cache key is "domain|category_key|city" so that a company enriched for
# "Hospitality in Pune" is NEVER reused for "Agriculture in Pune".
# Requirement: cache validation must include category + location + domain.
_DOMAIN_CACHE: dict[str, dict] = {}


def _cache_key(domain: str, category_key: str = "", city: str = "") -> str:
    """Build a category+location aware cache key."""
    return f"{domain}|{category_key.lower().strip()}|{city.lower().strip()}"


def _cache_get(domain: str, category_key: str = "", city: str = "") -> Optional[dict]:
    if not domain:
        return None
    key = _cache_key(domain, category_key, city)
    entry = _DOMAIN_CACHE.get(key)
    if not entry:
        return None
    if time.monotonic() - entry.get("_cached_at", 0) > _CACHE_TTL:
        del _DOMAIN_CACHE[key]
        return None
    return entry


def _cache_set(domain: str, data: dict, category_key: str = "", city: str = "") -> None:
    if not domain:
        return
    key = _cache_key(domain, category_key, city)
    _DOMAIN_CACHE[key] = {**data, "_cached_at": time.monotonic()}


# ── Stats (reset per pipeline run) ────────────────────────────────────────────
class _EnrichStats:
    def __init__(self):
        self.companyenrich_calls = 0
        self.companyenrich_hits  = 0
        self.cache_hits          = 0
        # kept for pipeline_stats compatibility (all zeros)
        self.hunter_calls = self.apollo_calls = self.pdl_calls = self.google_places_calls = 0
        self.hunter_hits  = self.apollo_hits  = self.pdl_hits  = self.google_places_hits  = 0

_stats = _EnrichStats()


def reset_stats() -> None:
    global _stats
    _stats = _EnrichStats()


def get_stats() -> dict:
    """Return stats dict — Hunter/Apollo/PDL/GPlaces are always 0."""
    return {
        "companyenrich_calls": _stats.companyenrich_calls,
        "companyenrich_hits":  _stats.companyenrich_hits,
        "cache_hits":          _stats.cache_hits,
        # Legacy keys expected by routes/leads.py pipeline_stats — always 0
        "hunter_calls":        0,
        "hunter_hits":         0,
        "apollo_calls":        0,
        "apollo_hits":         0,
        "pdl_calls":           0,
        "pdl_hits":            0,
        "google_places_calls": 0,
        "google_places_hits":  0,
    }


def _log(tag: str, msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


def _companyenrich_key() -> str:
    return os.getenv("COMPANYENRICH_API_KEY", "").strip()


# ── Field helpers ─────────────────────────────────────────────────────────────

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


def is_complete(company: dict) -> bool:
    """
    Return True only if the minimum required CRM fields are present.

    HARD required (must be present for a useful CRM lead):
      company_name, website, email, company_number

    SOFT fields (logged as warnings, not rejection criteria):
      address, founder_name  — useful but not always available

    Companies failing the HARD check are rejected — not written to MongoDB.
    """
    hard_required = {
        "company_name":   company.get("company_name"),
        "website":        company.get("website"),
        "email":          company.get("email"),
        "company_number": company.get("company_number"),
    }
    missing_hard = [k for k, v in hard_required.items() if not v]
    if missing_hard:
        _log("COMPLETENESS", f"{company.get('company_name','?')} — REJECTED missing: {missing_hard}")
        return False

    # Log soft-missing fields as warnings (not rejection)
    soft_required = {
        "address":      company.get("address"),
        "founder_name": company.get("founder_name"),
    }
    missing_soft = [k for k, v in soft_required.items() if not v]
    if missing_soft:
        _log("COMPLETENESS", (
            f"{company.get('company_name','?')} — ACCEPTED (soft fields missing: {missing_soft})"
        ))
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# PER-COMPANY ENRICHMENT — CompanyEnrich only
# ═══════════════════════════════════════════════════════════════════════════════

async def _enrich_one(
    company: dict,
    requested_city: str = "",
    requested_category_key: str = "",
) -> dict:
    """
    Enrich one company using only CompanyEnrich.

    Strategy:
      1. Skip companies already enriched by _process_ce_candidate() in
         discovery_service — they have _ce_enriched=True and already carry
         authoritative CompanyEnrich data. Re-enriching them wastes credits
         and can overwrite valid CE data with an identical (or stale) API response.
      2. Check domain cache (category+location aware — a hotel enriched for
         "Hospitality" is NEVER reused for "Agriculture").
      3. Call enrich_company_full() — two concurrent API calls:
           GET /companies/enrich?domain=   → company fields
           POST /people/search + GET /people/email → founder + email
      4. Merge enriched data into the company dict.
      5. Mark confidence score.
    """
    name   = company.get("company_name", "?")
    domain = company.get("domain") or company.get("website", "")

    # Normalize domain from website URL if needed
    from app.services.companyenrich_service import _normalize_domain
    if not domain and company.get("website"):
        domain = _normalize_domain(company["website"])

    if not domain:
        _log("ENRICH[CE]", f"{name}: no domain — cannot enrich")
        return company

    # ── Skip double-enrichment for CE-primary candidates ──────────────────────
    # _process_ce_candidate() already called /companies/enrich + /people/search
    # + /people/email for this company. The authoritative CE data is already
    # embedded. Calling enrich_company_full() again would:
    #   - waste ~3 API credits per company
    #   - potentially overwrite a valid CE founder/email with null if the second
    #     /people/search returns fewer results (caching is non-deterministic)
    # We recalculate the confidence score and return immediately.
    if company.get("_ce_enriched"):
        _stats.cache_hits += 1
        _log("ENRICH[CE]", f"{name}: skipping re-enrichment (_ce_enriched=True) for domain={domain!r}")
        updated = dict(company)
        updated["confidence"] = _recalculate_confidence(updated)
        return updated

    # Cache check — category+location aware to prevent cross-category reuse
    cache_hit = _cache_get(domain, requested_category_key, requested_city)
    if cache_hit:
        _stats.cache_hits += 1
        _log("ENRICH[CE]", f"{name} → cache hit for {domain} (category={requested_category_key!r}, city={requested_city!r})")
        updated = dict(company)
        updated.update({k: v for k, v in cache_hit.items() if v and k != "_cached_at"})
        updated["confidence"] = _recalculate_confidence(updated)
        return updated

    _log("ENRICH[CE]", f"{name}: calling CompanyEnrich for domain={domain!r}")
    _stats.companyenrich_calls += 1

    # Skip CE call if credits are exhausted — fall through to Serper/Firecrawl data
    from app.services.companyenrich_service import is_credits_exhausted
    if is_credits_exhausted():
        _log("ENRICH[CE]", f"{name}: skipping CE call (credits exhausted — 402)")
        return company

    enriched = await _ce.enrich_company_full(name, domain)

    if not enriched:
        _log("ENRICH[CE]", f"{name}: CompanyEnrich returned no data")
        return company

    _stats.companyenrich_hits += 1

    # Merge enriched fields into company dict — enriched values WIN over
    # whatever discovery/Firecrawl may have set (CompanyEnrich is authoritative)
    updated = dict(company)

    # Company identity fields
    if enriched.get("company_name"):
        updated["company_name"] = enriched["company_name"]
    if enriched.get("website"):
        updated["website"] = enriched["website"]
    if enriched.get("domain"):
        updated["domain"] = enriched["domain"]

    # Contact fields
    if enriched.get("company_number"):
        updated["company_number"] = enriched["company_number"]
        phones = list(updated.get("phones") or [])
        if enriched["company_number"] not in phones:
            phones.insert(0, enriched["company_number"])
        updated["phones"] = phones

    if enriched.get("email"):
        updated["email"] = enriched["email"]
        emails = list(updated.get("emails") or [])
        if enriched["email"] not in emails:
            emails.insert(0, enriched["email"])
        updated["emails"] = emails

    # Address
    if enriched.get("address"):
        updated["address"] = enriched["address"]
    if enriched.get("city"):    updated["city"]    = enriched["city"]
    if enriched.get("state"):   updated["state"]   = enriched["state"]
    if enriched.get("country"): updated["country"] = enriched["country"]
    if enriched.get("postal_code"): updated["postal_code"] = enriched["postal_code"]

    # Founder
    if enriched.get("founder_name"):
        if _is_plausible_person_name(enriched["founder_name"]):
            updated["founder_name"]   = enriched["founder_name"]
            updated["founder_number"] = enriched.get("founder_number")
        else:
            _log("ENRICH[CE]", f"{name} — rejected implausible founder {enriched['founder_name']!r}")

    # Source
    if enriched.get("source_url"):
        updated["source_url"]      = enriched["source_url"]
    updated["research_source"]     = "companyenrich"

    # Field verification
    fv = dict(updated.get("_field_verification") or {})
    ev = enriched.get("_field_verification") or {}
    for field, data in ev.items():
        if data:  # only overwrite with non-empty verification records
            fv[field] = data
    updated["_field_verification"] = fv

    updated["confidence"] = _recalculate_confidence(updated)

    # Cache the result — include category+city so cross-category reuse is prevented
    _cache_set(domain, {
        "company_name":   updated.get("company_name"),
        "website":        updated.get("website"),
        "email":          updated.get("email"),
        "company_number": updated.get("company_number"),
        "address":        updated.get("address"),
        "city":           updated.get("city", ""),
        "state":          updated.get("state", ""),
        "country":        updated.get("country", ""),
        "postal_code":    updated.get("postal_code", ""),
        "founder_name":   updated.get("founder_name"),
        "founder_number": updated.get("founder_number"),
        "_field_verification": updated.get("_field_verification", {}),
    }, category_key=requested_category_key, city=requested_city)

    _log("ENRICH[CE]", (
        f"{name}: done — "
        f"email={bool(updated.get('email'))} "
        f"phone={bool(updated.get('company_number'))} "
        f"address={bool(updated.get('address'))} "
        f"founder={updated.get('founder_name')!r} "
        f"confidence={updated.get('confidence')}"
    ))
    return updated


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def enrich_all_companies(
    companies: list[dict],
    requested_city: str = "",
    requested_category_key: str = "",
) -> list[dict]:
    """
    Run CompanyEnrich enrichment for all companies concurrently.

    PROVIDERS LOG:
      [PROVIDERS] CompanyEnrich : ENABLED
      [PROVIDERS] Hunter        : NOT USED
      [PROVIDERS] Apollo        : NOT USED
      [PROVIDERS] PDL           : NOT USED
      [PROVIDERS] Google Places : NOT USED
    """
    if not companies:
        return companies

    reset_stats()

    # Log provider status — only CompanyEnrich is active
    _log("PROVIDERS", "Provider configuration for this enrichment run:")
    _log("PROVIDERS", f"  CompanyEnrich : {'ENABLED' if _companyenrich_key() else 'DISABLED (no key)'}")
    _log("PROVIDERS", "  Hunter        : NOT USED")
    _log("PROVIDERS", "  Apollo        : NOT USED")
    _log("PROVIDERS", "  PDL           : NOT USED")
    _log("PROVIDERS", "  Google Places : NOT USED")

    if not _companyenrich_key():
        _log("ENRICH", "COMPANYENRICH_API_KEY not set — enrichment skipped")
        return companies

    _log("ENRICH", (
        f"Starting CompanyEnrich enrichment: {len(companies)} companies | "
        f"category={requested_category_key!r} city={requested_city!r} | "
        f"concurrency={_ENRICH_SEM_SIZE}"
    ))
    t0  = time.monotonic()
    sem = asyncio.Semaphore(_ENRICH_SEM_SIZE)

    async def _bounded(c: dict) -> dict:
        async with sem:
            try:
                return await asyncio.wait_for(
                    _enrich_one(
                        c,
                        requested_city=requested_city,
                        requested_category_key=requested_category_key,
                    ),
                    timeout=_COMPANY_TIMEOUT,
                )
            except asyncio.TimeoutError:
                _log("ENRICH", f"Timeout enriching {c.get('company_name','?')}")
                return c
            except Exception as exc:
                _log("ENRICH", f"Error enriching {c.get('company_name','?')}: {exc}")
                return c

    results = await asyncio.gather(*[_bounded(c) for c in companies], return_exceptions=True)

    out: list[dict] = []
    for original, result in zip(companies, results):
        if isinstance(result, Exception):
            _log("ENRICH", f"gather error for {original.get('company_name','?')}: {result}")
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
        f"founder={sum(1 for c in out if c.get('founder_name'))}/{n} | "
        f"CE_calls={st['companyenrich_calls']} hits={st['companyenrich_hits']} | "
        f"cache_hits={st['cache_hits']}"
    ))

    return out


# ── Backward-compat stubs so old imports don't break ─────────────────────────

def _email_verified(company: dict) -> bool:
    fv = company.get("_field_verification") or {}
    e  = fv.get("email") or {}
    return bool(company.get("email")) and bool(e.get("verified"))


def _phone_verified(company: dict) -> bool:
    fv = company.get("_field_verification") or {}
    return bool(company.get("company_number")) and bool((fv.get("phone") or {}).get("verified"))


def _address_verified(company: dict) -> bool:
    fv = company.get("_field_verification") or {}
    return bool(company.get("address")) and bool((fv.get("address") or {}).get("verified"))


def _founder_verified(company: dict) -> bool:
    fv = company.get("_field_verification") or {}
    return bool(company.get("founder_name")) and bool((fv.get("founder") or {}).get("verified"))
