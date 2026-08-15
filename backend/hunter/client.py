"""
hunter/client.py
─────────────────
Low-level async HTTP client for Hunter.io API v2.

Endpoints exposed:
  email_finder(domain, first_name, last_name)
      GET /v2/email-finder?domain=&first_name=&last_name=&api_key=
      Returns a single guessed email for the person at that domain.

  domain_search(domain, limit)
      GET /v2/domain-search?domain=&limit=&api_key=
      Returns all known emails at a domain — used by the people waterfall.

Design rules:
  - The API key is NEVER logged, printed, or included in error messages.
  - Credentials are read fresh on every call via get_api_key().
  - Every HTTP/timeout/parse error is caught and returned as an error code.
  - Never raises — always returns a (data, error_code) tuple.
  - error_code is None on success, otherwise one of:
      "auth_failed"   — HTTP 401
      "no_credits"    — HTTP 402
      "rate_limited"  — HTTP 429
      "http_<N>"      — other non-2xx status
      "timeout"       — httpx.TimeoutException
      "<ExcType>"     — any other exception
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from hunter.config import (
    HUNTER_BASE_URL,
    HUNTER_MAX_RESULTS,
    HUNTER_TIMEOUT,
    get_api_key,
    is_configured,
)


# ── Email quality helpers ─────────────────────────────────────────────────────

_PERSONAL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "yahoo.com", "yahoo.in", "yahoo.co.in",
    "hotmail.com", "hotmail.in", "outlook.com", "outlook.in",
    "rediffmail.com", "icloud.com", "protonmail.com",
    "live.com", "msn.com", "aol.com",
})

_DISPOSABLE_RE = re.compile(
    r"(?i)(mailinator|guerrillamail|tempmail|throwaway|yopmail|trashmail|sharklasers)",
)

_JUNK_LOCALS: frozenset[str] = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "bounce", "bounces", "mailer-daemon", "postmaster",
    "unsubscribe", "webmaster", "hostmaster", "abuse", "spam",
    "billing", "crm-support", "freshbots-support", "dpo",
    "ir", "newsletter",
})


def is_valid_email(email: str) -> bool:
    """Return True when the email looks syntactically valid and non-junk."""
    if not email or "@" not in email:
        return False
    local, _, domain = email.strip().lower().partition("@")
    if not domain or "." not in domain:
        return False
    if local in _JUNK_LOCALS or len(local) < 2:
        return False
    if domain in _PERSONAL_DOMAINS or bool(_DISPOSABLE_RE.search(domain)):
        return False
    return True


def domain_matches(email: str, company_domain: str) -> bool:
    """Return True when the email belongs to the expected company domain."""
    if not email or not company_domain:
        return False
    edom = email.strip().lower().split("@")[-1]
    dom  = company_domain.strip().lower().lstrip("www.")
    return edom == dom or edom.endswith("." + dom)


def _hunter_confidence(score: int) -> float:
    """Convert Hunter 0–100 score to 0.0–1.0 confidence."""
    return round(min(max(score, 0), 100) / 100, 2)


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [HUNTER] {msg}", flush=True)


def _handle_status(resp: httpx.Response) -> Optional[str]:
    """Return an error code for non-success HTTP statuses, or None if OK."""
    if resp.status_code == 200:
        return None
    if resp.status_code == 401:
        _log("Auth failed (401) — HUNTER_API_KEY is invalid or expired")
        return "auth_failed"
    if resp.status_code == 402:
        _log("Plan limit reached (402) — no credits remaining")
        return "no_credits"
    if resp.status_code == 429:
        _log("Rate limited (429)")
        return "rate_limited"
    _log(f"Unexpected HTTP {resp.status_code}")
    return f"http_{resp.status_code}"


# ── /email-finder ─────────────────────────────────────────────────────────────

async def email_finder(
    domain: str,
    first_name: str,
    last_name: str,
) -> tuple[Optional[dict], Optional[str]]:
    """
    GET /v2/email-finder?domain=&first_name=&last_name=&api_key=

    Returns:
        (contact_dict, None)         on success — contact_dict has keys:
                                       email, first_name, last_name,
                                       score (0–100), sources
        (None, error_code)           on any failure
        (None, "no_result")          when Hunter found no email for the person
        (None, "not_configured")     when HUNTER_API_KEY is not set
        (None, "no_domain")          when domain is empty
        (None, "no_name")            when both first_name and last_name are empty

    SECURITY: The api_key is passed as a query parameter (Hunter's standard
    approach) and is NEVER printed or logged by this function.
    """
    if not is_configured():
        return None, "not_configured"
    if not domain:
        return None, "no_domain"
    if not first_name and not last_name:
        return None, "no_name"

    key = get_api_key()
    params: dict = {
        "domain":     domain.strip().lower().lstrip("www."),
        "api_key":    key,
    }
    if first_name:
        params["first_name"] = first_name.strip()
    if last_name:
        params["last_name"] = last_name.strip()

    _log(
        f"email-finder domain={params['domain']!r} "
        f"first_name={first_name!r} last_name={last_name!r}"
    )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(HUNTER_TIMEOUT),
            follow_redirects=True,
        ) as client:
            resp = await client.get(f"{HUNTER_BASE_URL}/email-finder", params=params)
    except httpx.TimeoutException:
        _log(f"Timeout on email-finder for {domain!r}")
        return None, "timeout"
    except Exception as exc:
        _log(f"Exception on email-finder: {type(exc).__name__}")
        return None, type(exc).__name__

    err = _handle_status(resp)
    if err:
        return None, err

    try:
        body = resp.json()
    except Exception:
        return None, "parse_error"

    data = (body.get("data") or {})
    email = (data.get("email") or "").strip().lower()

    if not email:
        _log(f"No email returned by email-finder for {domain!r}")
        return None, "no_result"

    if not is_valid_email(email):
        _log(f"email-finder returned invalid/junk email {email!r} — discarded")
        return None, "no_result"

    score = int(data.get("score") or 0)
    result = {
        "email":      email,
        "first_name": (data.get("first_name") or first_name or "").strip(),
        "last_name":  (data.get("last_name")  or last_name  or "").strip(),
        "score":      score,
        "sources":    ["hunter"],
    }
    _log(
        f"email-finder HIT domain={params['domain']!r} "
        f"email={email!r} score={score}"
    )
    return result, None


# ── /domain-search ────────────────────────────────────────────────────────────

async def domain_search(
    domain: str,
    limit: int = HUNTER_MAX_RESULTS,
) -> tuple[list[dict], Optional[str]]:
    """
    GET /v2/domain-search?domain=&limit=&api_key=

    Returns:
        (contacts_list, None)        on success — each dict has:
                                       first_name, last_name, name,
                                       email, title, score, sources
        ([], error_code)             on any failure
        ([], "not_configured")       when HUNTER_API_KEY is not set
        ([], "no_domain")            when domain is empty

    SECURITY: api_key is NEVER printed or logged.
    """
    if not is_configured():
        return [], "not_configured"
    if not domain:
        return [], "no_domain"

    key    = get_api_key()
    dom    = domain.strip().lower().lstrip("www.")
    params = {"domain": dom, "limit": limit, "api_key": key}

    _log(f"domain-search domain={dom!r} limit={limit}")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(HUNTER_TIMEOUT),
            follow_redirects=True,
        ) as client:
            resp = await client.get(f"{HUNTER_BASE_URL}/domain-search", params=params)
    except httpx.TimeoutException:
        _log(f"Timeout on domain-search for {dom!r}")
        return [], "timeout"
    except Exception as exc:
        _log(f"Exception on domain-search: {type(exc).__name__}")
        return [], type(exc).__name__

    err = _handle_status(resp)
    if err:
        return [], err

    try:
        body = resp.json()
    except Exception:
        return [], "parse_error"

    entries = ((body.get("data") or {}).get("emails") or [])
    contacts: list[dict] = []

    for entry in entries:
        addr = (entry.get("value") or "").strip().lower()
        if not addr or "@" not in addr:
            continue
        if not is_valid_email(addr):
            continue
        if not domain_matches(addr, dom):
            continue

        first = (entry.get("first_name") or "").strip()
        last  = (entry.get("last_name")  or "").strip()
        name  = f"{first} {last}".strip() or None
        title = (entry.get("position") or entry.get("type") or "").strip() or None
        score = int(entry.get("confidence") or 0)

        # Skip generic/catch-all emails with no named person
        etype = (entry.get("type") or "").strip().lower()
        if not name and etype not in ("personal",):
            continue

        contacts.append({
            "first_name": first or None,
            "last_name":  last  or None,
            "name":       name,
            "title":      title,
            "email":      addr,
            "score":      score,
            "sources":    ["hunter"],
        })

    _log(f"domain-search domain={dom!r} contacts={len(contacts)}")
    return contacts, None
