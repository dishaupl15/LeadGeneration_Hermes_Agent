import urllib.request, urllib.error, json, time

url  = "http://localhost:8001/leads/generate-leads"
body = json.dumps({"industry": "Real Estate", "city": "Pune", "count": 5}).encode()
req  = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")

print("Sending Real Estate request to backend...")
start = time.time()
try:
    with urllib.request.urlopen(req, timeout=400) as r:
        elapsed = time.time() - start
        data = json.loads(r.read())
        print(f"SUCCESS in {elapsed:.1f}s — {data.get('total')} leads")
        for l in data.get("leads", []):
            print(f"  - {l.get('company_name')} | {l.get('website')}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
except Exception as e:
    print(f"ERROR: {e}")
