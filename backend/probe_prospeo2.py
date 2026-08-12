"""
probe_prospeo2.py — test the uncertain seniority values after rate limit clears
"""
import asyncio, httpx, os, time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=True, encoding="utf-8-sig")
API_KEY = os.getenv("PROSPEO_API_KEY", "").strip()

async def test(val, domain="intercom.com"):
    hdrs    = {"X-KEY": API_KEY, "Content-Type": "application/json"}
    payload = {
        "filters": {
            "company": {"websites": {"include": [domain]}},
            "person_seniority": {"include": [val]},
        },
        "page": 1,
    }
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post("https://api.prospeo.io/search-person", headers=hdrs, json=payload)
            if r.status_code == 200:
                n = len(r.json().get("results") or [])
                return f"VALID  (results={n})"
            body = r.json()
            ec   = body.get("error_code", "")
            msg  = body.get("message", "")[:80]
            return f"HTTP{r.status_code} ec={ec!r} msg={msg!r}"
        except Exception as e:
            return f"ERROR:{e}"

async def test_combined(vals, domain="intercom.com"):
    hdrs    = {"X-KEY": API_KEY, "Content-Type": "application/json"}
    payload = {
        "filters": {
            "company": {"websites": {"include": [domain]}},
            "person_seniority": {"include": vals},
        },
        "page": 1,
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.prospeo.io/search-person", headers=hdrs, json=payload)
        if r.status_code == 200:
            body    = r.json()
            results = body.get("results") or []
            total   = (body.get("pagination") or {}).get("total_count", len(results))
            titles  = []
            for res in results[:5]:
                p = res.get("person") or {}
                titles.append(f"{p.get('full_name','?')} — {p.get('current_job_title','?')}")
            return {"ok": True, "results": len(results), "total": total, "titles": titles}
        body = r.json()
        return {"ok": False, "status": r.status_code, "ec": body.get("error_code"), "msg": body.get("message","")[:120]}

async def main():
    print("=" * 60)
    print("PROSPEO SENIORITY — ROUND 2 PROBE")
    print("=" * 60)

    # Test the ones that 429'd before
    uncertain = ["Director", "Chairman", "President", "VP Level", "Executive", "Lead"]
    print("\nTesting uncertain values (waited for rate limit):")
    for v in uncertain:
        res = await test(v)
        status = "VALID  " if res.startswith("VALID") else "INVALID"
        print(f"  {status} {v!r:20} -> {res}")
        await asyncio.sleep(4)

    # Confirmed valid from round 1
    confirmed_valid = ["Founder/Owner", "C-Suite", "Vice President", "Head", "Partner", "Manager"]
    print(f"\nConfirmed valid from round 1: {confirmed_valid}")

    # Now test the final PROPOSED fixed filter list
    # Tier A: executives — Founder/Owner, C-Suite, Vice President, Head, Partner
    # Tier B: HR/mgr — Manager
    print("\nTesting PROPOSED Tier A filter:")
    tier_a = ["Founder/Owner", "C-Suite", "Vice President", "Head", "Partner"]
    await asyncio.sleep(5)
    res_a = await test_combined(tier_a)
    print(f"  Tier A {tier_a}: {res_a}")

    print("\nTesting PROPOSED Tier B filter:")
    tier_b = ["Manager"]
    await asyncio.sleep(5)
    res_b = await test_combined(tier_b)
    print(f"  Tier B {tier_b}: {res_b}")

    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
