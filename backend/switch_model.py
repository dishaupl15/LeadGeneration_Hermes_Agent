"""Switch Hermes to a free model via /model slash command."""
import asyncio, json, os, uuid
from dotenv import load_dotenv
load_dotenv()

WS  = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
TOK = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")

FREE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

async def switch_model():
    from websockets.asyncio.client import connect as ws_connect
    url = WS + ("?token=" + TOK if TOK else "")
    print(f"Switching Hermes to model: {FREE_MODEL}")
    async with ws_connect(url, open_timeout=10,
                          additional_headers={"Origin": "http://localhost:9119"}) as ws:
        rs = uuid.uuid4().hex
        rc = uuid.uuid4().hex
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
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": rs,
                        "method": "session.create", "params": {}
                    }))
                elif fid == rs and res is not None:
                    sid = res.get("session_id")
                    cmd = "/model " + FREE_MODEL
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": rc,
                        "method": "prompt.submit",
                        "params": {"session_id": sid, "text": cmd}
                    }))
                    print("Sent: " + cmd)
                elif fid == rc and res is not None:
                    print("Ack: " + str(res))
                elif et == "message.complete":
                    pl = params.get("payload") or {}
                    text = pl.get("text", "")
                    status = pl.get("status", "?")
                    print("Status: " + status)
                    print("Result: " + text[:300])
                    return True
                elif et in ("message.start", "message.delta", "session.info",
                            "sessions.changed", "status.update", "reasoning.delta",
                            "thinking.delta", "reasoning.available"):
                    pass
                else:
                    print("  event: " + et)

        try:
            r = await asyncio.wait_for(read(), timeout=20)
            print("Done" if r else "Incomplete")
        except asyncio.TimeoutError:
            print("Timeout")

if __name__ == "__main__":
    asyncio.run(switch_model())
