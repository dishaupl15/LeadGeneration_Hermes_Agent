"""
origami/routes.py
──────────────────
FastAPI router for the standalone Origami people-enrichment module.
Mounted at /origami in app/main.py.

Endpoints
─────────
  GET  /origami/health          — Module health / key configuration status
  GET  /origami/auth-test       — Live authentication test against Origami API
  POST /origami/search-contacts — Find decision-makers for a company

Rules
─────
  - Never reveal the API key in responses or logs
  - Does NOT import from app/services/, src/routes/, or any other module
  - Does NOT modify the existing leads pipeline in any way
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from origami.client import probe_auth
from origami.config import (
    ORIGAMI_BASE_URL,
    ORIGAMI_MAX_CONTACTS,
    ORIGAMI_TIMEOUT_SECONDS,
    is_configured,
    key_length,
    status_message,
)
from origami.people_search import search_company_contacts
from origami.schemas import (
    OrigamiAuthTestResponse,
    OrigamiHealthResponse,
    OrigamiSearchInput,
    OrigamiSearchResult,
)

router = APIRouter(
    prefix="/origami",
    tags=["Origami"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@router.get(
    "/health",
    summary="Origami module health check",
    response_model=OrigamiHealthResponse,
    tags=["Origami"],
)
def origami_health():
    """Returns key configuration status. Never reveals the actual key."""
    configured = is_configured()
    return OrigamiHealthResponse(
        module          = "origami",
        configured      = configured,
        status          = "ready" if configured else "no_key",
        message         = status_message(),
        base_url        = ORIGAMI_BASE_URL,
        max_contacts    = ORIGAMI_MAX_CONTACTS,
        timeout_seconds = ORIGAMI_TIMEOUT_SECONDS,
    )


# ── Auth test ─────────────────────────────────────────────────────────────────

@router.get(
    "/auth-test",
    summary="Live Origami authentication test",
    response_model=OrigamiAuthTestResponse,
    tags=["Origami"],
)
async def origami_auth_test():
    """
    Sends a minimal probe request to verify the API key is accepted
    by the Origami API.

    Returns:
        ORIGAMI_AUTHENTICATION  — SUCCESS or FAILED
        ORIGAMI_KEY_LENGTH      — integer, never the key itself
        ORIGAMI_HTTP_STATUS     — actual HTTP status code from Origami
    """
    configured = is_configured()

    if not configured:
        return OrigamiAuthTestResponse(
            ORIGAMI_CONFIGURED     = False,
            ORIGAMI_KEY_LENGTH     = 0,
            ORIGAMI_HTTP_STATUS    = None,
            ORIGAMI_AUTHENTICATION = "FAILED",
            message = "ORIGAMI_API_KEY is not set. Add it to backend/.env and restart.",
        )

    http_status, error_code = await probe_auth()

    if error_code is None:
        return OrigamiAuthTestResponse(
            ORIGAMI_CONFIGURED     = True,
            ORIGAMI_KEY_LENGTH     = key_length(),
            ORIGAMI_HTTP_STATUS    = http_status,
            ORIGAMI_AUTHENTICATION = "SUCCESS",
            message = "Origami authentication successful.",
        )

    # Map error codes to helpful messages
    _messages = {
        "auth_failed":       "ORIGAMI_API_KEY rejected (401). Verify or regenerate at your Origami dashboard.",
        "credits_exhausted": "Origami credits exhausted (402). Top up your account.",
        "rate_limited":      "Origami rate limited (429). Wait and retry.",
        "timeout":           "Request timed out. Check network connectivity.",
        "network_error":     "Network error reaching Origami API. Check ORIGAMI_BASE_URL.",
        "server_error":      "Origami API returned a server error (5xx).",
    }
    msg = _messages.get(error_code, f"Authentication check failed (error={error_code!r}).")

    return OrigamiAuthTestResponse(
        ORIGAMI_CONFIGURED     = True,
        ORIGAMI_KEY_LENGTH     = key_length(),
        ORIGAMI_HTTP_STATUS    = http_status,
        ORIGAMI_AUTHENTICATION = "FAILED",
        message = msg,
    )


# ── Contact search ────────────────────────────────────────────────────────────

@router.post(
    "/search-contacts",
    summary="Find decision-maker contacts for a company via Origami",
    response_model=OrigamiSearchResult,
    status_code=status.HTTP_200_OK,
    tags=["Origami"],
)
async def origami_search_contacts(payload: OrigamiSearchInput):
    """
    Search Origami for business decision-makers at the given company.

    Contact priority (returned in tier order, best first):
      Tier 1 — Founder / Owner / Co-founder / Proprietor
      Tier 2 — CEO / President / MD / Chairman
      Tier 3 — COO / CFO / CTO / CMO / Director / VP
      Tier 4 — Head of / GM / Country Head
      Tier 5 — Other employees

    Rules:
      - founder_status: "found" (Tier 1), "found_decision_maker" (Tier 2-3),
                        "not_found" (Tier 4-5), "skipped" (no key), "error"
      - Emails returned only when Origami provides them — never fabricated
      - Capped at ORIGAMI_MAX_CONTACTS (default 8)
    """
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Origami not configured. Add ORIGAMI_API_KEY to backend/.env and restart.",
        )

    try:
        result = await search_company_contacts(
            company_name = payload.company_name,
            domain       = payload.domain,
            website      = payload.website,
            location     = payload.location,
            category     = payload.category,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Origami search error: {type(exc).__name__}: {exc}",
        )

    if result.error == "auth_failed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Origami authentication failed (401). "
                "The ORIGAMI_API_KEY in backend/.env is invalid or revoked. "
                "Verify it at your Origami dashboard."
            ),
        )

    return result
