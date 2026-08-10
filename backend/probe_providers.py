#!/usr/bin/env python3
"""
probe_providers.py — Full provider diagnostic.
Run: venv\Scripts\python.exe probe_providers.py
"""
import asyncio
import os
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

import httpx

HUNTER_KEY  = os.getenv("HUNTER_API_KEY", "")
APOLLO_KEY  = os.getenv("APOLLO_API_KEY", "")
PDL_KEY     = os.getenv("PDL_API_KEY", "")
GPLACES_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

TEST_DOMAIN  = "nyatigroup.com"
TEST_COMPANY = "Nyati Group"

SEP  = "=" * 60
DASH = "-" * 60

async def probe_hunter():
    print(SEP)
    print("HUNTER DIAGNOSTIC")
    print(SEP)
    configured = bool(HUNTER_KEY and HUNTER_KEY.strip() and HUNTER_KEY != "your_hunter_api_key_here")
    print(f"  Key configured : {configured}")
    if not configured:
        print("  STATUS: MISSING — Hunter will be SKIPPED")
        return

    async with httpx.AsyncClient(timeout=10) as c:
        # Account check
        try:
            r = await c.get("https://api.hunter.io/v2/account",
                            params={"api_key": HUNTER_KEY})
            print(f"  /account        : HTTP {r.status_code}")
            d = r.json()
            if r.status_code == 200:
                acc = d.get("data", {})
                print(f"  Email           : {acc.get('email', 'N/A')}")
                print(f"  Plan            : {acc.get('plan_name', 'N/A')}")
                searches = acc.get("searches", {})
                print(f"  Searches used   : {searches.get('used', '?')} / {searches.get('available', '?')}")
            else:
                print(f"  Error           : {d}")
        except Exception as e:
            print(f"  /account ERROR  : {e}")
            return

        if r.status_code != 200:
            print("  STATUS: AUTH FAILED — check HUNTER_API_KEY")
            return

        # Domain search
        try:
            r2 = await c.get("https://api.hunter.io/v2/domain-search",
                             params={"domain": TEST_DOMAIN, "limit": 5,
                                     "api_key": HUNTER_KEY})
            print(f"\n  /domain-search  : HTTP {r2.status_code}")
            d2 = r2.json()
            emails = (d2.get("data") or {}).get("emails", [])
            print(f"  Emails found    : {len(emails)}")
            for e in emails[:3]:
                print(f"    {e.get('value')} [{e.get('type')}]")
        except Exception as e:
            print(f"  /domain-search ERROR: {e}")

        # Email finder
        try:
            r3 = await c.get("https://api.hunter.io/v2/email-finder",
                             params={"domain": TEST_DOMAIN, "company": TEST_COMPANY,
                                     "api_key": HUNTER_KEY})
            print(f"\n  /email-finder   : HTTP {r3.status_code}")
            d3 = r3.json()
            found = (d3.get("data") or {}).get("email")
            score = (d3.get("data") or {}).get("score", 0)
            print(f"  Email found     : {found} (score={score})")
        except Exception as e:
            print(f"  /email-finder ERROR: {e}")

    print("  STATUS: OK")


async def probe_apollo():
    print()
    print(SEP)
    print("APOLLO DIAGNOSTIC")
    print(SEP)
    configured = bool(APOLLO_KEY and APOLLO_KEY.strip() and APOLLO_KEY != "your_apollo_api_key_here")
    print(f"  Key configured : {configured}")
    if not configured:
        print("  STATUS: MISSING — Apollo will be SKIPPED")
        return

    async with httpx.AsyncClient(timeout=10) as c:
        # Test header auth on mixed_companies/search (allowed on free tier)
        try:
            r = await c.post(
                "https://api.apollo.io/v1/mixed_companies/search",
                headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json",
                         "Cache-Control": "no-cache"},
                json={"q_organization_name": TEST_COMPANY, "per_page": 3},
            )
            print(f"  mixed_companies/search : HTTP {r.status_code}")
            d = r.json()
            orgs = d.get("organizations") or []
            print(f"  Orgs found      : {len(orgs)}")
            if orgs:
                o = orgs[0]
                print(f"  First org       : {o.get('name')} | {o.get('website_url')}")
            elif r.status_code != 200:
                print(f"  Error           : {str(d)[:200]}")
        except Exception as e:
            print(f"  mixed_companies ERROR: {e}")

        # Test people search
        try:
            r2 = await c.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json",
                         "Cache-Control": "no-cache"},
                json={"q_organization_name": TEST_COMPANY, "per_page": 3,
                      "person_titles": ["founder", "ceo", "co-founder"]},
            )
            print(f"\n  mixed_people/search    : HTTP {r2.status_code}")
            d2 = r2.json()
            people = d2.get("people") or []
            print(f"  People found    : {len(people)}")
            for p in people[:3]:
                print(f"    {p.get('first_name')} {p.get('last_name')} | {p.get('title')} | {p.get('organization', {}).get('name','?')}")
            if r2.status_code != 200:
                print(f"  Error           : {str(d2)[:200]}")
        except Exception as e:
            print(f"  mixed_people ERROR: {e}")

        # Test org enrich (may require paid plan)
        try:
            r3 = await c.post(
                "https://api.apollo.io/v1/organizations/enrich",
                headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"},
                json={"domain": TEST_DOMAIN},
            )
            print(f"\n  organizations/enrich   : HTTP {r3.status_code}")
            d3 = r3.json()
            org = d3.get("organization") or {}
            print(f"  Org name        : {org.get('name', 'N/A')}")
            if r3.status_code == 403:
                print(f"  NOTE: 403 = endpoint not in plan (use mixed_companies/search instead)")
            elif r3.status_code != 200:
                print(f"  Error           : {str(d3)[:150]}")
        except Exception as e:
            print(f"  organizations/enrich ERROR: {e}")

    print("  STATUS: CHECKED (see HTTP codes above)")


async def probe_pdl():
    print()
    print(SEP)
    print("PDL DIAGNOSTIC")
    print(SEP)
    configured = bool(PDL_KEY and PDL_KEY.strip() and PDL_KEY != "your_pdl_api_key_here")
    print(f"  Key configured : {configured}")
    if not configured:
        print("  STATUS: MISSING — PDL will be SKIPPED")
        return

    async with httpx.AsyncClient(timeout=10) as c:
        # Company enrich
        try:
            r = await c.get("https://api.peopledatalabs.com/v5/company/enrich",
                            headers={"X-Api-Key": PDL_KEY},
                            params={"website": TEST_DOMAIN})
            print(f"  /company/enrich : HTTP {r.status_code}")
            d = r.json()
            if r.status_code == 200:
                loc = d.get("location") or {}
                print(f"  Name            : {d.get('name', 'N/A')}")
                print(f"  Location        : {loc.get('name', 'N/A')}")
                print(f"  Country         : {loc.get('country', 'N/A')}")
                print(f"  Industry        : {d.get('industry', 'N/A')}")
            else:
                print(f"  Error           : {str(d)[:200]}")
        except Exception as e:
            print(f"  /company/enrich ERROR: {e}")

        # Person search — simple query
        try:
            r2 = await c.post(
                "https://api.peopledatalabs.com/v5/person/search",
                headers={"X-Api-Key": PDL_KEY},
                json={
                    "query": {"bool": {"must": [
                        {"term": {"job_company_website": TEST_DOMAIN}},
                        {"term": {"job_title": "founder"}},
                    ]}},
                    "size": 3,
                },
            )
            print(f"\n  /person/search (founder, term): HTTP {r2.status_code}")
            d2 = r2.json()
            data = d2.get("data") or []
            print(f"  People found    : {len(data)} (total={d2.get('total',0)})")
            for p in data[:2]:
                print(f"    {p.get('first_name')} {p.get('last_name')} | {p.get('job_title')} | {p.get('job_company_website')}")
        except Exception as e:
            print(f"  /person/search ERROR: {e}")

        # Person search — match query (broader)
        try:
            r3 = await c.post(
                "https://api.peopledatalabs.com/v5/person/search",
                headers={"X-Api-Key": PDL_KEY},
                json={
                    "query": {"bool": {"must": [
                        {"term": {"job_company_website": TEST_DOMAIN}},
                    ]}},
                    "size": 5,
                },
            )
            print(f"\n  /person/search (any role): HTTP {r3.status_code}")
            d3 = r3.json()
            data3 = d3.get("data") or []
            print(f"  People found    : {len(data3)} (total={d3.get('total',0)})")
            for p in data3[:5]:
                print(f"    {p.get('first_name')} {p.get('last_name')} | {p.get('job_title')}")
        except Exception as e:
            print(f"  /person/search (any role) ERROR: {e}")

    print("  STATUS: CHECKED")


async def probe_gplaces():
    print()
    print(SEP)
    print("GOOGLE PLACES DIAGNOSTIC")
    print(SEP)
    configured = bool(GPLACES_KEY and GPLACES_KEY.strip() and GPLACES_KEY != "your_google_maps_api_key_here")
    print(f"  Key configured : {configured}")
    if not configured:
        print("  STATUS: MISSING — Google Places will be SKIPPED")
        print("  NOTE: Set GOOGLE_MAPS_API_KEY in .env to enable phone+address enrichment")
        return

    async with httpx.AsyncClient(timeout=10) as c:
        try:
            r = await c.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": GPLACES_KEY,
                    "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.internationalPhoneNumber",
                },
                json={"textQuery": f"{TEST_COMPANY}, Pune", "languageCode": "en", "pageSize": 3},
            )
            print(f"  /places:searchText : HTTP {r.status_code}")
            d = r.json()
            places = d.get("places") or []
            print(f"  Places found    : {len(places)}")
            for p in places[:3]:
                name = (p.get("displayName") or {}).get("text", "?")
                addr = p.get("formattedAddress", "?")
                phone = p.get("internationalPhoneNumber", "?")
                print(f"    {name} | {addr[:50]} | {phone}")
        except Exception as e:
            print(f"  ERROR: {e}")


async def main():
    print()
    print("=" * 60)
    print("  PROVIDER DIAGNOSTIC — Lead Generation Pipeline")
    print("=" * 60)
    print(f"  Test company : {TEST_COMPANY}")
    print(f"  Test domain  : {TEST_DOMAIN}")
    print()
    print("  Configured keys:")
    print(f"    HUNTER_API_KEY       : {'SET (' + HUNTER_KEY[:8] + '...)' if HUNTER_KEY and HUNTER_KEY != 'your_hunter_api_key_here' else 'MISSING'}")
    print(f"    APOLLO_API_KEY       : {'SET (' + APOLLO_KEY[:8] + '...)' if APOLLO_KEY and APOLLO_KEY != 'your_apollo_api_key_here' else 'MISSING'}")
    print(f"    PDL_API_KEY          : {'SET (' + PDL_KEY[:8] + '...)' if PDL_KEY and PDL_KEY != 'your_pdl_api_key_here' else 'MISSING'}")
    print(f"    GOOGLE_MAPS_API_KEY  : {'SET (' + GPLACES_KEY[:8] + '...)' if GPLACES_KEY and GPLACES_KEY != 'your_google_maps_api_key_here' and GPLACES_KEY.strip() else 'MISSING'}")
    print()

    await probe_hunter()
    await probe_apollo()
    await probe_pdl()
    await probe_gplaces()

    print()
    print(SEP)
    print("  SUMMARY")
    print(SEP)
    print(f"  Hunter       : {'CONFIGURED' if HUNTER_KEY and HUNTER_KEY != 'your_hunter_api_key_here' else 'MISSING'}")
    print(f"  Apollo       : {'CONFIGURED' if APOLLO_KEY and APOLLO_KEY != 'your_apollo_api_key_here' else 'MISSING'}")
    print(f"  PDL          : {'CONFIGURED' if PDL_KEY and PDL_KEY != 'your_pdl_api_key_here' else 'MISSING'}")
    print(f"  Google Places: {'CONFIGURED' if GPLACES_KEY and GPLACES_KEY.strip() and GPLACES_KEY != 'your_google_maps_api_key_here' else 'MISSING'}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
