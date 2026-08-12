"""
people_data_labs/people_search.py
───────────────────────────────────
Core orchestration: company input → up to 2 ranked PDL contacts.

Strategy (cost-safe — max 2 PDL API calls per company)
────────────────────────────────────────────────────────
Search 1 (Tier A — executive):
  job_title_levels = ["founder", "c_suite", "owner", "partner", "director"]
  → Founder / Co-Founder / Owner / CEO / MD / Director

Search 2 (Tier B — HR/talent, only if fewer than 2 contacts from Search 1):
  job_title_levels = ["vp", "manager", "senior"]
  → Head of HR / Talent Acquisition / HR Manager / Recruiter

Stop when 2 suitable contacts are found.
Stop immediately if PDL returns auth_failed (401).

Isolation
─────────
Only imports from people_data_labs/ and stdlib.
Does NOT import from google_maps/, app/services/, or src/.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from people_data_labs.client import person_search, is_credits_exhausted, reset_credits_flag
from people_data_labs.config import (
    PDL_MAX_CONTACTS_PER_COMPANY,
    PDL_SEARCH_PAGE_SIZE,
    is_configured,
    key_length,
)
from people_data_labs.contact_mapper import map_person_to_contact
from people_data_labs.schemas import PeopleDataLabsContact, PeopleDataLabsResult


# ── Logger ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [PDL] {msg}", flush=True)


# ── Domain normalisation ──────────────────────────────────────────────────────

def _normalise_domain(value: Optional[str]) -> str:
    """Strip scheme and www-prefix to get a bare domain, e.g. 'example.com'."""
    if not value:
        return ""
    v = value.strip().lower()
    if not v.startswith("http"):
        v = "https://" + v
    try:
        netloc = urlparse(v).netloc
        return netloc.lstrip("www.").split(":")[0].strip()
    except Exception:
        return value.lower().strip()


# ── PDL fields we actually need (keeps responses small) ──────────────────────
_DATA_INCLUDE = (
    "id,full_name,first_name,last_name,"
    "job_title,job_title_role,job_title_sub_role,job_title_levels,"
    "job_company_name,job_company_website,"
    "work_email,emails,phone_numbers,"
    "linkedin_url,profiles"
)

# ── Search tiers (2 tiers maximum) ───────────────────────────────────────────
#   Tier A: executive/owner roles — always run first
#   Tier B: HR/talent roles      — only run if Tier A < PDL_MAX_CONTACTS_PER_COMPANY
_TIERS: list[tuple[str, list[str]]] = [
    (
        "executive",
        ["founder", "c_suite", "owner", "partner", "director"],
    ),
    (
        "hr_talent",
        ["vp", "manager", "senior"],
    ),
]

# Role priority order for final sort (lower = higher priority)
_ROLE_ORDER: dict[str, int] = {
    "founder":            0,
    "co_founder":         1,
    "owner":              2,
    "ceo":                3,
    "managing_director":  4,
    "director":           5,
    "hr":                 6,
    "talent_acquisition": 7,
    "recruitment":        8,
    "other":              9,
}


# ── Query builder ─────────────────────────────────────────────────────────────

def _build_query(domain: str, company_name: str, levels: list[str]) -> dict:
    """
    Build a PDL Elasticsearch query.
    Prefers domain-based company matching (precise); falls back to name match.
    """
    company_clause: dict
    if domain:
        company_clause = {"term": {"job_company_website": domain}}
    else:
        company_clause = {"match": {"job_company_name": company_name}}

    must: list[dict] = [company_clause]
    if levels:
        must.append({"terms": {"job_title_levels": levels}})

    return {"bool": {"must": must}}


# ── Main entry point ──────────────────────────────────────────────────────────

async def search_company_contacts(
    company_name: str,
    domain: Optional[str] = None,
    website: Optional[str] = None,
) -> PeopleDataLabsResult:
    """
    Search PDL for up to PDL_MAX_CONTACTS_PER_COMPANY decision-makers.

    Args:
        company_name: Required.
        domain:       Bare domain e.g. "example.com" (preferred over name match).
        website:      Full URL — domain is extracted when domain is absent.

    Returns:
        PeopleDataLabsResult.
        On auth failure: result.error = "auth_failed" and contacts = [].
    """
    t0 = time.monotonic()

    _log("Request started")
    _log(f"company={company_name!r}")

    effective_domain = _normalise_domain(domain or website or "")
    _log(f"domain={effective_domain or '(none — using name match)'!r}")

    # ── Guard: key not configured ─────────────────────────────────────────────
    if not is_configured():
        _log(f"API key not configured (key_length={key_length()}) — skipping")
        return PeopleDataLabsResult(
            company_name=company_name,
            company_domain=effective_domain or None,
            error="PDL_API_KEY not configured",
        )

    _log(f"authentication=key_present key_length={key_length()}")

    # ── Per-run dedup stores ──────────────────────────────────────────────────
    seen_emails: set[str] = set()
    seen_names:  set[str] = set()
    accepted:    list[dict] = []
    api_calls    = 0
    total_raw    = 0
    auth_failed  = False

    # ── Tiered search (max 2 tiers) ───────────────────────────────────────────
    max_contacts = PDL_MAX_CONTACTS_PER_COMPANY  # env: PDL_MAX_CONTACTS_PER_COMPANY

    for tier_name, levels in _TIERS:
        if len(accepted) >= max_contacts:
            _log(f"tier={tier_name} skipped — already have {len(accepted)}/{max_contacts} contacts")
            break

        # Skip immediately if credits were exhausted in a previous tier
        if is_credits_exhausted():
            _log(f"tier={tier_name} skipped — PDL credits exhausted (402 received earlier)")
            break

        query = _build_query(effective_domain, company_name, levels)
        _log(f"tier={tier_name} levels={levels} searching ...")

        data, auth_failed_now, _ = await person_search(
            query,
            size=PDL_SEARCH_PAGE_SIZE,
            data_include=_DATA_INCLUDE,
        )
        api_calls += 1

        if auth_failed_now:
            # Auth failed — stop all further PDL requests for this run
            auth_failed = True
            _log("authentication=FAILED — stopping PDL for this pipeline run")
            break

        total_raw += len(data)
        _log(f"tier={tier_name} raw_people={len(data)}")

        for person in data:
            if len(accepted) >= max_contacts:
                break

            contact = map_person_to_contact(person, company_name, effective_domain)
            if contact is None:
                continue

            # Deduplicate by email, fallback to name
            email = (contact.get("email") or "").lower().strip()
            if email:
                if email in seen_emails:
                    continue
                seen_emails.add(email)
            else:
                name_key = (contact.get("name") or "").lower().strip()
                if name_key and name_key in seen_names:
                    continue
                if name_key:
                    seen_names.add(name_key)

            accepted.append(contact)

    # Early return when credits are exhausted (402) — no need to process empty results
    if is_credits_exhausted():
        elapsed = round(time.monotonic() - t0, 2)
        _log("PDL credits exhausted — returning no_credits result immediately")
        return PeopleDataLabsResult(
            company_name=company_name,
            company_domain=effective_domain or None,
            contacts=[],
            contacts_found=0,
            emails_found=0,
            pdl_api_calls=api_calls,
            elapsed_seconds=elapsed,
            error="no_credits",
        )

    if auth_failed:
        elapsed = round(time.monotonic() - t0, 2)
        return PeopleDataLabsResult(
            company_name=company_name,
            company_domain=effective_domain or None,
            contacts=[],
            contacts_found=0,
            emails_found=0,
            pdl_api_calls=api_calls,
            elapsed_seconds=elapsed,
            error="auth_failed",
        )

    # ── Sort: confidence (desc) then role priority ────────────────────────────
    accepted.sort(
        key=lambda c: (
            -c["confidence"],
            _ROLE_ORDER.get(c.get("email_type", "other"), 9),
        )
    )

    contacts_out = [PeopleDataLabsContact(**c) for c in accepted]
    emails_found = sum(1 for c in contacts_out if c.email)
    phones_found = sum(1 for c in contacts_out if c.phone)

    elapsed = round(time.monotonic() - t0, 2)

    # ── Summary log ───────────────────────────────────────────────────────────
    _log(f"raw_people={total_raw}")
    _log(f"contacts_with_email={emails_found}")
    for idx, ct in enumerate(contacts_out, 1):
        email_flag = "email=YES" if ct.email else "email=NO"
        phone_flag = "phone=YES" if ct.phone else "phone=NO"
        _log(
            f"Contact {idx}: {ct.name or '?'} | "
            f"{ct.designation or '?'} | "
            f"{email_flag} | {phone_flag}"
        )
    _log(
        f"COMPLETE — contacts={len(contacts_out)} "
        f"emails={emails_found} "
        f"phones={phones_found} "
        f"api_calls={api_calls} "
        f"elapsed={elapsed}s"
    )

    return PeopleDataLabsResult(
        company_name=company_name,
        company_domain=effective_domain or None,
        contacts=contacts_out,
        contacts_found=len(contacts_out),
        emails_found=emails_found,
        phones_found=phones_found,
        pdl_api_calls=api_calls,
        elapsed_seconds=elapsed,
    )
