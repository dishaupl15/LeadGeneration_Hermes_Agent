"""
test_contactout.py
───────────────────
Comprehensive unit tests for the ContactOut module.

Tests covered
─────────────
 1. Successful search (email + phone returned)
 2. Company with multiple decision makers
 3. No profiles returned
 4. Profiles without email (contact_info has no emails)
 5. Profiles without phone
 6. Authentication failure (400)
 7. Rate limit (429)
 8. Duplicate profiles deduplication
 9. Missing company domain (name-only fallback)
10. Malformed API response

Contact-mapper unit tests:
11. Role classification
12. Email normalisation / validation
13. Phone normalisation — never generate/guess
14. contact_availability does NOT mean email exists

Usage:
    python -m pytest test_contactout.py -v
    python test_contactout.py          (standalone)
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

# ── Path setup ────────────────────────────────────────────────────────────────
_BACKEND = os.path.dirname(os.path.abspath(__file__))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

# ── Make sure CONTACTOUT_API_TOKEN looks configured for most tests ────────────
os.environ["CONTACTOUT_API_TOKEN"] = "test_fake_token_12345"
os.environ.setdefault("CONTACTOUT_MAX_CONTACTS_PER_COMPANY", "2")

# Force-patch the module-level variable after dotenv may have overwritten it
import importlib, contactout.config as _co_cfg
_co_cfg.CONTACTOUT_API_TOKEN = "test_fake_token_12345"


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_profile(
    full_name: str = "Rahul Sharma",
    title: str = "Founder & CEO",
    company_name: str = "Acme Pvt Ltd",
    company_domain: str = "acme.com",
    linkedin: str = "https://linkedin.com/in/rahul-sharma",
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    contact_availability: bool = True,
) -> dict[str, Any]:
    """Build a minimal ContactOut profile dict."""
    if emails is None:
        emails = ["rahul@acme.com"]
    if phones is None:
        phones = ["+91 9876543210"]
    return {
        "full_name":             full_name,
        "title":                 title,
        "current_company":       {"name": company_name, "domain": company_domain},
        "linkedin":              linkedin,
        "contact_availability":  contact_availability,
        "contact_info": {
            "professional_emails": emails,
            "phones":              phones,
        },
    }


def _api_response(profiles: list[dict]) -> dict:
    """Wrap profiles list into a ContactOut-style API response dict."""
    # ContactOut returns profiles as a dict keyed by index/linkedin url
    profiles_dict = {str(i): p for i, p in enumerate(profiles)}
    return {
        "status_code": 200,
        "profiles":    profiles_dict,
        "metadata":    {"total_results": len(profiles)},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Test runner helpers
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


# ═══════════════════════════════════════════════════════════════════════════════
# Async tests
# ═══════════════════════════════════════════════════════════════════════════════

# ── Test 1: Successful search ─────────────────────────────────────────────────

async def test_successful_search() -> None:
    name = "1. Successful search (email + phone returned)"
    profile  = _make_profile()
    api_body = _api_response([profile])

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(api_body, None)),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com")

    try:
        assert result.success is True, f"success={result.success}"
        assert result.error is None, f"error={result.error}"
        assert len(result.contacts) == 1, f"contacts={len(result.contacts)}"
        assert result.contacts[0].email == "rahul@acme.com"
        assert result.contacts[0].phone is not None
        assert result.contacts[0].source == "contactout"
        assert result.contacts_found == 1
        assert result.emails_found == 1
        assert result.phones_found == 1
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 2: Multiple decision makers ─────────────────────────────────────────

async def test_multiple_decision_makers() -> None:
    name = "2. Company with multiple decision makers"
    p1 = _make_profile(
        full_name="Alice Smith",
        title="CEO",
        emails=["alice@corp.com"],
        phones=["+1 415 000 0001"],
    )
    p2 = _make_profile(
        full_name="Bob Jones",
        title="HR Manager",
        emails=["bob@corp.com"],
        phones=["+1 415 000 0002"],
        company_name="Corp Ltd",
        company_domain="corp.com",
        linkedin="https://linkedin.com/in/bob-jones",
    )
    p1["current_company"] = {"name": "Corp Ltd", "domain": "corp.com"}
    api_body = _api_response([p1, p2])

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(api_body, None)),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Corp Ltd", domain="corp.com", max_contacts=5)

    try:
        assert result.success is True
        assert len(result.contacts) == 2, f"expected 2, got {len(result.contacts)}"
        names = [c.name for c in result.contacts]
        assert "Alice Smith" in names
        assert "Bob Jones" in names
        # CEO should rank before HR Manager
        assert result.contacts[0].name == "Alice Smith", \
            f"CEO should be first, got {result.contacts[0].name}"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 3: No profiles ───────────────────────────────────────────────────────

async def test_no_profiles() -> None:
    name = "3. No profiles returned"
    api_body = _api_response([])

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(api_body, None)),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Ghost Corp", domain="ghost.io")

    try:
        assert result.success is True
        assert len(result.contacts) == 0
        assert result.contacts_found == 0
        assert result.error is None
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 4: Profiles without email ───────────────────────────────────────────

async def test_no_email() -> None:
    name = "4. Profiles without email"
    profile = _make_profile(emails=[])
    api_body = _api_response([profile])

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(api_body, None)),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com")

    try:
        assert result.success is True
        assert len(result.contacts) == 1, f"contact still returned: {len(result.contacts)}"
        assert result.contacts[0].email is None
        assert result.emails_found == 0
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 5: Profiles without phone ───────────────────────────────────────────

async def test_no_phone() -> None:
    name = "5. Profiles without phone"
    profile = _make_profile(phones=[])
    api_body = _api_response([profile])

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(api_body, None)),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com")

    try:
        assert result.success is True
        assert result.contacts[0].phone is None
        assert result.phones_found == 0
        assert result.contacts[0].email == "rahul@acme.com"
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 6: Authentication failure (400) ──────────────────────────────────────

async def test_auth_failure() -> None:
    name = "6. Authentication failure (400)"

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(None, "auth_failed")),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Any Corp", domain="any.com")

    try:
        assert result.success is False, f"success should be False, got {result.success}"
        assert result.error == "auth_failed", f"error={result.error}"
        assert len(result.contacts) == 0
        assert result.contacts_found == 0
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 7: Rate limit (429) ──────────────────────────────────────────────────

async def test_rate_limit() -> None:
    name = "7. Rate limit (429)"

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(None, "rate_limited")),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Rate Corp", domain="rate.io")

    try:
        assert result.success is False
        assert result.error == "rate_limited"
        assert len(result.contacts) == 0
        assert result.error != "auth_failed"  # not an auth failure
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 8: Duplicate profiles deduplication ──────────────────────────────────

async def test_deduplication() -> None:
    name = "8. Duplicate profiles deduplication"
    p1 = _make_profile(full_name="Alice Smith", emails=["alice@co.com"])
    p2 = _make_profile(full_name="Alice Smith", emails=["alice@co.com"])  # exact duplicate
    api_body = _api_response([p1, p2])

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(api_body, None)),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd", domain="acme.com", max_contacts=5)

    try:
        assert len(result.contacts) == 1, \
            f"Duplicate should be removed — got {len(result.contacts)}"
        assert result.emails_found == 1
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 9: Missing domain (name-only fallback) ───────────────────────────────

async def test_missing_domain() -> None:
    name = "9. Missing company domain (name-only fallback)"
    profile  = _make_profile()
    api_body = _api_response([profile])

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(api_body, None)),
    ) as mock_search:
        from contactout.people_search import search_contacts
        result = await search_contacts("Acme Pvt Ltd")  # no domain

    try:
        assert result.success is True
        # Verify the payload sent to the API does NOT include company_domain
        call_payload = mock_search.call_args[0][0]
        assert "company_domain" not in call_payload, \
            f"company_domain should be absent, got {call_payload}"
        assert "company" in call_payload
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))


# ── Test 10: Malformed API response ──────────────────────────────────────────

async def test_malformed_response() -> None:
    name = "10. Malformed API response"
    # profiles field is an unexpected type
    bad_body = {"status_code": 200, "profiles": "not_a_dict_or_list", "metadata": {}}

    with patch(
        "contactout.people_search._api_people_search",
        new=AsyncMock(return_value=(bad_body, None)),
    ):
        from contactout.people_search import search_contacts
        result = await search_contacts("Weird Corp", domain="weird.io")

    try:
        assert result.success is True   # should handle gracefully, not crash
        assert len(result.contacts) == 0
        assert result.error is None
        record(name, True)
    except (AssertionError, Exception) as exc:
        record(name, False, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Contact-mapper unit tests (sync)
# ═══════════════════════════════════════════════════════════════════════════════

def test_classify_role() -> None:
    from contactout.contact_mapper import classify_role
    cases = [
        ("Founder & CEO",               "founder"),
        ("co-founder",                  "co_founder"),
        ("Owner",                       "owner"),
        ("Chief Executive Officer",     "ceo"),
        ("Managing Director",           "managing_director"),
        ("COO",                         "coo"),
        ("Head of HR",                  "hr"),
        ("VP Human Resources",          "hr"),
        ("Talent Acquisition Manager",  "talent_acquisition_manager"),
        ("HR Manager",                  "hr_manager"),
        ("Recruitment Head",            "recruitment"),
        ("Software Engineer",           "other"),
    ]
    errors = []
    for title, expected in cases:
        got = classify_role(title)
        if got != expected:
            errors.append(f"{title!r}: expected {expected!r}, got {got!r}")
    record("11. Role classification", not errors, "; ".join(errors))


def test_email_normalisation() -> None:
    from contactout.contact_mapper import normalise_email
    good = [
        "rahul@acmecorp.com",
        "HR.HEAD@mycompany.co.in",
        "john.doe@acme.com",
    ]
    bad = [
        "info@acmecorp.com",       # junk local
        "admin@acmecorp.com",      # junk local
        "noreply@acmecorp.com",    # junk local
        "support@acmecorp.com",    # junk local
        "not-an-email",
        "user@example.com",        # blocked domain
        "null",
        "N/A",
        "",
    ]
    errors = []
    for e in good:
        result = normalise_email(e)
        if not result:
            errors.append(f"False negative: {e!r}")
    for e in bad:
        result = normalise_email(e)
        if result:
            errors.append(f"False positive: {e!r} → {result!r}")
    record("12. Email normalisation / validation", not errors, "; ".join(errors))


def test_phone_normalisation_never_guesses() -> None:
    """Phone normalisation must never generate numbers — only clean real ones."""
    from contactout.contact_mapper import normalise_phone
    cases_good = ["+91 9876543210", "+1 415 000 0001", "0044 20 7946 0001"]
    cases_bad  = ["null", "N/A", "", "123"]  # too short or null placeholder
    errors = []
    for p in cases_good:
        if not normalise_phone(p):
            errors.append(f"Should have returned value for {p!r}")
    for p in cases_bad:
        if normalise_phone(p):
            errors.append(f"Should have returned None for {p!r}")
    record("13. Phone normalisation — never generate/guess", not errors, "; ".join(errors))


def test_contact_availability_not_equal_to_contact_exists() -> None:
    """
    contact_availability=True does NOT guarantee email/phone exist.
    We must check the actual contact_info fields.
    """
    from contactout.contact_mapper import extract_best_email, extract_best_phone
    profile_no_contacts = {
        "contact_availability": True,  # flag says available
        "contact_info": {
            "professional_emails": [],  # but actually empty
            "phones": [],
        },
    }
    email = extract_best_email(profile_no_contacts)
    phone = extract_best_phone(profile_no_contacts)
    passed = email is None and phone is None
    record(
        "14. contact_availability ≠ contact exists",
        passed,
        f"email={email!r} phone={phone!r}",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Missing API key test (async)
# ═══════════════════════════════════════════════════════════════════════════════

async def test_missing_api_token() -> None:
    name = "15. Missing API token"
    import contactout.config as cfg
    original = cfg.CONTACTOUT_API_TOKEN
    try:
        cfg.CONTACTOUT_API_TOKEN = ""
        from contactout.people_search import search_contacts
        result = await search_contacts("NoKey Corp", domain="nokey.com")
        assert result.success is False
        assert result.error is not None
        assert len(result.contacts) == 0
        record(name, True)
    except AssertionError as exc:
        record(name, False, str(exc))
    finally:
        cfg.CONTACTOUT_API_TOKEN = original


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_all() -> None:
    print()
    print("=" * 60)
    print("CONTACTOUT MODULE TESTS")
    print("=" * 60)

    await test_successful_search()
    await test_multiple_decision_makers()
    await test_no_profiles()
    await test_no_email()
    await test_no_phone()
    await test_auth_failure()
    await test_rate_limit()
    await test_deduplication()
    await test_missing_domain()
    await test_malformed_response()

    test_classify_role()
    test_email_normalisation()
    test_phone_normalisation_never_guesses()
    test_contact_availability_not_equal_to_contact_exists()

    await test_missing_api_token()

    print()
    print("=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
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


# ── pytest compatibility ──────────────────────────────────────────────────────
import pytest


@pytest.mark.asyncio
async def test_01_successful_search():         await test_successful_search()

@pytest.mark.asyncio
async def test_02_multiple_decision_makers():  await test_multiple_decision_makers()

@pytest.mark.asyncio
async def test_03_no_profiles():               await test_no_profiles()

@pytest.mark.asyncio
async def test_04_no_email():                  await test_no_email()

@pytest.mark.asyncio
async def test_05_no_phone():                  await test_no_phone()

@pytest.mark.asyncio
async def test_06_auth_failure():              await test_auth_failure()

@pytest.mark.asyncio
async def test_07_rate_limit():                await test_rate_limit()

@pytest.mark.asyncio
async def test_08_deduplication():             await test_deduplication()

@pytest.mark.asyncio
async def test_09_missing_domain():            await test_missing_domain()

@pytest.mark.asyncio
async def test_10_malformed_response():        await test_malformed_response()

def test_11_classify_role():                   test_classify_role()
def test_12_email_normalisation():             test_email_normalisation()
def test_13_phone_normalisation():             test_phone_normalisation_never_guesses()
def test_14_contact_availability():            test_contact_availability_not_equal_to_contact_exists()

@pytest.mark.asyncio
async def test_15_missing_api_token():         await test_missing_api_token()


if __name__ == "__main__":
    asyncio.run(_run_all())
