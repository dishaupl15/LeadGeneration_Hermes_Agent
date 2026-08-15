"""
people_enrichment/orchestrator.py
───────────────────────────────────
Waterfall orchestrator: PDL → Prospeo → ContactOut.

Architecture
────────────
  Google Maps company
    ↓ existing company enrichment (CompanyEnrich → Serper → Firecrawl)
    ↓
  enrich_company_contacts(company_dict)
    ↓
  PDL  (always first — domain preferred, name fallback)
    ↓ check: useful_contacts >= TARGET?
  Prospeo  (if still needed)
    ↓ check: useful_contacts >= TARGET?
  ContactOut  (if still needed)
    ↓
  dedup + merge + rank
    ↓
  PeopleEnrichmentResult

Failure handling
────────────────
  - Auth failure on any provider → record it, continue to next provider.
    PDL auth_failed disables PDL only — Prospeo and ContactOut still run.
  - Any non-auth error (rate limit, request error, no results) is recorded
    in stats but does NOT stop the waterfall.
  - ContactOut HTTP 200 with profiles is always processed, even if the
    profiles have unrecognised titles. Title filtering must never convert
    "profiles found" into zero contacts.
  - A contact is "useful" when it has: name + (email OR phone).
    A title is preferred but not required — it affects ranking only.
  - No provider failure breaks the pipeline for any other provider.

Usefulness definition
─────────────────────
  Useful = name present AND (email OR phone present).
  Title is used for ranking/prioritisation only.
  Do NOT require title for a contact to be counted as useful.

Provider isolation
──────────────────
  This module imports ONLY from:
    people_data_labs.people_search   (search_company_contacts)
    prospeo.people_search            (search_contacts)
    contactout.people_search         (search_contacts)
    people_enrichment.dedup          (dedup_and_merge, count_useful)
    people_enrichment.scoring        (rank_contacts, is_useful)
    people_enrichment.schemas        (PeopleEnrichmentResult, ProviderStats, EnrichedContact)

  It does NOT reach into:
    - Any provider's client.py, config.py, or contact_mapper.py
    - app/services/
    - google_maps/
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from people_enrichment.dedup   import dedup_and_merge, count_useful
from people_enrichment.scoring import rank_contacts, is_useful
from people_enrichment.schemas import (
    EnrichedContact,
    PeopleEnrichmentBatchStats,
    PeopleEnrichmentResult,
    ProviderStats,
)


# ── Config ────────────────────────────────────────────────────────────────────

def _target() -> int:
    import os
    return max(1, int(os.getenv("PEOPLE_ENRICHMENT_TARGET", "2")))


# ── Logger ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [PEOPLE_ENRICH] {msg}", flush=True)


# ── In-memory cache (per pipeline run) ───────────────────────────────────────
# Key: normalised company_domain (or company_name when no domain).
# Cleared by reset_cache() at the start of each pipeline run.

_cache: dict[str, PeopleEnrichmentResult] = {}


def reset_cache() -> None:
    """Call at the start of each pipeline run to clear stale entries."""
    global _cache
    _cache = {}
    # Also reset PDL credits-exhausted flag so a new pipeline run re-checks
    try:
        from people_data_labs.client import reset_credits_flag
        reset_credits_flag()
    except Exception:
        pass
    _log("Cache cleared")


def _cache_key(company_name: str, domain: Optional[str]) -> str:
    dom = (domain or "").lower().strip().lstrip("www.").rstrip("/")
    if dom:
        return f"domain:{dom}"
    return f"name:{company_name.lower().strip()}"


# ── Domain normalisation ──────────────────────────────────────────────────────

def _normalise_domain(value: Optional[str]) -> Optional[str]:
    """
    Return a bare domain (e.g. 'example.com') or None if input is empty.
    Handles full URLs, www-prefixed, and bare domains.
    """
    if not value:
        return None
    v = value.strip().lower()
    if not v.startswith("http"):
        v = "https://" + v
    try:
        netloc = urlparse(v).netloc
        bare   = netloc.lstrip("www.").split(":")[0].strip()
        return bare or None
    except Exception:
        return value.lower().strip() or None


# ── Company name normalisation ────────────────────────────────────────────────

def _normalise_company_name(name: str) -> str:
    """
    Strip common legal suffixes and whitespace for cleaner matching.
    e.g. "Acme Pvt. Ltd." → "Acme"
    """
    if not name:
        return name
    # Remove trailing legal forms
    suffixes = r"\s*(pvt\.?|private|ltd\.?|limited|inc\.?|llc|llp|corp\.?|co\.?)\s*\.?\s*$"
    cleaned = re.sub(suffixes, "", name.strip(), flags=re.IGNORECASE).strip()
    # Collapse internal whitespace
    return re.sub(r"\s+", " ", cleaned)


# ── Contact normalisation helpers ─────────────────────────────────────────────

def _pdl_contact_to_dict(c) -> dict:
    """
    Convert PeopleDataLabsContact → raw dict used by dedup.
    PDL uses 'designation' for title — map it to 'title' for the shared layer.
    """
    return {
        "name":         getattr(c, "name", None),
        # PDL stores title in 'designation' — normalize to 'title'
        "title":        getattr(c, "designation", None) or getattr(c, "title", None),
        "email":        getattr(c, "email", None),
        "phone":        getattr(c, "phone", None),
        "linkedin_url": getattr(c, "linkedin_url", None),
        "sources":      ["pdl"],
        "confidence":   getattr(c, "confidence", 0.0),
    }


def _prospeo_contact_to_dict(c) -> dict:
    """Convert ProspeoContact → raw dict used by dedup."""
    return {
        "name":         getattr(c, "name", None),
        "title":        getattr(c, "title", None),
        "email":        getattr(c, "email", None),
        "phone":        getattr(c, "phone", None),
        "linkedin_url": getattr(c, "linkedin_url", None),
        "sources":      ["prospeo"],
        "confidence":   getattr(c, "confidence", 0.0),
    }


def _contactout_contact_to_dict(c) -> dict:
    """Convert ContactOutContact → raw dict used by dedup."""
    return {
        "name":         getattr(c, "name", None),
        "title":        getattr(c, "title", None),
        "email":        getattr(c, "email", None),
        "phone":        getattr(c, "phone", None),
        "linkedin_url": getattr(c, "linkedin_url", None),
        "sources":      ["contactout"],
        "confidence":   getattr(c, "confidence", 0.0),
    }


# ── Provider calls ────────────────────────────────────────────────────────────
# Rules for every _call_* function:
#   - NEVER raise — always return (raw_contacts, ProviderStats)
#   - auth_failed → stats.error = "auth_failed", raw = []
#   - any other error → stats.error = error_code, raw = whatever was returned
#   - Contacts are extracted from result.contacts regardless of non-auth errors
#     (e.g. Prospeo rate-limits bulk_enrich but still returns search candidates)
#   - Domain is tried first; name fallback is handled inside each provider module

async def _call_pdl(
    company_name: str,
    domain: Optional[str],
    website: Optional[str],
) -> tuple[list[dict], ProviderStats]:
    """
    Call PDL for contacts.

    Auth failure disables PDL for this company only — does NOT affect
    Prospeo or ContactOut.
    """
    stats = ProviderStats(called=True)
    raw: list[dict] = []

    try:
        from people_data_labs.config import is_configured as _pdl_ok
        if not _pdl_ok():
            stats.called         = False
            stats.skipped_reason = "not_configured"
            _log("PDL skipped — not configured")
            return raw, stats

        from people_data_labs.people_search import search_company_contacts
        result = await search_company_contacts(
            company_name=company_name,
            domain=domain,
            website=website,
        )
    except Exception as exc:
        stats.error = f"{type(exc).__name__}: {exc}"
        _log(f"PDL exception — {stats.error}")
        return raw, stats

    stats.api_calls      = getattr(result, "pdl_api_calls", 0)
    stats.contacts_found = result.contacts_found
    stats.emails_found   = result.emails_found
    stats.phones_found   = getattr(result, "phones_found", 0)

    if result.error == "auth_failed":
        stats.error = "auth_failed"
        _log("PDL auth_failed — PDL disabled for this company; continuing to Prospeo")
        return raw, stats

    if result.error == "no_credits":
        stats.error = "no_credits"
        stats.called = True
        _log("PDL no_credits (402) — PDL credits exhausted; continuing to Prospeo")
        return raw, stats

    if result.error:
        # Non-fatal error (rate limit, no results, etc.) — log but keep any contacts
        stats.error = result.error
        _log(f"PDL non-fatal error: {result.error!r} — keeping {len(result.contacts)} contacts")

    raw = [_pdl_contact_to_dict(c) for c in result.contacts]
    _log(
        f"PDL: contacts={len(raw)} "
        f"emails={stats.emails_found} "
        f"phones={stats.phones_found} "
        f"error={result.error!r}"
    )
    return raw, stats


async def _call_prospeo(
    company_name: str,
    domain: Optional[str],
) -> tuple[list[dict], ProviderStats]:
    """
    Call Prospeo for contacts.

    Any error is recorded but does not prevent ContactOut from running.
    Prospeo may return contacts even when bulk_enrich rate-limits
    (contacts will lack email/phone but still have name/title/LinkedIn).
    """
    stats = ProviderStats(called=True)
    raw: list[dict] = []

    try:
        from prospeo.config import is_configured as _prospeo_ok
        if not _prospeo_ok():
            stats.called         = False
            stats.skipped_reason = "not_configured"
            _log("Prospeo skipped — not configured")
            return raw, stats

        from prospeo.people_search import search_contacts
        result = await search_contacts(
            company_name=company_name,
            domain=domain,
        )
    except Exception as exc:
        stats.error = f"{type(exc).__name__}: {exc}"
        _log(f"Prospeo exception — {stats.error}")
        return raw, stats

    stats.api_calls      = getattr(result, "api_calls", 0)
    stats.contacts_found = result.contacts_found
    stats.emails_found   = result.emails_found
    stats.phones_found   = result.phones_found

    if result.error == "auth_failed":
        stats.error = "auth_failed"
        _log("Prospeo auth_failed — Prospeo disabled for this company; continuing to ContactOut")
        return raw, stats

    if result.error in ("rate_limited", "no_credits", "plan_required"):
        stats.error = result.error
        _log(f"Prospeo {result.error} — continuing to ContactOut")
        return raw, stats

    if result.error:
        # Non-fatal error — log and keep any contacts already found
        stats.error = result.error
        _log(f"Prospeo non-fatal error: {result.error!r} — keeping {len(result.contacts)} contacts")

    raw = [_prospeo_contact_to_dict(c) for c in result.contacts]
    _log(
        f"Prospeo: contacts={len(raw)} "
        f"emails={stats.emails_found} "
        f"phones={stats.phones_found} "
        f"error={result.error!r}"
    )
    return raw, stats


async def _call_hunter(
    company_name: str,
    domain: Optional[str],
) -> tuple[list[dict], ProviderStats]:
    """
    Call Hunter.io /domain-search as a fallback when PDL+Prospeo+ContactOut
    return zero emails.

    Delegates to the isolated hunter/ module (hunter/people_search.py).
    Skipped silently when HUNTER_API_KEY is not set.
    """
    stats = ProviderStats(called=True)
    raw:   list[dict] = []

    if not domain:
        stats.called         = False
        stats.skipped_reason = "no_domain"
        return raw, stats

    try:
        from hunter.config import is_configured as _hunter_ok
        if not _hunter_ok():
            stats.called         = False
            stats.skipped_reason = "not_configured"
            _log("Hunter skipped — HUNTER_API_KEY not set")
            return raw, stats

        from hunter.people_search import search_contacts as _hunter_search
        result = await _hunter_search(company_name=company_name, domain=domain)
    except Exception as exc:
        stats.error = f"{type(exc).__name__}: {exc}"
        _log(f"Hunter exception: {stats.error}")
        return raw, stats

    stats.api_calls      = result.calls
    stats.contacts_found = result.contacts_found
    stats.emails_found   = result.emails_found

    if result.error == "auth_failed":
        stats.error = "auth_failed"
        return raw, stats
    if result.error == "no_credits":
        stats.error = "no_credits"
        return raw, stats
    if result.error == "rate_limited":
        stats.error = "rate_limited"
        return raw, stats
    if result.error and result.error not in ("no_result",):
        stats.error = result.error

    # Convert HunterContact → orchestrator raw dict format
    for c in result.contacts:
        email = c.email or ""
        if not email:
            continue
        raw.append({
            "name":         c.name,
            "title":        c.title,
            "email":        email,
            "phone":        None,
            "linkedin_url": None,
            "sources":      ["hunter"],
            "confidence":   c.confidence,
        })

    stats.contacts_found = len(raw)
    stats.emails_found   = len(raw)
    _log(f"Hunter: domain={domain!r} contacts={len(raw)}")
    return raw, stats


async def _call_contactout(
    company_name: str,
    domain: Optional[str],
) -> tuple[list[dict], ProviderStats]:
    """
    Call ContactOut for contacts.

    ContactOut HTTP 200 with profiles must always be processed.
    Title filtering (done inside contactout.people_search) must never
    convert profiles into zero contacts — that is enforced in that module.
    """
    stats = ProviderStats(called=True)
    raw: list[dict] = []

    try:
        from contactout.config import is_configured as _co_ok
        if not _co_ok():
            stats.called         = False
            stats.skipped_reason = "not_configured"
            _log("ContactOut skipped — not configured")
            return raw, stats

        from contactout.people_search import search_contacts
        result = await search_contacts(
            company_name=company_name,
            domain=domain,
        )
    except Exception as exc:
        stats.error = f"{type(exc).__name__}: {exc}"
        _log(f"ContactOut exception — {stats.error}")
        return raw, stats

    stats.api_calls      = getattr(result, "api_calls", 0)
    stats.contacts_found = result.contacts_found
    stats.emails_found   = result.emails_found
    stats.phones_found   = result.phones_found

    if result.error == "auth_failed":
        stats.error = "auth_failed"
        _log("ContactOut auth_failed — ContactOut disabled for this company")
        return raw, stats

    if result.error:
        # Non-fatal — keep any contacts that were returned
        stats.error = result.error
        _log(f"ContactOut non-fatal error: {result.error!r} — keeping {len(result.contacts)} contacts")

    raw = [_contactout_contact_to_dict(c) for c in result.contacts]
    _log(
        f"ContactOut: contacts={len(raw)} "
        f"emails={stats.emails_found} "
        f"phones={stats.phones_found} "
        f"error={result.error!r}"
    )
    return raw, stats


# ── Main entry point (single company) ────────────────────────────────────────

async def enrich_company_contacts(
    company_name: str,
    domain: Optional[str] = None,
    website: Optional[str] = None,
    origami_contacts: Optional[list] = None,
) -> PeopleEnrichmentResult:
    """
    Waterfall people-enrichment for one company.

    Waterfall:
      0. Origami seed  (if origami_contacts provided — pre-seeded from origami_service)
      1. PDL    → if useful_contacts >= TARGET: stop
      2. Prospeo → if useful_contacts >= TARGET: stop
      3. ContactOut
      4. Hunter.io fallback (if no emails found)
      → dedup → merge → rank → return

    Domain is preferred for all provider calls.
    If domain is unavailable, each provider falls back to name matching.
    Company name is normalised before use (strips legal suffixes).

    Args:
        company_name:     Required — used for name-match fallback.
        domain:           Bare domain e.g. "example.com" (preferred).
        website:          Full URL — domain is extracted when domain is absent.
        origami_contacts: Optional list of raw contact dicts from Origami.
                          These are seeded into the dedup pool before PDL runs
                          so any duplicates across providers are merged cleanly.

    Returns:
        PeopleEnrichmentResult with merged, deduped, ranked contacts.
        Never raises — all provider errors are captured in provider_stats.
    """
    t0     = time.monotonic()
    TARGET = _target()

    # Resolve domain from website if not provided directly
    if not domain and website:
        domain = _normalise_domain(website)

    # Normalise company name (strip Pvt. Ltd. etc.)
    norm_name = _normalise_company_name(company_name) or company_name

    cache_key = _cache_key(norm_name, domain)

    # Cache hit
    if cache_key in _cache:
        _log(f"Cache hit for {company_name!r} ({cache_key})")
        return _cache[cache_key]

    _log(f"─── {company_name!r} ───")
    _log(f"domain={domain or '(none — name match)'!r}  target={TARGET}")

    all_raw:        list[dict]               = []
    provider_stats: dict[str, ProviderStats] = {}
    providers_used: list[str]                = []

    # ════════════════════════════════════════════════════════════════════════
    # STEP 0 — Origami (optional pre-seed)
    # Origami contacts are staged in company["_origami_contacts"] by
    # app/services/origami_service.py which runs earlier in the pipeline.
    # Injected here so dedup_and_merge() treats them alongside PDL/Prospeo/
    # ContactOut contacts — cross-provider duplicates are merged cleanly.
    # ════════════════════════════════════════════════════════════════════════
    _origami_seed: list[dict] = list(origami_contacts or [])
    if _origami_seed:
        _log(f"--- Origami seed: {len(_origami_seed)} contacts ---")
        all_raw.extend(_origami_seed)
        providers_used.append("origami")
        provider_stats["origami"] = ProviderStats(
            called=True,
            contacts_found=len(_origami_seed),
            emails_found=sum(1 for c in _origami_seed if c.get("email")),
            phones_found=sum(1 for c in _origami_seed if c.get("phone")),
        )

    # ════════════════════════════════════════════════════════════════════════
    # STEP 1 — PDL
    # ════════════════════════════════════════════════════════════════════════
    _log("--- PDL ---")
    pdl_raw, pdl_stats = await _call_pdl(norm_name, domain, website)
    provider_stats["pdl"] = pdl_stats

    if pdl_stats.called and not pdl_stats.skipped_reason:
        providers_used.append("pdl")

    all_raw.extend(pdl_raw)
    merged_after_pdl = dedup_and_merge(all_raw, domain)
    useful_after_pdl = count_useful(merged_after_pdl)
    _log(
        f"After PDL: raw={len(pdl_raw)} "
        f"merged={len(merged_after_pdl)} "
        f"useful={useful_after_pdl}"
    )

    if useful_after_pdl >= TARGET and pdl_stats.called and not pdl_stats.error:
        _log(f"Target {TARGET} reached after PDL — skipping Prospeo + ContactOut")
        provider_stats["prospeo"]    = ProviderStats(called=False, skipped_reason="target_reached")
        provider_stats["contactout"] = ProviderStats(called=False, skipped_reason="target_reached")
        result = _finalise(all_raw, domain, provider_stats, providers_used, TARGET, t0)
        _cache[cache_key] = result
        return result

    # ════════════════════════════════════════════════════════════════════════
    # STEP 2 — Prospeo
    # ════════════════════════════════════════════════════════════════════════
    _log("--- Prospeo ---")
    prospeo_raw, prospeo_stats = await _call_prospeo(norm_name, domain)
    provider_stats["prospeo"] = prospeo_stats

    if prospeo_stats.called and not prospeo_stats.skipped_reason:
        providers_used.append("prospeo")

    all_raw.extend(prospeo_raw)
    merged_after_prospeo = dedup_and_merge(all_raw, domain)
    useful_after_prospeo = count_useful(merged_after_prospeo)
    _log(
        f"After Prospeo: raw={len(prospeo_raw)} "
        f"merged={len(merged_after_prospeo)} "
        f"useful={useful_after_prospeo}"
    )

    if useful_after_prospeo >= TARGET and prospeo_stats.called and not prospeo_stats.error:
        _log(f"Target {TARGET} reached after Prospeo — skipping ContactOut")
        provider_stats["contactout"] = ProviderStats(called=False, skipped_reason="target_reached")
        result = _finalise(all_raw, domain, provider_stats, providers_used, TARGET, t0)
        _cache[cache_key] = result
        return result

    # ════════════════════════════════════════════════════════════════════════
    # STEP 3 — ContactOut
    # ════════════════════════════════════════════════════════════════════════
    _log("--- ContactOut ---")
    co_raw, co_stats = await _call_contactout(norm_name, domain)
    provider_stats["contactout"] = co_stats

    if co_stats.called and not co_stats.skipped_reason:
        providers_used.append("contactout")

    all_raw.extend(co_raw)
    _log(f"After ContactOut: raw={len(co_raw)} added")

    # ════════════════════════════════════════════════════════════════════════
    # STEP 4 — Hunter.io domain-search fallback
    # ════════════════════════════════════════════════════════════════════════
    # If none of PDL / Prospeo / ContactOut returned an email, try Hunter.
    # Hunter searches a company's domain for any known work emails and returns
    # real individual contacts (first_name, last_name, title, email).
    # This is especially effective for small/mid Indian companies.
    emails_so_far = sum(1 for c in all_raw if c.get("email"))
    if emails_so_far == 0 and domain:
        _log("--- Hunter.io fallback (no emails yet) ---")
        hunter_raw, hunter_stats = await _call_hunter(company_name, domain)
        provider_stats["hunter"] = hunter_stats
        if hunter_raw:
            providers_used.append("hunter")
            all_raw.extend(hunter_raw)
            _log(f"Hunter: added {len(hunter_raw)} contacts with email")
    else:
        provider_stats["hunter"] = ProviderStats(
            called=False,
            skipped_reason="emails_already_found" if emails_so_far > 0 else "no_domain",
        )

    # ════════════════════════════════════════════════════════════════════════
    # Finalise
    # ════════════════════════════════════════════════════════════════════════
    result = _finalise(all_raw, domain, provider_stats, providers_used, TARGET, t0)
    _cache[cache_key] = result
    return result


# ── Finalise helper ───────────────────────────────────────────────────────────

def _count_by_source(contacts: list[dict], source: str) -> int:
    """Count contacts that include `source` in their sources list."""
    return sum(1 for c in contacts if source in (c.get("sources") or []))


def _finalise(
    all_raw:        list[dict],
    domain:         Optional[str],
    provider_stats: dict[str, ProviderStats],
    providers_used: list[str],
    target:         int,
    t0:             float,
) -> PeopleEnrichmentResult:
    """
    Dedup → merge → rank → build PeopleEnrichmentResult with full stats.
    """
    merged  = dedup_and_merge(all_raw, domain)
    ranked  = rank_contacts(merged)

    emails_found      = sum(1 for c in ranked if c.get("email"))
    phones_found      = sum(1 for c in ranked if c.get("phone"))
    contacts_with_both = sum(1 for c in ranked if c.get("email") and c.get("phone"))
    useful_count      = count_useful(ranked)

    # Per-provider contact counts (a merged contact may credit multiple sources)
    pdl_contacts        = _count_by_source(ranked, "pdl")
    prospeo_contacts    = _count_by_source(ranked, "prospeo")
    contactout_contacts = _count_by_source(ranked, "contactout")

    elapsed = round(time.monotonic() - t0, 2)

    _log(
        f"COMPLETE — contacts={len(ranked)} useful={useful_count} "
        f"emails={emails_found} phones={phones_found} both={contacts_with_both} "
        f"pdl={pdl_contacts} prospeo={prospeo_contacts} contactout={contactout_contacts} "
        f"providers={providers_used} elapsed={elapsed}s"
    )

    # Detailed per-contact log
    for idx, ct in enumerate(ranked, 1):
        eflag = "email=YES" if ct.get("email") else "email=NO"
        pflag = "phone=YES" if ct.get("phone") else "phone=NO"
        src   = ",".join(ct.get("sources") or [])
        _log(
            f"  [{idx}] {ct.get('name','?')!r} | "
            f"{(ct.get('title') or '(no title)')!r} | "
            f"{eflag} | {pflag} | "
            f"conf={ct.get('confidence', 0):.3f} | "
            f"src={src}"
        )

    # Build clean ProviderStats (coerce duck-typed objects from tests)
    clean_stats: dict[str, ProviderStats] = {}
    for prov, ps in provider_stats.items():
        if isinstance(ps, ProviderStats):
            clean_stats[prov] = ps
        else:
            try:
                clean_stats[prov] = ProviderStats(
                    called         = bool(getattr(ps, "called", False)),
                    contacts_found = int(getattr(ps, "contacts_found", 0)),
                    emails_found   = int(getattr(ps, "emails_found", 0)),
                    phones_found   = int(getattr(ps, "phones_found", 0)),
                    api_calls      = int(getattr(ps, "api_calls", 0)),
                    error          = getattr(ps, "error", None) or None,
                    skipped_reason = getattr(ps, "skipped_reason", None) or None,
                )
            except Exception:
                clean_stats[prov] = ProviderStats()

    contacts_out = [
        EnrichedContact(
            name         = c.get("name"),
            title        = c.get("title"),
            email        = c.get("email"),
            phone        = c.get("phone"),
            linkedin_url = c.get("linkedin_url"),
            sources      = c.get("sources", []),
            confidence   = c.get("confidence", 0.0),
        )
        for c in ranked
    ]

    return PeopleEnrichmentResult(
        contacts            = contacts_out,
        contacts_found      = len(contacts_out),
        emails_found        = emails_found,
        phones_found        = phones_found,
        contacts_with_both  = contacts_with_both,
        pdl_contacts        = pdl_contacts,
        prospeo_contacts    = prospeo_contacts,
        contactout_contacts = contactout_contacts,
        providers_used      = providers_used,
        provider_stats      = clean_stats,
        target_contacts     = target,
        target_reached      = useful_count >= target,
        elapsed_seconds     = elapsed,
    )


# ── Batch entry point ─────────────────────────────────────────────────────────

async def batch_enrich_contacts(
    companies: list[dict],
) -> tuple[list[PeopleEnrichmentResult], PeopleEnrichmentBatchStats]:
    """
    Run enrich_company_contacts() for a list of company dicts.

    Each dict must have at minimum 'company_name'.
    Optional keys: 'domain', 'website'.

    Returns:
        (results, batch_stats)
        results:     one PeopleEnrichmentResult per input company
        batch_stats: aggregated PeopleEnrichmentBatchStats

    Clears the per-run cache before starting.
    Never raises — errors are captured per company.
    """
    reset_cache()
    t0 = time.monotonic()

    results: list[PeopleEnrichmentResult] = []
    batch_stats = PeopleEnrichmentBatchStats()
    batch_stats.companies_processed = len(companies)

    provider_failure_counts: dict[str, int] = {}

    for i, company in enumerate(companies, 1):
        name    = company.get("company_name") or company.get("name") or f"Company_{i}"
        domain  = company.get("domain")
        website = company.get("website")

        _log(f"[{i}/{len(companies)}] Processing: {name!r}")

        try:
            result = await enrich_company_contacts(
                company_name=name,
                domain=domain,
                website=website,
            )
        except Exception as exc:
            _log(f"[{i}/{len(companies)}] Unexpected error for {name!r}: {exc}")
            result = PeopleEnrichmentResult(
                error=f"{type(exc).__name__}: {exc}",
                target_contacts=_target(),
            )

        results.append(result)

        # Accumulate stats
        if result.contacts_found > 0:
            batch_stats.companies_with_contacts += 1

        batch_stats.total_contacts        += result.contacts_found
        batch_stats.contacts_with_email   += result.emails_found
        batch_stats.contacts_with_phone   += result.phones_found
        batch_stats.contacts_with_both    += result.contacts_with_both
        batch_stats.pdl_contacts          += result.pdl_contacts
        batch_stats.prospeo_contacts      += result.prospeo_contacts
        batch_stats.contactout_contacts   += result.contactout_contacts

        # Count provider failures
        for prov, ps in result.provider_stats.items():
            if ps.error and ps.error not in ("target_reached",):
                provider_failure_counts[prov] = provider_failure_counts.get(prov, 0) + 1

    batch_stats.provider_failures = provider_failure_counts
    batch_stats.elapsed_seconds   = round(time.monotonic() - t0, 2)

    # Print batch summary
    _log("═" * 60)
    _log("BATCH COMPLETE")
    _log(f"  companies_processed     : {batch_stats.companies_processed}")
    _log(f"  companies_with_contacts : {batch_stats.companies_with_contacts}")
    _log(f"  total_contacts          : {batch_stats.total_contacts}")
    _log(f"  contacts_with_email     : {batch_stats.contacts_with_email}")
    _log(f"  contacts_with_phone     : {batch_stats.contacts_with_phone}")
    _log(f"  contacts_with_both      : {batch_stats.contacts_with_both}")
    _log(f"  pdl_contacts            : {batch_stats.pdl_contacts}")
    _log(f"  prospeo_contacts        : {batch_stats.prospeo_contacts}")
    _log(f"  contactout_contacts     : {batch_stats.contactout_contacts}")
    _log(f"  provider_failures       : {batch_stats.provider_failures}")
    _log(f"  elapsed_seconds         : {batch_stats.elapsed_seconds}")
    _log("═" * 60)

    return results, batch_stats
