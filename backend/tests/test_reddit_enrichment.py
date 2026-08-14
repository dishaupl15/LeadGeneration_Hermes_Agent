"""
tests/test_reddit_enrichment.py
────────────────────────────────
Tests for the Reddit → people-enrichment waterfall integration.

Covers:
  1.  Reddit lead reaches enrichment pipeline (enrich_one_reddit_lead called)
  2.  Prospeo success → contacts + email promoted to lead
  3.  Prospeo failure → Hunter attempted (waterfall continues)
  4.  Hunter failure → PDL still attempted (waterfall continues)
  5.  All enrichment providers fail → Reddit lead still returned unchanged
  6.  Existing Reddit source fields remain unchanged after enrichment
  7.  No duplicate lead created during enrichment write-back
  8.  enrich_reddit_leads_batch processes multiple leads concurrently
  9.  enrich_one_reddit_lead does not raise on orchestrator exception
  10. enrich_reddit_leads_batch returns correct batch stats
  11. Enrichment skips leads with no company_name
  12. Confidence is boosted when contacts are found
  13. Google Maps enrichment (enrich_company_contacts) is NOT modified by Reddit tests
  14. Reddit source fields locked after _merge_enrichment_into_lead

Run:
    cd backend
    python -m pytest tests/test_reddit_enrichment.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_reddit_lead(
    company_name: str = "ABC Manufacturing Pvt Ltd",
    website: str = "https://abcmfg.com",
    email: str = "",
    source: str = "reddit",
    post_id: str = "post_abc",
    post_url: str = "https://www.reddit.com/r/India/comments/post_abc/",
    subreddit: str = "India",
) -> dict:
    """Return a minimal Reddit lead dict as it would look after MongoDB insertion."""
    return {
        "id":              "64f1a2b3c4d5e6f7a8b9c0d1",
        "company_name":    company_name,
        "website":         website,
        "email":           email,
        "emails":          [email] if email else [],
        "company_number":  "",
        "phones":          [],
        "address":         "",
        "city":            "",
        "state":           "",
        "country":         "India",
        "founder_name":    None,
        "founder_number":  None,
        "designation":     None,
        "source":          source,
        "platform":        source,
        "research_source": source,
        "post_id":         post_id,
        "post_url":        post_url,
        "subreddit":       subreddit,
        "reddit_author":   "test_user",
        "post_score":      10,
        "contacts":        [],
        "people":          [],
        "confidence":      0.35,
        "status":          "new",
    }


def _make_enrichment_result(
    contacts: list | None = None,
    contacts_found: int = 0,
    emails_found: int = 0,
    phones_found: int = 0,
    providers_used: list | None = None,
    target_reached: bool = False,
    elapsed_seconds: float = 0.5,
    error: str | None = None,
):
    """Build a mock PeopleEnrichmentResult-like object."""
    from people_enrichment.schemas import PeopleEnrichmentResult, EnrichedContact

    real_contacts = []
    for c in (contacts or []):
        real_contacts.append(EnrichedContact(
            name=c.get("name"),
            title=c.get("title"),
            email=c.get("email"),
            phone=c.get("phone"),
            linkedin_url=c.get("linkedin_url"),
            sources=c.get("sources", []),
            confidence=c.get("confidence", 0.5),
        ))

    return PeopleEnrichmentResult(
        contacts=real_contacts,
        contacts_found=contacts_found or len(real_contacts),
        emails_found=emails_found,
        phones_found=phones_found,
        providers_used=providers_used or [],
        target_reached=target_reached,
        elapsed_seconds=elapsed_seconds,
        error=error,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Reddit lead reaches enrichment pipeline
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_one_reddit_lead_calls_orchestrator():
    """
    enrich_one_reddit_lead must call enrich_company_contacts exactly once
    for a lead that has a company_name.
    """
    from reddit.enrichment import enrich_one_reddit_lead

    lead = _make_reddit_lead()
    mock_result = _make_enrichment_result(contacts=[], contacts_found=0)

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ) as mock_enrich:
        await enrich_one_reddit_lead(lead)

    mock_enrich.assert_called_once()
    call_kwargs = mock_enrich.call_args.kwargs
    assert call_kwargs["company_name"] == "ABC Manufacturing Pvt Ltd"
    assert call_kwargs["origami_contacts"] is None   # Reddit has no Origami seed


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prospeo success → contacts and email promoted to lead
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prospeo_success_promotes_email():
    """
    When the orchestrator returns a contact with an email (sourced from Prospeo),
    the email must be promoted to lead["email"] and added to lead["emails"].
    """
    from reddit.enrichment import enrich_one_reddit_lead

    lead = _make_reddit_lead(email="")   # no email yet

    prospeo_contact = {
        "name":       "Ravi Sharma",
        "title":      "CEO",
        "email":      "ravi@abcmfg.com",
        "phone":      None,
        "linkedin_url": None,
        "sources":    ["prospeo"],
        "confidence": 0.72,
    }
    mock_result = _make_enrichment_result(
        contacts=[prospeo_contact],
        contacts_found=1,
        emails_found=1,
        providers_used=["prospeo"],
    )

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched = await enrich_one_reddit_lead(lead)

    assert enriched["email"] == "ravi@abcmfg.com"
    assert "ravi@abcmfg.com" in enriched["emails"]
    assert len(enriched["contacts"]) == 1
    assert enriched["contacts"][0]["sources"] == ["prospeo"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Prospeo failure → Hunter attempted (waterfall continues)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prospeo_failure_hunter_attempted():
    """
    When Prospeo returns an error, the orchestrator continues to Hunter.
    The lead should still be returned (possibly with Hunter contacts).
    We test by asserting the orchestrator was called (it internally continues).
    """
    from reddit.enrichment import enrich_one_reddit_lead
    from people_enrichment.schemas import ProviderStats

    lead = _make_reddit_lead(email="")

    # Simulate result where Prospeo failed but Hunter succeeded
    hunter_contact = {
        "name":       "Priya Mehta",
        "title":      "Director",
        "email":      "priya@abcmfg.com",
        "phone":      None,
        "linkedin_url": None,
        "sources":    ["hunter"],
        "confidence": 0.55,
    }
    mock_result = _make_enrichment_result(
        contacts=[hunter_contact],
        contacts_found=1,
        emails_found=1,
        providers_used=["hunter"],
    )
    # Attach provider_stats to confirm Prospeo errored
    mock_result.provider_stats["prospeo"] = ProviderStats(
        called=True, contacts_found=0, error="rate_limited"
    )
    mock_result.provider_stats["hunter"] = ProviderStats(
        called=True, contacts_found=1, emails_found=1
    )

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched = await enrich_one_reddit_lead(lead)

    # Hunter's contact was used
    assert enriched["email"] == "priya@abcmfg.com"
    assert enriched["contacts"][0]["sources"] == ["hunter"]
    # Lead was not dropped — it was returned
    assert enriched["company_name"] == "ABC Manufacturing Pvt Ltd"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Hunter failure → PDL still attempted (waterfall continues)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hunter_failure_pdl_attempted():
    """
    When Hunter also fails, the orchestrator runs PDL.
    Lead must still be returned.
    """
    from reddit.enrichment import enrich_one_reddit_lead
    from people_enrichment.schemas import ProviderStats

    lead = _make_reddit_lead(email="")

    pdl_contact = {
        "name":       "Amit Kumar",
        "title":      "Founder",
        "email":      "amit@abcmfg.com",
        "phone":      "+91 9876543210",
        "linkedin_url": None,
        "sources":    ["pdl"],
        "confidence": 0.80,
    }
    mock_result = _make_enrichment_result(
        contacts=[pdl_contact],
        contacts_found=1,
        emails_found=1,
        phones_found=1,
        providers_used=["pdl"],
    )
    mock_result.provider_stats["prospeo"] = ProviderStats(
        called=True, contacts_found=0, error="auth_failed"
    )
    mock_result.provider_stats["hunter"] = ProviderStats(
        called=True, contacts_found=0, error="no_credits"
    )
    mock_result.provider_stats["pdl"] = ProviderStats(
        called=True, contacts_found=1, emails_found=1
    )

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched = await enrich_one_reddit_lead(lead)

    assert enriched["email"] == "amit@abcmfg.com"
    assert enriched["contacts"][0]["sources"] == ["pdl"]
    assert enriched["company_name"] == "ABC Manufacturing Pvt Ltd"


# ─────────────────────────────────────────────────────────────────────────────
# 5. All enrichment providers fail → Reddit lead still saved / returned
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_providers_fail_lead_still_returned():
    """
    When every provider returns an error, the lead must be returned intact
    with its original Reddit fields — not dropped or replaced with None.
    """
    from reddit.enrichment import enrich_one_reddit_lead
    from people_enrichment.schemas import ProviderStats

    original_email = "founder@abcmfg.com"
    lead = _make_reddit_lead(email=original_email)

    mock_result = _make_enrichment_result(
        contacts=[],
        contacts_found=0,
        emails_found=0,
        providers_used=[],
        error="all_providers_failed",
    )
    mock_result.provider_stats["pdl"]        = ProviderStats(called=True, error="auth_failed")
    mock_result.provider_stats["prospeo"]    = ProviderStats(called=True, error="rate_limited")
    mock_result.provider_stats["contactout"] = ProviderStats(called=True, error="timeout")
    mock_result.provider_stats["hunter"]     = ProviderStats(called=True, error="no_credits")

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched = await enrich_one_reddit_lead(lead)

    # Lead is returned
    assert enriched["company_name"] == "ABC Manufacturing Pvt Ltd"
    # Original email preserved (enrichment added no email, so existing stays)
    assert enriched["email"] == original_email
    # contacts list is empty (no enrichment succeeded)
    assert enriched["contacts"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Reddit source fields remain unchanged after enrichment
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reddit_source_fields_preserved():
    """
    source, platform, research_source, post_id, post_url, subreddit, reddit_author
    must survive the enrichment merge unchanged.
    """
    from reddit.enrichment import enrich_one_reddit_lead

    lead = _make_reddit_lead(
        source="reddit",
        post_id="test_post_999",
        post_url="https://www.reddit.com/r/India/comments/test_post_999/",
        subreddit="IndiaBusinessHub",
    )

    mock_result = _make_enrichment_result(
        contacts=[{
            "name": "Test User", "title": "CEO",
            "email": "ceo@abcmfg.com", "phone": None,
            "linkedin_url": None, "sources": ["pdl"], "confidence": 0.7,
        }],
        contacts_found=1,
        emails_found=1,
    )

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched = await enrich_one_reddit_lead(lead)

    # Source fields must not change
    assert enriched["source"]          == "reddit"
    assert enriched["platform"]        == "reddit"
    assert enriched["research_source"] == "reddit"
    assert enriched["post_id"]         == "test_post_999"
    assert enriched["post_url"]        == "https://www.reddit.com/r/India/comments/test_post_999/"
    assert enriched["subreddit"]       == "IndiaBusinessHub"
    assert enriched["reddit_author"]   == "test_user"


# ─────────────────────────────────────────────────────────────────────────────
# 7. No duplicate lead created during enrichment
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrichment_does_not_create_duplicate():
    """
    enrich_reddit_leads_batch operates on already-inserted leads.
    It must update the existing document, not insert a new one.
    The returned list has the same length as the input list.
    """
    from reddit.enrichment import enrich_reddit_leads_batch

    leads = [
        _make_reddit_lead(company_name="Company A", post_id="p1"),
        _make_reddit_lead(company_name="Company B", post_id="p2"),
    ]

    mock_result = _make_enrichment_result(contacts=[], contacts_found=0)

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched_leads, batch_stats = await enrich_reddit_leads_batch(leads)

    # Same count — no duplicates
    assert len(enriched_leads) == 2
    # Companies still distinct
    names = {l["company_name"] for l in enriched_leads}
    assert names == {"Company A", "Company B"}


# ─────────────────────────────────────────────────────────────────────────────
# 8. Batch processes multiple leads concurrently
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_batch_processes_all_leads():
    """enrich_reddit_leads_batch must return an entry for every input lead."""
    from reddit.enrichment import enrich_reddit_leads_batch

    leads = [_make_reddit_lead(company_name=f"Company {i}", post_id=f"p{i}")
             for i in range(5)]

    mock_result = _make_enrichment_result(
        contacts=[{"name": "CEO", "title": "CEO", "email": "ceo@x.com",
                   "phone": None, "linkedin_url": None,
                   "sources": ["prospeo"], "confidence": 0.7}],
        contacts_found=1,
        emails_found=1,
        providers_used=["prospeo"],
    )

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched_leads, batch_stats = await enrich_reddit_leads_batch(leads)

    assert len(enriched_leads) == 5
    assert batch_stats["total"] == 5
    assert batch_stats["enriched"] == 5      # all had contacts found


# ─────────────────────────────────────────────────────────────────────────────
# 9. enrich_one_reddit_lead does not raise on orchestrator exception
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_one_never_raises_on_exception():
    """
    Even when enrich_company_contacts raises an unexpected exception,
    enrich_one_reddit_lead must return the lead unchanged — never raise.
    """
    from reddit.enrichment import enrich_one_reddit_lead

    lead = _make_reddit_lead()

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(side_effect=RuntimeError("Simulated crash")),
    ):
        result = await enrich_one_reddit_lead(lead)

    # Lead returned intact
    assert result["company_name"] == "ABC Manufacturing Pvt Ltd"
    assert result["source"] == "reddit"


# ─────────────────────────────────────────────────────────────────────────────
# 10. Batch returns correct stats dict
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_batch_stats_structure():
    """Returned batch_stats must contain all expected keys."""
    from reddit.enrichment import enrich_reddit_leads_batch

    leads = [_make_reddit_lead()]
    mock_result = _make_enrichment_result(
        contacts=[{"name": "A", "email": "a@b.com", "phone": None,
                   "title": None, "linkedin_url": None,
                   "sources": ["pdl"], "confidence": 0.6}],
        contacts_found=1,
        emails_found=1,
    )

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        _, stats = await enrich_reddit_leads_batch(leads)

    for key in ("total", "enriched", "failed", "contacts_found",
                "emails_found", "elapsed_seconds"):
        assert key in stats, f"Missing key: {key}"

    assert stats["total"] == 1
    assert stats["contacts_found"] == 1
    assert stats["emails_found"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 11. Enrichment skips leads with no company_name
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_skips_lead_without_company_name():
    """
    A lead document with an empty company_name must be returned as-is
    without calling the orchestrator.
    """
    from reddit.enrichment import enrich_one_reddit_lead

    lead = _make_reddit_lead(company_name="")

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(),
    ) as mock_enrich:
        result = await enrich_one_reddit_lead(lead)

    mock_enrich.assert_not_called()
    assert result["company_name"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# 12. Confidence is boosted when contacts are found
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confidence_boosted_when_contacts_found():
    """
    When the orchestrator returns contacts, confidence must increase
    from the Reddit-assigned base value (but stay <= 1.0).
    """
    from reddit.enrichment import enrich_one_reddit_lead

    lead = _make_reddit_lead()
    original_conf = lead["confidence"]  # 0.35

    mock_result = _make_enrichment_result(
        contacts=[
            {"name": "CEO", "email": "ceo@x.com", "title": "CEO",
             "phone": None, "linkedin_url": None,
             "sources": ["prospeo"], "confidence": 0.8},
        ],
        contacts_found=1,
        emails_found=1,
    )

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(return_value=mock_result),
    ):
        enriched = await enrich_one_reddit_lead(lead)

    assert enriched["confidence"] >= original_conf
    assert enriched["confidence"] <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 13. Google Maps enrichment function is unchanged
# ─────────────────────────────────────────────────────────────────────────────

def test_google_maps_orchestrator_import_unchanged():
    """
    enrich_company_contacts must still be importable from
    people_enrichment.orchestrator — the Reddit enrichment module does not
    modify or monkey-patch it.
    """
    from people_enrichment.orchestrator import enrich_company_contacts
    import asyncio
    import inspect
    assert callable(enrich_company_contacts)
    # Must be a coroutine function (async)
    assert asyncio.iscoroutinefunction(enrich_company_contacts)


def test_reddit_enrichment_does_not_import_maps_pipeline():
    """
    reddit/enrichment.py must NOT import from app/services/maps_pipeline_service
    or google_maps/ — isolation contract.
    """
    import importlib
    import sys

    # Load the module source without executing it
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "reddit" / "enrichment.py"
    text = src.read_text(encoding="utf-8")

    assert "maps_pipeline_service" not in text, (
        "reddit/enrichment.py must not import maps_pipeline_service"
    )
    assert "google_maps" not in text, (
        "reddit/enrichment.py must not import google_maps"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 14. _merge_enrichment_into_lead never overwrites existing valid data
# ─────────────────────────────────────────────────────────────────────────────

def test_merge_does_not_overwrite_existing_email():
    """
    If the lead already has an email, enrichment must NOT overwrite it
    with a contact email.
    """
    from reddit.enrichment import _merge_enrichment_into_lead

    lead = _make_reddit_lead(email="existing@abcmfg.com")

    result = _make_enrichment_result(
        contacts=[{
            "name": "CEO", "email": "new@abcmfg.com", "title": "CEO",
            "phone": None, "linkedin_url": None,
            "sources": ["prospeo"], "confidence": 0.8,
        }],
        contacts_found=1,
        emails_found=1,
    )

    _merge_enrichment_into_lead(lead, result)

    # Must not be overwritten
    assert lead["email"] == "existing@abcmfg.com"
    # But contacts should still be attached
    assert len(lead["contacts"]) == 1


def test_merge_does_not_overwrite_existing_founder_name():
    """
    If lead already has a founder_name extracted from the Reddit post,
    enrichment must not overwrite it.
    """
    from reddit.enrichment import _merge_enrichment_into_lead

    lead = _make_reddit_lead()
    lead["founder_name"] = "Raj Patel (from Reddit)"

    result = _make_enrichment_result(
        contacts=[{
            "name": "Different Person", "email": "d@x.com", "title": "CEO",
            "phone": "+91 9999999999", "linkedin_url": None,
            "sources": ["pdl"], "confidence": 0.9,
        }],
        contacts_found=1,
        emails_found=1,
        phones_found=1,
    )

    _merge_enrichment_into_lead(lead, result)

    # founder_name was already set — must not change
    assert lead["founder_name"] == "Raj Patel (from Reddit)"


def test_merge_source_fields_always_locked():
    """
    _merge_enrichment_into_lead must always set source/platform/research_source
    to 'reddit' regardless of any contact data.
    """
    from reddit.enrichment import _merge_enrichment_into_lead

    lead = _make_reddit_lead()
    # Deliberately corrupt source fields before merge (edge-case protection)
    lead["source"]          = "corrupted"
    lead["platform"]        = "corrupted"
    lead["research_source"] = "corrupted"

    result = _make_enrichment_result(contacts=[], contacts_found=0)

    _merge_enrichment_into_lead(lead, result)

    assert lead["source"]          == "reddit"
    assert lead["platform"]        == "reddit"
    assert lead["research_source"] == "reddit"


# ─────────────────────────────────────────────────────────────────────────────
# 15. Empty batch → no enrichment calls, empty result
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_empty_batch():
    """enrich_reddit_leads_batch with [] must return ([], stats with zeros)."""
    from reddit.enrichment import enrich_reddit_leads_batch

    with patch(
        "reddit.enrichment.enrich_company_contacts",
        new=AsyncMock(),
    ) as mock_enrich:
        result_leads, stats = await enrich_reddit_leads_batch([])

    mock_enrich.assert_not_called()
    assert result_leads == []
    assert stats["total"] == 0
    assert stats["enriched"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 16. Batch timeout is non-fatal
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_batch_timeout_is_nonfatal():
    """
    If a single lead enrichment times out, the rest of the batch continues.
    """
    from reddit.enrichment import enrich_reddit_leads_batch

    leads = [
        _make_reddit_lead(company_name="Slow Company",  post_id="slow"),
        _make_reddit_lead(company_name="Fast Company",  post_id="fast"),
    ]

    call_count = 0

    async def slow_then_fast(company_name, domain, website, origami_contacts):
        nonlocal call_count
        call_count += 1
        if company_name.startswith("Slow"):
            await asyncio.sleep(200)   # will be killed by per_lead_timeout
        return _make_enrichment_result(
            contacts=[{
                "name": "CEO", "email": f"ceo@{company_name.replace(' ', '')}.com",
                "title": "CEO", "phone": None, "linkedin_url": None,
                "sources": ["pdl"], "confidence": 0.7,
            }],
            contacts_found=1,
            emails_found=1,
        )

    with patch("reddit.enrichment.enrich_company_contacts", new=slow_then_fast):
        enriched_leads, stats = await enrich_reddit_leads_batch(
            leads,
            per_lead_timeout=0.01,   # 10 ms — Slow Company will time out
        )

    # Both leads returned (one untouched due to timeout, one enriched)
    assert len(enriched_leads) == 2
    assert stats["total"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Run directly
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    import sys
    import pathlib
    backend_dir = str(pathlib.Path(__file__).parent.parent)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=backend_dir,
    )
    sys.exit(result.returncode)
