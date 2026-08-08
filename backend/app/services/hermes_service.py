"""
app/services/hermes_service.py
--------------------------------
Single responsibility: run the lead-generation pipeline and return
validated JSON ready for MongoDB insertion.

Architecture
------------
FastAPI
  -> hermes_service.call_hermes_agent()
       -> subprocess: python leadgen.py --query "<query>" --num N
            -> leadgen.py
                 -> Serper API  (Google search)
                 -> Firecrawl API (website scraping)
                 -> returns JSON on stdout

NOTE on Windows + asyncio subprocesses
---------------------------------------
asyncio.create_subprocess_exec requires ProactorEventLoop on Windows.
Uvicorn by default uses SelectorEventLoop which does NOT support subprocesses.
We use loop.run_in_executor + subprocess.run (blocking, thread-pool) instead —
this works on every platform and every event loop without configuration.
"""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# ── Pipeline config ───────────────────────────────────────────────────────────

# Absolute path to the leadgen.py script
# Defaults to the known installation path; override with LEADGEN_SCRIPT env var.
_default_script = r"C:\Users\Disha\LeadGeneration\tools\leadgen.py"
LEADGEN_SCRIPT = Path(os.getenv("LEADGEN_SCRIPT", _default_script))

# Python interpreter — use the same venv that runs FastAPI so all deps are available
PYTHON_EXE = Path(sys.executable)

# Timeout for the full pipeline (Serper + Firecrawl scraping across N companies)
PIPELINE_TIMEOUT = 600  # 10 minutes

# Thread pool for running the blocking subprocess (avoids event-loop compatibility issues on Windows)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hermes")

# ── Required output fields ────────────────────────────────────────────────────

REQUIRED_TOP_FIELDS = {"companies"}


# ── Blocking runner (runs in thread pool) ────────────────────────────────────

def _run_leadgen_blocking(query: str, num: int) -> tuple[str, str, int]:
    """
    Run leadgen.py synchronously in a worker thread.
    Returns (stdout_text, stderr_text, returncode).
    Safe to call from any asyncio event loop on any platform.
    """
    subprocess_env = os.environ.copy()
    subprocess_env["PYTHONIOENCODING"] = "utf-8"
    subprocess_env["PYTHONUTF8"] = "1"

    cmd = [
        str(PYTHON_EXE),
        "-X", "utf8",
        str(LEADGEN_SCRIPT),
        "--query", query,
        "--num", str(num),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=PIPELINE_TIMEOUT,
        cwd=str(LEADGEN_SCRIPT.parent),
        env=subprocess_env,
    )

    stdout_text = result.stdout.decode("utf-8", errors="replace").strip()
    stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
    return stdout_text, stderr_text, result.returncode


# ── Public interface ──────────────────────────────────────────────────────────

async def call_hermes_agent(query: str, num: int = 10) -> dict:
    """
    Run the lead-generation pipeline for the given query.

    Runs leadgen.py in a thread pool (blocking subprocess.run) so it works
    on any asyncio event loop, including uvicorn's SelectorEventLoop on Windows.

    Returns a normalised dict ready for MongoDB upsert.

    Raises
    ------
    RuntimeError  on timeout, non-zero exit, missing script, or invalid JSON
    """
    if not LEADGEN_SCRIPT.exists():
        raise RuntimeError(
            f"leadgen.py not found at {LEADGEN_SCRIPT}. "
            "Verify the LeadGeneration toolkit installation."
        )

    if not PYTHON_EXE.exists():
        raise RuntimeError(f"Python interpreter not found: {PYTHON_EXE}")

    print(f"[HermesService] Running leadgen.py: query={query!r} num={num}")

    loop = asyncio.get_event_loop()
    try:
        stdout_text, stderr_text, returncode = await loop.run_in_executor(
            _executor,
            _run_leadgen_blocking,
            query,
            num,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"leadgen.py timed out after {PIPELINE_TIMEOUT}s for query: {query!r}"
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to launch leadgen.py: {exc}") from exc

    # ── Log stderr (progress lines from leadgen.py) ───────────────────────────
    if stderr_text:
        for line in stderr_text.splitlines():
            print(f"[leadgen] {line}")

    # ── Guard: no stdout at all ───────────────────────────────────────────────
    if not stdout_text:
        hint = stderr_text[-400:] if stderr_text else "(no output)"
        raise RuntimeError(
            f"leadgen.py produced no stdout. "
            f"Exit code: {returncode}. Hint: {hint}"
        )

    # ── Parse JSON ────────────────────────────────────────────────────────────
    raw = _extract_json(stdout_text)

    # ── Validate ──────────────────────────────────────────────────────────────
    _validate(raw)

    # ── Normalise ─────────────────────────────────────────────────────────────
    companies = [_normalize_company(c) for c in raw.get("companies", [])]

    print(f"[HermesService] Pipeline complete — {len(companies)} companies returned")

    return {
        "query":     raw.get("query", query),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "companies": companies,
        "total":     len(companies),
        "status":    "success",
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract a JSON object from stdout. Handles both raw JSON and wrapped output."""
    import re

    # 1. Try raw parse first (leadgen.py outputs clean JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Find the outermost { ... } block (skip any progress lines before JSON)
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Could not extract valid JSON from leadgen.py output. "
        f"First 300 chars: {text[:300]!r}"
    )


def _validate(data: dict) -> None:
    """Raise RuntimeError if required top-level fields are missing."""
    missing = REQUIRED_TOP_FIELDS - set(data.keys())
    if missing:
        raise RuntimeError(
            f"leadgen.py JSON missing required fields: {missing}. "
            f"Got keys: {set(data.keys())}"
        )
    if not isinstance(data.get("companies"), list):
        raise RuntimeError(
            "'companies' field must be a list. "
            f"Got: {type(data.get('companies'))}"
        )


def _normalize_company(raw: dict) -> dict:
    """
    Map leadgen.py output schema → MongoDB document schema.

    leadgen.py uses "name" as the company name key and may return
    address as either a nested dict or a plain string.
    """
    addr = raw.get("address", {})
    if isinstance(addr, str):
        street, city, state, country, postal_code = addr, "", "", "", ""
    elif isinstance(addr, dict):
        street      = addr.get("street", "")
        city        = addr.get("city", "")
        state       = addr.get("state", "")
        country     = addr.get("country", "")
        postal_code = addr.get("postal_code", "")
    else:
        street = city = state = country = postal_code = ""

    return {
        # leadgen.py uses "name"; accept both for safety
        "company_name": raw.get("name") or raw.get("company_name", ""),
        "website":      raw.get("website", ""),
        "emails":       raw.get("emails", []),
        "phones":       raw.get("phones", []),
        "address":      street,
        "city":         city,
        "state":        state,
        "country":      country,
        "postal_code":  postal_code,
        "sources":      raw.get("sources", []),
    }
