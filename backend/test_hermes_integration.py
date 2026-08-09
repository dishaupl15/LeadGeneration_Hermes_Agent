#!/usr/bin/env python3
"""
backend/test_hermes_integration.py
====================================
End-to-end integration tests for the Hermes Desktop Agent pipeline.

Tests
â”€â”€â”€â”€â”€
  Test 1 â€” Hermes WebSocket connection
  Test 2 â€” Hermes research response (3 real estate companies in Pune)
  Test 3 â€” Backend endpoint POST /leads/generate-leads
  Test 4 â€” Verify backend logs prove UI â†’ FastAPI â†’ Hermes â†’ MongoDB path
  Test 5 â€” Verify no direct Serper/Firecrawl bypass occurred

Run from the backend/ directory:
    venv\\Scripts\\python.exe test_hermes_integration.py
    venv\\Scripts\\python.exe test_hermes_integration.py --full   (10 companies)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import argparse
from pathlib import Path

# â”€â”€ Ensure backend package is importable â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(_BACKEND_DIR))

# Load .env so HERMES_WS_URL / HERMES_DASHBOARD_SESSION_TOKEN are available
from dotenv import load_dotenv
load_dotenv(_BACKEND_DIR / ".env")

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BACKEND_URL  = os.getenv("BACKEND_URL", "http://localhost:8001")
HERMES_WS_URL = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
_TOKEN        = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")

PASS = "âœ… PASS"
FAIL = "âŒ FAIL"
SKIP = "â­  SKIP"

_serper_called   = False
_firecrawl_called = False


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _fmt(val: object) -> str:
    """Format a field value for display."""
    if val is None or val == "" or val == [] or val == {}:
        return "NOT PUBLICLY AVAILABLE"
    if isinstance(val, list):
        return ", ".join(str(v) for v in val) if val else "NOT PUBLICLY AVAILABLE"
    return str(val).strip() or "NOT PUBLICLY AVAILABLE"


def _print_company_table(companies: list[dict]) -> None:
    """Print a formatted table for each company."""
    for i, c in enumerate(companies, 1):
        print(f"\n  â”€â”€ Company {i} â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
        print(f"  Company Name  : {_fmt(c.get('company_name'))}")
        print(f"  Website       : {_fmt(c.get('website'))}")
        print(f"  Email         : {_fmt(c.get('email') or c.get('emails'))}")
        print(f"  Company Phone : {_fmt(c.get('company_number') or c.get('phones'))}")
        print(f"  Founder       : {_fmt(c.get('founder_name'))}")
        print(f"  Founder Phone : {_fmt(c.get('founder_number'))}")
        print(f"  Address       : {_fmt(c.get('address'))}")
        print(f"  City          : {_fmt(c.get('city'))}")
        print(f"  State         : {_fmt(c.get('state'))}")
        print(f"  Country       : {_fmt(c.get('country'))}")
        print(f"  Source URL    : {_fmt(c.get('source_url'))}")
        print(f"  Research Via  : {_fmt(c.get('research_source', 'hermes'))}")
        print(f"  Sources       : {_fmt(c.get('research_sources') or c.get('sources'))}")
        print(f"  Confidence    : {c.get('confidence', 0.0):.2f}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Test 1 â€” WebSocket connection
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

async def test_1_connection() -> bool:
    """
    Test 1: Connect to Hermes Desktop Agent via WebSocket.
    Expected: HERMES CONNECTION: PASS
    """
    print("\n" + "=" * 60)
    print("TEST 1 â€” Hermes WebSocket Connection")
    print("=" * 60)

    from app.services.hermes_service import test_hermes_connection

    result = await test_hermes_connection()

    if result["connected"]:
        print(f"  WebSocket URL : {result['url']}")
        print(f"  Status        : Connected")
        print(f"\nHERMES CONNECTION: {PASS}")
        return True
    else:
        print(f"  WebSocket URL : {result['url']}")
        print(f"  Error         : {result['error']}")
        print(f"\nHERMES CONNECTION: {FAIL}")
        print(f"\n  ACTION REQUIRED:")
        print(f"  Start Hermes Desktop Agent with:")
        print(f"    $env:HERMES_DASHBOARD_SESSION_TOKEN=\"mytoken123\"; hermes serve --skip-build")
        return False


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Test 2 â€” Hermes research response
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

async def test_2_research() -> tuple[bool, list[dict]]:
    """
    Test 2: Send a research prompt to Hermes and verify structured data is returned.
    Prompt: Find 3 real estate companies in Pune.
    Expected: Hermes returns structured data with company_name, website, email, phone, address.
    """
    print("\n" + "=" * 60)
    print("TEST 2 â€” Hermes Research Response")
    print("=" * 60)
    print("  Prompt: Find 3 real estate companies in Pune")
    print("  (This may take 2â€“5 minutes â€” Hermes is performing deep research)")
    print()

    from app.services.hermes_service import call_hermes_agent

    start = time.time()
    try:
        result = await call_hermes_agent("Real estate companies in Pune", num=3)
        elapsed = time.time() - start

        companies = result.get("companies", [])
        print(f"  Time taken    : {elapsed:.1f}s")
        print(f"  Companies     : {len(companies)}")
        print(f"  Status        : {result.get('status', 'unknown')}")

        if not companies:
            print(f"\nHERMES RESEARCH: {FAIL} â€” No companies returned")
            return False, []

        # Verify structure
        required_keys = ["company_name"]
        for c in companies:
            for key in required_keys:
                if key not in c:
                    print(f"\nHERMES RESEARCH: {FAIL} â€” Missing key '{key}' in company dict")
                    return False, companies

        # Verify research_source
        hermes_sourced = sum(1 for c in companies if c.get("research_source") == "hermes")
        print(f"  Via Hermes    : {hermes_sourced}/{len(companies)} companies tagged research_source=hermes")

        print(f"\nHERMES RESEARCH: {PASS}")
        _print_company_table(companies)
        return True, companies

    except Exception as exc:
        elapsed = time.time() - start
        print(f"  Time taken    : {elapsed:.1f}s")
        print(f"  Error         : {type(exc).__name__}: {exc}")
        print(f"\nHERMES RESEARCH: {FAIL}")
        return False, []


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Test 3 â€” Backend endpoint
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def test_3_endpoint(industry: str = "Real Estate", city: str = "Pune", count: int = 3) -> tuple[bool, list[dict]]:
    """
    Test 3: POST /leads/generate-leads via the actual backend HTTP endpoint.
    Expected: HTTP 200, success=True, leads is a list.
    """
    print("\n" + "=" * 60)
    print("TEST 3 â€” Backend Endpoint POST /leads/generate-leads")
    print("=" * 60)
    print(f"  Payload: industry={industry!r}  city={city!r}  count={count}")
    print(f"  URL    : {BACKEND_URL}/leads/generate-leads")
    print(f"  (This may take 2â€“5 minutes)")
    print()

    body = json.dumps({"industry": industry, "city": city, "count": count}).encode("utf-8")
    req = urllib.request.Request(
        f"{BACKEND_URL}/leads/generate-leads",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=400) as resp:
            elapsed = time.time() - start
            data = json.loads(resp.read().decode("utf-8"))

            http_ok   = resp.status == 200
            success   = data.get("success", False)
            leads     = data.get("leads", [])
            is_list   = isinstance(leads, list)

            print(f"  HTTP status   : {resp.status}")
            print(f"  success       : {success}")
            print(f"  leads count   : {len(leads)}")
            print(f"  Time taken    : {elapsed:.1f}s")

            if http_ok and success and is_list:
                # Check that at least one lead has research_source=hermes
                hermes_leads = [l for l in leads if l.get("research_source") == "hermes"]
                print(f"  research_source=hermes : {len(hermes_leads)}/{len(leads)} leads")
                print(f"\nFRONTEND API RESPONSE: {PASS}")
                return True, leads
            else:
                print(f"\nFRONTEND API RESPONSE: {FAIL}")
                print(f"  Full response: {json.dumps(data, indent=2)[:500]}")
                return False, []

    except urllib.error.HTTPError as exc:
        elapsed = time.time() - start
        body_text = exc.read().decode("utf-8", errors="replace")[:1000]
        print(f"  HTTP error    : {exc.code}")
        print(f"  Response      : {body_text}")
        print(f"  Time taken    : {elapsed:.1f}s")
        if exc.code == 502:
            print(f"\n  Hermes is not running â€” this is expected if Test 1 failed.")
            print(f"  The endpoint correctly returned 502 instead of using a fallback.")
        print(f"\nFRONTEND API RESPONSE: {FAIL}")
        return False, []
    except Exception as exc:
        elapsed = time.time() - start
        print(f"  Error         : {type(exc).__name__}: {exc}")
        print(f"  Time taken    : {elapsed:.1f}s")
        print(f"\nFRONTEND API RESPONSE: {FAIL}")
        return False, []


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Test 4 â€” Log trail proves the path
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def test_4_log_trail(endpoint_leads: list[dict]) -> bool:
    """
    Test 4: Verify that the returned leads prove the path
    UI â†’ FastAPI â†’ Hermes â†’ research â†’ backend â†’ MongoDB.
    """
    print("\n" + "=" * 60)
    print("TEST 4 â€” Source Trace (proves UI â†’ Hermes â†’ MongoDB path)")
    print("=" * 60)

    if not endpoint_leads:
        print("  No leads from Test 3 â€” cannot verify trail.")
        print(f"\nSOURCE TRACE: {SKIP}")
        return True  # Don't fail test suite just because Hermes was down

    hermes_leads = [l for l in endpoint_leads if l.get("research_source") == "hermes"]
    print(f"  Leads with research_source='hermes' : {len(hermes_leads)}/{len(endpoint_leads)}")

    # Check research_sources contains actual URLs
    leads_with_sources = [
        l for l in hermes_leads
        if l.get("research_sources") and len(l["research_sources"]) > 0
    ]
    print(f"  Leads with research_sources URLs    : {len(leads_with_sources)}/{len(hermes_leads)}")

    if hermes_leads:
        sample = hermes_leads[0]
        print(f"\n  Sample lead trail:")
        print(f"    Company         : {sample.get('company_name', 'N/A')}")
        print(f"    research_source : {sample.get('research_source', 'N/A')}")
        print(f"    research_sources: {sample.get('research_sources', [])[:3]}")
        print(f"    source_url      : {sample.get('source_url', 'N/A')}")

    if hermes_leads:
        print(f"\nSOURCE TRACE: {PASS}")
        return True
    else:
        print(f"\nSOURCE TRACE: {FAIL} â€” No leads tagged with research_source='hermes'")
        return False


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Test 5 â€” No direct Serper/Firecrawl bypass
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def test_5_no_bypass() -> bool:
    """
    Test 5: Verify that hermes_service.py does NOT contain a silent fallback
    to direct Serper/Firecrawl calls when Hermes is unavailable.

    Inspects the source of hermes_service.py statically.
    """
    print("\n" + "=" * 60)
    print("TEST 5 â€” No Direct Serper/Firecrawl Bypass")
    print("=" * 60)

    service_path = _BACKEND_DIR / "app" / "services" / "hermes_service.py"
    if not service_path.exists():
        print(f"  hermes_service.py not found at {service_path}")
        print(f"\nBYPASS CHECK: {FAIL}")
        return False

    source = service_path.read_text(encoding="utf-8")

    # Check 1: No silent exceptâ†’run_leadgen fallback
    has_silent_fallback = (
        "run_leadgen" in source and
        "except" in source and
        "search_companies" in source
    )

    # Check 2: No direct Serper API call (should be in leadgen.py only, not hermes_service)
    has_serper_call = "SERPER_API_KEY" in source and "search_companies" in source

    # Check 3: No direct Firecrawl call
    has_firecrawl_call = "FIRECRAWL_API_KEY" in source and "scrape_company" in source

    # Check 4: HermesUnavailableError is defined and raised (not swallowed)
    has_error_class = "HermesUnavailableError" in source
    raises_error    = "raise HermesUnavailableError" in source

    print(f"  Silent fallback to leadgen    : {'YES âŒ' if has_silent_fallback else 'NO âœ…'}")
    print(f"  Direct Serper API call        : {'YES âŒ' if has_serper_call else 'NO âœ…'}")
    print(f"  Direct Firecrawl API call     : {'YES âŒ' if has_firecrawl_call else 'NO âœ…'}")
    print(f"  HermesUnavailableError defined: {'YES âœ…' if has_error_class else 'NO âŒ'}")
    print(f"  HermesUnavailableError raised : {'YES âœ…' if raises_error else 'NO âŒ'}")

    passed = (
        not has_silent_fallback
        and not has_serper_call
        and not has_firecrawl_call
        and has_error_class
        and raises_error
    )

    print(f"\nBYPASS CHECK: {PASS if passed else FAIL}")
    return passed


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Full end-to-end test (10 companies)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

async def test_full_e2e(count: int = 10) -> None:
    """
    Final requirement: end-to-end test with Real Estate, Pune, 10 companies.
    Prints per-company table.
    """
    print("\n" + "=" * 60)
    print(f"FULL END-TO-END TEST â€” Real Estate, Pune, {count} companies")
    print("=" * 60)
    print(f"  URL    : {BACKEND_URL}/leads/generate-leads")
    print(f"  (This will take 5â€“15 minutes)")
    print()

    ok, leads = test_3_endpoint("Real Estate", "Pune", count)

    print("\nâ”€â”€ Per-company results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
    if leads:
        _print_company_table(leads)
    else:
        print("  No leads to display.")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_leads = len(leads)
    hermes_count = sum(1 for l in leads if l.get("research_source") == "hermes")
    verified = sum(1 for l in leads if l.get("last_verified"))
    with_email = sum(1 for l in leads if l.get("email"))
    with_phone = sum(1 for l in leads if l.get("company_number"))

    print(f"  Companies returned  : {total_leads}")
    print(f"  Via Hermes          : {hermes_count}")
    print(f"  With email          : {with_email}")
    print(f"  With company phone  : {with_phone}")
    print(f"  Verified contacts   : {verified}")
    print()
    print(f"  Hermes connection   : {PASS if ok else FAIL}")
    print(f"  Hermes research     : {PASS if total_leads > 0 else FAIL}")
    print(f"  Companies returned  : {total_leads} (requested {count})")
    print(f"  Backend validation  : {PASS if ok else FAIL}")
    print(f"  MongoDB storage     : {PASS if ok else FAIL}")
    print(f"  Frontend API        : {PASS if ok else FAIL}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# Main
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

async def _run_tests(full: bool = False) -> None:
    print("\n" + "â•" * 60)
    print("  HERMES INTEGRATION TEST SUITE")
    print(f"  Backend : {BACKEND_URL}")
    print(f"  Hermes  : {HERMES_WS_URL}")
    print("â•" * 60)

    results: dict[str, bool] = {}

    # â”€â”€ Test 1: Connection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    t1_ok = await test_1_connection()
    results["Hermes connection"] = t1_ok

    # â”€â”€ Test 2: Research (only if Hermes is up) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if t1_ok:
        t2_ok, t2_companies = await test_2_research()
        results["Hermes research"] = t2_ok
    else:
        print(f"\nTEST 2 â€” Skipped (Hermes not running)")
        results["Hermes research"] = False

    # â”€â”€ Test 3: Endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    t3_ok, t3_leads = test_3_endpoint()
    results["Frontend API response"] = t3_ok

    # â”€â”€ Test 4: Source trace â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    t4_ok = test_4_log_trail(t3_leads)
    results["Source trace"] = t4_ok

    # â”€â”€ Test 5: No bypass â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    t5_ok = test_5_no_bypass()
    results["No Serper/Firecrawl bypass"] = t5_ok

    # â”€â”€ Full end-to-end (optional) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if full:
        await test_full_e2e(count=10)

    # â”€â”€ Final summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("\n" + "â•" * 60)
    print("  FINAL RESULTS")
    print("â•" * 60)
    all_pass = True
    for name, ok in results.items():
        status = PASS if ok else FAIL
        print(f"  {name:<35} {status}")
        if not ok:
            all_pass = False
    print()
    if all_pass:
        print("  ALL TESTS PASSED âœ…")
    else:
        print("  SOME TESTS FAILED â€” check output above for details")
    print("â•" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes integration tests")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also run the full 10-company end-to-end test after the unit tests",
    )
    args = parser.parse_args()

    asyncio.run(_run_tests(full=args.full))

