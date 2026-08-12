"""
prospeo/people_search.py
─────────────────────────
Core orchestration: company input → up to N ranked Prospeo contacts.

Two-step workflow
─────────────────
Step 1 — Search Person (/search-person)
  Three-tier search with fallback:
    Tier A (exec): Founder/Owner, C-Suite, Vice President, Director, Head, Partner
    Tier B (mgr):  Manager  (only if Tier A < max_contacts)
    Fallback:      no seniority filter (only if both tiers returned 0)
  Map each result through contact_mapper.map_search_result().
  Rank by role priority + match strength.
  Take the top PROSPEO_MAX_CONTACTS_PER_COMPANY candidates.

Step 2 — Bulk Enrich Person (/bulk-enrich-person)
  Submit the selected person_ids.
  Extract revealed email + mobile.
  Re-score confidence with email availability.
  Return final normalised contacts.

Valid Prospeo seniority values (verified by live API probe)
────────────────────────────────────────────────────────────
  VALID:   "Founder/Owner", "C-Suite", "Vice President", "Director",
           "Head", "Partner", "Manager", "Senior"
  INVALID: "VP" (400 INVALID_FILTERS), "Chairman", "President",
           "Executive", "Lead"

  "VP" has been replaced with "Vice President".

Isolation
─────────
  Imports ONLY from prospeo/ and stdlib.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from prospeo.client import bulk_enrich_person, search_person
from prospeo.config import (
    PROSPEO_MAX_CONTACTS_PER_COMPANY,
    PROSPEO_SEARCH_PAGE_SIZE,
    is_configured,
    key_length,
)
from prospeo.contact_mapper import (
    ROLE_PRIORITY,
    map_enriched_result,
    map_search_result,
)
from prospeo.schemas import ProspeoContact, ProspeoSearchResult


# ── Logger ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [PROSPEO] {msg}", flush=True)


# ── Domain normalisation ──────────────────────────────────────────────────────

def _normalise_domain(value: Optional[str]) -> str:
    """Return a bare domain, e.g. 'intercom.com'."""
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


# ── Confirmed-valid Prospeo seniority values ──────────────────────────────────
# Verified by live API probe (HTTP 200 = valid, HTTP 400 INVALID_FILTERS = bad).
#
#  VALID:   Founder/Owner, C-Suite, Vice President, Director, Head, Partner,
#           Manager, Senior
#  INVALID: VP (was causing 400), Chairman, President, Executive, Lead, VP Level

_TIER_A_SENIORITIES: list[str] = [
    "Founder/Owner",   # Founders, owners
    "C-Suite",         # CEO, COO, CFO, CTO, etc.
    "Vice President",  # VP-level (NOT "VP" — that 400s the whole request)
    "Director",        # Directors at all levels
    "Head",            # Head of HR, Head of Talent, etc.
    "Partner",         # Managing Partners
]

_TIER_B_SENIORITIES: list[str] = [
    "Manager",         # HR Manager, Talent Acquisition Manager, etc.
]


# ── Search-filter builder ─────────────────────────────────────────────────────

def _build_filters(
    domain: str,
    company_name: str,
    seniorities: list[str] | None = None,
) -> dict:
    """
    Build Prospeo /search-person filters.
    seniorities=None → no seniority filter (fallback mode).
    """
    company_filter: dict = (
        {"websites": {"include": [domain]}} if domain
        else {"names":    {"include": [company_name]}}
    )
    filters: dict = {"company": company_filter}
    if seniorities:
        filters["person_seniority"] = {"include": seniorities}
    return filters


# ── Core search helper ────────────────────────────────────────────────────────

async def _do_search(
    domain: str,
    company_name: str,
    seniorities: list[str] | None,
    label: str,
) -> tuple[list[dict], int, str | None]:
    """
    Call /search-person with the given seniorities.
    Logs request parameters and full response stats.
    """
    filters = _build_filters(domain, company_name, seniorities)
    _log(
        f"{label} request — "
        f"domain={domain or company_name!r} "
        f"seniorities={seniorities if seniorities is not None else '(no filter)'}"
    )
    results, total, err = await search_person(filters, page=1)
    _log(
        f"{label} response — "
        f"HTTP={'200' if err is None else ('no_results(200)' if err == 'no_results' else 'non-200')} "
        f"profiles_returned={len(results)} "
        f"total_in_index={total} "
        f"error={err!r}"
    )
    return results, total, err


# ── Internal: map raw results → candidate dicts (deduped by person_id) ───────

def _map_candidates(
    results: list[dict],
    domain: str,
    company_name: str,
) -> list[dict]:
    """Map raw /search-person results through contact_mapper, dedup by person_id."""
    seen_ids:   set[str]   = set()
    candidates: list[dict] = []
    for res in results[:PROSPEO_SEARCH_PAGE_SIZE * 3]:
        cand = map_search_result(res, domain, company_name)
        if not cand:
            continue
        pid = cand.get("person_id", "")
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        candidates.append(cand)
    return candidates


# ── Main entry point ──────────────────────────────────────────────────────────

async def search_contacts(
    company_name: str,
    domain: Optional[str] = None,
    website: Optional[str] = None,
    max_contacts: int = PROSPEO_MAX_CONTACTS_PER_COMPANY,
) -> ProspeoSearchResult:
    """
    Find up to `max_contacts` decision-makers at the given company via Prospeo.

    Three-tier search (stops as soon as enough candidates found):
      Tier A — execs:    Founder/Owner, C-Suite, Vice President, Director, Head, Partner
      Tier B — managers: Manager  (only if Tier A < max_contacts)
      Fallback:          no seniority filter (only if both tiers return 0 candidates)

    Returns ProspeoSearchResult.
    On auth failure: .error = "auth_failed", .contacts = [].
    """
    t0 = time.monotonic()
    max_contacts = max(1, max_contacts)

    _log(f"=== Company: {company_name!r} ===")

    effective_domain = _normalise_domain(domain or website or "")
    _log(f"Effective domain: {effective_domain or '(none — using name match)'!r}")
    _log(f"Max contacts requested: {max_contacts}")

    if not is_configured():
        _log(f"API key not configured (key_length={key_length()}) — skipping")
        return ProspeoSearchResult(
            success=False,
            company_name=company_name,
            company_domain=effective_domain or None,
            error="PROSPEO_API_KEY not configured",
        )

    api_calls = 0
    credits   = 0
    all_results: list[dict] = []

    # ── Tier A: executives ───────────────────────────────────────────────────
    results_a, _total_a, err_a = await _do_search(
        effective_domain, company_name, _TIER_A_SENIORITIES, "Tier-A(exec)"
    )
    api_calls += 1

    if err_a == "auth_failed":
        return ProspeoSearchResult(
            success=False, company_name=company_name,
            company_domain=effective_domain or None,
            api_calls=api_calls,
            elapsed_seconds=round(time.monotonic() - t0, 2),
            error="auth_failed",
        )

    if err_a in ("no_credits", "plan_required"):
        _log(f"Prospeo credits/plan issue ({err_a!r}) — stopping")
        return ProspeoSearchResult(
            success=False, company_name=company_name,
            company_domain=effective_domain or None,
            api_calls=api_calls,
            elapsed_seconds=round(time.monotonic() - t0, 2),
            error=err_a,
        )

    # Track if ALL tiers were rate-limited (so we can propagate the error)
    _all_rate_limited = (err_a == "rate_limited")

    if err_a in (None, "no_results"):
        all_results.extend(results_a or [])
        _all_rate_limited = False
    else:
        _log(f"Tier A non-fatal error ({err_a!r}) — continuing to Tier B")

    # ── Tier B: managers (only if need more) ─────────────────────────────────
    candidates_so_far = _map_candidates(all_results, effective_domain, company_name)
    if len(candidates_so_far) < max_contacts:
        _log(f"Tier A: {len(candidates_so_far)} candidates — running Tier B")
        results_b, _total_b, err_b = await _do_search(
            effective_domain, company_name, _TIER_B_SENIORITIES, "Tier-B(mgr)"
        )
        api_calls += 1

        if err_b == "auth_failed":
            return ProspeoSearchResult(
                success=False, company_name=company_name,
                company_domain=effective_domain or None,
                api_calls=api_calls,
                elapsed_seconds=round(time.monotonic() - t0, 2),
                error="auth_failed",
            )

        if err_b in (None, "no_results"):
            all_results.extend(results_b or [])
            _all_rate_limited = False
        else:
            if err_b == "rate_limited":
                _log(f"Tier B rate_limited — also rate limited")
            else:
                _log(f"Tier B error ({err_b!r})")
                _all_rate_limited = False
    else:
        _log(f"Tier A sufficient ({len(candidates_so_far)} candidates) — Tier B skipped")
        _all_rate_limited = False

    # ── Fallback: no seniority filter ────────────────────────────────────────
    candidates_so_far = _map_candidates(all_results, effective_domain, company_name)
    if not candidates_so_far:
        # If all tiers were rate-limited, skip fallback — it will also be rate-limited
        if _all_rate_limited:
            _log("All tiers rate-limited — skipping fallback to avoid further 429s")
            return ProspeoSearchResult(
                success=False, company_name=company_name,
                company_domain=effective_domain or None,
                api_calls=api_calls,
                elapsed_seconds=round(time.monotonic() - t0, 2),
                error="rate_limited",
            )

        _log("0 relevant candidates after Tier A+B — running fallback (no seniority filter)")
        results_fb, _total_fb, err_fb = await _do_search(
            effective_domain, company_name, None, "Fallback(no-filter)"
        )
        api_calls += 1

        if err_fb == "auth_failed":
            return ProspeoSearchResult(
                success=False, company_name=company_name,
                company_domain=effective_domain or None,
                api_calls=api_calls,
                elapsed_seconds=round(time.monotonic() - t0, 2),
                error="auth_failed",
            )

        if err_fb in (None, "no_results"):
            all_results.extend(results_fb or [])
        else:
            _log(f"Fallback error ({err_fb!r})")

    if not all_results:
        elapsed = round(time.monotonic() - t0, 2)
        _log("No matching people found after all search tiers")
        return ProspeoSearchResult(
            success=True,
            company_name=company_name,
            company_domain=effective_domain or None,
            api_calls=api_calls,
            elapsed_seconds=elapsed,
        )

    # ── Map + rank candidates ────────────────────────────────────────────────
    candidates = _map_candidates(all_results, effective_domain, company_name)
    _log(
        f"Profiles returned: {len(all_results)} total "
        f"→ {len(candidates)} relevant decision-makers retained"
    )

    if not candidates:
        elapsed = round(time.monotonic() - t0, 2)
        _log("No relevant decision-makers found in profiles")
        return ProspeoSearchResult(
            success=True,
            company_name=company_name,
            company_domain=effective_domain or None,
            api_calls=api_calls,
            elapsed_seconds=elapsed,
        )

    # Sort: role priority (asc) then match strength (desc)
    candidates.sort(key=lambda c: (ROLE_PRIORITY.get(c["role"], 99), -c["match_strength"]))
    top_candidates = candidates[:max_contacts]

    _log(f"Top {len(top_candidates)} candidates selected for bulk enrichment:")
    for i, c in enumerate(top_candidates, 1):
        _log(f"  [{i}] {c['name']!r} | {c['title']!r} | role={c['role']}")

    # ════════════════════════════════════════════════════════════════════════
    # STEP 2 — Bulk Enrich Person (email + mobile)
    # ════════════════════════════════════════════════════════════════════════
    _log(f"Bulk enrichment: submitting {len(top_candidates)} person(s)")

    enrich_records = [
        {"identifier": str(i), "person_id": c["person_id"]}
        for i, c in enumerate(top_candidates)
    ]

    matched, total_cost, enrich_err = await bulk_enrich_person(
        enrich_records,
        enrich_mobile=True,
        only_verified_email=False,
    )
    api_calls += 1
    credits   += total_cost

    if enrich_err == "auth_failed":
        _log("Authentication failed during bulk enrich — stopping")
        return ProspeoSearchResult(
            success=False, company_name=company_name,
            company_domain=effective_domain or None,
            api_calls=api_calls, credits_estimated=credits,
            elapsed_seconds=round(time.monotonic() - t0, 2),
            error="auth_failed",
        )

    _log(
        f"Bulk enrich response — "
        f"matched={len(matched)}/{len(top_candidates)} "
        f"credits_used={total_cost}"
    )

    # Index enriched persons by identifier
    enriched_index: dict[str, dict] = {
        str(item.get("identifier", "")): item for item in matched
    }

    # Merge enriched data into candidates
    final_contacts: list[dict] = []
    seen_emails: set[str] = set()
    seen_names:  set[str] = set()

    for i, cand in enumerate(top_candidates):
        enriched_item = enriched_index.get(str(i))
        if enriched_item:
            ep = enriched_item.get("person") or {}
            ec = enriched_item.get("company")
        else:
            ep = cand.get("_raw_person") or {}
            ec = cand.get("_raw_company")

        contact = map_enriched_result(cand, ep, ec, effective_domain, company_name)

        email    = (contact.get("email") or "").lower().strip()
        name_key = (contact.get("name")  or "").lower().strip()

        if email:
            if email in seen_emails:
                continue
            seen_emails.add(email)
        else:
            if name_key and name_key in seen_names:
                continue
        if name_key:
            seen_names.add(name_key)

        final_contacts.append(contact)

    # Final sort: confidence desc, then role priority
    final_contacts.sort(
        key=lambda c: (-c["confidence"], ROLE_PRIORITY.get(c.get("role", "other"), 99))
    )
    final_contacts = final_contacts[:max_contacts]

    # ── Stats + detailed log ─────────────────────────────────────────────────
    emails_found = sum(1 for c in final_contacts if c.get("email"))
    phones_found = sum(1 for c in final_contacts if c.get("phone"))
    elapsed      = round(time.monotonic() - t0, 2)

    _log(f"Final contacts:  {len(final_contacts)}")
    _log(f"Emails found:    {emails_found}")
    _log(f"Phones found:    {phones_found}")

    for idx, ct in enumerate(final_contacts, 1):
        eflag = "email=YES" if ct.get("email") else "email=NO"
        pflag = "phone=YES" if ct.get("phone") else "phone=NO"
        _log(
            f"  Contact [{idx}]: {ct['name']!r} | "
            f"{ct['title']!r} | {eflag} | {pflag} | "
            f"confidence={ct.get('confidence', 0):.3f}"
        )

    _log(
        f"COMPLETE — contacts={len(final_contacts)} "
        f"emails={emails_found} phones={phones_found} "
        f"api_calls={api_calls} credits={credits} elapsed={elapsed}s"
    )

    contacts_out = [ProspeoContact(**c) for c in final_contacts]

    return ProspeoSearchResult(
        success=True,
        company_name=company_name,
        company_domain=effective_domain or None,
        contacts=contacts_out,
        contacts_found=len(contacts_out),
        emails_found=emails_found,
        phones_found=phones_found,
        api_calls=api_calls,
        credits_estimated=credits,
        elapsed_seconds=elapsed,
    )
