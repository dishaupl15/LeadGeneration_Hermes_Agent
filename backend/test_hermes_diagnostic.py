"""
test_hermes_diagnostic.py
─────────────────────────
Minimal Hermes end-to-end diagnostic.
Uses the same JSON-RPC 2.0 protocol as hermes_service.py.
Does NOT call /leads/generate-leads or any backend pipeline.

Sends a small 2-company prompt, waits up to 180s for message.complete.
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

WS_URL  = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
TOKEN   = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")
TIMEOUT = 180  # seconds

PROMPT = """\
Name 2 real manufacturing companies in Pune, India from your knowledge or a quick web search.
Return ONLY this JSON, no other text:
{"companies": [{"company_name": "Bajaj Auto","official_website": "https://www.bajajauto.com","public_business_email": null,"public_business_phone": null,"full_address": "Akurdi, Pune 411035","city": "Pune","founder_or_ceo": "Rajiv Bajaj"},{"company_name": "","official_website": "","public_business_email": null,"public_business_phone": null,"full_address": "","city": "Pune","founder_or_ceo": null}]}
Replace ALL values with real data for 2 Pune manufacturing companies.\
"""


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}", flush=True)


async def run_diagnostic() -> int:
    """Returns 0 on success, 1 on failure."""

    results = {
        "connection":  "FAIL",
        "json_rpc":    "FAIL",
        "prompt_exec": "FAIL",
        "research":    "FAIL",
        "json_resp":   "FAIL",
        "elapsed":     0,
        "error":       None,
    }

    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:
        log("ERROR: websockets not installed — pip install websockets")
        _print_verdict(results)
        return 1

    ws_url = WS_URL
    if TOKEN:
        sep = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{sep}token={TOKEN}"

    log(f"Connecting to {WS_URL} ...")
    t_start = asyncio.get_event_loop().time()

    try:
        async with ws_connect(
            ws_url,
            open_timeout=15,
            ping_interval=60,
            ping_timeout=TIMEOUT,
            close_timeout=10,
            additional_headers={"Origin": "http://localhost:9119"},
        ) as ws:
            results["connection"] = "PASS"
            log("WebSocket connected")

            rpc_id_session = uuid.uuid4().hex
            rpc_id_prompt  = uuid.uuid4().hex
            session_id     = None
            session_done   = False
            prompt_acked   = False
            delta_count    = 0
            delta_chars    = 0
            full_text      = ""
            last_hb        = 0.0

            async def _read() -> dict | None:
                nonlocal session_id, session_done, prompt_acked
                nonlocal delta_count, delta_chars, full_text, last_hb

                async for raw in ws:
                    elapsed = asyncio.get_event_loop().time() - t_start

                    # Heartbeat every 30s
                    if elapsed - last_hb >= 30:
                        last_hb = elapsed
                        log(f"Still waiting — elapsed {elapsed:.0f}s ...")

                    raw_str = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
                    try:
                        frame = json.loads(raw_str)
                    except json.JSONDecodeError:
                        log(f"Non-JSON frame ({len(raw_str)} chars): {raw_str[:80]!r}")
                        continue

                    frame_id     = frame.get("id")
                    frame_method = frame.get("method", "")
                    frame_result = frame.get("result")
                    frame_error  = frame.get("error")
                    params       = frame.get("params") or {}
                    event_type   = params.get("type", "")
                    payload      = params.get("payload") or {}

                    # ── RPC responses ─────────────────────────────────────────
                    if frame_id is not None and frame_method == "":
                        if frame_error:
                            log(f"RPC ERROR id={frame_id}: {frame_error}")
                            results["error"] = f"RPC error: {frame_error}"
                            return None

                        if frame_id == rpc_id_session and not session_done:
                            session_id = (frame_result or {}).get("session_id")
                            session_done = True
                            results["json_rpc"] = "PASS"
                            log(f"session.create OK — session_id={session_id!r}")
                            # Submit the research prompt
                            await ws.send(json.dumps({
                                "jsonrpc": "2.0",
                                "id":      rpc_id_prompt,
                                "method":  "prompt.submit",
                                "params":  {
                                    "session_id": session_id,
                                    "text":       PROMPT,
                                },
                            }))
                            log("prompt.submit sent")

                        elif frame_id == rpc_id_prompt and not prompt_acked:
                            prompt_acked = True
                            results["prompt_exec"] = "PASS"
                            log(f"prompt.submit ack — status={frame_result!r}")
                        continue

                    # ── Events ────────────────────────────────────────────────
                    if frame_method != "event":
                        log(f"Unknown frame method={frame_method!r}")
                        continue

                    if event_type == "gateway.ready":
                        log("gateway.ready received")
                        # Create session
                        await ws.send(json.dumps({
                            "jsonrpc": "2.0",
                            "id":      rpc_id_session,
                            "method":  "session.create",
                            "params":  {},
                        }))
                        log("session.create sent")

                    elif event_type == "message.start":
                        log("message.start — Hermes started responding")
                        results["research"] = "STARTED"

                    elif event_type == "message.delta":
                        chunk = payload.get("text", "")
                        if chunk:
                            full_text += chunk
                            delta_count += 1
                            delta_chars += len(chunk)
                            if delta_count == 1:
                                log(f"message.delta — first chunk received")

                    elif event_type == "message.interim":
                        text = payload.get("text", "")
                        log(f"message.interim — {text[:80]!r}")

                    elif event_type == "message.complete":
                        status   = payload.get("status", "?")
                        response = payload.get("text", "") or full_text
                        err_msg  = payload.get("error", "")
                        elapsed  = asyncio.get_event_loop().time() - t_start
                        results["elapsed"] = round(elapsed, 1)

                        log(f"message.complete — status={status!r} "
                            f"length={len(response)} chars elapsed={elapsed:.1f}s")

                        if status == "error" or err_msg:
                            results["error"] = err_msg or "unknown agent error"
                            log(f"AGENT ERROR: {results['error']}")
                            return None

                        results["research"] = "PASS"
                        return {"text": response, "status": status}

                    elif event_type == "error":
                        msg = payload.get("message", str(payload))
                        results["error"] = f"Hermes error event: {msg}"
                        log(f"ERROR event: {msg}")
                        return None

                    elif event_type in ("session.info", "sessions.changed",
                                        "status.update", "message.stop",
                                        "reasoning.delta", "thinking.delta",
                                        "reasoning.available", "tool.generating",
                                        "tool.complete", "tool.start", "tool.end"):
                        # Expected background events — log tool activity only
                        if event_type in ("tool.generating", "tool.complete"):
                            tool_name = payload.get("name", payload.get("tool_id", "?"))
                            log(f"  tool activity: {event_type} — {tool_name}")

                    elif event_type == "approval.request":
                        # Hermes is asking for tool approval — auto-approve
                        req_id = payload.get("request_id") or payload.get("id") or ""
                        tool   = payload.get("tool_name") or payload.get("tool") or "?"
                        log(f"  approval.request for tool={tool!r} — auto-approving")
                        approve_id = uuid.uuid4().hex
                        await ws.send(json.dumps({
                            "jsonrpc": "2.0",
                            "id":      approve_id,
                            "method":  "approval.respond",
                            "params":  {
                                "session_id": session_id,
                                "request_id": req_id,
                                "choice":     "allow",
                            },
                        }))
                    else:
                        log(f"  unknown event: {event_type!r}")

                return None  # connection closed

            # ── Run with timeout ──────────────────────────────────────────────
            try:
                resp = await asyncio.wait_for(_read(), timeout=TIMEOUT)
            except asyncio.TimeoutError:
                elapsed = asyncio.get_event_loop().time() - t_start
                results["elapsed"] = round(elapsed, 1)
                results["error"] = (
                    f"Timeout after {TIMEOUT}s — "
                    f"research={'started' if results['research']=='STARTED' else 'not started'}, "
                    f"deltas={delta_count}, chars={delta_chars}"
                )
                log(f"TIMEOUT after {TIMEOUT}s")
                _print_verdict(results)
                return 1

            if resp is None:
                _print_verdict(results)
                return 1

            # ── Validate JSON response ────────────────────────────────────────
            response_text = resp["text"]
            log(f"\n{'='*60}")
            log(f"RAW RESPONSE ({len(response_text)} chars):")
            print(response_text[:3000])
            if len(response_text) > 3000:
                print(f"... [truncated, full length {len(response_text)}]")
            log(f"{'='*60}\n")

            # Parse JSON
            parsed = None
            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown fences or surrounding text
                import re
                m = re.search(r'\{.*\}', response_text, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except json.JSONDecodeError:
                        pass

            if parsed is None:
                results["error"] = "Response is not valid JSON"
                log("VALIDATION FAIL: not valid JSON")
                _print_verdict(results)
                return 1

            companies = parsed.get("companies", [])
            log(f"JSON parsed OK — companies found: {len(companies)}")

            issues = []
            placeholders = {"", "null", "none", "n/a", "na", "unknown", "string", "..."}

            for i, c in enumerate(companies, 1):
                name    = str(c.get("company_name") or "").strip()
                website = str(c.get("official_website") or "").strip()
                city    = str(c.get("city") or "").strip()

                if not name or name.lower() in placeholders:
                    issues.append(f"Company {i}: missing/placeholder company_name ({name!r})")
                if not website or website.lower() in placeholders:
                    issues.append(f"Company {i}: missing/placeholder official_website ({website!r})")

                log(f"  Company {i}: {name!r} | {website!r} | email={c.get('public_business_email')!r}"
                    f" | phone={c.get('public_business_phone')!r}"
                    f" | city={city!r} | founder={c.get('founder_or_ceo')!r}")

            if len(companies) != 2:
                issues.append(f"Expected 2 companies, got {len(companies)}")

            if issues:
                results["error"] = "; ".join(issues)
                log(f"VALIDATION ISSUES: {results['error']}")
            else:
                results["json_resp"] = "PASS"
                log("JSON validation PASS — 2 valid companies returned")

            _print_verdict(results)
            return 0 if results["json_resp"] == "PASS" else 1

    except ConnectionRefusedError:
        results["error"] = f"Connection refused at {WS_URL} — is Hermes running?"
        log(results["error"])
        _print_verdict(results)
        return 1
    except Exception as exc:
        results["error"] = f"{type(exc).__name__}: {exc}"
        log(f"UNEXPECTED ERROR: {results['error']}")
        _print_verdict(results)
        return 1


def _print_verdict(r: dict) -> None:
    research_pass = r["research"] in ("PASS", "STARTED")
    print("\n" + "=" * 60)
    print("HERMES DIAGNOSTIC VERDICT")
    print("=" * 60)
    print(f"  HERMES CONNECTION   : {r['connection']}")
    print(f"  JSON-RPC PROTOCOL   : {r['json_rpc']}")
    print(f"  PROMPT EXECUTION    : {r['prompt_exec']}")
    print(f"  RESEARCH COMPLETED  : {r['research']}")
    print(f"  JSON RESPONSE       : {r['json_resp']}")
    print(f"  TOTAL TIME          : {r['elapsed']}s")
    if r["error"]:
        print(f"\n  FAILURE REASON      : {r['error']}")
    print("=" * 60)
    if r["json_resp"] == "PASS":
        print("  FINAL VERDICT: Hermes is working correctly ✓")
    else:
        print("  FINAL VERDICT: Hermes is still failing ✗")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    exit_code = asyncio.run(run_diagnostic())
    sys.exit(exit_code)
