"""
app/services/discovery_service.py
──────────────────────────────────
Serper + Firecrawl company discovery service.

Production flow (Hermes is NEVER called from this module):
  1. DISCOVERY   — multiple targeted Serper searches → candidate URLs
  2. FILTER      — reject directories, social, Wikipedia, 404s, duplicates
  3. FIRECRAWL   — concurrent multi-page scrapes (bounded concurrency)
  4. EXTRACTION  — emails, phones, address, founder from scraped markdown
  5. CONTACT GAP — targeted Serper searches for missing email/phone/address/founder
  6. NORMALIZE   — map to internal schema

The output list feeds into the existing
VALIDATE → CONFIDENCE → ENRICH → VERIFY → DEDUPLICATE → MongoDB pipeline
in src/routes/leads.py without any changes to that pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

# Import verify_service lazily to avoid circular imports at module load
from app.services import verify_service as _vs

# ── Config ────────────────────────────────────────────────────────────────────
SERPER_API_KEY    = os.getenv("SERPER_API_KEY", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

SERPER_URL    = "https://google.serper.dev/search"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

# Timeouts (seconds)
_T_SERPER    = 12
_T_FIRECRAWL = 25
_T_HTTP      = 15

# Concurrency — max simultaneous Firecrawl requests
_FIRECRAWL_CONCURRENCY = 6

# Candidate multiplier: gather this many candidates per requested company
_CANDIDATE_MULT = 4

# Pages to scrape per company: (path, full_content)
# full_content=True keeps headers/footers so phone/email in nav bar is captured
# Trimmed to 6 pages max to stay within 30s for 10 companies
_PAGES: list[tuple[str, bool]] = [
    ("/",             True),
    ("/contact-us",   True),
    ("/contact",      True),
    ("/about-us",     False),
    ("/about",        False),
    ("/leadership",   False),
]

# ── Domain blocklist ──────────────────────────────────────────────────────────
_BLOCKED: frozenset[str] = frozenset({
    # Social / professional networks
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "pinterest.com", "tiktok.com", "snapchat.com",
    # Encyclopaedia / wiki
    "wikipedia.org", "wikidata.org", "wikimedia.org", "en.wikipedia.org",
    # Government / regulatory portals (not target companies)
    "mca.gov.in", "companieshouse.gov.uk", "roc.gov.in",
    "maharera.maharashtra.gov.in", "rera.rajasthan.gov.in",
    "up-rera.in", "rera.karnataka.gov.in", "hprera.in",
    "rerait.telangana.gov.in", "maharera.gov.in",
    # Business directories / aggregators
    "justdial.com", "indiamart.com", "tradeindia.com", "sulekha.com",
    "yellowpages.com", "yelp.com", "clutch.co", "glassdoor.com",
    "ambitionbox.com", "zaubacorp.com", "tofler.in",
    "crunchbase.com", "bloomberg.com", "dnb.com", "zoominfo.com",
    "rocketreach.co", "lusha.com", "apollo.io",
    # Document / content hosts
    "scribd.com", "slideshare.net", "issuu.com", "academia.edu",
    "medium.com", "substack.com", "quora.com", "reddit.com",
    "wordpress.com", "blogger.com", "tumblr.com",
    # Job boards
    "naukri.com", "indeed.com", "monster.com", "internshala.com",
    "shine.com", "foundit.in", "timesjobs.com", "unstop.com",
    # News / media portals
    "timesofindia.com", "economictimes.com", "moneycontrol.com",
    "livemint.com", "businesstoday.in", "hindustantimes.com",
    "ndtv.com", "thehindu.com", "firstpost.com", "news18.com",
    "deccanherald.com", "indiatimes.com", "cnbc.com", "reuters.com",
    # Real estate portals
    "99acres.com", "magicbricks.com", "housing.com", "makaan.com",
    "commonfloor.com", "nobroker.in", "squareyards.com",
    "proptiger.com", "commonfloor.com",
    # Maps / search engines
    "maps.google.com", "google.com", "bing.com",
    "play.google.com", "apps.apple.com",
    # Review sites
    "tripadvisor.com", "trustpilot.com", "mouthshut.com",
    # Lead generation / data aggregators
    "datascrappingservice.com", "b2bdataservices.com",
    # Real estate portals / aggregators (common for Indian RE searches)
    "goodfirms.co", "clutch.co", "sortlist.com", "designrush.com",
    "propjinni.com", "propertypistol.com", "propsearch.in",
    # RE listing portals
    "realestateagent.com", "realestateagencies.in",
    # Maharashtra / India directories
    "maharashtradirectory.com", "indiadirectory.in", "localbd.in",
    # Review/ranking sites (country-specific subdomains)
    "glassdoor.co.in", "glassdoor.com.au", "glassdoor.co.uk",
    # Marketing / lead-gen agencies (not target companies for RE industry)
    "aajneeti.social", "aajneeti.com",
})

_BLOCKED_TITLE_RE = re.compile(
    r'(?i)(404|not\s+found|page\s+not\s+found|file\s+not\s+found'
    r'|access\s+denied|error\s+page|under\s+construction'
    r'|coming\s+soon|domain\s+for\s+sale'
    r'|top\s+\d+\s+(?:real\s+estate|companies|developers|builders|brokers|agents)'
    r'|list\s+of\s+(?:all\s+)?(?:real\s+estate|companies)'
    r'|best\s+(?:real\s+estate|builders|developers|brokers)\s+in'
    r'|reviews?\s*\|'
    r'|\d{4}\s+reviews?)',
)

# Separate — used only for company_name cleanup (more aggressive, not for candidate rejection)
_AGGREGATOR_NAME_RE = re.compile(
    r'(?i)((?:real\s+estate\s+)?(?:companies|developers|builders|brokers|agents)\s+in\s+\w+'
    r'|top\s+real\s+estate|commercial\s+real\s+estate\s+agency\s+in'
    r'|reviews?\s*\|)',
)

# Path patterns that indicate list/aggregator/blog pages (not company homepages)
_AGGREGATOR_PATH_RE = re.compile(
    r'(?i)/(?:blog|blogs|news|article|articles|top[-_]?\d+|best[-_]?\d*'
    r'|list[-_]of|guide|reviews?|directory|search|category|tag'
    r'|media|magazine|pdf|document'
    r'|en/[a-z]+/offices'            # e.g. cushmanwakefield.com/en/india/offices/pune
    r'|real[-_]?estate[-_]?(?:companies|agents|developers|in)'
    r')[\-/]',
)

# ── Counters (per-request, reset in discover_leads) ──────────────────────────
class _Stats:
    def __init__(self):
        self.serper_calls   = 0
        self.firecrawl_calls = 0
        self.llm_calls      = 0
        self.filtered_404   = 0
        self.filtered_dir   = 0
        self.duplicates     = 0

_stats = _Stats()

# ── Logging helpers ───────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(tag: str, msg: str) -> None:
    print(f"[{_ts()}] [{tag}] {msg}", flush=True)

# ── URL utilities ─────────────────────────────────────────────────────────────

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _base_url(url: str) -> str:
    """scheme://netloc with no trailing slash."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}".rstrip("/")


def _is_official(url: str) -> bool:
    """Return True if URL is likely an official company website."""
    d = _domain(url)
    if not d:
        return False
    # Reject government portals (RERA, MCA, etc.) — they are not target companies
    if ".gov.in" in d or ".gov.au" in d or ".gov.uk" in d or ".gov.us" in d:
        return False
    for b in _BLOCKED:
        if d == b or d.endswith("." + b):
            return False
    return True

# ── Async HTTP client (shared, with connection pooling) ───────────────────────
# Built lazily to avoid event-loop issues at import time.
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=_T_HTTP,
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
            follow_redirects=True,
        )
    return _http_client

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: DISCOVERY — multi-query Serper
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_query(query: str) -> tuple[str, str]:
    """Split 'Industry companies in City' → (industry, city). Returns (query, '') if not matched."""
    m = re.match(r'^(.+?)\s+(?:companies\s+)?in\s+(.+)$', query, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return query.strip(), ""


def _build_discovery_queries(query: str) -> list[str]:
    """Build 4–5 targeted search queries to surface official company websites."""
    industry, city = _parse_query(query)
    if city:
        return [
            f"{industry} companies in {city} official website",
            f"{industry} companies in {city} contact email phone",
            f"{industry} companies in {city} address",
            f"{industry} companies in {city}",
            f'"{industry}" "{city}" company website',
        ]
    return [
        f"{query} official website",
        f"{query} contact email phone",
        f"{query} company website",
        f"{query}",
    ]


async def _serper_search(client: httpx.AsyncClient, q: str, num: int = 10) -> list[dict]:
    """Run a single Serper search. Returns a list of result dicts."""
    if not SERPER_API_KEY:
        _log("DISCOVERY", "SERPER_API_KEY not set — skipping search")
        return []
    _stats.serper_calls += 1
    try:
        resp = await client.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            content=json.dumps({"q": q, "num": num}).encode(),
            timeout=_T_SERPER,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log("DISCOVERY", f"Serper error for {q!r}: {exc}")
        return []

    results = []

    # Knowledge graph first — highest confidence result
    kg = data.get("knowledgeGraph", {})
    kg_url = (kg.get("website") or "").strip().rstrip("/")
    if kg_url and kg_url.startswith("http"):
        results.append({
            "title":   kg.get("title", "").strip(),
            "link":    kg_url,
            "domain":  _domain(kg_url),
            "snippet": kg.get("description", "").strip(),
            "source":  "knowledge_graph",
        })

    for item in data.get("organic", []):
        link = (item.get("link") or "").strip().rstrip("/")
        if not link.startswith("http"):
            continue
        results.append({
            "title":   (item.get("title") or "").strip(),
            "link":    link,
            "domain":  _domain(link),
            "snippet": (item.get("snippet") or "").strip(),
            "source":  "organic",
        })

    return results


async def discover_candidates(query: str, want: int) -> list[dict]:
    """
    Run multiple Serper queries concurrently, deduplicate by domain,
    filter non-official sources. Returns up to want * _CANDIDATE_MULT candidates.
    """
    target  = want * _CANDIDATE_MULT
    queries = _build_discovery_queries(query)
    _log("DISCOVERY", f"Running {len(queries)} Serper queries, targeting {target} candidates")

    client = _get_http_client()
    tasks  = [_serper_search(client, q, num=min(10, target)) for q in queries]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_domains: set[str] = set()
    candidates:   list[dict] = []
    n_dir = 0
    n_bad_title = 0

    for batch in all_results:
        if isinstance(batch, Exception):
            continue
        for r in batch:
            d     = r.get("domain", "")
            title = r.get("title", "")
            link  = r.get("link", "")

            if not d or not link:
                continue

            # Deduplicate by domain
            if d in seen_domains:
                _stats.duplicates += 1
                continue
            seen_domains.add(d)

            # Reject non-official sources (directories, social, Wikipedia, etc.)
            if not _is_official(link):
                n_dir += 1
                continue

            # Reject pages with 404 / error titles
            if _BLOCKED_TITLE_RE.search(title):
                n_bad_title += 1
                _log("FILTER", f"Rejected (bad title): {title!r} — {link}")
                _stats.filtered_404 += 1
                continue

            # Reject obvious list/aggregator/blog paths (e.g. /blogs/top-10-..., /media/...)
            parsed_path = urlparse(link).path
            if _AGGREGATOR_PATH_RE.search(parsed_path + "/"):
                n_dir += 1
                _log("FILTER", f"Rejected (aggregator path): {link}")
                continue

            # Reject PDF/document direct links
            if parsed_path.lower().endswith(".pdf"):
                n_dir += 1
                _log("FILTER", f"Rejected (PDF): {link}")
                continue

            candidates.append(r)
            if len(candidates) >= target:
                break
        if len(candidates) >= target:
            break

    _log("DISCOVERY", (
        f"Candidates: {len(candidates)} valid | "
        f"{n_dir} directories filtered | "
        f"{n_bad_title} bad-title filtered"
    ))
    return candidates[:target]

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: FIRECRAWL — concurrent multi-page scrape
# ═══════════════════════════════════════════════════════════════════════════════

async def _scrape_one_page(
    client: httpx.AsyncClient,
    url: str,
    full_content: bool,
    sem: asyncio.Semaphore,
) -> dict:
    """Scrape a single URL via Firecrawl. Returns {url, markdown, metadata, error}."""
    if not FIRECRAWL_API_KEY:
        return {"url": url, "markdown": "", "metadata": {}}

    async with sem:
        _stats.firecrawl_calls += 1
        body = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": not full_content,
            "timeout": int(_T_FIRECRAWL * 1000),
        }
        try:
            resp = await client.post(
                FIRECRAWL_URL,
                headers={
                    "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(body).encode(),
                timeout=_T_FIRECRAWL + 5,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                _stats.filtered_404 += 1
            return {"url": url, "markdown": "", "metadata": {}, "error": f"HTTP {exc.response.status_code}"}
        except Exception as exc:
            return {"url": url, "markdown": "", "metadata": {}, "error": str(exc)}

    result = data.get("data") or data
    if isinstance(result, list):
        result = result[0] if result else {}

    return {
        "url":      url,
        "markdown": (result.get("markdown") or "")[:12000],
        "metadata": result.get("metadata") or {},
    }


async def scrape_company_pages(base_url: str, sem: asyncio.Semaphore) -> dict:
    """
    Scrape homepage + contact/about/leadership pages concurrently.
    Returns merged markdown + individual pages list.
    """
    base   = _base_url(base_url)
    client = _get_http_client()
    tasks  = []
    labels = []

    for path, full in _PAGES:
        url = base + path
        tasks.append(_scrape_one_page(client, url, full, sem))
        labels.append(path or "/")

    raw_pages = await asyncio.gather(*tasks, return_exceptions=True)

    pages         = []
    merged_parts  = []
    success_urls  = []
    failed_urls   = []

    for label, result in zip(labels, raw_pages):
        if isinstance(result, Exception):
            failed_urls.append(base + label)
            continue
        md = result.get("markdown", "")
        if md.strip():
            success_urls.append(result["url"])
            merged_parts.append(f"\n\n--- [{label.upper()} PAGE: {result['url']}] ---\n{md}")
            pages.append(result)
        else:
            failed_urls.append(result.get("url", base + label))

    # Check if homepage returned a 404-like title
    homepage_meta = pages[0].get("metadata", {}) if pages else {}
    page_title    = (homepage_meta.get("title") or "").strip()
    if _BLOCKED_TITLE_RE.search(page_title):
        _log("FILTER", f"Rejected after Firecrawl (404 page title): {page_title!r} — {base_url}")
        _stats.filtered_404 += 1
        return {
            "base_url": base_url, "domain": _domain(base_url),
            "pages": [], "markdown": "",
            "pages_visited": {"success": [], "failed": [base_url]},
            "_is_404": True,
        }

    return {
        "base_url":       base_url,
        "domain":         _domain(base_url),
        "pages":          pages,
        "markdown":       "\n".join(merged_parts)[:35000],
        "pages_visited": {"success": success_urls, "failed": failed_urls},
        "_is_404":        False,
    }

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: EXTRACTION — emails, phones, address, company name
# ═══════════════════════════════════════════════════════════════════════════════

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_EMAIL_JUNK_LOCALS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "bounce", "bounces",
    "unsubscribe", "webmaster", "hostmaster", "abuse",
    "spam", "admin", "test", "example",
})
_EMAIL_JUNK_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".pdf", ".css", ".js", ".woff", ".ttf", ".ico",
})
_EMAIL_JUNK_DOMS = frozenset({
    "sentry.io", "wixpress.com", "example.com", "example.org",
    "test.com", "mailchimp.com", "sendgrid.net", "googletagmanager.com",
    "cloudfront.net", "amazonaws.com",
})


def _is_junk_email(addr: str) -> bool:
    addr  = addr.lower().strip()
    local, _, dom = addr.partition("@")
    if not dom or "." not in dom:
        return True
    if any(addr.endswith(e) for e in _EMAIL_JUNK_EXTS):
        return True
    if local in _EMAIL_JUNK_LOCALS:
        return True
    if dom in _EMAIL_JUNK_DOMS or "/" in addr:
        return True
    if local.isdigit() or len(local) < 2 or len(dom) < 4:
        return True
    return False


_PHONE_PATTERNS = [
    re.compile(r'\+91[\s\-]?[6-9]\d{4}[\s\-]?\d{5}'),
    re.compile(r'\b0\d{2,4}[\s\-]\d{6,8}\b'),
    re.compile(r'\+[1-9]\d{0,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,6}'),
    re.compile(r'\(?\b[2-9]\d{2}\)?[\s\-]\d{3}[\s\-]\d{4}\b'),
    re.compile(r'\b1[\s\-]?8[0-9]{2}[\s\-]\d{3}[\s\-]\d{4}\b'),
    re.compile(r'\b\d{5}[\s\-]\d{5}\b'),
    re.compile(r'\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b'),
]
_YEAR_RE = re.compile(r'^(19|20)\d{2}$')
_ZIP_RE  = re.compile(r'^\d{4,6}$')


def _extract_phones(text: str) -> list[str]:
    seen: set[str] = set()
    found = []
    for pat in _PHONE_PATTERNS:
        for m in pat.finditer(text):
            raw    = m.group(0).strip()
            digits = re.sub(r'\D', '', raw)
            if not (7 <= len(digits) <= 15):
                continue
            if _YEAR_RE.match(digits):
                continue
            if _ZIP_RE.match(digits) and not raw.startswith("+"):
                continue
            if re.search(r'[a-zA-Z]', raw):
                continue
            key = digits
            if key not in seen:
                seen.add(key)
                found.append(re.sub(r'[\s\-]+', ' ', raw).strip())
    return found

_INDIAN_CITIES = [
    "Pune", "Mumbai", "Delhi", "Bangalore", "Bengaluru", "Hyderabad",
    "Ahmedabad", "Chennai", "Kolkata", "Surat", "Jaipur", "Lucknow",
    "Nagpur", "Indore", "Thane", "Bhopal", "Pimpri", "Nashik",
    "Navi Mumbai", "Noida", "Gurugram", "Gurgaon", "Chandigarh",
    "Pimpri-Chinchwad", "PCMC", "Aurangabad", "Solapur", "Mysore",
    "Vadodara", "Rajkot", "Coimbatore", "Vizag", "Visakhapatnam",
]
_INDIAN_STATES = [
    "Maharashtra", "Karnataka", "Tamil Nadu", "Telangana", "Gujarat",
    "Rajasthan", "Uttar Pradesh", "West Bengal", "Delhi", "Punjab",
    "Haryana", "Madhya Pradesh", "Bihar", "Andhra Pradesh", "Kerala",
    "Goa", "Odisha", "Assam", "Jharkhand", "Chhattisgarh",
]
_PIN_RE        = re.compile(r'(?<!\d)([1-9]\d{5})(?!\d)')
_ADDR_LABEL_RE = re.compile(
    r'(?i)(?:address|location|office|registered\s+office|corporate\s+office'
    r'|head\s*quarters?|hq|regd\.?\s+office)\s*[:\-–]?\s*(.+)',
)


def _extract_address(markdown: str) -> dict:
    """Extract structured address from scraped markdown."""
    lines = markdown.split("\n")
    block: list[str] = []

    # Pass 1: explicit address label
    for i, line in enumerate(lines):
        m = _ADDR_LABEL_RE.match(line.strip())
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) > 5:
                block = [candidate]
                for j in range(1, 4):
                    if i + j < len(lines):
                        nxt = lines[i + j].strip()
                        if nxt and len(nxt) > 3:
                            block.append(nxt)
                        else:
                            break
                break

    # Pass 2: PIN code proximity
    if not block:
        for i, line in enumerate(lines):
            if _PIN_RE.search(line):
                start = max(0, i - 3)
                block = [l.strip() for l in lines[start:i + 1] if l.strip()]
                break

    if not block:
        return {"full": "", "city": "", "state": "", "country": "", "postal_code": ""}

    full = ", ".join(p for p in block if p)

    # Reject if the assembled text looks like a paragraph (>25 words), not an address
    if len(full.split()) > 25:
        # Try to salvage just the first line if it contains a city/PIN
        first_line = block[0] if block else ""
        has_pin  = bool(_PIN_RE.search(first_line))
        has_city = any(re.search(r'\b' + re.escape(c) + r'\b', first_line, re.IGNORECASE)
                       for c in _INDIAN_CITIES)
        if has_pin or has_city:
            full = first_line
        else:
            return {"full": "", "city": "", "state": "", "country": "", "postal_code": ""}

    postal = ""
    for part in block:
        pm = _PIN_RE.search(part)
        if pm:
            postal = pm.group(1)
            break

    city = next(
        (c for part in block for c in _INDIAN_CITIES
         if re.search(r'\b' + re.escape(c) + r'\b', part, re.IGNORECASE)),
        "",
    )
    state = next(
        (s for part in block for s in _INDIAN_STATES
         if re.search(r'\b' + re.escape(s) + r'\b', part, re.IGNORECASE)),
        "",
    )
    country = "India" if (postal or city or state or "india" in full.lower()) else ""
    return {"full": full, "city": city, "state": state, "country": country, "postal_code": postal}


_GENERIC_TITLES = frozenset({
    "contact", "contact us", "contactus", "get in touch", "reach us",
    "home", "welcome", "index", "about", "about us", "services",
    "solutions", "products", "page not found", "404", "error",
    "login", "sign in", "sign up", "register",
})
_STRIP_SUFFIX_RE = re.compile(
    r'[\|\-–—·]\s*(?:contact\s*(?:us)?|home|about\s*(?:us)?|'
    r'services|solutions|products|index)\s*$',
    re.IGNORECASE,
)
# Strip trailing geo/marketing suffixes: "| Homes in Pune", "| Properties in Mumbai"
_STRIP_GEO_SUFFIX_RE = re.compile(
    r'\s*[\|\-–—]\s*(?:homes?|properties|projects?|apartments?|real\s+estate|'
    r'builders?|developers?|realty)\s+in\s+.+$',
    re.IGNORECASE,
)
# Strip "Official Website" type suffixes and ® ™ © symbols
_STRIP_OFFICIAL_RE = re.compile(
    r'\s*[\|\-\u2013\u2014]?\s*(?:official\s+(?:website|site|web\s*site)|'
    r'website|official)\s*$'
    r'|[®™©]\s*(?:official\s+\S+.*|\.\.\.*|\s*$)',
    re.IGNORECASE,
)
# Strip brand tagline prefixes like "Pune's Leading Real Estate Brand | VTP Realty®"
_STRIP_BRAND_PREFIX_RE = re.compile(
    r"(?i)^(?:india'?s?|pune'?s?|mumbai'?s?|bangalore'?s?|delhi'?s?|hyderabad'?s?)?\s*"
    r"(?:leading|top|best|premier|most\s+trusted|award\s*winning|#\d)\s+"
    r"(?:real\s+estate|property|builder|developer|realty)\s+"
    r"(?:brand|company|developer|builder|group|firm)\s*[|—\-–]\s*",
)


def extract_company_info(scrape: dict, search_result: dict) -> dict:
    """Extract company name, emails, phones, address from scraped markdown."""
    md       = scrape.get("markdown", "")
    metadata: dict = {}
    for page in scrape.get("pages", []):
        m = page.get("metadata") or {}
        if m:
            metadata = {**metadata, **m}

    # ── Company name: og:site_name > title split > serper title > domain ──────
    og_name    = (metadata.get("og:site_name") or "").strip()
    raw_title  = (metadata.get("title") or "").strip()

    def _clean_title(t: str) -> str:
        """Strip marketing/geo suffixes from a page title."""
        t = _STRIP_GEO_SUFFIX_RE.sub("", t).strip()
        t = _STRIP_OFFICIAL_RE.sub("", t).strip()
        t = _STRIP_BRAND_PREFIX_RE.sub("", t).strip()
        t = _STRIP_SUFFIX_RE.sub("", t).strip()
        return t

    title_name = ""
    if raw_title:
        cleaned_raw = _clean_title(raw_title)
        for sep in (" | ", " — ", " - ", " · ", " > "):
            parts = cleaned_raw.split(sep)
            for candidate in [parts[-1].strip(), parts[0].strip()]:
                # Prefer the LAST segment (usually brand name after separator)
                # But also try first segment. Pick shortest non-generic.
                if candidate and candidate.lower() not in _GENERIC_TITLES and len(candidate) >= 2:
                    if len(candidate) < len(cleaned_raw):  # it's a real segment, not the whole title
                        title_name = candidate
                        break
            if title_name:
                break
        if not title_name:
            if cleaned_raw and cleaned_raw.lower() not in _GENERIC_TITLES and len(cleaned_raw) >= 2:
                title_name = cleaned_raw

    # Serper title cleaning — "Real Estate Developers in Pune — Nyati Group" → "Nyati Group"
    serper_raw   = search_result.get("title", "")
    serper_title = _clean_title(serper_raw)
    # Strip SEO prefixes like "Real Estate Developers in Pune — "
    serper_title = re.sub(
        r'(?i)^(?:real\s+estate\s+)?(?:companies|developers|builders|brokers|agents)\s+in\s+\S+\s*[—\-–|]\s*',
        "", serper_title,
    ).strip()
    if serper_title.lower() in _GENERIC_TITLES:
        serper_title = ""
    if serper_title and (_BLOCKED_TITLE_RE.search(serper_title) or _AGGREGATOR_NAME_RE.search(serper_title)):
        serper_title = ""

    domain_raw  = search_result.get("domain", "")
    domain_name = domain_raw.split(".")[0].replace("-", " ").title() if domain_raw else ""

    # Priority: og:site_name → page title segment → serper title → domain
    company_name = og_name or title_name or serper_title or domain_name

    # Emails
    emails: set[str] = set()
    for line in md.split("\n"):
        for addr in _EMAIL_RE.findall(line):
            al = addr.lower()
            if not _is_junk_email(al):
                emails.add(al)

    phones  = _extract_phones(md)
    addr    = _extract_address(md)
    sources = list(scrape.get("pages_visited", {}).get("success", []))

    return {
        "company_name":     company_name,
        "website":          search_result.get("link", ""),
        "domain":           domain_raw,
        "emails":           sorted(emails)[:6],
        "phones":           phones[:5],
        "address":          addr["full"],
        "city":             addr["city"],
        "state":            addr["state"],
        "country":          addr["country"],
        "postal_code":      addr["postal_code"],
        "description":      (metadata.get("description") or
                             metadata.get("og:description") or
                             search_result.get("snippet", "")),
        "source_url":       search_result.get("link", ""),
        "sources":          sources,
        "pages_visited":    scrape.get("pages_visited", {"success": [], "failed": []}),
        "_scraped_pages":   scrape.get("pages", []),
        "_merged_markdown": md,
        "research_source":  "serper_firecrawl",
        "research_sources": sources,
        "email_status":     "",
        "phone_status":     "",
        "founder_name":     None,
        "_serper_title":    serper_raw,
    }

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: CONTACT GAP SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

async def _gap_serper_snippets(client: httpx.AsyncClient, q: str) -> str:
    """Run a targeted Serper query and return merged snippet text."""
    if not SERPER_API_KEY:
        return ""
    _stats.serper_calls += 1
    try:
        resp = await client.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            content=json.dumps({"q": q, "num": 5}).encode(),
            timeout=_T_SERPER,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""
    return "\n".join(
        item.get("snippet", "")
        for item in data.get("organic", [])[:5]
        if item.get("snippet")
    )


_LEADER_TITLE_RE = re.compile(
    r'(?i)(founder|co-founder|ceo|chief\s+executive|managing\s+director'
    r'|chairman|president|director|md\b)',
)
_NAME_RE = re.compile(r'\b([A-Z][a-z]{1,20})\s+([A-Z][a-z]{1,20})\b')


async def contact_gap_search(company: dict) -> dict:
    """
    For companies still missing email/phone/address/founder after Firecrawl,
    run targeted Serper searches to fill gaps.
    Never fabricates — only uses text from Serper snippets.
    """
    name   = company.get("company_name", "")
    domain = company.get("domain", "")
    emails = set(company.get("emails", []))
    phones = set(company.get("phones", []))
    addr   = company.get("address", "")
    founder = company.get("founder_name")

    gap_queries: list[tuple[str, str]] = []
    if not emails:
        # Try both domain-scoped and general searches to maximize email recall
        if domain:
            gap_queries.append(("email", f'"{name}" email site:{domain}'))
        gap_queries.append(("email_general", f'"{name}" contact email Pune'))
    if not phones:
        q = f'"{name}" phone number site:{domain}' if domain else f'"{name}" phone number'
        gap_queries.append(("phone", q))
    if not addr:
        city = company.get("city", "")
        gap_queries.append(("address", f'"{name}" office address {city}'.strip()))
    if not founder:
        gap_queries.append(("founder", f'"{name}" founder CEO managing director'))

    if not gap_queries:
        return company

    _log("CONTACT_SEARCH", f"{name}: gap fields={[g[0] for g in gap_queries]}")

    client = _get_http_client()
    tasks  = [_gap_serper_snippets(client, q) for _, q in gap_queries]
    texts  = await asyncio.gather(*tasks, return_exceptions=True)

    merged = "\n".join(t for t in texts if isinstance(t, str))

    # Extract new emails from snippets
    new_emails: set[str] = set()
    for addr_str in _EMAIL_RE.findall(merged):
        al = addr_str.lower()
        if not _is_junk_email(al):
            email_dom = al.split("@")[-1]
            # Accept if: matches company domain, OR domain is unknown (no domain restriction)
            if domain and (email_dom == domain or email_dom.endswith("." + domain)):
                new_emails.add(al)
            elif not domain:
                new_emails.add(al)

    # Extract new phones
    new_phones = _extract_phones(merged)

    # Extract address from snippets
    updated = dict(company)
    if not updated.get("address"):
        addr_info = _extract_address(merged)
        if addr_info["full"]:
            updated.update({
                "address":     addr_info["full"],
                "city":        addr_info["city"]    or updated.get("city", ""),
                "state":       addr_info["state"]   or updated.get("state", ""),
                "country":     addr_info["country"] or updated.get("country", ""),
                "postal_code": addr_info["postal_code"] or updated.get("postal_code", ""),
            })

    # Extract founder name from snippets
    if not founder:
        for line in merged.split("\n"):
            if _LEADER_TITLE_RE.search(line):
                m = _NAME_RE.search(line)
                if m:
                    updated["founder_name"] = m.group(0)
                    break

    all_emails = list(emails | new_emails)
    # Dedup phones by digits
    seen_digits: set[str] = set()
    all_phones: list[str] = []
    for p in list(phones) + new_phones:
        d = re.sub(r'\D', '', p)
        if d not in seen_digits:
            seen_digits.add(d)
            all_phones.append(p)

    updated["emails"] = all_emails[:6]
    updated["phones"] = all_phones[:5]
    if not updated["emails"]:
        updated["email_status"] = "not_publicly_found"
    if not updated["phones"]:
        updated["phone_status"] = "not_publicly_found"

    return updated

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5: NORMALIZE — map to the shape the pipeline expects
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_company(c: dict) -> dict:
    """
    Map discovery output → shape expected by
    VALIDATE → CONFIDENCE → ENRICH → VERIFY → DEDUPLICATE pipeline.
    Preserves _scraped_pages and _merged_markdown for ENRICH/VERIFY stages.
    """
    emails = c.get("emails", [])
    phones = c.get("phones", [])
    email  = emails[0] if emails else None
    company_number = phones[0] if phones else None
    sources = c.get("sources") or c.get("research_sources") or []

    return {
        # Identity
        "company_name":     c.get("company_name", ""),
        "name":             c.get("company_name", ""),
        "website":          c.get("website", ""),
        "domain":           c.get("domain", ""),
        # Legacy arrays (pipeline reads these)
        "emails":           emails,
        "phones":           phones,
        # Address
        "address":          c.get("address", ""),
        "city":             c.get("city", ""),
        "state":            c.get("state", ""),
        "country":          c.get("country", "India"),
        "postal_code":      c.get("postal_code", ""),
        # Enriched contact fields
        "email":            email,
        "company_number":   company_number,
        "founder_name":     c.get("founder_name"),
        "founder_number":   None,
        "source_url":       c.get("source_url") or c.get("website", ""),
        "sources":          sources,
        # Contact gap status
        "email_status":     c.get("email_status", ""),
        "phone_status":     c.get("phone_status", ""),
        # Metadata
        "description":      c.get("description", ""),
        "confidence":       0.0,
        "last_verified":    None,
        # Research source trace
        "research_source":  "serper_firecrawl",
        "research_sources": sources,
        # Pipeline internal keys (used by ENRICH + VERIFY, stripped before storage)
        "_scraped_pages":   c.get("_scraped_pages", []),
        "_merged_markdown": c.get("_merged_markdown", ""),
        "pages_visited":    c.get("pages_visited", {"success": [], "failed": []}),
        # Pre-validated lists (VALIDATE stage will re-check)
        "validated_emails": emails,
        "validated_phones": [{"number": p, "type": "unknown"} for p in phones],
        "services":         [],
        "socials":          {},
    }

# ═══════════════════════════════════════════════════════════════════════════════
# Per-company processing + public entry point
# ═══════════════════════════════════════════════════════════════════════════════

async def _process_candidate(
    search_result: dict,
    sem: asyncio.Semaphore,
) -> Optional[dict]:
    """
    Scrape + extract + gap-search + context-verify one candidate.
    Returns a normalized company dict, or None on hard failure.
    """
    url  = search_result["link"]
    name = search_result.get("title", url)

    try:
        # FIRECRAWL
        scrape = await scrape_company_pages(url, sem)
        if scrape.get("_is_404"):
            _log("FILTER", f"Skipped (404 confirmed by Firecrawl): {url}")
            return None

        # EXTRACTION
        company = extract_company_info(scrape, search_result)

        # CONTACT GAP (fills missing email/phone/address/founder from Serper snippets)
        company = await contact_gap_search(company)

        # CONTEXT VERIFICATION (verify each field is actually associated with this company)
        verify_sem = asyncio.Semaphore(_vs._SEM_SIZE)
        company = await _vs.verify_company(company, verify_sem)

        # NORMALIZE
        normalized = normalize_company(company)

        fv = company.get("_field_verification", {})
        _log("EXTRACTION", (
            f"{normalized['company_name'] or name} | "
            f"domain={normalized['domain']} | "
            f"sources={len(normalized['sources'])} | "
            f"email={'✓ ' + str(normalized['email']) if normalized['email'] else '✗'} | "
            f"phone={'✓' if normalized['company_number'] else '✗'} | "
            f"address={'✓' if normalized['address'] else '✗'} | "
            f"founder={'✓ ' + str(normalized['founder_name']) + ' [' + fv.get('founder',{}).get('status','') + ']' if normalized['founder_name'] else '✗'}"
        ))
        return normalized

    except Exception as exc:
        _log("EXTRACTION", f"Failed for {url}: {type(exc).__name__}: {exc}")
        return None


async def discover_leads(query: str, num: int) -> dict:
    """
    Full Serper+Firecrawl discovery pipeline.

    Returns a dict matching what src/routes/leads.py expects:
        {query, timestamp, companies: [normalized_dicts], total, status, _stats}

    Hermes is NEVER called. Not as a fallback. Not at all.
    """
    global _stats
    _stats = _Stats()   # reset per-request counters
    t0 = time.monotonic()

    _log("DISCOVERY", f"START — query={query!r}  count={num}  [NO HERMES]")

    # Step 1: collect candidates (3× the requested count)
    candidates = await discover_candidates(query, num)
    if not candidates:
        _log("DISCOVERY", "No candidates found — check SERPER_API_KEY")
        return {
            "query":     query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "companies": [],
            "total":     0,
            "status":    "no_candidates",
            "_stats":    vars(_stats),
        }

    _log("FIRECRAWL", f"Scraping {len(candidates)} candidates concurrently (sem={_FIRECRAWL_CONCURRENCY})")

    # Shared semaphore for all Firecrawl calls across all companies
    sem = asyncio.Semaphore(_FIRECRAWL_CONCURRENCY)

    # Steps 2–5: scrape + extract + gap-search all candidates concurrently
    tasks   = [_process_candidate(c, sem) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    companies: list[dict] = [
        r for r in results
        if isinstance(r, dict) and r.get("company_name")
    ]

    # Deduplicate by domain (route will do a second pass by website URL)
    seen_domains: set[str] = set()
    unique: list[dict] = []
    for c in companies:
        d = c.get("domain", "").lower()
        if d and d in seen_domains:
            _stats.duplicates += 1
            continue
        if d:
            seen_domains.add(d)
        unique.append(c)

    elapsed = time.monotonic() - t0

    _log("DISCOVERY", (
        f"DONE in {elapsed:.1f}s — "
        f"candidates={len(candidates)}  valid={len(unique)}  "
        f"email={sum(1 for c in unique if c.get('email'))}/{len(unique)}  "
        f"phone={sum(1 for c in unique if c.get('company_number'))}/{len(unique)}  "
        f"address={sum(1 for c in unique if c.get('address'))}/{len(unique)}  "
        f"founder={sum(1 for c in unique if c.get('founder_name'))}/{len(unique)}"
    ))
    _log("DISCOVERY", (
        f"STATS — serper_calls={_stats.serper_calls}  "
        f"firecrawl_calls={_stats.firecrawl_calls}  "
        f"llm_calls={_stats.llm_calls}  "
        f"filtered_404={_stats.filtered_404}  "
        f"duplicates={_stats.duplicates}"
    ))

    return {
        "query":     query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "companies": unique,
        "total":     len(unique),
        "status":    "success",
        "_elapsed":  round(elapsed, 1),
        "_stats":    vars(_stats),
    }
