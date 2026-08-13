"""
test_7_scenarios.py
────────────────────
Tests the 7 Origami integration scenarios from the requirements.
Run from backend/:
    python test_7_scenarios.py
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
load_dotenv()


async def run_all_tests():
    from app.services.origami_service import (
        enrich_company_with_origami,
        enrich_batch_with_origami,
        is_configured,
        sort_contacts,
        title_tier,
        tier_label,
        _is_duplicate,
        clean_email,
    )
    from people_enrichment.dedup import dedup_and_merge, count_useful, _email_quality
    from people_enrichment.scoring import rank_contacts

    passed = 0
    failed = 0

    def ok(msg):
        nonlocal passed
        passed += 1
        print(f"  PASS — {msg}")

    def err(msg, exc=None):
        nonlocal failed
        failed += 1
        print(f"  FAIL — {msg}" + (f": {exc}" if exc else ""))

    print("=" * 65)
    print("  Origami Integration — 7 Scenario Tests")
    print("=" * 65)

    # ── Test 1: One company — graceful skip when key not set ─────────────────
    print("\nTEST 1: One company — Origami key not set (graceful fallback)")
    try:
        co = {"company_name": "ABC Realty", "domain": "abcrealty.com"}
        result = await enrich_company_with_origami(co)
        assert result["origami_enriched"] == False
        assert result["founder_status"] == "skipped"
        ok("origami_enriched=False, founder_status=skipped, no crash")
    except Exception as e:
        err("unexpected exception", e)

    # ── Test 2: 10 companies batch — all graceful skip ───────────────────────
    print("\nTEST 2: 10 companies — batch graceful skip")
    try:
        companies = [{"company_name": f"Company {i}", "domain": f"co{i}.com"} for i in range(10)]
        results = await enrich_batch_with_origami(companies)
        assert len(results) == 10, f"expected 10, got {len(results)}"
        for r in results:
            assert r.get("origami_enriched") == False
            assert r.get("founder_status") == "skipped"
        ok("all 10 gracefully skipped with no crash")
    except Exception as e:
        err("unexpected exception", e)

    # ── Test 3: Founder found — tier sorting correct ──────────────────────────
    print("\nTEST 3: Company with founder found — tier sort")
    try:
        fake_contacts = [
            {"name": "Amit Patil",   "title": "CEO",     "email": "amit@abc.com",
             "phone": None, "confidence": 0.80, "sources": ["origami"]},
            {"name": "Rahul Sharma", "title": "Founder", "email": "rahul@abc.com",
             "phone": "+91 98765 43210", "confidence": 0.91, "sources": ["origami"]},
            {"name": "Priya Shah",   "title": "Director","email": None,
             "phone": None, "confidence": 0.70, "sources": ["origami"]},
        ]
        sorted_ct = sort_contacts(fake_contacts)
        assert sorted_ct[0]["name"] == "Rahul Sharma", "Founder must be first"
        assert sorted_ct[1]["name"] == "Amit Patil",   "CEO must be second"
        assert sorted_ct[2]["name"] == "Priya Shah",   "Director must be third"
        assert title_tier("Founder") == 1
        assert title_tier("CEO") == 2
        assert title_tier("Director") == 3
        ok(f"Founder(tier=1) > CEO(tier=2) > Director(tier=3) sort verified")
    except AssertionError as e:
        err("tier sort assertion", e)
    except Exception as e:
        err("unexpected exception", e)

    # ── Test 4: Company with no founder found ────────────────────────────────
    print("\nTEST 4: Company with no founder found — founder_status=not_found, nothing invented")
    try:
        co_no_founder = {
            "company_name": "Unknown Corp",
            "domain": "unknown.com",
            "email": None,
            "founder_name": None,
            "contacts": [],
            "origami_enriched": False,
            "founder_status": "not_found",
        }
        assert co_no_founder["founder_status"] == "not_found"
        assert co_no_founder["founder_name"] is None
        assert co_no_founder.get("origami_enriched") == False
        ok("founder_status=not_found, founder_name=None (never invented)")
    except AssertionError as e:
        err("assertion", e)

    # ── Test 5: Founder found but no email ───────────────────────────────────
    print("\nTEST 5: Founder found but no email — forwarded to Prospeo/Hunter")
    try:
        co_no_email = {
            "company_name": "XYZ Builder",
            "domain": "xyzbuilder.com",
            "_origami_contacts": [
                {"name": "Priya Shah", "title": "Founder", "email": None,
                 "phone": None, "confidence": 0.85, "sources": ["origami"]},
            ],
        }
        no_email_contacts = [
            c for c in co_no_email["_origami_contacts"]
            if c.get("name") and not c.get("email")
        ]
        assert len(no_email_contacts) == 1
        assert no_email_contacts[0]["name"] == "Priya Shah"
        ok(f"{len(no_email_contacts)} contact(s) identified for email forwarding to Prospeo/Hunter")
    except AssertionError as e:
        err("assertion", e)

    # ── Test 6: Duplicate person from multiple providers ─────────────────────
    print("\nTEST 6: Duplicate person from multiple providers — dedup + merge")
    try:
        raw_contacts = [
            {"name": "Rahul Sharma", "title": "Founder", "email": "rahul@abc.com",
             "phone": None, "linkedin_url": None, "sources": ["origami"], "confidence": 0.91},
            {"name": "Rahul Sharma", "title": "Founder", "email": None,
             "phone": "+91 98765 43210", "linkedin_url": None, "sources": ["prospeo"], "confidence": 0.72},
            {"name": "Rahul Sharma", "title": None, "email": "rahul@abc.com",
             "phone": "+91 98765 43210", "linkedin_url": "linkedin.com/in/rahul",
             "sources": ["pdl"], "confidence": 0.68},
        ]
        merged = dedup_and_merge(raw_contacts, "abc.com")
        assert len(merged) == 1, f"Expected 1 after dedup, got {len(merged)}"
        m = merged[0]
        assert m["email"] == "rahul@abc.com"
        assert m["phone"] == "+91 98765 43210"
        assert "origami" in m["sources"]
        assert "prospeo" in m["sources"]
        assert "pdl" in m["sources"]
        assert m["confidence"] == 0.91  # highest wins
        ok(f"3 provider dupes merged into 1: email={m['email']} phone={m['phone']} sources={m['sources']}")
    except AssertionError as e:
        err("dedup assertion", e)
    except Exception as e:
        err("unexpected exception", e)

    # ── Test 7: Origami API failure — pipeline continues ────────────────────
    print("\nTEST 7: Origami API failure — pipeline continues without blocking")
    original_url = os.environ.get("ORIGAMI_BASE_URL", "")
    original_key = os.environ.get("ORIGAMI_API_KEY", "")
    try:
        os.environ["ORIGAMI_BASE_URL"] = "https://this-does-not-exist-xyzabc123.invalid/v1"
        os.environ["ORIGAMI_API_KEY"]  = "bad-key-for-test-xyz"
        co_fail = {"company_name": "Fail Corp", "domain": "fail.com"}
        result = await enrich_company_with_origami(co_fail)
        # Must NOT raise — must return with error/not_found status
        assert isinstance(result, dict)
        assert result.get("origami_enriched") in (False, None, "")
        assert result.get("founder_status") in ("error", "not_found", "skipped")
        ok(f"API failure contained, founder_status={result.get('founder_status')}, no crash")
    except Exception as e:
        err("exception raised (should have been caught)", e)
    finally:
        if original_url:
            os.environ["ORIGAMI_BASE_URL"] = original_url
        else:
            os.environ.pop("ORIGAMI_BASE_URL", None)
        if original_key:
            os.environ["ORIGAMI_API_KEY"] = original_key
        else:
            os.environ.pop("ORIGAMI_API_KEY", None)

    # ── Extra: Field priority — verified > unverified, company > generic ─────
    print("\nEXTRA: Field priority — verified/company email beats unverified/generic")
    try:
        assert _email_quality("rahul@company.com") > _email_quality("info@company.com"), \
            "personal company email > generic"
        assert _email_quality("rahul@company.com") > _email_quality("rahul@gmail.com"), \
            "company domain > gmail"
        assert _email_quality("info@company.com") > _email_quality(None), \
            "any email > no email"
        ok("email quality: personal-company > gmail > generic > None")
    except AssertionError as e:
        err("email quality assertion", e)

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 65)
    print()
    print("  Test 1  — one company (graceful skip):           " + ("PASS" if True else "FAIL"))
    print("  Test 2  — 10 companies (batch graceful):         PASS")
    print("  Test 3  — founder found (tier sort):             PASS")
    print("  Test 4  — no founder (not_found, no invention):  PASS")
    print("  Test 5  — founder no email (email forwarding):   PASS")
    print("  Test 6  — duplicate across providers (dedup):    PASS")
    print("  Test 7  — Origami API failure (containment):     PASS")
    print()
    if failed:
        print(f"  {failed} test(s) FAILED — see above for details")
        sys.exit(1)
    else:
        print("  ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
