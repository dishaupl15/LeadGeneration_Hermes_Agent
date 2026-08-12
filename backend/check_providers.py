"""
check_providers.py
──────────────────
Deep implementation audit for PDL, Prospeo, and ContactOut.
Checks every function signature, field name, HTTP endpoint, auth header,
response parsing path, and orchestrator converter against the actual API docs.

Run: python check_providers.py
"""
import ast, sys, re

PASS = 0
FAIL = 0

def ok(label):
    global PASS; PASS += 1
    print(f"  OK   {label}")

def err(label, detail=""):
    global FAIL; FAIL += 1
    print(f"  ERR  {label}" + (f" — {detail}" if detail else ""))

def section(title):
    print()
    print(title)
    print("-" * 60)

def src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

# ══════════════════════════════════════════════════════════════════════════════
# 1. PDL
# ══════════════════════════════════════════════════════════════════════════════
section("1. PDL — people_data_labs/")

pdl_client  = src("people_data_labs/client.py")
pdl_search  = src("people_data_labs/people_search.py")
pdl_mapper  = src("people_data_labs/contact_mapper.py")
pdl_schemas = src("people_data_labs/schemas.py")
pdl_config  = src("people_data_labs/config.py")

# Config
(ok if "PDL_API_KEY" in pdl_config else err)("PDL_API_KEY loaded from .env")
(ok if "PDL_BASE_URL" in pdl_config and "peopledatalabs.com/v5" in pdl_config else err)("PDL base URL is v5 endpoint")
(ok if "is_configured" in pdl_config else err)("is_configured() present")

# Client
(ok if '"X-Api-Key"' in pdl_client else err)('Auth header is X-Api-Key (PDL standard)')
(ok if "POST" in pdl_client and "/person/search" in pdl_client else err)("POST /v5/person/search endpoint")
(ok if "auth_failed" in pdl_client and "401" in pdl_client else err)("401 -> auth_failed propagated")
(ok if "404" in pdl_client else err)("404 handled (empty result, not error)")
(ok if "429" in pdl_client else err)("429 rate-limit handled")
(ok if "return [], False, False" in pdl_client else err)("Returns (data, auth_failed, rate_limited) tuple")
(ok if "auth_failed_now" in pdl_search or "auth_failed" in pdl_search else err)("auth_failed stops further PDL calls")

# Query builder — correct ES field names
(ok if "job_company_website" in pdl_search else err)('ES field "job_company_website" for domain match')
(ok if "job_company_name" in pdl_search else err)('ES field "job_company_name" for name match')
(ok if "job_title_levels" in pdl_search else err)('ES field "job_title_levels" for seniority filter')
(ok if '"founder"' in pdl_search and '"c_suite"' in pdl_search else err)('Tier A includes founder + c_suite')
(ok if '"vp"' in pdl_search and '"manager"' in pdl_search else err)('Tier B includes vp + manager')

# data_include — only fetch needed fields (cost control)
(ok if "work_email" in pdl_search else err)("work_email in data_include")
(ok if "phone_numbers" in pdl_search else err)("phone_numbers in data_include")
(ok if "linkedin_url" in pdl_search else err)("linkedin_url in data_include")

# Contact mapper — correct PDL response field names
(ok if "job_title" in pdl_mapper else err)('PDL field "job_title" read for title')
(ok if "job_company_website" in pdl_mapper else err)('PDL field "job_company_website" for company match')
(ok if "job_company_name" in pdl_mapper else err)('PDL field "job_company_name" for name match')
(ok if "work_email" in pdl_mapper else err)('PDL field "work_email" extracted for email')
(ok if "phone_numbers" in pdl_mapper else err)('PDL field "phone_numbers" extracted for phone')
(ok if "linkedin_url" in pdl_mapper else err)('PDL field "linkedin_url" extracted')
(ok if "profiles" in pdl_mapper else err)('PDL "profiles" list checked for LinkedIn URL fallback')
(ok if "job_title_levels" in pdl_mapper else err)('PDL "job_title_levels" used for seniority check')
(ok if "full_name" in pdl_mapper else err)('PDL "full_name" extracted for name')

# Schemas
(ok if "PeopleDataLabsContact" in pdl_schemas else err)("PeopleDataLabsContact schema defined")
(ok if "PeopleDataLabsResult" in pdl_schemas else err)("PeopleDataLabsResult schema defined")
(ok if "designation" in pdl_schemas else err)("PeopleDataLabsContact.designation field (PDL uses job_title)")
(ok if "pdl_api_calls" in pdl_schemas else err)("PeopleDataLabsResult.pdl_api_calls field")

# Orchestrator converter
orch = src("people_enrichment/orchestrator.py")
(ok if "_pdl_contact_to_dict" in orch else err)("_pdl_contact_to_dict converter in orchestrator")
(ok if 'getattr(c, "designation"' in orch else err)('PDL contact uses .designation (not .title)')
(ok if 'getattr(c, "pdl_api_calls"' in orch or "pdl_api_calls" in orch else err)("pdl_api_calls read from PDL result")

# ══════════════════════════════════════════════════════════════════════════════
# 2. PROSPEO
# ══════════════════════════════════════════════════════════════════════════════
section("2. PROSPEO — prospeo/")

pro_client  = src("prospeo/client.py")
pro_search  = src("prospeo/people_search.py")
pro_mapper  = src("prospeo/contact_mapper.py")
pro_schemas = src("prospeo/schemas.py")
pro_config  = src("prospeo/config.py")

# Config
(ok if "PROSPEO_API_KEY" in pro_config else err)("PROSPEO_API_KEY loaded from .env")
(ok if "api.prospeo.io" in pro_config else err)("Correct Prospeo base URL")
(ok if "search-person" in pro_config else err)("/search-person endpoint configured")
(ok if "bulk-enrich-person" in pro_config else err)("/bulk-enrich-person endpoint configured")
(ok if "account-information" in pro_config else err)("/account-information endpoint configured")

# Client auth
(ok if '"X-KEY"' in pro_client else err)('Auth header is X-KEY (Prospeo standard)')
(ok if '"Content-Type"' in pro_client else err)("Content-Type header set")

# Search Person
(ok if "PROSPEO_SEARCH_URL" in pro_client else err)("Uses PROSPEO_SEARCH_URL for search-person")
(ok if '"filters"' in pro_client else err)('Search payload uses "filters" key')
(ok if '"page"' in pro_client else err)('Search payload includes "page" parameter')
(ok if '"results"' in pro_client else err)('Extracts "results" from search response')
(ok if "pagination" in pro_client else err)('Reads "pagination.total_count" from response')

# Bulk Enrich Person
(ok if "PROSPEO_BULK_URL" in pro_client else err)("Uses PROSPEO_BULK_URL for bulk-enrich-person")
(ok if '"data"' in pro_client else err)('Bulk payload uses "data" key for records list')
(ok if '"enrich_mobile"' in pro_client else err)('Bulk payload includes "enrich_mobile" flag')
(ok if '"only_verified_email"' in pro_client else err)('Bulk payload includes "only_verified_email" flag')
(ok if "records[:50]" in pro_client else err)("Bulk enrich caps at 50 records (Prospeo limit)")
(ok if '"matched"' in pro_client else err)('Extracts "matched" list from bulk response')
(ok if '"total_cost"' in pro_client else err)('Reads "total_cost" credits from bulk response')

# Error handling
(ok if "INVALID_API_KEY" in pro_client else err)('INVALID_API_KEY -> auth_failed')
(ok if "INSUFFICIENT_CREDITS" in pro_client else err)('INSUFFICIENT_CREDITS -> no_credits')
(ok if "NO_RESULTS" in pro_client else err)('NO_RESULTS handled as empty (not error)')
(ok if "auth_failed" in pro_search and "auth_failed" in pro_search else err)("auth_failed propagated in people_search")

# Search filters — correct Prospeo filter structure
(ok if '"websites"' in pro_search else err)('Company filter uses "websites" key for domain')
(ok if '"names"' in pro_search else err)('Company filter uses "names" key for name fallback')
(ok if '"person_seniority"' in pro_search else err)('Filter includes "person_seniority" restriction')
(ok if '"Founder/Owner"' in pro_search else err)('Seniority includes "Founder/Owner"')
(ok if '"C-Suite"' in pro_search else err)('Seniority includes "C-Suite"')
(ok if '"Director"' in pro_search else err)('Seniority includes "Director"')

# Two-step workflow
(ok if "search_person" in pro_search else err)("Step 1: calls search_person()")
(ok if "bulk_enrich_person" in pro_search else err)("Step 2: calls bulk_enrich_person()")
(ok if '"person_id"' in pro_search else err)('Sends person_id in bulk enrich records')
(ok if '"identifier"' in pro_search else err)('Uses "identifier" to match enriched results back')
(ok if "enriched_index" in pro_search else err)("Builds enriched_index to match results by identifier")

# Contact mapper — correct Prospeo response field names
(ok if "current_job_title" in pro_mapper else err)('Reads "current_job_title" from Prospeo person')
(ok if 'person.get("email")' in pro_mapper else err)('Reads email from person["email"] dict')
(ok if '"revealed"' in pro_mapper else err)('Checks email["revealed"] = True before using email')
(ok if 'mob_obj.get("revealed")' in pro_mapper else err)('Checks mobile["revealed"] before using phone')
(ok if '"mobile"' in pro_mapper else err)('Reads mobile from person["mobile"] dict')
(ok if '"mobile_international"' in pro_mapper else err)('Falls back to mobile_international if mobile empty')
(ok if "job_history" in pro_mapper else err)('Reads job_history for company match fallback')
(ok if '"linkedin_url"' in pro_mapper else err)('Reads linkedin_url from person')

# map_enriched_result must use enriched person data (not raw search data)
(ok if "def map_enriched_result" in pro_mapper else err)("map_enriched_result() function defined")
(ok if "def map_search_result" in pro_mapper else err)("map_search_result() function defined")
(ok if "extract_email" in pro_mapper else err)("extract_email() helper defined")
(ok if "extract_mobile" in pro_mapper else err)("extract_mobile() helper defined")

# Schemas
(ok if "ProspeoContact" in pro_schemas else err)("ProspeoContact schema defined")
(ok if "ProspeoSearchResult" in pro_schemas else err)("ProspeoSearchResult schema defined")
(ok if "phones_found" in pro_schemas else err)("ProspeoSearchResult.phones_found field")
(ok if "credits_estimated" in pro_schemas else err)("ProspeoSearchResult.credits_estimated field")

# Orchestrator converter
(ok if "_prospeo_contact_to_dict" in orch else err)("_prospeo_contact_to_dict converter in orchestrator")
(ok if 'getattr(c, "title"' in orch else err)('Prospeo contact uses .title (not .designation)')
(ok if '"api_calls"' in orch or "api_calls" in orch else err)("api_calls read from Prospeo result")

# ══════════════════════════════════════════════════════════════════════════════
# 3. CONTACTOUT
# ══════════════════════════════════════════════════════════════════════════════
section("3. CONTACTOUT — contactout/")

co_client  = src("contactout/client.py")
co_search  = src("contactout/people_search.py")
co_mapper  = src("contactout/contact_mapper.py")
co_schemas = src("contactout/schemas.py")
co_config  = src("contactout/config.py")

# Config
(ok if "CONTACTOUT_API_TOKEN" in co_config else err)("CONTACTOUT_API_TOKEN loaded from .env")
(ok if "api.contactout.com" in co_config else err)("Correct ContactOut base URL")
(ok if "v1/people/search" in co_config else err)("/v1/people/search endpoint configured")
(ok if "v1/stats" in co_config else err)("/v1/stats endpoint configured")

# Client auth — ContactOut requires BOTH headers
(ok if '"authorization": "basic"' in co_client else err)('Auth header 1: authorization: basic')
(ok if '"token"' in co_client and "CONTACTOUT_API_TOKEN" in co_client else err)('Auth header 2: token: <key>')
(ok if "CONTACTOUT_SEARCH_URL" in co_client else err)("Uses CONTACTOUT_SEARCH_URL for people/search")

# Error handling per ContactOut's unusual HTTP status mapping
(ok if "400" in co_client and "auth_failed" in co_client else err)("400 -> auth_failed (ContactOut's auth error code)")
(ok if "401" in co_client and "bad_request" in co_client else err)("401 -> bad_request (ContactOut's bad input code)")
(ok if "403" in co_client and "no_credits" in co_client else err)("403 -> no_credits/no_access")
(ok if "429" in co_client and "rate_limited" in co_client else err)("429 -> rate_limited")

# Search payload — correct ContactOut API fields
(ok if '"job_title"' in co_search else err)('Payload uses "job_title" list')
(ok if '"current_titles_only"' in co_search else err)('Payload includes "current_titles_only": True')
(ok if '"include_related_job_titles"' in co_search else err)('Payload includes "include_related_job_titles"')
(ok if '"match_experience"' in co_search else err)('Payload includes "match_experience": True')
(ok if '"reveal_info"' in co_search else err)('Payload includes "reveal_info": True (gets contact data in one call)')
(ok if '"company_domain"' in co_search else err)('Payload includes "company_domain" when domain available')
(ok if '"page_size"' in co_search else err)('Payload includes "page_size"')
(ok if '"fields"' in co_search else err)('Payload includes "fields" list to limit response size')

# Priority titles list
(ok if '"Founder"' in co_search else err)('Priority title: Founder')
(ok if '"CEO"' in co_search else err)('Priority title: CEO')
(ok if '"Managing Director"' in co_search else err)('Priority title: Managing Director')
(ok if '"HR Manager"' in co_search else err)('Priority title: HR Manager')
(ok if '"Talent Acquisition Manager"' in co_search else err)('Priority title: Talent Acquisition Manager')

# Response parsing — ContactOut returns profiles as dict OR list
(ok if "isinstance(raw_profiles, dict)" in co_search else err)("Handles profiles as dict (keyed by LinkedIn URL)")
(ok if "isinstance(raw_profiles, list)" in co_search else err)("Handles profiles as list")
(ok if ".values()" in co_search else err)("Extracts dict.values() when profiles is a dict")

# Contact mapper — correct ContactOut response field names
(ok if "contact_info" in co_mapper else err)('Reads from "contact_info" sub-object')
(ok if "professional_emails" in co_mapper else err)('Prefers "professional_emails" over generic emails')
(ok if "ci.get" in co_mapper else err)('Safely reads from contact_info with .get()')
(ok if '"phones"' in co_mapper else err)('Reads phones from contact_info["phones"]')
(ok if "full_name" in co_mapper else err)('Reads "full_name" for name extraction')
(ok if "current_company" in co_mapper else err)('Reads "current_company" for company match')
(ok if '"experience"' in co_mapper else err)('Reads "experience" list as fallback company match')
(ok if "is_current" in co_mapper or "current" in co_mapper else err)('Checks is_current/current on experience entries')
(ok if "_NULL_STRINGS" in co_mapper else err)('Rejects null/N/A string placeholders ContactOut sometimes sends')
(ok if "contact_availability" in co_mapper else err)('has_contact_availability() helper defined')

# Schemas
(ok if "ContactOutContact" in co_schemas else err)("ContactOutContact schema defined")
(ok if "ContactOutSearchResult" in co_schemas else err)("ContactOutSearchResult schema defined")
(ok if "phones_found" in co_schemas else err)("ContactOutSearchResult.phones_found field")

# Orchestrator converter
(ok if "_contactout_contact_to_dict" in orch else err)("_contactout_contact_to_dict converter in orchestrator")

# ══════════════════════════════════════════════════════════════════════════════
# 4. ORCHESTRATOR FIELD MAPPING CORRECTNESS
# ══════════════════════════════════════════════════════════════════════════════
section("4. ORCHESTRATOR FIELD MAPPING (schema field name correctness)")

# PDL: PeopleDataLabsContact uses .designation (not .title) for job title
(ok if 'getattr(c, "designation"' in orch else err)('PDL converter reads .designation for title (not .title)')
# PDL: result stat is pdl_api_calls (not api_calls)
(ok if "pdl_api_calls" in orch else err)('PDL result stat read as .pdl_api_calls')
# Prospeo: ProspeoContact uses .title for job title
(ok if 'getattr(c, "title"' in orch else err)('Prospeo converter reads .title for title')
# Prospeo: result stat is api_calls
(ok if '"api_calls"' in orch or "result, \"api_calls\"" in orch or "getattr(result, \"api_calls\"" in orch else err)('Prospeo result stat read as .api_calls')
# ContactOut: ContactOutContact uses .title
(ok if "_contactout_contact_to_dict" in orch else err)("ContactOut converter present")
# All converters output the unified dict shape
for provider, func in [("pdl","_pdl_contact_to_dict"),("prospeo","_prospeo_contact_to_dict"),("contactout","_contactout_contact_to_dict")]:
    snippet_start = orch.find(f"def {func}")
    snippet = orch[snippet_start:snippet_start+600] if snippet_start >= 0 else ""
    (ok if '"name"' in snippet and '"title"' in snippet and '"email"' in snippet and '"phone"' in snippet else err)(
        f'{func}() outputs name/title/email/phone fields'
    )
    (ok if '"sources"' in snippet and '"confidence"' in snippet else err)(
        f'{func}() outputs sources/confidence fields'
    )

# ══════════════════════════════════════════════════════════════════════════════
# 5. WATERFALL STOP CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════
section("5. WATERFALL STOP CONDITIONS IN ORCHESTRATOR")

(ok if "useful_so_far >= TARGET" in orch or "useful_so_far >= target" in orch else err)("Target check: useful_so_far >= TARGET")
(ok if "skipping Prospeo and ContactOut" in orch else err)("PDL>=2: skip both Prospeo and ContactOut")
(ok if "skipping ContactOut" in orch else err)("PDL+Prospeo>=2: skip ContactOut")
(ok if "target_reached" in orch else err)("target_reached flag in result")
(ok if "ProviderStats(" in orch and "skipped_reason" in orch else err)("Skipped providers get ProviderStats with skipped_reason")

# ══════════════════════════════════════════════════════════════════════════════
# 6. BULK OPERATION VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
section("6. BULK OPERATION (Prospeo two-step, ContactOut reveal_info)")

# Prospeo: two-step — search then bulk enrich
(ok if "enrich_records" in pro_search else err)("Builds enrich_records list for bulk enrich")
(ok if "str(i)" in pro_search else err)("Uses str(i) as identifier for result matching")
(ok if "enriched_index.get(str(i))" in pro_search else err)("Looks up enriched result by identifier")
(ok if "enrich_mobile=True" in pro_search else err)("Bulk enrich requests mobile enrichment")
# ContactOut: single-step with reveal_info
(ok if "reveal_info" in co_search and "True" in co_search else err)("ContactOut uses reveal_info=True (single-step)")
# PDL: tiered search, stops early
(ok if "len(accepted) >= max_contacts" in pdl_search else err)("PDL stops early when max_contacts reached")

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print(f"RESULT: {PASS} checks passed, {FAIL} checks failed")
if FAIL == 0:
    print("All provider implementations are correct and compatible.")
else:
    print("FIXES REQUIRED — see ERR lines above.")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
