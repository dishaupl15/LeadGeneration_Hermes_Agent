#!/usr/bin/env python3
"""Quick smoke test for normalize_hermes_response."""
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from app.services.hermes_service import normalize_hermes_response

sample = '{"companies": [{"company_name": "Kolte Patil Developers", "industry": "Real Estate", "website": "https://koltepatil.com", "email": "info@koltepatil.com", "company_number": "+91 20 6764 5400", "founder_name": "Rajesh Patil", "founder_number": null, "address": "2nd Floor, Dhole Patil Road, Pune 411001", "city": "Pune", "state": "Maharashtra", "country": "India", "source_url": "https://koltepatil.com/contact", "sources": ["https://koltepatil.com/contact"], "confidence": 0.85}]}'

companies = normalize_hermes_response(sample)
print(f'Parsed {len(companies)} companies')
c = companies[0]
print(f'  company_name   : {c["company_name"]}')
print(f'  email          : {c["email"]}')
print(f'  company_number : {c["company_number"]}')
print(f'  founder_name   : {c["founder_name"]}')
print(f'  founder_number : {c["founder_number"]}')
print(f'  research_source: {c["research_source"]}')
print(f'  research_sources: {c["research_sources"]}')
print(f'  confidence     : {c["confidence"]}')
print()
# Test null/missing fields
sample2 = '{"companies": [{"company_name": "Test Co", "website": "", "email": null, "company_number": "n/a", "founder_number": "none"}]}'
companies2 = normalize_hermes_response(sample2)
c2 = companies2[0]
print(f'Null-handling test:')
print(f'  email          : {c2["email"]} (should be None)')
print(f'  company_number : {c2["company_number"]} (should be None)')
print(f'  founder_number : {c2["founder_number"]} (should be None)')
print('normalize_hermes_response: OK')
