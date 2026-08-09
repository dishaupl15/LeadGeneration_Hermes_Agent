"""
test_hermes_direct.py
─────────────────────
Direct WebSocket diagnostic test for the Hermes Desktop Agent.

Usage:
    python test_hermes_direct.py

What it does:
1. Connects to ws://127.0.0.1:9119/api/ws with the correct JSON-RPC 2.0 protocol
2. Waits for the gateway.ready event
3. Creates a session via session.create RPC
4. Submits a simple research prompt via prompt.submit RPC
5. Prints EVERY incoming event with timestamps
6. Detects the final message.complete event and prints the research result
7. Exits with a clear PASS / FAIL
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

_WS_URL: str = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
_TOKEN:  str = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")
_TIMEOUT: float = float(os.getenv("HERMES_TIMEOUT", "600"))

SIMPLE_PROMPT = """Find 3 real estate companies in Pune, India.
For each company find:
- company name
- official website
- public business email
- public business phone number
- Pune address
- founder or leadership name
- source URLs

Use web research. Return results as JSON:
{
  "companies": [
    {
      "company_name": "...",
      "website": "...",
      "email": "...",
      "company_number": "...",
      "founder_name": "...",
      "address": "...",
      "city": "Pune",
      "country": "India",
      "source_url": "..."
    }
  ]
}"""


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}")


async def run_test() -> None:
    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:
        print("FAIL — websockets not installed: pip install websockets")
        return

    ws_url = _WS_URL
    if _TOKEN:
        sep = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{sep}token={_TOKEN}"

    log(f"[HERMES] Connecting to {_WS_URL} …")

    try:
        async with ws_connect(
            ws_url,
            open_timeout=30,
            ping_interval=60,
            ping_timeout=_TIMEOUT,
            close_timeout=30,
            additional_headers={"Origin": "http://localhost:9119"},
        ) as ws:
            log("[HERMES] WebSocket connected")

            gateway_ready = False
            session_id: str | None = None
            rpc_id_session = uuid.uuid4().hex
            rpc_id_prompt  = uuid.uuid4().hex
            session_created = False
            prompt_sent = False
            full_text_parts: list[str] = []
            start_time = asyncio.get_event_loop().time()

            async def _read() -> str | None:
                nonlocal gateway_ready, session_id, session_created, prompt_sent

                async for raw_frame in ws:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    raw = raw_frame if isinstance(raw_frame, str) else raw_frame.decode("utf-8", errors="replace")

                    # Parse
                    try:
                        frame = json.loads(raw)
                    except json.JSONDecodeError:
                        log(f"[HERMES] RAW (non-JSON, {len(raw)} chars): {raw[:200]!r}")
                        continue

                    frame_method = frame.get("method", "")
                    frame_id     = frame.get("id")
                    frame_result = frame.get("result")
                    frame_error  = frame.get("error")
                    params       = frame.get("params") or {}
                    event_type   = params.get("type", "")
                    payload      = params.get("payload") or {}

                    # ── JSON-RPC 2.0 response to our RPC calls ─────────────────
                    if frame_id is not None and frame_method == "":
                        if frame_error:
                            log(f"[HERMES] RPC ERROR id={frame_id}: {frame_error}")
                        elif frame_id == rpc_id_session and not session_created:
                            session_id = (frame_result or {}).get("session_id") or \
                                         (frame_result or {}).get("id")
                            log(f"[HERMES] session.create → session_id={session_id!r}")
                            session_created = True
                            # Now submit the prompt
                            prompt_msg = {
                                "jsonrpc": "2.0",
                                "id": rpc_id_prompt,
                                "method": "prompt.submit",
                                "params": {
                                    "session_id": session_id,
                                    "text": SIMPLE_PROMPT,
                                },
                            }
                            await ws.send(json.dumps(prompt_msg))
                            log(f"[HERMES] prompt.submit sent (session_id={session_id!r})")
                        elif frame_id == rpc_id_prompt and not prompt_sent:
                            log(f"[HERMES] prompt.submit → result={frame_result}")
                            prompt_sent = True
                        continue

                    # ── JSON-RPC 2.0 events ────────────────────────────────────
                    if frame_method != "event":
                        log(f"[HERMES] UNKNOWN FRAME method={frame_method!r} keys={list(frame.keys())}")
                        continue

                    # ── gateway.ready ──────────────────────────────────────────
                    if event_type == "gateway.ready":
                        log(f"[HERMES] gateway.ready received (skin={list(payload.keys())})")
                        gateway_ready = True
                        # Create a session
                        create_msg = {
                            "jsonrpc": "2.0",
                            "id": rpc_id_session,
                            "method": "session.create",
                            "params": {},
                        }
                        await ws.send(json.dumps(create_msg))
                        log("[HERMES] session.create sent")
                        continue

                    # ── streaming events ───────────────────────────────────────
                    if event_type == "message.start":
                        log("[HERMES] message.start — agent started responding")

                    elif event_type == "message.delta":
                        text_chunk = payload.get("text", "")
                        full_text_parts.append(text_chunk)
                        if len(full_text_parts) % 10 == 0:
                            log(f"[HERMES] message.delta — received {len(full_text_parts)} chunks so far ({sum(len(p) for p in full_text_parts)} chars)")

                    elif event_type == "message.interim":
                        text = payload.get("text", "")
                        log(f"[HERMES] message.interim — {text[:100]!r}")

                    elif event_type == "message.complete":
                        text = payload.get("text", "") or "".join(full_text_parts)
                        status = payload.get("status", "complete")
                        log(f"[HERMES] message.complete — status={status!r} text_length={len(text)} chars elapsed={elapsed:.1f}s")
                        if status == "error":
                            log(f"[HERMES] ERROR in response: {payload.get('error')}")
                            return None
                        return text

                    elif event_type == "tool.call":
                        tool_name = payload.get("name") or payload.get("tool") or "unknown"
                        log(f"[HERMES] tool.call — {tool_name!r}")

                    elif event_type == "tool.result":
                        log(f"[HERMES] tool.result — received")

                    elif event_type == "session.info":
                        log(f"[HERMES] session.info — model={payload.get('model','?')} running={payload.get('running','?')}")

                    elif event_type in ("reasoning.delta", "thinking.delta"):
                        pass  # skip noisy streaming tokens

                    elif event_type == "error":
                        log(f"[HERMES] ERROR event: {payload}")
                        return None

                    else:
                        log(f"[HERMES] EVENT type={event_type!r} payload_keys={list(payload.keys() if isinstance(payload, dict) else [])}")

                    # Progress heartbeat
                    if elapsed > 0 and int(elapsed) % 60 == 0 and int(elapsed) > 0:
                        log(f"[HERMES] Still waiting — elapsed: {elapsed:.0f}s")

                return None  # connection closed without a result

            try:
                result = await asyncio.wait_for(_read(), timeout=_TIMEOUT)
            except asyncio.TimeoutError:
                log(f"[HERMES] TIMEOUT after {_TIMEOUT:.0f}s — no message.complete received")
                print("\n=== RESULT: FAIL — Hermes timed out ===")
                return

            if result is None:
                print("\n=== RESULT: FAIL — No response from Hermes ===")
                return

            log(f"\n[HERMES] Full response ({len(result)} chars):")
            print(result[:2000])
            print("\n=== RESULT: PASS — Hermes responded successfully ===")

    except ConnectionRefusedError:
        print(f"FAIL — Connection refused at {_WS_URL}. Is Hermes running?")
    except Exception as exc:
        print(f"FAIL — {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(run_test())
