"""
hunter/routes.py
─────────────────
FastAPI router for the standalone Hunter.io module.

Endpoints
─────────
GET  /hunter/health          — Key presence check (never exposes the key)
POST /hunter/email-finder    — Safe backend-only live test of /email-finder
POST /hunter/domain-search   — Safe backend-only live test of /domain-search

These endpoints exist purely for testing and diagnostics.
They are NEVER called by the lead-generation pipeline — the orchestrator
calls hunter/people_search.py directly.

SECURITY: The HUNTER_API_KEY is NEVER returned in any response body or log.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hunter.config import is_configured, key_hint
from hunter.people_search import email_finder_for_contact, search_contacts

router = APIRouter(prefix="/hunter", tags=["Hunter"])


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [HUNTER] {msg}", flush=True)


# ── Schemas ───────────────────────────────────────────────────────────────────

class EmailFinderRequest(BaseModel):
    domain:     str = Field(..., example="stripe.com")
    first_name: str = Field(..., example="Alexis")
    last_name:  str = Field(..., example="Ohanian")


class DomainSearchRequest(BaseModel):
    company_name: str           = Field(..., example="Stripe")
    domain:       str           = Field(..., example="stripe.com")


# ── GET /hunter/health ────────────────────────────────────────────────────────

@router.get(
    "/health",
    summary="Hunter.io module health check",
    response_model=dict,
)
def hunter_health() -> dict:
    """
    Returns whether HUNTER_API_KEY is configured.
    Does NOT make a live network call.
    Does NOT expose the API key value.
    """
    configured = is_configured()
    return {
        "module":          "hunter",
        "configured":      configured,
        "api_key_hint":    key_hint(),      # safe: first4…last2 chars only
        "status":          "ready" if configured else "no_key",
        "message": (
            "HUNTER_API_KEY is configured — module is ready."
            if configured else
            "HUNTER_API_KEY is not set. Add it to backend/.env and restart."
        ),
    }


# ── POST /hunter/email-finder ─────────────────────────────────────────────────

@router.post(
    "/email-finder",
    summary="Live test: Hunter /email-finder with domain + first_name + last_name",
    response_model=dict,
)
async def test_email_finder(payload: EmailFinderRequest) -> dict:
    """
    Safe backend-only live test of the Hunter /email-finder endpoint.

    Calls Hunter with the provided domain, first_name, and last_name.
    Returns the result without exposing the API key.

    Use for verifying that HUNTER_API_KEY is valid and the endpoint works.
    """
    _log(
        f"POST /hunter/email-finder "
        f"domain={payload.domain!r} "
        f"first={payload.first_name!r} last={payload.last_name!r}"
    )

    if not is_configured():
        return {
            "success": False,
            "error":   "not_configured",
            "message": "HUNTER_API_KEY is not set in backend/.env",
        }

    result = await email_finder_for_contact(
        domain=payload.domain,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )

    if result.error == "not_configured":
        return {"success": False, "error": "not_configured"}

    if result.error == "no_result" or result.no_result:
        return {
            "success":       True,
            "email_found":   False,
            "message":       "Hunter found no email for this person at that domain.",
            "calls":         result.calls,
            "no_result":     result.no_result,
        }

    if result.error or result.failed:
        return {
            "success":   False,
            "error":     result.error,
            "calls":     result.calls,
            "failed":    result.failed,
            "message":   f"Hunter call failed: {result.error}",
        }

    contact = result.contacts[0]
    return {
        "success":     True,
        "email_found": True,
        "email":       contact.email,
        "name":        contact.name,
        "score":       contact.email_score,
        "confidence":  contact.confidence,
        "calls":       result.calls,
        "success_count": result.success,
    }


# ── POST /hunter/domain-search ────────────────────────────────────────────────

@router.post(
    "/domain-search",
    summary="Live test: Hunter /domain-search for all emails at a domain",
    response_model=dict,
)
async def test_domain_search(payload: DomainSearchRequest) -> dict:
    """
    Safe backend-only live test of the Hunter /domain-search endpoint.
    Returns the list of contacts found without exposing the API key.
    """
    _log(
        f"POST /hunter/domain-search "
        f"company={payload.company_name!r} domain={payload.domain!r}"
    )

    if not is_configured():
        return {
            "success": False,
            "error":   "not_configured",
            "message": "HUNTER_API_KEY is not set in backend/.env",
        }

    result = await search_contacts(
        company_name=payload.company_name,
        domain=payload.domain,
    )

    contacts_out = [
        {
            "name":       c.name,
            "first_name": c.first_name,
            "last_name":  c.last_name,
            "title":      c.title,
            "email":      c.email,
            "score":      c.email_score,
            "confidence": c.confidence,
        }
        for c in result.contacts
    ]

    return {
        "success":        True,
        "domain":         payload.domain,
        "contacts_found": result.contacts_found,
        "emails_found":   result.emails_found,
        "contacts":       contacts_out,
        "error":          result.error,
        "calls":          result.calls,
        "no_result":      result.no_result,
        "failed":         result.failed,
    }
