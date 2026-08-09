"""Quick credit/model probe — sends a tiny prompt to Hermes, reports back."""
import asyncio, json, os, uuid, sys
from dotenv import load_dotenv
load_dotenv()

WS  = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
TOK = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")

async def probe():
    from websockets.asyncio.client import connect as ws_connect
    url = WS + ("?token=" + TOK if TOK else "")
    print(f"Connecting to {WS} ...")
    async with ws_connect(url, open_timeout=10,
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
                    print("gateway.ready ✓")
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": rs,
                        "method": "session.create", "params": {}
                    }))
                elif fid == rs and res is not None:
                    sid = res.get("session_id")
                    print(f"session.create ✓  sid={sid}")
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": rp,
                        "method": "prompt.submit",
                        "params": {"session_id": sid,
                                   "text": "Reply with exactly one word: READY"}
                    }))
                elif fid == rp and res is not None:
                    print(f"prompt.submit ✓  ack={res}")
                elif et == "message.complete":
                    pl = params.get("payload") or {}
                    status = pl.get("status", "?")
                    text   = pl.get("text", "")
                    err    = pl.get("error", "")
                    print(f"message.complete  status={status!r}  text={text[:200]!r}")
                    if err:
                        print(f"ERROR: {err}")
                    return status == "complete"
                elif et == "error":
                    print(f"Hermes ERROR: {params}")
                    return False
                elif et in ("message.start", "message.delta",
                            "session.info", "sessions.changed",
                            "status.update"):
                    pass  # normal flow noise
                else:
                    print(f"  event: {et}")

        try:
            ok = await asyncio.wait_for(read(), timeout=45)
            print("\nCREDITS/MODEL:", "OK ✓" if ok else "FAIL ✗")
            return ok
        except asyncio.TimeoutError:
            print("\nTIMEOUT 45s — Hermes connected but no response yet")
            return None

if __name__ == "__main__":
    asyncio.run(probe())
