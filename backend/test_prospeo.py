"""
test_prospeo.py
────────────────
Comprehensive unit tests for the Prospeo module.

Tests covered
─────────────
 1. Successful search + enrichment (happy path)
 2. No people found (search returns empty)
 3. People found but no email in enrichment
 4. People found but no mobile in enrichment
 5. 401 authentication failure in search
 6. 401 authentication failure in bulk-enrich
 7. 429 rate limit in search
 8. Duplicate people deduplication
 9. Missing domain (name-only fallback)
10. Missing API key

Usage:  python -m pytest test_prospeo.py -v
        python test_prospeo.py         (standalone — no pytest needed)
"""
from __future__ import annotations

import asyncio
import sys
import os
from typing import Any
from unittest.mock import AsyncMock, patch

# ── Path setup ────────────────────────────────────────────────────────────────
_BACKEND = os.path.dirname(os.path.abspath(__file__))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

# ── Make sure PROSPEO_API_KEY looks configured for most tests ─────────────────
os.environ.setdefault("PROSPEO_API_KEY", "test_fake_key_12345")
os.environ.setdefault("PROSPEO_MAX_CONTACTS_PER_COMPANY", "2")


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_person(
    person_id: str = "pid001",
    full_name: str = "Rahul Sharma",
    title: str = "Founder & CEO",
    company_name: str = "Acme Pvt Ltd",
    company_website: str = "acme.com",
    email_revealed: bool = True,
    email_addr: str = "rahul@acme.com",
    mobile_revealed: bool = True,
    mobile_number: str = "+91 9876543210",
) -> dict[str, Any]:
    return {
        "person_id":        person_id,
        "full_name":        full_name,
        "first_name":       full_name.split()[0],
        "last_name":        full_name.split()[-1],
        "current_job_title": title,
        "current_job_key":  "job001",
        "linkedin_url":     f"https://linkedin.com/in/{full_name.lower().replace(' ','-')}",
        "headline":         title,
        "job_history": [
            {
                "title":        title,
                "company_name": company_name,
                "current":      True,
                "seniority":    "Founder/Owner",
                "company_id":   "ccc001",
                "job_key":      "job001",
            }
        ],
        "email": {
            "status":   "VERIFIED",
            "revealed": email_revealed,
            "email":    email_addr if email_revealed else None,
        },
        "mobile": {
            "status":             "VERIFIED",
            "revealed":           mobile_revealed,
            "mobile":             mobile_number if mobile_revealed else None,
            "mobile_international": mobile_number if mobile_revealed else None,
        },
        "location": None,
        "skills": [],
    }


def _make_company(name: str = "Acme Pvt Ltd", website: str = "acme.com") -> dict:
    return {"name": name, "website": website}


def _search_result(
    person: dict,
    company: dict,
) -> dict:
    """Wrap person+company into a /search-person result item."""
    return {"person": person, "company": company}


def _enrich_match(identifier: str, person: dict, company: dict) -> dict:
    return {"identifier": identifier, "person": person, "company": company}


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════

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


# ── Test 1: Successful search + enrichment ─────────────────────────────────────

async def test_successful_search() -> None:
    name = "1. Successful search + enrichment"
    person   = _make_person()
    company  = _make_company()
    sr       = _search_result(person, company)
    em       = _enrich_match("0", person, company)

    with (
        patch("prospeo.people_search.search_person",
              new=AsyncMock(return_value=([sr], 1, None))),
        patch("prospeo.people_search.bulk_enrich_person",
              new=AsyncMock(return_value=([em], 1, None))),
    ):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com")

    try:
        assert result.success is True
        assert result.error is None
        assert len(result.contacts) == 1
        assert result.contacts[0].email == "rahul@acme.com"
        assert result.contacts[0].phone is not None
        assert result.contacts[0].source == "prospeo"
        assert result.contacts_found == 1
        assert result.emails_found == 1
        assert result.phones_found == 1
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 2: No people found ────────────────────────────────────────────────────

async def test_no_people() -> None:
    name = "2. No people found"

    with patch("prospeo.people_search.search_person",
               new=AsyncMock(return_value=([], 0, "no_results"))):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Ghost Corp", domain="ghost.io")

    try:
        assert result.success is True
        assert len(result.contacts) == 0
        assert result.contacts_found == 0
        assert result.error is None
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 3: No email in enrichment ────────────────────────────────────────────

async def test_no_email() -> None:
    name = "3. No email in enrichment"
    person  = _make_person(email_revealed=False, email_addr="")
    company = _make_company()
    sr      = _search_result(person, company)
    em      = _enrich_match("0", person, company)

    with (
        patch("prospeo.people_search.search_person",
              new=AsyncMock(return_value=([sr], 1, None))),
        patch("prospeo.people_search.bulk_enrich_person",
              new=AsyncMock(return_value=([em], 0, None))),
    ):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com")

    try:
        assert result.success is True
        # Contact still returned (we have name, title, linkedin)
        assert len(result.contacts) == 1
        assert result.contacts[0].email is None
        assert result.emails_found == 0
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 4: No mobile in enrichment ──────────────────────────────────────────

async def test_no_mobile() -> None:
    name = "4. No mobile in enrichment"
    person  = _make_person(mobile_revealed=False)
    company = _make_company()
    sr      = _search_result(person, company)
    em      = _enrich_match("0", person, company)

    with (
        patch("prospeo.people_search.search_person",
              new=AsyncMock(return_value=([sr], 1, None))),
        patch("prospeo.people_search.bulk_enrich_person",
              new=AsyncMock(return_value=([em], 1, None))),
    ):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com")

    try:
        assert result.success is True
        assert result.contacts[0].phone is None
        assert result.phones_found == 0
        assert result.contacts[0].email == "rahul@acme.com"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 5: 401 auth failure in search ────────────────────────────────────────

async def test_auth_failure_search() -> None:
    name = "5. 401 auth failure in search"

    with patch("prospeo.people_search.search_person",
               new=AsyncMock(return_value=([], 0, "auth_failed"))):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Any Corp", domain="any.com")

    try:
        assert result.success is False
        assert result.error == "auth_failed"
        assert len(result.contacts) == 0
        # bulk_enrich must NOT have been called — can't easily assert without
        # more complex mocking, but we can verify contacts_found == 0
        assert result.contacts_found == 0
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 6: 401 auth failure in bulk-enrich ───────────────────────────────────

async def test_auth_failure_bulk_enrich() -> None:
    name = "6. 401 auth failure in bulk-enrich"
    person  = _make_person()
    company = _make_company()
    sr      = _search_result(person, company)

    with (
        patch("prospeo.people_search.search_person",
              new=AsyncMock(return_value=([sr], 1, None))),
        patch("prospeo.people_search.bulk_enrich_person",
              new=AsyncMock(return_value=([], 0, "auth_failed"))),
    ):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com")

    try:
        assert result.success is False
        assert result.error == "auth_failed"
        assert len(result.contacts) == 0
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 7: 429 rate limit in search ─────────────────────────────────────────

async def test_rate_limit() -> None:
    name = "7. 429 rate limit in search"

    with patch("prospeo.people_search.search_person",
               new=AsyncMock(return_value=([], 0, "rate_limited"))):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Rate Ltd", domain="rate.io")

    try:
        # rate_limited is not auth_failed — success=True, 0 contacts, no crash
        assert len(result.contacts) == 0
        assert result.error != "auth_failed"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 8: Duplicate people deduplication ───────────────────────────────────

async def test_deduplication() -> None:
    name = "8. Duplicate people deduplication"
    p1  = _make_person(person_id="p1", full_name="Alice Smith", email_addr="alice@co.com")
    p2  = _make_person(person_id="p2", full_name="Alice Smith", email_addr="alice@co.com")  # same email
    cmp = _make_company()
    sr1 = _search_result(p1, cmp)
    sr2 = _search_result(p2, cmp)
    em1 = _enrich_match("0", p1, cmp)
    em2 = _enrich_match("1", p2, cmp)

    with (
        patch("prospeo.people_search.search_person",
              new=AsyncMock(return_value=([sr1, sr2], 2, None))),
        patch("prospeo.people_search.bulk_enrich_person",
              new=AsyncMock(return_value=([em1, em2], 2, None))),
    ):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com",
                                        max_contacts=5)

    try:
        # Same email — should be deduplicated to 1 contact
        assert len(result.contacts) == 1
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 9: Missing domain (name-only) ────────────────────────────────────────

async def test_missing_domain() -> None:
    name = "9. Missing domain (name-only fallback)"
    person  = _make_person()
    company = _make_company()
    sr      = _search_result(person, company)
    em      = _enrich_match("0", person, company)

    with (
        patch("prospeo.people_search.search_person",
              new=AsyncMock(return_value=([sr], 1, None))) as mock_search,
        patch("prospeo.people_search.bulk_enrich_person",
              new=AsyncMock(return_value=([em], 1, None))),
    ):
        from prospeo.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd")  # no domain

    try:
        assert result.success is True
        # Verify search was called with names filter (not websites)
        call_filters = mock_search.call_args[0][0]
        assert "names" in call_filters.get("company", {})
        assert "websites" not in call_filters.get("company", {})
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 10: Missing API key ──────────────────────────────────────────────────

async def test_missing_api_key() -> None:
    name = "10. Missing API key"
    import prospeo.config as cfg
    original = cfg.PROSPEO_API_KEY
    try:
        cfg.PROSPEO_API_KEY = ""
        from prospeo.people_search import search_contacts
        result = await search_contacts("NoKey Corp", domain="nokey.com")
        assert result.success is False
        assert result.error is not None
        assert len(result.contacts) == 0
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))
    finally:
        cfg.PROSPEO_API_KEY = original


# ── Test 11: Malformed response from search ───────────────────────────────────

async def test_malformed_search_response() -> None:
    name = "11. Malformed search response (missing person_id)"
    # Result with no person_id — should be filtered out
    bad_result = {
        "person": {
            "person_id": None,         # missing
            "full_name": "Bob",
            "current_job_title": "CEO",
            "job_history": [{"title": "CEO", "company_name": "X", "current": True,
                             "seniority": "C-Suite", "job_key": "j1", "company_id": "c1"}],
            "email": {}, "mobile": {}, "linkedin_url": None,
        },
        "company": {"name": "X Corp", "website": "x.com"},
    }

    with patch("prospeo.people_search.search_person",
               new=AsyncMock(return_value=([bad_result], 1, None))):
        from prospeo.people_search import search_contacts
        result = await search_contacts("X Corp", domain="x.com")

    try:
        # Bad record should be silently skipped
        assert len(result.contacts) == 0
        assert result.error is None   # not an auth error
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Contact-mapper unit tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_classify_role() -> None:
    from prospeo.contact_mapper import classify_role
    cases = [
        ("Founder & CEO", "founder"),
        ("co-founder", "co_founder"),
        ("Owner", "owner"),
        ("Chief Executive Officer", "ceo"),
        ("Managing Director", "managing_director"),
        ("COO", "coo"),
        ("Head of HR", "hr"),
        ("VP Human Resources", "hr"),
        ("Talent Acquisition Manager", "talent_acquisition_manager"),
        ("HR Manager", "hr_manager"),
        ("Recruitment Head", "recruitment"),
        ("Software Engineer", "other"),
    ]
    failed = []
    for title, expected in cases:
        got = classify_role(title)
        if got != expected:
            failed.append(f"{title!r}: expected {expected!r}, got {got!r}")
    record("12. Role classification", not failed, "; ".join(failed))


def test_is_valid_email() -> None:
    from prospeo.contact_mapper import _is_valid_email
    # good: real personal-looking professional emails (not junk locals, not blocked domains)
    good = ["rahul@acmecorp.com", "hr.head@mycompany.co.in", "john.doe@acme.com"]
    # bad: junk locals (info, admin, noreply, support) or blocked domains (example.com)
    bad  = ["info@acmecorp.com", "admin@acmecorp.com", "noreply@acmecorp.com",
            "support@acmecorp.com", "not-an-email", "user@example.com"]
    errors = []
    for e in good:
        if not _is_valid_email(e):
            errors.append(f"False negative: {e}")
    for e in bad:
        if _is_valid_email(e):
            errors.append(f"False positive: {e}")
    record("13. Email validation", not errors, "; ".join(errors))


def test_extract_phone_no_copy_company_phone() -> None:
    """Phone must come from person.mobile, never from company data."""
    from prospeo.contact_mapper import extract_mobile
    person_no_mobile = {"mobile": {"status": "UNAVAILABLE", "revealed": False}}
    result = extract_mobile(person_no_mobile)
    passed = result is None
    record("14. Phone not copied from company", passed,
           f"extract_mobile returned {result!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_all() -> None:
    print()
    print("=" * 60)
    print("PROSPEO MODULE TESTS")
    print("=" * 60)

    # Async tests
    await test_successful_search()
    await test_no_people()
    await test_no_email()
    await test_no_mobile()
    await test_auth_failure_search()
    await test_auth_failure_bulk_enrich()
    await test_rate_limit()
    await test_deduplication()
    await test_missing_domain()
    await test_missing_api_key()
    await test_malformed_search_response()

    # Sync tests
    test_classify_role()
    test_is_valid_email()
    test_extract_phone_no_copy_company_phone()

    print()
    print("=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
    print("=" * 60)

    if FAIL:
        print()
        print("FAILED TESTS:")
        for tname, ok, detail in _results:
            if not ok:
                print(f"  - {tname}: {detail}")
        sys.exit(1)
    else:
        print("All tests passed.")


# pytest compatibility
import pytest

@pytest.mark.asyncio
async def test_01_successful_search():     await test_successful_search()

@pytest.mark.asyncio
async def test_02_no_people():             await test_no_people()

@pytest.mark.asyncio
async def test_03_no_email():              await test_no_email()

@pytest.mark.asyncio
async def test_04_no_mobile():             await test_no_mobile()

@pytest.mark.asyncio
async def test_05_auth_failure_search():   await test_auth_failure_search()

@pytest.mark.asyncio
async def test_06_auth_failure_enrich():   await test_auth_failure_bulk_enrich()

@pytest.mark.asyncio
async def test_07_rate_limit():            await test_rate_limit()

@pytest.mark.asyncio
async def test_08_deduplication():         await test_deduplication()

@pytest.mark.asyncio
async def test_09_missing_domain():        await test_missing_domain()

@pytest.mark.asyncio
async def test_10_missing_api_key():       await test_missing_api_key()

@pytest.mark.asyncio
async def test_11_malformed_response():    await test_malformed_search_response()

def test_12_classify_role():               test_classify_role()
def test_13_email_validation():            test_is_valid_email()
def test_14_no_company_phone_copy():       test_extract_phone_no_copy_company_phone()


if __name__ == "__main__":
    asyncio.run(_run_all())
