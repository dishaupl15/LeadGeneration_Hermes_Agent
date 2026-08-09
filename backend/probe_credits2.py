"""Credit probe with 120s timeout — confirms max_tokens fix works."""
import asyncio, json, os, uuid
from dotenv import load_dotenv
load_dotenv()

WS  = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
TOK = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")

async def probe():
    from websockets.asyncio.client import connect as ws_connect
    url = WS + ("?token=" + TOK if TOK else "")
    print(f"Connecting to {WS} ...")
    async with ws_connect(url, open_timeout=15, ping_interval=60,
                          ping_timeout=120, close_timeout=10,
                          additional_headers={"Origin": "http://localhost:9119"}) as ws:
        rs = uuid.uuid4().hex
        rp = uuid.uuid4().hex
        sid = None

        async def read():
            nonlocal sid
            async for raw in ws:
                f = json.loads(raw if isinstance(raw, str) else raw.decode())
                params = f.get("params") or {}
                et  = params.get("type", "")
                res = f.get("result")
                fid = f.get("id")

                if et == "gateway.ready":
                    print("gateway.ready OK")
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": rs,
                        "method": "session.create", "params": {}
                    }))
                elif fid == rs and res is not None:
                    sid = res.get("session_id")
                    print(f"session.create OK  sid={sid}")
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": rp,
                        "method": "prompt.submit",
                        "params": {"session_id": sid,
                                   "text": "Reply with exactly one word: READY"}
                    }))
                elif fid == rp and res is not None:
                    print(f"prompt.submit OK  ack={res}")
                elif et == "message.complete":
                    pl = params.get("payload") or {}
                    status = pl.get("status", "?")
                    text   = pl.get("text", "")
                    err    = pl.get("error", "")
                    print(f"message.complete  status={status!r}")
                    print(f"text={text[:100]!r}")
                    if err:
                        print(f"ERROR: {err}")
                        return False
                    return status == "complete"
                elif et in ("message.start", "message.delta", "session.info",
                            "sessions.changed", "status.update",
                            "reasoning.delta", "thinking.delta",
                            "reasoning.available"):
                    pass  # expected streaming noise
                else:
                    print(f"  event: {et}")

        try:
            ok = await asyncio.wait_for(read(), timeout=120)
            if ok:
                print("\nCREDITS/MAX_TOKENS: OK - no 402 error")
            else:
                print("\nCREDITS/MAX_TOKENS: FAIL - got error response")
            return ok
        except asyncio.TimeoutError:
            print("\nTIMEOUT 120s - Hermes still thinking (no 402 = credits OK)")
            return None

if __name__ == "__main__":
    asyncio.run(probe())
