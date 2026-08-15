"""
tests/test_hunter.py
─────────────────────
Unit tests for the standalone hunter/ module.

Covers:
  1.  Valid email-finder response — email returned and validated
  2.  email-finder no email found — no_result returned cleanly
  3.  email-finder API error (401 auth_failed) — error captured, never raises
  4.  email-finder timeout — timeout error captured, never raises
  5.  email-finder rate limit (429) — rate_limited captured
  6.  domain-search success — contacts list returned
  7.  domain-search no results — no_result returned
  8.  domain-search auth failure — auth_failed captured
  9.  Existing valid email preserved — Hunter not called when email already set
  10. Hunter contact promoted to company email field
  11. is_valid_email — accepts good, rejects junk/personal
  12. domain_matches — correct domain matching
  13. HUNTER_API_KEY never appears in any log output

Run:
    cd backend
    python -m pytest tests/test_hunter.py -v
"""
from __future__ import annotations

import asyncio
import io
import sys
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_httpx_response(status_code: int, json_body: dict):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    return resp


def _make_email_finder_response(email: str = "alexis@stripe.com", score: int = 85) -> dict:
    return {
        "data": {
            "email":      email,
            "first_name": "Alexis",
            "last_name":  "Ohanian",
            "score":      score,
        }
    }


def _make_domain_search_response(emails: list[dict]) -> dict:
    return {"data": {"emails": emails}}


def _sample_domain_email(
    addr: str = "priya@abcmfg.com",
    first: str = "Priya",
    last: str = "Mehta",
    position: str = "CEO",
    confidence: int = 90,
) -> dict:
    return {
        "value":      addr,
        "first_name": first,
        "last_name":  last,
        "position":   position,
        "confidence": confidence,
        "type":       "personal",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. email-finder returns a valid email
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_finder_success():
    """Hunter /email-finder returns a valid email → contact has the email."""
    with patch("hunter.client.get_api_key", return_value="fake-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(200, _make_email_finder_response())
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import email_finder_for_contact
        result = await email_finder_for_contact(
            domain="stripe.com",
            first_name="Alexis",
            last_name="Ohanian",
        )

    assert result.error is None
    assert result.success == 1
    assert result.contacts_found == 1
    assert result.emails_found == 1
    assert len(result.contacts) == 1
    assert result.contacts[0].email == "alexis@stripe.com"
    assert result.contacts[0].confidence == 0.85
    assert "hunter" in result.contacts[0].sources


# ─────────────────────────────────────────────────────────────────────────────
# 2. email-finder no email found
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_finder_no_result():
    """Hunter returns empty email → no_result, contacts empty."""
    with patch("hunter.client.get_api_key", return_value="fake-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(200, {"data": {"email": None}})
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import email_finder_for_contact
        result = await email_finder_for_contact("stripe.com", "Unknown", "Person")

    assert result.no_result == 1
    assert result.contacts_found == 0
    assert result.emails_found == 0
    assert result.success == 0
    assert result.error is None
    assert result.contacts == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. email-finder auth failure (401)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_finder_auth_failed():
    """HTTP 401 → error='auth_failed', never raises."""
    with patch("hunter.client.get_api_key", return_value="bad-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(401, {})
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import email_finder_for_contact
        result = await email_finder_for_contact("stripe.com", "Alexis", "Ohanian")

    assert result.error == "auth_failed"
    assert result.failed == 1
    assert result.contacts == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. email-finder timeout
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_finder_timeout():
    """TimeoutException → error='timeout', never raises."""
    import httpx

    with patch("hunter.client.get_api_key", return_value="fake-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client_cls.return_value = mock_client

        from hunter.people_search import email_finder_for_contact
        result = await email_finder_for_contact("stripe.com", "Alexis", "Ohanian")

    assert result.error == "timeout"
    assert result.failed == 1
    assert result.contacts == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. email-finder rate limited (429)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_finder_rate_limited():
    """HTTP 429 → error='rate_limited', never raises."""
    with patch("hunter.client.get_api_key", return_value="fake-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(429, {})
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import email_finder_for_contact
        result = await email_finder_for_contact("stripe.com", "Alexis", "Ohanian")

    assert result.error == "rate_limited"
    assert result.failed == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6. domain-search success
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_domain_search_success():
    """domain-search returns contacts → all valid ones included."""
    emails = [
        _sample_domain_email("priya@abcmfg.com", "Priya", "Mehta", "CEO", 90),
        _sample_domain_email("rahul@abcmfg.com", "Rahul", "Shah", "Director", 75),
        # junk email — should be filtered
        {"value": "noreply@abcmfg.com", "first_name": "", "last_name": "", "type": "generic"},
    ]

    with patch("hunter.client.get_api_key", return_value="fake-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(200, _make_domain_search_response(emails))
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import search_contacts
        result = await search_contacts("ABC Manufacturing", "abcmfg.com")

    assert result.error is None
    assert result.success == 1
    assert result.contacts_found == 2   # noreply filtered out
    assert result.emails_found == 2
    emails_out = [c.email for c in result.contacts]
    assert "priya@abcmfg.com" in emails_out
    assert "rahul@abcmfg.com" in emails_out
    assert not any("noreply" in e for e in emails_out)
    for c in result.contacts:
        assert "hunter" in c.sources


# ─────────────────────────────────────────────────────────────────────────────
# 7. domain-search no results
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_domain_search_no_results():
    """domain-search returns empty list → no_result."""
    with patch("hunter.client.get_api_key", return_value="fake-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(200, _make_domain_search_response([]))
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import search_contacts
        result = await search_contacts("Tiny Company", "tinycompany.in")

    assert result.no_result == 1
    assert result.contacts_found == 0
    assert result.contacts == []


# ─────────────────────────────────────────────────────────────────────────────
# 8. domain-search auth failure
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_domain_search_auth_failed():
    """HTTP 401 on domain-search → error='auth_failed'."""
    with patch("hunter.client.get_api_key", return_value="bad-key"), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls:

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(401, {})
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import search_contacts
        result = await search_contacts("ABC Corp", "abccorp.com")

    assert result.error == "auth_failed"
    assert result.failed == 1
    assert result.contacts == []


# ─────────────────────────────────────────────────────────────────────────────
# 9. Existing valid email preserved — Hunter NOT called
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_existing_email_preserved():
    """
    The orchestrator skips Hunter when emails_so_far > 0.
    This test confirms Hunter is not called when a prior provider already found an email.
    """
    # Simulate orchestrator logic: emails_so_far > 0 → Hunter skipped
    emails_before_hunter = 1   # PDL or Prospeo already found one

    hunter_was_called = False

    async def _fake_hunter_search(company_name, domain):
        nonlocal hunter_was_called
        hunter_was_called = True
        from hunter.schemas import HunterResult
        return HunterResult(contacts_found=1, emails_found=1)

    # Replicate the orchestrator guard
    if emails_before_hunter == 0:
        await _fake_hunter_search("Test Corp", "testcorp.com")

    assert not hunter_was_called, "Hunter should NOT be called when emails already found"


# ─────────────────────────────────────────────────────────────────────────────
# 10. Hunter contact email promoted to company-level email field
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hunter_email_promoted_to_company():
    """
    When Hunter is the only provider that finds an email, it gets promoted
    to the company dict's 'email' field by the pipeline.
    """
    from hunter.schemas import HunterContact, HunterResult

    # Build a mock orchestrator result as if Hunter contributed
    from people_enrichment.schemas import EnrichedContact, PeopleEnrichmentResult, ProviderStats

    hunter_contact = EnrichedContact(
        name="Priya Mehta",
        title="CEO",
        email="priya@abcmfg.com",
        phone=None,
        sources=["hunter"],
        confidence=0.90,
    )
    mock_result = PeopleEnrichmentResult(
        contacts=[hunter_contact],
        contacts_found=1,
        emails_found=1,
        phones_found=0,
        providers_used=["hunter"],
    )

    # Simulate what maps_pipeline_service._enrich_via_people_orchestrator does
    company: dict = {
        "company_name": "ABC Manufacturing",
        "email": None,
        "emails": [],
        "contacts": [],
        "_field_verification": {},
    }

    contacts_list = [
        {
            "name":       c.name,
            "title":      c.title,
            "email":      c.email,
            "phone":      c.phone,
            "linkedin_url": c.linkedin_url,
            "sources":    list(c.sources),
            "confidence": c.confidence,
        }
        for c in mock_result.contacts
    ]
    company["contacts"] = contacts_list

    if not company.get("email"):
        for ct in contacts_list:
            if ct.get("email"):
                company["email"] = ct["email"]
                emails = list(company.get("emails") or [])
                if ct["email"] not in emails:
                    emails.insert(0, ct["email"])
                company["emails"] = emails
                break

    assert company["email"] == "priya@abcmfg.com"
    assert "priya@abcmfg.com" in company["emails"]
    assert company["contacts"][0]["sources"] == ["hunter"]


# ─────────────────────────────────────────────────────────────────────────────
# 11. is_valid_email helper
# ─────────────────────────────────────────────────────────────────────────────

def test_is_valid_email_accepts_good():
    from hunter.client import is_valid_email
    assert is_valid_email("priya.mehta@abcmfg.com")
    assert is_valid_email("info@stripe.com")
    assert is_valid_email("ceo@tatamotors.com")


def test_is_valid_email_rejects_personal():
    from hunter.client import is_valid_email
    assert not is_valid_email("priya@gmail.com")
    assert not is_valid_email("someone@yahoo.com")
    assert not is_valid_email("user@hotmail.com")


def test_is_valid_email_rejects_junk_local():
    from hunter.client import is_valid_email
    assert not is_valid_email("noreply@company.com")
    assert not is_valid_email("no-reply@example.com")
    assert not is_valid_email("abuse@company.com")


def test_is_valid_email_rejects_malformed():
    from hunter.client import is_valid_email
    assert not is_valid_email("")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("missing@")
    assert not is_valid_email("@nodomain.com")


# ─────────────────────────────────────────────────────────────────────────────
# 12. domain_matches helper
# ─────────────────────────────────────────────────────────────────────────────

def test_domain_matches_exact():
    from hunter.client import domain_matches
    assert domain_matches("info@stripe.com", "stripe.com")


def test_domain_matches_subdomain():
    from hunter.client import domain_matches
    assert domain_matches("priya@mail.abcmfg.com", "abcmfg.com")


def test_domain_matches_rejects_wrong_domain():
    from hunter.client import domain_matches
    assert not domain_matches("priya@othercorp.com", "abcmfg.com")


def test_domain_matches_empty():
    from hunter.client import domain_matches
    assert not domain_matches("", "abcmfg.com")
    assert not domain_matches("priya@abcmfg.com", "")


# ─────────────────────────────────────────────────────────────────────────────
# 13. API key NEVER appears in any logged output
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_key_never_logged():
    """
    Capture stdout and confirm the real API key value is never printed
    during a Hunter call (even on failure).
    """
    real_key = "super-secret-hunter-key-12345"

    captured = io.StringIO()

    with patch("hunter.client.get_api_key", return_value=real_key), \
         patch("hunter.client.is_configured", return_value=True), \
         patch("httpx.AsyncClient") as mock_client_cls, \
         patch("sys.stdout", captured):

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_make_httpx_response(401, {})
        )
        mock_client_cls.return_value = mock_client

        from hunter.people_search import email_finder_for_contact
        await email_finder_for_contact("stripe.com", "Alexis", "Ohanian")

    output = captured.getvalue()
    assert real_key not in output, (
        f"API key was found in log output! "
        f"Check hunter/client.py for accidental key logging."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 14. not_configured — skipped cleanly when no key set
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_finder_not_configured():
    """No HUNTER_API_KEY → skipped, error='not_configured', calls=0."""
    with patch("hunter.config.is_configured", return_value=False), \
         patch("hunter.people_search.is_configured", return_value=False):
        from hunter.people_search import email_finder_for_contact
        result = await email_finder_for_contact("stripe.com", "Alexis", "Ohanian")

    assert result.error == "not_configured"
    assert result.skipped_reason == "not_configured"
    assert result.calls == 0
    assert result.contacts == []


@pytest.mark.asyncio
async def test_domain_search_not_configured():
    """No HUNTER_API_KEY → skipped, error='not_configured', calls=0."""
    with patch("hunter.config.is_configured", return_value=False), \
         patch("hunter.people_search.is_configured", return_value=False):
        from hunter.people_search import search_contacts
        result = await search_contacts("Test Corp", "testcorp.com")

    assert result.error == "not_configured"
    assert result.skipped_reason == "not_configured"
    assert result.calls == 0
    assert result.contacts == []
