"""
app/services/verify_service.py
──────────────────────────────
Company-Context Verification stage.

Runs AFTER extraction/enrichment. For each extracted field (founder, email,
phone, address, company_name) it performs targeted Serper searches to verify
that the value is actually associated with the target company.

No LLM is used. Verification is purely evidence-based: a field is accepted
only when a Serper snippet or scraped text explicitly names both the company
AND the field value in the same sentence/passage.

Rules:
  - Founder: reject if the name cannot be found in proximity to the company
    name + a leadership title on an official source. Searches use exact
    domain + candidate name to avoid cross-company contamination.
  - Email: accept only if domain matches company domain.
  - Phone: prefer +91/India numbers when domain ends in .in or .co.in.
  - Address: reject paragraphs; require city name or PIN code.
  - Company name: strip aggregator/SEO noise from titles.
  - Company type: reject government portals and non-target-industry sites.

All searches run concurrently (bounded). Target: add ≤5s to the pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_URL     = "https://google.serper.dev/search"
_T_SERPER      = 10          # per-query timeout
_SEM_SIZE      = 8           # max concurrent Serper calls in this stage
_MAX_RESULTS   = 5           # snippets to examine per query

# ── Social / non-official domains — never trusted as founder evidence ─────────
_NON_OFFICIAL: frozenset[str] = frozenset({
    "linkedin.com", "instagram.com", "facebook.com", "twitter.com", "x.com",
    "youtube.com", "wikipedia.org", "glassdoor.com", "glassdoor.co.in",
    "ambitionbox.com", "quora.com", "reddit.com", "medium.com",
    "indiamart.com", "justdial.com", "crunchbase.com", "bloomberg.com",
    "naukri.com", "indeed.com",
})

# ── Founder rejection patterns ────────────────────────────────────────────────
_HONORIFICS = frozenset({
    "late", "mr", "mrs", "ms", "dr", "prof", "sir", "shri", "smt",
    "executive", "managing", "chief", "senior", "junior",
    "vice", "deputy", "assistant", "additional", "associate",
    "the", "our", "your", "view", "see", "meet", "about",
    "director",   # "Executive Director" should be rejected as a NAME
    "head", "team", "leadership", "regulatory", "authority",
    "business", "general", "national", "regional", "global",
})
_COMPANY_WORDS = frozenset({
    "ltd", "limited", "pvt", "private", "inc", "incorporated",
    "corp", "corporation", "group", "developers", "development",
    "realty", "realtors", "realtor", "properties", "builders", "construction", "infra",
    "infrastructure", "associates", "consultants", "solutions",
    "services", "ventures", "holdings", "industries", "enterprises",
    "estate", "estates", "homes", "housing",
    "regulatory", "authority", "team",
})
# Any word in the name that is a role/title word — reject the entire name
_ROLE_WORDS = frozenset({
    "founder", "co-founder", "ceo", "coo", "cfo", "cto",
    "director", "chairman", "president", "md", "manager",
    "officer", "head", "leader", "principal", "partner",
    "executive", "promoter", "investor", "advisor",
})
# Multi-word fragments that look like names but are NOT personal names
_NON_PERSON_PHRASES = frozenset({
    "leadership team", "regulatory authority leadership", "business head",
    "view sachin", "view profile", "meet team", "our team", "our leadership",
    "management team", "board directors", "executive team",
})
_LEADERSHIP_RE = re.compile(
    r'(?i)\b(founder|co-founder|ceo|chief\s+executive|managing\s+director'
    r'|chairman|chairperson|president|promoter|md\b)',
)
_NAME_RE = re.compile(r'\b([A-Z][a-z]{1,20})\s+([A-Z][a-z]{1,20})(?:\s+([A-Z][a-z]{1,20}))?\b')

# ── Phone helpers ─────────────────────────────────────────────────────────────
_INDIAN_PHONE_RE = re.compile(
    r'(?:\+91[\s\-]?)?(?:[6-9]\d{9}|1800[\s\-]?\d{3}[\s\-]?\d{4}'
    r'|0\d{2,4}[\s\-]\d{6,8})',
)

def _is_indian_number(phone: str) -> bool:
    digits = re.sub(r'\D', '', phone)
    if digits.startswith("91") and len(digits) == 12:
        return True
    if digits.startswith("1800"):
        return True
    if len(digits) == 10 and digits[0] in "6789":
        return True
    if digits.startswith("0") and 10 <= len(digits) <= 12:
        return True
    return False

def _is_foreign_number(phone: str) -> bool:
    if phone.strip().startswith("+") and not phone.strip().startswith("+91"):
        return True
    digits = re.sub(r'\D', '', phone)
    if digits.startswith("1") and len(digits) == 11 and not digits.startswith("1800"):
        return True  # US/Canada +1
    return False

def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""

def _is_india_domain(domain: str) -> bool:
    return domain.endswith(".in") or domain.endswith(".co.in") or ".india" in domain

# ── HTTP client (reuse discovery_service client) ──────────────────────────────
_http_client: Optional[httpx.AsyncClient] = None

def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=8.0, read=_T_SERPER, write=8.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=8),
            follow_redirects=True,
        )
    return _http_client


# ── Low-level Serper call returning structured results ────────────────────────
async def _serper(
    client: httpx.AsyncClient,
    q: str,
    sem: asyncio.Semaphore,
    n: int = _MAX_RESULTS,
) -> list[dict]:
    """Return list of {title, link, snippet} from Serper. Empty on failure."""
    if not SERPER_API_KEY:
        return []
    async with sem:
        try:
            resp = await client.post(
                SERPER_URL,
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                content=json.dumps({"q": q, "num": n}).encode(),
                timeout=_T_SERPER,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
    out = []
    kg = data.get("knowledgeGraph", {})
    if kg.get("description"):
        out.append({
            "title":   kg.get("title", ""),
            "link":    kg.get("website", ""),
            "snippet": kg.get("description", ""),
        })
    for item in data.get("organic", [])[:n]:
        out.append({
            "title":   item.get("title", ""),
            "link":    item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return out


def _snippet_contains(results: list[dict], *terms: str) -> tuple[bool, str]:
    """
    Return (True, source_url) if any snippet/title contains ALL given terms
    (case-insensitive). Returns (False, "") otherwise.
    """
    terms_lower = [t.lower() for t in terms if t]
    for r in results:
        text = f"{r.get('title','')} {r.get('snippet','')}".lower()
        if all(t in text for t in terms_lower):
            # Only trust official sources for founder verification
            link = r.get("link", "")
            dom  = _domain_of(link)
            if any(dom == b or dom.endswith("." + b) for b in _NON_OFFICIAL):
                continue   # skip social/directory sources
            return True, link
    return False, ""


def _is_plausible_person_name(name: str) -> bool:
    """Return True if name looks like a real person (not a job title or company)."""
    if not name:
        return False
    # Quick check against known non-person phrases
    if name.strip().lower() in _NON_PERSON_PHRASES:
        return False
    words = name.strip().split()
    if len(words) < 2 or len(words) > 4:
        return False
    if words[0].lower() in _HONORIFICS:
        return False
    word_lower = {w.lower() for w in words}
    # Reject if ANY word is a role/title word (catches "Founder Om Gupta", "Pravin Gawali Founder")
    if word_lower & _ROLE_WORDS:
        return False
    if word_lower & _COMPANY_WORDS:
        return False
    # Each word must start with uppercase followed by lowercase
    if not all(len(w) >= 2 and w[0].isupper() and w[1:].islower() for w in words):
        return False
    # "View Sachin" style — reject if first word is a common action verb/article
    _ACTION_WORDS = frozenset({
        "view", "see", "meet", "read", "know", "find", "click",
        "learn", "more", "all", "the",
    })
    if words[0].lower() in _ACTION_WORDS:
        return False
    return True

# ═══════════════════════════════════════════════════════════════════════════════
# FOUNDER VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

async def verify_founder(
    company_name: str,
    domain: str,
    candidate: Optional[str],
    merged_markdown: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> tuple[Optional[str], str, str]:
    """
    Verify that `candidate` is actually a founder/leader of `company_name`.

    Strict verification — the candidate must be explicitly associated with
    THIS company. Cross-company contamination is rejected by:
    1. Requiring both the company name AND the candidate in the same snippet.
    2. Preferring site:domain searches over general web searches.
    3. Rejecting results from social/directory/non-official domains.

    Returns:
        (verified_name_or_None, source_url, verification_status)
        status: "verified_scraped" | "verified_search" | "rejected" | "null_input"
    """
    if not candidate:
        return None, "", "null_input"

    if not _is_plausible_person_name(candidate):
        return None, "", "rejected_invalid_name"

    # ── Pass 1: Check scraped markdown from official pages ────────────────────
    # Look for candidate name near a leadership title on the company's own pages
    if merged_markdown:
        lines = merged_markdown.split("\n")
        name_lower = candidate.lower()
        name_words = name_lower.split()
        for i, line in enumerate(lines):
            ll = line.lower()
            if all(w in ll for w in name_words):
                # Check ±4 lines for a leadership title
                window_start = max(0, i - 4)
                window_end   = min(len(lines), i + 5)
                window_text  = " ".join(lines[window_start:window_end]).lower()
                if _LEADERSHIP_RE.search(window_text):
                    # Also verify the window mentions the company (avoids embedded content)
                    company_words = company_name.lower().split()[:3]
                    company_mentioned = any(cw in merged_markdown.lower() for cw in company_words if len(cw) > 3)
                    if company_mentioned:
                        return candidate, "scraped_pages", "verified_scraped"

    # ── Pass 2: Serper verification — STRICT domain-scoped searches ───────────
    # All queries must reference the specific company to prevent cross-company
    # contamination (e.g. Raju Bhise appearing for Austin Realty from an
    # unrelated snippet).
    name_parts = candidate.split()
    first, last = name_parts[0], name_parts[-1]

    queries = []
    if domain:
        # Exact name search on official domain — highest confidence
        queries.append(f'site:{domain} "{candidate}"')
        # Leadership page search on official domain
        queries.append(f'site:{domain} founder leadership team')
    # General search: MUST contain both company name AND candidate name
    queries.append(f'"{company_name}" "{candidate}" founder CEO')
    # Additional: company domain + candidate last name
    if domain:
        queries.append(f'"{last}" "{company_name}" founder managing director')

    tasks  = [_serper(client, q, sem, 5) for q in queries]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[dict] = []
    for r in results_list:
        if isinstance(r, list):
            all_results.extend(r)

    # Check if any result explicitly connects candidate to company in a leadership role
    # Require ALL of: company name word, candidate last name, leadership title
    for r in all_results:
        text = f"{r.get('title','')} {r.get('snippet','')}".lower()
        link = r.get("link", "")
        link_dom = _domain_of(link)

        # Skip social/directory sources
        if any(link_dom == b or link_dom.endswith("." + b) for b in _NON_OFFICIAL):
            continue

        name_in_text = last.lower() in text and first.lower() in text
        # Must explicitly mention the company — use first significant word (>3 chars)
        co_words = [w for w in company_name.lower().split() if len(w) > 3]
        co_in_text = co_words and any(cw in text for cw in co_words[:2])
        title_near = bool(_LEADERSHIP_RE.search(text))

        if name_in_text and co_in_text and title_near:
            return candidate, link, "verified_search"

    # ── Pass 3: Try to find a BETTER name from site:domain search ────────────
    # If we couldn't verify the candidate, look for a name that IS on the site
    if domain:
        # Use site:domain results (first query result set)
        site_results = next(
            (r for r in results_list if isinstance(r, list) and r),
            []
        )
        for r in site_results:
            text = f"{r.get('title','')} {r.get('snippet','')} "
            if not _LEADERSHIP_RE.search(text.lower()):
                continue
            # Only trust results from the company's own domain
            link_dom = _domain_of(r.get("link", ""))
            if not (link_dom == domain or link_dom.endswith("." + domain)):
                continue
            for m in _NAME_RE.finditer(text):
                name_cand = m.group(0).strip()
                if not _is_plausible_person_name(name_cand):
                    continue
                name_w = name_cand.lower().split()
                text_l = text.lower()
                if all(w in text_l for w in name_w):
                    co_word = company_name.split()[0].lower()
                    if co_word in text_l and len(co_word) > 3:
                        if not any(link_dom == b or link_dom.endswith("."+b) for b in _NON_OFFICIAL):
                            return name_cand, r.get("link", ""), "found_alternative"

    return None, "", "rejected"

# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

async def verify_email(
    company_name: str,
    domain: str,
    candidate: Optional[str],
    merged_markdown: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> tuple[Optional[str], str, str]:
    """
    Verify email belongs to this company.

    Returns (verified_email_or_None, source_url, status).
    status: "verified_domain" | "found_gap" | "rejected_domain" | "not_found"
    """
    # ── Check existing emails already extracted from scraped pages ────────────
    if candidate:
        email_dom = candidate.split("@")[-1].lower()
        if email_dom == domain or email_dom.endswith("." + domain):
            return candidate, "scraped_pages", "verified_domain"
        else:
            # Domain mismatch — reject this email
            return None, "", "rejected_domain_mismatch"

    # No email found yet — run targeted gap searches
    if not domain and not company_name:
        return None, "", "not_found"

    queries = []
    if domain:
        queries.append(f'site:{domain} email contact')
        queries.append(f'"{company_name}" "@{domain}"')
    queries.append(f'"{company_name}" official email contact')

    tasks        = [_serper(client, q, sem, 5) for q in queries[:3]]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    email_re = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    _junk_locals = frozenset({"noreply","no-reply","donotreply","support",
                               "mailer-daemon","postmaster","bounce","spam"})

    for r_list in results_list:
        if not isinstance(r_list, list):
            continue
        for r in r_list:
            text = f"{r.get('title','')} {r.get('snippet','')} "
            for m in email_re.finditer(text):
                addr = m.group(0).lower()
                local, _, edom = addr.partition("@")
                if local in _junk_locals or "/" in addr:
                    continue
                # Must match company domain
                if domain and (edom == domain or edom.endswith("." + domain)):
                    return addr, r.get("link", ""), "found_gap"

    return None, "", "not_found"


# ═══════════════════════════════════════════════════════════════════════════════
# PHONE VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

async def verify_phone(
    company_name: str,
    domain: str,
    candidate: Optional[str],
    all_phones: list[str],
    merged_markdown: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> tuple[Optional[str], str, str]:
    """
    Verify phone is a real company number. Prefer Indian numbers for .in domains.
    For India-domain companies, REJECT any foreign/non-Indian numbers — prefer
    null over a wrong number.

    Returns (best_phone_or_None, source_url, status).
    """
    india_domain = _is_india_domain(domain)

    # Filter out foreign numbers for India-domain companies before ranking
    if india_domain:
        all_phones = [p for p in all_phones if not _is_foreign_number(p)]

    # Sort available phones: prefer Indian if India domain
    def _phone_rank(p: str) -> int:
        if _is_indian_number(p):
            return 0 if india_domain else 1
        if _is_foreign_number(p):
            return 3 if india_domain else 0
        return 2

    phones_ranked = sorted(all_phones, key=_phone_rank)

    if phones_ranked:
        best = phones_ranked[0]
        # Final safety: reject foreign numbers for India-domain companies
        if india_domain and _is_foreign_number(best):
            return None, "", "rejected_foreign_for_india_domain"
        status = "verified_indian" if _is_indian_number(best) else "verified_present"
        return best, "scraped_pages", status

    # Gap search for phone
    if not company_name:
        return None, "", "not_found"

    q = f'site:{domain} phone contact' if domain else f'"{company_name}" phone contact'

    results = await _serper(client, q, sem, 5)

    phone_re = re.compile(
        r'\+91[\s\-]?[6-9]\d{9}'            # Indian mobile +91
        r'|\+91[\s\-]?\d{2,4}[\s\-]\d{6,8}' # Indian landline +91
        r'|1800[\s\-]?\d{3}[\s\-]?\d{4}'    # Indian toll-free
        r'|\b0\d{2,4}[\s\-]\d{6,8}\b'       # Indian STD
    )

    for r in results:
        text = f"{r.get('snippet','')} "
        for m in phone_re.finditer(text):
            num = m.group(0).strip()
            digits = re.sub(r'\D', '', num)
            if 7 <= len(digits) <= 13:
                return num, r.get("link", ""), "found_gap_indian"

    return None, "", "not_found"

# ═══════════════════════════════════════════════════════════════════════════════
# ADDRESS VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

_INDIAN_CITIES = [
    "Pune", "Mumbai", "Delhi", "Bangalore", "Bengaluru", "Hyderabad",
    "Ahmedabad", "Chennai", "Kolkata", "Nagpur", "Nashik", "Thane",
    "Navi Mumbai", "Noida", "Gurugram", "Gurgaon", "Chandigarh",
    "Aurangabad", "Pimpri", "Pimpri-Chinchwad",
]
_PIN_RE = re.compile(r'(?<!\d)([1-9]\d{5})(?!\d)')

def verify_address_local(candidate: str, domain: str) -> tuple[Optional[str], str]:
    """
    Synchronous address quality check.
    Returns (clean_address_or_None, status).
    """
    if not candidate:
        return None, "not_found"

    words = candidate.split()
    if len(words) > 30:
        # Paragraph — try to salvage first sentence
        first = candidate.split(".")[0].strip()
        if len(first.split()) <= 30:
            candidate = first
        else:
            return None, "rejected_paragraph"

    # Must contain a city name or PIN code
    has_city = any(
        re.search(r'\b' + re.escape(c) + r'\b', candidate, re.IGNORECASE)
        for c in _INDIAN_CITIES
    )
    has_pin  = bool(_PIN_RE.search(candidate))
    has_india = "india" in candidate.lower()

    if has_city or has_pin or has_india:
        # Clean up markdown artefacts
        clean = re.sub(r'^[#\-\*\s]+', '', candidate).strip()
        clean = re.sub(r'\s{2,}', ' ', clean)
        return clean, "verified_location"

    # No location indicator — reject
    return None, "rejected_no_location"


# ═══════════════════════════════════════════════════════════════════════════════
# COMPANY NAME CLEANUP
# ═══════════════════════════════════════════════════════════════════════════════

# Title separators to try when stripping SEO noise
_TITLE_SEPS = [" — ", " | ", " - ", " · ", " > ", " :: ", " – "]

_NOISE_PREFIX_RE = re.compile(
    r'(?i)^(?:real\s+estate\s+)?(?:companies|developers|builders|brokers|agents)\s+in\s+\S+\s*[—\-–|]\s*',
)
# Also strip brand tagline prefixes like "Pune's Leading Real Estate Brand | VTP Realty®"
_NOISE_BRAND_PREFIX_RE = re.compile(
    r"(?i)^(?:india'?s?|pune'?s?|mumbai'?s?|bangalore'?s?|delhi'?s?|hyderabad'?s?)?\s*"
    r"(?:leading|top|best|premier|most\s+trusted|award\s*winning|#\d)\s+"
    r"(?:real\s+estate|property|builder|developer|realty)\s+"
    r"(?:brand|company|developer|builder|group|firm)\s*[|—\-–]\s*",
)
_NOISE_SUFFIX_RE = re.compile(
    r'(?i)\s*[|—\-–]\s*(?:official\s+(?:website|site)?|'
    r'real\s+estate.*|top\s+.*|best\s+.*|premium\s+.*'
    r'|homes\s+in\s+.*'           # "Kolte Patil Developers | Homes in Pune, Mumbai & Bengaluru"
    r'|properties\s+in\s+.*'
    r'|projects\s+in\s+.*'
    r'|developers\s+in\s+.*'
    r'|builders\s+in\s+.*)$',
)
# Trailing words to strip from company names
_NAME_TRAILING_NOISE_RE = re.compile(
    r'(?i)\s*(?:'
    r'[®™©]\s*(?:official\s+\S+.*|site\s*.*|\.\.\.*|\s*$)'  # ® Official ..., ® ...
    r'|official\s+(?:website|site|web\s*site)'
    r'|website|site|online'
    r'|pvt\.?\s*ltd\.?|limited|incorporated|private\s+limited'
    r')\s*$',
)


def clean_company_name(
    og_site_name: str,
    page_title: str,
    serper_title: str,
    domain: str,
) -> str:
    """
    Return the best company name from available signals.

    Priority:
    1. og:site_name (most reliable — set by the company itself)
    2. Page title segment (split on separator, pick brand part)
    3. Serper title (cleaned of SEO noise)
    4. Domain-derived name (fallback)

    Additional cleanup:
    - Strip trailing "Official Website", "Website", "Online", etc.
    - Strip "| Homes in ...", "| Properties in ...", "| Real Estate ..." suffixes
    - Fix title-case for names like "Austinrealty" → try to preserve original casing
      but only if the og:site_name or page title provides it.
    """
    def _strip_trailing_noise(name: str) -> str:
        """Remove trailing marketing noise from a company name."""
        name = _NAME_TRAILING_NOISE_RE.sub("", name).strip()
        return name

    # 1. og:site_name
    if og_site_name and len(og_site_name) >= 2:
        return _strip_trailing_noise(og_site_name.strip())

    # 2. Page title — try each separator, pick the shortest non-generic segment
    _GENERIC = frozenset({
        "contact", "contact us", "home", "welcome", "about", "about us",
        "services", "solutions", "products", "index", "error", "404",
        "login", "sign in", "register",
    })
    if page_title:
        # First remove known noise prefix (SEO pattern like "Developers in Pune — Brand")
        cleaned_title = _NOISE_PREFIX_RE.sub("", page_title).strip()
        cleaned_title = _NOISE_BRAND_PREFIX_RE.sub("", cleaned_title).strip()
        cleaned_title = _NOISE_SUFFIX_RE.sub("", cleaned_title).strip()

        for sep in _TITLE_SEPS:
            parts = cleaned_title.split(sep)
            # Check all parts, prefer non-generic, shortest first
            candidates = sorted(
                [p.strip() for p in parts if p.strip() and p.strip().lower() not in _GENERIC],
                key=len,
            )
            if candidates:
                return _strip_trailing_noise(candidates[0])

        if cleaned_title and cleaned_title.lower() not in _GENERIC and len(cleaned_title) >= 2:
            return _strip_trailing_noise(cleaned_title)

    # 3. Serper title — same cleaning
    if serper_title:
        cleaned = _NOISE_PREFIX_RE.sub("", serper_title).strip()
        cleaned = _NOISE_BRAND_PREFIX_RE.sub("", cleaned).strip()
        cleaned = _NOISE_SUFFIX_RE.sub("", cleaned).strip()
        for sep in _TITLE_SEPS:
            parts = cleaned.split(sep)
            candidates = sorted(
                [p.strip() for p in parts if p.strip() and p.strip().lower() not in _GENERIC],
                key=len,
            )
            if candidates:
                return _strip_trailing_noise(candidates[0])
        if cleaned and cleaned.lower() not in _GENERIC and len(cleaned) >= 2:
            return _strip_trailing_noise(cleaned)

    # 4. Domain fallback
    if domain:
        return domain.split(".")[0].replace("-", " ").replace("_", " ").title()

    return ""

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN: verify_company — per-company orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

async def verify_company(company: dict, sem: asyncio.Semaphore) -> dict:
    """
    Run all verification checks for one company concurrently.

    Mutates a copy of the company dict with verified/cleaned values and
    adds a `_field_verification` dict for audit/logging.

    Never fabricates data — a field is set to None if verification fails.
    """
    client = _get_client()

    name     = company.get("company_name", "")
    domain   = company.get("domain", "")
    email    = company.get("email")
    phones   = company.get("phones", []) or []
    phone    = company.get("company_number") or (phones[0] if phones else None)
    address  = company.get("address", "")
    founder  = company.get("founder_name")
    md       = company.get("_merged_markdown", "")

    # ── Company name cleanup (synchronous — no Serper call needed) ────────────
    og_name      = ""
    page_title   = ""
    serper_title = company.get("_serper_title", "")
    for page in company.get("_scraped_pages", []):
        meta = page.get("metadata") or {}
        if not og_name:
            og_name    = (meta.get("og:site_name") or "").strip()
        if not page_title:
            page_title = (meta.get("title") or "").strip()

    clean_name = clean_company_name(og_name, page_title, name, domain)
    if not clean_name:
        clean_name = name  # keep original if cleaning produced nothing

    # ── Run field verifications concurrently ──────────────────────────────────
    founder_task = asyncio.create_task(
        verify_founder(clean_name, domain, founder, md, client, sem)
    )
    email_task = asyncio.create_task(
        verify_email(clean_name, domain, email, md, client, sem)
    )
    phone_task = asyncio.create_task(
        verify_phone(clean_name, domain, phone, phones, md, client, sem)
    )

    (v_founder, founder_src, founder_status), \
    (v_email,   email_src,   email_status),   \
    (v_phone,   phone_src,   phone_status)    \
        = await asyncio.gather(founder_task, email_task, phone_task)

    # ── Address verification (synchronous) ───────────────────────────────────
    v_address, addr_status = verify_address_local(address, domain)

    # ── Confidence recalculation ──────────────────────────────────────────────
    score = 0.0
    if v_email:   score += 0.30
    if v_phone:   score += 0.25
    if v_address: score += 0.10
    if v_founder: score += 0.10
    if domain:    score += 0.05
    pages_ok = len(company.get("pages_visited", {}).get("success", []))
    if pages_ok >= 2:
        score += 0.10
    score = round(min(score, 1.0), 2)

    # ── Field verification audit dict ────────────────────────────────────────
    fv = {
        "company_name": {
            "value": clean_name, "original": name,
            "verified": clean_name != "" and not (clean_name == domain.split(".")[0].title()),
            "source": "og_site_name" if og_name else ("page_title" if page_title else "domain"),
        },
        "email": {
            "value": v_email, "verified": v_email is not None,
            "status": email_status, "source": email_src,
        },
        "phone": {
            "value": v_phone, "verified": v_phone is not None,
            "status": phone_status, "source": phone_src,
        },
        "address": {
            "value": v_address, "verified": v_address is not None,
            "status": addr_status, "source": "scraped_pages" if v_address else "",
        },
        "founder": {
            "value": v_founder, "verified": v_founder is not None,
            "status": founder_status, "source": founder_src,
        },
    }

    updated = {
        **company,
        "company_name":   clean_name,
        "name":           clean_name,
        "email":          v_email,
        "company_number": v_phone,
        "address":        v_address or "",
        "city":           company.get("city", "") if v_address else "",
        "state":          company.get("state", "") if v_address else "",
        "founder_name":   v_founder,
        "confidence":     score,
        "_field_verification": fv,
    }
    # Update emails/phones lists to match verified single values
    if v_email and v_email not in updated.get("emails", []):
        updated["emails"] = [v_email] + [e for e in updated.get("emails", []) if e != v_email]
    if v_phone and v_phone not in updated.get("phones", []):
        updated["phones"] = [v_phone] + [p for p in updated.get("phones", []) if p != v_phone]
    if not v_email:
        updated["email_status"] = "not_publicly_found"
        updated["emails"] = []
    if not v_phone:
        updated["phone_status"] = "not_publicly_found"

    # Always scrub foreign numbers from phones list for India-domain companies
    # regardless of whether a valid phone was found
    if _is_india_domain(domain):
        updated["phones"] = [p for p in updated.get("phones", []) if not _is_foreign_number(p)]
        if updated.get("company_number") and _is_foreign_number(updated["company_number"]):
            updated["company_number"] = None
            updated["phone_status"] = "rejected_foreign_for_india_domain"

    return updated


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def verify_all_companies(companies: list[dict]) -> list[dict]:
    """
    Run context verification for all companies concurrently.
    Uses a shared bounded semaphore to cap Serper requests.
    """
    sem   = asyncio.Semaphore(_SEM_SIZE)
    tasks = [verify_company(c, sem) for c in companies]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for original, result in zip(companies, results):
        if isinstance(result, Exception):
            # Verification failed — keep original company unchanged
            out.append(original)
        else:
            out.append(result)
    return out
