"""
Probe the Hermes WebSocket to understand its protocol.
Run: venv\Scripts\python.exe probe_hermes_ws.py
"""
import asyncio, json, sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv('.env')

WS_URL = os.getenv('HERMES_WS_URL', 'ws://127.0.0.1:9119/api/ws')
TOKEN  = os.getenv('HERMES_DASHBOARD_SESSION_TOKEN', '')

async def probe():
    from websockets.asyncio.client import connect as ws_connect

    # Build URL with token
    url = WS_URL
    if TOKEN:
        sep = '&' if '?' in url else '?'
        url = f"{url}{sep}token={TOKEN}"

    print(f"Connecting to: {WS_URL} (token=[hidden])")

    async with ws_connect(
        url,
        open_timeout=10,
        additional_headers={'Origin': 'http://localhost:9119'},
    ) as ws:
        print("Connected!")

        # Step 1: just listen for any unsolicited welcome frame first
        print("\n--- Listening for welcome frame (5s) ---")
        try:
            async with asyncio.timeout(5):
                raw = await ws.recv()
                print(f"Welcome frame received ({len(raw)} chars):")
                try:
                    parsed = json.loads(raw)
                    print(json.dumps(parsed, indent=2)[:800])
                except:
                    print(repr(raw[:400]))
        except asyncio.TimeoutError:
            print("No welcome frame in 5s — server waits for client to speak first")

        # Step 2: try various message formats and see what the server does
        test_messages = [
            # Format A: chat message (standard Hermes ACP)
            {"type": "chat", "content": "Hello, are you there? Reply with: yes", "stream": False},
            # Format B: message type
            {"type": "message", "content": "Hello, are you there? Reply with: yes"},
            # Format C: prompt
            {"type": "prompt", "text": "Hello, are you there? Reply with: yes"},
            # Format D: raw string
            "Hello, are you there? Reply with: yes",
            # Format E: ACP protocol init
            {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1},
        ]

        for i, msg in enumerate(test_messages, 1):
            print(f"\n--- Test message {i}: {type(msg).__name__} ---")
            if isinstance(msg, dict):
                payload = json.dumps(msg)
                print(f"Sending: {payload[:100]}")
            else:
                payload = msg
                print(f"Sending: {repr(payload[:100])}")

            await ws.send(payload)

            # Wait up to 10s for any response
            try:
                async with asyncio.timeout(10):
                    raw = await ws.recv()
                    print(f"Response ({len(raw)} chars):")
                    try:
                        parsed = json.loads(raw)
                        print(json.dumps(parsed, indent=2)[:600])
                        # If we got a useful response, stop here
                        if parsed.get('type') or parsed.get('content') or parsed.get('result'):
                            print(f"\n=> Format {i} works! type={parsed.get('type')} content={str(parsed.get('content',''))[:50]}")
                            break
                    except:
                        print(repr(raw[:400]))
                        if raw.strip():
                            print(f"\n=> Format {i} works (raw text)!")
                            break
            except asyncio.TimeoutError:
                print(f"No response in 10s for format {i}")
            except Exception as e:
                print(f"Error: {type(e).__name__}: {e}")
                break

asyncio.run(probe())
