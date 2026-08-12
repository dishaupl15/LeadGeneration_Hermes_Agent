"""
contactout/people_search.py
────────────────────────────
Core orchestration: company input → up to N ranked ContactOut contacts.

Workflow
────────
POST /v1/people/search (page 1, page_size=CONTACTOUT_PAGE_SIZE)
  If total_results > page_size, continue fetching additional pages
  until max_contacts reached or no more pages.

  Each call uses:
    • company / company_domain
    • job_title (priority titles list) — sent to bias server-side ranking
    • current_titles_only = True
    • include_related_job_titles = True
    • match_experience = True
    • reveal_info = True   ← requests actual contact data in one call

  Filter: hard-noise titles are rejected; everything else is kept.
  Rank by role priority (asc) then confidence (desc).
  Deduplicate by email, then LinkedIn URL, then name+company.
  Return up to max_contacts contacts.

Auth-failure handling
─────────────────────
  If the API call returns error_code == "auth_failed" the function
  returns immediately with ContactOutSearchResult.error = "auth_failed".

Isolation
─────────
  Imports ONLY from contactout/ and stdlib.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from contactout.client import people_search as _api_people_search
from contactout.config import (
    CONTACTOUT_MAX_CONTACTS_PER_COMPANY,
    CONTACTOUT_PAGE_SIZE,
    is_configured,
    token_length,
)
from contactout.contact_mapper import (
    ROLE_PRIORITY,
    classify_role,
    extract_title,
    extract_name,
    is_decision_maker,
    map_profile,
)
from contactout.schemas import ContactOutContact, ContactOutSearchResult


# ── Logger ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [CONTACTOUT] {msg}", flush=True)


# ── Priority titles sent to ContactOut ───────────────────────────────────────
# These bias the server-side result ranking; our own filtering is inclusive.

_PRIORITY_TITLES: list[str] = [
    "Founder",
    "Co-Founder",
    "Owner",
    "CEO",
    "Chief Executive Officer",
    "Managing Director",
    "Director",
    "Executive Director",
    "General Manager",
    "Partner",
    "Managing Partner",
    "Principal",
    "Chairman",
    "President",
    "COO",
    "Head",
    "HR Head",
    "Head of Human Resources",
    "Talent Acquisition Head",
    "Recruitment Head",
    "HR Manager",
    "Talent Acquisition Manager",
]


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


# ── Payload builder ───────────────────────────────────────────────────────────

def _build_payload(
    company_name: str,
    domain: str,
    page: int = 1,
    page_size: int = CONTACTOUT_PAGE_SIZE,
) -> dict:
    """
    Build ContactOut /v1/people/search payload for the given page.

    Always restricts to current employees of the specific company.
    Never searches the entire database.
    Requests reveal_info=True to get actual contact details in one call.
    """
    payload: dict = {
        "job_title":                   _PRIORITY_TITLES,
        "current_titles_only":         True,
        "include_related_job_titles":  True,
        "match_experience":            True,
        "reveal_info":                 True,
        "page":                        page,
        "page_size":                   page_size,
        "fields": [
            "full_name", "first_name", "last_name",
            "title", "current_title", "headline",
            "current_company", "company", "experience",
            "linkedin", "linkedin_url",
            "contact_availability",
            "contact_info",
        ],
    }

    # Always include company restriction — never search without it
    if domain:
        payload["company_domain"] = domain
        payload["company"]        = company_name
    else:
        payload["company"] = company_name

    return payload


# ── Safe profile diagnostic logger ───────────────────────────────────────────

def _log_profile_safe(idx: int, profile: dict) -> None:
    """
    Log non-PII profile fields for debugging.
    NEVER logs email addresses or phone numbers.
    """
    name = (
        profile.get("full_name")
        or profile.get("name")
        or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
        or "(no name)"
    )
    title = (
        profile.get("title")
        or profile.get("current_title")
        or profile.get("headline")
        or "(no title)"
    )
    company_raw = profile.get("current_company") or profile.get("company") or {}
    if isinstance(company_raw, str):
        company_display = company_raw
    elif isinstance(company_raw, dict):
        company_display = company_raw.get("name") or company_raw.get("domain") or "(unknown)"
    else:
        company_display = "(unknown)"

    linkedin = profile.get("linkedin") or profile.get("linkedin_url") or "(none)"

    ci = profile.get("contact_info") or {}
    # ContactOut actual field names (confirmed by live API probe):
    #   work_emails, personal_emails, emails, work_email_status, phones
    has_work_email = bool(ci.get("work_emails"))
    has_any_email  = bool(ci.get("emails") or ci.get("work_emails") or ci.get("personal_emails"))
    has_phone      = bool(ci.get("phones"))
    avail          = profile.get("contact_availability") or {}

    _log(
        f"  Profile[{idx}]: name={name!r} title={title!r} "
        f"company={company_display!r} linkedin={linkedin!r} "
        f"has_work_email={has_work_email} has_any_email={has_any_email} "
        f"has_phone={has_phone} contact_availability={avail}"
    )


# ── Main entry point ──────────────────────────────────────────────────────────

async def search_contacts(
    company_name: str,
    domain: Optional[str] = None,
    max_contacts: int = CONTACTOUT_MAX_CONTACTS_PER_COMPANY,
) -> ContactOutSearchResult:
    """
    Find up to `max_contacts` contacts at the given company via ContactOut.

    Decision-makers are preferred (ranked first) but all non-noise profiles
    from the target company are retained.

    Args:
        company_name:  Required — used for filtering results.
        domain:        Bare domain, e.g. "intercom.com" (preferred for precision).
        max_contacts:  Cap on returned contacts (default from env, min 1).

    Returns:
        ContactOutSearchResult.
        On auth failure: .error = "auth_failed", .contacts = [].
    """
    t0 = time.monotonic()
    max_contacts = max(1, max_contacts)

    _log(f"Company: {company_name!r}")

    effective_domain = _normalise_domain(domain or "")
    _log(f"Domain: {effective_domain or '(none — using name match)'!r}")

    # ── Guard: not configured ────────────────────────────────────────────────
    if not is_configured():
        _log(f"API token not configured (token_length={token_length()}) — skipping")
        return ContactOutSearchResult(
            success=False,
            error="CONTACTOUT_API_TOKEN not configured",
        )

    _log(f"Searching contacts (max={max_contacts}, page_size={CONTACTOUT_PAGE_SIZE})")

    # ── Paginated fetch ───────────────────────────────────────────────────────
    all_profiles: list[dict] = []
    api_calls = 0
    total_available = 0
    current_page = 1

    while True:
        payload = _build_payload(
            company_name, effective_domain,
            page=current_page,
            page_size=CONTACTOUT_PAGE_SIZE,
        )

        body, error_code = await _api_people_search(payload)
        api_calls += 1

        if error_code == "auth_failed":
            _log("Authentication failed — stopping")
            return ContactOutSearchResult(
                success=False,
                api_calls=api_calls,
                error="auth_failed",
            )

        if error_code in ("rate_limited", "no_credits", "no_access"):
            _log(f"API error: {error_code} — cannot retrieve more contacts")
            break

        if error_code or not body:
            _log(f"API error: {error_code or 'empty_response'} — stopping pagination")
            break

        # ── Parse profiles from this page ─────────────────────────────────
        raw_profiles = body.get("profiles") or {}
        if isinstance(raw_profiles, dict):
            page_profiles = list(raw_profiles.values())
        elif isinstance(raw_profiles, list):
            page_profiles = raw_profiles
        else:
            page_profiles = []

        meta = body.get("metadata") or {}
        if isinstance(meta, dict):
            total_available = meta.get("total_results", total_available)

        _log(
            f"Page {current_page}: received {len(page_profiles)} profiles "
            f"(total_available={total_available})"
        )

        # Diagnostic: log non-PII fields for each profile
        for i, prof in enumerate(page_profiles):
            if isinstance(prof, dict):
                _log_profile_safe(i + 1, prof)

        all_profiles.extend(p for p in page_profiles if isinstance(p, dict))

        # ── Decide whether to fetch more pages ────────────────────────────
        profiles_so_far = len(all_profiles)
        if profiles_so_far >= max_contacts * 3:
            # We have enough raw candidates to fill max_contacts after filtering
            _log(f"Collected {profiles_so_far} profiles — sufficient, stopping pagination")
            break
        if len(page_profiles) < CONTACTOUT_PAGE_SIZE:
            # API returned fewer than a full page → no more pages
            _log("Last page reached (partial page returned)")
            break
        if total_available and profiles_so_far >= total_available:
            _log(f"All {total_available} available profiles fetched")
            break
        current_page += 1

    _log(f"Profiles received across {api_calls} API call(s): {len(all_profiles)}")

    if not all_profiles:
        _log("No profiles returned by API")
        return ContactOutSearchResult(
            success=True,
            api_calls=api_calls,
        )

    # ── Map, filter, rank ────────────────────────────────────────────────────
    candidates: list[dict] = []
    rejected_noise   = 0
    rejected_company = 0

    for profile in all_profiles:
        mapped = map_profile(profile, effective_domain, company_name)
        if mapped is None:
            # Determine why it was rejected for the log
            title = extract_title(profile)
            from contactout.contact_mapper import is_noise_title, company_matches
            if is_noise_title(title):
                rejected_noise += 1
            else:
                rejected_company += 1
        else:
            candidates.append(mapped)

    _log(
        f"Profiles retained: {len(candidates)} "
        f"(rejected_noise={rejected_noise}, rejected_no_company_match={rejected_company})"
    )

    decision_makers = sum(1 for c in candidates if is_decision_maker(c.get("title") or ""))
    _log(f"Decision-makers found: {decision_makers}")

    if not candidates:
        _log(
            "No profiles retained — all were either noise titles or could not be "
            "matched to the target company."
        )
        return ContactOutSearchResult(
            success=True,
            api_calls=api_calls,
        )

    # Sort: decision-makers first (by role priority), then by confidence desc
    candidates.sort(
        key=lambda c: (
            ROLE_PRIORITY.get(c.get("role", "other"), 98),
            -c.get("confidence", 0.0),
        )
    )

    # ── Deduplicate ──────────────────────────────────────────────────────────
    seen_emails:    set[str] = set()
    seen_linkedin:  set[str] = set()
    seen_name_co:   set[str] = set()
    final_contacts: list[dict] = []

    for cand in candidates:
        email    = (cand.get("email")        or "").lower().strip()
        linkedin = (cand.get("linkedin_url") or "").lower().strip()
        name_key = (cand.get("name")         or "").lower().strip()

        # Dedup by email
        if email:
            if email in seen_emails:
                continue
            seen_emails.add(email)

        # Dedup by LinkedIn URL
        if linkedin:
            if linkedin in seen_linkedin:
                continue
            seen_linkedin.add(linkedin)

        # Dedup by name (last resort)
        if name_key:
            if name_key in seen_name_co:
                continue
            seen_name_co.add(name_key)

        final_contacts.append(cand)
        if len(final_contacts) >= max_contacts:
            break

    # ── Summary stats ─────────────────────────────────────────────────────────
    emails_found  = sum(1 for c in final_contacts if c.get("email"))
    phones_found  = sum(1 for c in final_contacts if c.get("phone"))
    dm_count      = sum(1 for c in final_contacts if is_decision_maker(c.get("title") or ""))

    _log(f"Profiles received  : {len(all_profiles)}")
    _log(f"Profiles retained  : {len(candidates)}")
    _log(f"Contacts returned  : {len(final_contacts)}")
    _log(f"Contacts with email: {emails_found}")
    _log(f"Contacts with phone: {phones_found}")
    _log(f"Decision-makers    : {dm_count}")

    # Strip internal "role" field before building output
    contacts_out: list[ContactOutContact] = []
    for ct in final_contacts:
        contacts_out.append(ContactOutContact(
            name         = ct.get("name"),
            title        = ct.get("title"),
            email        = ct.get("email"),
            phone        = ct.get("phone"),
            linkedin_url = ct.get("linkedin_url"),
            source       = "contactout",
            confidence   = ct.get("confidence", 0.0),
        ))

    elapsed = round(time.monotonic() - t0, 2)
    _log(
        f"COMPLETE — contacts={len(contacts_out)} "
        f"emails={emails_found} "
        f"phones={phones_found} "
        f"decision_makers={dm_count} "
        f"api_calls={api_calls} "
        f"elapsed={elapsed}s"
    )

    return ContactOutSearchResult(
        success        = True,
        contacts       = contacts_out,
        contacts_found = len(contacts_out),
        emails_found   = emails_found,
        phones_found   = phones_found,
        api_calls      = api_calls,
        error          = None,
    )
