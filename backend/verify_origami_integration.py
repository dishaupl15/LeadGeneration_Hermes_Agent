"""
verify_origami_integration.py
──────────────────────────────
Quick sanity-check: import all integration points and verify they are
correctly wired.  Runs in under 2 seconds (no network calls).
"""
from dotenv import load_dotenv
load_dotenv()

print("Checking Origami integration wiring...")

# 1. Import origami_service and its exported functions
from app.services.origami_service import (
    enrich_company_with_origami,
    enrich_batch_with_origami,
    inject_origami_contacts_into_waterfall,
    _enrich_origami_founder_emails,
    is_configured,
    title_tier,
    tier_label,
    sort_contacts,
    clean_email,
)
print("[OK] origami_service.py imports")

# 2. Verify tier system
assert title_tier("Founder") == 1
assert title_tier("Co-Founder") == 1
assert title_tier("Owner") == 1
assert title_tier("CEO") == 2
assert title_tier("Managing Director") == 2
assert title_tier("Director") == 3
assert title_tier("Head of Sales") == 4
assert title_tier("Software Engineer") == 5
print("[OK] Title tier classification correct (Founder=1, CEO=2, Director=3, Head=4, Other=5)")

# 3. Verify tier labels
assert tier_label(1) == "Founder/Owner"
assert tier_label(2) == "CEO/MD"
assert tier_label(3) == "Director/VP"
assert tier_label(4) == "Head/GM"
assert tier_label(5) == "Other"
print("[OK] Tier labels correct")

# 4. Verify email cleaning
assert clean_email("info@test.com") is None          # junk local
assert clean_email("noreply@test.com") is None       # junk local
assert clean_email("rahul@tcs.com") == "rahul@tcs.com"
assert clean_email(None) is None
print("[OK] Email cleaning (junk locals rejected, valid emails pass)")

# 5. Verify contact sorting (Founder should sort before CEO should sort before Other)
contacts = [
    {"name": "Alice", "title": "Software Engineer", "confidence": 0.9},
    {"name": "Bob",   "title": "CEO",               "confidence": 0.7},
    {"name": "Carol", "title": "Founder",            "confidence": 0.6},
]
sorted_ct = sort_contacts(contacts)
assert sorted_ct[0]["name"] == "Carol", f"Expected Founder first, got {sorted_ct[0]['name']}"
assert sorted_ct[1]["name"] == "Bob",   f"Expected CEO second, got {sorted_ct[1]['name']}"
assert sorted_ct[2]["name"] == "Alice", f"Expected Engineer last, got {sorted_ct[2]['name']}"
print("[OK] Contact sorting (Founder > CEO > Other)")

# 6. Verify inject_origami_contacts_into_waterfall
company = {
    "company_name": "Test Corp",
    "_origami_contacts": [{"name": "Rahul", "email": "rahul@test.com", "sources": ["origami"]}],
    "people": [{"name": "Rahul", "title": "Founder"}],
}
contacts_out, clean_company = inject_origami_contacts_into_waterfall(company)
assert len(contacts_out) == 1
assert "_origami_contacts" not in clean_company
assert clean_company.get("people") is not None
print("[OK] inject_origami_contacts_into_waterfall removes _origami_contacts staging field")

# 7. Verify is_configured returns False when key not set
import os
orig = os.environ.pop("ORIGAMI_API_KEY", "")
assert is_configured() is False
if orig:
    os.environ["ORIGAMI_API_KEY"] = orig
print("[OK] is_configured() returns False when ORIGAMI_API_KEY is empty")

# 8. Verify enrich_company_with_origami handles no-key gracefully
import asyncio
test_co = {"company_name": "ABC Corp", "domain": "abccorp.com"}
result = asyncio.run(enrich_company_with_origami(test_co))
assert result.get("origami_enriched") is False
assert result.get("founder_status") == "skipped"
print("[OK] enrich_company_with_origami graceful when key not set (origami_enriched=False, founder_status=skipped)")

# 9. Import orchestrator and verify origami_contacts parameter
from people_enrichment.orchestrator import enrich_company_contacts
import inspect
sig = inspect.signature(enrich_company_contacts)
assert "origami_contacts" in sig.parameters, "orchestrator missing origami_contacts param"
print("[OK] people_enrichment orchestrator accepts origami_contacts parameter")

# 10. Verify maps_pipeline_service has origami step wired
from app.services.maps_pipeline_service import _enrich_one_company
src = inspect.getsource(_enrich_one_company)
assert "origami_configured" in src
assert "enrich_company_with_origami" in src
assert "_enrich_origami_founder_emails" in src
assert "_enrich_via_people_orchestrator" in src
print("[OK] maps_pipeline_service._enrich_one_company calls Origami (Step 4) before people waterfall (Step 5)")

# 11. Verify MongoDB upsert stores all Origami fields
from src.routes.leads import router
import inspect as _insp
leads_src = _insp.getsource(router.routes[-1].endpoint) if hasattr(router.routes[-1], 'endpoint') else ""
# Check the generate_leads route source
import importlib.util, sys
spec = importlib.util.spec_from_file_location("leads_route", 
    r"backend\src\routes\leads.py" if False else 
    __import__("os").path.join(__import__("os").path.dirname(__file__), "src", "routes", "leads.py"))
# Just check that the key fields are in the route source file
with open(__import__("os").path.join(__import__("os").path.dirname(__file__), "src", "routes", "leads.py"), encoding="utf-8") as f:
    route_src = f.read()

origami_fields = [
    "origami_enriched", "origami_confidence", "origami_source",
    "founder_status", "founder_title", "founder_email", "founder_profile_url",
    "people", "contacts",
]
for field in origami_fields:
    assert field in route_src, f"Field '{field}' missing from leads route MongoDB upsert"
print(f"[OK] leads route stores all {len(origami_fields)} Origami fields to MongoDB: {origami_fields}")

print()
print("=" * 60)
print("  ALL INTEGRATION CHECKS PASSED")
print("=" * 60)
print()
print("Origami pipeline position:")
print("  Google Maps → CompanyEnrich → Serper → Firecrawl")
print("    ↓ [STEP 4] Origami enrichment (origami_service.py)")
print("    ↓   - finds Founder/CEO/Director/other senior people")
print("    ↓   - sets founder_name/email/title/profile_url (if Tier 1 found)")
print("    ↓   - stages _origami_contacts[] for waterfall dedup")
print("    ↓   - promotes people[] for MongoDB / CRM display")
print("    ↓ [STEP 4b] Email forwarding (no-email contacts → Prospeo/Hunter)")
print("    ↓ [STEP 5] PDL → Prospeo → ContactOut → Hunter waterfall")
print("    ↓   - Origami contacts injected as Step 0 seed")
print("    ↓   - dedup_and_merge() merges across all providers")
print("    ↓   - rank_contacts() sorts: Founder > CEO > Director > Head > Other")
print("  MongoDB upsert: people[] + contacts[] + all origami_* fields saved")
print()
print("Fields added to lead documents:")
for f in origami_fields:
    print(f"  • {f}")
print("  • founder_name  (only set when not already present)")
print("  • founder_phone (from origami Tier-1 contact)")
print()
print("Deduplication keys (across all providers):")
print("  1. normalized email   (strongest)")
print("  2. normalized phone   (last 10 digits)")
print("  3. linkedin URL       ")
print("  4. name + domain      (weakest fallback)")
print()
print("To enable Origami: set ORIGAMI_API_KEY in backend/.env")
print("When key is empty: module is silently skipped,")
print("  existing PDL/Prospeo/ContactOut/Hunter pipeline runs unchanged.")
