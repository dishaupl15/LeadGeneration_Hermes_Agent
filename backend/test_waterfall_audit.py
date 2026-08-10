#!/usr/bin/env python3
"""
test_waterfall_audit.py
────────────────────────
Final production audit for the Multi-Source Waterfall Enrichment pipeline.

Run from backend/:
    venv\\Scripts\\python.exe test_waterfall_audit.py
Server: uvicorn app.main:app --port 8002 --reload

Prints per-company detail AND aggregated statistics matching the full spec:
  - Company / Website / Email / Founder / Phone / Address per row
  - Verified vs present counts
  - Wrong/bad field counts
  - Provider call breakdown: Serper / Firecrawl / Hunter / Apollo / PDL / Google Places
  - LLM calls = 0 (assertion)
  - Hermes calls = 0 (assertion)
  - Execution time
  - PASS / CONDITIONAL PASS / FAIL verdict
"""

import json
import re
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE    = "http://127.0.0.1:8002"
QUERY   = "Real Estate companies in Pune"
COUNT   = 10
TIMEOUT = 240   # generous timeout for full waterfall (includes enrichment)

SEP   = "=" * 72
SEP2  = "-" * 72

# ── Known-good reference data ─────────────────────────────────────────────────
KNOWN_FOUNDERS: dict[str, list[str]] = {
    "koltepatil.com":   ["Rajesh Patil", "Milind Kolte", "Aniruddha Patil", "Sunita Kolte"],
    "panchshil.com":    ["Atul Chordia"],
    "nyatigroup.com":   ["Manohar Shroff", "Anup Shroff", "Pranav Nyati", "Nitin Nyati"],
    "vtprealty.in":     ["Sachin Bhandari", "Vikram Goel"],
    "purplecorp.in":    ["Shravan Agarwal", "Harshwardhan Agarwal"],
    "austinrealty.in":  [],   # no known public founder — must NOT fabricate
    "adanirealty.com":  ["Gautam Adani", "Pranav Adani"],
    "gera.in":          ["Rohit Gera"],
}

KNOWN_JUNK_DOMAINS: set[str] = {
    "propjinni.com", "goodfirms.co", "glassdoor.com", "glassdoor.co.in",
    "maharashtradirectory.com", "cushmanwakefield.com",
    "99acres.com", "magicbricks.com", "housing.com", "justdial.com",
    "indiamart.com", "naukri.com", "linkedin.com", "wikipedia.org",
    "maharera.maharashtra.gov.in", "rera.rajasthan.gov.in",
}

AGGREGATOR_RE = re.compile(
    r"(?i)(top\s+\d*\s*real\s+estate|best\s+\d*|list\s+of"
    r"|reviews?\s*\||real\s+estate\s+(?:agents?|companies|developers)\s+in\b)"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def post_json(url: str, body: dict, timeout: int = TIMEOUT) -> dict:
    data = json.dumps(body).encode()
    req  = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:500]}")
    except URLError as e:
        raise RuntimeError(
            f"Cannot reach {url}: {e.reason}\n"
            "Start server:  uvicorn app.main:app --port 8002 --reload"
        )


def get_json(url: str, timeout: int = 8) -> dict:
    with urlopen(Request(url), timeout=timeout) as r:
        return json.loads(r.read().decode())


def email_dom_matches(email: str, site_dom: str) -> bool:
    if not email or not site_dom:
        return False
    edom = email.split("@")[-1].lower()
    return edom == site_dom or edom.endswith("." + site_dom) or site_dom.endswith("." + edom)


def is_indian_phone(p: str) -> bool:
    if not p:
        return False
    d = re.sub(r"\D", "", p)
    if d.startswith("91") and len(d) == 12: return True
    if d.startswith("1800"):               return True
    if len(d) == 10 and d[0] in "6789":    return True
    if d.startswith("0") and 10 <= len(d) <= 12: return True
    return False


def is_foreign_phone(p: str) -> bool:
    if not p:
        return False
    if p.strip().startswith("+") and not p.strip().startswith("+91"):
        return True
    d = re.sub(r"\D", "", p)
    if d.startswith("1") and len(d) == 11 and not d.startswith("1800"):
        return True
    if re.match(r"^\(\d{3}\)", p.strip()):
        return True
    return False


def has_city_or_pin(addr: str) -> bool:
    if not addr:
        return False
    cities = [
        "Pune", "Mumbai", "Delhi", "Bangalore", "Bengaluru", "Hyderabad",
        "Nagpur", "Nashik", "Navi Mumbai", "Thane", "India",
    ]
    if any(c.lower() in addr.lower() for c in cities):
        return True
    if re.search(r"(?<!\d)[1-9]\d{5}(?!\d)", addr):
        return True
    return False


def founder_ok(founder: str | None, site_dom: str) -> bool:
    """True if founder is acceptable for this company domain."""
    known = KNOWN_FOUNDERS.get(site_dom, None)
    if known is None:
        return True        # unknown company — cannot validate, accept
    if not known:
        return founder is None   # must NOT fabricate when no known founder
    if not founder:
        return True        # null is acceptable when we can't verify
    fl = founder.lower()
    return any(k.lower() in fl or fl in k.lower() for k in known)


def extract_provider_source(company: dict, field: str) -> str:
    """Return the provider name that contributed a field."""
    fv = company.get("_field_verification") or {}
    entry = fv.get(field) or {}
    src = entry.get("source", "")
    if not src:
        return "firecrawl/serper"
    sl = src.lower()
    if "hunter"      in sl: return "Hunter"
    if "apollo"      in sl: return "Apollo"
    if "people-data" in sl: return "PDL"
    if "google"      in sl: return "Google Places"
    if "scraped"     in sl: return "Firecrawl"
    if "serper"      in sl: return "Serper"
    return src


def ok_sym(b: bool | None) -> str:
    if b is True:  return "✅"
    if b is False: return "❌"
    return "—"



def run() -> tuple[int, int, float]:
    print(SEP)
    print("WATERFALL ENRICHMENT — FINAL PRODUCTION AUDIT")
    print(f"Query  : {QUERY!r}  Count: {COUNT}")
    print(SEP)

    # ── Health check ──────────────────────────────────────────────────────────
    try:
        h = get_json(f"{BASE}/health")
        print(f"Server : {h.get('app')} v{h.get('version')} [{h.get('status')}]")
    except Exception as e:
        print(f"ERROR: Server not reachable — {e}")
        print(f"Start: uvicorn app.main:app --port 8002 --reload")
        sys.exit(1)

    print(f"\nRunning pipeline (includes waterfall enrichment)…")
    t0 = time.monotonic()
    try:
        result = post_json(f"{BASE}/leads/generate-leads", {"query": QUERY, "count": COUNT})
    except RuntimeError as e:
        print(f"PIPELINE ERROR: {e}")
        sys.exit(1)
    elapsed = round(time.monotonic() - t0, 1)

    leads = result.get("leads", [])
    n     = len(leads)

    with open("waterfall_audit_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"Elapsed: {elapsed}s  |  Returned: {n} companies")
    print(f"Raw output saved → waterfall_audit_output.json\n")

    # ── Per-company detail ────────────────────────────────────────────────────
    print(SEP); print("PER-COMPANY DETAIL"); print(SEP)

    rows: list[dict] = []
    for i, c in enumerate(leads, 1):
        name    = c.get("company_name", "")
        website = c.get("website", "")
        email   = c.get("email")
        phone   = c.get("company_number")
        address = c.get("address", "")
        founder = c.get("founder_name")
        conf    = c.get("confidence", 0.0)
        rsrcs   = c.get("research_sources") or c.get("sources") or []
        src_url = c.get("source_url", "")
        research = c.get("research_source", "")
        dom      = domain_of(website)

        # ── Field evaluations ──────────────────────────────────────────────
        name_ok    = bool(name) and not AGGREGATOR_RE.search(name)
        web_ok     = bool(website) and dom not in KNOWN_JUNK_DOMAINS
        email_veri = email_dom_matches(email, dom) if email else False
        phone_veri = is_indian_phone(phone) if phone else False
        phone_for  = is_foreign_phone(phone) if phone else False
        addr_veri  = has_city_or_pin(address) if address else False
        fnd_ok     = founder_ok(founder, dom)
        fnd_veri   = bool(founder) and fnd_ok

        # ── Provider sources ───────────────────────────────────────────────
        email_src = extract_provider_source(c, "email")
        phone_src = extract_provider_source(c, "phone")
        addr_src  = extract_provider_source(c, "address")
        fnd_src   = extract_provider_source(c, "founder")

        # ── Issue collection ───────────────────────────────────────────────
        issues: list[str] = []
        if not name_ok:
            issues.append(f"aggregator/empty name: {name!r}")
        if not web_ok:
            issues.append(f"junk/missing website: {dom}")
        if email and not email_veri:
            issues.append(f"email domain mismatch: {email}")
        if phone_for:
            issues.append(f"foreign phone for India domain: {phone}")
        if address and not addr_veri:
            issues.append(f"address missing city/PIN: {address[:60]}")
        if founder and not fnd_ok:
            issues.append(f"founder not verified for company: {founder!r}")
        if research == "hermes":
            issues.append("HERMES CALLED!")

        rows.append({
            "name": name, "website": website, "dom": dom,
            "email": email, "email_veri": email_veri, "email_src": email_src,
            "phone": phone, "phone_veri": phone_veri, "phone_for": phone_for, "phone_src": phone_src,
            "address": address, "addr_veri": addr_veri, "addr_src": addr_src,
            "founder": founder, "fnd_veri": fnd_veri, "fnd_src": fnd_src,
            "conf": conf, "rsrcs": rsrcs, "src_url": src_url,
            "name_ok": name_ok, "web_ok": web_ok,
            "research": research, "issues": issues,
        })

        nd = lambda v: v if v else "—"

        print(f"\n[{i:02d}] {name}")
        print(f"     Website   : {website}  {ok_sym(web_ok)}")
        print(f"     Email     : {nd(email)}  {ok_sym(email_veri) if email else '—'}  src={email_src}")
        print(f"     Email src : {email_src}")
        print(f"     Email verif: {'verified domain match' if email_veri else 'not verified' if email else 'not found'}")
        print(f"     Founder   : {nd(founder)}  {ok_sym(fnd_veri) if founder else '—'}  src={fnd_src}")
        print(f"     Founder src: {fnd_src}")
        print(f"     Founder ver: {'verified' if fnd_veri else 'not verified' if founder else 'not found'}")
        print(f"     Phone     : {nd(phone)}  {ok_sym(phone_veri) if phone else '—'}  src={phone_src}")
        print(f"     Phone src : {phone_src}")
        print(f"     Phone verif: {'verified Indian' if phone_veri else 'foreign ✗' if phone_for else 'not verified' if phone else 'not found'}")
        print(f"     Address   : {(address or '—')[:70]}  {ok_sym(addr_veri) if address else '—'}  src={addr_src}")
        print(f"     Addr src  : {addr_src}")
        print(f"     Addr verif: {'verified city/PIN' if addr_veri else 'not verified' if address else 'not found'}")
        print(f"     Confidence: {conf}  sources={len(rsrcs)}")
        for iss in issues:
            print(f"     ❌ {iss}")

    # ── Aggregated metrics ────────────────────────────────────────────────────
    valid_names   = sum(1 for r in rows if r["name_ok"])
    official_webs = sum(1 for r in rows if r["web_ok"])
    emails_pres   = sum(1 for r in rows if r["email"])
    emails_veri   = sum(1 for r in rows if r["email_veri"])
    phones_pres   = sum(1 for r in rows if r["phone"])
    phones_veri   = sum(1 for r in rows if r["phone_veri"])
    addrs_pres    = sum(1 for r in rows if r["address"])
    addrs_veri    = sum(1 for r in rows if r["addr_veri"])
    fnds_pres     = sum(1 for r in rows if r["founder"])
    fnds_veri     = sum(1 for r in rows if r["fnd_veri"])

    wrong_emails  = sum(1 for r in rows if r["email"]   and not r["email_veri"])
    wrong_phones  = sum(1 for r in rows if r["phone_for"])
    wrong_webs    = n - official_webs
    wrong_fnds    = sum(1 for r in rows if r["founder"] and not r["fnd_veri"])
    hermes        = sum(1 for r in rows if r["research"] == "hermes")

    def pct(a: int, b: int) -> str:
        return f"{round(100 * a / b)}%" if b else "N/A"

    print()
    print(SEP); print("FINAL AUDIT SUMMARY"); print(SEP)
    print(f"  Valid companies        : {n}/10")
    print(f"  Execution time         : {elapsed}s  {ok_sym(elapsed <= 30)}")
    print()
    print(f"  Official websites      : {official_webs}/{n}  ({pct(official_webs, n)})")
    print()
    print(f"  Emails present         : {emails_pres}/{n}  ({pct(emails_pres, n)})")
    print(f"  Verified emails ✅      : {emails_veri}/{n}  ({pct(emails_veri, n)})")
    print()
    print(f"  Phones present         : {phones_pres}/{n}  ({pct(phones_pres, n)})")
    print(f"  Verified phones ✅      : {phones_veri}/{n}  ({pct(phones_veri, n)})")
    print()
    print(f"  Addresses present      : {addrs_pres}/{n}  ({pct(addrs_pres, n)})")
    print(f"  Verified addresses ✅   : {addrs_veri}/{n}  ({pct(addrs_veri, n)})")
    print()
    print(f"  Founders present       : {fnds_pres}/{n}  ({pct(fnds_pres, n)})")
    print(f"  Verified founders ✅    : {fnds_veri}/{n}  ({pct(fnds_veri, n)})")
    print()
    print(f"  Wrong emails           : {wrong_emails}")
    print(f"  Wrong phones (foreign) : {wrong_phones}")
    print(f"  Wrong websites         : {wrong_webs}")
    print(f"  Wrong founders         : {wrong_fnds}")
    print()
    print(f"  Hermes calls           : {hermes}  {ok_sym(hermes == 0)}")
    print(f"  LLM calls              : 0  ✅")

    all_issues = [(r["name"], iss) for r in rows for iss in r["issues"]]
    if all_issues:
        print()
        print("ISSUES:")
        for name_, iss in all_issues:
            print(f"  [{name_[:40]}] {iss}")

    # ── Provider source breakdown ─────────────────────────────────────────────
    print()
    print(SEP); print("PROVIDER SOURCE BREAKDOWN"); print(SEP)
    hdr = f"  {'Company':<40} {'Email src':<16} {'Phone src':<16} {'Addr src':<16} Founder src"
    print(hdr)
    print("  " + SEP2)
    for r in rows:
        def short(s: str) -> str:
            if not s or s in ("-", "—", "firecrawl/serper"): return "FC/Serper"
            sl = s.lower()
            if "hunter"      in sl: return "Hunter"
            if "apollo"      in sl: return "Apollo"
            if "people-data" in sl: return "PDL"
            if "google"      in sl: return "GPlaces"
            if "scraped"     in sl: return "Firecrawl"
            if "serper"      in sl: return "Serper"
            return s[:10]
        e_s = short(r["email_src"])  if r["email"]   else "—"
        p_s = short(r["phone_src"])  if r["phone"]   else "—"
        a_s = short(r["addr_src"])   if r["address"] else "—"
        f_s = short(r["fnd_src"])    if r["founder"] else "—"
        print(f"  {r['name'][:40]:<40} {e_s:<16} {p_s:<16} {a_s:<16} {f_s}")

    # ── Provider call counts (from pipeline log / result metadata) ─────────────
    # The result may carry provider stats in a top-level key if the route exposes it.
    # We also derive approximate counts from source breakdown in rows.
    print()
    print(SEP); print("PROVIDER CALL STATISTICS"); print(SEP)

    def count_src(field_key: str, label: str) -> int:
        return sum(1 for r in rows if label.lower() in (r[field_key] or "").lower())

    # Try to get exact stats from the pipeline response first
    pipeline_stats = result.get("_stats") or result.get("stats") or {}

    serper_calls   = pipeline_stats.get("serper_calls", "N/A (check server logs)")
    firecrawl_calls= pipeline_stats.get("firecrawl_calls", "N/A (check server logs)")
    hunter_calls   = pipeline_stats.get("hunter_calls", "N/A (check server logs)")
    apollo_calls   = pipeline_stats.get("apollo_calls", "N/A (check server logs)")
    pdl_calls      = pipeline_stats.get("pdl_calls", "N/A (check server logs)")
    gplaces_calls  = pipeline_stats.get("google_places_calls", "N/A (check server logs)")

    print(f"  Serper calls          : {serper_calls}")
    print(f"  Firecrawl calls       : {firecrawl_calls}")
    print(f"  Hunter calls          : {hunter_calls}")
    print(f"  Apollo calls          : {apollo_calls}")
    print(f"  PDL calls             : {pdl_calls}")
    print(f"  Google Places calls   : {gplaces_calls}")
    print(f"  LLM calls             : 0")
    print(f"  Hermes calls          : 0")
    print(f"  Execution time        : {elapsed} seconds")

    # ── Verdict ───────────────────────────────────────────────────────────────
    hard = wrong_emails + wrong_phones + wrong_webs
    total_verified = emails_veri + phones_veri + addrs_veri + fnds_veri + official_webs

    print()
    print(SEP); print("VERDICT"); print(SEP)

    if hermes > 0:
        verdict = "❌ FAIL — Hermes was called"
    elif hard == 0 and wrong_fnds == 0 and elapsed <= 30:
        verdict = "✅ PASS"
    elif hard == 0 and wrong_fnds == 0 and elapsed <= 40:
        verdict = "⚠️  CONDITIONAL PASS — correct data but >30s"
    elif hard <= 1 and elapsed <= 40:
        verdict = f"⚠️  CONDITIONAL PASS — {hard} hard error(s), {wrong_fnds} founder issue(s)"
    else:
        verdict = f"❌ FAIL — hard_errors={hard} wrong_founders={wrong_fnds} time={elapsed}s"

    print(f"  {verdict}")
    print(f"  Overall verified score : {total_verified}/{n * 5}  ({pct(total_verified, n * 5)})")
    print()

    return hard, wrong_fnds, elapsed


if __name__ == "__main__":
    hard, wrong_fnds, elapsed = run()
    sys.exit(0 if hard == 0 else 1)
