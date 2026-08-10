#!/usr/bin/env python3
"""
probe_providers2.py — Deep provider API investigation.
Tests Apollo free-tier endpoints and PDL query formats.
"""
import asyncio, os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
import httpx

APOLLO_KEY = os.getenv("APOLLO_API_KEY", "")
PDL_KEY    = os.getenv("PDL_API_KEY", "")
TEST_DOM   = "nyatigroup.com"
TEST_CO    = "Nyati Group"

async def main():
    async with httpx.AsyncClient(timeout=15) as c:

        print("=== APOLLO FREE TIER ENDPOINT DISCOVERY ===")
        # Apollo free plan only allows certain endpoints
        endpoints_to_try = [
            ("GET",  "https://api.apollo.io/api/v1/auth/health", {}),
            ("POST", "https://api.apollo.io/api/v1/people/search",
             {"q_organization_name": TEST_CO, "per_page": 3,
              "person_titles": ["founder", "ceo"]}),
            ("POST", "https://api.apollo.io/api/v1/organizations/search",
             {"q_organization_name": TEST_CO, "per_page": 3}),
            ("POST", "https://api.apollo.io/v1/contacts/search",
             {"q_organization_name": TEST_CO, "per_page": 3,
              "person_titles": ["founder"]}),
        ]
        for method, url, body in endpoints_to_try:
            try:
                if method == "GET":
                    r = await c.get(url, headers={"X-Api-Key": APOLLO_KEY})
                else:
                    r = await c.post(url,
                        headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"},
                        json=body)
                snippet = str(r.json())[:180].replace("\n", " ")
                print(f"  {method} {url.split('apollo.io')[-1]}: HTTP {r.status_code}")
                print(f"    -> {snippet}")
            except Exception as e:
                print(f"  {method} {url}: ERROR {e}")

        print()
        print("=== PDL PERSON SEARCH — WORKING QUERY FORMATS ===")
        # Test multiple PDL query shapes
        queries = [
            ("term/match combined", {
                "query": {"bool": {"must": [
                    {"term": {"job_company_website": TEST_DOM}},
                    {"match": {"job_title": "founder"}},
                ]}},
                "size": 5,
            }),
            ("term only - all employees", {
                "query": {"bool": {"must": [
                    {"term": {"job_company_website": TEST_DOM}},
                ]}},
                "size": 10,
            }),
            ("company name match", {
                "query": {"bool": {"must": [
                    {"match": {"job_company_name": TEST_CO}},
                    {"match": {"job_title": "founder"}},
                ]}},
                "size": 5,
            }),
        ]
        for label, q in queries:
            r = await c.post("https://api.peopledatalabs.com/v5/person/search",
                headers={"X-Api-Key": PDL_KEY}, json=q)
            d = r.json()
            data = d.get("data") or []
            print(f"  [{label}]: HTTP {r.status_code}, found={len(data)}, total={d.get('total',0)}")
            for p in data[:5]:
                fn = p.get("first_name", "")
                ln = p.get("last_name", "")
                jt = p.get("job_title", "")
                jl = p.get("job_title_levels", [])
                jw = p.get("job_company_website", "")
                print(f"    {fn} {ln} | {jt} | levels={jl} | co={jw}")

        print()
        print("=== PDL COMPANY ENRICH — EXTRA FIELDS ===")
        r = await c.get("https://api.peopledatalabs.com/v5/company/enrich",
            headers={"X-Api-Key": PDL_KEY},
            params={"website": TEST_DOM})
        d = r.json()
        if r.status_code == 200:
            print(f"  Name: {d.get('name')}")
            print(f"  Display name: {d.get('display_name')}")
            print(f"  Industry: {d.get('industry')}")
            loc = d.get("location") or {}
            print(f"  Location.name: {loc.get('name')}")
            print(f"  Location.region: {loc.get('region')}")
            print(f"  Location.country: {loc.get('country')}")
            print(f"  Location.postal: {loc.get('postal_code')}")
            print(f"  Location.street: {loc.get('street_address')}")
            print(f"  Phone: {d.get('phone')}")
            print(f"  LinkedIn: {d.get('linkedin_url')}")
            print(f"  Employee count: {d.get('employee_count')}")
        else:
            print(f"  ERROR: {d}")

        print()
        print("=== PDL COMPANY SEARCH ===")
        r2 = await c.post("https://api.peopledatalabs.com/v5/company/search",
            headers={"X-Api-Key": PDL_KEY},
            json={
                "query": {"bool": {"must": [
                    {"match": {"name": TEST_CO}},
                    {"match": {"location.country": "india"}},
                ]}},
                "size": 3,
            })
        d2 = r2.json()
        data2 = d2.get("data") or []
        print(f"  Company search: HTTP {r2.status_code}, found={len(data2)}")
        for co in data2[:3]:
            print(f"  {co.get('name')} | {co.get('location',{}).get('name')} | {co.get('website')}")


if __name__ == "__main__":
    asyncio.run(main())
