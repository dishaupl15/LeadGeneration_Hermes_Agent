"""
reddit/enrichment.py
─────────────────────
People-enrichment adapter for Reddit-sourced leads.

Connects Reddit leads to the EXISTING people_enrichment orchestrator
(PDL → Prospeo → ContactOut → Hunter waterfall) — the exact same pipeline
used by the Google Maps flow.

Design contract
───────────────
  ✅ Reuses  people_enrichment.orchestrator.enrich_company_contacts
     directly — no duplicate enrichment logic here.
  ✅ Preserves all existing Reddit/post source fields
     (post_id, post_url, subreddit, reddit_author, source="reddit", …).
  ✅ Never overwrites valid existing data with null/empty values.
  ✅ Never raises — all provider failures are captured and logged.
  ✅ One enrichment failure never aborts the batch.

Isolation
─────────
  ✅ Imports ONLY from:
       people_enrichment.orchestrator  (enrich_company_contacts, reset_cache)
       people_enrichment.schemas       (PeopleEnrichmentResult)
       standard library
  🚫 Does NOT import from:
       Any Reddit-specific schema or search module

Usage (from src/routes/leads.py)
─────────────────────────────────
  from reddit.enrichment import enrich_reddit_leads_batch

  enriched_docs = await enrich_reddit_leads_batch(lead_docs, log_fn=_log)

  Each element of enriched_docs is the original lead dict with enrichment
  fields merged in (contacts, email, emails, founder_name, founder_number,
  confidence, people_enrichment_stats).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import urlparse

# Module-level import so patch("reddit.enrichment.enrich_company_contacts") works in tests.
# The orchestrator is the single entry point for the PDL → Prospeo → ContactOut → Hunter
# waterfall — the same function used by the Google Maps pipeline.
from people_enrichment.orchestrator import enrich_company_contacts, reset_cache as _reset_orchestrator_cache


# ── Logging ───────────────────────────────────────────────────────────────────

def _default_log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [REDDIT_ENRICH] {msg}", flush=True)


# ── Domain normalisation (local copy — no external pipeline imports) ──────────

def _normalise_domain(value: Optional[str]) -> Optional[str]:
    """Return bare domain from a URL/domain string, or None."""
    if not value:
        return None
    v = value.strip().lower()
    if not v.startswith("http"):
        v = "https://" + v
    try:
        netloc = urlparse(v).netloc
        bare = netloc.lstrip("www.").split(":")[0].strip()
        return bare or None
    except Exception:
        return value.lower().strip() or None


# ── Reddit source field preservation ──────────────────────────────────────────

_REDDIT_SOURCE_FIELDS = frozenset({
    "source", "platform", "research_source",
    "post_id", "post_title", "post_text", "post_url",
    "subreddit", "reddit_author", "post_score",
    "search_keywords", "search_location", "research_sources",
    "source_url",
})


def _merge_enrichment_into_lead(lead: dict, result) -> dict:
    """
    Merge a PeopleEnrichmentResult into a Reddit lead document.

    Rules (mirror of _enrich_via_people_orchestrator in the Google Maps pipeline):
      - Never overwrite a field that already has a non-empty value.
      - Always preserve every Reddit source field.
      - Serialise contacts to plain dicts for MongoDB storage.
      - Promote first contact email → company email when company has none.
      - Promote first contact phone → founder_number when not already set.
      - Update confidence score using a simple weighted formula.

    Returns the mutated lead dict (same object).
    """
    company_name = lead.get("company_name", "?")

    # Serialise contacts to plain dicts
    contacts_list: list[dict] = []
    for c in result.contacts:
        contacts_list.append({
            "name":         c.name,
            "title":        c.title,
            "email":        c.email,
            "phone":        c.phone,
            "linkedin_url": c.linkedin_url,
            "sources":      list(c.sources),
            "confidence":   c.confidence,
        })

    lead["contacts"] = contacts_list

    # ── Promote best contact email → company-level email (only when absent) ──
    if not lead.get("email"):
        for ct in contacts_list:
            if ct.get("email"):
                lead["email"] = ct["email"]
                # Keep in emails list for backward compat
                emails = list(lead.get("emails") or [])
                if ct["email"] not in emails:
                    emails.insert(0, ct["email"])
                lead["emails"] = emails
                # Field-verification record
                fv = dict(lead.get("_field_verification") or {})
                fv["email"] = {
                    "value":    ct["email"],
                    "verified": True,
                    "status":   f"people_enrichment_{','.join(ct.get('sources', ['unknown']))}",
                    "source":   "people_enrichment",
                }
                lead["_field_verification"] = fv
                break

    # ── Promote best contact phone → founder_number (only when absent) ───────
    if not lead.get("founder_number"):
        for ct in contacts_list:
            if ct.get("phone") and ct.get("name") and ct.get("email"):
                lead["founder_number"] = ct["phone"]
                if not lead.get("founder_name"):
                    lead["founder_name"] = ct["name"]
                break

    # ── Boost confidence when enrichment found contacts ───────────────────────
    # Reddit leads start with a low relevance-based confidence (0.15–1.0).
    # Bump it slightly when the waterfall returned useful contacts.
    if result.contacts_found > 0:
        existing = float(lead.get("confidence") or 0.0)
        boost = min(0.15 * result.contacts_found, 0.30)
        lead["confidence"] = round(min(existing + boost, 1.0), 2)

    # ── Store enrichment stats on the document (for audit/debugging) ─────────
    lead["people_enrichment_stats"] = {
        "contacts_found":    result.contacts_found,
        "emails_found":      result.emails_found,
        "phones_found":      result.phones_found,
        "providers_used":    result.providers_used,
        "target_reached":    result.target_reached,
        "elapsed_seconds":   result.elapsed_seconds,
        "error":             result.error,
    }

    # ── Guarantee Reddit source fields are not touched ────────────────────────
    # (They were in the dict before this function — this is a safety assertion.)
    lead["source"]   = "reddit"
    lead["platform"] = "reddit"
    lead["research_source"] = "reddit"

    return lead


# ── Single-company enrichment ──────────────────────────────────────────────────

async def enrich_one_reddit_lead(
    lead: dict,
    log: Callable[[str], None] = _default_log,
) -> dict:
    """
    Run the people-enrichment waterfall (PDL → Prospeo → ContactOut → Hunter)
    for a single Reddit lead document.

    Parameters
    ──────────
    lead : dict
        A Reddit lead document as stored in MongoDB.
        Must contain at least 'company_name'.
        Optionally contains 'website' and/or 'email'.

    Returns
    ───────
    The mutated lead dict with enrichment fields merged in.
    Never raises.
    """
    company_name = (lead.get("company_name") or "").strip()
    if not company_name:
        log("Skipping lead with no company_name")
        return lead

    website = (lead.get("website") or "").strip()
    domain  = _normalise_domain(website) if website else None

    log(f"Enriching Reddit lead: {company_name!r} domain={domain!r}")

    try:
        result = await enrich_company_contacts(
            company_name=company_name,
            domain=domain or None,
            website=website or None,
            origami_contacts=None,  # Reddit leads have no Origami pre-seed
        )
    except Exception as exc:
        log(f"Orchestrator error for {company_name!r} — {type(exc).__name__}: {exc}")
        # Return lead unchanged — enrichment failure is non-fatal
        return lead

    _merge_enrichment_into_lead(lead, result)
    log(
        f"{company_name!r} — "
        f"contacts={result.contacts_found} "
        f"emails={result.emails_found} "
        f"providers={result.providers_used} "
        f"elapsed={result.elapsed_seconds:.1f}s"
    )
    return lead


# ── Batch enrichment (concurrent, with per-company timeout) ───────────────────

async def enrich_reddit_leads_batch(
    leads: list[dict],
    max_concurrency: int = 3,
    per_lead_timeout: float = 60.0,
    log: Callable[[str], None] = _default_log,
) -> tuple[list[dict], dict]:
    """
    Enrich a list of Reddit lead documents concurrently.

    Uses the same concurrency pattern as the Google Maps pipeline:
      - asyncio.Semaphore to cap simultaneous provider calls
      - Per-lead timeout to avoid hanging on slow providers
      - Any individual failure is caught and logged; the batch continues

    Parameters
    ──────────
    leads           : list of lead dicts (already saved to MongoDB)
    max_concurrency : max simultaneous enrichment calls (default 3)
    per_lead_timeout: seconds before a single-lead enrichment is abandoned
    log             : logging callable

    Returns
    ───────
    (enriched_leads, batch_stats)
      enriched_leads : same list with enrichment fields merged in
      batch_stats    : summary dict for history/logging
    """
    if not leads:
        return [], {
            "total": 0, "enriched": 0, "failed": 0,
            "contacts_found": 0, "emails_found": 0, "elapsed_seconds": 0.0,
        }

    t0  = time.monotonic()
    sem = asyncio.Semaphore(max_concurrency)

    # Reset the orchestrator cache so each Reddit run starts fresh
    try:
        _reset_orchestrator_cache()
    except Exception as _rc_exc:
        log(f"Cache reset warning (non-fatal): {_rc_exc}")

    total_contacts = 0
    total_emails   = 0
    enriched_count = 0
    failed_count   = 0

    async def _enrich_with_semaphore(lead: dict) -> dict:
        async with sem:
            try:
                return await asyncio.wait_for(
                    enrich_one_reddit_lead(lead, log=log),
                    timeout=per_lead_timeout,
                )
            except asyncio.TimeoutError:
                log(f"Enrichment timeout for {lead.get('company_name','?')!r}")
                return lead
            except Exception as exc:
                log(f"Enrichment error for {lead.get('company_name','?')!r}: {exc}")
                return lead

    results = await asyncio.gather(
        *[_enrich_with_semaphore(lead) for lead in leads],
        return_exceptions=True,
    )

    enriched_leads: list[dict] = []
    for original, result in zip(leads, results):
        if isinstance(result, Exception):
            log(f"gather error for {original.get('company_name','?')!r}: {result}")
            enriched_leads.append(original)
            failed_count += 1
        else:
            enriched_leads.append(result)
            stats = result.get("people_enrichment_stats") or {}
            if stats.get("contacts_found", 0) > 0:
                enriched_count += 1
            elif stats.get("error") and stats.get("contacts_found", 0) == 0:
                failed_count += 1
            total_contacts += stats.get("contacts_found", 0)
            total_emails   += stats.get("emails_found", 0)

    elapsed = round(time.monotonic() - t0, 2)
    batch_stats = {
        "total":            len(leads),
        "enriched":         enriched_count,
        "failed":           failed_count,
        "contacts_found":   total_contacts,
        "emails_found":     total_emails,
        "elapsed_seconds":  elapsed,
    }
    log(
        f"Batch complete — total={len(leads)} enriched={enriched_count} "
        f"failed={failed_count} contacts={total_contacts} emails={total_emails} "
        f"elapsed={elapsed}s"
    )
    return enriched_leads, batch_stats
