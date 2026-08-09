"""List available Hermes models and find free/low-cost options."""
import asyncio, json, os, uuid
from dotenv import load_dotenv
load_dotenv()

WS  = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
TOK = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")

async def get_models():
    from websockets.asyncio.client import connect as ws_connect
    url = WS + ("?token=" + TOK if TOK else "")
    async with ws_connect(url, open_timeout=10,
                          additional_headers={"Origin": "http://localhost:9119"}) as ws:
        rs = uuid.uuid4().hex
        rm = uuid.uuid4().hex
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
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": rm,
                        "method": "model.options",
                        "params": {"session_id": sid, "explicit_only": False}
                    }))
                elif fid == rm and res is not None:
                    providers = res.get("providers", [])
                    print(f"\nCurrent model: {res.get('current_model', '?')}")
                    print(f"Current provider: {res.get('current_provider', '?')}")
                    print("\nAll authenticated providers and models:")
                    for p in providers:
                        pname = p.get("name", "?")
                        slug  = p.get("slug", "?")
                        auth  = p.get("authenticated", False)
                        if not auth:
                            continue
                        models = p.get("models") or []
                        print(f"\n  Provider: {pname} ({slug}) auth={auth}")
                        for m in models[:10]:
                            if not isinstance(m, dict):
                                print(f"    model: {m}")
                                continue
                            mid   = m.get("id", "?")
                            mname = m.get("name", "?")
                            free  = m.get("is_free", False)
                            ctx   = m.get("context_length", "?")
                            print(f"    {'[FREE]' if free else '      '} {mid}  ctx={ctx}  ({mname})")
                    return True

        try:
            await asyncio.wait_for(read(), timeout=15)
        except asyncio.TimeoutError:
            print("timeout")

if __name__ == "__main__":
    asyncio.run(get_models())
