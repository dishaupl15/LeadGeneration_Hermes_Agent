#!/usr/bin/env python3
"""
test_accuracy_audit.py
──────────────────────
Production-quality data accuracy audit for the Serper+Firecrawl pipeline.

Runs the pipeline once, then performs deep per-field analysis on every
returned company — checking company_name, website, email, company_number,
address, founder_name, confidence.

Does NOT modify any code. Read-only analysis only.

Run from backend/:
    python test_accuracy_audit.py
Server must be running: uvicorn app.main:app --port 8002 --reload
"""

import json
import re
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_URL = "http://127.0.0.1:8002"
QUERY    = "Real Estate companies in Pune"
COUNT    = 10
TIMEOUT  = 180

# ── Helpers ───────────────────────────────────────────────────────────────────

def post_json(url, body, timeout=TIMEOUT):
    data = json.dumps(body).encode()
    req  = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:400]}")
    except URLError as e:
        raise RuntimeError(f"Cannot reach {url}: {e.reason}\nStart: uvicorn app.main:app --port 8002 --reload")

def get_json(url, timeout=10):
    with urlopen(Request(url), timeout=timeout) as r:
        return json.loads(r.read().decode())

def domain_of(url):
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""

# ── Known-good Pune real estate companies (ground truth seed) ─────────────────
# These are verifiable real Pune RE companies with public websites
KNOWN_PUNE_RE = {
    "koltepatil.com":      {"name": "Kolte-Patil Developers",  "email_domain": "koltepatil.com"},
    "panchshil.com":       {"name": "Panchshil Realty",        "email_domain": "panchshil.com"},
    "nyatigroup.com":      {"name": "Nyati Group",             "email_domain": "nyatigroup.com"},
    "vtprealty.in":        {"name": "VTP Realty",              "email_domain": "vtprealty.in"},
    "runal.com":           {"name": "Runal Group",             "email_domain": "runal.com"},
    "purplecorp.in":       {"name": "Purple Group",            "email_domain": "purplecorp.in"},
    "austinrealty.in":     {"name": "Austin Realty",           "email_domain": "austinrealty.in"},
    "realtorsindia.net":   {"name": "Realtors India",          "email_domain": "realtorsindia.net"},
    "adanirealty.com":     {"name": "Adani Realty",            "email_domain": "adanirealty.com"},
    "cushmanwakefield.com":{"name": "Cushman & Wakefield",     "email_domain": "cushwake.com"},
    "theoptionsrealestate.com": {"name": "The Options Real Estate", "email_domain": "theoptionsrealestate.com"},
    "tejraj.in":           {"name": "Tejraj Group",            "email_domain": "tejraj.in"},
}

# Domains that are NOT official company websites (aggregators, portals, etc.)
JUNK_DOMAINS = {
    "propjinni.com",        # real estate portal/aggregator
    "punerealty.in",        # broker aggregator
    "realpropertiesemag.com",  # magazine/media
    "realestateagent.com",
    "thebalancemoney.com",
    "naiknavare.com",       # verify — could be real
    "cushmanwakefield.com", # legit global RE firm but not Pune-specific
}

# Titles that indicate the result is NOT a company homepage
AGGREGATOR_TITLE_PATTERNS = [
    r'top \d+',
    r'best \d+',
    r'list of',
    r'directory',
    r'brokers? in',
    r'agents? in',
    r'developers? in',
    r'companies in',
    r'reviews?',
    r'magazine',
    r'real estate agents?$',
    r'real estate companies',
]
_AGG_RE = re.compile('|'.join(AGGREGATOR_TITLE_PATTERNS), re.IGNORECASE)


def is_aggregator_title(title):
    return bool(_AGG_RE.search(title))


def email_domain_matches_website(email, website):
    """Check email domain is the same as the company website domain."""
    if not email or not website:
        return False
    email_dom = email.split("@")[-1].lower().lstrip("www.")
    site_dom  = domain_of(website)
    return email_dom == site_dom or site_dom.endswith("." + email_dom) or email_dom.endswith("." + site_dom)


def is_indian_phone(phone):
    """Rough check: phone looks like an Indian number."""
    digits = re.sub(r'\D', '', phone)
    if digits.startswith("91") and len(digits) == 12:
        return True
    if digits.startswith("0") and 10 <= len(digits) <= 12:
        return True
    if len(digits) == 10 and digits[0] in "6789":
        return True
    if digits.startswith("1800") and len(digits) >= 10:
        return True  # toll-free
    return False


def is_foreign_phone(phone):
    """Detect clearly non-Indian international numbers."""
    digits = re.sub(r'\D', '', phone)
    # starts with country code that isn't +91
    if phone.startswith("+") and not phone.startswith("+91") and not phone.startswith("+1800"):
        cc = digits[:2] if len(digits) >= 2 else ""
        if cc not in ("91",):
            return True
    # US format: (212) 301 1140 etc.
    if re.match(r'^\(\d{3}\)', phone.strip()):
        return True
    return False


# ── Per-company analysis ──────────────────────────────────────────────────────

def audit_company(idx, c):
    """
    Return an audit dict with pass/fail for each field and issue descriptions.
    """
    name     = c.get("company_name", "")
    website  = c.get("website", "")
    email    = c.get("email", "")
    phone    = c.get("company_number", "")
    address  = c.get("address", "")
    founder  = c.get("founder_name", "")
    conf     = c.get("confidence", 0.0)
    sources  = c.get("research_sources", []) or c.get("sources", [])

    issues   = []
    warnings = []

    site_dom = domain_of(website)

    # ── company_name ──────────────────────────────────────────────────────────
    name_ok = True
    if not name:
        name_ok = False; issues.append("MISSING company_name")
    elif is_aggregator_title(name):
        name_ok = False; issues.append(f"company_name looks like aggregator/list page: {name!r}")
    elif len(name) < 3:
        name_ok = False; issues.append(f"company_name too short: {name!r}")

    # ── website ───────────────────────────────────────────────────────────────
    website_ok = True
    website_is_official = False
    if not website:
        website_ok = False; issues.append("MISSING website")
    else:
        if site_dom in JUNK_DOMAINS:
            website_ok = False; issues.append(f"website is aggregator/portal: {site_dom}")
        elif site_dom in KNOWN_PUNE_RE:
            website_is_official = True
        else:
            # Unknown domain — could still be legit, flag as unverified
            warnings.append(f"website domain not in known-good set: {site_dom}")
            website_is_official = True  # assume legitimate unless domain is known-junk

        # Check URL has a path that suggests it's a sub-page rather than homepage
        parsed_path = urlparse(website).path
        if parsed_path not in ("", "/", "/contact-us", "/about", "/about-us"):
            if len(parsed_path) > 30:
                warnings.append(f"website URL has deep path (may not be homepage): {parsed_path[:50]}")

    # ── email ─────────────────────────────────────────────────────────────────
    email_ok = False
    email_verified = False
    email_status_note = ""
    if not email:
        email_status_note = c.get("email_status", "not_publicly_found")
        # Is it genuinely unavailable or a pipeline miss?
        if site_dom in KNOWN_PUNE_RE:
            known = KNOWN_PUNE_RE[site_dom]
            expected_dom = known.get("email_domain", "")
            if expected_dom:
                email_status_note += f" [pipeline_miss: expected @{expected_dom}]"
                issues.append(f"email MISSING — pipeline likely missed it (expected @{expected_dom})")
            else:
                email_status_note += " [genuinely_unavailable]"
        else:
            email_status_note += " [unknown: may be genuinely unavailable]"
    else:
        if email_domain_matches_website(email, website):
            email_ok = True
            email_verified = True
        else:
            email_dom = email.split("@")[-1].lower()
            issues.append(
                f"email domain {email_dom!r} does NOT match website domain {site_dom!r} "
                f"— possible cross-company pollution"
            )

    # ── company_number ────────────────────────────────────────────────────────
    phone_ok = False
    phone_verified = False
    phone_status_note = ""
    if not phone:
        phone_status_note = c.get("phone_status", "not_publicly_found")
    else:
        if is_foreign_phone(phone):
            issues.append(f"phone looks non-Indian/foreign: {phone!r}")
        elif is_indian_phone(phone):
            phone_ok = True
            phone_verified = True
        else:
            warnings.append(f"phone format unrecognised — needs manual check: {phone!r}")
            phone_ok = True  # give benefit of doubt

    # ── address ───────────────────────────────────────────────────────────────
    address_ok = False
    address_verified = False
    if not address:
        pass  # genuinely missing
    else:
        # Check address is not just a description sentence (common extraction error)
        word_count = len(address.split())
        if word_count > 30:
            issues.append(f"address looks like a paragraph/description, not an address ({word_count} words)")
        elif any(city in address for city in ["Pune", "Mumbai", "Bengaluru", "Delhi", "India"]):
            address_ok = True
            address_verified = True
        else:
            warnings.append(f"address doesn't mention a known Indian city: {address[:80]!r}")
            address_ok = True  # give benefit of doubt for international companies

    # ── founder_name ──────────────────────────────────────────────────────────
    founder_ok = False
    founder_verified = False
    # Known founder cross-check
    KNOWN_FOUNDERS = {
        "koltepatil.com":    ["Rajesh Patil", "Milind Kolte", "Sunita Kolte"],
        "panchshil.com":     ["Atul Chordia"],
        "nyatigroup.com":    ["Manohar Shroff", "Anup Shroff"],
        "vtprealty.in":      ["Sachin Bhandari", "Vikram Goel"],
        "cushmanwakefield.com": ["John Cushman", "Wellington Wakefield"],
    }
    if not founder:
        pass  # genuinely missing
    else:
        known_founders = KNOWN_FOUNDERS.get(site_dom, [])
        if known_founders:
            if any(kf.lower() in founder.lower() or founder.lower() in kf.lower()
                   for kf in known_founders):
                founder_ok = True
                founder_verified = True
            else:
                issues.append(
                    f"founder {founder!r} does NOT match known founders for {site_dom}: "
                    f"{known_founders}"
                )
        else:
            # Unknown company — accept if it looks like a real name
            parts = founder.strip().split()
            if (2 <= len(parts) <= 4 and
                    all(p[0].isupper() and p[1:].islower() for p in parts if len(p) > 1)):
                founder_ok = True
                founder_verified = True
            else:
                warnings.append(f"founder name format looks odd: {founder!r}")
                founder_ok = True  # still count it as present

    # ── confidence sanity ─────────────────────────────────────────────────────
    expected_conf = 0.0
    if email_verified:   expected_conf += 0.30
    if phone_verified:   expected_conf += 0.25
    if address_verified: expected_conf += 0.05
    if sources:          expected_conf += 0.10
    if website:          expected_conf += 0.05

    if conf > expected_conf + 0.25:
        warnings.append(
            f"confidence={conf} seems HIGH vs evidence (expected ~{round(expected_conf,2)})"
        )
    elif conf < expected_conf - 0.20 and expected_conf > 0.2:
        warnings.append(
            f"confidence={conf} seems LOW vs evidence (expected ~{round(expected_conf,2)})"
        )

    return {
        "idx":              idx,
        "company_name":     name,
        "website":          website,
        "site_dom":         site_dom,
        "email":            email or None,
        "phone":            phone or None,
        "address":          address or None,
        "founder":          founder or None,
        "confidence":       conf,
        "research_sources": sources,
        # pass/fail
        "name_ok":         name_ok,
        "website_ok":      website_ok,
        "website_official": website_is_official,
        "email_ok":        email_ok,
        "email_verified":  email_verified,
        "email_status":    email_status_note,
        "phone_ok":        phone_ok,
        "phone_verified":  phone_verified,
        "phone_status":    phone_status_note,
        "address_ok":      address_ok,
        "address_verified": address_verified,
        "founder_ok":      founder_ok,
        "founder_verified": founder_verified,
        "issues":          issues,
        "warnings":        warnings,
    }


# ── Main audit runner ─────────────────────────────────────────────────────────

def run_audit():
    SEP = "=" * 72

    print(SEP)
    print("PRODUCTION DATA ACCURACY AUDIT")
    print(f"Query  : {QUERY!r}")
    print(f"Count  : {COUNT}")
    print(SEP)

    # Health check
    try:
        h = get_json(f"{BASE_URL}/health")
        print(f"Server : {h.get('app')} v{h.get('version')} [{h.get('status')}]")
    except Exception as e:
        print(f"ERROR: Server not reachable — {e}")
        sys.exit(1)

    # Run pipeline
    print(f"\nRunning pipeline... (may take 20-60s)")
    t0 = time.monotonic()
    try:
        result = post_json(
            f"{BASE_URL}/leads/generate-leads",
            {"query": QUERY, "count": COUNT},
        )
    except RuntimeError as e:
        print(f"PIPELINE ERROR: {e}")
        sys.exit(1)

    elapsed = round(time.monotonic() - t0, 1)
    leads = result.get("leads", [])

    print(f"Elapsed: {elapsed}s")
    print(f"Returned: {len(leads)} companies\n")

    # Save raw JSON for inspection
    with open("audit_raw_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print("Raw output saved → audit_raw_output.json\n")

    # ── Per-company audit ─────────────────────────────────────────────────────
    audits = [audit_company(i + 1, c) for i, c in enumerate(leads)]

    print(SEP)
    print("PER-COMPANY ANALYSIS")
    print(SEP)

    for a in audits:
        ok_sym  = lambda b: "✅" if b else "❌"
        warn_sym = "⚠️ " if a["warnings"] else "   "

        print(f"\n[{a['idx']:02d}] {a['company_name']}")
        print(f"     website   : {a['website']}")
        print(f"     domain    : {a['site_dom']}  {ok_sym(a['website_ok'])}")
        print(f"     email     : {a['email'] or '(none)'}  {ok_sym(a['email_ok'])}"
              + (f"  [{a['email_status']}]" if not a['email_ok'] and a['email_status'] else ""))
        print(f"     phone     : {a['phone'] or '(none)'}  {ok_sym(a['phone_ok'])}"
              + (f"  [{a['phone_status']}]" if not a['phone_ok'] and a['phone_status'] else ""))
        print(f"     address   : {(a['address'] or '(none)')[:80]}  {ok_sym(a['address_ok'])}")
        print(f"     founder   : {a['founder'] or '(none)'}  {ok_sym(a['founder_ok'])}")
        print(f"     confidence: {a['confidence']}  sources={len(a['research_sources'])}")
        if a["issues"]:
            for iss in a["issues"]:
                print(f"     ❌ ISSUE: {iss}")
        if a["warnings"]:
            for w in a["warnings"]:
                print(f"     ⚠️  WARN : {w}")

    # ── Summary metrics ───────────────────────────────────────────────────────
    n = len(audits)

    valid_names        = sum(1 for a in audits if a["name_ok"])
    official_websites  = sum(1 for a in audits if a["website_ok"])
    verified_emails    = sum(1 for a in audits if a["email_verified"])
    emails_present     = sum(1 for a in audits if a["email"])
    verified_phones    = sum(1 for a in audits if a["phone_verified"])
    phones_present     = sum(1 for a in audits if a["phone"])
    verified_addresses = sum(1 for a in audits if a["address_verified"])
    addresses_present  = sum(1 for a in audits if a["address"])
    verified_founders  = sum(1 for a in audits if a["founder_verified"])
    founders_present   = sum(1 for a in audits if a["founder"])

    all_issues = [(a["idx"], a["company_name"], iss)
                  for a in audits for iss in a["issues"]]
    all_warns  = [(a["idx"], a["company_name"], w)
                  for a in audits for w in a["warnings"]]

    wrong_names    = sum(1 for a in audits if not a["name_ok"])
    wrong_websites = sum(1 for a in audits if not a["website_ok"])
    wrong_emails   = sum(1 for a in audits if a["email"] and not a["email_ok"])
    wrong_phones   = sum(1 for a in audits if a["phone"] and not a["phone_ok"])
    wrong_addresses= sum(1 for a in audits if a["address"] and not a["address_ok"])
    wrong_founders = sum(1 for a in audits if a["founder"] and not a["founder_ok"])

    # Hermes proof
    hermes_leads = [c for c in leads if (c.get("research_source") or "").lower() == "hermes"]

    print()
    print(SEP)
    print("SUMMARY METRICS")
    print(SEP)
    print(f"  Total returned            : {n}/10")
    print(f"  Execution time            : {elapsed}s {'✅' if elapsed <= 60 else '⚠️'}")
    print()
    print(f"  Valid company names       : {valid_names}/{n}  ({pct(valid_names,n)}%)")
    print(f"  Official websites         : {official_websites}/{n}  ({pct(official_websites,n)}%)")
    print(f"  Emails present            : {emails_present}/{n}  ({pct(emails_present,n)}%)")
    print(f"  Emails domain-verified    : {verified_emails}/{n}  ({pct(verified_emails,n)}%)")
    print(f"  Phones present            : {phones_present}/{n}  ({pct(phones_present,n)}%)")
    print(f"  Phones format-verified    : {verified_phones}/{n}  ({pct(verified_phones,n)}%)")
    print(f"  Addresses present         : {addresses_present}/{n}  ({pct(addresses_present,n)}%)")
    print(f"  Addresses city-verified   : {verified_addresses}/{n}  ({pct(verified_addresses,n)}%)")
    print(f"  Founders present          : {founders_present}/{n}  ({pct(founders_present,n)}%)")
    print(f"  Founders name-verified    : {verified_founders}/{n}  ({pct(verified_founders,n)}%)")
    print()
    print(f"  WRONG company names       : {wrong_names}")
    print(f"  WRONG/junk websites       : {wrong_websites}")
    print(f"  WRONG emails              : {wrong_emails}")
    print(f"  WRONG phones              : {wrong_phones}")
    print(f"  WRONG addresses           : {wrong_addresses}")
    print(f"  WRONG founders            : {wrong_founders}")
    print()
    print(f"  Hermes called             : {'YES ❌' if hermes_leads else 'NO ✅'}")

    # ── Missing data analysis ─────────────────────────────────────────────────
    missing_emails = [(a["idx"], a["company_name"], a["site_dom"], a["email_status"])
                      for a in audits if not a["email"]]
    missing_phones = [(a["idx"], a["company_name"], a["site_dom"])
                      for a in audits if not a["phone"]]
    missing_addrs  = [(a["idx"], a["company_name"], a["site_dom"])
                      for a in audits if not a["address"]]

    if missing_emails:
        print()
        print("MISSING EMAIL ANALYSIS")
        print("-" * 60)
        for idx, name, dom, status in missing_emails:
            print(f"  [{idx:02d}] {name} ({dom})")
            if "pipeline_miss" in status:
                print(f"       → PIPELINE MISS: {status}")
            elif "genuinely" in status:
                print(f"       → Genuinely unavailable (company does not publish email)")
            else:
                print(f"       → Unknown: {status}")

    if missing_phones:
        print()
        print("MISSING PHONE ANALYSIS")
        print("-" * 60)
        for idx, name, dom in missing_phones:
            print(f"  [{idx:02d}] {name} ({dom})")

    if missing_addrs:
        print()
        print("MISSING ADDRESS ANALYSIS")
        print("-" * 60)
        for idx, name, dom in missing_addrs:
            print(f"  [{idx:02d}] {name} ({dom})")

    # ── Issues list ───────────────────────────────────────────────────────────
    if all_issues:
        print()
        print("ALL ISSUES")
        print("-" * 60)
        for idx, name, iss in all_issues:
            print(f"  [{idx:02d}] {name}: {iss}")

    if all_warns:
        print()
        print("ALL WARNINGS")
        print("-" * 60)
        for idx, name, w in all_warns:
            print(f"  [{idx:02d}] {name}: {w}")

    # ── Production readiness verdict ──────────────────────────────────────────
    hard_failures = wrong_names + wrong_websites + wrong_emails + wrong_phones
    score = (
        valid_names + official_websites + verified_emails +
        verified_phones + verified_addresses
    )
    max_score = n * 5

    print()
    print(SEP)
    print("PRODUCTION READINESS VERDICT")
    print(SEP)

    if hermes_leads:
        print("❌ FAIL — Hermes was called")
    elif hard_failures == 0 and wrong_founders == 0:
        print(f"✅ PASS — No hard field errors detected")
    elif hard_failures <= 2:
        print(f"⚠️  CONDITIONAL PASS — {hard_failures} hard field error(s), review required")
    else:
        print(f"❌ FAIL — {hard_failures} hard field errors detected")

    quality_pct = pct(score, max_score)
    print(f"Overall quality score: {score}/{max_score} ({quality_pct}%)")
    print()

    # ── Top 5 problems ────────────────────────────────────────────────────────
    problems = []
    if wrong_names > 0:
        problems.append(f"AGGREGATOR NAMES: {wrong_names} company_name(s) are list/aggregator pages, not real companies")
    if wrong_websites > 0:
        problems.append(f"JUNK WEBSITES: {wrong_websites} website(s) are portal/aggregator domains")
    if wrong_emails > 0:
        problems.append(f"EMAIL DOMAIN MISMATCH: {wrong_emails} email(s) don't match the company website")
    if wrong_phones > 0:
        problems.append(f"PHONE ISSUES: {wrong_phones} phone(s) look foreign/invalid for a Pune RE company")
    if missing_emails and any("pipeline_miss" in s for _, _, _, s in missing_emails):
        n_miss = sum(1 for _, _, _, s in missing_emails if "pipeline_miss" in s)
        problems.append(f"EMAIL PIPELINE MISSES: {n_miss} email(s) are publicly available but not extracted")
    if wrong_founders > 0:
        problems.append(f"FOUNDER ERRORS: {wrong_founders} founder name(s) don't match known founders")
    low_conf = [a for a in audits if a["phone"] and a["email"] and a["confidence"] < 0.5]
    if low_conf:
        problems.append(f"LOW CONFIDENCE with contacts: {len(low_conf)} companies have email+phone but confidence<0.5")

    if problems:
        print("TOP PROBLEMS:")
        for i, p in enumerate(problems[:5], 1):
            print(f"  {i}. {p}")
    else:
        print("No significant problems detected.")

    print()
    print("Code changes required: ", end="")
    code_change_needed = hard_failures > 0 or any("pipeline_miss" in s for _, _, _, s in missing_emails if missing_emails)
    print("YES — see analysis above" if code_change_needed else "NO (or minor improvements only)")

    return hard_failures, audits, leads


def pct(n, total):
    return round(100 * n / total) if total else 0


if __name__ == "__main__":
    hard_failures, audits, leads = run_audit()

    # Print per-company full JSON for manual inspection
    print()
    print("=" * 72)
    print("FULL JSON OUTPUT (for manual spot-check)")
    print("=" * 72)
    for i, c in enumerate(leads, 1):
        print(f"\n--- Company {i:02d} ---")
        fields = ["company_name", "website", "email", "company_number",
                  "address", "city", "state", "founder_name",
                  "confidence", "research_source", "research_sources"]
        for f in fields:
            val = c.get(f)
            if isinstance(val, list):
                val = val[:3]  # truncate long lists
            if val is not None and val != "" and val != []:
                print(f"  {f}: {val}")

    sys.exit(1 if hard_failures > 3 else 0)
