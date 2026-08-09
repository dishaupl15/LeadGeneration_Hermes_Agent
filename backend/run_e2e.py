"""
Real end-to-end test: API -> hermes_service -> Hermes WS -> research -> pipeline -> MongoDB -> response
Run from backend/:
    venv\Scripts\python.exe run_e2e.py
"""
import sys, json, time, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8')

BACKEND  = 'http://localhost:8001'
PAYLOAD  = {"industry": "Real Estate", "city": "Pune", "count": 3}
TIMEOUT  = 400  # seconds — Hermes needs time to research

def fmt(val):
    if val is None or val == '' or val == [] or val == {}:
        return 'NOT PUBLICLY AVAILABLE'
    if isinstance(val, list):
        return ', '.join(str(v) for v in val) if val else 'NOT PUBLICLY AVAILABLE'
    return str(val).strip() or 'NOT PUBLICLY AVAILABLE'

print("=" * 60)
print("END-TO-END TEST: React/API -> Hermes -> Pipeline -> MongoDB")
print("=" * 60)
print(f"Payload : {json.dumps(PAYLOAD)}")
print(f"Backend : {BACKEND}/leads/generate-leads")
print(f"Timeout : {TIMEOUT}s")
print()
print("Waiting for Hermes to perform research ...")
print("(Backend logs will show the full execution path)")
print()

body = json.dumps(PAYLOAD).encode()
req  = urllib.request.Request(
    f'{BACKEND}/leads/generate-leads',
    data=body,
    headers={'Content-Type': 'application/json'},
    method='POST',
)

t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        elapsed = time.time() - t0
        data = json.loads(r.read().decode('utf-8'))

        print(f"HTTP status     : {r.status}")
        print(f"Time taken      : {elapsed:.1f}s")
        print(f"success         : {data.get('success')}")
        print(f"total leads     : {data.get('total')}")
        print(f"inserted        : {data.get('inserted')}")
        print(f"updated         : {data.get('updated')}")
        print(f"query           : {data.get('query')}")
        print()

        leads = data.get('leads', [])
        hermes_leads = [l for l in leads if l.get('research_source') == 'hermes']
        print(f"Leads tagged research_source=hermes : {len(hermes_leads)}/{len(leads)}")
        print()

        for i, lead in enumerate(leads, 1):
            print(f"--- Company {i} ---")
            print(f"  Company Name  : {fmt(lead.get('company_name'))}")
            print(f"  Website       : {fmt(lead.get('website'))}")
            print(f"  Email         : {fmt(lead.get('email') or lead.get('emails'))}")
            print(f"  Company Phone : {fmt(lead.get('company_number') or lead.get('phones'))}")
            print(f"  Founder       : {fmt(lead.get('founder_name'))}")
            print(f"  Founder Phone : {fmt(lead.get('founder_number'))}")
            print(f"  Address       : {fmt(lead.get('address'))}")
            print(f"  City          : {fmt(lead.get('city'))}")
            print(f"  State         : {fmt(lead.get('state'))}")
            print(f"  Country       : {fmt(lead.get('country'))}")
            print(f"  Source URL    : {fmt(lead.get('source_url'))}")
            print(f"  Research Via  : {fmt(lead.get('research_source'))}")
            print(f"  Sources       : {fmt(lead.get('research_sources') or lead.get('sources'))}")
            print(f"  Confidence    : {lead.get('confidence', 0.0):.2f}")
            print(f"  Last Verified : {fmt(lead.get('last_verified'))}")
            print()

        # Verify checks
        ok_200          = r.status == 200
        ok_success      = data.get('success') is True
        ok_list         = isinstance(leads, list)
        ok_nonempty     = len(leads) > 0
        ok_hermes_tag   = len(hermes_leads) > 0
        ok_no_fake      = all(
            l.get('founder_number') is None or str(l.get('founder_number','')).strip().lower() not in ('n/a','none','not available','')
            for l in leads
        )

        print("=" * 60)
        print("VERIFICATION RESULTS")
        print("=" * 60)

        checks = [
            ("HTTP 200",              ok_200),
            ("success=true",          ok_success),
            ("leads is list",         ok_list),
            ("leads not empty",       ok_nonempty),
            ("research_source=hermes",ok_hermes_tag),
            ("no fabricated values",  ok_no_fake),
        ]
        all_pass = True
        for name, ok in checks:
            status = 'PASS' if ok else 'FAIL'
            if not ok:
                all_pass = False
            print(f"  {name:<35} {status}")

        print()
        if all_pass:
            print("END-TO-END: PASS")
        else:
            print("END-TO-END: FAIL — check failures above")

except urllib.error.HTTPError as e:
    elapsed = time.time() - t0
    body_text = e.read().decode('utf-8', errors='replace')
    print(f"HTTP Error {e.code} after {elapsed:.1f}s")
    print(body_text[:2000])
    if e.code == 502:
        print()
        print("=> Hermes is unavailable. Backend correctly returned 502.")
        print("   Start Hermes with: $env:HERMES_DASHBOARD_SESSION_TOKEN='mytoken123'; hermes serve --skip-build")
    print()
    print("END-TO-END: FAIL")

except Exception as e:
    elapsed = time.time() - t0
    print(f"Error after {elapsed:.1f}s: {type(e).__name__}: {e}")
    print()
    print("END-TO-END: FAIL")
