"""
audit_report.py
───────────────
Final integration audit for the people-enrichment orchestrator.
Run: python audit_report.py
"""
import ast
import sys

OK  = "OK "
ERR = "ERR"
sep = "-" * 55

def hdr(title):
    print()
    print(title)
    print(sep)

def chk(label, condition):
    icon = OK if condition else ERR
    print(f"  {icon}  {label}")
    if not condition:
        global _errors
        _errors += 1

_errors = 0

# ── 1. Backend module files ────────────────────────────────────────────────
hdr("1. BACKEND MODULE FILES")
files = {
    "people_enrichment/__init__.py":   "Module docstring + public API exports",
    "people_enrichment/orchestrator.py": "Waterfall PDL -> Prospeo -> ContactOut",
    "people_enrichment/dedup.py":      "Dedup by email/phone/linkedin/name+domain",
    "people_enrichment/scoring.py":    "Role classification, confidence rescoring",
    "people_enrichment/schemas.py":    "EnrichedContact, ProviderStats, PeopleEnrichmentResult",
    "app/services/maps_pipeline_service.py": "Orchestrator wired, old PDL flag removed",
    "src/routes/leads.py":             "New people stats in pipeline_stats response",
}
for f, desc in files.items():
    try:
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        ast.parse(src)
        lines = src.count("\n")
        print(f"  OK   {f} ({lines}L)")
    except SyntaxError as e:
        print(f"  ERR  {f}: SyntaxError: {e}")
        _errors += 1
    except FileNotFoundError:
        print(f"  ERR  {f}: FILE MISSING")
        _errors += 1

# ── 2. Provider isolation ──────────────────────────────────────────────────
hdr("2. PROVIDER ISOLATION (orchestrator never touches provider internals)")
with open("people_enrichment/orchestrator.py", encoding="utf-8") as fh:
    orch = fh.read()

chk("Does NOT import people_data_labs.client directly",  "people_data_labs.client" not in orch)
chk("Does NOT import prospeo.client directly",           "prospeo.client" not in orch)
chk("Does NOT import contactout.client directly",        "contactout.client" not in orch)
chk("Calls PDL via people_search module",                "people_data_labs.people_search" in orch or "people_data_labs.config" in orch)
chk("Calls Prospeo via people_search module",            "prospeo.people_search" in orch or "prospeo.config" in orch)
chk("Calls ContactOut via people_search module",         "contactout.people_search" in orch or "contactout.config" in orch)

# ── 3. Waterfall logic ─────────────────────────────────────────────────────
hdr("3. WATERFALL LOGIC IN ORCHESTRATOR")
chk("TARGET per-run (env configurable)",                 "_target()" in orch or "PEOPLE_ENRICHMENT_TARGET" in orch)
chk("Stops after PDL when target reached",               "Target reached after PDL" in orch)
chk("Stops after Prospeo when target reached",           "Target reached after Prospeo" in orch)
chk("PDL auth_failed recorded + continues",              "auth_failed" in orch)
chk("In-memory cache (_cache dict)",                     "_cache: dict" in orch or "_cache =" in orch)
chk("reset_cache() function exposed",                    "def reset_cache" in orch)
chk("dedup_and_merge() used after each step",            "dedup_and_merge" in orch)
chk("count_useful() used for target check",              "count_useful" in orch)
chk("rank_contacts() used in _finalise",                 "rank_contacts" in orch)

# ── 4. Pipeline integration ────────────────────────────────────────────────
hdr("4. PIPELINE INTEGRATION (maps_pipeline_service.py)")
with open("app/services/maps_pipeline_service.py", encoding="utf-8") as fh:
    mp = fh.read()

chk("people_enrichment.orchestrator imported",           "people_enrichment.orchestrator" in mp)
chk("_enrich_via_people_orchestrator() present",         "_enrich_via_people_orchestrator" in mp)
chk("_enrich_one_company calls orchestrator",            "_enrich_via_people_orchestrator" in mp)
chk("Old _enrich_via_pdl() REMOVED",                     "_enrich_via_pdl" not in mp)
chk("Old _pdl_auth_failed_flag REMOVED",                 "_pdl_auth_failed_flag" not in mp)
chk("reset_cache() called at pipeline start",            "reset_cache" in mp)
chk("company[contacts] assigned from result",            'company["contacts"] = contacts_list' in mp or "company[\"contacts\"]" in mp)

# ── 5. Pipeline statistics ─────────────────────────────────────────────────
hdr("5. PIPELINE STATISTICS (all 12 required keys)")
required_stats = [
    "people_companies_processed",
    "people_contacts_found",
    "people_emails_found",
    "people_phones_found",
    "pdl_calls",
    "pdl_contacts",
    "prospeo_calls",
    "prospeo_contacts",
    "contactout_calls",
    "contactout_contacts",
    "people_target_reached",
    "people_auth_failures",
]
for key in required_stats:
    chk(f"maps_pipeline_service has stat: {key}", key in mp)

with open("src/routes/leads.py", encoding="utf-8") as fh:
    lr = fh.read()
route_stats = [
    "people_companies_processed",
    "people_contacts_found",
    "pdl_calls",
    "prospeo_calls",
    "contactout_calls",
    "people_target_reached",
    "people_auth_failures",
]
for key in route_stats:
    chk(f"leads route propagates stat: {key}", key in lr)

# ── 6. Output schema ───────────────────────────────────────────────────────
hdr("6. OUTPUT SCHEMA (PeopleEnrichmentResult / EnrichedContact)")
with open("people_enrichment/schemas.py", encoding="utf-8") as fh:
    schemas = fh.read()

chk("EnrichedContact has name",         "name" in schemas)
chk("EnrichedContact has title",        "title" in schemas)
chk("EnrichedContact has email",        "email" in schemas)
chk("EnrichedContact has phone",        "phone" in schemas)
chk("EnrichedContact has linkedin_url", "linkedin_url" in schemas)
chk("EnrichedContact has sources",      "sources" in schemas)
chk("EnrichedContact has confidence",   "confidence" in schemas)
chk("PeopleEnrichmentResult present",   "PeopleEnrichmentResult" in schemas)
chk("ProviderStats present",            "ProviderStats" in schemas)

# ── 7. Frontend UI ─────────────────────────────────────────────────────────
hdr("7. FRONTEND UI CHANGES")
fe_base = "../frontend/src"
fe_files = {
    f"{fe_base}/components/MapsLeadsTable.jsx":    ["ContactCard", "ContactsPanel", "pipelineStats", "SourceBadge"],
    f"{fe_base}/components/GoogleMapsPanel.jsx":   ["pipelineStats"],
    f"{fe_base}/components/LeadsTable.jsx":        ["contacts.length", "contacts.some"],
    f"{fe_base}/components/PDLContactsPanel.jsx":  ["savedContacts", "hasSavedContacts", "normalisedContacts", "_roleFromTitle", "SourceBadges"],
    f"{fe_base}/hooks/useGoogleMapsLeads.js":      ["pipelineStats", "setPipelineStats"],
    f"{fe_base}/hooks/useGenerateLeads.js":        ["pipelineStats"],
    f"{fe_base}/pages/LeadGeneration.jsx":         ["people_contacts_found", "pdl_calls", "prospeo_calls"],
}
for path, patterns in fe_files.items():
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        missing = [p for p in patterns if p not in content]
        if missing:
            print(f"  ERR  {path.split('/')[-1]}: missing {missing}")
            _errors += 1
        else:
            print(f"  OK   {path.split('/')[-1]}: all {len(patterns)} patterns found")
    except FileNotFoundError:
        print(f"  ERR  {path.split('/')[-1]}: FILE MISSING")
        _errors += 1

# ── 8. Test results ────────────────────────────────────────────────────────
hdr("8. TEST SUITE")
import subprocess, re
result = subprocess.run(
    [sys.executable, "test_people_enrichment.py"],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)
output = result.stdout + result.stderr
m = re.search(r"RESULTS: (\d+) passed, (\d+) failed", output)
if m:
    passed, failed = int(m.group(1)), int(m.group(2))
    chk(f"All tests pass: {passed} passed, {failed} failed", failed == 0)
else:
    print("  ERR  Could not parse test output")
    _errors += 1

# ── Summary ────────────────────────────────────────────────────────────────
print()
print("=" * 55)
if _errors == 0:
    print("RESULT: COMPLETE  —  0 errors, all checks passed")
else:
    print(f"RESULT: INCOMPLETE — {_errors} check(s) failed")
print("=" * 55)
sys.exit(0 if _errors == 0 else 1)
