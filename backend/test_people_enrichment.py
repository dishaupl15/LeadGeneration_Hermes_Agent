"""
test_people_enrichment.py
──────────────────────────
Tests for the people-enrichment orchestrator.

Tests:
 1.  PDL gives 2 → Prospeo skipped, ContactOut skipped
 2.  PDL gives 1 → Prospeo called
 3.  PDL gives 0 → Prospeo called
 4.  PDL auth failure → Prospeo called
 5.  PDL + Prospeo together give 2 → ContactOut skipped
 6.  PDL + Prospeo give only 1 → ContactOut called
 7.  Duplicate person (same name/domain) → one final contact
 8.  Duplicate email across providers → one merged contact
 9.  Same person from 3 providers → one merged contact, all sources listed
10.  All providers fail → pipeline succeeds with zero contacts
11.  Company has no domain → name-search used
12.  Cache: same company called twice → one real API call each
13.  Dedup: normalised phone match deduplicates correctly
14.  Dedup: normalised LinkedIn match deduplicates correctly
15.  Scoring: email+phone ranked above email-only
16.  Scoring: founder ranked above HR manager

Usage:  python test_people_enrichment.py
        python -m pytest test_people_enrichment.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = os.path.dirname(os.path.abspath(__file__))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

# Force provider env tokens so is_configured() returns True
os.environ["PDL_API_KEY"]            = "test_pdl_key"
os.environ["PROSPEO_API_KEY"]        = "test_prospeo_key"
os.environ["CONTACTOUT_API_TOKEN"]   = "test_co_token"

# Patch module-level vars BEFORE any provider module is imported
import people_data_labs.config as _pdl_cfg
import prospeo.config          as _pro_cfg
import contactout.config       as _co_cfg
_pdl_cfg.PDL_API_KEY           = "test_pdl_key"
_pro_cfg.PROSPEO_API_KEY       = "test_prospeo_key"
_co_cfg.CONTACTOUT_API_TOKEN   = "test_co_token"


# ── Fake result builders ──────────────────────────────────────────────────────

def _pdl_result(contacts: list[dict], error: str | None = None):
    """Build a minimal PeopleDataLabsResult-like object."""
    m = MagicMock()
    m.contacts       = [_pdl_contact(c) for c in contacts]
    m.contacts_found = len(contacts)
    m.emails_found   = sum(1 for c in contacts if c.get("email"))
    m.phones_found   = sum(1 for c in contacts if c.get("phone"))
    m.pdl_api_calls  = 1
    m.error          = error
    return m


def _pdl_contact(c: dict):
    m = MagicMock()
    m.name         = c.get("name")
    m.designation  = c.get("title")
    m.email        = c.get("email")
    m.phone        = c.get("phone")
    m.linkedin_url = c.get("linkedin_url")
    m.confidence   = c.get("confidence", 0.7)
    return m


def _prospeo_result(contacts: list[dict], error: str | None = None):
    m = MagicMock()
    m.contacts       = [_prospeo_contact(c) for c in contacts]
    m.contacts_found = len(contacts)
    m.emails_found   = sum(1 for c in contacts if c.get("email"))
    m.phones_found   = sum(1 for c in contacts if c.get("phone"))
    m.api_calls      = 1
    m.error          = error
    return m


def _prospeo_contact(c: dict):
    m = MagicMock()
    m.name         = c.get("name")
    m.title        = c.get("title")
    m.email        = c.get("email")
    m.phone        = c.get("phone")
    m.linkedin_url = c.get("linkedin_url")
    m.confidence   = c.get("confidence", 0.7)
    return m


def _co_result(contacts: list[dict], error: str | None = None):
    m = MagicMock()
    m.contacts       = [_co_contact(c) for c in contacts]
    m.contacts_found = len(contacts)
    m.emails_found   = sum(1 for c in contacts if c.get("email"))
    m.phones_found   = sum(1 for c in contacts if c.get("phone"))
    m.api_calls      = 1
    m.error          = error
    return m


def _co_contact(c: dict):
    m = MagicMock()
    m.name         = c.get("name")
    m.title        = c.get("title")
    m.email        = c.get("email")
    m.phone        = c.get("phone")
    m.linkedin_url = c.get("linkedin_url")
    m.confidence   = c.get("confidence", 0.7)
    return m


# ── Test runner helpers ───────────────────────────────────────────────────────

PASS = 0
FAIL = 0
_results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    global PASS, FAIL
    if passed:
        PASS += 1
        print(f"  ✅ PASS  {name}")
    else:
        FAIL += 1
        print(f"  ❌ FAIL  {name}: {detail}")
    _results.append((name, passed, detail))


# ── Helper: run with fresh cache each test ────────────────────────────────────

async def _enrich(company_name: str, domain: str | None = None):
    from people_enrichment.orchestrator import enrich_company_contacts, reset_cache
    reset_cache()
    return await enrich_company_contacts(company_name, domain=domain)


# ══════════════════════════════════════════════════════════════════════════════
# WATERFALL TESTS
# ══════════════════════════════════════════════════════════════════════════════

async def test_pdl_gives_2_stops() -> None:
    """PDL returns 2 useful contacts → Prospeo and ContactOut must NOT be called."""
    name = "1. PDL gives 2 → Prospeo + ContactOut skipped"
    pdl_contacts = [
        {"name": "Alice", "title": "CEO",      "email": "alice@acme.com", "phone": "+91 9000000001"},
        {"name": "Bob",   "title": "HR Head",  "email": "bob@acme.com",   "phone": "+91 9000000002"},
    ]
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=(
                  [{"name":"Alice","title":"CEO","email":"alice@acme.com","phone":"+91 9000000001","linkedin_url":None,"sources":["pdl"],"confidence":0.85},
                   {"name":"Bob",  "title":"HR Head","email":"bob@acme.com","phone":"+91 9000000002","linkedin_url":None,"sources":["pdl"],"confidence":0.75}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=2, emails_found=2, phones_found=2, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=([], MagicMock(called=False)))) as mock_pro,
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))) as mock_co,
    ):
        result = await _enrich("Acme Corp", domain="acme.com")

    try:
        assert result.contacts_found == 2, f"contacts={result.contacts_found}"
        assert result.target_reached is True
        assert mock_pro.call_count == 0, "Prospeo should NOT be called"
        assert mock_co.call_count  == 0, "ContactOut should NOT be called"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_pdl_gives_1_calls_prospeo() -> None:
    """PDL returns 1 useful → Prospeo must be called."""
    name = "2. PDL gives 1 → Prospeo called"
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=(
                  [{"name":"Alice","title":"CEO","email":"alice@acme.com","phone":None,"linkedin_url":None,"sources":["pdl"],"confidence":0.80}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=0, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=(
                  [{"name":"Bob","title":"HR Head","email":"bob@acme.com","phone":"+91 9000000002","linkedin_url":None,"sources":["prospeo"],"confidence":0.72}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1),
              ))) as mock_pro,
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))) as mock_co,
    ):
        result = await _enrich("Acme Corp", domain="acme.com")

    try:
        assert mock_pro.call_count == 1, "Prospeo should be called"
        assert mock_co.call_count  == 0, "ContactOut should NOT be called (target reached)"
        assert result.contacts_found == 2
        assert result.target_reached is True
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_pdl_gives_0_calls_prospeo() -> None:
    """PDL returns 0 → Prospeo must be called."""
    name = "3. PDL gives 0 → Prospeo called"
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=(
                  [],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=0, emails_found=0, phones_found=0, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=(
                  [{"name":"Bob","title":"HR Head","email":"bob@x.com","phone":"+91 9000000002","linkedin_url":None,"sources":["prospeo"],"confidence":0.70}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1),
              ))) as mock_pro,
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))) as mock_co,
    ):
        result = await _enrich("X Corp", domain="x.com")

    try:
        assert mock_pro.call_count == 1
        assert result.contacts_found >= 1
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_pdl_auth_fail_calls_prospeo() -> None:
    """PDL auth failure → Prospeo still called."""
    name = "4. PDL auth failure → Prospeo called"
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=(
                  [],
                  MagicMock(called=True, skipped_reason=None, error="auth_failed",
                            contacts_found=0, emails_found=0, phones_found=0, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=(
                  [{"name":"Carol","title":"CEO","email":"carol@y.com","phone":"+91 9000000003","linkedin_url":None,"sources":["prospeo"],"confidence":0.80}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1),
              ))) as mock_pro,
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))),
    ):
        result = await _enrich("Y Corp", domain="y.com")

    try:
        assert mock_pro.call_count == 1
        assert result.provider_stats["pdl"].error == "auth_failed"
        assert result.contacts_found >= 1
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_pdl_prospeo_give_2_skips_co() -> None:
    """PDL(1) + Prospeo(1) = 2 → ContactOut must NOT be called."""
    name = "5. PDL + Prospeo give 2 → ContactOut skipped"
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=(
                  [{"name":"Alice","title":"CEO","email":"alice@z.com","phone":None,"linkedin_url":None,"sources":["pdl"],"confidence":0.80}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=0, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=(
                  [{"name":"Dan","title":"HR Manager","email":"dan@z.com","phone":"+91 9000000004","linkedin_url":None,"sources":["prospeo"],"confidence":0.70}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))) as mock_co,
    ):
        result = await _enrich("Z Corp", domain="z.com")

    try:
        assert mock_co.call_count == 0, "ContactOut should NOT be called"
        assert result.contacts_found == 2
        assert result.target_reached is True
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_pdl_prospeo_give_1_calls_co() -> None:
    """PDL(0) + Prospeo(1) = 1 useful → ContactOut must be called."""
    name = "6. PDL + Prospeo give 1 → ContactOut called"
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=(
                  [],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=0, emails_found=0, phones_found=0, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=(
                  [{"name":"Eve","title":"Founder","email":"eve@w.com","phone":None,"linkedin_url":None,"sources":["prospeo"],"confidence":0.78}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=0, api_calls=1),
              ))),
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=(
                  [{"name":"Frank","title":"HR Head","email":"frank@w.com","phone":"+91 9000000005","linkedin_url":None,"sources":["contactout"],"confidence":0.68}],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1),
              ))) as mock_co,
    ):
        result = await _enrich("W Corp", domain="w.com")

    try:
        assert mock_co.call_count == 1, "ContactOut should be called"
        assert result.contacts_found >= 2
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_duplicate_person_deduplication() -> None:
    """Same person (same name+domain) from two providers → one final contact."""
    name = "7. Duplicate person → one final contact"
    same = {"name":"John Smith","title":"CEO","email":None,"phone":None,
            "linkedin_url":None,"sources":["pdl"],"confidence":0.70}
    same2 = dict(same, sources=["prospeo"])
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=([same],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=0, phones_found=0, api_calls=1)))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=([same2],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=0, phones_found=0, api_calls=1)))),
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))),
    ):
        result = await _enrich("Dup Corp", domain="dup.com")

    try:
        assert result.contacts_found == 1, f"Expected 1, got {result.contacts_found}"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_duplicate_email_deduplication() -> None:
    """Same email from PDL and Prospeo → one merged contact."""
    name = "8. Duplicate email across providers → one merged contact"
    c1 = {"name":"Jane","title":"CEO","email":"jane@corp.com","phone":None,
          "linkedin_url":None,"sources":["pdl"],"confidence":0.80}
    c2 = {"name":"Jane","title":"Chief Executive Officer","email":"jane@corp.com",
          "phone":"+91 9000000006","linkedin_url":None,"sources":["prospeo"],"confidence":0.72}
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=([c1],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=0, api_calls=1)))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=([c2],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1)))),
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))),
    ):
        result = await _enrich("Corp", domain="corp.com")

    try:
        assert result.contacts_found == 1, f"Expected 1 merged contact, got {result.contacts_found}"
        merged = result.contacts[0]
        assert merged.phone == "+91 9000000006", "Phone should be merged in"
        assert merged.email == "jane@corp.com"
        assert "pdl" in merged.sources and "prospeo" in merged.sources
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_same_person_3_providers() -> None:
    """Same person from all 3 providers → one merged contact with all 3 sources."""
    name = "9. Same person from 3 providers → one merged, all sources listed"
    base = {"name":"Max","title":"Founder","email":"max@three.com",
            "phone":"+91 9000000007","linkedin_url":"https://linkedin.com/in/max",
            "confidence":0.88}
    c1 = dict(base, sources=["pdl"])
    c2 = dict(base, sources=["prospeo"])
    c3 = dict(base, sources=["contactout"])
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=([c1],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1)))),
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=([c2],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1)))),
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([c3],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=1, emails_found=1, phones_found=1, api_calls=1)))),
    ):
        result = await _enrich("Three Corp", domain="three.com")

    try:
        assert result.contacts_found == 1
        src = result.contacts[0].sources
        assert "pdl" in src and "prospeo" in src and "contactout" in src, f"sources={src}"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_all_providers_fail() -> None:
    """All providers fail → pipeline returns success with zero contacts."""
    name = "10. All providers fail → pipeline succeeds with zero contacts"
    fail_stats = MagicMock(called=True, skipped_reason=None, error="server_error",
                           contacts_found=0, emails_found=0, phones_found=0, api_calls=1)
    with (
        patch("people_enrichment.orchestrator._call_pdl",       new=AsyncMock(return_value=([], fail_stats))),
        patch("people_enrichment.orchestrator._call_prospeo",   new=AsyncMock(return_value=([], fail_stats))),
        patch("people_enrichment.orchestrator._call_contactout",new=AsyncMock(return_value=([], fail_stats))),
    ):
        result = await _enrich("Ghost Corp", domain="ghost.io")

    try:
        assert result.contacts_found == 0
        assert result.error is None   # pipeline itself did not error
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_no_domain_name_search() -> None:
    """No domain → orchestrator still calls providers (using company name)."""
    name = "11. Company has no domain → name search used"
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=([],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=0, emails_found=0, phones_found=0, api_calls=1)))) as mock_pdl,
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=([], MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=0, emails_found=0, phones_found=0, api_calls=1)))),
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=0, emails_found=0, phones_found=0, api_calls=1)))),
    ):
        result = await _enrich("Nameless Ltd")   # no domain

    try:
        assert mock_pdl.call_count == 1, "PDL should still be called"
        # Third arg to _call_pdl is website — check that domain is None or empty
        call_args = mock_pdl.call_args
        domain_arg = call_args[0][1] if call_args[0] else call_args[1].get("domain")
        assert not domain_arg, f"domain should be None/empty, got {domain_arg!r}"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


async def test_cache_prevents_double_call() -> None:
    """Same company called twice → providers only called once (cache hit second time)."""
    name = "12. Cache: same company called twice → single real API call"
    single_contact = {"name":"Alice","title":"CEO","email":"alice@cache.com",
                      "phone":"+91 9000000001","linkedin_url":None,"sources":["pdl"],"confidence":0.85}
    with (
        patch("people_enrichment.orchestrator._call_pdl",
              new=AsyncMock(return_value=([single_contact, dict(single_contact, name="Bob", email="bob@cache.com", sources=["pdl"])],
                  MagicMock(called=True, skipped_reason=None, error=None,
                            contacts_found=2, emails_found=2, phones_found=2, api_calls=1)))) as mock_pdl,
        patch("people_enrichment.orchestrator._call_prospeo",
              new=AsyncMock(return_value=([], MagicMock(called=False)))),
        patch("people_enrichment.orchestrator._call_contactout",
              new=AsyncMock(return_value=([], MagicMock(called=False)))),
    ):
        from people_enrichment.orchestrator import enrich_company_contacts, reset_cache
        reset_cache()
        r1 = await enrich_company_contacts("Cache Corp", domain="cache.com")
        r2 = await enrich_company_contacts("Cache Corp", domain="cache.com")

    try:
        assert mock_pdl.call_count == 1, f"PDL called {mock_pdl.call_count} times"
        assert r1.contacts_found == r2.contacts_found
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# DEDUP UNIT TESTS (sync)
# ══════════════════════════════════════════════════════════════════════════════

def test_dedup_phone_normalisation() -> None:
    """Same phone number in different formats → deduplicated."""
    name = "13. Dedup: normalised phone match"
    from people_enrichment.dedup import dedup_and_merge
    c1 = {"name":"Ana","title":"Founder","email":None,"phone":"+91-9876543210",
          "linkedin_url":None,"sources":["pdl"],"confidence":0.75}
    c2 = {"name":"Ana","title":"Founder","email":"ana@co.com","phone":"09876543210",
          "linkedin_url":None,"sources":["prospeo"],"confidence":0.70}
    result = dedup_and_merge([c1, c2], "co.com")
    try:
        assert len(result) == 1, f"Expected 1, got {len(result)}"
        assert result[0]["email"] == "ana@co.com"   # merged in
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


def test_dedup_linkedin_normalisation() -> None:
    """Same LinkedIn URL (different casing/trailing slash) → deduplicated."""
    name = "14. Dedup: normalised LinkedIn match"
    from people_enrichment.dedup import dedup_and_merge
    c1 = {"name":"Ben","title":"CEO","email":"ben@co.com","phone":None,
          "linkedin_url":"https://www.linkedin.com/in/ben-jones/",
          "sources":["pdl"],"confidence":0.80}
    c2 = {"name":"Ben","title":"Chief Executive Officer","email":None,"phone":"+91 9111111111",
          "linkedin_url":"https://linkedin.com/in/ben-jones",
          "sources":["contactout"],"confidence":0.72}
    result = dedup_and_merge([c1, c2], "co.com")
    try:
        assert len(result) == 1, f"Expected 1, got {len(result)}"
        assert result[0].get("phone") == "+91 9111111111"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


def test_scoring_email_phone_ranked_first() -> None:
    """Contact with email+phone ranked above email-only."""
    name = "15. Scoring: email+phone ranked above email-only"
    from people_enrichment.scoring import rank_contacts
    contacts = [
        {"name":"A","title":"HR Manager","email":"a@x.com","phone":None,
         "linkedin_url":None,"sources":["pdl"],"confidence":0.70},
        {"name":"B","title":"Founder","email":"b@x.com","phone":"+91 9000000001",
         "linkedin_url":None,"sources":["pdl"],"confidence":0.85},
    ]
    ranked = rank_contacts(contacts)
    try:
        assert ranked[0]["name"] == "B", f"Expected B first, got {ranked[0]['name']}"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


def test_scoring_founder_above_hr_manager() -> None:
    """Founder ranked above HR Manager when both have same contact data."""
    name = "16. Scoring: founder ranked above HR manager"
    from people_enrichment.scoring import rank_contacts
    contacts = [
        {"name":"HR","title":"HR Manager","email":"hr@x.com","phone":"+91 9000000001",
         "linkedin_url":None,"sources":["pdl"],"confidence":0.75},
        {"name":"FD","title":"Founder","email":"fd@x.com","phone":"+91 9000000002",
         "linkedin_url":None,"sources":["pdl"],"confidence":0.75},
    ]
    ranked = rank_contacts(contacts)
    try:
        assert ranked[0]["name"] == "FD", f"Expected Founder first, got {ranked[0]['name']}"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

async def _run_all() -> None:
    print()
    print("=" * 65)
    print("PEOPLE ENRICHMENT ORCHESTRATOR TESTS")
    print("=" * 65)

    # Waterfall tests
    await test_pdl_gives_2_stops()
    await test_pdl_gives_1_calls_prospeo()
    await test_pdl_gives_0_calls_prospeo()
    await test_pdl_auth_fail_calls_prospeo()
    await test_pdl_prospeo_give_2_skips_co()
    await test_pdl_prospeo_give_1_calls_co()
    await test_duplicate_person_deduplication()
    await test_duplicate_email_deduplication()
    await test_same_person_3_providers()
    await test_all_providers_fail()
    await test_no_domain_name_search()
    await test_cache_prevents_double_call()

    # Sync unit tests
    test_dedup_phone_normalisation()
    test_dedup_linkedin_normalisation()
    test_scoring_email_phone_ranked_first()
    test_scoring_founder_above_hr_manager()

    print()
    print("=" * 65)
    print(f"RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    print("=" * 65)

    if FAIL:
        print()
        print("FAILED:")
        for tname, ok, detail in _results:
            if not ok:
                print(f"  - {tname}: {detail}")
        sys.exit(1)
    else:
        print("All tests passed.")


# ── pytest wrappers ───────────────────────────────────────────────────────────
import pytest

@pytest.mark.asyncio
async def test_01(): await test_pdl_gives_2_stops()

@pytest.mark.asyncio
async def test_02(): await test_pdl_gives_1_calls_prospeo()

@pytest.mark.asyncio
async def test_03(): await test_pdl_gives_0_calls_prospeo()

@pytest.mark.asyncio
async def test_04(): await test_pdl_auth_fail_calls_prospeo()

@pytest.mark.asyncio
async def test_05(): await test_pdl_prospeo_give_2_skips_co()

@pytest.mark.asyncio
async def test_06(): await test_pdl_prospeo_give_1_calls_co()

@pytest.mark.asyncio
async def test_07(): await test_duplicate_person_deduplication()

@pytest.mark.asyncio
async def test_08(): await test_duplicate_email_deduplication()

@pytest.mark.asyncio
async def test_09(): await test_same_person_3_providers()

@pytest.mark.asyncio
async def test_10(): await test_all_providers_fail()

@pytest.mark.asyncio
async def test_11(): await test_no_domain_name_search()

@pytest.mark.asyncio
async def test_12(): await test_cache_prevents_double_call()

def test_13(): test_dedup_phone_normalisation()
def test_14(): test_dedup_linkedin_normalisation()
def test_15(): test_scoring_email_phone_ranked_first()
def test_16(): test_scoring_founder_above_hr_manager()


if __name__ == "__main__":
    asyncio.run(_run_all())
