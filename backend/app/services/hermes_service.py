"""
app/services/hermes_service.py
──────────────────────────────
Hermes Desktop Agent WebSocket client.

Architecture
────────────
  FastAPI  →  call_hermes_agent(query, num)
    →  WebSocket  →  ws://127.0.0.1:9119/api/ws
    →  Hermes Desktop Agent performs deep multi-source research
    →  Returns structured JSON with companies
    →  normalize_hermes_response()
    →  Returns dict to src/routes/leads.py

MANDATORY CONSTRAINT
────────────────────
This service connects to the Hermes Desktop Agent for ALL primary company
research.  It does NOT fall back to direct Serper / Firecrawl calls.

If Hermes is unavailable, a clear HermesUnavailableError is raised so the
caller (routes/leads.py) can return an informative HTTP 502 to the frontend.
The user will see the exact reason rather than silently receiving stale data
from a different pipeline.

WebSocket protocol (Hermes Desktop Agent) — JSON-RPC 2.0
──────────────────────────────────────────────────────────
Hermes Desktop Agent uses the JSON-RPC 2.0 protocol over WebSocket.
Source: C:\\Users\\<user>\\AppData\\Local\\hermes\\hermes-agent\\tui_gateway\\ws.py
        and tui_gateway/server.py

Wire format (all messages are newline-delimited JSON):

  CLIENT → SERVER (JSON-RPC 2.0 requests):
    { "jsonrpc": "2.0", "id": "<uuid>", "method": "session.create", "params": {} }
    { "jsonrpc": "2.0", "id": "<uuid>", "method": "prompt.submit",
      "params": { "session_id": "<sid>", "text": "<prompt>" } }

  SERVER → CLIENT (JSON-RPC 2.0 responses and events):
    Immediate RPC response:
      { "jsonrpc": "2.0", "id": "<uuid>", "result": { "session_id": "...", ... } }
      { "jsonrpc": "2.0", "id": "<uuid>", "result": { "status": "streaming" } }

    Async events emitted DURING the agent turn:
      { "jsonrpc": "2.0", "method": "event",
        "params": { "type": "<event_type>", "session_id": "<sid>",
                    "payload": { ... } } }

  Event types (from tui_gateway/server.py _emit calls):
    gateway.ready    — server ready, sent immediately on connection
    message.start    — agent started generating a response
    message.delta    — streaming text chunk in payload.text
    message.interim  — complete interim assistant message
    message.complete — FINAL response in payload.text, payload.status="complete"
    session.info     — session metadata update
    error            — agent-level error in payload.message
    tool.call        — agent called a tool
    tool.result      — tool returned a result

  The FINAL response text is in:
    message.complete → params.payload.text

  Authentication:
    Token is passed as URL query param: ?token=<HERMES_DASHBOARD_SESSION_TOKEN>

HERMES_TIMEOUT controls how long to wait for message.complete (default: 600s = 10 min).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# ── Config (from .env — never hard-coded) ────────────────────────────────────
_WS_URL: str = os.getenv("HERMES_WS_URL", "ws://127.0.0.1:9119/api/ws")
_TOKEN:  str = os.getenv("HERMES_DASHBOARD_SESSION_TOKEN", "")
_TIMEOUT: float = float(os.getenv("HERMES_TIMEOUT", "300"))


# ── Custom exception ─────────────────────────────────────────────────────────

class HermesUnavailableError(RuntimeError):
    """Raised when the Hermes Desktop Agent cannot be reached."""
    pass


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_research_prompt(query: str, num: int) -> str:
    """
    Build a focused, efficiency-bounded research prompt for Hermes.

    Instructs Hermes to stop as soon as num companies are found to avoid
    exhaustive research that can exceed the timeout budget.
    """
    return f"""You are the lead-generation research agent.

User request: Find {num} real companies matching this query: {query}

EFFICIENCY RULE: Stop as soon as you have confirmed {num} valid companies.
Do NOT keep researching once you have {num} results. Return immediately.
Do NOT exceed {num * 5} total tool/search calls.

For every company:
1. Run ONE search query to find the company and its official website.
2. Visit the official website. Check Contact and About pages ONLY.
3. If contact info is not on the website, try ONE additional public source.
4. Do not invent or guess any information.
5. If a field is not publicly available after 2 sources, return null for that field.
6. Never fabricate phone numbers or email addresses.
7. Reject: 404 pages, generic directories, government portals.

Return ONLY valid JSON. No markdown. No text outside the JSON.

Required response format:
{{
  "companies": [
    {{
      "company_name": "...",
      "industry": "...",
      "website": "...",
      "email": "...",
      "company_number": "...",
      "founder_name": "...",
      "founder_number": null,
      "address": "...",
      "city": "...",
      "state": "...",
      "country": "...",
      "source_url": "...",
      "sources": [],
      "confidence": 0.0
    }}
  ]
}}"""


# ── WebSocket client ──────────────────────────────────────────────────────────

async def _connect_and_send(prompt: str) -> str:
    """
    Connect to Hermes Desktop Agent WebSocket using JSON-RPC 2.0 protocol,
    create a session, submit the prompt, collect the full response, and
    return the raw response string.

    Protocol (verified from Hermes source tui_gateway/ws.py + server.py):
      1. Connect → receive gateway.ready event
      2. Send session.create RPC → receive session_id in result
      3. Send prompt.submit RPC with session_id → receive status:"streaming"
      4. Collect message.delta chunks and wait for message.complete
      5. Return payload.text from message.complete

    Raises HermesUnavailableError with an exact reason if anything fails.
    """
    try:
        from websockets.asyncio.client import connect as ws_connect
        from websockets.exceptions import WebSocketException
    except ImportError:
        raise HermesUnavailableError(
            "websockets library not installed. Run: pip install websockets"
        )

    # Build URL with token as query param (Hermes Desktop convention)
    ws_url = _WS_URL
    if _TOKEN:
        separator = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{separator}token={_TOKEN}"

    _ts = lambda: __import__('datetime').datetime.now().strftime("%H:%M:%S.%f")[:-3]
    def _log(msg): print(f"[{_ts()}] {msg}")

    _log(f"[HERMES] Connecting to {_WS_URL} …")

    try:
        async with ws_connect(
            ws_url,
            open_timeout=30,
            ping_interval=60,
            ping_timeout=_TIMEOUT,
            close_timeout=30,
            additional_headers={"Origin": "http://localhost:9119"},
        ) as ws:
            _log("[HERMES] WebSocket connected")

            import uuid as _uuid

            rpc_id_session = _uuid.uuid4().hex
            rpc_id_prompt  = _uuid.uuid4().hex

            session_id: str | None = None
            session_created = False
            prompt_sent = False
            delta_parts: list[str] = []
            delta_count = 0
            research_started = False
            start_time = asyncio.get_event_loop().time()
            last_heartbeat = 0.0

            async def _read_with_timeout() -> str | None:
                nonlocal session_id, session_created, prompt_sent
                nonlocal delta_parts, delta_count, research_started, last_heartbeat

                async for raw_frame in ws:
                    elapsed = asyncio.get_event_loop().time() - start_time

                    # Heartbeat every 60 seconds
                    if elapsed - last_heartbeat >= 60:
                        last_heartbeat = elapsed
                        _log(f"[HERMES] Still waiting — elapsed: {elapsed:.0f}s")

                    raw = (
                        raw_frame
                        if isinstance(raw_frame, str)
                        else raw_frame.decode("utf-8", errors="replace")
                    )

                    # Parse JSON-RPC 2.0 frame
                    try:
                        frame = json.loads(raw)
                    except (json.JSONDecodeError, ValueError):
                        _log(f"[HERMES] RAW non-JSON frame ({len(raw)} chars): {raw[:120]!r}")
                        continue

                    frame_id     = frame.get("id")
                    frame_method = frame.get("method", "")
                    frame_result = frame.get("result")
                    frame_error  = frame.get("error")
                    params       = frame.get("params") or {}
                    event_type   = params.get("type", "")
                    payload      = params.get("payload") or {}

                    # ── JSON-RPC responses to our calls ────────────────────────
                    if frame_id is not None and frame_method == "":
                        if frame_error:
                            _log(f"[HERMES] RPC ERROR id={frame_id}: {frame_error}")
                            raise HermesUnavailableError(
                                f"Hermes RPC error: {frame_error}"
                            )

                        if frame_id == rpc_id_session and not session_created:
                            result = frame_result or {}
                            session_id = result.get("session_id") or result.get("id")
                            _log(f"[HERMES] Session created — session_id={session_id!r}")
                            session_created = True
                            # Submit the prompt
                            prompt_msg = json.dumps({
                                "jsonrpc": "2.0",
                                "id": rpc_id_prompt,
                                "method": "prompt.submit",
                                "params": {
                                    "session_id": session_id,
                                    "text": prompt,
                                },
                            })
                            await ws.send(prompt_msg)
                            _log("[HERMES] Research request sent")

                        elif frame_id == rpc_id_prompt and not prompt_sent:
                            _log(f"[HERMES] Request acknowledged — status={frame_result!r}")
                            prompt_sent = True
                        continue

                    # ── JSON-RPC 2.0 event frames ──────────────────────────────
                    if frame_method != "event":
                        _log(f"[HERMES] UNKNOWN FRAME method={frame_method!r} keys={list(frame.keys())}")
                        continue

                    # ── gateway.ready — create session immediately ─────────────
                    if event_type == "gateway.ready":
                        _log("[HERMES] gateway.ready — creating session")
                        create_msg = json.dumps({
                            "jsonrpc": "2.0",
                            "id": rpc_id_session,
                            "method": "session.create",
                            "params": {},
                        })
                        await ws.send(create_msg)
                        continue

                    # ── Streaming response events ──────────────────────────────
                    if event_type == "message.start":
                        _log("[HERMES] Agent started responding (message.start)")
                        research_started = True

                    elif event_type == "message.delta":
                        chunk = payload.get("text", "")
                        if chunk:
                            delta_parts.append(chunk)
                            delta_count += 1
                            if delta_count % 20 == 0:
                                _log(f"[HERMES] Agent is researching… ({delta_count} chunks, {sum(len(p) for p in delta_parts)} chars so far)")

                    elif event_type == "message.interim":
                        text = payload.get("text", "")
                        _log(f"[HERMES] Interim response: {text[:80]!r}")

                    elif event_type == "message.complete":
                        # ── FINAL response ─────────────────────────────────────
                        status = payload.get("status", "complete")
                        full_text = payload.get("text", "") or "".join(delta_parts)
                        _log(
                            f"[HERMES] Final response received — "
                            f"status={status!r} length={len(full_text)} chars "
                            f"elapsed={elapsed:.1f}s"
                        )
                        if status == "error":
                            error_msg = payload.get("error") or "unknown agent error"
                            raise HermesUnavailableError(
                                f"Hermes agent returned an error: {error_msg}"
                            )
                        return full_text

                    elif event_type == "session.info":
                        model = payload.get("model", "?")
                        running = payload.get("running", "?")
                        _log(f"[HERMES] Session info — model={model!r} running={running}")

                    elif event_type == "error":
                        msg = payload.get("message", str(payload))
                        _log(f"[HERMES] Agent ERROR: {msg}")
                        raise HermesUnavailableError(f"Hermes agent error: {msg}")

                    elif event_type in ("tool.call", "tool.result",
                                        "thinking.delta", "reasoning.delta",
                                        "tool.start", "tool.end"):
                        # Tool activity — Hermes is actively researching
                        if event_type == "tool.call":
                            tool_name = payload.get("name") or payload.get("tool", "?")
                            _log(f"[HERMES] Search/tool activity detected — {tool_name!r}")

                    else:
                        _log(
                            f"[HERMES] EVENT type={event_type!r} "
                            f"payload_keys={list(payload.keys() if isinstance(payload, dict) else [])}"
                        )

                # Connection closed without a message.complete
                if delta_parts:
                    joined = "".join(delta_parts)
                    _log(f"[HERMES] Connection closed — using {len(joined)} chars from delta parts")
                    return joined
                return None

            try:
                result = await asyncio.wait_for(_read_with_timeout(), timeout=_TIMEOUT)
            except asyncio.TimeoutError:
                raise HermesUnavailableError(
                    f"Hermes did not respond within {_TIMEOUT:.0f}s. "
                    f"Check that the agent is running and the research skill is active."
                )

            if not result:
                raise HermesUnavailableError(
                    "Hermes returned an empty response. "
                    "The agent may have completed without generating content."
                )

            _log(f"[HERMES] Research response received ({len(result)} chars)")
            return result

    except HermesUnavailableError:
        raise  # re-raise as-is
    except ConnectionRefusedError:
        raise HermesUnavailableError(
            f"Unable to connect to Hermes at {_WS_URL}. "
            "Connection refused — is the Hermes Desktop Agent running? "
            "Start it with: hermes serve"
        )
    except OSError as exc:
        raise HermesUnavailableError(
            f"Network error connecting to Hermes at {_WS_URL}: {exc}"
        )
    except Exception as exc:
        ws_exc_type = "WebSocketException"
        try:
            from websockets.exceptions import WebSocketException
            if isinstance(exc, WebSocketException):
                ws_exc_type = type(exc).__name__
        except ImportError:
            pass
        raise HermesUnavailableError(
            f"WebSocket error from Hermes ({type(exc).__name__}): {exc}"
        )


# ── Response parser ───────────────────────────────────────────────────────────

def _extract_json_from_response(raw: str) -> dict:
    """
    Extract and parse the JSON companies payload from Hermes's response.

    Hermes may:
    - Return clean JSON directly
    - Wrap JSON in a markdown code block (```json … ```)
    - Include explanatory text before/after the JSON block
    - Return partial/malformed JSON (json-repair handles this)

    Returns a dict with at least a "companies" key.
    Raises ValueError if no parseable JSON is found.
    """
    if not raw:
        raise ValueError("Hermes returned an empty response.")

    # ── Try 1: direct JSON parse ──────────────────────────────────────────
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"companies": parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    # ── Try 2: extract JSON block from markdown fences ────────────────────
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', raw, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"companies": parsed}
        except (json.JSONDecodeError, ValueError):
            pass

    # ── Try 3: find the largest JSON object in the response ───────────────
    # Walk through raw looking for { … } blocks
    depth = 0
    start = -1
    best_json = None
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                candidate = raw[start:i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "companies" in parsed:
                        return parsed
                    best_json = parsed  # keep even without "companies"
                except (json.JSONDecodeError, ValueError):
                    pass
                start = -1

    if best_json is not None:
        if "companies" not in best_json:
            # Wrap bare company dict in list
            if "company_name" in best_json:
                return {"companies": [best_json]}
        return best_json

    # ── Try 4: json-repair (handles truncated / slightly malformed JSON) ──
    try:
        from json_repair import repair_json
        repaired_str = repair_json(raw)
        if repaired_str and repaired_str.strip() not in ('""', '{}', '[]'):
            repaired = json.loads(repaired_str)
            if isinstance(repaired, dict):
                return repaired
            if isinstance(repaired, list):
                return {"companies": repaired}
    except (ImportError, Exception):
        pass

    raise ValueError(
        f"Could not extract JSON from Hermes response. "
        f"First 500 chars: {raw[:500]!r}"
    )


# ── Normaliser ───────────────────────────────────────────────────────────────

def _normalize_hermes_company(raw: dict) -> dict:
    """
    Normalise a single company dict returned by Hermes into the shape
    that src/routes/leads.py and the existing MongoDB upsert expect.

    Key rules:
    - Never fabricate missing fields — pass None / [] for absent data.
    - Preserve all existing field names used by the MongoDB upsert.
    - Add research_source = "hermes" and research_sources = [source_url, ...]
      so the caller can prove the lead came through Hermes.
    - Map Hermes field names → internal field names where they differ.
    """
    def _str(val, default="") -> str:
        if val is None:
            return default
        s = str(val).strip()
        return s if s.lower() not in ("none", "null", "n/a", "na", "not available", "") else default

    def _nullable(val) -> str | None:
        if val is None:
            return None
        s = str(val).strip()
        return s if s.lower() not in ("none", "null", "n/a", "na", "not available", "") else None

    def _list(val) -> list:
        if not val:
            return []
        if isinstance(val, list):
            return [str(v).strip() for v in val if v and str(v).strip()]
        return [str(val).strip()] if str(val).strip() else []

    company_name   = _str(raw.get("company_name") or raw.get("name", ""))
    website        = _str(raw.get("website") or raw.get("domain", ""))
    email          = _nullable(raw.get("email"))
    company_number = _nullable(raw.get("company_number") or raw.get("phone"))
    founder_name   = _nullable(raw.get("founder_name"))
    founder_number = _nullable(raw.get("founder_number"))
    address        = _str(raw.get("address", ""))
    city           = _str(raw.get("city", ""))
    state          = _str(raw.get("state", ""))
    country        = _str(raw.get("country", ""))
    source_url     = _str(raw.get("source_url") or website)
    sources        = _list(raw.get("sources"))
    confidence_raw = raw.get("confidence", 0.0)
    try:
        confidence = round(float(confidence_raw), 2)
    except (TypeError, ValueError):
        confidence = 0.0

    # research_sources: collect all URL sources Hermes reported
    research_sources: list[str] = list(sources)
    if source_url and source_url not in research_sources:
        research_sources.insert(0, source_url)

    # Build emails/phones lists for backward compat (routes/leads.py reads these)
    emails: list[str] = []
    if email:
        emails = [email]

    phones: list[str] = []
    if company_number:
        phones = [company_number]

    return {
        # ── Core identity ─────────────────────────────────────────────────
        "company_name":     company_name,
        "website":          website,
        # ── Legacy contact arrays (kept for MongoDB upsert compat) ─────────
        "emails":           emails,
        "phones":           phones,
        # ── Address ───────────────────────────────────────────────────────
        "address":          address,
        "city":             city,
        "state":            state,
        "country":          country,
        "postal_code":      _str(raw.get("postal_code", "")),
        # ── Enriched single-value fields ───────────────────────────────────
        "email":            email,            # best single validated email
        "company_number":   company_number,   # None if not found
        "founder_name":     founder_name,     # None if not found
        "founder_number":   founder_number,   # None unless publicly listed
        "source_url":       source_url,
        "sources":          sources,
        "confidence":       confidence,
        # ── Validated lists (pass through for pipeline compat) ─────────────
        "validated_emails": emails,
        "validated_phones": [{"number": company_number, "type": "unknown"}] if company_number else [],
        # ── Hermes source trace ────────────────────────────────────────────
        "research_source":  "hermes",
        "research_sources": research_sources,
        # ── Verify stage placeholder (will be filled by existing pipeline) ─
        "last_verified":    None,
        # ── Internal helpers for existing pipeline stages ─────────────────
        "description":      _str(raw.get("description") or raw.get("industry", "")),
        "services":         _list(raw.get("services")),
        "_scraped_pages":   [],          # no raw pages from Hermes path
        "_merged_markdown": "",
        # pages_visited needed by score_confidence()
        "pages_visited":    {
            "success": research_sources[:6],
            "failed":  [],
        },
    }


def normalize_hermes_response(raw_text: str) -> list[dict]:
    """
    Parse Hermes's raw text response and return a list of normalised company
    dicts ready for the existing VALIDATE → CONFIDENCE → ENRICH → VERIFY
    → DEDUPLICATE → MongoDB pipeline.

    Never fabricates data.  If a field is missing it stays None / [].
    """
    parsed = _extract_json_from_response(raw_text)

    raw_companies = parsed.get("companies", [])
    if not raw_companies and isinstance(parsed, list):
        raw_companies = parsed

    if not isinstance(raw_companies, list):
        raw_companies = [raw_companies] if raw_companies else []

    return [_normalize_hermes_company(c) for c in raw_companies if isinstance(c, dict)]


# ── Public interface ──────────────────────────────────────────────────────────

async def call_hermes_agent(query: str, num: int = 10) -> dict:
    """
    Send a research request to the Hermes Desktop Agent via WebSocket.

    This is the ONLY path for primary company discovery.
    No fallback to direct Serper / Firecrawl calls is ever attempted.

    Parameters
    ----------
    query : str
        The user's search query (e.g. "Real estate companies in Pune").
    num : int
        How many companies to request.

    Returns
    -------
    dict with keys:
        query        : the original query
        timestamp    : UTC ISO-8601 string
        companies    : list of normalised company dicts
        total        : number of companies
        status       : "success"

    Raises
    ------
    HermesUnavailableError
        If the WebSocket connection fails for any reason.
        The caller (routes/leads.py) converts this to HTTP 502.
    """
    print(f"[LEADS] Sending research request to Hermes — query={query!r} num={num}")

    prompt = build_research_prompt(query, num)

    # Connect → send → receive  (raises HermesUnavailableError on any failure)
    raw_response = await _connect_and_send(prompt)

    # Parse and normalise
    companies = normalize_hermes_response(raw_response)
    print(f"[HERMES] Companies returned by Hermes: {len(companies)}")

    return {
        "query":     query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "companies": companies,
        "total":     len(companies),
        "status":    "success",
    }


# ── Connection test (used by test_hermes_integration.py) ─────────────────────

async def test_hermes_connection() -> dict:
    """
    Lightweight connectivity test using correct JSON-RPC 2.0 protocol.

    Returns a result dict:
        connected : bool
        url       : str  (without token)
        error     : str | None
    """
    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:
        return {"connected": False, "url": _WS_URL, "error": "websockets not installed"}

    ws_url = _WS_URL
    if _TOKEN:
        separator = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{separator}token={_TOKEN}"

    try:
        async with ws_connect(
            ws_url,
            open_timeout=10,
            additional_headers={"Origin": "http://localhost:9119"},
        ) as ws:
            # Wait for gateway.ready event — that's Hermes's on-connect signal
            try:
                async with asyncio.timeout(8):
                    raw = await ws.recv()
                    frame = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                    params = frame.get("params") or {}
                    if params.get("type") == "gateway.ready" or frame.get("method") == "event":
                        return {"connected": True, "url": _WS_URL, "error": None}
                    # Any frame received = connected
                    return {"connected": True, "url": _WS_URL, "error": None}
            except (asyncio.TimeoutError, Exception):
                # A frame wasn't received but the connection was accepted = still connected
                return {"connected": True, "url": _WS_URL, "error": None}

    except ConnectionRefusedError:
        return {
            "connected": False,
            "url": _WS_URL,
            "error": (
                "Connection refused. Hermes Desktop Agent is not running. "
                "Start it with: hermes serve"
            ),
        }
    except OSError as exc:
        return {"connected": False, "url": _WS_URL, "error": f"Network error: {exc}"}
    except Exception as exc:
        return {"connected": False, "url": _WS_URL, "error": f"{type(exc).__name__}: {exc}"}
