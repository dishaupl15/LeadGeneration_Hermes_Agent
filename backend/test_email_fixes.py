"""
Minimal test for the 7 email-flow fixes.
Run from backend/ with: venv\Scripts\python test_email_fixes.py
"""
import sys, os, asyncio, re
sys.path.insert(0, os.path.dirname(__file__))

# ── Req 3: _normalize_email strips mailto/markdown ────────────────────────────
from app.services.discovery_service import _normalize_email

def test_normalize_email():
    assert _normalize_email("mailto:info@example.com") == "info@example.com"
    assert _normalize_email("[info@example.com](mailto:info@example.com)") == "info@example.com"
    assert _normalize_email("  INFO@Example.COM  ") == "info@example.com"
    assert _normalize_email("plain@example.com") == "plain@example.com"
    print("PASS  Req 3: _normalize_email strips mailto/markdown")

# ── Req 5: verify_service.verify_email accepts same-root-label TLD variants ───
from app.services.verify_service import verify_email

async def test_verify_email_domain_variants():
    import httpx
    sem = asyncio.Semaphore(1)
    client = httpx.AsyncClient()

    # Exact match
    email, src, status = await verify_email("Acme", "acme.com", "info@acme.com", "", client, sem)
    assert email == "info@acme.com", f"Expected info@acme.com, got {email!r}"
    assert status == "verified_domain"

    # Subdomain match
    email, src, status = await verify_email("Acme", "acme.com", "info@mail.acme.com", "", client, sem)
    assert email == "info@mail.acme.com", f"Subdomain should pass, got {email!r}"

    # Same root label, different TLD (.com vs .in) — Req 5 fix
    email, src, status = await verify_email("Acme", "acme.com", "info@acme.in", "", client, sem)
    assert email == "info@acme.in", f"Same root label should pass, got {email!r} status={status}"

    # mailto: normalization in verify_email — Req 3 fix
    email, src, status = await verify_email("Acme", "acme.com", "mailto:info@acme.com", "", client, sem)
    assert email == "info@acme.com", f"mailto: should be stripped, got {email!r}"

    # Completely different domain — must still reject
    email, src, status = await verify_email("Acme", "acme.com", "info@other.com", "", client, sem)
    assert email is None, f"Different domain should be rejected, got {email!r}"

    await client.aclose()
    print("PASS  Req 5: verify_email accepts same-root TLD variants, rejects unrelated domains")

# ── Req 2/4: CE email preserved through validate_contacts ─────────────────────
def test_ce_email_preserved_in_validate_contacts():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "leadgen", pathlib.Path(__file__).parent / "tools" / "leadgen.py"
    )
    lg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lg)

    company = {
        "_ce_enriched": True,
        "email": "founder@acmepharma.com",
        "emails": ["founder@acmepharma.com"],
        "phones": [],
        "_field_verification": {
            "email": {
                "value": "founder@acmepharma.com",
                "verified": True,
                "status": "companyenrich_email",
                "source": "companyenrich.com",
            }
        },
    }
    result = lg.validate_contacts(company)
    assert "founder@acmepharma.com" in result["validated_emails"], (
        f"CE email must survive validate_contacts. validated_emails={result['validated_emails']}"
    )
    print("PASS  Req 2/4: CE email preserved through validate_contacts")

# ── Req 2/4: CE email not rejected when not in scraped pages ──────────────────
def test_ce_email_not_rejected_for_missing_scraped_pages():
    """
    CE companies have _scraped_pages=[]. verify_company_data (leadgen) uses
    the CE fast-path which trusts _field_verification, not scraped pages.
    """
    import importlib.util, pathlib
    from datetime import datetime, timezone
    spec = importlib.util.spec_from_file_location(
        "leadgen", pathlib.Path(__file__).parent / "tools" / "leadgen.py"
    )
    lg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lg)

    company = {
        "_ce_enriched": True,
        "company_name": "Acme Pharma",
        "email": "founder@acmepharma.com",
        "emails": ["founder@acmepharma.com"],
        "company_number": "+91 20 12345678",
        "phones": ["+91 20 12345678"],
        "website": "https://acmepharma.com",
        "domain": "acmepharma.com",
        "confidence": 0.55,
        "_scraped_pages": [],
        "_merged_markdown": "",
        "_field_verification": {
            "email": {"value": "founder@acmepharma.com", "verified": True,
                      "status": "companyenrich_email", "source": "companyenrich.com"},
            "phone": {"value": "+91 20 12345678", "verified": True,
                      "status": "companyenrich_phone", "source": "companyenrich.com"},
        },
    }
    result = lg.verify_company_data(company)
    assert result.get("last_verified") is not None, (
        "CE company with verified email/phone must have last_verified set"
    )
    print("PASS  Req 2/4: CE email not rejected for missing scraped pages (CE fast-path)")

# ── Req 1: No Hunter/Apollo/PDL/Google Places imports ─────────────────────────
def test_no_other_providers():
    with open(os.path.join(os.path.dirname(__file__), "app/services/enrichment_service.py"),
              encoding="utf-8") as f:
        src = f.read()
    for provider in ("hunter_service", "apollo_service", "pdl_service", "google_places_service"):
        assert f"import {provider}" not in src and f"from app.services.{provider}" not in src, (
            f"enrichment_service.py must not import {provider}"
        )
    print("PASS  Req 1: enrichment_service uses only CompanyEnrich")

# ── Req 6: CE enrichment not called for filtered-out candidates ───────────────
def test_category_gate_before_ce_enrich():
    """
    _is_category_relevant and _is_location_relevant_ce run before candidates
    are added to the list that feeds _process_ce_candidate.
    Verify the gate functions exist and work correctly.
    """
    from app.services.discovery_service import _is_category_relevant, _is_location_relevant_ce

    # A hotel result should be rejected for a manufacturing query
    hotel_result = {
        "name": "Grand Hotel Pune",
        "industry": "hotel",
        "description": "luxury hotel accommodation resort",
    }
    assert not _is_category_relevant(hotel_result, "manufacturing"), (
        "Hotel must be rejected for manufacturing category"
    )

    # A manufacturing company in Bengaluru should be rejected for Pune query
    blr_result = {
        "name": "Bengaluru Precision Parts",
        "industry": "manufacturing",
        "description": "precision engineering manufacturer",
        "location": {
            "city": {"name": "Bengaluru"},
            "state": {"name": "Karnataka"},
            "address": "Whitefield, Bengaluru",
        },
    }
    assert not _is_location_relevant_ce(blr_result, "pune"), (
        "Bengaluru company must be rejected for Pune query"
    )
    print("PASS  Req 6: Category/location gates prevent unnecessary CE enrichment calls")

if __name__ == "__main__":
    test_normalize_email()
    test_ce_email_preserved_in_validate_contacts()
    test_ce_email_not_rejected_for_missing_scraped_pages()
    test_no_other_providers()
    test_category_gate_before_ce_enrich()
    asyncio.run(test_verify_email_domain_variants())
    print("\nAll tests passed.")
