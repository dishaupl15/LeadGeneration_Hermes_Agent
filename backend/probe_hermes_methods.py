"""
Discover valid JSON-RPC methods on the Hermes WebSocket gateway.
Run: venv\Scripts\python.exe probe_hermes_methods.py
"""
import asyncio, json, sys, os
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv('.env')

WS_URL = os.getenv('HERMES_WS_URL', 'ws://127.0.0.1:9119/api/ws')
TOKEN  = os.getenv('HERMES_DASHBOARD_SESSION_TOKEN', '')

async def probe():
    from websockets.asyncio.client import connect as ws_connect

    url = WS_URL
    if TOKEN:
        sep = '&' if '?' in url else '?'
        url = f"{url}{sep}token={TOKEN}"

    async with ws_connect(url, open_timeout=10,
                          additional_headers={'Origin': 'http://localhost:9119'}) as ws:
        print("Connected!")

        # Drain welcome frame
        try:
            async with asyncio.timeout(3):
                raw = await ws.recv()
                welcome = json.loads(raw)
                print(f"Gateway ready. Skin: {welcome.get('params',{}).get('payload',{}).get('skin',{}).get('name')}")
        except asyncio.TimeoutError:
            pass

        # Try candidate method names for running a prompt
        candidate_methods = [
            # Standard ACP methods
            ("acp.run",           {"prompt": "Say: HELLO", "stream": False}),
            ("acp.prompt",        {"prompt": "Say: HELLO", "stream": False}),
            ("agent.run",         {"prompt": "Say: HELLO"}),
            ("agent.prompt",      {"prompt": "Say: HELLO"}),
            ("chat",              {"prompt": "Say: HELLO", "stream": False}),
            ("chat.send",         {"message": "Say: HELLO", "stream": False}),
            ("run",               {"prompt": "Say: HELLO", "stream": False}),
            ("prompt",            {"text": "Say: HELLO", "stream": False}),
            ("hermes.run",        {"prompt": "Say: HELLO"}),
            ("session.run",       {"prompt": "Say: HELLO"}),
            ("session.prompt",    {"prompt": "Say: HELLO", "stream": False}),
            ("execute",           {"prompt": "Say: HELLO"}),
            ("task.run",          {"prompt": "Say: HELLO"}),
            # Gateway-level introspection
            ("rpc.discover",      {}),
            ("system.listMethods",{}),
            ("methods",           {}),
            ("help",              {}),
        ]

        for method, params in candidate_methods:
            msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1})
            print(f"\n  -> {method} ...")
            await ws.send(msg)
            try:
                async with asyncio.timeout(8):
                    raw = await ws.recv()
                    resp = json.loads(raw)
                    err = resp.get('error', {})
                    result = resp.get('result')
                    if err:
                        code = err.get('code')
                        emsg = err.get('message','')
                        print(f"     ERR {code}: {emsg}")
                        if code != -32601:  # -32601 = unknown method; anything else is interesting
                            print(f"     *** INTERESTING: method exists but error: {emsg}")
                    elif result is not None:
                        print(f"     SUCCESS! result = {json.dumps(result)[:200]}")
                        # Keep reading — may stream more frames
                        for _ in range(5):
                            try:
                                async with asyncio.timeout(5):
                                    extra = await ws.recv()
                                    eparsed = json.loads(extra)
                                    print(f"     stream frame: {json.dumps(eparsed)[:200]}")
                            except asyncio.TimeoutError:
                                break
                        return method, params
            except asyncio.TimeoutError:
                print(f"     TIMEOUT — may be streaming/pending")

        return None, None

asyncio.run(probe())
