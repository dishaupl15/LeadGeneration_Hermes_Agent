#!/usr/bin/env python3
"""
probe_providers3.py — Apollo/PDL deep investigation.
"""
import asyncio, os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
import httpx

APOLLO_KEY = os.getenv("APOLLO_API_KEY", "")
PDL_KEY    = os.getenv("PDL_API_KEY", "")

async def main():
    async with httpx.AsyncClient(timeout=15) as c:

        print("=== APOLLO organizations/search FULL RESPONSE ===")
        r = await c.post("https://api.apollo.io/api/v1/organizations/search",
            headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"},
            json={"q_organization_name": "Nyati Group", "per_page": 3})
        d = r.json()
        orgs = d.get("organizations") or []
        print(f"HTTP {r.status_code}, orgs found: {len(orgs)}")
        for o in orgs[:3]:
            print(f"  Name: {o.get('name')}")
            print(f"  Website: {o.get('website_url')}")
            print(f"  Phone: {o.get('phone')}")
            print(f"  City: {o.get('city')}")
            print(f"  Country: {o.get('country')}")
            print(f"  Primary domain: {o.get('primary_domain')}")
            print()

        print()
        print("=== PDL PERSON SEARCH — job_title_levels filter ===")
        q = {
            "query": {"bool": {"must": [
                {"term": {"job_company_website": "nyatigroup.com"}},
                {"terms": {"job_title_levels": ["owner", "c_suite", "partner", "founder"]}},
            ]}},
            "size": 10,
        }
        r2 = await c.post("https://api.peopledatalabs.com/v5/person/search",
            headers={"X-Api-Key": PDL_KEY}, json=q)
        d2 = r2.json()
        data2 = d2.get("data") or []
        print(f"PDL top-level people: HTTP {r2.status_code}, found={len(data2)}, total={d2.get('total',0)}")
        for p in data2[:10]:
            fn = p.get("first_name", "")
            ln = p.get("last_name", "")
            jt = p.get("job_title", "")
            jl = p.get("job_title_levels", [])
            print(f"  {fn} {ln} | {jt} | levels={jl}")

        print()
        print("=== PDL COMPANY ENRICH for Pune RE firms ===")
        test_domains = ["panchshil.com", "koltepatil.com", "vtprealty.in", "gera.in", "nyatigroup.com"]
        for dom in test_domains:
            r3 = await c.get("https://api.peopledatalabs.com/v5/company/enrich",
                headers={"X-Api-Key": PDL_KEY},
                params={"website": dom})
            d3 = r3.json()
            if r3.status_code == 200:
                loc = d3.get("location") or {}
                phone = d3.get("phone") or "N/A"
                print(f"{dom}: {d3.get('name')} | {loc.get('name')} | phone={phone}")
            else:
                err = (d3.get("error") or {})
                print(f"{dom}: HTTP {r3.status_code} {err}")

        print()
        print("=== APOLLO organizations/search for Pune RE firms ===")
        test_companies = ["Nyati Group", "Panchshil Realty", "VTP Realty", "Kolte Patil", "Gera Developments"]
        for co in test_companies:
            r4 = await c.post("https://api.apollo.io/api/v1/organizations/search",
                headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"},
                json={"q_organization_name": co, "per_page": 2})
            d4 = r4.json()
            orgs4 = d4.get("organizations") or []
            if orgs4:
                o = orgs4[0]
                print(f"{co}: {o.get('name')} | {o.get('website_url')} | city={o.get('city')} | phone={o.get('phone')}")
            else:
                print(f"{co}: no results (HTTP {r4.status_code})")

        print()
        print("=== APOLLO organizations/search for FinTech Pune ===")
        r5 = await c.post("https://api.apollo.io/api/v1/organizations/search",
            headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"},
            json={
                "q_organization_keyword_tags": ["fintech"],
                "organization_locations": ["Pune, Maharashtra, India"],
                "per_page": 5,
            })
        d5 = r5.json()
        orgs5 = d5.get("organizations") or []
        print(f"FinTech Pune geo-filter: HTTP {r5.status_code}, found={len(orgs5)}")
        for o in orgs5[:5]:
            print(f"  {o.get('name')} | {o.get('website_url')} | {o.get('city')},{o.get('country')}")


if __name__ == "__main__":
    asyncio.run(main())
