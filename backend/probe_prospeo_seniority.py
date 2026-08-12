"""
probe_prospeo_seniority.py
───────────────────────────
Live probe to discover exactly which seniority values Prospeo accepts.

Strategy:
  1. Try each candidate seniority value in isolation.
  2. Record which ones return 200 vs 400 INVALID_FILTERS.
  3. Try a working combination and confirm we get results.

Run: python probe_prospeo_seniority.py
"""
import asyncio
import json
from datetime import datetime

import httpx
from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=True, encoding="utf-8-sig")
API_KEY  = os.getenv("PROSPEO_API_KEY", "").strip()
BASE_URL = "https://api.prospeo.io"

def _headers():
    return {"X-KEY": API_KEY, "Content-Type": "application/json"}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ─────────────────────────────────────────────────────────────────────────────
# Candidates to test — include what we currently send PLUS likely alternatives
# ─────────────────────────────────────────────────────────────────────────────
CANDIDATES = [
    # What we currently send (known bad)
    "VP",
    "Manager",
    # Likely valid based on Prospeo docs
    "Founder/Owner",
    "C-Suite",
    "Director",
    "Partner",
    "President",
    "Chairman",
    # Other common variants
    "Senior",
    "Executive",
    "VP Level",
    "Vice President",
    "Head",
    "Lead",
]

# A real domain to test against (small company, likely has indexed people)
TEST_DOMAIN  = "intercom.com"
TEST_COMPANY = "Intercom"

async def test_single_seniority(client: httpx.AsyncClient, value: str) -> str:
    """Try one seniority value. Return 'ok', 'invalid', or 'error:...'"""
    payload = {
        "filters": {
            "company": {"websites": {"include": [TEST_DOMAIN]}},
            "person_seniority": {"include": [value]},
        },
        "page": 1,
    }
    try:
        resp = await client.post(f"{BASE_URL}/search-person", headers=_headers(), json=payload, timeout=15)
    except Exception as e:
        return f"network_error:{e}"

    if resp.status_code == 200:
        body = resp.json()
        n = len(body.get("results") or [])
        return f"ok (results={n})"
    try:
        body = resp.json()
        ec   = body.get("error_code", "")
        msg  = body.get("message", "")[:120]
    except Exception:
        ec, msg = "", resp.text[:120]
    return f"HTTP{resp.status_code} ec={ec!r} {msg!r}"


async def test_no_seniority_filter(client: httpx.AsyncClient) -> dict:
    """Search with NO seniority filter — just company domain."""
    payload = {
        "filters": {
            "company": {"websites": {"include": [TEST_DOMAIN]}},
        },
        "page": 1,
    }
    resp = await client.post(f"{BASE_URL}/search-person", headers=_headers(), json=payload, timeout=15)
    if resp.status_code == 200:
        body = resp.json()
        results = body.get("results") or []
        total   = (body.get("pagination") or {}).get("total_count", len(results))
        return {"status": "ok", "results": len(results), "total": total, "raw": results[:2]}
    return {"status": f"HTTP{resp.status_code}", "body": resp.text[:200]}


async def test_combined_valid(client: httpx.AsyncClient, values: list[str]) -> dict:
    """Test a combined seniority list."""
    payload = {
        "filters": {
            "company": {"websites": {"include": [TEST_DOMAIN]}},
            "person_seniority": {"include": values},
        },
        "page": 1,
    }
    resp = await client.post(f"{BASE_URL}/search-person", headers=_headers(), json=payload, timeout=15)
    if resp.status_code == 200:
        body    = resp.json()
        results = body.get("results") or []
        total   = (body.get("pagination") or {}).get("total_count", len(results))
        # Extract titles from first few results
        titles = []
        for r in results[:5]:
            p = r.get("person") or {}
            titles.append(f"{p.get('full_name','?')} / {p.get('current_job_title','?')}")
        return {"status": "ok", "results": len(results), "total": total, "titles": titles}
    try:
        body = resp.json()
        return {"status": f"HTTP{resp.status_code}", "error_code": body.get("error_code"), "msg": body.get("message","")[:200]}
    except Exception:
        return {"status": f"HTTP{resp.status_code}", "body": resp.text[:200]}


async def main():
    print("=" * 65)
    print("PROSPEO SENIORITY PROBE")
    print(f"Target: {TEST_DOMAIN}")
    print("=" * 65)

    if not API_KEY:
        print("ERR: PROSPEO_API_KEY not set in .env")
        return

    async with httpx.AsyncClient(follow_redirects=True) as client:

        # ── Step 1: test each candidate individually ─────────────────────────
        print()
        print("STEP 1 — Testing individual seniority values:")
        valid_values = []
        for val in CANDIDATES:
            result = await test_single_seniority(client, val)
            status = "VALID" if result.startswith("ok") else "INVALID"
            log(f"  {status:7} {val!r:25} → {result}")
            if status == "VALID":
                valid_values.append(val)

        print()
        print(f"Valid seniority values found: {valid_values}")

        # ── Step 2: test with no seniority filter ────────────────────────────
        print()
        print("STEP 2 — Search with NO seniority filter (baseline):")
        no_filter = await test_no_seniority_filter(client)
        log(f"  Result: {no_filter}")

        # ── Step 3: test combined valid list ─────────────────────────────────
        if valid_values:
            print()
            print(f"STEP 3 — Combined valid list {valid_values}:")
            combined = await test_combined_valid(client, valid_values)
            log(f"  Result: {json.dumps(combined, indent=2)}")

        # ── Step 4: test the EXACT current filter list (what's causing the error) ──
        print()
        print("STEP 4 — Current filter list (what the code sends TODAY):")
        current_list = ["Founder/Owner", "C-Suite", "VP", "Director", "Manager"]
        bad = await test_combined_valid(client, current_list)
        log(f"  Current list {current_list}: {bad}")

        # ── Step 5: fixed list without 'VP' and 'Manager' ────────────────────
        print()
        print("STEP 5 — Fixed list (without VP and Manager):")
        fixed_list = [v for v in current_list if v not in ("VP", "Manager")]
        if fixed_list:
            fixed = await test_combined_valid(client, fixed_list)
            log(f"  Fixed list {fixed_list}: {json.dumps(fixed, indent=2)}")

    print()
    print("=" * 65)
    print("PROBE COMPLETE — use the VALID values above to fix the code")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
