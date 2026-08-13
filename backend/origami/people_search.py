"""
origami/people_search.py
─────────────────────────
Business logic layer for Origami contact search.

Responsibilities
────────────────
  - Call client.call_origami_api()
  - Sort contacts by tier then confidence
  - Derive founder_status from best contact tier
  - Build the OrigamiSearchResult response

Isolation
─────────
  Only imports from: origami/client.py, origami/schemas.py, origami/config.py
"""
from __future__ import annotations

import time
from typing import Optional

from origami.client import call_origami_api, sort_contacts, title_tier
from origami.config import is_configured
from origami.schemas import OrigamiContact, OrigamiSearchResult


async def search_company_contacts(
    company_name: str,
    domain: Optional[str] = None,
    website: Optional[str] = None,
    location: Optional[str] = None,
    category: Optional[str] = None,
) -> OrigamiSearchResult:
    """
    Find decision-maker contacts for a company via the Origami API.

    Returns an OrigamiSearchResult.  Never raises.

    Contact priority (Tier 1 highest):
      Tier 1 — Founder / Owner / Co-founder / Proprietor
      Tier 2 — CEO / President / Managing Director / Chairman
      Tier 3 — COO / CFO / CTO / CMO / Director / VP
      Tier 4 — Head of / GM / Country Head / Regional Head
      Tier 5 — Other employees
    """
    if not is_configured():
        return OrigamiSearchResult(
            success=False,
            company_name=company_name,
            founder_status="skipped",
            error="no_key",
        )

    t0 = time.monotonic()

    raw_contacts, error_code = await call_origami_api(
        company_name=company_name,
        domain=domain,
        website=website,
        location=location,
        category=category,
    )

    elapsed = round(time.monotonic() - t0, 2)

    if error_code and error_code not in ("not_found",):
        return OrigamiSearchResult(
            success=False,
            company_name=company_name,
            founder_status="error",
            elapsed_seconds=elapsed,
            error=error_code,
        )

    if not raw_contacts:
        return OrigamiSearchResult(
            success=True,
            company_name=company_name,
            founder_status="not_found",
            elapsed_seconds=elapsed,
        )

    sorted_raw = sort_contacts(raw_contacts)
    top_tier   = title_tier(sorted_raw[0].get("title"))

    # Derive founder_status
    if top_tier == 1:
        founder_status = "found"
    elif top_tier <= 3:
        founder_status = "found_decision_maker"
    else:
        founder_status = "not_found"

    contacts = [
        OrigamiContact(
            name         = c.get("name"),
            title        = c.get("title"),
            tier         = c.get("tier", 5),
            tier_label   = c.get("tier_label", "Other"),
            email        = c.get("email"),
            phone        = c.get("phone"),
            linkedin_url = c.get("linkedin_url"),
            confidence   = c.get("confidence", 0.65),
        )
        for c in sorted_raw
    ]

    emails_found = sum(1 for c in contacts if c.email)
    phones_found = sum(1 for c in contacts if c.phone)

    return OrigamiSearchResult(
        success        = True,
        company_name   = company_name,
        contacts       = contacts,
        contacts_found = len(contacts),
        emails_found   = emails_found,
        phones_found   = phones_found,
        founder_status = founder_status,
        elapsed_seconds= elapsed,
    )
