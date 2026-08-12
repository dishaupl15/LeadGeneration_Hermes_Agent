"""
Diagnose why pharma and manufacturing return only 2 results.
Tests the exact keyword-matching logic against realistic CE API return values.
Run: .venv\Scripts\python.exe test_pharma_mfg_diag.py
"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8')

# ── exact copies of the current keyword lists ─────────────────────────────────

_CE_CATEGORY_KEYWORDS_PHARMA = [
    "pharmaceutical", "pharma company", "drug manufacturer",
    "medicine manufacturer", "clinical", "formulation",
    "dosage form", "tablet manufacturer", "capsule manufacturer",
    "bulk drug", "active pharmaceutical", "life sciences company",
    "biopharma",
]

_CE_CATEGORY_KEYWORDS_MFG = [
    "manufactur", "fabricat", "industrial production",
    "factory", "plant production", "machiner", "tooling",
    "casting", "forging", "precision engineering", "foundry",
    "industrial manufacturer", "produces components",
    "produces parts", "production facility",
]

_INDUSTRY_KEYWORDS_PHARMA = [
    "pharma", "pharmaceutical", "pharmaceuticals", "pharmacy",
    "drug", "medicine", "medicines", "clinical", "formulation",
    "dosage", "tablet", "capsule", "injectable", "api",
    "active pharmaceutical ingredient",
    "cpg", "bulk drug", "life science", "biopharma", "clinical trials",
]

_INDUSTRY_KEYWORDS_MFG = [
    "manufacturing", "manufacturer", "manufacturers", "fabrication",
    "fabricator", "fabricators", "machinery", "factory", "plant",
    "production", "assembly", "components", "parts", "metal",
    "steel", "cast", "casting", "molding", "tooling", "toolroom",
    "machined", "forged", "precision engineering", "industrial",
    "engineering works", "electrical panel", "automotive component",
    "pump", "valve", "welding", "press", "die", "fabricated",
    "machine shop", "foundry", "manufacturing unit", "industrial automation",
]

_MFG_DISQUALIFIERS_CE = ["consulting", "marketing agency", "real estate", "hotel",
                          "education", "school", "restaurant", "media"]

_MFG_DISQUALIFIERS_VALIDATE = [
    "hotel", "resort", "spa", "restaurant", "cafe", "bar",
    "salon", "clinic", "dentist", "dentistry", "hospital",
    "school", "college", "university", "academy",
    "job", "jobs", "career", "careers", "recruit", "recruitment",
    "real estate", "property", "projects", "builder",
    "property developer", "media", "magazine", "news",
    "event", "conference", "consulting", "agency",
]

PASS = "PASS"
FAIL = "FAIL ← BUG"

def check(label, condition, detail=""):
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f"\n          detail: {detail}" if detail else ""))
    return condition

# ──────────────────────────────────────────────────────────────────────────────
# What CE commonly returns for pharma industry field
# (based on real API behaviour for Indian pharma companies)
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("PHARMA — CE industry field values (Step 1 of _is_category_relevant)")
print("="*70)
pharma_ce_industry_cases = [
    # (ce_industry, expected, note)
    ("pharmaceutical",            True,  "bare 'pharmaceutical' — CE returns this often"),
    ("Pharmaceutical",            True,  "capitalized"),
    ("pharma",                    False, "BUG: bare 'pharma' NOT in keyword list"),
    ("Pharma",                    False, "BUG: capitalized 'Pharma' not matched"),
    ("Pharmaceuticals",           True,  "plural — 'pharmaceutical' is a substring"),
    ("Drug Manufacturing",        False, "BUG: 'drug manufacturing' not in list; 'drug manufacturer' is"),
    ("Medicine",                  False, "BUG: bare 'medicine' not in keyword list"),
    ("Medicines",                 False, "BUG: bare 'medicines' not in keyword list"),
    ("API Manufacturing",         False, "BUG: 'api' not in CE keyword list"),
    ("Bulk Drugs",                False, "BUG: 'bulk drugs' — 'bulk drug' needs exact match"),
    ("Life Sciences",             False, "BUG: 'life sciences' not in CE keyword list"),
    ("Clinical Research",         True,  "'clinical' matches"),
    ("Biotech",                   False, "BUG: 'biotech' not in pharma CE keyword list"),
    ("Specialty Chemicals",       False, "not pharma — correctly rejected"),
    ("Information Technology",    False, "IT — correctly rejected"),
]

fails_pharma = 0
for ce_ind, expected, note in pharma_ce_industry_cases:
    result = any(kw in ce_ind.lower() for kw in _CE_CATEGORY_KEYWORDS_PHARMA)
    ok = result == expected
    if not ok: fails_pharma += 1
    check(f"CE industry={ce_ind!r}", ok, f"got={result} expected={expected} — {note}")

print(f"\n  → {fails_pharma} bugs found in pharma CE keyword matching")

print("\n" + "="*70)
print("MANUFACTURING — CE industry field values (Step 1)")
print("="*70)
mfg_ce_industry_cases = [
    # (ce_industry, expected, note)
    ("Manufacturing",             True,  "'manufactur' prefix matches"),
    ("manufacturing",             True,  "lowercase"),
    ("Manufacturer",              True,  "'manufactur' prefix matches"),
    ("Fabrication",               True,  "'fabricat' prefix matches"),
    ("Engineering",               False, "BUG: bare 'engineering' not in CE list"),
    ("Engineering Services",      False, "BUG: 'engineering services' not matched"),
    ("Industrial",                False, "BUG: bare 'industrial' not in CE keyword list"),
    ("Industrial Manufacturing",  True,  "'manufactur' matches in compound"),
    ("Metal Fabrication",         True,  "'fabricat' matches"),
    ("Precision Components",      False, "BUG: 'precision components' not matched"),
    ("Auto Components",           False, "BUG: 'auto components' not matched"),
    ("Steel",                     False, "BUG: bare 'steel' not in CE keyword list"),
    ("Machine Tools",             False, "BUG: 'machine tools' not matched; 'machiner' is"),
    ("Plastics Manufacturing",    True,  "'manufactur' matches"),
    ("Chemical Manufacturing",    True,  "'manufactur' matches"),
    ("Consulting",                False, "correctly rejected by disqualifier"),
    ("Real Estate",               False, "correctly rejected by disqualifier"),
]

fails_mfg = 0
for ce_ind, expected, note in mfg_ce_industry_cases:
    # Check disqualifier first
    is_dq = any(dq in ce_ind.lower() for dq in _MFG_DISQUALIFIERS_CE)
    if is_dq:
        result = False
    else:
        result = any(kw in ce_ind.lower() for kw in _CE_CATEGORY_KEYWORDS_MFG)
    ok = result == expected
    if not ok: fails_mfg += 1
    check(f"CE industry={ce_ind!r}", ok, f"got={result} expected={expected} — {note}")

print(f"\n  → {fails_mfg} bugs found in manufacturing CE keyword matching")

print("\n" + "="*70)
print("MANUFACTURING — validate_candidate disqualifier false-positives")
print("="*70)
print("  These manufacturing companies would be INCORRECTLY REJECTED by")
print("  validate_candidate's industry_key=='manufacturing' disqualifier block:")
mfg_validate_cases = [
    # (industry_text, expected_pass, company_note)
    ("Sun Pharma Industries Limited pharmaceutical manufacturing plant India",
     False, "BUG: 'plant' triggers no disqualifier but 'pharmaceutical' is fine..."),
    ("ABC Auto Components manufacturing precision parts pune",
     True,  "should pass — no disqualifiers"),
    ("XYZ Industrial Projects Pvt Ltd fabrication pune",
     False, "BUG: 'projects' in disqualifier list — rejects valid mfg co"),
    ("Precision Engineering & Consulting pune manufacturing",
     False, "BUG: 'consulting' in disqualifier — rejects valid co if they offer consulting"),
    ("ABC Properties and Manufacturing pune",
     False, "BUG: 'property' disqualifier — name contains 'properties'"),
    ("Pune Industrial Agency for Manufacturing",
     False, "BUG: 'agency' disqualifier — too broad"),
    ("Global Builders and Manufacturers pune",
     False, "BUG: 'builder' disqualifier — rejects company named 'builders & manufacturers'"),
]

fails_validate = 0
for industry_text, expected_pass, note in mfg_validate_cases:
    disqualified = any(term in industry_text.lower() for term in _MFG_DISQUALIFIERS_VALIDATE)
    actual_pass = not disqualified
    ok = actual_pass == expected_pass
    if not ok: fails_validate += 1
    check(
        f"text contains disqualifier",
        ok,
        f"pass={actual_pass} expected={expected_pass} — {note}"
    )

print(f"\n  → {fails_validate} false-rejection bugs in manufacturing validate_candidate")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"  pharma CE keyword gaps:       {fails_pharma}")
print(f"  manufacturing CE keyword gaps: {fails_mfg}")
print(f"  manufacturing false-rejects:  {fails_validate}")
print()
print("  Root causes:")
print("  1. pharma: bare 'pharma', 'drug manufacturing', 'medicine', 'life sciences',")
print("             'api manufacturing', 'bulk drugs' all missing from CE keyword list")
print("  2. manufacturing: 'engineering', 'industrial', 'steel', 'precision components'")
print("             missing from CE keyword list")
print("  3. manufacturing validate_candidate: 'projects', 'consulting', 'agency',")
print("             'builder', 'property' disqualifiers are too broad — reject valid cos")
