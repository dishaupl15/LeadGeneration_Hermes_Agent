"""
prospeo/routes.py
──────────────────
FastAPI router for the standalone Prospeo people-enrichment module.
Mounted at /prospeo in app/main.py.

Endpoints
─────────
GET  /prospeo/health          Key status + module config
GET  /prospeo/auth-test       Live auth test (free — uses /account-information)
POST /prospeo/search-contacts Find decision-maker contacts for a company

Rules
─────
- Never reveal the API key in responses or logs
- Does NOT import from google_maps/, people_data_labs/, app/services/, or src/
- Does NOT modify any existing pipeline
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from prospeo.client import get_account_info
from prospeo.config import (
    PROSPEO_MAX_CONTACTS_PER_COMPANY,
    PROSPEO_TIMEOUT_SECONDS,
    is_configured,
    key_length,
    status_message,
)
from prospeo.people_search import search_contacts
from prospeo.schemas import (
    ProspeoAuthTestResponse,
    ProspeoHealthResponse,
    ProspeoSearchInput,
    ProspeoSearchResult,
)

router = APIRouter(
    prefix="/prospeo",
    tags=["Prospeo"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@router.get(
    "/health",
    summary="Prospeo module health check",
    response_model=ProspeoHealthResponse,
    tags=["Prospeo"],
)
def prospeo_health():
    """Returns API key configuration status. Never reveals the key."""
    configured = is_configured()
    return ProspeoHealthResponse(
        module="prospeo",
        configured=configured,
        status="ready" if configured else "no_key",
        message=status_message(),
        max_contacts_per_company=PROSPEO_MAX_CONTACTS_PER_COMPANY,
        timeout_seconds=PROSPEO_TIMEOUT_SECONDS,
    )


# ── Auth test ─────────────────────────────────────────────────────────────────

@router.get(
    "/auth-test",
    summary="Live Prospeo authentication test (free — uses /account-information)",
    response_model=ProspeoAuthTestResponse,
    tags=["Prospeo"],
)
async def prospeo_auth_test():
    """
    Calls GET /account-information on the Prospeo API.
    This endpoint is free (0 credits) and is the safest way to verify the key.

    Returns:
        PROSPEO_AUTHENTICATION: SUCCESS or FAILED
        PROSPEO_KEY_LENGTH:     integer, never the key itself
        plan / remaining_credits on success
    """
    configured = is_configured()

    if not configured:
        return ProspeoAuthTestResponse(
            PROSPEO_CONFIGURED=False,
            PROSPEO_KEY_LENGTH=0,
            PROSPEO_HTTP_STATUS=None,
            PROSPEO_AUTHENTICATION="FAILED",
            message="PROSPEO_API_KEY is not set. Add it to backend/.env and restart.",
        )

    info, error_code = await get_account_info()

    if error_code is None and info is not None:
        return ProspeoAuthTestResponse(
            PROSPEO_CONFIGURED=True,
            PROSPEO_KEY_LENGTH=key_length(),
            PROSPEO_HTTP_STATUS=200,
            PROSPEO_AUTHENTICATION="SUCCESS",
            plan=info.get("current_plan"),
            remaining_credits=info.get("remaining_credits"),
            message="Prospeo authentication successful.",
        )

    # Map error_code → HTTP status approximation for the test report
    _http_map = {
        "auth_failed":    400,
        "rate_limited":   429,
        "timeout":        None,
        "network_error":  None,
        "server_error":   500,
    }
    http_status = _http_map.get(error_code)

    if error_code == "auth_failed":
        msg = (
            "PROSPEO_API_KEY is rejected by the Prospeo API. "
            "This is an API credential problem, not a code problem. "
            "Check/regenerate the key at https://prospeo.io/api-keys"
        )
    elif error_code == "rate_limited":
        msg = "Rate limited (429). Wait and retry."
    elif error_code == "timeout":
        msg = "Request timed out. Check network connectivity."
    else:
        msg = f"Authentication check failed (error_code={error_code!r})."

    return ProspeoAuthTestResponse(
        PROSPEO_CONFIGURED=True,
        PROSPEO_KEY_LENGTH=key_length(),
        PROSPEO_HTTP_STATUS=http_status,
        PROSPEO_AUTHENTICATION="FAILED",
        message=msg,
    )


# ── Contact search ────────────────────────────────────────────────────────────

@router.post(
    "/search-contacts",
    summary="Find decision-maker contacts for a company via Prospeo",
    response_model=ProspeoSearchResult,
    status_code=status.HTTP_200_OK,
    tags=["Prospeo"],
)
async def prospeo_search_contacts(payload: ProspeoSearchInput):
    """
    Two-step Prospeo workflow:

    1. Search Person — find relevant decision-makers by company + seniority
    2. Bulk Enrich Person — reveal email + mobile for selected person_ids

    Contact priority:
      Founder / Co-Founder / Owner → CEO / MD → COO → Director
      → HR Head → Talent Acquisition → Recruitment → HR Manager

    Rules:
      - Domain match preferred over name match
      - Email and mobile only returned when Prospeo confirms them
      - Person phone kept separate from company phone (never copied)
      - Capped at PROSPEO_MAX_CONTACTS_PER_COMPANY (default 2)
    """
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prospeo not configured. Add PROSPEO_API_KEY to backend/.env and restart.",
        )

    try:
        result = await search_contacts(
            company_name=payload.company_name,
            domain=payload.domain,
            website=payload.website,
            max_contacts=PROSPEO_MAX_CONTACTS_PER_COMPANY,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prospeo search error: {type(exc).__name__}: {exc}",
        )

    # Surface auth failure as a proper HTTP error
    if result.error == "auth_failed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Prospeo authentication failed. "
                "The PROSPEO_API_KEY in backend/.env is invalid or revoked. "
                "Check/regenerate at https://prospeo.io/api-keys"
            ),
        )

    return result
