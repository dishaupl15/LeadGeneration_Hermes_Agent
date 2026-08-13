"""
origami/client.py
──────────────────
Raw HTTP layer for the Origami API.

Responsibilities
────────────────
  - Build the request payload
  - Handle all HTTP-level errors gracefully (never raises)
  - Parse and normalise the response into a flat list of contact dicts
  - Log status without ever printing the API key

Isolation
─────────
  Only imports from: origami/config.py + standard library + httpx
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import httpx

from origami.config import (
    ORIGAMI_API_KEY,
    ORIGAMI_BASE_URL,
    ORIGAMI_MAX_CONTACTS,
    ORIGAMI_TIMEOUT_SECONDS,
    is_configured,
)

# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [ORIGAMI-MODULE] {msg}", flush=True)


# ── Title tier system ─────────────────────────────────────────────────────────
#
#  Tier 1 — Founder / Owner / Proprietor / Co-founder
#  Tier 2 — CEO / MD / President / Chairman
#  Tier 3 — C-suite (COO/CTO/CFO/CMO) / Director / VP
#  Tier 4 — Head of / GM / Country Head / Regional Head
#  Tier 5 — Other

_TIER_RULES: list[tuple[int, list[str]]] = [
    (1, ["co-founder", "cofounder", "co founder",
         "founder", "owner", "proprietor", "promoter"]),
    (2, ["chief executive", "ceo", "managing director", " md ",
         "president", "chairman", "chairperson", "chairwoman"]),
    (3, ["chief operating", "coo", "chief financial", "cfo",
         "chief technology", "cto", "chief marketing", "cmo",
         "chief product", "cpo", "vice president", " vp ",
         "svp", "evp", "avp", "director"]),
    (4, ["head of", "general manager", "country head", "regional head",
         "state head", "city head", "zonal head", "area head",
         "branch head", "cluster head"]),
]

_TIER_LABELS: dict[int, str] = {
    1: "Founder/Owner",
    2: "CEO/MD",
    3: "Director/VP",
    4: "Head/GM",
    5: "Other",
}


def title_tier(title: Optional[str]) -> int:
    if not title:
        return 5
    t = f" {title.lower().strip()} "
    for tier, keywords in _TIER_RULES:
        for kw in keywords:
            if kw in t:
                return tier
    return 5


def tier_label(tier: int) -> str:
    return _TIER_LABELS.get(tier, "Other")


# ── Email helpers ──────────────────────────────────────────────────────────────

_JUNK_LOCALS: frozenset[str] = frozenset({
    "noreply", "no-reply", "donotreply", "webmaster", "admin",
    "info", "contact", "support", "hello", "billing", "test",
    "sales", "hr", "office", "careers", "jobs", "media",
    "press", "legal", "compliance", "dpo", "abuse",
})


def clean_email(email: Optional[str]) -> Optional[str]:
    """Validate and normalise an email string. Returns None for junk/invalid."""
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


# ── Phone helpers ─────────────────────────────────────────────────────────────

def _norm_phone_digits(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone.strip())
    return digits[-10:] if len(digits) >= 10 else digits


# ── Contact sort ──────────────────────────────────────────────────────────────

def sort_contacts(contacts: list[dict]) -> list[dict]:
    """Sort: lower tier number first, then confidence descending."""
    return sorted(
        contacts,
        key=lambda c: (title_tier(c.get("title")), -(c.get("confidence") or 0.0)),
    )


# ── Raw API call ──────────────────────────────────────────────────────────────

async def call_origami_api(
    company_name: str,
    domain: Optional[str] = None,
    website: Optional[str] = None,
    location: Optional[str] = None,
    category: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    """
    Call POST /people/search on the Origami API.

    Returns (contacts, error_code) where:
      - contacts is a list of normalised dicts (may be [])
      - error_code is None on success, or one of:
          "no_key" | "auth_failed" | "credits_exhausted" | "rate_limited" |
          "not_found" | "timeout" | "network_error" | "server_error" | "parse_error"

    Never raises.
    """
    if not is_configured():
        return [], "no_key"

    payload: dict = {
        "company_name": company_name,
        "limit": ORIGAMI_MAX_CONTACTS,
    }
    if domain:    payload["domain"]   = domain
    if website:   payload["website"]  = website
    if location:  payload["location"] = location
    if category:  payload["industry"] = category

    _log(f"API call → {company_name!r}  domain={domain!r}  location={location!r}")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(ORIGAMI_TIMEOUT_SECONDS),
            follow_redirects=True,
            headers={"User-Agent": "LeadCRM-Origami-Module/1.0"},
        ) as client:
            resp = await client.post(
                f"{ORIGAMI_BASE_URL}/people/search",
                headers={
                    "Authorization": f"Bearer {ORIGAMI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException:
        _log(f"Timeout ({ORIGAMI_TIMEOUT_SECONDS}s) for {company_name!r}")
        return [], "timeout"
    except httpx.RequestError as exc:
        _log(f"Network error for {company_name!r}: {exc}")
        return [], "network_error"
    except Exception as exc:
        _log(f"Unexpected error for {company_name!r}: {exc}")
        return [], "network_error"

    # ── HTTP status handling ──────────────────────────────────────────────────
    if resp.status_code == 401:
        _log("Auth failed (401) — check ORIGAMI_API_KEY")
        return [], "auth_failed"
    if resp.status_code == 402:
        _log("Credits exhausted (402)")
        return [], "credits_exhausted"
    if resp.status_code == 429:
        _log("Rate limited (429)")
        return [], "rate_limited"
    if resp.status_code == 404:
        _log(f"Company not found (404): {company_name!r}")
        return [], "not_found"
    if resp.status_code >= 500:
        _log(f"Server error ({resp.status_code}) for {company_name!r}")
        return [], "server_error"
    if not resp.is_success:
        _log(f"HTTP {resp.status_code} for {company_name!r}")
        return [], f"http_{resp.status_code}"

    # ── Parse response ────────────────────────────────────────────────────────
    try:
        data = resp.json()
    except Exception as exc:
        _log(f"JSON parse error for {company_name!r}: {exc}")
        return [], "parse_error"

    raw_list = (
        data.get("contacts")
        or data.get("people")
        or data.get("results")
        or data.get("data")
        or []
    )
    if isinstance(raw_list, dict):
        raw_list = [raw_list]

    # ── Normalise entries ─────────────────────────────────────────────────────
    contacts: list[dict] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            continue

        name = (
            entry.get("name")
            or entry.get("full_name")
            or (f"{entry.get('first_name', '')} {entry.get('last_name', '')}".strip() or None)
        )
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

        confidence = 0.65
        raw_conf = entry.get("confidence") or entry.get("score") or entry.get("relevance")
        if raw_conf is not None:
            try:
                confidence = max(0.0, min(float(raw_conf), 1.0))
            except (ValueError, TypeError):
                pass

        if not name and not email:
            continue

        tier = title_tier(title)
        contacts.append({
            "name":         name,
            "title":        title,
            "tier":         tier,
            "tier_label":   tier_label(tier),
            "email":        email,
            "phone":        phone,
            "linkedin_url": linkedin,
            "confidence":   confidence,
            "source":       "origami",
        })

    _log(f"API returned {len(contacts)} contacts for {company_name!r}")
    return contacts, None


# ── Minimal auth probe (does NOT consume search credits) ─────────────────────

async def probe_auth() -> tuple[Optional[int], Optional[str]]:
    """
    Send the smallest possible request to verify the API key.
    Returns (http_status, error_code).  Never raises.
    """
    if not is_configured():
        return None, "no_key"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
        ) as client:
            # Minimal search — single result, no real data needed
            resp = await client.post(
                f"{ORIGAMI_BASE_URL}/people/search",
                headers={
                    "Authorization": f"Bearer {ORIGAMI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={"company_name": "auth_probe", "limit": 1},
            )
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.RequestError as exc:
        _log(f"Auth probe network error: {exc}")
        return None, "network_error"
    except Exception as exc:
        _log(f"Auth probe unexpected error: {exc}")
        return None, "network_error"

    if resp.status_code == 401:
        return 401, "auth_failed"
    if resp.status_code == 402:
        return 402, "credits_exhausted"
    if resp.status_code == 429:
        return 429, "rate_limited"
    if resp.status_code >= 500:
        return resp.status_code, "server_error"

    # 200, 404, etc. — key was accepted
    return resp.status_code, None
