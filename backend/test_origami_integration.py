"""
test_origami_integration.py
────────────────────────────
Integration test for the Origami enrichment workflow.

Tests the full Origami enrichment pipeline against real company records:
  - Fetches 5 existing company records from MongoDB (any category)
  - Runs each through enrich_company_with_origami()
  - If a founder is found without email, runs _enrich_origami_founder_emails()
  - Merges Origami contacts into the people waterfall (PDL → Prospeo → ContactOut → Hunter)
  - Displays results: company → founder → email → phone → other employees → provider/source

Usage (from backend/):
    python test_origami_integration.py
    python test_origami_integration.py --category construction
    python test_origami_integration.py --limit 3
    python test_origami_integration.py --company "ABC Realty" --domain abcrealty.com

The test also works without MongoDB by providing companies on the CLI.
"""
from __future__ import annotations

import asyncio
import argparse
import os
import sys
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(tag: str, msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


# ── Fetch companies from MongoDB ──────────────────────────────────────────────

async def _fetch_companies_from_mongo(
    category: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """
    Fetch `limit` company records from MongoDB to test against.
    Prefers records that have a domain/website and are missing people data.
    Falls back to any 5 records.
    """
    try:
        import motor.motor_asyncio
        uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/crm")
        client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        await client.admin.command("ping")
        db = client["crm"]

        # Determine which collection(s) to query
        from src.config.mongo import collection_for_category, ALL_CATEGORIES
        if category:
            collections = [collection_for_category(category)]
        else:
            # List all leads_* collections
            all_colls = await db.list_collection_names()
            collections = [c for c in all_colls if c.startswith("leads_")]
            if not collections:
                collections = ["leads"]

        # Prefer companies with a website/domain but without contacts or people arrays
        companies: list[dict] = []
        for coll_name in collections:
            if len(companies) >= limit:
                break
            coll = db[coll_name]
            # First: prefer records with website but no Origami enrichment yet
            async for doc in coll.find(
                {"website": {"$exists": True, "$ne": ""},
                 "origami_enriched": {"$ne": True}},
                limit=limit - len(companies),
            ):
                doc["_id"] = str(doc["_id"])
                companies.append(doc)

        # Fallback: any records
        if len(companies) < limit:
            for coll_name in collections:
                if len(companies) >= limit:
                    break
                coll = db[coll_name]
                async for doc in coll.find(
                    {},
                    limit=limit - len(companies),
                ):
                    doc["_id"] = str(doc["_id"])
                    # Skip already fetched
                    if not any(c.get("company_name") == doc.get("company_name") for c in companies):
                        companies.append(doc)

        client.close()
        return companies[:limit]
    except Exception as exc:
        _log("MONGO", f"Could not fetch from MongoDB: {exc}")
        return []


# ── Build minimal company dict from CLI args ──────────────────────────────────

def _make_test_company(name: str, domain: Optional[str] = None) -> dict:
    website = f"https://{domain}" if domain else ""
    return {
        "company_name":   name,
        "domain":         domain or "",
        "website":        website,
        "email":          None,
        "emails":         [],
        "phones":         [],
        "company_number": None,
        "address":        "",
        "city":           "",
        "state":          "",
        "country":        "India",
        "founder_name":   None,
        "contacts":       [],
    }


# ── Run full Origami + waterfall test for one company ─────────────────────────

async def test_one_company(company: dict) -> dict:
    """
    Run the full Origami → email-forwarding → PDL/Prospeo/ContactOut/Hunter
    pipeline for a single company dict.

    Returns the enriched company dict.
    """
    name = company.get("company_name", "?")
    domain = company.get("domain") or ""
    _log("TEST", f"─── {name!r} (domain={domain or 'none'!r}) ───")

    t0 = time.monotonic()

    # ── Step 1: Origami enrichment ────────────────────────────────────────────
    from app.services.origami_service import (
        enrich_company_with_origami,
        is_configured as origami_configured,
        _enrich_origami_founder_emails,
    )

    if not origami_configured():
        _log("ORIGAMI", "ORIGAMI_API_KEY not set — simulating empty result")
        company["origami_enriched"] = False
        company["founder_status"]   = "skipped"
    else:
        company = await enrich_company_with_origami(company)
        _log("ORIGAMI", (
            f"origami_enriched={company.get('origami_enriched')} "
            f"founder_status={company.get('founder_status')} "
            f"people={len(company.get('people') or [])}"
        ))

        # ── Step 1b: Email forwarding for name-only contacts ──────────────────
        no_email_contacts = [
            c for c in (company.get("_origami_contacts") or [])
            if c.get("name") and not c.get("email")
        ]
        if no_email_contacts and domain:
            _log("EMAIL_FWD", f"Forwarding {len(no_email_contacts)} name-only contacts to Prospeo/Hunter")
            company = await _enrich_origami_founder_emails(company)

    # ── Step 2: People waterfall (PDL → Prospeo → ContactOut → Hunter) ────────
    origami_contacts = list(company.get("_origami_contacts") or [])
    company.pop("_origami_contacts", None)  # remove staging field before waterfall

    from people_enrichment.orchestrator import enrich_company_contacts, reset_cache
    reset_cache()

    result = await enrich_company_contacts(
        company_name=name,
        domain=domain or None,
        website=company.get("website") or None,
        origami_contacts=origami_contacts if origami_contacts else None,
    )

    elapsed = round(time.monotonic() - t0, 2)
    _log("WATERFALL", (
        f"contacts={result.contacts_found} "
        f"emails={result.emails_found} "
        f"phones={result.phones_found} "
        f"providers={result.providers_used} "
        f"elapsed={elapsed}s"
    ))

    # Attach contacts to company dict
    company["contacts"] = [
        {
            "name":         c.name,
            "title":        c.title,
            "email":        c.email,
            "phone":        c.phone,
            "linkedin_url": c.linkedin_url,
            "sources":      list(c.sources),
            "confidence":   c.confidence,
        }
        for c in result.contacts
    ]

    return company


# ── Pretty-print results ───────────────────────────────────────────────────────

def _print_result(company: dict, idx: int) -> None:
    """Print one company's enrichment result in the requested format."""
    name   = company.get("company_name", "?")
    domain = company.get("domain") or ""
    print()
    print(f"{'═'*65}")
    print(f"  [{idx}] {name}")
    if domain:
        print(f"       Domain : {domain}")
    print(f"{'─'*65}")

    # ── Founder / Owner ───────────────────────────────────────────────────────
    founder_status  = company.get("founder_status", "skipped")
    founder_name    = company.get("founder_name")
    founder_title   = company.get("founder_title")
    founder_email   = company.get("founder_email") or company.get("email")
    founder_phone   = company.get("founder_number") or company.get("company_number")
    founder_profile = company.get("founder_profile_url")
    origami_conf    = company.get("origami_confidence", 0.0)
    origami_src     = company.get("origami_source", "—")

    print(f"\n  Origami Status : {founder_status}")
    if company.get("origami_enriched"):
        print(f"  Origami Conf   : {origami_conf:.2f}  source={origami_src}")

    print()

    if founder_name:
        print(f"  ▶ Founder/Owner")
        print(f"       Name    : {founder_name}")
        if founder_title:
            print(f"       Title   : {founder_title}")
        print(f"       Email   : {founder_email or '—'}")
        print(f"       Phone   : {founder_phone or '—'}")
        if founder_profile:
            print(f"       Profile : {founder_profile}")
    else:
        print(f"  ▶ Founder/Owner : NOT FOUND (founder_status={founder_status})")

    # ── All Origami people (from people[] field) ──────────────────────────────
    people = company.get("people") or []
    if people:
        print(f"\n  Origami People ({len(people)} total):")
        for i, p in enumerate(people, 1):
            tier_lbl = p.get("tier_label", "Other")
            print(f"    [{i}] {tier_lbl} | {p.get('name') or '—'}")
            print(f"         Title   : {p.get('title') or '—'}")
            print(f"         Email   : {p.get('email') or '—'}")
            print(f"         Phone   : {p.get('phone') or '—'}")
            print(f"         Conf    : {p.get('confidence', 0):.2f}")
            print(f"         Source  : {p.get('source', '—')}")

    # ── All enriched contacts (from waterfall — deduped, merged) ─────────────
    contacts = company.get("contacts") or []
    if contacts:
        print(f"\n  Enriched Contacts ({len(contacts)} after dedup/merge):")
        for i, ct in enumerate(contacts, 1):
            srcs = ", ".join(ct.get("sources") or [])
            print(f"    [{i}] {ct.get('name') or '—'}")
            print(f"         Title   : {ct.get('title') or '—'}")
            print(f"         Email   : {ct.get('email') or '—'}")
            print(f"         Phone   : {ct.get('phone') or '—'}")
            print(f"         Sources : {srcs or '—'}")
            print(f"         Conf    : {ct.get('confidence', 0):.2f}")
    else:
        print("\n  Enriched Contacts : none found")

    print(f"\n  Company Email  : {company.get('email') or '—'}")
    print(f"  Company Phone  : {company.get('company_number') or '—'}")
    print(f"{'═'*65}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(args) -> None:
    print(f"\n{'═'*65}")
    print("  Origami Integration Test")
    print(f"{'═'*65}")

    # Check API key
    from app.services.origami_service import is_configured, _api_key, _base_url, _timeout
    api_key = _api_key()
    print(f"  ORIGAMI_API_KEY : {'SET (' + api_key[:12] + '…)' if api_key else 'NOT SET — enrichment will be simulated'}")
    print(f"  ORIGAMI_BASE_URL: {_base_url()}")
    print(f"  Timeout         : {_timeout()}s")

    # Determine companies to test
    companies: list[dict] = []

    if args.company:
        # CLI-provided company
        companies = [_make_test_company(args.company, args.domain)]
        _log("INPUT", f"Using CLI company: {args.company!r}")
    else:
        # Fetch from MongoDB
        _log("INPUT", f"Fetching {args.limit} companies from MongoDB (category={args.category or 'any'})")
        companies = await _fetch_companies_from_mongo(
            category=args.category,
            limit=args.limit,
        )

        if not companies:
            _log("INPUT", "No companies found in MongoDB — using built-in test companies")
            # Fallback: well-known Indian companies for realistic testing
            companies = [
                _make_test_company("Tata Consultancy Services", "tcs.com"),
                _make_test_company("Infosys Limited",            "infosys.com"),
                _make_test_company("Godrej Properties",          "godrejproperties.com"),
                _make_test_company("Prestige Group",             "prestigeconstructions.com"),
                _make_test_company("DLF Limited",                "dlf.in"),
            ]

    print(f"\n  Testing {len(companies)} companies\n")

    # Run enrichment for each company
    results: list[dict] = []
    for i, company in enumerate(companies, 1):
        try:
            enriched = await test_one_company(company)
            results.append(enriched)
        except Exception as exc:
            _log("ERROR", f"Failed for {company.get('company_name','?')}: {exc}")
            results.append(company)

    # Print summary
    print(f"\n\n{'═'*65}")
    print("  RESULTS SUMMARY")
    print(f"{'═'*65}")

    for i, company in enumerate(results, 1):
        _print_result(company, i)

    # Print aggregate stats
    print(f"\n{'─'*65}")
    print("  AGGREGATE STATS")
    print(f"{'─'*65}")
    n = len(results)
    n_origami    = sum(1 for c in results if c.get("origami_enriched"))
    n_founders   = sum(1 for c in results if c.get("founder_name"))
    n_f_emails   = sum(1 for c in results if c.get("founder_email") or c.get("email"))
    n_contacts   = sum(1 for c in results if c.get("contacts"))
    total_people = sum(len(c.get("people") or []) for c in results)
    total_ct     = sum(len(c.get("contacts") or []) for c in results)

    print(f"  Companies tested     : {n}")
    print(f"  Origami enriched     : {n_origami}/{n}")
    print(f"  Founders found       : {n_founders}/{n}")
    print(f"  Companies with email : {n_f_emails}/{n}")
    print(f"  With contacts        : {n_contacts}/{n}")
    print(f"  Total Origami people : {total_people}")
    print(f"  Total merged contacts: {total_ct}")
    print()

    # Show per-company one-liner
    print("  Per-company summary:")
    for c in results:
        fstatus = c.get("founder_status", "skipped")
        fname   = c.get("founder_name") or "—"
        femail  = c.get("founder_email") or c.get("email") or "—"
        fphone  = c.get("founder_number") or c.get("company_number") or "—"
        npeople = len(c.get("people") or [])
        ncts    = len(c.get("contacts") or [])
        print(
            f"  {c.get('company_name','?'):35s} | "
            f"founder={fname:25s} | "
            f"email={femail:35s} | "
            f"phone={fphone:15s} | "
            f"origami_people={npeople} contacts={ncts} | "
            f"status={fstatus}"
        )
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test Origami enrichment integration against real company records"
    )
    parser.add_argument(
        "--company", type=str, default=None,
        help="Test a specific company name (use with --domain)"
    )
    parser.add_argument(
        "--domain", type=str, default=None,
        help="Domain for the company (e.g. tcs.com)"
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Fetch companies from this category's MongoDB collection (e.g. construction)"
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Number of companies to test from MongoDB (default: 5)"
    )
    args = parser.parse_args()

    asyncio.run(main(args))
