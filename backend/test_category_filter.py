"""
test_category_filter.py
────────────────────────
Offline unit tests for strict category matching.

Run from backend/:
    python test_category_filter.py

Tests cover:
  1. _detect_industry()    — detects the right industry from text
  2. _has_industry_relevance() — keyword matching per category
  3. _CE_CATEGORY_DISQUALIFIERS — confirm hotel/RE/detective/news are blocked
     for retail and agriculture queries
  4. validate_candidate()  — end-to-end hard-reject of wrong-category companies
  5. enrichment cache key  — different categories produce different cache keys
"""

import sys, os

# ── Minimal env so imports don't blow up ─────────────────────────────────────
os.environ.setdefault("SERPER_API_KEY", "dummy")
os.environ.setdefault("FIRECRAWL_API_KEY", "dummy")
os.environ.setdefault("COMPANYENRICH_API_KEY", "dummy")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")

sys.path.insert(0, os.path.dirname(__file__))

# ── Imports ───────────────────────────────────────────────────────────────────
from app.services.discovery_service import (
    _detect_industry,
    _has_industry_relevance,
    _normalise_industry_key,
    _CE_CATEGORY_DISQUALIFIERS,
    validate_candidate,
)
from app.services.enrichment_service import _cache_key

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(label, got, expected):
    ok = (got == expected)
    status = PASS if ok else FAIL
    results.append((status, label, f"got={got!r} expected={expected!r}"))
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         got={got!r}  expected={expected!r}")


# ═════════════════════════════════════════════════════════════════════════════
# 1. _detect_industry()
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 1. _detect_industry() ===")

check("hotel text -> hospitality",
      _detect_industry("hotel resort accommodation hospitality tourism travel agency lodge inn"),
      "hospitality")

check("agri text -> agriculture",
      _detect_industry("agriculture farming agribusiness seeds fertilizer crop irrigation dairy"),
      "agriculture")

check("retail text -> retail",
      _detect_industry("retail store fmcg consumer goods supermarket hypermarket merchandise"),
      "retail")

check("real-estate text -> real estate",
      _detect_industry("real estate property developer builder residential apartments flat"),
      "real estate")

check("empty text -> unknown",
      _detect_industry(""),
      "unknown")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Disqualifier presence
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 2. _CE_CATEGORY_DISQUALIFIERS entries ===")

retail_dq = _CE_CATEGORY_DISQUALIFIERS.get("retail", [])
agri_dq   = _CE_CATEGORY_DISQUALIFIERS.get("agriculture", [])

for term in ["hotel", "real estate", "tourism", "detective"]:
    check(f"retail disqualifies '{term}'", term in retail_dq, True)

for term in ["hotel", "real estate", "tourism", "detective", "news"]:
    check(f"agriculture disqualifies '{term}'", term in agri_dq, True)


# ═════════════════════════════════════════════════════════════════════════════
# 3. _has_industry_relevance()
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 3. _has_industry_relevance() ===")

RETAIL_TEXT = "DMart retail chain consumer goods supermarket fmcg grocery merchandise"
AGRI_TEXT   = "Nuziveedu Seeds agriculture seed company crop fertilizer farming horticulture"
HOTEL_TEXT  = "Marriott Hotel resort accommodation hospitality tourism lodge inn five star"
RE_TEXT     = "Kolte Patil Developers real estate property developer residential apartments Pune"
DET_TEXT    = "detective agency private investigator investigation services Pune"
NEWS_TEXT   = "Sakal Media news newspaper media company publishing broadcast"

check("retail text | retail     -> True",  _has_industry_relevance(RETAIL_TEXT, "retail"), True)
check("retail text | agriculture-> False", _has_industry_relevance(RETAIL_TEXT, "agriculture"), False)

check("agri text  | agriculture -> True",  _has_industry_relevance(AGRI_TEXT,  "agriculture"), True)
check("agri text  | retail      -> False", _has_industry_relevance(AGRI_TEXT,  "retail"), False)

check("hotel text | retail      -> False", _has_industry_relevance(HOTEL_TEXT, "retail"), False)
check("hotel text | agriculture -> False", _has_industry_relevance(HOTEL_TEXT, "agriculture"), False)
check("hotel text | hospitality -> True",  _has_industry_relevance(HOTEL_TEXT, "hospitality"), True)

check("RE text    | retail      -> False", _has_industry_relevance(RE_TEXT,    "retail"), False)
check("RE text    | agriculture -> False", _has_industry_relevance(RE_TEXT,    "agriculture"), False)

check("detective  | agriculture -> False", _has_industry_relevance(DET_TEXT,   "agriculture"), False)
check("detective  | retail      -> False", _has_industry_relevance(DET_TEXT,   "retail"), False)

check("news/media | agriculture -> False", _has_industry_relevance(NEWS_TEXT,  "agriculture"), False)
check("news/media | retail      -> False", _has_industry_relevance(NEWS_TEXT,  "retail"), False)


# ═════════════════════════════════════════════════════════════════════════════
# 4. validate_candidate() — hard-reject wrong-category companies
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 4. validate_candidate() ===")

def _make_company(name, industry, description, city="Pune", ce=True):
    """Build a minimal company dict for validate_candidate testing."""
    return {
        "company_name":     name,
        "domain":           name.lower().replace(" ", "") + ".com",
        "website":          "https://" + name.lower().replace(" ", "") + ".com",
        "_merged_markdown": f"{name} {industry} {description}",
        "description":      description,
        "industry":         industry,
        "city":             city,
        "state":            "Maharashtra",
        "address":          f"123 Main St, {city}, Maharashtra",
        "_ce_enriched":     ce,
    }


# Retail query
RETAIL_QUERY = "Retail companies in Pune"

c1 = _make_company("Big Bazaar", "retail", "retail chain fmcg consumer goods supermarket grocery merchandise")
ok1, reason1 = validate_candidate(c1, RETAIL_QUERY)
check("Retail company ACCEPTED for retail query", ok1, True)

c2 = _make_company("Hotel Marriott Pune", "hotel hospitality", "hotel resort accommodation hospitality five star luxury")
ok2, reason2 = validate_candidate(c2, RETAIL_QUERY)
check("Hotel REJECTED for retail query", ok2, False)
if not ok2:
    print(f"         Rejection reason: {reason2}")

c3 = _make_company("Kolte Patil Developers", "real estate", "real estate developer residential apartments Pune builder")
ok3, reason3 = validate_candidate(c3, RETAIL_QUERY)
check("Real estate REJECTED for retail query", ok3, False)
if not ok3:
    print(f"         Rejection reason: {reason3}")

c4 = _make_company("Pune Detective Agency", "detective investigation", "private investigator detective agency investigation services")
ok4, reason4 = validate_candidate(c4, RETAIL_QUERY)
check("Detective agency REJECTED for retail query", ok4, False)
if not ok4:
    print(f"         Rejection reason: {reason4}")

c5 = _make_company("Sakal Times", "news media", "newspaper media company news publishing broadcast")
ok5, reason5 = validate_candidate(c5, RETAIL_QUERY)
check("News company REJECTED for retail query", ok5, False)
if not ok5:
    print(f"         Rejection reason: {reason5}")


# Agriculture query
AGRI_QUERY = "Agriculture companies in Pune"

c6 = _make_company("Nuziveedu Seeds", "agriculture", "agriculture seeds crop horticulture farming agribusiness fertilizer")
ok6, reason6 = validate_candidate(c6, AGRI_QUERY)
check("Agriculture company ACCEPTED for agri query", ok6, True)

c7 = _make_company("Hotel Sunderban", "hotel hospitality", "hotel resort accommodation tourism five star")
ok7, reason7 = validate_candidate(c7, AGRI_QUERY)
check("Hotel REJECTED for agriculture query", ok7, False)
if not ok7:
    print(f"         Rejection reason: {reason7}")

c8 = _make_company("Pune Real Estate Corp", "real estate", "real estate property developer builder residential")
ok8, reason8 = validate_candidate(c8, AGRI_QUERY)
check("Real estate REJECTED for agriculture query", ok8, False)
if not ok8:
    print(f"         Rejection reason: {reason8}")

c9 = _make_company("Maharashtra Tourism", "tourism hospitality", "tourism travel agency tour operator accommodation lodge")
ok9, reason9 = validate_candidate(c9, AGRI_QUERY)
check("Tourism REJECTED for agriculture query", ok9, False)
if not ok9:
    print(f"         Rejection reason: {reason9}")

c10 = _make_company("City Detective Bureau", "detective investigation", "detective agency private investigator investigation")
ok10, reason10 = validate_candidate(c10, AGRI_QUERY)
check("Detective REJECTED for agriculture query", ok10, False)
if not ok10:
    print(f"         Rejection reason: {reason10}")

c11 = _make_company("Pune News Network", "news media", "news newspaper media company broadcast publishing")
ok11, reason11 = validate_candidate(c11, AGRI_QUERY)
check("News REJECTED for agriculture query", ok11, False)
if not ok11:
    print(f"         Rejection reason: {reason11}")


# ═════════════════════════════════════════════════════════════════════════════
# 5. Cache key is category+location aware
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 5. Cache key category-awareness ===")

key_retail_pune   = _cache_key("example.com", "retail",      "pune")
key_agri_pune     = _cache_key("example.com", "agriculture", "pune")
key_retail_mumbai = _cache_key("example.com", "retail",      "mumbai")
key_retail_empty  = _cache_key("example.com", "retail",      "")

check("retail/pune != agri/pune",    key_retail_pune != key_agri_pune,     True)
check("retail/pune != retail/mumbai",key_retail_pune != key_retail_mumbai, True)
check("retail/pune != retail/empty", key_retail_pune != key_retail_empty,  True)
print(f"  Cache key example: {key_retail_pune!r}")


# ═════════════════════════════════════════════════════════════════════════════
# Summary
# ═════════════════════════════════════════════════════════════════════════════
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"\n{'='*55}")
print(f"  RESULTS: {passed} PASSED  |  {failed} FAILED  (total {len(results)})")
print(f"{'='*55}")
if failed:
    print("\nFailed tests:")
    for r in results:
        if r[0] == FAIL:
            print(f"  ✗ {r[1]}: {r[2]}")
    sys.exit(1)
else:
    print("\nAll tests PASSED.")
