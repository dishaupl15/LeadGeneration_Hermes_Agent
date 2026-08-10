"""
app/services/hunter_service.py
───────────────────────────────
Hunter.io email discovery and verification.

Waterfall role: PRIMARY email provider (Hunter → Apollo → Firecrawl/Serper)

API: https://hunter.io/api-documentation
Key: HUNTER_API_KEY in .env

Rules:
  - Accept ONLY emails whose domain matches the company's official domain.
  - Prefer business addresses: info@, contact@, sales@, hello@, enquiry@.
  - Reject personal providers (gmail, yahoo, hotmail, outlook, etc.).
  - Reject disposable/junk domains.
  - ALWAYS read the key fresh from env — do NOT capture at module import.
  - On 401 auth failure: log clearly and return None (do not crash).
  - Never fabricate — if Hunter fails or returns nothing valid, return None.
"""
from __future__ import annotations

import os
import re
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

_BASE    = "https://api.hunter.io/v2"
_TIMEOUT = 10

# ── Email quality helpers ─────────────────────────────────────────────────────

_PERSONAL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "yahoo.com", "yahoo.in", "yahoo.co.in",
    "hotmail.com", "hotmail.in", "outlook.com", "outlook.in",
    "rediffmail.com", "icloud.com", "protonmail.com",
    "live.com", "msn.com", "aol.com",
})

_DISPOSABLE_PATTERNS = re.compile(
    r'(?i)(mailinator|guerrillamail|tempmail|throwaway|yopmail|trashmail|sharklasers)',
)

_PREFERRED_LOCALS: tuple[str, ...] = (
    "info", "contact", "sales", "hello", "enquiry", "enquire",
    "support", "office", "business", "admin", "mail",
)

_JUNK_LOCALS: frozenset[str] = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "bounce", "bounces", "mailer-daemon", "postmaster",
    "unsubscribe", "webmaster", "hostmaster", "abuse", "spam",
})


def _get_key() -> str:
    """Always read from env fresh — supports runtime key updates."""
    return os.getenv("HUNTER_API_KEY", "").strip()


def _is_personal_email(email: str) -> bool:
    dom = email.split("@")[-1].lower()
    return dom in _PERSONAL_DOMAINS or bool(_DISPOSABLE_PATTERNS.search(dom))


def _is_junk_email(email: str) -> bool:
    local = email.split("@")[0].lower()
    return local in _JUNK_LOCALS or local.isdigit() or len(local) < 2


def _email_score(email: str) -> int:
    local = email.split("@")[0].lower()
    for i, pref in enumerate(_PREFERRED_LOCALS):
        if local == pref or local.startswith(pref):
            return i
    return len(_PREFERRED_LOCALS)


def _domain_matches(email: str, company_domain: str) -> bool:
    if not email or not company_domain:
        return False
    edom = email.split("@")[-1].lower()
    return edom == company_domain or edom.endswith("." + company_domain)


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [HUNTER] {msg}", flush=True)


def _get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_TIMEOUT),
        limits=httpx.Limits(max_connections=10),
        follow_redirects=True,
    )


# ── Internal API wrappers ─────────────────────────────────────────────────────

async def _domain_search(domain: str, limit: int = 10) -> list[dict]:
    """GET /domain-search — find known emails at a domain."""
    key = _get_key()
    if not key or not domain:
        return []
    async with _get_client() as client:
        try:
            resp = await client.get(
                f"{_BASE}/domain-search",
                params={"domain": domain, "limit": limit, "api_key": key},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 401:
                _log(f"AUTH FAILED 401 — HUNTER_API_KEY is invalid or expired")
                return []
            if resp.status_code == 429:
                _log(f"Rate limit hit")
                return []
            if resp.status_code == 402:
                _log(f"Plan limit reached (402)")
                return []
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("emails", []) or []
        except httpx.TimeoutException:
            _log(f"Timeout on domain-search for {domain}")
            return []
        except Exception as exc:
            _log(f"Error on domain-search {domain}: {exc}")
            return []


async def _email_finder(domain: str, company: str) -> Optional[str]:
    """GET /email-finder — guess a generic company email."""
    key = _get_key()
    if not key or not domain:
        return None
    async with _get_client() as client:
        try:
            resp = await client.get(
                f"{_BASE}/email-finder",
                params={"domain": domain, "company": company, "api_key": key},
                timeout=_TIMEOUT,
            )
            if resp.status_code in (401, 402, 429):
                return None
            resp.raise_for_status()
            data = resp.json()
            email = (data.get("data") or {}).get("email")
            if email and not _is_personal_email(email) and not _is_junk_email(email):
                return email.lower()
            return None
        except Exception:
            return None


async def _verify_email(email: str) -> str:
    """GET /email-verifier — check deliverability."""
    key = _get_key()
    if not key or not email:
        return "unknown"
    async with _get_client() as client:
        try:
            resp = await client.get(
                f"{_BASE}/email-verifier",
                params={"email": email, "api_key": key},
                timeout=_TIMEOUT,
            )
            if resp.status_code in (401, 402, 429):
                return "unknown"
            resp.raise_for_status()
            data = resp.json()
            return (data.get("data") or {}).get("status", "unknown")
        except Exception:
            return "unknown"


# ── Public entry point ────────────────────────────────────────────────────────

async def find_email(
    company_name: str,
    domain: str,
) -> tuple[Optional[str], str, str]:
    """
    Find the best business email for a company using Hunter.

    Returns (email_or_None, source_url, verification_status).
    Statuses: "hunter_valid" | "hunter_accept_all" | "hunter_domain_match" |
              "hunter_failed" | "skipped" | "auth_failed"
    """
    key = _get_key()
    if not key:
        _log(f"HUNTER_API_KEY not set — skipping for {company_name!r}")
        return None, "", "skipped"
    if not domain:
        return None, "", "skipped"

    source = f"https://hunter.io (domain: {domain})"
    _log(f"company={company_name!r} domain={domain} — starting domain-search")

    # Step 1: domain-search
    emails_raw = await _domain_search(domain, limit=15)

    if emails_raw is None:
        # Auth failed
        return None, "", "auth_failed"

    candidates: list[str] = []
    for entry in emails_raw:
        addr = (entry.get("value") or "").lower().strip()
        if not addr:
            continue
        if not _domain_matches(addr, domain):
            continue
        if _is_personal_email(addr) or _is_junk_email(addr):
            continue
        candidates.append(addr)

    candidates.sort(key=_email_score)

    if candidates:
        best = candidates[0]
        status = await _verify_email(best)
        if status in ("valid", "accept_all"):
            _log(f"company={company_name!r} domain={domain} status=HIT email={best!r} verified={status}")
            return best, source, f"hunter_{status}"
        _log(f"company={company_name!r} domain={domain} status=HIT email={best!r} verified=domain_match")
        return best, source, "hunter_domain_match"

    # Step 2: email-finder
    found = await _email_finder(domain, company_name)
    if found and _domain_matches(found, domain):
        status = await _verify_email(found)
        vs = f"hunter_{status}" if status != "unknown" else "hunter_domain_match"
        _log(f"company={company_name!r} domain={domain} status=HIT(finder) email={found!r}")
        return found, source, vs

    _log(f"company={company_name!r} domain={domain} status=NO_HIT")
    return None, "", "hunter_failed"
