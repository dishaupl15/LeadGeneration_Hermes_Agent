"""
verify_gmaps.py
───────────────
Final verification checklist for the Google Maps module.
Run from backend/ with: python verify_gmaps.py
"""
import sys
import os
import inspect
import importlib

sys.path.insert(0, ".")
os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27017/crm")

PASS = "PASS"
FAIL = "FAIL"

def check(label, result, detail=""):
    status = PASS if result else FAIL
    d = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{d}")
    return result

print("=" * 60)
print("Google Maps Module — Final Verification Checklist")
print("=" * 60)

all_ok = True

# ── 1. Config ──────────────────────────────────────────────────────────────────
print("\n[1] API Configuration")
from google_maps.config import (
    GOOGLE_MAPS_API_KEY, PLACES_TEXT_SEARCH_URL, FIELD_MASK,
    MAX_QUERIES_PER_REQUEST, MAX_PAGES_PER_QUERY, MAX_CONCURRENCY,
    SEEN_COLLECTION_NAME,
)
comma = ","
all_ok &= check("API key loaded from .env", bool(GOOGLE_MAPS_API_KEY))
all_ok &= check("Correct endpoint", "places.googleapis.com" in PLACES_TEXT_SEARCH_URL)
all_ok &= check("Field mask has required fields", all(
    f in FIELD_MASK for f in ["places.id", "places.displayName", "places.formattedAddress",
                               "places.nationalPhoneNumber", "places.websiteUri",
                               "places.location", "nextPageToken"]
), f"{len(FIELD_MASK.split(comma))} fields")
all_ok &= check("No expensive fields (reviews/photos/etc)", all(
    f not in FIELD_MASK for f in ["reviews", "photos", "openingHours", "priceLevel"]
))
all_ok &= check("API key NOT in endpoint URL", GOOGLE_MAPS_API_KEY not in PLACES_TEXT_SEARCH_URL)

# ── 2. No pipeline imports ─────────────────────────────────────────────────────
print("\n[2] Isolation — No Pipeline Imports")
gm_mods = [
    "google_maps.config", "google_maps.geography", "google_maps.places_client",
    "google_maps.schemas", "google_maps.seen_store", "google_maps.discovery",
    "google_maps.routes",
]
forbidden = ["companyenrich", "serper_api", "firecrawl", "hermes_service",
             "hunter_service", "apollo_service", "pdl_service"]
for modname in gm_mods:
    m = importlib.import_module(modname)
    src = inspect.getsource(m)
    # Check actual import lines only, not docstrings/comments
    import_lines = [line for line in src.splitlines()
                    if line.strip().startswith(("import ", "from ")) and not line.strip().startswith("#")]
    import_text = "\n".join(import_lines).lower()
    found = [f for f in forbidden if f in import_text]
    all_ok &= check(f"{modname} clean", not found,
                    f"found in imports: {found}" if found else "")

# ── 3. Geography ───────────────────────────────────────────────────────────────
print("\n[3] Geography Subdivision")
from google_maps.geography import get_all_states, get_districts, resolve_areas
states = get_all_states()
all_ok &= check("States loaded", len(states) >= 20, f"{len(states)} states")
all_ok &= check("Maharashtra in states", "Maharashtra" in states)
mh_d = get_districts("Maharashtra")
all_ok &= check("Maharashtra has districts", len(mh_d) >= 5, f"{mh_d}")
pune_areas = resolve_areas("Maharashtra", "Pune")
all_ok &= check("Pune resolves to localities", len(pune_areas) >= 10, f"{len(pune_areas)} localities")
state_areas = resolve_areas("Maharashtra", "")
all_ok &= check("State resolves to districts", len(state_areas) >= 5, f"{len(state_areas)} districts")
no_state_areas = resolve_areas("", "")
all_ok &= check("Empty input returns empty list", no_state_areas == [], str(no_state_areas))

# ── 4. Query building ──────────────────────────────────────────────────────────
print("\n[4] Query Building")
from google_maps.discovery import _build_queries, _get_phrases
q_construction = _build_queries("construction", "Baner", "Maharashtra")
all_ok &= check("Construction: 6 phrases", len(q_construction) == 6, str(q_construction))
all_ok &= check("No duplicate queries", len(q_construction) == len(set(q_construction)))
all_ok &= check("Queries contain location", all("Baner" in q and "India" in q for q in q_construction))
q_generic = _build_queries("widgets", "Mumbai", "Maharashtra")
all_ok &= check("Generic category fallback", len(q_generic) >= 2, f"{q_generic}")
phrases = _get_phrases("construction")
expected = ["construction company", "construction contractor", "building contractor",
            "civil contractor", "infrastructure company", "real estate developer"]
all_ok &= check("Construction phrases exact", phrases == expected, f"{phrases}")

# ── 5. Deduplication ───────────────────────────────────────────────────────────
print("\n[5] Deduplication")
from google_maps.discovery import _normalised_name, _website_domain, _digits_only
all_ok &= check("Name normalisation: Pvt Ltd == Private Limited",
                _normalised_name("Acme Pvt Ltd") == _normalised_name("Acme Private Limited"))
all_ok &= check("Domain extraction strips www",
                _website_domain("https://www.test.co.in") == "test.co.in")
all_ok &= check("Domain extraction handles no scheme",
                _website_domain("www.acme.com") == "acme.com")
all_ok &= check("Phone digits only strips non-digits",
                _digits_only("+91 98765-43210") == "919876543210")

# ── 6. Seen store ──────────────────────────────────────────────────────────────
print("\n[6] Cross-Request Seen Store")
import asyncio
from google_maps.seen_store import (
    _get_in_memory_seen, is_seen, mark_seen, clear_session, count_seen
)

async def test_seen():
    # Clear first
    await clear_session("test_cat", "test_state", "test_dist")
    # Not seen initially
    r1 = await is_seen("PLACE001", "test_cat", "test_state", "test_dist")
    # Mark seen
    await mark_seen("PLACE001", "Test Co", "test_cat", "test_state", "test_dist")
    # Now seen
    r2 = await is_seen("PLACE001", "test_cat", "test_state", "test_dist")
    # Count
    c = await count_seen("test_cat", "test_state", "test_dist")
    # Clear
    await clear_session("test_cat", "test_state", "test_dist")
    r3 = await is_seen("PLACE001", "test_cat", "test_state", "test_dist")
    return (not r1), r2, (c == 1), (not r3)

results = asyncio.run(test_seen())
all_ok &= check("Not seen before mark_seen", results[0])
all_ok &= check("Seen after mark_seen", results[1])
all_ok &= check("count_seen returns 1", results[2])
all_ok &= check("Not seen after clear_session", results[3])
# Verify seen_store does NOT touch the leads collection
from google_maps.config import SEEN_COLLECTION_NAME
all_ok &= check("Seen collection is isolated (not 'leads')", SEEN_COLLECTION_NAME != "leads",
                f"collection='{SEEN_COLLECTION_NAME}'")

# ── 7. MapBusiness schema ──────────────────────────────────────────────────────
print("\n[7] Schema & Fields")
from google_maps.schemas import MapBusiness, MapLeadsRequest, MapLeadsResponse, MapLeadsStats
b = MapBusiness(place_id="ChIJtest", name="Test Company")
all_ok &= check("source defaults to 'google_maps'", b.source == "google_maps")
all_ok &= check("MapBusiness has place_id", bool(b.place_id))
all_ok &= check("MapBusiness phone defaults to None", b.phone is None)
all_ok &= check("MapBusiness website defaults to None", b.website is None)
req = MapLeadsRequest(category="construction", state="Maharashtra", target=10)
all_ok &= check("MapLeadsRequest exclude_seen defaults True", req.exclude_seen is True)
all_ok &= check("MapLeadsRequest district optional", req.district is None)

# ── 8. Cost protection ─────────────────────────────────────────────────────────
print("\n[8] Cost Protection")
all_ok &= check(f"MAX_QUERIES_PER_REQUEST = {MAX_QUERIES_PER_REQUEST}", MAX_QUERIES_PER_REQUEST > 0)
all_ok &= check(f"MAX_PAGES_PER_QUERY = {MAX_PAGES_PER_QUERY}", 1 <= MAX_PAGES_PER_QUERY <= 5)
all_ok &= check(f"MAX_CONCURRENCY = {MAX_CONCURRENCY}", 1 <= MAX_CONCURRENCY <= 10)
# Verify early-stop logic is in discovery.py
disc_src = open("google_maps/discovery.py").read()
all_ok &= check("Early stop on target reached", "if len(results) >= target:" in disc_src)
all_ok &= check("Query cap check", "MAX_QUERIES_PER_REQUEST" in disc_src)

# ── 9. Key never in logs ───────────────────────────────────────────────────────
print("\n[9] API Key Safety")
places_src = open("google_maps/places_client.py").read()
all_ok &= check("Key passed in header (X-Goog-Api-Key)", "X-Goog-Api-Key" in places_src)
all_ok &= check("Key NOT in URL params", "?key=" not in places_src)
# Key should never log its value — check that the actual runtime value
# (the key string itself) is never concatenated into a log message.
# Logging the variable NAME as a hint (e.g. "check GOOGLE_MAPS_API_KEY") is fine.
# The actual secret value is only placed in the X-Goog-Api-Key header.
log_lines = [l for l in places_src.splitlines() if "_log(" in l]
# Dangerous pattern: f"...{GOOGLE_MAPS_API_KEY}..." or + GOOGLE_MAPS_API_KEY
import re as _re
key_value_in_log = any(
    _re.search(r'_log\s*\(.*\{GOOGLE_MAPS_API_KEY\}', l)
    for l in log_lines
)
all_ok &= check("API key value never interpolated into logs", not key_value_in_log)

# ── 10. Router endpoints ───────────────────────────────────────────────────────
print("\n[10] Router Endpoints")
from google_maps.routes import router
endpoints = {r.path: sorted(r.methods) for r in router.routes}
all_ok &= check("GET /maps-leads/health", "/maps-leads/health" in endpoints)
all_ok &= check("GET /maps-leads/states", "/maps-leads/states" in endpoints)
all_ok &= check("GET /maps-leads/districts/{state}", "/maps-leads/districts/{state}" in endpoints)
all_ok &= check("POST /maps-leads/generate", "/maps-leads/generate" in endpoints)
all_ok &= check("DELETE /maps-leads/seen", "/maps-leads/seen" in endpoints)

# ── 11. Existing pipeline untouched ───────────────────────────────────────────
print("\n[11] Existing Pipeline Untouched")
pipeline_files = [
    "app/services/discovery_service.py",
    "app/services/enrichment_service.py",
    "app/services/companyenrich_service.py",
    "src/routes/leads.py",
]
for f in pipeline_files:
    if os.path.exists(f):
        content = open(f, encoding="utf-8").read()
        gm_import = "from google_maps" in content or "import google_maps" in content
        all_ok &= check(f"{f}", not gm_import,
                        "CLEAN" if not gm_import else "HAS google_maps IMPORT!")

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
if all_ok:
    print("RESULT: ALL CHECKS PASSED")
else:
    print("RESULT: SOME CHECKS FAILED — see above")
print("=" * 60)

sys.exit(0 if all_ok else 1)
