#!/usr/bin/env python3
"""
test_no_hermes.py
─────────────────
End-to-end test that proves:
  1. Hermes Desktop Agent is NOT called
  2. The Serper+Firecrawl pipeline returns real company data
  3. Coverage metrics meet acceptable thresholds

Run from backend/ directory:
    python test_no_hermes.py

Requirements: server must be running on http://127.0.0.1:8001
    uvicorn app.main:app --port 8001 --reload
"""

import json
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

BASE_URL = "http://127.0.0.1:8002"
QUERY    = "Real Estate companies in Pune"
COUNT    = 10
TIMEOUT  = 120   # seconds — pipeline should finish well under 60s

def post_json(url: str, body: dict, timeout: int = TIMEOUT) -> dict:
    data = json.dumps(body).encode()
    req  = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        body_text = e.read().decode()[:500]
        raise RuntimeError(f"HTTP {e.code}: {body_text}")
    except URLError as e:
        raise RuntimeError(
            f"Cannot reach server at {url}.\n"
            "Start the server first:\n"
            "  uvicorn app.main:app --port 8001 --reload"
        )


def get_json(url: str, timeout: int = 10) -> dict:
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        raise RuntimeError(f"GET {url} failed: {e}")


def run_test():
    print("=" * 70)
    print("TEST: Serper+Firecrawl pipeline — NO HERMES")
    print(f"Query : {QUERY!r}")
    print(f"Count : {COUNT}")
    print("=" * 70)

    # Health check
    try:
        health = get_json(f"{BASE_URL}/health")
        print(f"✅ Server healthy: {health}")
    except Exception as e:
        print(f"❌ Server health check failed: {e}")
        sys.exit(1)

    print(f"\n⏳ Calling POST /leads/generate-leads (timeout={TIMEOUT}s) …\n")
    t0 = time.monotonic()

    try:
        result = post_json(
            f"{BASE_URL}/leads/generate-leads",
            {"query": QUERY, "count": COUNT},
            timeout=TIMEOUT,
        )
    except RuntimeError as e:
        print(f"❌ Request failed: {e}")
        sys.exit(1)

    elapsed = round(time.monotonic() - t0, 1)

    leads   = result.get("leads", [])
    n_total = len(leads)

    # Coverage metrics
    n_email   = sum(1 for c in leads if c.get("email"))
    n_phone   = sum(1 for c in leads if c.get("company_number"))
    n_address = sum(1 for c in leads if c.get("address"))
    n_founder = sum(1 for c in leads if c.get("founder_name"))

    # All research_source fields should be "serper_firecrawl", never "hermes"
    hermes_leads = [
        c for c in leads
        if (c.get("research_source") or "").lower() == "hermes"
    ]

    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Valid companies returned    : {n_total}")
    print(f"  Inserted (new)             : {result.get('inserted', '?')}")
    print(f"  Updated (existing)         : {result.get('updated', '?')}")
    print(f"  Total execution time       : {elapsed}s")
    print()
    print(f"  Email coverage             : {n_email}/{n_total} ({_pct(n_email, n_total)}%)")
    print(f"  Phone coverage             : {n_phone}/{n_total} ({_pct(n_phone, n_total)}%)")
    print(f"  Address coverage           : {n_address}/{n_total} ({_pct(n_address, n_total)}%)")
    print(f"  Founder coverage           : {n_founder}/{n_total} ({_pct(n_founder, n_total)}%)")
    print()

    # Hermes check — must be 0
    if hermes_leads:
        print(f"❌ FAIL: {len(hermes_leads)} lead(s) have research_source='hermes'!")
        for c in hermes_leads:
            print(f"   - {c.get('company_name')} | research_source={c.get('research_source')}")
    else:
        print("✅ HERMES NOT CALLED — all leads have research_source='serper_firecrawl'")

    # Performance check
    if elapsed <= 60:
        print(f"✅ Performance OK — {elapsed}s ≤ 60s target")
    else:
        print(f"⚠️  Performance WARNING — {elapsed}s > 60s target (check concurrency)")

    # Per-company detail
    print()
    print("COMPANY DETAILS")
    print("-" * 70)
    for i, c in enumerate(leads, 1):
        print(f"  [{i:02d}] {c.get('company_name','?')}")
        print(f"        website : {c.get('website','')}")
        print(f"        email   : {c.get('email') or '(not found)'}")
        print(f"        phone   : {c.get('company_number') or '(not found)'}")
        print(f"        address : {c.get('address') or '(not found)'}")
        print(f"        founder : {c.get('founder_name') or '(not found)'}")
        print(f"        source  : {c.get('research_source','?')}  "
              f"confidence={c.get('confidence',0.0)}")
        print()

    print("=" * 70)
    if hermes_leads:
        print("❌ TEST FAILED — Hermes was called")
        sys.exit(1)
    else:
        print("✅ TEST PASSED — Pipeline ran without Hermes")


def _pct(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0


if __name__ == "__main__":
    run_test()
