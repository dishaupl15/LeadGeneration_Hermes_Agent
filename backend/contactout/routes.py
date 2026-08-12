"""
contactout/routes.py
─────────────────────
FastAPI router for the standalone ContactOut people-enrichment module.
Mounted at /contactout in app/main.py.

Endpoints
─────────
GET  /contactout/auth-test        Live auth test via /v1/stats
POST /contactout/search-contacts  Find decision-maker contacts for a company

Rules
─────
- Never reveal the API token in responses or logs
- Does NOT import from google_maps/, people_data_labs/, prospeo/, app/services/
- Does NOT modify any existing pipeline
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from contactout.client import get_stats
from contactout.config import (
    CONTACTOUT_MAX_CONTACTS_PER_COMPANY,
    CONTACTOUT_TIMEOUT_SECONDS,
    is_configured,
    token_length,
    status_message,
)
from contactout.people_search import search_contacts
from contactout.schemas import (
    ContactOutAuthTestResponse,
    ContactOutSearchInput,
    ContactOutSearchResult,
)

router = APIRouter(
    prefix="/contactout",
    tags=["ContactOut"],
)


# ── Auth test ─────────────────────────────────────────────────────────────────

@router.get(
    "/auth-test",
    summary="Live ContactOut authentication test (uses /v1/stats)",
    response_model=ContactOutAuthTestResponse,
    tags=["ContactOut"],
)
async def contactout_auth_test():
    """
    Calls GET /v1/stats on the ContactOut API.
    Used to verify the token without consuming search credits.

    Returns:
        CONTACTOUT_AUTHENTICATION: SUCCESS or FAILED
        CONTACTOUT_TOKEN_LENGTH:   integer, never the token itself
    """
    configured = is_configured()

    if not configured:
        return ContactOutAuthTestResponse(
            CONTACTOUT_CONFIGURED=False,
            CONTACTOUT_TOKEN_LENGTH=0,
            CONTACTOUT_HTTP_STATUS=None,
            CONTACTOUT_AUTHENTICATION="FAILED",
            message="CONTACTOUT_API_TOKEN is not set. Add it to backend/.env and restart.",
        )

    stats, error_code = await get_stats()

    if error_code is None and stats is not None:
        return ContactOutAuthTestResponse(
            CONTACTOUT_CONFIGURED=True,
            CONTACTOUT_TOKEN_LENGTH=token_length(),
            CONTACTOUT_HTTP_STATUS=200,
            CONTACTOUT_AUTHENTICATION="SUCCESS",
            message="ContactOut authentication successful.",
        )

    _http_map = {
        "auth_failed":   400,
        "bad_request":   401,
        "no_credits":    403,
        "no_access":     403,
        "rate_limited":  429,
        "timeout":       None,
        "network_error": None,
        "server_error":  500,
    }
    http_status = _http_map.get(error_code)

    if error_code == "auth_failed":
        msg = (
            "CONTACTOUT_API_TOKEN is rejected by the ContactOut API. "
            "Check or regenerate your token at https://app.contactout.com/settings/api"
        )
    elif error_code == "rate_limited":
        msg = "Rate limited (429). Wait and retry."
    elif error_code == "no_credits":
        msg = "Out of ContactOut credits (403)."
    elif error_code == "timeout":
        msg = "Request timed out. Check network connectivity."
    else:
        msg = f"Authentication check failed (error_code={error_code!r})."

    return ContactOutAuthTestResponse(
        CONTACTOUT_CONFIGURED=True,
        CONTACTOUT_TOKEN_LENGTH=token_length(),
        CONTACTOUT_HTTP_STATUS=http_status,
        CONTACTOUT_AUTHENTICATION="FAILED",
        message=msg,
    )


# ── Contact search ────────────────────────────────────────────────────────────

@router.post(
    "/search-contacts",
    summary="Find decision-maker contacts for a company via ContactOut",
    response_model=ContactOutSearchResult,
    status_code=status.HTTP_200_OK,
    tags=["ContactOut"],
)
async def contactout_search_contacts(payload: ContactOutSearchInput):
    """
    Single-step ContactOut workflow:

    POST /v1/people/search with reveal_info=True
      → Finds current employees matching priority decision-maker titles
      → Returns actual emails and phones revealed in the same call

    Contact priority:
      Founder / Co-Founder / Owner → CEO / MD → COO → Director
      → HR Head → Talent Acquisition → Recruitment → HR Manager

    Rules:
      - Company name + domain always required (no open-database searches)
      - contact_availability flag does NOT guarantee actual contact data
      - Only actual email/phone values returned by ContactOut are saved
      - Capped at CONTACTOUT_MAX_CONTACTS_PER_COMPANY (default 2)
    """
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ContactOut not configured. Add CONTACTOUT_API_TOKEN to backend/.env and restart.",
        )

    try:
        result = await search_contacts(
            company_name=payload.company_name,
            domain=payload.domain,
            max_contacts=CONTACTOUT_MAX_CONTACTS_PER_COMPANY,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ContactOut search error: {type(exc).__name__}: {exc}",
        )

    if result.error == "auth_failed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "ContactOut authentication failed. "
                "The CONTACTOUT_API_TOKEN in backend/.env is invalid or revoked. "
                "Check/regenerate at https://app.contactout.com/settings/api"
            ),
        )

    return result
