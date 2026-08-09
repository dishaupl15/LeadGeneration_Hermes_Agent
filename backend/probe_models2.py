import asyncio, json, os, uuid
from dotenv import load_dotenv
load_dotenv()
WS  = os.getenv('HERMES_WS_URL','ws://127.0.0.1:9119/api/ws')
TOK = os.getenv('HERMES_DASHBOARD_SESSION_TOKEN','')

async def run():
    from websockets.asyncio.client import connect as ws_connect
    url = WS + ('?token=' + TOK if TOK else '')
    async with ws_connect(url, open_timeout=10, additional_headers={'Origin':'http://localhost:9119'}) as ws:
        rs = uuid.uuid4().hex; rm = uuid.uuid4().hex; sid = None
        async def read():
            nonlocal sid
            async for raw in ws:
                f = json.loads(raw if isinstance(raw,str) else raw.decode())
                params = f.get('params') or {}; et = params.get('type','')
                res = f.get('result'); fid = f.get('id')
                if et == 'gateway.ready':
                    await ws.send(json.dumps({'jsonrpc':'2.0','id':rs,'method':'session.create','params':{}}))
                elif fid == rs and res:
                    sid = res.get('session_id')
                    await ws.send(json.dumps({'jsonrpc':'2.0','id':rm,'method':'model.options',
                        'params':{'session_id':sid,'explicit_only':False,'include_unconfigured':True}}))
                elif fid == rm and res:
                    for p in res.get('providers',[]):
                        slug = p.get('slug','?'); auth = p.get('authenticated',False)
                        if slug != 'openrouter': continue
                        for m in (p.get('models') or []):
                            if not isinstance(m,dict): 
                                mid = str(m)
                            else:
                                mid = m.get('id','?')
                            if any(x in mid for x in ['free','gemini','google','llama','mistral','deepseek','phi','qwen']):
                                print(mid)
                    return True
        try: await asyncio.wait_for(read(), timeout=15)
        except asyncio.TimeoutError: print('timeout')
asyncio.run(run())
