"""
Static + runtime integration checks.
Run from backend/ directory:
    venv\Scripts\python.exe run_checks.py
"""
import sys, os, asyncio, json, time, urllib.request, urllib.error
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv('.env')

BACKEND = 'http://localhost:8001'
PASS = 'PASS'
FAIL = 'FAIL'
results = {}

# ── 1. Hermes port check ──────────────────────────────────────────────────────
import socket
def port_open(host, port, timeout=3):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except:
        return False

hermes_port = port_open('127.0.0.1', 9119)
results['Hermes running (port 9119)'] = PASS if hermes_port else FAIL
print(f"[1] Hermes port 9119 open: {hermes_port}")

# ── 2. WebSocket connection test ──────────────────────────────────────────────
from app.services.hermes_service import test_hermes_connection, HermesUnavailableError
ws_result = asyncio.run(test_hermes_connection())
results['WebSocket connection'] = PASS if ws_result['connected'] else FAIL
print(f"[2] WebSocket connected: {ws_result['connected']}  error: {ws_result['error']}")

# ── 3. Static bypass check of hermes_service.py ──────────────────────────────
from pathlib import Path
svc = Path('app/services/hermes_service.py').read_text(encoding='utf-8')

has_subprocess       = 'subprocess.run' in svc or 'create_subprocess' in svc
has_serper_direct    = 'SERPER_API_KEY' in svc and 'search_companies' in svc
has_firecrawl_direct = 'FIRECRAWL_API_KEY' in svc and 'scrape_company' in svc
has_leadgen_import   = ('import leadgen' in svc or '_get_leadgen()' in svc or
                        'run_pipeline' in svc)
has_error_class      = 'HermesUnavailableError' in svc
raises_error         = 'raise HermesUnavailableError' in svc
has_ws_connect       = 'ws_connect' in svc or 'websockets' in svc

results['Direct Serper bypass']   = FAIL if has_serper_direct    else PASS
results['Direct Firecrawl bypass'] = FAIL if has_firecrawl_direct else PASS
results['Silent fallback (subprocess)'] = FAIL if has_subprocess       else PASS
results['Silent fallback (leadgen)']    = FAIL if has_leadgen_import    else PASS
results['HermesUnavailableError exists'] = PASS if has_error_class     else FAIL
results['HermesUnavailableError raised'] = PASS if raises_error        else FAIL
results['WebSocket client in service']   = PASS if has_ws_connect      else FAIL

print(f"[3] Static hermes_service.py checks:")
print(f"    subprocess.run / create_subprocess : {has_subprocess}")
print(f"    Direct Serper (SERPER_API_KEY+search_companies) : {has_serper_direct}")
print(f"    Direct Firecrawl (FIRECRAWL_API_KEY+scrape_company): {has_firecrawl_direct}")
print(f"    leadgen import/run_pipeline         : {has_leadgen_import}")
print(f"    HermesUnavailableError class        : {has_error_class}")
print(f"    raise HermesUnavailableError        : {raises_error}")
print(f"    WebSocket client (ws_connect)       : {has_ws_connect}")

# ── 4. Backend health ─────────────────────────────────────────────────────────
try:
    with urllib.request.urlopen(f'{BACKEND}/health', timeout=5) as r:
        health = json.loads(r.read())
        results['Backend running'] = PASS
        print(f"[4] Backend health: {health}")
except Exception as e:
    results['Backend running'] = FAIL
    print(f"[4] Backend health FAIL: {e}")

# ── 5. Test 502 when Hermes down (skip if Hermes is down already) ─────────────
# We will test this only by calling with a tiny timeout on the WS side
# without actually stopping Hermes — we test it via direct call_hermes_agent
print(f"[5] 502 behavior test: direct HermesUnavailableError when WS refused ...")
import asyncio
from app.services.hermes_service import _connect_and_send, _WS_URL
# Temporarily patch WS URL to a closed port to test error path
import app.services.hermes_service as _svc
_orig_url = _svc._WS_URL
_svc._WS_URL = 'ws://127.0.0.1:19999/api/ws'  # definitely closed
t0 = time.time()
try:
    asyncio.run(_connect_and_send('test'))
    results['502 on Hermes down'] = FAIL
    print(f"    FAIL: No error raised")
except HermesUnavailableError as e:
    elapsed = time.time() - t0
    results['502 on Hermes down'] = PASS
    print(f"    PASS: HermesUnavailableError in {elapsed:.1f}s: {str(e)[:80]}")
except Exception as e:
    results['502 on Hermes down'] = FAIL
    print(f"    FAIL: Wrong exception {type(e).__name__}: {e}")
finally:
    _svc._WS_URL = _orig_url

# ── 6. Real Hermes connection + tiny probe ────────────────────────────────────
print(f"[6] Real Hermes connection probe ...")
if hermes_port and ws_result['connected']:
    results['Hermes WebSocket probe'] = PASS
    print(f"    PASS: connected to {_WS_URL}")
else:
    results['Hermes WebSocket probe'] = FAIL
    print(f"    FAIL: {ws_result['error']}")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 55)
print("STATIC + CONNECTIVITY RESULTS")
print("=" * 55)
for k, v in results.items():
    marker = "OK" if v == PASS else "!!"
    print(f"  [{marker}] {k:<40} {v}")
print("=" * 55)
