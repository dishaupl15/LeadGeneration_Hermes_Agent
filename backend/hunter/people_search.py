"""
hunter/people_search.py
────────────────────────
Hunter.io people-search adapter for the people-enrichment orchestrator.

Two modes:
  1. email_finder_for_contact(domain, first_name, last_name)
       Calls GET /v2/email-finder — use when you already have a person's name
       but need their work email (e.g. from Origami name-only contacts).

  2. search_contacts(company_name, domain)
       Calls GET /v2/domain-search — use as a domain-wide fallback when no
       other provider returned any emails.

Both return a HunterResult with contacts, stat counters, and an error code.

Isolation contract:
  ✅ Imports only from hunter/* + stdlib + httpx + pydantic
  🚫 Does NOT import from app/services/, google_maps/, src/*, or other modules
"""
from __future__ import annotations

import re
from typing import Optional

from hunter.client import domain_search, email_finder, domain_matches, is_valid_email
from hunter.config import is_configured
from hunter.schemas import HunterContact, HunterResult


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [HUNTER] {msg}", flush=True)


def _hunter_confidence(score: int) -> float:
    return round(min(max(score, 0), 100) / 100, 2)


# ── Mode 1: email-finder for a named contact ──────────────────────────────────

async def email_finder_for_contact(
    domain: str,
    first_name: str,
    last_name: str,
    title: Optional[str] = None,
) -> HunterResult:
    """
    Call /email-finder for a specific person.

    Use when you have a person's name (e.g. from Origami) but no email.
    Returns a HunterResult with at most one contact.

    Never raises — all errors are captured in HunterResult.error.
    """
    result = HunterResult(calls=1)

    if not is_configured():
        result.error          = "not_configured"
        result.skipped_reason = "not_configured"
        result.calls          = 0
        _log("Skipped — HUNTER_API_KEY not set")
        return result

    if not domain:
        result.error          = "no_domain"
        result.skipped_reason = "no_domain"
        result.calls          = 0
        return result

    contact_data, err = await email_finder(domain, first_name, last_name)
    if err == "no_result":
        result.no_result = 1
        _log(f"email-finder no result for {first_name} {last_name} @ {domain!r}")
        return result

    if err:
        result.error  = err
        result.failed = 1
        _log(f"email-finder failed for {first_name} {last_name} @ {domain!r}: {err}")
        return result

    # Success
    email = contact_data["email"]
    score = contact_data["score"]
    name  = f"{contact_data.get('first_name', '')} {contact_data.get('last_name', '')}".strip()

    contact = HunterContact(
        name=name or None,
        first_name=contact_data.get("first_name") or None,
        last_name=contact_data.get("last_name") or None,
        title=title,
        email=email,
        email_score=score,
        confidence=_hunter_confidence(score),
        sources=["hunter"],
    )

    result.contacts       = [contact]
    result.contacts_found = 1
    result.emails_found   = 1
    result.success        = 1
    _log(f"email-finder SUCCESS {email!r} score={score} name={name!r}")
    return result


# ── Mode 2: domain-search for a company ───────────────────────────────────────

async def search_contacts(
    company_name: str,
    domain: Optional[str],
) -> HunterResult:
    """
    Call /domain-search to find all known emails at a company's domain.

    This is the orchestrator integration point — mirrors the interface of
    prospeo/people_search.py::search_contacts() and
    contactout/people_search.py::search_contacts().

    Returns a HunterResult.
    Never raises — all errors are captured in HunterResult.error.
    """
    result = HunterResult(calls=1)

    if not is_configured():
        result.error          = "not_configured"
        result.skipped_reason = "not_configured"
        result.calls          = 0
        _log(f"Skipped for {company_name!r} — HUNTER_API_KEY not set")
        return result

    if not domain:
        result.error          = "no_domain"
        result.skipped_reason = "no_domain"
        result.calls          = 0
        _log(f"Skipped for {company_name!r} — no domain")
        return result

    _log(f"domain-search for company={company_name!r} domain={domain!r}")
    contacts_raw, err = await domain_search(domain)

    if err == "no_result" or (err is None and not contacts_raw):
        result.no_result = 1
        _log(f"domain-search no results for {domain!r}")
        return result

    if err:
        result.error  = err
        result.failed = 1
        _log(f"domain-search failed for {domain!r}: {err}")
        return result

    # Convert raw dicts → HunterContact
    contacts: list[HunterContact] = []
    for c in contacts_raw:
        email = c.get("email") or ""
        if not email or not is_valid_email(email):
            continue
        score = int(c.get("score") or 0)
        contacts.append(HunterContact(
            name=c.get("name"),
            first_name=c.get("first_name"),
            last_name=c.get("last_name"),
            title=c.get("title"),
            email=email,
            email_score=score,
            confidence=_hunter_confidence(score),
            sources=["hunter"],
        ))

    if not contacts:
        result.no_result = 1
        _log(f"domain-search returned entries but all were filtered (junk/domain-mismatch) for {domain!r}")
        return result

    result.contacts       = contacts
    result.contacts_found = len(contacts)
    result.emails_found   = len(contacts)
    result.success        = 1
    _log(
        f"domain-search SUCCESS for {domain!r}: "
        f"{len(contacts)} valid contacts"
    )
    return result
