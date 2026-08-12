"""Quick PDL key check + live auth test. Run: python check_pdl_key.py"""
import asyncio
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND, ".env"), override=True, encoding="utf-8-sig")

key = os.getenv("PDL_API_KEY", "").strip()

print("=" * 55)
print("PDL KEY CHECK")
print("=" * 55)
print(f"PDL_CONFIGURED : {bool(key)}")
print(f"PDL_KEY_LENGTH : {len(key)}")
print(f"KEY_IS_ASCII   : {key.isascii() if key else 'N/A'}")
print(f"KEY_START      : {key[:6] if key else '(empty)'}")
print(f"KEY_END        : {key[-4:] if key else '(empty)'}")
print()

if not key:
    print("STOP: PDL_API_KEY is empty. Update backend/.env and rerun.")
    sys.exit(1)

import httpx

async def test_auth():
    url = "https://api.peopledatalabs.com/v5/person/search"
    payload = {
        "query": {"bool": {"must": [{"term": {"job_company_website": "peopledatalabs.com"}}]}},
        "size": 1,
        "pretty": False,
    }
    headers = {
        "X-Api-Key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    print("Sending live PDL test request (size=1) ...")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
        except Exception as exc:
            print(f"PDL_HTTP_STATUS    : ERROR ({type(exc).__name__}: {exc})")
            print("PDL_AUTHENTICATION : FAILED")
            return

    print(f"PDL_HTTP_STATUS    : {r.status_code}")

    if r.status_code == 200:
        body = r.json()
        total   = body.get("total", 0)
        records = len(body.get("data") or [])
        print(f"PDL_TOTAL_MATCHED  : {total}")
        print(f"PDL_RECORDS_BACK   : {records}")
        print("PDL_AUTHENTICATION : SUCCESS")
    elif r.status_code == 401:
        print("PDL_AUTHENTICATION : FAILED")
        print()
        print("STOP: The PDL key is rejected by the PDL API.")
        print("This is an API credential problem, NOT a code problem.")
        print("Go to https://dashboard.peopledatalabs.com/api-keys")
        print("Copy the ACTIVE key and paste it into backend/.env as:")
        print("PDL_API_KEY=<paste_key_here_no_quotes>")
        print()
        print(f"PDL error: {r.text[:200]}")
    else:
        print(f"PDL_AUTHENTICATION : UNEXPECTED ({r.status_code})")
        print(r.text[:200])

asyncio.run(test_auth())
