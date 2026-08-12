import os
from dotenv import load_dotenv
import httpx

load_dotenv()
key = os.getenv('COMPANYENRICH_API_KEY', '').strip()
print('KEY_SET', bool(key))
print('KEY_PREVIEW', key[:10] + '...' if key else '<none>')
urls = [
    ('companies_search', 'https://api.companyenrich.com/v1/companies/search'),
    ('search_companies', 'https://api.companyenrich.com/v1/search/companies'),
    ('companies_enrich', 'https://api.companyenrich.com/v1/companies/enrich'),
    ('people_search', 'https://api.companyenrich.com/v1/people/search'),
    ('search_people', 'https://api.companyenrich.com/v1/search/people'),
]
for name, url in urls:
    try:
        print('\nPROBING', name, url)
        with httpx.Client(timeout=10) as c:
            resp = c.post(
                url,
                headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                json={'query': 'Pharma in Pune', 'page': 1, 'pageSize': 1},
                timeout=10
            )
            print('STATUS', resp.status_code)
            try:
                print('TEXT', resp.text[:400])
            except Exception as exc:
                print('TEXT ERROR', exc)
    except Exception as exc:
        print('ERROR', type(exc).__name__, exc)
