"""Find the session token from the running Hermes Desktop backend."""
import urllib.request, urllib.error, json, re

# Try /api/status to get info, then try /api/ws/ticket endpoint
for port in [63159, 56608]:
    print(f"\n--- Port {port} ---")
    
    # Get status (no auth needed)
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=3) as r:
            data = json.loads(r.read())
            print(f"  /api/status: {list(data.keys())[:5]}")
    except Exception as e:
        print(f"  /api/status: {e}")

    # Try endpoints that might expose token or allow unauthenticated access
    for path in ['/api/ws/ticket', '/api/pair', '/api/auth/local', '/api/login']:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=2) as r:
                body = r.read().decode()
                print(f"  {path}: {r.status} -> {body[:100]!r}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:80]
            print(f"  {path}: HTTP {e.code} -> {body!r}")
        except Exception as e:
            print(f"  {path}: {type(e).__name__}")

    # Try websocket with known patterns - check if loopback allows no token
    import asyncio, websockets
    async def try_ws_paths():
        for ws_path in ['/api/ws', '/ws', '/api/acp']:
            uri = f'ws://127.0.0.1:{port}{ws_path}'
            try:
                async with websockets.connect(uri, open_timeout=2, 
                    additional_headers={'Origin': 'http://localhost:9119'}) as ws:
                    print(f"  WS {ws_path}: CONNECTED!")
                    return port, ws_path
            except Exception as e:
                print(f"  WS {ws_path}: {type(e).__name__}: {str(e)[:60]}")
        return None, None
    
    asyncio.run(try_ws_paths())
