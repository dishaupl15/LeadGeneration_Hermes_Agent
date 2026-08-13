"""
app/services/origami_service.py
────────────────────────────────
Origami — optional decision-maker / people enrichment layer.

Pipeline position
─────────────────
  Google Maps → Companies
    ↓  CompanyEnrich / Serper / Firecrawl  (field enrichment)
    ↓
  *** Origami (this module) ***
    ↓  – contacts fed into company["_origami_contacts"]
    ↓  – founder promoted to company["founder_name"] / ["founder_email"] when empty
    ↓  – origami_enriched / origami_confidence / founder_status written
    ↓
  PDL → Prospeo → ContactOut → Hunter  (existing waterfall)
    ↓  – _origami_contacts merged via existing dedup_and_merge
    ↓
  MongoDB → CRM

Origami's contract
──────────────────
  enrich_company_with_origami(company: dict) -> dict

  Priority order returned (always source-verified, never invented):
    Tier 1 — Founder / Owner / Co-founder / Proprietor
    Tier 2 — CEO / President / Managing Director / Chairman
    Tier 3 — COO / CFO / CTO / CMO / Director / VP
    Tier 4 — Head of / General Manager / Country Head
    Tier 5 — Other senior employees

  Fields added to the company dict:
    origami_enriched      bool   — True when Origami ran and returned ≥1 contact
    origami_confidence    float  — top contact's confidence score (0.0–1.0)
    origami_source        str    — "origami" (constant)
    founder_status        str    — "found" | "not_found" | "skipped" | "error"
    founder_title         str    — job title of the promoted founder contact
    founder_email         str    — email of the promoted founder (if available)
    founder_profile_url   str    — LinkedIn / profile URL of founder (if available)
    people[]              list   — ALL Origami contacts (structured, before dedup)
    _origami_contacts[]   list   — raw contacts for the orchestrator's dedup step

  Existing fields NEVER overwritten:
    founder_name   — only set when currently empty
    email          — only set when currently empty
    company_number — never touched
    phones         — never touched
    contacts[]     — Origami contacts are injected via _origami_contacts[], not
                     directly into contacts[]. The orchestrator's dedup merges them.

Configuration (via .env)
────────────────────────
  ORIGAMI_API_KEY          required  — your Origami dashboard key
  ORIGAMI_BASE_URL         optional  — default https://api.origami.ai/v1
  ORIGAMI_TIMEOUT_SECONDS  optional  — default 20
  ORIGAMI_MAX_CONTACTS     optional  — default 8

Independent test
────────────────
  From backend/:
    python -m app.services.origami_service "ABC Realty" abcrealty.com
    python -m app.services.origami_service "Tata Motors" tatamotors.com
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime
from typing import Optional

# ── Configuration ─────────────────────────────────────────────────────────────

def _api_key() -> str:
    return os.getenv("ORIGAMI_API_KEY", "").strip()

def _base_url() -> str:
    return os.getenv("ORIGAMI_BASE_URL", "https://api.origami.ai/v1").rstrip("/")

def _timeout() -> float:
    try:
        return max(5.0, float(os.getenv("ORIGAMI_TIMEOUT_SECONDS", "20")))
    except ValueError:
        return 20.0

def _max_contacts() -> int:
    try:
        return max(1, int(os.getenv("ORIGAMI_MAX_CONTACTS", "8")))
    except ValueError:
        return 8

def is_configured() -> bool:
    """Return True when ORIGAMI_API_KEY is set in the environment."""
    return bool(_api_key())


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [ORIGAMI] {msg}", flush=True)


# ── Title priority / tier system ──────────────────────────────────────────────
#
#  Tier 1 — Founder / Owner  (highest — used for founder_name promotion)
#  Tier 2 — CEO / President / MD / Chairman
#  Tier 3 — C-suite (COO/CTO/CFO/CMO/CPO) / Director / VP
#  Tier 4 — Head of / GM / Country Head / Regional Head
#  Tier 5 — Other employees
#
#  Rules are checked in order; FIRST match wins.

_TIER_RULES: list[tuple[int, list[str]]] = [
    (1, ["co-founder", "cofounder", "co founder",
         "founder", "owner", "proprietor", "promoter"]),
    (2, ["chief executive", "ceo", "managing director", " md ",
         "president", "chairman", "chairperson", "chairwoman",
         "chief executive officer"]),
    (3, ["chief operating", "coo", "chief financial", "cfo",
         "chief technology", "cto", "chief marketing", "cmo",
         "chief product", "cpo", "chief people", "chro",
         "vice president", " vp ", "svp", "evp", "avp",
         "director"]),
    (4, ["head of", "general manager", "country head", "regional head",
         "state head", "city head", "zonal head", "area head",
         "branch head", "cluster head"]),
]


def title_tier(title: Optional[str]) -> int:
    """
    Return 1–5 priority tier for a job title.
    Tier 1 = Founder/Owner (highest priority), Tier 5 = other.
    """
    if not title:
        return 5
    t = f" {title.lower().strip()} "
    for tier, keywords in _TIER_RULES:
        for kw in keywords:
            if kw in t:
                return tier
    return 5


def tier_label(tier: int) -> str:
    return {1: "Founder/Owner", 2: "CEO/MD", 3: "Director/VP",
            4: "Head/GM", 5: "Other"}.get(tier, "Other")


def sort_contacts(contacts: list[dict]) -> list[dict]:
    """Sort contacts: lower tier first, then confidence descending."""
    return sorted(
        contacts,
        key=lambda c: (title_tier(c.get("title")), -(c.get("confidence") or 0.0)),
    )


# ── Email helpers ──────────────────────────────────────────────────────────────

_JUNK_LOCALS: frozenset[str] = frozenset({
    "noreply", "no-reply", "donotreply", "webmaster", "admin",
    "info", "contact", "support", "hello", "billing", "test",
    "sales", "hr", "office", "careers", "jobs", "media",
    "press", "legal", "compliance", "dpo", "abuse",
})

def clean_email(email: Optional[str]) -> Optional[str]:
    """Validate and normalise an email. Returns None for junk/invalid."""
    if not email:
        return None
    e = email.strip().lower()
    if "@" not in e:
        return None
    local, _, domain = e.partition("@")
    if not domain or "." not in domain:
        return None
    if local in _JUNK_LOCALS:
        return None
    if len(local) < 2 or "/" in local:
        return None
    return e


# ── Phone helpers ──────────────────────────────────────────────────────────────

def _norm_phone_digits(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone.strip())
    return digits[-10:] if len(digits) >= 10 else digits


# ── API call ───────────────────────────────────────────────────────────────────

async def _call_origami_api(
    company_name: str,
    domain: Optional[str],
    website: Optional[str],
    location: Optional[str],
    category: Optional[str],
) -> list[dict]:
    """
    Call the Origami API endpoint.

    Returns a list of normalised contact dicts.  Returns [] on any error.
    Never raises.

    Expected Origami response (adapt parser block if real API differs):
    {
      "contacts": [
        {
          "name":         "Rahul Sharma",
          "title":        "Founder",
          "email":        "rahul@abcrealty.com",
          "phone":        "+91 98765 43210",
          "linkedin_url": "https://linkedin.com/in/rahulsharma",
          "confidence":   0.91,
          "source":       "origami"
        }
      ]
    }
    """
    import httpx

    key = _api_key()
    if not key:
        return []

    payload: dict = {
        "company_name": company_name,
        "limit": _max_contacts(),
    }
    if domain:    payload["domain"]   = domain
    if website:   payload["website"]  = website
    if location:  payload["location"] = location
    if category:  payload["industry"] = category

    _log(f"API call → {company_name!r}  domain={domain!r}  location={location!r}")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_timeout()),
            follow_redirects=True,
            headers={"User-Agent": "LeadCRM-Origami/1.0"},
        ) as client:
            resp = await client.post(
                f"{_base_url()}/people/search",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException:
        _log(f"Timeout ({_timeout()}s) for {company_name!r} — skipped")
        return []
    except httpx.RequestError as exc:
        _log(f"Network error for {company_name!r}: {exc} — skipped")
        return []
    except Exception as exc:
        _log(f"Unexpected error calling API for {company_name!r}: {exc} — skipped")
        return []

    # Status handling
    if resp.status_code == 401:
        _log("Auth failed (401) — check ORIGAMI_API_KEY")
        return []
    if resp.status_code == 402:
        _log("Credits exhausted (402) — Origami skipped for remaining companies this run")
        return []
    if resp.status_code == 429:
        _log("Rate limited (429) — skipping this company")
        return []
    if resp.status_code == 404:
        _log(f"Company not found (404): {company_name!r}")
        return []
    if not resp.is_success:
        _log(f"HTTP {resp.status_code} for {company_name!r} — skipping")
        return []

    # Parse response
    try:
        data = resp.json()
    except Exception as exc:
        _log(f"JSON parse error for {company_name!r}: {exc}")
        return []

    # Normalise different possible response shapes
    raw_list = (
        data.get("contacts")
        or data.get("people")
        or data.get("results")
        or data.get("data")
        or []
    )
    if isinstance(raw_list, dict):
        raw_list = [raw_list]

    contacts: list[dict] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue

        # Name — try several field names
        name = (
            entry.get("name")
            or entry.get("full_name")
            or (
                f"{entry.get('first_name', '')} {entry.get('last_name', '')}".strip()
                or None
            )
        )

        # Title — normalise to a single string
        title = (
            entry.get("title")
            or entry.get("job_title")
            or entry.get("designation")
            or entry.get("position")
            or entry.get("role")
        )

        email    = clean_email(
            entry.get("email") or entry.get("email_address") or entry.get("work_email")
        )
        phone    = entry.get("phone") or entry.get("phone_number") or entry.get("mobile")
        linkedin = (
            entry.get("linkedin_url")
            or entry.get("linkedin")
            or entry.get("profile_url")
            or entry.get("social_url")
        )
        confidence = 0.65  # default when Origami doesn't provide one
        raw_conf = entry.get("confidence") or entry.get("score") or entry.get("relevance")
        if raw_conf is not None:
            try:
                confidence = max(0.0, min(float(raw_conf), 1.0))
            except (ValueError, TypeError):
                pass

        # Skip entries with zero useful data
        if not name and not email:
            continue

        contacts.append({
            "name":         name,
            "title":        title,
            "email":        email,
            "phone":        phone,
            "linkedin_url": linkedin,
            "confidence":   confidence,
            "source":       "origami",
            "sources":      ["origami"],
        })

    _log(f"API returned {len(contacts)} contacts for {company_name!r}")
    return contacts


# ── Dedup against existing contacts ──────────────────────────────────────────

def _is_duplicate(candidate: dict, existing: list[dict]) -> bool:
    """
    Return True if candidate is already represented in existing contacts.
    Dedup keys (in priority order):
      1. Normalised email
      2. Normalised phone (last 10 digits)
      3. Exact name (case-insensitive) + same company domain context
    """
    c_email = (candidate.get("email") or "").strip().lower()
    c_phone = _norm_phone_digits(candidate.get("phone"))
    c_name  = (candidate.get("name") or "").strip().lower()

    for ex in existing:
        ex_email = (ex.get("email") or "").strip().lower()
        ex_phone = _norm_phone_digits(ex.get("phone"))
        ex_name  = (ex.get("name") or "").strip().lower()

        if c_email and ex_email and c_email == ex_email:
            return True
        if c_phone and len(c_phone) >= 8 and ex_phone and c_phone == ex_phone:
            return True
        if c_name and ex_name and c_name == ex_name:
            return True
    return False


# ── Core enrichment function ──────────────────────────────────────────────────

async def enrich_company_with_origami(company: dict) -> dict:
    """
    Run Origami enrichment for one company dict.

    Returns the updated company dict with new Origami-specific fields.
    NEVER raises — all failures are caught and logged.
    NEVER overwrites existing authoritative fields (Google Maps, CompanyEnrich).

    New fields written:
      origami_enriched      bool
      origami_confidence    float
      origami_source        str
      founder_status        str   "found" | "not_found" | "skipped" | "error"
      founder_title         str   (when a Tier-1 contact was found)
      founder_email         str   (when a Tier-1 contact had an email)
      founder_profile_url   str   (when a Tier-1 contact had a LinkedIn URL)
      people[]              list  ALL Origami contacts (structured)
      _origami_contacts[]   list  raw contacts for dedup in orchestrator
    """
    if not is_configured():
        company.setdefault("origami_enriched", False)
        company.setdefault("founder_status",   "skipped")
        return company

    company_name = (company.get("company_name") or "").strip()
    if not company_name:
        company["origami_enriched"] = False
        company["founder_status"]   = "skipped"
        return company

    domain   = company.get("domain")  or ""
    website  = company.get("website") or ""
    location = ", ".join(
        p for p in [company.get("city"), company.get("state"), company.get("country")]
        if p
    ) or None
    category = company.get("category") or company.get("industry") or None

    t0 = time.monotonic()

    try:
        raw_contacts = await asyncio.wait_for(
            _call_origami_api(
                company_name=company_name,
                domain=domain or None,
                website=website or None,
                location=location,
                category=category,
            ),
            timeout=_timeout() + 5,
        )
    except asyncio.TimeoutError:
        _log(f"Outer timeout for {company_name!r}")
        company["origami_enriched"] = False
        company["founder_status"]   = "error"
        return company
    except Exception as exc:
        _log(f"Error for {company_name!r}: {type(exc).__name__}: {exc}")
        company["origami_enriched"] = False
        company["founder_status"]   = "error"
        return company

    elapsed = round(time.monotonic() - t0, 2)

    if not raw_contacts:
        _log(f"{company_name!r}: no contacts ({elapsed}s) — founder_status=not_found")
        company["origami_enriched"] = False
        company["founder_status"]   = "not_found"
        return company

    # Sort by priority tier then confidence
    sorted_contacts = sort_contacts(raw_contacts)

    _log(
        f"{company_name!r}: {len(sorted_contacts)} contacts in {elapsed}s | "
        f"top={sorted_contacts[0].get('name')!r} "
        f"tier={title_tier(sorted_contacts[0].get('title'))} "
        f"({tier_label(title_tier(sorted_contacts[0].get('title')))})"
    )

    updated = dict(company)

    # ── Write _origami_contacts for the orchestrator's dedup step ────────────
    # The orchestrator's people waterfall will run dedup_and_merge() on
    # (existing contacts + _origami_contacts + PDL/Prospeo/ContactOut contacts).
    # We stage them here rather than directly inserting into contacts[] so the
    # existing dedup logic handles the merge cleanly.
    existing_contacts = list(updated.get("contacts") or [])
    new_contacts: list[dict] = []
    for c in sorted_contacts:
        if not _is_duplicate(c, existing_contacts + new_contacts):
            new_contacts.append(c)

    updated["_origami_contacts"] = new_contacts

    # ── Write structured people[] (all Origami contacts, for MongoDB) ────────
    # people[] is a permanent record on the lead document so the CRM can show
    # "ABC Realty → Rahul Sharma (Founder) | Amit Patil (CEO) | …"
    updated["people"] = [
        {
            "name":         c.get("name"),
            "title":        c.get("title"),
            "tier":         title_tier(c.get("title")),
            "tier_label":   tier_label(title_tier(c.get("title"))),
            "email":        c.get("email"),
            "phone":        c.get("phone"),
            "linkedin_url": c.get("linkedin_url"),
            "confidence":   c.get("confidence", 0.0),
            "source":       "origami",
        }
        for c in sorted_contacts
    ]

    # ── Origami meta fields ───────────────────────────────────────────────────
    top = sorted_contacts[0]
    updated["origami_enriched"]  = True
    updated["origami_confidence"] = top.get("confidence", 0.0)
    updated["origami_source"]    = "origami"

    # ── founder_status ────────────────────────────────────────────────────────
    # Only promote as "founder" when the source-verified title is Tier 1.
    # If the best contact is Tier 2+ we still store it but set status accordingly.
    top_tier = title_tier(top.get("title"))
    if top_tier == 1:
        updated["founder_status"] = "found"
    elif top_tier <= 3:
        updated["founder_status"] = "found_decision_maker"
    else:
        updated["founder_status"] = "not_found"

    # ── Founder field promotion ───────────────────────────────────────────────
    # Find the highest-priority Tier-1 contact (Founder/Owner).
    # Only promote when founder_name is currently empty — never overwrite
    # CompanyEnrich or other authoritative sources.
    tier1_contacts = [c for c in sorted_contacts if title_tier(c.get("title")) == 1]
    founder_candidate = tier1_contacts[0] if tier1_contacts else None

    if founder_candidate:
        founder_name_val = founder_candidate.get("name")
        if founder_name_val and not updated.get("founder_name"):
            updated["founder_name"]       = founder_name_val
            updated["founder_number"]     = founder_candidate.get("phone") or updated.get("founder_number")
            updated["founder_title"]      = founder_candidate.get("title")
            updated["founder_email"]      = founder_candidate.get("email")
            updated["founder_profile_url"] = founder_candidate.get("linkedin_url")

            # Update _field_verification for downstream pipeline
            fv = dict(updated.get("_field_verification") or {})
            fv["founder"] = {
                "value":    founder_name_val,
                "verified": bool(
                    founder_candidate.get("linkedin_url")
                    or founder_candidate.get("email")
                ),
                "status":   "origami_founder",
                "source":   "origami",
            }
            updated["_field_verification"] = fv
            _log(
                f"{company_name!r}: promoted founder → {founder_name_val!r} "
                f"({founder_candidate.get('title')}) "
                f"email={'YES' if founder_candidate.get('email') else 'NO'}"
            )
        else:
            # Founder name already set — record structured fields without overwriting
            updated["founder_title"]       = founder_candidate.get("title")
            updated["founder_profile_url"] = founder_candidate.get("linkedin_url")
            if not updated.get("founder_email"):
                updated["founder_email"]   = founder_candidate.get("email")
    else:
        # No Tier-1 contact found — store title of best contact as context
        updated["founder_title"]       = top.get("title")
        updated["founder_profile_url"] = top.get("linkedin_url")

    # ── Email promotion ───────────────────────────────────────────────────────
    # Promote the first available email from ANY contact (if company has none yet).
    if not updated.get("email"):
        for c in sorted_contacts:
            if c.get("email"):
                updated["email"] = c["email"]
                emails = list(updated.get("emails") or [])
                if c["email"] not in emails:
                    emails.insert(0, c["email"])
                updated["emails"] = emails
                fv = dict(updated.get("_field_verification") or {})
                fv["email"] = {
                    "value":    c["email"],
                    "verified": False,  # not verified yet; existing pipeline may verify
                    "status":   "origami_email",
                    "source":   "origami",
                }
                updated["_field_verification"] = fv
                _log(f"{company_name!r}: promoted email → {c['email']!r} (from {c.get('name')!r})")
                break

    # ── Log all contacts found ────────────────────────────────────────────────
    for i, c in enumerate(sorted_contacts, 1):
        _log(
            f"  [{i}] {tier_label(title_tier(c.get('title')))} "
            f"| {c.get('name')!r} "
            f"| {c.get('title') or '(no title)'!r} "
            f"| email={'YES' if c.get('email') else 'NO'} "
            f"| phone={'YES' if c.get('phone') else 'NO'} "
            f"| conf={c.get('confidence', 0):.2f}"
        )

    return updated


# ── Orchestrator integration hook ─────────────────────────────────────────────

def inject_origami_contacts_into_waterfall(company: dict) -> tuple[list[dict], dict]:
    """
    Called by the people enrichment orchestrator BEFORE running PDL/Prospeo/ContactOut.

    Returns (origami_contacts, updated_company_without_origami_staging_field)

    The origami contacts are fed into the waterfall's raw contacts list so
    dedup_and_merge() processes them together with PDL/Prospeo/ContactOut contacts.
    This ensures:
      - A Prospeo contact for the same person as an Origami contact merges cleanly.
      - The combined record gets the best data from both sources.
      - No duplicates reach MongoDB.
    """
    origami_contacts = list(company.get("_origami_contacts") or [])
    # Remove staging field — it's not a MongoDB-persisted field
    clean = {k: v for k, v in company.items() if k != "_origami_contacts"}
    return origami_contacts, clean


# ── Email forwarding: Origami founder → existing email providers ──────────────

async def _find_email_for_founder(
    founder_name: str,
    company_name: str,
    domain: Optional[str],
) -> Optional[str]:
    """
    When Origami finds a founder name but no email, try to find the email
    using Prospeo → Hunter → PDL in that order.

    Returns the first valid email found, or None if none found.
    Never raises — all failures are caught.
    """
    if not founder_name or not domain:
        return None

    first, _, last = founder_name.strip().partition(" ")
    if not last:
        return None  # need at least first + last for name-based lookup

    _log(f"Email forward: looking up {founder_name!r} at {domain!r}")

    # ── Try Prospeo first (LinkedIn-based email lookup is most reliable) ──────
    try:
        import os as _os
        prospeo_key = _os.getenv("PROSPEO_API_KEY", "").strip()
        if prospeo_key:
            import httpx as _httpx
            # Prospeo email-finder: POST /email-finder with name + domain
            async with _httpx.AsyncClient(timeout=12, follow_redirects=True) as _client:
                resp = await _client.post(
                    "https://api.prospeo.io/email-finder",
                    headers={"X-KEY": prospeo_key, "Content-Type": "application/json"},
                    json={"first_name": first, "last_name": last, "domain": domain},
                )
            if resp.status_code == 200:
                data = resp.json()
                found_email = (
                    (data.get("response") or {}).get("email")
                    or data.get("email")
                    or ""
                )
                from app.services.origami_service import clean_email as _ce
                cleaned = _ce(found_email)
                if cleaned:
                    _log(f"Prospeo found email for {founder_name!r}: {cleaned!r}")
                    return cleaned
    except Exception as _exc:
        _log(f"Prospeo email lookup error for {founder_name!r}: {_exc}")

    # ── Try Hunter.io email-finder ────────────────────────────────────────────
    try:
        import os as _os
        hunter_key = _os.getenv("HUNTER_API_KEY", "").strip()
        if hunter_key:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=12, follow_redirects=True) as _client:
                resp = await _client.get(
                    "https://api.hunter.io/v2/email-finder",
                    params={
                        "domain":      domain,
                        "first_name":  first,
                        "last_name":   last,
                        "api_key":     hunter_key,
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                found_email = (data.get("data") or {}).get("email") or ""
                score = (data.get("data") or {}).get("score", 0)
                if found_email and score >= 50:
                    from app.services.origami_service import clean_email as _ce
                    cleaned = _ce(found_email)
                    if cleaned:
                        _log(f"Hunter found email for {founder_name!r}: {cleaned!r} (score={score})")
                        return cleaned
    except Exception as _exc:
        _log(f"Hunter email lookup error for {founder_name!r}: {_exc}")

    return None


async def _enrich_origami_founder_emails(company: dict) -> dict:
    """
    Post-Origami step: for every contact in _origami_contacts that has a name
    but NO email, try to find their email via Prospeo → Hunter.

    This runs AFTER enrich_company_with_origami() but BEFORE the people
    waterfall so the enriched emails are available for dedup/merge.

    Only updates contacts in _origami_contacts[]; does NOT touch people[]
    (which is already set as the permanent structured record).
    """
    origami_contacts = company.get("_origami_contacts") or []
    if not origami_contacts:
        return company

    domain = company.get("domain") or ""
    company_name = company.get("company_name", "")

    enriched_contacts = []
    for contact in origami_contacts:
        c = dict(contact)
        # Only try email lookup when: name exists AND email is missing
        if c.get("name") and not c.get("email") and domain:
            found_email = await _find_email_for_founder(
                founder_name=c["name"],
                company_name=company_name,
                domain=domain,
            )
            if found_email:
                c["email"] = found_email
                # Mark source as compound so dedup knows it came from two steps
                srcs = list(c.get("sources") or ["origami"])
                if "prospeo" not in srcs and "hunter" not in srcs:
                    srcs.append("email_lookup")
                c["sources"] = srcs
                _log(f"Email injected into Origami contact {c['name']!r}: {found_email!r}")

                # Also update people[] to keep the permanent record in sync
                # Find the matching entry in people[] by name and update it
                people = list(company.get("people") or [])
                for p in people:
                    if (p.get("name") or "").strip().lower() == (c["name"] or "").strip().lower():
                        if not p.get("email"):
                            p["email"] = found_email
                        break
                company["people"] = people

                # If this is the founder and founder_email is unset, promote
                from app.services.origami_service import title_tier as _tier
                if _tier(c.get("title")) == 1 and not company.get("founder_email"):
                    company["founder_email"] = found_email
                    _log(f"Promoted founder_email from email_lookup: {found_email!r}")

                # Promote company email if still missing
                if not company.get("email"):
                    company["email"] = found_email
                    emails = list(company.get("emails") or [])
                    if found_email not in emails:
                        emails.insert(0, found_email)
                    company["emails"] = emails

        enriched_contacts.append(c)

    company["_origami_contacts"] = enriched_contacts
    return company


# ── Batch helper ──────────────────────────────────────────────────────────────

async def enrich_batch_with_origami(
    companies: list[dict],
    max_concurrency: int = 3,
) -> list[dict]:
    """
    Enrich a list of companies concurrently.
    Respects rate limits via semaphore (default: 3 concurrent calls).
    Returns results in the same order as input. Never raises.
    """
    if not is_configured():
        _log("ORIGAMI_API_KEY not set — batch skipped")
        for c in companies:
            c.setdefault("origami_enriched", False)
            c.setdefault("founder_status",   "skipped")
        return companies

    sem = asyncio.Semaphore(max_concurrency)

    async def _bounded(c: dict) -> dict:
        async with sem:
            return await enrich_company_with_origami(c)

    results = await asyncio.gather(
        *[_bounded(c) for c in companies],
        return_exceptions=True,
    )
    out: list[dict] = []
    for original, result in zip(companies, results):
        if isinstance(result, Exception):
            _log(f"Batch gather error for {original.get('company_name','?')}: {result}")
            original["origami_enriched"] = False
            original["founder_status"]   = "error"
            out.append(original)
        else:
            out.append(result)
    return out


# ── Standalone test runner ─────────────────────────────────────────────────────

async def _standalone_test(company_name: str, domain: Optional[str] = None) -> None:
    """Interactive test — pretty-prints the Origami enrichment result."""
    from dotenv import load_dotenv
    load_dotenv()

    print(f"\n{'═'*65}")
    print(f"  Origami Enrichment — Independent Test")
    print(f"{'═'*65}")
    print(f"  Company  : {company_name}")
    print(f"  Domain   : {domain or '(not provided)'}")
    key = _api_key()
    print(f"  API Key  : {'SET (' + key[:10] + '…)' if key else 'NOT SET — will simulate empty result'}")
    print(f"  Base URL : {_base_url()}")
    print(f"  Timeout  : {_timeout()}s  Max contacts: {_max_contacts()}")
    print(f"{'═'*65}\n")

    company: dict = {
        "company_name": company_name,
        "domain":       domain or "",
        "website":      f"https://{domain}" if domain else "",
        "contacts":     [],
        "emails":       [],
        "phones":       [],
    }

    result = await enrich_company_with_origami(company)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n  origami_enriched  : {result.get('origami_enriched')}")
    print(f"  founder_status    : {result.get('founder_status')}")
    print(f"  origami_confidence: {result.get('origami_confidence', 0):.2f}")

    if result.get("founder_name"):
        print(f"\n  ▶ Promoted founder_name  : {result['founder_name']}")
    if result.get("founder_title"):
        print(f"  ▶ Promoted founder_title : {result['founder_title']}")
    if result.get("founder_email"):
        print(f"  ▶ Promoted founder_email : {result['founder_email']}")
    if result.get("founder_profile_url"):
        print(f"  ▶ Promoted profile_url   : {result['founder_profile_url']}")
    if result.get("email"):
        print(f"  ▶ Promoted company email : {result['email']}")

    people = result.get("people") or []
    print(f"\n  People found: {len(people)}\n")

    for i, p in enumerate(people, 1):
        tier = p.get("tier", 5)
        stars = "★" * (6 - tier)
        print(f"  [{i}] {stars} {p.get('tier_label', 'Other')}")
        print(f"       Name       : {p.get('name') or '—'}")
        print(f"       Title      : {p.get('title') or '—'}")
        print(f"       Email      : {p.get('email') or '—'}")
        print(f"       Phone      : {p.get('phone') or '—'}")
        print(f"       LinkedIn   : {p.get('linkedin_url') or '—'}")
        print(f"       Confidence : {p.get('confidence', 0):.2f}")
        print()

    origami_contacts = result.get("_origami_contacts") or []
    print(f"  Staged for waterfall dedup: {len(origami_contacts)} new contacts")
    print(f"\n{'═'*65}\n")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        print("Usage: python -m app.services.origami_service <company_name> [domain]")
        print("       python -m app.services.origami_service 'ABC Realty' abcrealty.com")
        print("       python -m app.services.origami_service 'Tata Motors' tatamotors.com")
        sys.exit(1)

    asyncio.run(_standalone_test(args[0], args[1] if len(args) > 1 else None))
