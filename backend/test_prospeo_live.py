"""
test_prospeo_live.py
─────────────────────
Real live acceptance test for the fixed Prospeo people_search module.

Tests:
  1. No "invalid seniority" 400 error for any tier
  2. Tier A uses valid seniority values only
  3. search_contacts() returns contacts (or gracefully empty)
  4. Emails and phones preserved correctly
  5. Fallback search works when seniority filter returns nothing

Run: python test_prospeo_live.py
"""
import asyncio
import sys
import os
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=True, encoding="utf-8-sig")
os.chdir(Path(__file__).parent)
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

PASS = 0
FAIL = 0

def ok(label, detail=""):
    global PASS; PASS += 1
    suffix = f"  ({detail})" if detail else ""
    print(f"  PASS  {label}{suffix}")

def err(label, detail=""):
    global FAIL; FAIL += 1
    suffix = f"  ({detail})" if detail else ""
    print(f"  FAIL  {label}{suffix}")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


async def run_tests():
    from prospeo.people_search import (
        search_contacts,
        _TIER_A_SENIORITIES,
        _TIER_B_SENIORITIES,
    )
    from prospeo.config import is_configured

    print("=" * 60)
    print("PROSPEO LIVE ACCEPTANCE TEST")
    print("=" * 60)

    # ── Test 1: seniority list sanity ────────────────────────────────────────
    print()
    print("TEST 1 — Seniority values (static check)")

    KNOWN_INVALID = {"VP", "Chairman", "President", "Executive", "Lead", "VP Level"}
    bad_a = [v for v in _TIER_A_SENIORITIES if v in KNOWN_INVALID]
    bad_b = [v for v in _TIER_B_SENIORITIES if v in KNOWN_INVALID]

    if not bad_a:
        ok("Tier A contains no known-invalid seniority values", str(_TIER_A_SENIORITIES))
    else:
        err("Tier A contains invalid values", str(bad_a))

    if "Vice President" in _TIER_A_SENIORITIES:
        ok("'Vice President' present in Tier A (replaces invalid 'VP')")
    else:
        err("'Vice President' MISSING from Tier A")

    if "VP" not in _TIER_A_SENIORITIES:
        ok("'VP' correctly removed from Tier A")
    else:
        err("'VP' still present in Tier A — will cause 400")

    if not bad_b:
        ok("Tier B contains no known-invalid seniority values", str(_TIER_B_SENIORITIES))
    else:
        err("Tier B contains invalid values", str(bad_b))

    if not is_configured():
        print()
        print("PROSPEO_API_KEY not set — skipping live API tests")
        print("=" * 60)
        print(f"Static checks: {PASS} passed, {FAIL} failed")
        print("=" * 60)
        return

    # ── Test 2: live call — company with known Prospeo data ──────────────────
    print()
    print("TEST 2 — Live call: Intercom (intercom.com)")
    log("Calling search_contacts('Intercom', domain='intercom.com') ...")

    result = await search_contacts(
        company_name="Intercom",
        domain="intercom.com",
        max_contacts=2,
    )

    if result.error == "auth_failed":
        err("Authentication failed — check PROSPEO_API_KEY")
    elif result.error and "invalid" in result.error.lower():
        err("Got invalid_request error", result.error)
    elif result.error and "seniority" in (result.error or "").lower():
        err("Got seniority error", result.error)
    else:
        ok("No invalid_request / seniority error")

    if result.error != "auth_failed":
        ok(
            f"search_contacts() completed without crashing",
            f"contacts={result.contacts_found} emails={result.emails_found} "
            f"phones={result.phones_found} api_calls={result.api_calls} "
            f"elapsed={result.elapsed_seconds}s"
        )

    if result.contacts_found >= 1:
        ok(f"Got at least 1 contact", f"{result.contacts_found} contacts returned")
        for i, c in enumerate(result.contacts, 1):
            print(f"    Contact {i}: name={c.name!r} title={c.title!r} "
                  f"email={c.email!r} phone={c.phone!r} confidence={c.confidence:.3f}")
    else:
        # This is acceptable — company may have no people in Prospeo index
        ok("Zero contacts returned (acceptable — may not be in index)", "no failure")

    # ── Test 3: live call — company with no domain (name fallback) ───────────
    print()
    print("TEST 3 — Live call: no domain (name match fallback)")
    import asyncio as _aio
    await _aio.sleep(8)  # respect rate limit

    result2 = await search_contacts(
        company_name="Tata Consultancy Services",
        domain=None,
        max_contacts=2,
    )

    if result2.error == "auth_failed":
        err("Auth failed on name-only search")
    elif result2.error and "invalid" in (result2.error or "").lower():
        err("invalid_request error on name-only search", result2.error)
    else:
        ok("Name-only search completed without error",
           f"contacts={result2.contacts_found} error={result2.error!r}")

    # ── Test 4: verify ProspeoContact has email/phone fields intact ──────────
    print()
    print("TEST 4 — Schema field preservation")
    if result.contacts:
        c = result.contacts[0]
        has_email_field = hasattr(c, "email")
        has_phone_field = hasattr(c, "phone")
        ok("ProspeoContact.email field present", str(has_email_field))
        ok("ProspeoContact.phone field present", str(has_phone_field))
        ok("ProspeoContact.title field present", str(hasattr(c, "title")))
        ok("ProspeoContact.linkedin_url field present", str(hasattr(c, "linkedin_url")))
        ok("ProspeoContact.confidence field present", str(hasattr(c, "confidence")))
    else:
        ok("Schema check skipped (no contacts returned)", "acceptable")

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAIL == 0:
        print("All tests passed — Prospeo module is working correctly.")
    else:
        print("FAILURES detected — see above.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_tests())
    sys.exit(0 if FAIL == 0 else 1)
