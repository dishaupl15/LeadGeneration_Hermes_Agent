"""
people_data_labs/routes.py
───────────────────────────
FastAPI router for the isolated PDL contact-discovery module.

Endpoints
─────────
GET  /pdl/health          API key status + module config
GET  /pdl/auth-test       Standalone authentication test (1 PDL request, size=1)
POST /pdl/search-company  Find decision-makers for a given company

Rules
─────
- Never import from google_maps/, app/services/, or src/routes/
- The existing pipeline (POST /leads/generate-leads) is UNTOUCHED
- Never reveal the API key in responses
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from people_data_labs.config import (
    PDL_MAX_CONTACTS_PER_COMPANY,
    PDL_TIMEOUT_SECONDS,
    is_configured,
    key_length,
    status_message,
)
from people_data_labs.people_search import search_company_contacts
from people_data_labs.schemas import (
    PDLCompanyInput,
    PDLHealthResponse,
    PeopleDataLabsResult,
)

router = APIRouter(
    prefix="/pdl",
    tags=["People Data Labs"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@router.get(
    "/health",
    summary="PDL module health check",
    response_model=PDLHealthResponse,
    tags=["People Data Labs"],
)
def pdl_health():
    """Returns key configuration status. Never reveals the actual key."""
    configured = is_configured()
    return PDLHealthResponse(
        module="people_data_labs",
        configured=configured,
        status="ready" if configured else "no_key",
        message=status_message(),
        max_contacts_per_company=PDL_MAX_CONTACTS_PER_COMPANY,
        timeout_seconds=PDL_TIMEOUT_SECONDS,
    )


# ── Auth test ─────────────────────────────────────────────────────────────────

@router.get(
    "/auth-test",
    summary="Standalone PDL authentication test (consumes 1 credit on success)",
    response_model=dict,
    tags=["People Data Labs"],
)
async def pdl_auth_test():
    """
    Sends exactly ONE minimal PDL Person Search request (size=1) to verify
    the API key is accepted.

    Returns:
        PDL_CONFIGURED     – true/false
        PDL_KEY_LENGTH     – integer, never the key itself
        PDL_HTTP_STATUS    – actual HTTP status code
        PDL_AUTHENTICATION – SUCCESS or FAILED
        message            – human-readable explanation
    """
    configured = is_configured()

    if not configured:
        return {
            "PDL_CONFIGURED":     False,
            "PDL_KEY_LENGTH":     0,
            "PDL_HTTP_STATUS":    None,
            "PDL_AUTHENTICATION": "FAILED",
            "message": "PDL_API_KEY is not set. Add it to backend/.env and restart.",
        }

    from people_data_labs.client import person_search

    test_query = {
        "bool": {
            "must": [
                {"term": {"job_company_website": "peopledatalabs.com"}}
            ]
        }
    }

    data, auth_failed, rate_limited = await person_search(test_query, size=1)

    if auth_failed:
        return {
            "PDL_CONFIGURED":     True,
            "PDL_KEY_LENGTH":     key_length(),
            "PDL_HTTP_STATUS":    401,
            "PDL_AUTHENTICATION": "FAILED",
            "message": (
                "The PDL key is rejected by the PDL API. "
                "This is an API credential problem, not a query problem. "
                "Verify or regenerate the key at https://dashboard.peopledatalabs.com/api-keys"
            ),
        }

    if rate_limited:
        return {
            "PDL_CONFIGURED":     True,
            "PDL_KEY_LENGTH":     key_length(),
            "PDL_HTTP_STATUS":    429,
            "PDL_AUTHENTICATION": "UNKNOWN — rate limited",
            "message": "PDL rate limited. Wait and retry.",
        }

    return {
        "PDL_CONFIGURED":     True,
        "PDL_KEY_LENGTH":     key_length(),
        "PDL_HTTP_STATUS":    200,
        "PDL_AUTHENTICATION": "SUCCESS",
        "records_returned":   len(data),
        "message":            "PDL authentication successful.",
    }


# ── Company contact search ────────────────────────────────────────────────────

@router.post(
    "/search-company",
    summary="Find decision-maker contacts for a company via People Data Labs",
    response_model=PeopleDataLabsResult,
    status_code=status.HTTP_200_OK,
    tags=["People Data Labs"],
)
async def search_company(payload: PDLCompanyInput):
    """
    Search PDL for business decision-makers at the given company.

    Contact priority (Tier A first, then Tier B if slots remain):
      Tier A: Founder / Co-Founder / Owner / CEO / MD / Director
      Tier B: HR VP / Head of HR / Talent Acquisition / HR Manager

    Rules:
    - Domain match is preferred over name match
    - Only current employment accepted
    - Emails returned only when PDL provides them — never fabricated
    - Person phone kept separate from company phone
    - Capped at PDL_MAX_CONTACTS_PER_COMPANY (default 2)
    """
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDL not configured. Add PDL_API_KEY to backend/.env and restart.",
        )

    try:
        result = await search_company_contacts(
            company_name=payload.company_name,
            domain=payload.domain,
            website=payload.website,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PDL search error: {type(exc).__name__}: {exc}",
        )

    # Surface auth failure as a proper HTTP error so callers know it's a credential issue
    if result.error == "auth_failed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "PDL authentication failed (401). "
                "The API key in backend/.env is invalid or revoked. "
                "Regenerate it at https://dashboard.peopledatalabs.com/api-keys"
            ),
        )

    return result
