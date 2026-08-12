"""
Tests for the strict category filtering changes.
Covers: retail, agriculture, unknown, and known categories.
Run: .venv\Scripts\python.exe test_category_gate.py
"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8')

# ── Import the real functions from the module ────────────────────────────────
import importlib.util, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).parent))

# Patch the env/imports so discovery_service loads without network calls
import unittest.mock as mock
mock_httpx = mock.MagicMock()
mock_dotenv = mock.MagicMock()
sys.modules['httpx'] = mock_httpx
sys.modules['dotenv'] = mock_dotenv
sys.modules['dotenv'].load_dotenv = lambda: None

# Stub out sub-services discovery_service imports lazily
for mod in ['app.services.verify_service', 'app.services.companyenrich_service']:
    sys.modules[mod] = mock.MagicMock()

# Load discovery_service
import importlib
spec = importlib.util.spec_from_file_location(
    "discovery_service",
    pathlib.Path(__file__).parent / "app" / "services" / "discovery_service.py"
)
ds = importlib.util.module_from_spec(spec)
# Stub out any remaining imports
with mock.patch.dict('sys.modules', {
    'app.services.verify_service': mock.MagicMock(),
    'app.services.companyenrich_service': mock.MagicMock(),
    'app': mock.MagicMock(),
    'app.services': mock.MagicMock(),
}):
    spec.loader.exec_module(ds)

_norm = ds._normalise_industry_key
_has_rel = ds._has_industry_relevance
_ce_rel = ds._is_category_relevant

OK  = "\033[92mPASS\033[0m"
BAD = "\033[91mFAIL\033[0m"
results = []

def check(label, condition, detail=""):
    s = OK if condition else BAD
    msg = f"  [{s}] {label}"
    if detail:
        msg += f"\n         {detail}"
    print(msg)
    results.append(condition)
    return condition

print("\n" + "="*70)
print("1. _normalise_industry_key — retail, agriculture, and unknowns")
print("="*70)
check("retail → 'retail'",         _norm("Retail companies in Pune") == "retail")
check("agriculture → 'agriculture'", _norm("Agriculture companies in Pune") == "agriculture")
check("pharma → 'pharma'",          _norm("Pharma companies in Pune") == "pharma")
check("unknown → raw string",        _norm("Detective agencies in Pune") == "detective agencies")

print("\n" + "="*70)
print("2. _has_industry_relevance — retail")
print("="*70)
check("Retail keyword in text — PASS",
      _has_rel("a leading retail chain offering consumer goods", "retail"))
check("FMCG keyword — PASS",
      _has_rel("fmcg company selling packaged foods", "retail"))
check("Hotel text for retail query — FAIL",
      not _has_rel("luxury hotel and spa services pune", "retail"))
check("Real estate for retail query — FAIL",
      not _has_rel("real estate developer building apartments", "retail"))
check("Agriculture text for retail query — FAIL",
      not _has_rel("agricultural company growing wheat and vegetables", "retail"))
check("IT company for retail query — FAIL",
      not _has_rel("software development company providing saas solutions", "retail"))
check("Detective agency for retail query — FAIL",
      not _has_rel("detective agency investigation services pune", "retail"))

print("\n" + "="*70)
print("3. _has_industry_relevance — agriculture")
print("="*70)
check("Agriculture keyword — PASS",
      _has_rel("agriculture company farming organic crops", "agriculture"))
check("Agribusiness keyword — PASS",
      _has_rel("agribusiness company supplying seeds and fertilizers", "agriculture"))
check("Dairy company — PASS",
      _has_rel("dairy company producing milk products pune", "agriculture"))
check("Hotel for agriculture query — FAIL",
      not _has_rel("hotel and resort hospitality services", "agriculture"))
check("Real estate for agriculture query — FAIL",
      not _has_rel("real estate property developer pune", "agriculture"))
check("Tourism for agriculture query — FAIL",
      not _has_rel("tourism company travel and tours pune", "agriculture"))
check("IT for agriculture query — FAIL",
      not _has_rel("it services software company pune", "agriculture"))
check("Detective for agriculture query — FAIL",
      not _has_rel("detective agency investigation services", "agriculture"))
check("News media for agriculture query — FAIL",
      not _has_rel("news media company digital publishing", "agriculture"))

print("\n" + "="*70)
print("4. Unknown category — hard reject (not silent pass)")
print("="*70)
check("Unknown 'detective agencies' → no keywords → REJECT",
      not _has_rel("pune detective agency investigation services", "detective agencies"))
check("Unknown 'recruitment' → no keywords → REJECT",
      not _has_rel("recruitment company hiring services", "recruitment"))
check("Unknown 'spa' → REJECT",
      not _has_rel("spa and wellness centre beauty treatment", "spa"))

print("\n" + "="*70)
print("5. _is_category_relevant — CE result filtering for retail + agriculture")
print("="*70)

retail_result = {
    "name": "Big Retail Chain Ltd",
    "industry": "retail",
    "description": "retail chain with multiple stores across pune",
}
hotel_result = {
    "name": "Grand Hotel Pune",
    "industry": "hospitality",
    "description": "luxury hotel and resort services pune",
}
farm_result = {
    "name": "Pune Agro Farms",
    "industry": "agriculture",
    "description": "agribusiness company growing crops pune",
}
it_for_agri = {
    "name": "AgroTech IT Solutions",
    "industry": "information technology",
    "description": "software solutions for agriculture sector clients",
}
unknown_result = {
    "name": "Pune Detective Agency",
    "industry": "security services",
    "description": "detective agency investigation services pune",
}

check("Retail result for retail query — PASS",
      _ce_rel(retail_result, "retail"))
check("Hotel result for retail query — FAIL",
      not _ce_rel(hotel_result, "retail"))
check("Farm for agriculture query — PASS",
      _ce_rel(farm_result, "agriculture"))
check("IT company mentioning 'agriculture clients' for agri query — FAIL",
      not _ce_rel(it_for_agri, "agriculture"))
check("Unknown category 'detective agencies' — FAIL (no keywords = reject)",
      not _ce_rel(unknown_result, "detective agencies"))

print("\n" + "="*70)
print("6. Known categories still work correctly")
print("="*70)
pharma_result = {
    "name": "Cipla Ltd",
    "industry": "pharmaceutical",
    "description": "pharmaceutical manufacturer drug maker pune",
}
mfg_result = {
    "name": "ABC Fabricators Pvt Ltd",
    "industry": "manufacturing",
    "description": "precision manufacturing company pune",
}
check("Pharma for pharma query — PASS",  _ce_rel(pharma_result, "pharma"))
check("Mfg for manufacturing query — PASS", _ce_rel(mfg_result, "manufacturing"))
check("Pharma for retail query — FAIL",  not _ce_rel(pharma_result, "retail"))
check("Mfg for agriculture query — FAIL", not _ce_rel(mfg_result, "agriculture"))

print("\n" + "="*70)
total = len(results)
passed = sum(results)
print(f"RESULT: {passed}/{total} tests passed")
if passed == total:
    print("ALL TESTS PASSED ✓")
else:
    print(f"{total-passed} TESTS FAILED ✗")
print("="*70)
