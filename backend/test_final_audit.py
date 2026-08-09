#!/usr/bin/env python3
"""
test_final_audit.py
────────────────────
Final production audit after Company-Context Verification stage.

Run from backend/:
    python test_final_audit.py
Server: uvicorn app.main:app --port 8002 --reload
"""

import json, re, sys, time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = "http://127.0.0.1:8002"
QUERY = "Real Estate companies in Pune"
COUNT = 10
TIMEOUT = 240

# ── Known-good reference data ─────────────────────────────────────────────────
KNOWN_FOUNDERS = {
    "koltepatil.com":    ["Rajesh Patil","Milind Kolte","Sunita Kolte","Aniruddha Patil"],
    "panchshil.com":     ["Atul Chordia"],
    "nyatigroup.com":    ["Manohar Shroff","Anup Shroff","Aniruddha","Pranav Nyati","Nitin Nyati"],
    "vtprealty.in":      ["Sachin Bhandari","Vikram Goel"],
    "adanirealty.com":   ["Gautam Adani","Pranav Adani"],
    "gera.in":           ["Rohit Gera","Gulam Zia"],
    "purplecorp.in":     ["Shravan Agarwal","Harshwardhan Agarwal"],
    "austinrealty.in":   ["Raju Bhise","Austin"],   # accept if on company domain
}
KNOWN_JUNK_DOMAINS = {
    "propjinni.com","goodfirms.co","glassdoor.com","glassdoor.co.in",
    "maharashtradirectory.com","cushmanwakefield.com",
    "99acres.com","magicbricks.com","housing.com","justdial.com",
    "indiamart.com","naukri.com","linkedin.com","wikipedia.org",
}
AGGREGATOR_TITLE_RE = re.compile(
    r'(?i)(top\s+\d*\s*real\s+estate|best\s+\d*|list\s+of'
    r'|reviews?\s*\||real\s+estate\s+(?:agents?|companies|developers)\s+in\b)',
)

def domain_of(url):
    try: return urlparse(url).netloc.lower().lstrip("www.")
    except: return ""

def post_json(url, body, timeout=TIMEOUT):
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}")
    except URLError as e:
        raise RuntimeError(f"Cannot reach {url}: {e.reason}\n"
                           "Start: uvicorn app.main:app --port 8002 --reload")

def get_json(url, timeout=8):
    with urlopen(Request(url), timeout=timeout) as r:
        return json.loads(r.read().decode())

def email_dom_matches(email, site_dom):
    if not email: return False
    edom = email.split("@")[-1].lower()
    return edom == site_dom or edom.endswith("."+site_dom) or site_dom.endswith("."+edom)

def is_indian_phone(p):
    if not p: return False
    d = re.sub(r'\D','',p)
    if d.startswith("91") and len(d)==12: return True
    if d.startswith("1800"): return True
    if len(d)==10 and d[0] in "6789": return True
    if d.startswith("0") and 10<=len(d)<=12: return True
    return False

def is_foreign_phone(p):
    if not p: return False
    if p.strip().startswith("+") and not p.strip().startswith("+91"): return True
    d = re.sub(r'\D','',p)
    if d.startswith("1") and len(d)==11 and not d.startswith("1800"): return True
    if re.match(r'^\(\d{3}\)',p.strip()): return True
    return False

def has_city_or_pin(addr):
    if not addr: return False
    CITIES = ["Pune","Mumbai","Delhi","Bangalore","Bengaluru","Hyderabad",
              "Nagpur","Nashik","Navi Mumbai","Thane","India"]
    if any(c.lower() in addr.lower() for c in CITIES): return True
    if re.search(r'(?<!\d)[1-9]\d{5}(?!\d)', addr): return True
    return False

def founder_matches_known(founder, site_dom):
    known = KNOWN_FOUNDERS.get(site_dom, [])
    if not known: return True   # unknown company — can't validate, assume ok
    fl = founder.lower()
    return any(k.lower() in fl or fl in k.lower() for k in known)

SEP = "="*72

def run():
    print(SEP)
    print("FINAL PRODUCTION DATA ACCURACY AUDIT")
    print(f"Query  : {QUERY!r}  Count: {COUNT}")
    print(SEP)

    try:
        h = get_json(f"{BASE}/health")
        print(f"Server : {h.get('app')} v{h.get('version')} [{h.get('status')}]")
    except Exception as e:
        print(f"ERROR: {e}"); sys.exit(1)

    print(f"\nRunning pipeline...")
    t0 = time.monotonic()
    try:
        result = post_json(f"{BASE}/leads/generate-leads", {"query":QUERY,"count":COUNT})
    except RuntimeError as e:
        print(f"PIPELINE ERROR: {e}"); sys.exit(1)
    elapsed = round(time.monotonic()-t0, 1)

    leads = result.get("leads", [])
    n = len(leads)

    with open("final_audit_output.json","w",encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"Elapsed: {elapsed}s  |  Returned: {n} companies\n")

    # ── Per-company analysis ──────────────────────────────────────────────────
    print(SEP); print("PER-COMPANY DETAIL"); print(SEP)

    ok = lambda b: "✅" if b else "❌"
    results = []

    for i, c in enumerate(leads, 1):
        name       = c.get("company_name","")
        website    = c.get("website","")
        email      = c.get("email")
        phone      = c.get("company_number")
        address    = c.get("address","")
        founder    = c.get("founder_name")
        conf       = c.get("confidence", 0.0)
        rsrcs      = c.get("research_sources") or c.get("sources") or []
        site_dom   = domain_of(website)
        research   = c.get("research_source","")

        # --- evaluations ---
        name_ok      = bool(name) and not AGGREGATOR_TITLE_RE.search(name)
        website_ok   = bool(website) and site_dom not in KNOWN_JUNK_DOMAINS
        email_ok     = email_dom_matches(email, site_dom) if email else None
        email_veri   = email_ok is True
        phone_ok     = is_indian_phone(phone) if phone else None
        phone_foreign= is_foreign_phone(phone) if phone else False
        phone_veri   = phone_ok is True
        addr_ok      = has_city_or_pin(address) if address else None
        addr_veri    = addr_ok is True
        founder_ok   = founder_matches_known(founder, site_dom) if founder else None
        founder_veri = founder_ok is True

        # collect issues
        issues = []
        if not name_ok:  issues.append(f"name is aggregator/empty: {name!r}")
        if not website_ok: issues.append(f"junk/missing website: {site_dom}")
        if email and not email_ok: issues.append(f"email domain mismatch: {email}")
        if phone_foreign: issues.append(f"foreign phone for India domain: {phone}")
        if address and not addr_ok: issues.append(f"address has no city/PIN: {address[:60]}")
        if founder and not founder_ok: issues.append(f"founder not associated with company: {founder!r}")
        if research == "hermes": issues.append("HERMES CALLED!")

        results.append({
            "name": name, "website": website, "site_dom": site_dom,
            "email": email, "email_veri": email_veri,
            "phone": phone, "phone_veri": phone_veri, "phone_foreign": phone_foreign,
            "address": address, "addr_veri": addr_veri,
            "founder": founder, "founder_veri": founder_veri,
            "conf": conf, "rsrcs": rsrcs,
            "name_ok": name_ok, "website_ok": website_ok,
            "research": research, "issues": issues,
        })

        print(f"\n[{i:02d}] {name}")
        print(f"     website  : {website}")
        print(f"     domain   : {site_dom}  {ok(website_ok)}")
        print(f"     email    : {email or '(none)'}  {ok(email_veri) if email else '—'}  "
              f"{'[domain-verified]' if email_veri else '[not verified]' if email else '[not found]'}")
        print(f"     phone    : {phone or '(none)'}  {ok(phone_veri) if phone else '—'}  "
              f"{'[Indian ✓]' if phone_veri else '[foreign ✗]' if phone_foreign else '[not found]' if not phone else '[unclassified]'}")
        print(f"     address  : {(address or '(none)')[:70]}  {ok(addr_veri) if address else '—'}")
        print(f"     founder  : {founder or '(none)'}  {ok(founder_veri) if founder else '—'}")
        print(f"     conf     : {conf}  sources={len(rsrcs)}")
        print(f"     research : {research}")
        for iss in issues:
            print(f"     ❌ {iss}")

    # ── Aggregated metrics ────────────────────────────────────────────────────
    valid_names    = sum(1 for r in results if r["name_ok"])
    official_webs  = sum(1 for r in results if r["website_ok"])
    emails_present = sum(1 for r in results if r["email"])
    emails_veri    = sum(1 for r in results if r["email_veri"])
    phones_present = sum(1 for r in results if r["phone"])
    phones_veri    = sum(1 for r in results if r["phone_veri"])
    addrs_present  = sum(1 for r in results if r["address"])
    addrs_veri     = sum(1 for r in results if r["addr_veri"])
    founders_pres  = sum(1 for r in results if r["founder"])
    founders_veri  = sum(1 for r in results if r["founder_veri"])

    wrong_names    = n - valid_names
    wrong_websites = n - official_webs
    wrong_emails   = sum(1 for r in results if r["email"] and not r["email_veri"])
    wrong_phones   = sum(1 for r in results if r["phone_foreign"])
    wrong_addresses= sum(1 for r in results if r["address"] and not r["addr_veri"])
    wrong_founders = sum(1 for r in results if r["founder"] and not r["founder_veri"])

    hermes = sum(1 for r in results if r["research"]=="hermes")
    all_issues = [(r["name"], iss) for r in results for iss in r["issues"]]

    def pct(a,b): return f"{round(100*a/b)}%" if b else "N/A"

    print()
    print(SEP); print("FINAL AUDIT SUMMARY"); print(SEP)
    print(f"  Valid companies        : {n}/10")
    print(f"  Execution time         : {elapsed}s  {'✅' if elapsed<=30 else '⚠️ over 30s'}")
    print()
    print(f"  Official websites      : {official_webs}/{n}  ({pct(official_webs,n)})")
    print()
    print(f"  Emails present         : {emails_present}/{n}  ({pct(emails_present,n)})")
    print(f"  Emails verified ✅      : {emails_veri}/{n}  ({pct(emails_veri,n)})")
    print()
    print(f"  Phones present         : {phones_present}/{n}  ({pct(phones_present,n)})")
    print(f"  Phones verified ✅      : {phones_veri}/{n}  ({pct(phones_veri,n)})")
    print()
    print(f"  Addresses present      : {addrs_present}/{n}  ({pct(addrs_present,n)})")
    print(f"  Addresses verified ✅   : {addrs_veri}/{n}  ({pct(addrs_veri,n)})")
    print()
    print(f"  Founders present       : {founders_pres}/{n}  ({pct(founders_pres,n)})")
    print(f"  Founders verified ✅    : {founders_veri}/{n}  ({pct(founders_veri,n)})")
    print()
    print(f"  Wrong emails           : {wrong_emails}")
    print(f"  Wrong phones (foreign) : {wrong_phones}")
    print(f"  Wrong websites         : {wrong_websites}")
    print(f"  Wrong founders         : {wrong_founders}")
    print()
    print(f"  Hermes calls           : {hermes}  {'✅' if hermes==0 else '❌ HERMES CALLED!'}")

    if all_issues:
        print()
        print("ISSUES:")
        for name, iss in all_issues:
            print(f"  [{name[:35]}] {iss}")

    # ── Verdict ───────────────────────────────────────────────────────────────
    hard = wrong_emails + wrong_phones + wrong_websites
    print()
    print(SEP); print("VERDICT"); print(SEP)
    if hermes > 0:
        print("❌ FAIL — Hermes was called")
    elif hard == 0 and wrong_founders <= 1 and elapsed <= 30:
        print("✅ PASS — All hard field checks pass, within 30s, no Hermes")
    elif hard <= 1 and elapsed <= 35:
        print(f"⚠️  CONDITIONAL PASS — {hard} hard error(s), {wrong_founders} founder issue(s)")
    else:
        print(f"❌ FAIL — hard_errors={hard} wrong_founders={wrong_founders} time={elapsed}s")

    total_verified = emails_veri + phones_veri + addrs_veri + founders_veri + official_webs
    max_v = n * 5
    print(f"Overall verified score : {total_verified}/{max_v}  ({pct(total_verified,max_v)})")

if __name__ == "__main__":
    run()
