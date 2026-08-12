"""Careful Prospeo test — respects all rate limits."""
import asyncio, sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv; load_dotenv(".env", override=True)

async def main():
    import httpx
    from prospeo.config import PROSPEO_API_KEY
    h = {"X-KEY": PROSPEO_API_KEY, "Content-Type": "application/json"}

    # First check account info
    async with httpx.AsyncClient(timeout=20) as c:
        acc = await c.get("https://api.prospeo.io/account-information", headers=h)
        print("Account:", json.dumps(acc.json(), indent=2) if acc.status_code == 200 else acc.text[:300])
        print()

    # Wait to clear any rate limits
    print("Waiting 5s to clear rate limits...")
    await asyncio.sleep(5)

    async with httpx.AsyncClient(timeout=20) as c:
        # Step 1: search (1 call)
        r1 = await c.post("https://api.prospeo.io/search-person", headers=h,
            json={"filters": {"company": {"websites": {"include": ["freshworks.com"]}},
                              "person_seniority": {"include": ["Founder/Owner", "C-Suite"]}}, "page": 1})
        print(f"Search HTTP {r1.status_code}")
        hdrs1 = {k: v for k,v in r1.headers.items() if "rate" in k or "limit" in k or "second" in k or "minute" in k or "daily" in k}
        print(f"Rate headers after search: {hdrs1}")

        if r1.status_code != 200:
            print(f"Search failed: {r1.text[:200]}")
            return

        results = r1.json().get("results", [])
        if not results:
            print("No search results")
            return

        pid   = results[0].get("person", {}).get("person_id", "")
        pname = results[0].get("person", {}).get("full_name", "?")
        print(f"Top person: {pname!r}  pid={pid[:16]}...")

        # Wait for per-second reset
        sec_reset = float(r1.headers.get("x-second-reset-seconds", "1"))
        wait = sec_reset + 0.5
        print(f"\nWaiting {wait}s before bulk-enrich...")
        await asyncio.sleep(wait)

        # Step 2: bulk-enrich (1 call)
        r2 = await c.post("https://api.prospeo.io/bulk-enrich-person", headers=h,
            json={"data": [{"identifier": "0", "person_id": pid}], "enrich_mobile": True})

        print(f"\nBulk-enrich HTTP {r2.status_code}")
        hdrs2 = {k: v for k,v in r2.headers.items() if "rate" in k or "limit" in k or "second" in k or "minute" in k or "daily" in k}
        print(f"Rate headers: {hdrs2}")

        if r2.status_code != 200:
            print(f"Bulk error: {r2.text[:300]}")
            return

        body = r2.json()
        print(f"cost={body.get('total_cost')}  matched={len(body.get('matched',[]))}  not_matched={len(body.get('not_matched',[]))}")

        for m in body.get("matched", []):
            p  = m.get("person", {})
            eo = p.get("email") or {}
            mo = p.get("mobile") or {}
            name = p.get("full_name", "?")
            print(f"\n  Person: {name!r}")
            print(f"  email  (full json): {json.dumps(eo)}")
            print(f"  mobile (full json): {json.dumps(mo)}")
            # Show all top-level keys to spot any hidden email fields
            print(f"  all person keys: {list(p.keys())}")

asyncio.run(main())
