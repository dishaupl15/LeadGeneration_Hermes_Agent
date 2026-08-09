#!/usr/bin/env python3
"""
Lead Generation Engine — Research Module
=========================================
Workflow:
  1.  DISCOVER    — Search Google via Serper API
  2.  SCRAPE      — Visit company pages via Firecrawl (home, contact, about, team, services, projects)
  3.  EXTRACT     — Pull raw emails, phones, name, description, services, socials from markdown
  4.  NORMALIZE   — Map fields to a consistent shape (merge_company_data)
  5.  VALIDATE    — Reject junk emails/phones; classify surviving phones
  6.  CONFIDENCE  — Score 0.0–1.0 based only on evidence actually found
  7.  ENRICH      — Discover founder name via Serper; extract publicly listed professional
                    contact from official About/Team/Leadership pages
  8.  VERIFY      — Cross-check all contact fields against already-scraped Firecrawl pages;
                    set last_verified and update confidence without any new HTTP calls
  9.  STORE       — (done upstream in routes/leads.py via MongoDB upsert)

Usage:
  python3 leadgen.py --query "AI consulting firms in New York"
  python3 leadgen.py --query "Real estate companies in Pune" --num 5 --pretty
  python3 leadgen.py --query "..." --jsonl   # one JSON object per line
"""

import os
import json
import re
import sys
import time
import argparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Optional

# ── Load .env BEFORE reading key constants ─────────────────────────────────
def _load_env():
    """Load .env from project root into environment (does not override existing)."""
    env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".env"
    )
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()

# ── Config ──────────────────────────────────────────────────────────────────
SERPER_API_KEY = os.environ.get("SERPER_API_KEY") or ""
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY") or ""

SERPER_URL = "https://google.serper.dev/search"
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"

DEFAULT_NUM = 10
REQUEST_DELAY = 1.0   # seconds between Firecrawl calls (per-page)
COMPANY_DELAY = 1.5   # extra delay between companies

# ── Junk-email filters ──────────────────────────────────────────────────────
# Local-parts that are system/automated addresses, never real business contacts
_EMAIL_JUNK_LOCALPARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "bounce", "bounces",
    "unsubscribe", "webmaster", "hostmaster", "abuse",
    "spam", "admin@example", "test", "example",
    "support@example", "info@example",
}

# File extensions that appear after @ in image/asset CDN paths
_EMAIL_JUNK_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".pdf", ".css", ".js", ".woff", ".ttf", ".ico",
    ".mp4", ".mp3", ".zip", ".tar", ".gz",
}

# Domains that are never real company contact addresses
_EMAIL_JUNK_DOMAINS = {
    "sentry.io", "wixpress.com", "squarespace.com", "shopify.com",
    "wordpress.com", "google.com", "googletagmanager.com",
    "amazonaws.com", "cloudfront.net", "example.com", "example.org",
    "test.com", "mailchimp.com", "sendgrid.net",
}

# ── Phone patterns that are NOT phone numbers ───────────────────────────────
# Regex patterns matched against the *digit-only* string of a candidate phone

# Years: 4-digit strings 1900–2099
_PHONE_YEAR_RE    = re.compile(r'^(19|20)\d{2}$')
# Pure version strings: digits separated only by dots (e.g. 3.2.1, 10.0.2)
_PHONE_VERSION_RE = re.compile(r'^\d+\.\d+')
# Short postal codes: exactly 4–6 digits with nothing else
_PHONE_ZIP_RE     = re.compile(r'^\d{4,6}$')

# ── Helpers ─────────────────────────────────────────────────────────────────

def _json_request(url: str, headers: dict, body: dict, timeout: int = 30) -> dict:
    """POST JSON, return parsed response."""
    data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code} from {url}: {body_text}")
    except URLError as e:
        raise RuntimeError(f"Network error for {url}: {e.reason}")


def _clean_url(url: str) -> str:
    """Normalise URL — strip trailing slash, fragment, tracking params."""
    url = url.strip().rstrip("/")
    if "#" in url:
        url = url.split("#")[0]
    return url


def _domain(url: str) -> str:
    """Extract domain from URL (e.g. https://www.example.com/page -> example.com)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "").lower()


# ── Non-official domain blocklist ───────────────────────────────────────────
# Domains (or domain suffixes) that are directories, social networks, document
# hosts, or aggregator sites — never the actual company website.
_NON_OFFICIAL_DOMAINS: frozenset[str] = frozenset({
    # Social / professional networks
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "pinterest.com", "tiktok.com",
    # Document / slide hosts
    "scribd.com", "slideshare.net", "issuu.com", "docplayer.net",
    "academia.edu",
    # Business directories
    "justdial.com", "indiamart.com", "tradeindia.com", "sulekha.com",
    "yellowpages.com", "yelp.com", "clutch.co", "glassdoor.com",
    "ambitionbox.com", "zaubacorp.com", "tofler.in", "mca.gov.in",
    "companieshouse.gov.uk", "crunchbase.com", "bloomberg.com",
    "dnb.com", "zoominfo.com", "rocketreach.co",
    # News / general portals
    "wikipedia.org", "wikidata.org", "wikimedia.org",
    "medium.com", "substack.com", "quora.com", "reddit.com",
    "tumblr.com", "wordpress.com", "blogger.com",
    "timesofindia.com", "economictimes.com", "moneycontrol.com",
    "livemint.com", "businesstoday.in", "hindustantimes.com",
    "ndtv.com", "thehindu.com", "deccanherald.com",
    # Job boards
    "naukri.com", "indeed.com", "monster.com", "internshala.com",
    "shine.com", "foundit.in",
    # Maps / review
    "maps.google.com", "google.com", "bing.com",
    "tripadvisor.com", "trustpilot.com",
    # Real estate portals / property directories (not company sites)
    "99acres.com", "magicbricks.com", "housing.com", "makaan.com",
    "commonfloor.com", "nobroker.in", "squareyards.com",
    # News aggregators
    "indiatimes.com", "timesofindia.com", "economictimes.com",
    "moneycontrol.com", "livemint.com", "businesstoday.in",
    "hindustantimes.com", "ndtv.com", "thehindu.com",
    "deccanherald.com", "firstpost.com", "news18.com",
    # App stores
    "play.google.com", "apps.apple.com",
})


def _is_official_url(url: str) -> bool:
    """
    Return True if this URL is likely an official company website.

    Rejects:
    - Social networks (linkedin.com, facebook.com, …)
    - Document hosts (scribd.com, slideshare.net, …)
    - Business directories (justdial.com, indiamart.com, …)
    - News / wiki / general portals
    - Job boards, map sites, app stores

    Accepts everything else (any domain that is NOT in the blocklist).
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().lstrip("www.")
    except Exception:
        return False

    # Exact match or subdomain of a blocked domain
    for blocked in _NON_OFFICIAL_DOMAINS:
        if host == blocked or host.endswith("." + blocked):
            return False

    # Path-based heuristic: long Scribd-style document paths
    # e.g. scribd.com/document/… already blocked above, but guard others
    path = parsed.path.lower()
    if "/document/" in path and ("scribd" in host or "docplayer" in host):
        return False

    return True


def _filter_official_results(results: list[dict]) -> list[dict]:
    """
    Remove non-official URLs from a Serper organic results list.
    If ALL results are non-official (edge case), return the original list
    so the pipeline always has something to work with.
    """
    official = [r for r in results if _is_official_url(r.get("link", ""))]
    if not official:
        # Fallback: return originals so pipeline doesn't silently return nothing
        print(
            "   [Serper] All results were non-official domains — returning unfiltered list",
            file=sys.stderr,
        )
        return results
    removed = len(results) - len(official)
    if removed:
        print(f"   [Serper] Filtered out {removed} non-official URL(s)", file=sys.stderr)
    return official


# ── Step 1: Serper Google Search ────────────────────────────────────────────

def _build_search_query(user_query: str) -> str:
    """
    Enrich the raw user query so Google returns pages that are more likely
    to be official company websites with contact information (email, phone, address).

    Strategy:
    - If the query already looks like a targeted search (contains site:, @, etc.)
      leave it alone.
    - Otherwise append industry-specific contact-discovery keywords so Serper
      surfaces actual company websites rather than social profiles, document
      hosts, or generic directory listings.
    """
    q = user_query.strip()
    # Don't touch already-specific queries
    if any(kw in q.lower() for kw in ("site:", "email", "phone", "contact", "@")):
        return q
    # Append focused contact-discovery hint targeting official websites
    # "address phone email" pushes Serper toward contact pages on company domains
    return f"{q} official website address phone email"


def search_companies(query: str, num: int = DEFAULT_NUM) -> list[dict]:
    """
    Search Google via Serper API.
    Returns list of result dicts with keys: title, link, snippet, position.
    """
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY not set. Add it to .env or export it.")

    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    enriched_query = _build_search_query(query)
    body = {"q": enriched_query, "num": num}

    print(f"   [Serper] Query: {enriched_query!r}", file=sys.stderr)
    data = _json_request(SERPER_URL, headers, body)

    organic = data.get("organic", [])
    results = []
    for item in organic:
        link = _clean_url(item.get("link", ""))
        if not link or not link.startswith("http"):
            continue
        results.append({
            "position": item.get("position", 0),
            "title": item.get("title", "").strip(),
            "link": link,
            "domain": _domain(link),
            "snippet": item.get("snippet", "").strip(),
        })

    # ── Filter out non-official URLs ───────────────────────────────────────
    # Social networks, document hosts, and news/directory sites are not
    # company websites.  Remove them so the pipeline scrapes real company
    # pages rather than LinkedIn profiles, Facebook groups, or Scribd docs.
    results = _filter_official_results(results)

    # Enrich with knowledge graph if available
    kg = data.get("knowledgeGraph")
    if kg:
        kg_url = _clean_url(kg.get("website", ""))
        if kg_url:
            results.insert(0, {
                "position": 0,
                "title": kg.get("title", ""),
                "link": kg_url,
                "domain": _domain(kg_url),
                "snippet": kg.get("description", ""),
                "knowledge_graph": {
                    "type": kg.get("type", ""),
                    "title": kg.get("title", ""),
                    "description": kg.get("description", ""),
                    "website": kg_url,
                },
            })

    return results


# ── Step 2–3: Firecrawl Multi-Page Scrape ────────────────────────────────────

# Page paths to try for each company website.
# Ordered by expected information density — contact info first, then about,
# team/leadership, services, projects.
# Each list is tried in order; the first URL that succeeds is used.
_PAGE_PATHS = {
    "home": ["/", ""],
    "contact": [
        "/contact", "/contact-us", "/contact/", "/contact-us/",
        "/get-in-touch", "/reach-us", "/reach-us/", "/enquiry",
        "/enquiry/", "/contactus", "/contact.php", "/contact.html",
        "/connect", "/connect-with-us", "/touch", "/talk-to-us",
        "/write-to-us", "/contact_us", "/contactus.html", "/contact_us.php",
    ],
    "about": [
        "/about", "/about-us", "/about/", "/about-us/",
        "/our-story", "/company", "/who-we-are", "/overview",
        "/about.php", "/about.html", "/about-the-company", "/corporate",
        "/profile", "/company-profile",
    ],
    "team": [
        "/team", "/our-team", "/leadership", "/management",
        "/founders", "/people", "/board",
    ],
    "services": [
        "/services", "/solutions", "/what-we-do", "/our-services",
        "/capabilities", "/offerings", "/products",
    ],
    "projects": [
        "/projects", "/portfolio", "/case-studies", "/our-work",
        "/work", "/past-projects", "/completed-projects",
    ],
}

# Pages where we DISABLE onlyMainContent so footer/header contact info is kept
_FULL_CONTENT_PAGES = {"contact", "home", "about", "team"}


def _build_page_urls(base_url: str) -> dict[str, str]:
    """
    Generate a candidate URL for each page category from a company's base domain.
    Uses only the scheme+netloc so existing paths in the search result URL
    don't pollute the guesses.
    """
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    # Normalise to scheme://netloc only
    base = f"{parsed.scheme}://{parsed.netloc}"
    pages = {}
    seen: set[str] = set()
    for category, paths in _PAGE_PATHS.items():
        for path in paths:
            full = base + path
            if full not in seen:
                seen.add(full)
                pages[category] = full
                break  # first candidate per category
    return pages


def _scrape_single(url: str, timeout: int = 30, full_content: bool = False) -> dict:
    """
    Scrape a single URL via Firecrawl.

    full_content=True  → onlyMainContent=False  (preserves header/footer)
    full_content=False → onlyMainContent=True   (cleaner body text)

    Returns: { url, markdown, metadata }
    """
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": not full_content,
        "timeout": timeout * 1000,
    }

    data = _json_request(FIRECRAWL_SCRAPE_URL, headers, body, timeout=timeout + 10)

    result = data if "data" not in data else data["data"]
    if isinstance(result, list):
        result = result[0] if result else {}

    return {
        "url": _clean_url(url),
        "markdown": result.get("markdown", "")[:12000],
        "metadata": result.get("metadata", {}),
    }


def scrape_company(base_url: str, timeout: int = 30) -> dict:
    """
    Scrape a company by visiting multiple pages.
    Contact and home pages are scraped with full content (headers/footers included)
    so phone/email in navigation or footer is captured.
    All other pages use main-content-only mode for cleaner text.

    Returns: { url, domain, pages, markdown (merged), metadata, failed_pages }
    """
    if not FIRECRAWL_API_KEY:
        raise RuntimeError("FIRECRAWL_API_KEY not set. Add it to .env or export it.")

    domain = _domain(base_url)
    page_urls = _build_page_urls(base_url)
    pages = []
    failed_pages = []
    merged_markdown_parts = []
    total_chars = 0
    MAX_MERGE_CHARS = 25000

    # Scrape order: contact first so emails/phones are at the top of merged text
    scrape_order = ["contact", "home", "about", "team", "services", "projects"]

    for category in scrape_order:
        url = page_urls.get(category)
        if not url:
            continue
        full = category in _FULL_CONTENT_PAGES
        try:
            result = _scrape_single(url, timeout=timeout, full_content=full)
            md = result.get("markdown", "")
            if md.strip():
                tagged = f"\n\n--- [{category.upper()} PAGE: {url}] ---\n{md}"
                remaining = MAX_MERGE_CHARS - total_chars
                if len(tagged) > remaining:
                    tagged = tagged[:remaining]
                merged_markdown_parts.append(tagged)
                total_chars += len(tagged)
            pages.append(result)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            failed_pages.append({"category": category, "url": url, "error": str(e)})

    # Metadata: home page takes priority, earlier pages overwrite later
    # Build metadata with home page taking highest priority.
    # Iterate in reverse (projects → ... → contact) so contact page is
    # processed last and home page wins final merge.
    merged_metadata: dict = {}
    for p in reversed(pages):
        m = p.get("metadata", {})
        if m:
            merged_metadata = {**merged_metadata, **m}

    # og:site_name is the most reliable company name signal.
    # If home page provided it, keep it; otherwise let extract_business_info
    # work from H1s in the markdown.
    return {
        "url": _clean_url(base_url),
        "domain": domain,
        "pages": pages,
        "markdown": "\n".join(merged_markdown_parts)[:MAX_MERGE_CHARS],
        "metadata": merged_metadata,
        "failed_pages": failed_pages,
    }


# ── Step 4: Extract Business Information ────────────────────────────────────

# Keywords that indicate a service/product offering (for services extraction)
_SERVICE_KEYWORDS = [
    "we offer", "services", "solutions", "we provide", "products", "we specialize",
    "capabilities", "what we do", "our services", "we build", "we design",
    "we develop", "we deliver", "platform", "consulting", "development",
]

# Keywords that indicate a project/portfolio item
_PROJECT_KEYWORDS = [
    "project", "portfolio", "case stud", "our work", "client", "deployment",
    "featured project", "completed project", "award", "partnership",
]

# ── Email helpers ──────────────────────────────────────────────────────────

_EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')


def _is_junk_email(addr: str) -> bool:
    """Return True if this email address should be discarded."""
    addr = addr.lower().strip()
    local, _, domain_part = addr.partition("@")

    # File extension in the domain part (image/asset CDN emails)
    if any(addr.endswith(ext) for ext in _EMAIL_JUNK_EXTENSIONS):
        return True

    # Junk local-parts (noreply, bounce, etc.)
    if local in _EMAIL_JUNK_LOCALPARTS:
        return True

    # Junk domains
    if domain_part in _EMAIL_JUNK_DOMAINS:
        return True

    # Contains a slash — it's a URL fragment, not an email
    if "/" in addr:
        return True

    # Local part is all digits — likely a tracking ID
    if local.isdigit():
        return True

    # Too short to be real (e.g. "a@b.co" is fine but "x@y.z" is not)
    if len(local) < 2 or len(domain_part) < 4:
        return True

    return False


# ── Phone helpers ──────────────────────────────────────────────────────────

# Anchored patterns for common international phone formats.
# These are tried against the raw line text, not the full markdown at once,
# so we get precise matches rather than greedy substring noise.
_PHONE_PATTERNS = [
    # Indian mobile/landline with country code: +91 XXXXX XXXXX or +91-XXXXXXXXXX
    re.compile(r'\+91[\s\-]?[6-9]\d{4}[\s\-]?\d{5}'),
    # Indian landline without country code: 0XX-XXXXXXXX or (0XX) XXXXXXXX
    re.compile(r'\b0\d{2,4}[\s\-]\d{6,8}\b'),
    # International E.164-ish: +1 to +999, 6–14 digits after country code
    re.compile(r'\+[1-9]\d{0,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,6}'),
    # US/Canada: (NXX) NXX-XXXX — first digit of area code 2-9
    re.compile(r'\(?\b[2-9]\d{2}\)?[\s\-]\d{3}[\s\-]\d{4}\b'),
    # Toll-free / 1800 numbers: 1800-XXX-XXXX or 1-800-XXX-XXXX
    re.compile(r'\b1[\s\-]?8[0-9]{2}[\s\-]\d{3}[\s\-]\d{4}\b'),
    # Generic 10-digit blocks with separator: XXXXX XXXXX (e.g. Indian 98765 43210)
    re.compile(r'\b\d{5}[\s\-]\d{5}\b'),
    # Generic: XXX-XXX-XXXX or XXX.XXX.XXXX
    re.compile(r'\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b'),
]


def _is_junk_phone(raw: str) -> bool:
    """
    Return True if this phone candidate is actually a year, ZIP code,
    version number, or other non-phone number.
    """
    raw = raw.strip()
    digits_only = re.sub(r'\D', '', raw)

    # Too few or too many digits
    if not (7 <= len(digits_only) <= 15):
        return True

    # Year pattern: exactly 4 digits, 1900–2099
    if _PHONE_YEAR_RE.match(digits_only):
        return True

    # ZIP/postal: exactly 4–6 digits and no leading +
    if _PHONE_ZIP_RE.match(digits_only) and not raw.startswith("+"):
        return True

    # Version number in original string (e.g. "v10.2.1")
    if _PHONE_VERSION_RE.match(raw.lstrip("v").lstrip("V")):
        return True

    # Contains letters — not a phone number
    if re.search(r'[a-zA-Z]', raw):
        return True

    return False


def _extract_phones_from_line(line: str) -> list[str]:
    """
    Extract phone numbers from a single line of text using anchored patterns.
    Multiple overlapping patterns are deduplicated by their digit-only form
    so the same number is not returned twice.
    Returns a list of normalised phone strings.
    """
    seen_digits: set[str] = set()
    found: list[str] = []
    for pattern in _PHONE_PATTERNS:
        for m in pattern.finditer(line):
            candidate = m.group(0).strip()
            if _is_junk_phone(candidate):
                continue
            # Normalise: collapse runs of spaces/dashes to a single space
            normalised = re.sub(r'[\s\-]+', ' ', candidate).strip()
            # Deduplicate by digits only (so "+91 98765 43210" and "98765 43210" are the same)
            digits_key = re.sub(r'\D', '', normalised)
            if digits_key not in seen_digits:
                seen_digits.add(digits_key)
                found.append(normalised)
    return found


# ── Address extraction helpers ───────────────────────────────────────────────

# Indian states (full names and common abbreviations)
_INDIAN_STATES: list[str] = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    # Union territories
    "Delhi", "Jammu and Kashmir", "Ladakh", "Chandigarh", "Puducherry",
    "Lakshadweep", "Dadra and Nagar Haveli", "Daman and Diu",
    "Andaman and Nicobar",
    # Abbreviations
    "AP", "AR", "AS", "BR", "CG", "GA", "GJ", "HR", "HP", "JH",
    "KA", "KL", "MP", "MH", "MN", "ML", "MZ", "NL", "OD", "PB",
    "RJ", "SK", "TN", "TS", "TR", "UP", "UK", "WB",
]

# Major Indian cities used for city detection
_INDIAN_CITIES: list[str] = [
    "Mumbai", "Delhi", "Bangalore", "Bengaluru", "Hyderabad", "Ahmedabad",
    "Chennai", "Kolkata", "Surat", "Pune", "Jaipur", "Lucknow", "Kanpur",
    "Nagpur", "Visakhapatnam", "Indore", "Thane", "Bhopal", "Pimpri",
    "Patna", "Vadodara", "Ghaziabad", "Ludhiana", "Agra", "Nashik",
    "Faridabad", "Meerut", "Rajkot", "Kalyan", "Vasai", "Varanasi",
    "Srinagar", "Aurangabad", "Dhanbad", "Amritsar", "Navi Mumbai",
    "Allahabad", "Howrah", "Ranchi", "Coimbatore", "Jabalpur", "Gwalior",
    "Vijayawada", "Jodhpur", "Madurai", "Raipur", "Kota", "Chandigarh",
    "Guwahati", "Solapur", "Hubli", "Mysore", "Tiruchirappalli",
    "Bareilly", "Aligarh", "Moradabad", "Noida", "Gurugram", "Gurgaon",
    "Pimpri-Chinchwad", "PCMC",
]

# Regex: Indian PIN code (6 digits, optionally preceded by "PIN" / "Pin" / "Pincode")
_PIN_CODE_RE = re.compile(
    r'(?:PIN\s*(?:Code)?:?\s*)?(?<!\d)([1-9]\d{5})(?!\d)'
)

# Regex: lines that look like a postal address
# Looks for lines containing a PIN code, or lines near "address:" labels
_ADDRESS_LABEL_RE = re.compile(
    r'(?i)(?:^|\b)(?:address|location|office|registered\s+office|corporate\s+office|'
    r'head\s*quarters?|hq|regd\.?\s+office)\s*[:\-–]?\s*(.+)',
)

# Characters that suggest a line is NOT an address
_ADDRESS_JUNK_RE = re.compile(
    r'(?i)(follow\s+us|subscribe|newsletter|cookie|privacy|terms|©|copyright'
    r'|social media|share this|click here|learn more|read more|all rights)'
)


def _extract_address(markdown: str) -> dict:
    """
    Extract a structured address from scraped markdown.

    Returns a dict with keys:
        street      — first line of the address or full single-line address
        city        — detected city name
        state       — detected state name
        country     — detected country ("India" default when Indian indicators found)
        postal_code — 6-digit Indian PIN code (or empty string)
        full        — best full address string found

    Returns all-empty strings if nothing found.
    """
    empty = {"street": "", "city": "", "state": "", "country": "", "postal_code": "", "full": ""}

    lines = markdown.split("\n")

    # ── Pass 1: find lines with explicit address labels ────────────────────
    labeled_lines: list[str] = []
    for i, line in enumerate(lines):
        m = _ADDRESS_LABEL_RE.match(line.strip())
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) > 5 and not _ADDRESS_JUNK_RE.search(candidate):
                labeled_lines.append(candidate)
                # Grab the next 3 lines too (multi-line addresses)
                for j in range(1, 4):
                    if i + j < len(lines):
                        nxt = lines[i + j].strip()
                        if nxt and len(nxt) > 3 and not _ADDRESS_JUNK_RE.search(nxt):
                            labeled_lines.append(nxt)
                        else:
                            break
                break  # use first labeled address block

    # ── Pass 2: find lines containing a PIN code ───────────────────────────
    pin_lines: list[str] = []
    for i, line in enumerate(lines):
        if _PIN_CODE_RE.search(line):
            if not _ADDRESS_JUNK_RE.search(line):
                # Include up to 3 lines before the PIN line (street/city context)
                start = max(0, i - 3)
                block = [l.strip() for l in lines[start:i + 1] if l.strip()]
                pin_lines = block
                break

    # ── Choose best candidate block ────────────────────────────────────────
    block = labeled_lines or pin_lines
    if not block:
        return empty

    full_address = ", ".join(p for p in block if p)

    # ── Extract PIN code ───────────────────────────────────────────────────
    postal_code = ""
    for part in block:
        pm = _PIN_CODE_RE.search(part)
        if pm:
            postal_code = pm.group(1)
            break

    # ── Detect city ────────────────────────────────────────────────────────
    city = ""
    for part in block:
        for c in _INDIAN_CITIES:
            if re.search(r'\b' + re.escape(c) + r'\b', part, re.IGNORECASE):
                city = c
                break
        if city:
            break

    # ── Detect state ───────────────────────────────────────────────────────
    state = ""
    for part in block:
        for s in _INDIAN_STATES:
            if re.search(r'\b' + re.escape(s) + r'\b', part, re.IGNORECASE):
                state = s
                break
        if state:
            break

    # ── Detect country ─────────────────────────────────────────────────────
    country = ""
    full_lower = full_address.lower()
    if "india" in full_lower or postal_code or city or state:
        country = "India"
    elif "united states" in full_lower or "usa" in full_lower:
        country = "United States"
    elif "united kingdom" in full_lower or " uk" in full_lower:
        country = "United Kingdom"

    # ── Street = first block line (cleaned of PIN, city, state) ───────────
    street = block[0] if block else ""

    return {
        "street":      street,
        "city":        city,
        "state":       state,
        "country":     country,
        "postal_code": postal_code,
        "full":        full_address,
    }


def extract_business_info(scrape_result: dict) -> dict:
    """
    Extract factual business information from merged multi-page scraped content.
    Uses pattern matching — never invents data.
    Scans all merged pages so contact info in headers/footers is captured.
    """
    md   = scrape_result.get("markdown", "")
    meta = scrape_result.get("metadata", {})
    url  = scrape_result.get("url", "")
    domain = scrape_result.get("domain", "")

    # ── Base record from metadata ──────────────────────────────────────────
    # Title-splitting heuristic: "IBM | Contact Us" → "IBM"
    # But reject if the first segment is a generic page name.
    _GENERIC_PAGE_TITLES = frozenset({
        "contact", "contact us", "contactus", "get in touch", "reach us",
        "home", "welcome", "index", "about", "about us",
        "services", "solutions", "products",
        "page not found", "404", "file not found", "error",
        "login", "sign in", "sign up", "register",
    })

    raw_title = meta.get("title", "")
    # Try progressively shorter splits to find a non-generic segment
    title_name = ""
    for sep in (" | ", " — ", " - ", " · ", " > ", " :: "):
        parts = raw_title.split(sep)
        # Try first segment (usually brand)
        candidate = parts[0].strip()
        if candidate and candidate.lower() not in _GENERIC_PAGE_TITLES and len(candidate) >= 2:
            title_name = candidate
            break
        # Try last segment (some sites put brand last: "Contact | CompanyName")
        if len(parts) > 1:
            candidate = parts[-1].strip()
            if candidate and candidate.lower() not in _GENERIC_PAGE_TITLES and len(candidate) >= 2:
                title_name = candidate
                break

    company = {
        "domain":         domain,
        "website":        url,
        "name":           meta.get("og:site_name") or title_name,
        "title":          raw_title,
        "description":    meta.get("description", ""),
        "og_description": meta.get("og:description", ""),
        "keywords":       meta.get("keywords", ""),
        "page_title":     raw_title,
    }

    lines = md.split("\n")

    # First H1 as fallback company name — but skip generic headings
    if not company["name"]:
        for line in lines:
            if line.strip().startswith("# "):
                candidate = line.replace("# ", "").strip()
                if (candidate
                        and len(candidate) <= 80
                        and candidate.lower() not in _GENERIC_PAGE_TITLES):
                    company["name"] = candidate
                    break

    # ── Email extraction ───────────────────────────────────────────────────
    emails: set[str] = set()
    for line in lines:
        for addr in _EMAIL_PATTERN.findall(line):
            addr_lower = addr.lower()
            if not _is_junk_email(addr_lower):
                emails.add(addr_lower)

    # ── Phone extraction ───────────────────────────────────────────────────
    phones: set[str] = set()
    for line in lines:
        for phone in _extract_phones_from_line(line):
            phones.add(phone)

    # ── Social links ───────────────────────────────────────────────────────
    socials: dict[str, str] = {}
    for line in lines:
        ll = line.lower()
        for platform, keyword in [
            ("linkedin", "linkedin.com/company/"),
            ("linkedin", "linkedin.com/in/"),
            ("twitter",  "twitter.com/"),
            ("x",        "x.com/"),
            ("facebook", "facebook.com/"),
            ("instagram","instagram.com/"),
            ("github",   "github.com/"),
            ("youtube",  "youtube.com/@"),
        ]:
            if keyword in ll and platform not in socials:
                socials[platform] = line.strip()

    # ── Services ───────────────────────────────────────────────────────────
    services: list[str] = []
    seen_services: set[str] = set()
    for line in lines:
        stripped = line.strip().lstrip("-*#").strip()
        ll = stripped.lower()
        if (
            5 <= len(stripped) <= 140
            and any(kw in ll for kw in _SERVICE_KEYWORDS)
            and not stripped.startswith(("http", "www"))
            and not stripped.startswith("![")
        ):
            clean = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", stripped)
            if clean not in seen_services:
                seen_services.add(clean)
                services.append(clean)
    if not services:
        in_services = False
        for line in lines:
            if "[SERVICES PAGE" in line.upper():
                in_services = True
                continue
            if "[PROJECTS PAGE" in line.upper():
                in_services = False
            if in_services and line.strip().startswith(("##", "###")):
                heading = line.strip().lstrip("#").strip()
                if heading and heading not in seen_services and len(heading) <= 80:
                    seen_services.add(heading)
                    services.append(heading)
    services = services[:8]

    # ── Projects ───────────────────────────────────────────────────────────
    projects: list[dict] = []
    in_projects = False
    current_sub = None
    for line in lines:
        upper = line.upper()
        if "[PROJECTS PAGE" in upper:
            in_projects = True
            continue
        if any(tag in upper for tag in ("[SERVICES PAGE", "[ABOUT PAGE", "[CONTACT PAGE", "[TEAM PAGE")):
            in_projects = False
        if not in_projects:
            continue
        stripped = line.strip()
        if stripped.startswith(("##", "###")):
            heading = stripped.lstrip("#").strip()
            if heading and len(heading) <= 80 and not heading.lower().startswith(("http", "see all", "view all")):
                current_sub = heading
                projects.append({"title": heading, "description": ""})
        elif current_sub and stripped and len(stripped) > 20 and not stripped.startswith(("http", "![")):
            if projects:
                projects[-1]["description"] = stripped[:200]
    if not projects:
        for line in lines:
            stripped = line.strip()
            if any(kw in stripped.lower() for kw in _PROJECT_KEYWORDS) and stripped.startswith("["):
                m = re.match(r"\[([^\]]+)\]", stripped)
                if m and 3 <= len(m.group(1)) <= 80:
                    ptitle = m.group(1)
                    if ptitle not in [p["title"] for p in projects]:
                        projects.append({"title": ptitle, "description": ""})
    projects = projects[:8]

    # ── Address extraction ─────────────────────────────────────────────────
    # Run against the full merged markdown so contact/about page content is used.
    # Priority: pages tagged [CONTACT PAGE] and [ABOUT PAGE] appear first in
    # the merged markdown (see scrape_company scrape_order), so the extractor
    # naturally finds address blocks from those pages first.
    addr = _extract_address(md)

    # ── Assemble ───────────────────────────────────────────────────────────
    company["emails"]        = sorted(emails)[:8]
    company["phones"]        = sorted(phones)[:5]
    company["socials"]       = socials
    company["services"]      = services
    company["projects"]      = projects
    company["pages_visited"] = {
        "success": [p.get("url") for p in scrape_result.get("pages", []) if p.get("markdown", "").strip()],
        "failed":  [f.get("url") for f in scrape_result.get("failed_pages", [])],
    }
    # Address fields — populated by _extract_address, empty strings if not found
    company["address"]     = addr["full"]
    company["street"]      = addr["street"]
    company["city"]        = addr["city"]
    company["state"]       = addr["state"]
    company["country"]     = addr["country"]
    company["postal_code"] = addr["postal_code"]

    return company


# ── Step 5: Merge & Deduplicate ─────────────────────────────────────────────

def deduplicate_companies(companies: list[dict]) -> list[dict]:
    """Remove duplicate companies by domain. Keeps the first occurrence."""
    seen = set()
    deduped = []
    for c in companies:
        key = c.get("domain", "").lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def merge_company_data(search_result: dict, scraped: dict) -> dict:
    """Merge search result with multi-page scraped data into a single company record."""
    # Company name priority:
    #   1. og:site_name from scraped pages (most reliable)
    #   2. Non-generic title segment from scraped metadata
    #   3. Serper result title (cleaned of generic suffixes)
    #   4. Domain name as last resort (always fills the field)
    scraped_name = scraped.get("name", "").strip()
    serper_title = search_result.get("title", "").strip()
    domain_raw   = search_result.get("domain", "")

    # Clean Serper title — strip generic suffixes like "| Contact", "- Home"
    _STRIP_SUFFIXES = re.compile(
        r'[\|\-–—·]\s*(?:contact\s*(?:us)?|home|about\s*(?:us)?|'
        r'services|solutions|products|index)\s*$',
        re.IGNORECASE,
    )
    cleaned_serper = _STRIP_SUFFIXES.sub("", serper_title).strip()

    # If the cleaned Serper title is itself a generic word, discard it
    _GENERIC_TITLES = frozenset({
        "contact", "contact us", "contactus", "get in touch",
        "home", "welcome", "index", "about", "about us",
        "services", "solutions", "products",
        "page not found", "404", "file not found", "error",
        "login", "sign in", "sign up", "register",
    })
    if cleaned_serper.lower() in _GENERIC_TITLES:
        cleaned_serper = ""

    # Domain → readable name: "pristinepune.com" → "Pristinepune"
    domain_as_name = domain_raw.split(".")[0].replace("-", " ").replace("_", " ").title() if domain_raw else ""

    name = scraped_name or cleaned_serper or domain_as_name

    return {
        "name":           name,
        "domain":         domain_raw,
        "website":        search_result.get("link", ""),
        "search_snippet": search_result.get("snippet", ""),
        "description":    scraped.get("description") or scraped.get("og_description", ""),
        "page_title":     scraped.get("page_title", ""),
        "keywords":       scraped.get("keywords", ""),
        # raw lists from EXTRACT — passed to VALIDATE next
        "emails":         scraped.get("emails", []),
        "phones":         scraped.get("phones", []),
        "socials":        scraped.get("socials", {}),
        "services":       scraped.get("services", []),
        "projects":       scraped.get("projects", []),
        "pages_visited":  scraped.get("pages_visited", {}),
        # address fields from EXTRACT (_extract_address)
        "address":        scraped.get("address", ""),
        "street":         scraped.get("street", ""),
        "city":           scraped.get("city", ""),
        "state":          scraped.get("state", ""),
        "country":        scraped.get("country", ""),
        "postal_code":    scraped.get("postal_code", ""),
        "source":         "google_search",
    }


# ── Step 6: Validate contacts ────────────────────────────────────────────────

# Phone-type classification hints
# Numbers matching these patterns are more likely to be office/company lines
# than mobile numbers.
_LANDLINE_HINTS = [
    # Indian: +91 followed by a city-code prefix digit (2–5 = major cities, 8 = some city codes)
    # City codes after +91 start with 2 (Mumbai 22), 3 (Kolkata 33), 4 (Chennai 44),
    # 5 (Lucknow 522), 8 (Bangalore 80, Hyderabad 40…), 0 (explicit STD)
    # Explicitly NOT 6,7,9 which are mobile ranges
    re.compile(r'^\+91[\s\-]?[2-5]'),          # Major metro city codes
    re.compile(r'^\+91[\s\-]?80'),              # Bangalore 080
    re.compile(r'^\+91[\s\-]?0'),              # Explicit 0-prefixed STD via +91
    re.compile(r'^0\d{2,4}[\s\-]\d'),          # Indian STD without country code: 0XX-…
    re.compile(r'^\+1[\s]?\(?[2-9]\d{2}'),     # North American landline area codes
    re.compile(r'^\+44[\s]?(?:1|2)'),           # UK landline: +44 1X or +44 2X
    re.compile(r'^\+6[0-9][\s]?[3-9]'),        # SE Asia landline range
]

_MOBILE_HINTS = [
    re.compile(r'^\+91[\s\-]?[6-9]'),        # Indian mobile (6–9 prefix)
    re.compile(r'^\+1[\s]?\(?[2-9]\d{2}\)?[\s\-]\d{3}[\s\-]\d{4}$'),  # US mobile
]

_TOLLFREE_HINTS = [
    re.compile(r'\b1[\s\-]?8[0-9]{2}[\s\-]'),  # 1-800/1-888/1-877 …
    re.compile(r'\b1800[\s\-]'),                 # 1800 …
]


def _classify_phone(phone: str) -> str:
    """
    Return a coarse type label for a phone number.

    Check order matters:
      tollfree first (most specific)
      landline second (city/STD codes take priority over mobile range)
      mobile third
      unknown fallback

    Labels:
      "tollfree"  — 1800/1-800/1-888 style numbers
      "landline"  — city-code or STD-prefix numbers (likely company main line)
      "mobile"    — mobile-range prefix (+91 6-9, etc.)
      "unknown"   — no pattern matched; still a valid number
    """
    p = phone.strip()
    for pat in _TOLLFREE_HINTS:
        if pat.search(p):
            return "tollfree"
    # Landline BEFORE mobile — city codes like +91 80 must match landline first
    for pat in _LANDLINE_HINTS:
        if pat.match(p):
            return "landline"
    for pat in _MOBILE_HINTS:
        if pat.match(p):
            return "mobile"
    return "unknown"


def _pick_company_number(validated_phones: list[dict]) -> str:
    """
    Choose the single best company/business phone from the validated list.

    Priority order (highest to lowest):
      1. tollfree  — dedicated business line, highest confidence
      2. landline  — office main line
      3. unknown   — unclassified but valid
      4. mobile    — last resort; may be a company number but lower confidence

    Returns the raw phone string of the winner, or "" if the list is empty.
    """
    priority = {"tollfree": 0, "landline": 1, "unknown": 2, "mobile": 3}
    if not validated_phones:
        return ""
    best = min(validated_phones, key=lambda p: priority.get(p["type"], 99))
    return best["number"]


def validate_contacts(company: dict) -> dict:
    """
    VALIDATE stage.

    Takes a merged company dict (output of merge_company_data) and returns a
    new dict with:

      validated_emails  — list of emails that passed all checks
      rejected_emails   — list of {"addr": …, "reason": …} dicts
      validated_phones  — list of {"number": …, "type": …} dicts
      rejected_phones   — list of {"number": …, "reason": …} dicts
      company_number    — best single business/company phone (str or "")

    Original "emails" and "phones" keys are kept unchanged so callers that
    relied on them before this stage still work.
    """
    raw_emails: list[str] = company.get("emails", [])
    raw_phones: list[str] = company.get("phones", [])

    # ── Validate emails ────────────────────────────────────────────────────
    validated_emails: list[str] = []
    rejected_emails:  list[dict] = []

    for addr in raw_emails:
        addr = addr.lower().strip()
        if not addr:
            continue

        local, sep, domain_part = addr.partition("@")
        if not sep:
            rejected_emails.append({"addr": addr, "reason": "no @ sign"})
            continue

        # Structural check: must have at least one dot in domain
        if "." not in domain_part:
            rejected_emails.append({"addr": addr, "reason": "domain has no dot"})
            continue

        # Run through the junk filter (already applied in extract, but
        # validate_contacts is the authoritative gate so we re-check)
        if any(addr.endswith(ext) for ext in _EMAIL_JUNK_EXTENSIONS):
            rejected_emails.append({"addr": addr, "reason": "asset/file extension"})
            continue
        if local in _EMAIL_JUNK_LOCALPARTS:
            rejected_emails.append({"addr": addr, "reason": f"junk local-part: {local}"})
            continue
        if domain_part in _EMAIL_JUNK_DOMAINS:
            rejected_emails.append({"addr": addr, "reason": f"junk domain: {domain_part}"})
            continue
        if "/" in addr:
            rejected_emails.append({"addr": addr, "reason": "slash in address (URL fragment)"})
            continue
        if local.isdigit():
            rejected_emails.append({"addr": addr, "reason": "all-digit local-part"})
            continue
        if len(local) < 2 or len(domain_part) < 4:
            rejected_emails.append({"addr": addr, "reason": "address too short"})
            continue

        validated_emails.append(addr)

    # ── Validate phones ────────────────────────────────────────────────────
    validated_phones: list[dict] = []
    rejected_phones:  list[dict] = []
    seen_digits: set[str] = set()   # dedup across the validated list

    for phone in raw_phones:
        phone = phone.strip()
        if not phone:
            continue

        digits = re.sub(r'\D', '', phone)

        # Check specific junk patterns first (better rejection messages)
        # Year pattern: exactly 4 digits, 1900–2099
        if len(digits) == 4 and _PHONE_YEAR_RE.match(digits):
            rejected_phones.append({"number": phone, "reason": "looks like a year"})
            continue

        # Postal / ZIP: 4–6 pure digits, no leading +
        if _PHONE_ZIP_RE.match(digits) and not phone.startswith("+"):
            rejected_phones.append({"number": phone, "reason": "looks like a postal code"})
            continue

        # Version string
        if _PHONE_VERSION_RE.match(phone.lstrip("vV")):
            rejected_phones.append({"number": phone, "reason": "looks like a version number"})
            continue

        # Letters present (not a phone)
        if re.search(r'[a-zA-Z]', phone):
            rejected_phones.append({"number": phone, "reason": "contains letters"})
            continue

        # Digit count check (after specific checks so reason is precise)
        if len(digits) < 7:
            rejected_phones.append({"number": phone, "reason": "too few digits (<7)"})
            continue
        if len(digits) > 15:
            rejected_phones.append({"number": phone, "reason": "too many digits (>15)"})
            continue

        # Dedup by digit-normalised form
        if digits in seen_digits:
            continue
        seen_digits.add(digits)

        phone_type = _classify_phone(phone)
        validated_phones.append({"number": phone, "type": phone_type})

    company_number = _pick_company_number(validated_phones)

    return {
        **company,
        # Validation results (new keys)
        "validated_emails": validated_emails,
        "rejected_emails":  rejected_emails,
        "validated_phones": validated_phones,
        "rejected_phones":  rejected_phones,
        "company_number":   company_number,
    }


# ── Step 7: Confidence scoring ───────────────────────────────────────────────

def score_confidence(company: dict) -> float:
    """
    Produce a 0.0–1.0 confidence score based strictly on evidence found.

    Scoring philosophy:
    - A field's mere existence is weak evidence; we reward quality evidence.
    - Presence of a validated email or validated phone contributes most.
    - Supporting signals (description, services, pages scraped successfully)
      add small increments.
    - The score is never inflated — a company with no validated contacts
      cannot score above 0.35 no matter how much other data exists.

    Weight table
    ────────────────────────────────────────────────────────────────
    validated email present               0.30   (capped at first one)
    second distinct validated email       0.05   (bonus for depth)
    company_number present                0.25   (single best phone)
    additional validated phone            0.05   (bonus for depth)
    description present (≥ 20 chars)      0.10
    services list non-empty               0.05
    at least 2 pages scraped successfully 0.10
    website present                       0.05
    social link present                   0.05
    ────────────────────────────────────────────────────────────────
    Max theoretical: 0.30+0.05+0.25+0.05+0.10+0.05+0.10+0.05+0.05 = 1.00
    """
    score = 0.0

    validated_emails = company.get("validated_emails", [])
    validated_phones = company.get("validated_phones", [])
    company_number   = company.get("company_number", "")
    description      = company.get("description", "") or ""
    services         = company.get("services", [])
    website          = company.get("website", "")
    socials          = company.get("socials", {})
    pages_success    = company.get("pages_visited", {}).get("success", [])

    # ── Contact evidence (the most valuable signals) ──────────────────────
    if validated_emails:
        score += 0.30
    if len(validated_emails) >= 2:
        score += 0.05

    if company_number:
        score += 0.25
    elif validated_phones:
        # Phones found but none selected as company_number — partial credit
        score += 0.10
    if len(validated_phones) >= 2:
        score += 0.05

    # ── Supporting signals ────────────────────────────────────────────────
    if len(description.strip()) >= 20:
        score += 0.10

    if services:
        score += 0.05

    if len(pages_success) >= 2:
        score += 0.10

    if website:
        score += 0.05

    if socials:
        score += 0.05

    # Clamp to [0.0, 1.0] and round to 2 dp
    return round(min(max(score, 0.0), 1.0), 2)


# ── Step 8: Enrich — founder discovery ──────────────────────────────────────
#
# Safety contract (enforced throughout this section):
#   - founder_number is ONLY set when the phone number was found on an official
#     company About/Team/Leadership page alongside the person's name and title.
#   - We NEVER infer, guess, generate, or reuse a mobile number from the
#     general contact extraction as a founder number.
#   - If no publicly listed professional contact is found, founder_number = None.
#
# Discovery strategy:
#   1. Use Serper to search for "[company] founder", "[company] CEO",
#      "[company] leadership" — harvest the name from the top snippet.
#   2. Try to scrape the company's own About/Team/Leadership page (already
#      visited during SCRAPE if it succeeded; reuse markdown before re-fetching).
#   3. Scan that page markdown for the founder name in proximity to a phone number.
#      Only accept a phone that appears on the same line or within 3 lines of the
#      name — strict proximity rule prevents false matches.
#   4. Pass any candidate phone through the existing _is_junk_phone + _classify_phone
#      pipeline; reject mobiles unless the page explicitly labels them as office/
#      direct-dial for that person.

# Serper query templates for founder/leadership discovery
_FOUNDER_QUERY_TEMPLATES = [
    "{company} founder",
    "{company} CEO founder",
    "{company} managing director",
    "{company} leadership team",
]

# Title keywords that indicate a leadership role on an About/Team page
_LEADERSHIP_TITLES = {
    "founder", "co-founder", "cofounder",
    "ceo", "chief executive",
    "managing director", "md",
    "chairman", "chairperson",
    "president", "director",
    "cto", "coo", "cfo",
}

# Name patterns: "FirstName LastName" — two or three capitalised words
# Deliberately conservative to avoid matching company names or headings
_NAME_RE = re.compile(
    r'\b([A-Z][a-z]{1,20})\s+([A-Z][a-z]{1,20})(?:\s+([A-Z][a-z]{1,20}))?\b'
)


def _search_founder(company_name: str) -> dict:
    """
    Use Serper to search for the founder/CEO of a company.

    Returns:
      { "name": str|None, "source_url": str|None, "snippet": str }

    "name" is only set when the result snippet strongly implies a person's name
    in a leadership role.  Never guesses.
    """
    if not SERPER_API_KEY or not company_name.strip():
        return {"name": None, "source_url": None, "snippet": ""}

    # Try templates in order; stop at first credible result
    for template in _FOUNDER_QUERY_TEMPLATES:
        query = template.format(company=company_name)
        try:
            headers = {
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json",
            }
            data = _json_request(SERPER_URL, headers, {"q": query, "num": 3})
        except Exception:
            continue

        # Check knowledge graph first — most reliable
        kg = data.get("knowledgeGraph", {})
        kg_desc = kg.get("description", "")
        kg_url  = _clean_url(kg.get("website", ""))

        for item in [kg] + data.get("organic", [])[:3]:
            snippet  = item.get("snippet", "") or item.get("description", "")
            link     = _clean_url(item.get("link", "") or item.get("website", ""))
            combined = snippet.lower()

            # Must mention a leadership title to be credible
            if not any(t in combined for t in _LEADERSHIP_TITLES):
                continue

            # Only use official company URLs as source (not social media / directories)
            _NON_OFFICIAL_SOURCE = frozenset({
                "linkedin.com", "instagram.com", "facebook.com", "twitter.com",
                "x.com", "youtube.com", "wikipedia.org", "glassdoor.com",
                "ambitionbox.com", "indiamart.com", "justdial.com",
                "crunchbase.com", "bloomberg.com", "naukri.com",
                "quora.com", "reddit.com", "medium.com",
            })
            link_domain = link.split("/")[2].lstrip("www.") if "//" in link else ""
            source_ok = not any(
                link_domain == d or link_domain.endswith("." + d)
                for d in _NON_OFFICIAL_SOURCE
            )

            # Extract a plausible person name from the snippet
            for m in _NAME_RE.finditer(snippet):
                candidate = m.group(0).strip()
                words = candidate.split()
                # Reject honorifics, titles, and job-role words as first word
                _HONORIFICS = frozenset({
                    "late", "mr", "mrs", "ms", "dr", "prof", "sir",
                    "executive", "managing", "chief", "senior", "junior",
                    "vice", "deputy", "assistant", "additional",
                    "the", "our", "your", "this", "that",
                })
                if words and words[0].lower() in _HONORIFICS:
                    continue
                # Reject if it looks like a company name:
                _COMPANY_WORDS = frozenset({
                    "ltd", "limited", "pvt", "private", "inc", "incorporated",
                    "corp", "corporation", "group", "developers", "development",
                    "realty", "properties", "builders", "construction", "infra",
                    "infrastructure", "associates", "consultants", "solutions",
                    "services", "ventures", "holdings", "industries",
                })
                word_lower = {w.lower() for w in words}
                if word_lower & _COMPANY_WORDS:
                    continue
                if len(words) < 2 or len(words) > 4:
                    continue
                if all(len(w) > 1 for w in words):
                    return {
                        "name":       candidate,
                        "source_url": link if source_ok else None,
                        "snippet":    snippet[:200],
                    }

    return {"name": None, "source_url": None, "snippet": ""}


def _extract_founder_number_from_page(
    markdown: str,
    founder_name: str,
    page_url: str,
) -> str | None:
    """
    Scan a page's markdown for a phone number that is:
      - Explicitly adjacent (within 3 lines) to the founder's name
      - On an official About/Team/Leadership page
      - Not a mobile number unless the page labels it as an office/direct line
      - Passes _is_junk_phone validation

    Returns the phone string if found, else None.

    Safety: this function NEVER returns a number it cannot trace to a named
    person on an official page.  If proximity criteria are not met, returns None.
    """
    if not markdown or not founder_name:
        return None

    lines = markdown.split("\n")
    name_parts = founder_name.lower().split()
    if not name_parts:
        return None

    # Find every line index where the founder name appears
    name_line_indices: list[int] = []
    for i, line in enumerate(lines):
        ll = line.lower()
        if all(part in ll for part in name_parts):
            name_line_indices.append(i)

    if not name_line_indices:
        return None

    # For each name occurrence, scan ±3 lines for a phone number
    for name_idx in name_line_indices:
        window_start = max(0, name_idx - 3)
        window_end   = min(len(lines), name_idx + 4)
        window_lines = lines[window_start:window_end]
        window_text  = " ".join(window_lines)

        candidates = _extract_phones_from_line(window_text)
        for phone in candidates:
            if _is_junk_phone(phone):
                continue
            ptype = _classify_phone(phone)
            # Only accept landline, tollfree, or unknown from an official page.
            # Reject mobile unless the page explicitly labels it — we cannot tell
            # from text alone whether a mobile is personal or work-issued.
            if ptype == "mobile":
                # Accept mobile only if the surrounding text contains a direct-line
                # or work-phone label
                context = window_text.lower()
                if not any(kw in context for kw in (
                    "direct", "office", "work", "business", "ext", "extension"
                )):
                    continue
            return phone

    return None


def enrich_company(company: dict) -> dict:
    """
    ENRICH stage.

    Adds to the company dict:
      founder_name    — string or None
      founder_number  — publicly listed professional phone or None
                        (NEVER a guessed/inferred private number)
      enrich_source   — URL where founder info was found (for verification)

    Uses only:
      1. Serper search on company name + leadership keywords
      2. Existing scraped page markdown (already in pages_visited — no extra
         Firecrawl calls unless the team/about page wasn't scraped before)

    If no credible public founder contact is found, all three fields are None/"".
    """
    company_name  = company.get("name", "") or company.get("company_name", "")
    website       = company.get("website", "")
    pages_visited = company.get("pages_visited", {})

    # Default enrichment — all null until evidence is found
    founder_name:   str | None = None
    founder_number: str | None = None
    enrich_source:  str        = ""

    if not company_name:
        return {**company,
                "founder_name": None, "founder_number": None, "enrich_source": ""}

    # ── Step A: Discover founder name via Serper ───────────────────────────
    print(f"         [Enrich] Searching founder for: {company_name!r}", file=sys.stderr)
    founder_info = _search_founder(company_name)
    founder_name  = founder_info["name"]       # None if not found
    enrich_source = founder_info["source_url"] or ""

    if not founder_name:
        print(f"         [Enrich] No founder name found — skipping number search",
              file=sys.stderr)
        return {**company,
                "founder_name": None, "founder_number": None, "enrich_source": enrich_source}

    print(f"         [Enrich] Founder candidate: {founder_name!r}", file=sys.stderr)

    # ── Step B: Search for a phone next to the founder name ───────────────
    # Look in already-scraped team/about/leadership pages first (no new API call)
    pages_markdown: list[tuple[str, str]] = []   # (url, markdown)

    # Pull from pages already scraped during the main scrape
    for page in company.get("_scraped_pages", []):
        url = page.get("url", "")
        md  = page.get("markdown", "")
        if md and any(kw in url.lower() for kw in
                      ("team", "about", "leader", "management", "founder", "people", "board")):
            pages_markdown.append((url, md))

    # Fallback: the merged markdown already contains tagged sections
    merged_md = company.get("_merged_markdown", "")
    if merged_md:
        pages_markdown.append((website, merged_md))

    for page_url, md in pages_markdown:
        phone = _extract_founder_number_from_page(md, founder_name, page_url)
        if phone:
            founder_number = phone
            enrich_source  = page_url
            print(f"         [Enrich] Found professional number {phone!r} at {page_url}",
                  file=sys.stderr)
            break

    if not founder_number:
        print(f"         [Enrich] No publicly listed professional number found for {founder_name!r}",
              file=sys.stderr)

    return {
        **company,
        "founder_name":   founder_name,
        "founder_number": founder_number,   # None unless found on official page
        "enrich_source":  enrich_source,
    }


# ── Step 9: Verify ─────────────────────────────────────────────────────────
#
# Verification contract:
#   - We only "verify" a field when we can find the exact value in the
#     already-scraped page markdown from Firecrawl.  No new HTTP calls.
#   - A field is "verified" iff the value appears verbatim (or near-verbatim)
#     in an official company page (not a directory or third-party site).
#   - founder_number stays None unless the number appears adjacent to the
#     founder name on an official page — same rule as ENRICH.
#   - If a field cannot be verified, it is kept as-is and marked unverified.
#   - last_verified is set to the current UTC ISO timestamp only when at least
#     one contact field (email OR company_number) is confirmed in the markdown.
#   - Confidence is boosted slightly when key fields are verified, but never
#     exceeds 1.0 and never inflated without evidence.
#
# Verification sources used (priority order):
#   1. Contact page markdown  (most likely to contain definitive contact info)
#   2. Home page markdown     (often repeats header/footer contacts)
#   3. About/Team page markdown
#   4. Merged markdown        (fallback — full joined text from all pages)

# Fields that constitute "verified contact" (triggers last_verified timestamp)
_VERIFIED_CONTACT_FIELDS = ("email", "company_number")

# Confidence boost per verified field (small — verification is supporting
# evidence, not the primary scoring signal)
_VERIFY_BOOST_PER_FIELD = 0.05


def _pages_by_priority(company: dict) -> list[tuple[str, str]]:
    """
    Return (url, markdown) tuples from the stashed scraped pages, ordered so
    contact-dense pages come first:  contact → home → about/team → others.
    Falls back to the full merged markdown if no individual pages are stored.
    """
    priority_keywords = ("contact", "home", "about", "team", "leadership",
                         "management", "people", "board", "founder")
    pages: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    # Build a priority-ordered list from individually scraped pages
    scraped = company.get("_scraped_pages", [])
    # Sort: pages whose URL contains a high-priority keyword come first
    def _rank(page: dict) -> int:
        url_lower = page.get("url", "").lower()
        for rank, kw in enumerate(priority_keywords):
            if kw in url_lower:
                return rank
        return len(priority_keywords)

    for page in sorted(scraped, key=_rank):
        url = page.get("url", "")
        md  = page.get("markdown", "")
        if md.strip() and url not in seen_urls:
            seen_urls.add(url)
            pages.append((url, md))

    # Always append the full merged markdown as a last-resort fallback
    merged_md = company.get("_merged_markdown", "")
    if merged_md.strip():
        pages.append((company.get("website", ""), merged_md))

    return pages


def _text_contains(text: str, value: str, *, min_len: int = 4) -> bool:
    """
    Return True if `value` appears in `text` (case-insensitive).
    Guards against trivially short values that would match anywhere.
    """
    if not value or len(value.strip()) < min_len:
        return False
    return value.strip().lower() in text.lower()


def _find_value_in_pages(
    pages: list[tuple[str, str]],
    value: str,
    *,
    min_len: int = 4,
) -> str | None:
    """
    Search each (url, markdown) pair for `value`.
    Returns the URL of the first page where the value is found, else None.
    """
    for url, md in pages:
        if _text_contains(md, value, min_len=min_len):
            return url
    return None


def verify_company_data(company: dict) -> dict:
    """
    VERIFY stage.

    Cross-checks the enriched company data against the Firecrawl-scraped page
    markdown that is already stored in the company dict under _scraped_pages
    and _merged_markdown.  No new HTTP/API calls are made.

    For each verifiable field, the function checks whether the value can be
    found verbatim in an official company page.

    Returns the company dict with these additions/updates:

      verification        — dict with per-field verification results:
                            { field: {"verified": bool, "source_url": str|None} }
      source_url          — URL of the page that confirmed the most contact fields
      last_verified       — current UTC ISO timestamp IF at least one contact
                            field (email or company_number) was verified; else None
      confidence          — existing score + small boost for each verified field
                            (clamped to 1.0)
    """
    from datetime import datetime, timezone

    pages = _pages_by_priority(company)

    # ── Fields to verify and their minimum match length ───────────────────
    # Each entry: (field_key, value_to_find, min_len)
    fields_to_verify = [
        ("company_name",   company.get("name") or company.get("company_name", ""), 4),
        ("email",          company.get("validated_emails", [None])[0]
                           if company.get("validated_emails") else None,            6),
        ("company_number", company.get("company_number") or "",                     7),
        ("founder_name",   company.get("founder_name") or "",                       4),
        ("founder_number", company.get("founder_number") or "",                     7),
    ]

    verification: dict[str, dict] = {}
    verified_contact_source: str | None = None  # URL for the best verified contact page
    boost = 0.0

    for field_key, value, min_len in fields_to_verify:
        if not value:
            verification[field_key] = {"verified": False, "source_url": None}
            continue

        found_url = _find_value_in_pages(pages, value, min_len=min_len)

        if found_url:
            verification[field_key] = {"verified": True, "source_url": found_url}
            boost += _VERIFY_BOOST_PER_FIELD
            # Track source URL for contact fields (highest priority)
            if field_key in _VERIFIED_CONTACT_FIELDS and not verified_contact_source:
                verified_contact_source = found_url
        else:
            verification[field_key] = {"verified": False, "source_url": None}

    # ── founder_number: extra safety — only keep if verified on official page ──
    # If the founder_number was set by ENRICH but cannot be found in any scraped
    # page, it means it came from a Serper snippet only (not a full page).
    # We clear it to stay conservative.
    if company.get("founder_number"):
        if not verification.get("founder_number", {}).get("verified", False):
            print(
                f"         [Verify] founder_number not confirmed in scraped pages — clearing",
                file=sys.stderr,
            )
            company = {**company, "founder_number": None}
            verification["founder_number"] = {"verified": False, "source_url": None}

    # ── Determine whether any contact was actually verified ────────────────
    email_verified   = verification.get("email",          {}).get("verified", False)
    phone_verified   = verification.get("company_number", {}).get("verified", False)
    has_verified_contact = email_verified or phone_verified

    # ── Update last_verified ───────────────────────────────────────────────
    last_verified: str | None = (
        datetime.now(timezone.utc).isoformat()
        if has_verified_contact
        else None
    )

    # ── Update source_url — prefer the page that verified a contact ────────
    # Fall back to existing enrich_source or website
    source_url = (
        verified_contact_source
        or company.get("enrich_source", "")
        or company.get("website", "")
        or None
    )

    # ── Update confidence with verification boost ──────────────────────────
    existing_confidence = company.get("confidence", 0.0)
    new_confidence = round(min(existing_confidence + boost, 1.0), 2)

    print(
        f"         [Verify] verified fields: "
        f"{[k for k,v in verification.items() if v.get('verified')]}  "
        f"confidence: {existing_confidence} → {new_confidence}  "
        f"last_verified: {'SET' if last_verified else 'NOT SET'}",
        file=sys.stderr,
    )

    return {
        **company,
        "verification":   verification,
        "source_url":     source_url,
        "last_verified":  last_verified,
        "confidence":     new_confidence,
    }


# ── Contact-gap fallback ─────────────────────────────────────────────────────
# When a company leaves VALIDATE with no email AND no phone, we attempt one
# targeted recovery:
#   1. Serper query: "{company} site:{domain} contact email phone"
#      → surface a direct contact page URL we may have missed
#   2. Scrape at most 2 additional page URLs found via Serper
#      (full-content mode to capture header/footer contacts)
#   3. Merge any new emails/phones back into the company dict and re-validate
#
# This never fabricates data — it only performs real Firecrawl scrapes of
# publicly reachable pages.  If the new pages also return nothing, the
# company keeps its empty-contact state.  The Serper call uses a separate
# conservative query that explicitly targets the company's own domain.

def _contact_gap_search(company: dict) -> dict:
    """
    Targeted fallback for companies with no validated email AND no company_number
    after the initial SCRAPE+VALIDATE pass.

    Returns the company dict (possibly with new emails/phones merged in and
    re-validated).  Never modifies VALIDATE, ENRICH, VERIFY, or any other stage.
    """
    name   = company.get("name") or company.get("company_name", "")
    domain = company.get("domain", "")
    website = company.get("website", "")

    if not name and not domain:
        return company

    # Already has contacts — nothing to do
    if company.get("validated_emails") or company.get("company_number"):
        return company

    print(f"         [ContactGap] No contacts found for {name!r} — running targeted search",
          file=sys.stderr)

    # ── Step 1: Serper targeted query ──────────────────────────────────────
    # Try domain-scoped query first, then a generic one
    queries = []
    if domain:
        queries.append(f'site:{domain} contact email phone')
    if name:
        queries.append(f'"{name}" contact email phone address')

    candidate_urls: list[str] = []
    for q in queries:
        try:
            headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
            data = _json_request(SERPER_URL, headers, {"q": q, "num": 5})
            for item in data.get("organic", [])[:5]:
                link = _clean_url(item.get("link", ""))
                if not link or not link.startswith("http"):
                    continue
                # Only follow URLs on the same domain or clearly official
                item_domain = _domain(link)
                if domain and item_domain != domain:
                    continue
                if link not in candidate_urls:
                    candidate_urls.append(link)
            if candidate_urls:
                break   # first query that returns same-domain results is enough
        except Exception as exc:
            print(f"         [ContactGap] Serper query failed: {exc}", file=sys.stderr)

    if not candidate_urls and website:
        # Fallback: try common contact paths directly on the domain
        from urllib.parse import urlparse
        parsed = urlparse(website)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in ["/contact-us", "/contact", "/enquiry", "/reach-us", "/get-in-touch"]:
            candidate_urls.append(base + path)

    if not candidate_urls:
        print(f"         [ContactGap] No candidate URLs found — skipping", file=sys.stderr)
        return company

    # ── Step 2: Scrape up to 2 candidate URLs ─────────────────────────────
    already_scraped = {
        p.get("url", "") for p in company.get("_scraped_pages", [])
    }
    new_pages: list[dict] = []
    scraped_count = 0

    for url in candidate_urls:
        if url in already_scraped:
            continue
        if scraped_count >= 2:
            break
        try:
            page = _scrape_single(url, timeout=30, full_content=True)
            md = page.get("markdown", "")
            if md.strip():
                new_pages.append(page)
                scraped_count += 1
                print(f"         [ContactGap] Scraped {url} — {len(md)} chars",
                      file=sys.stderr)
            time.sleep(REQUEST_DELAY)
        except Exception as exc:
            print(f"         [ContactGap] Scrape failed for {url}: {exc}", file=sys.stderr)

    if not new_pages:
        print(f"         [ContactGap] No new content scraped — contacts remain empty",
              file=sys.stderr)
        return company

    # ── Step 3: Extract and re-validate ───────────────────────────────────
    new_emails: set[str] = set(company.get("emails", []))
    new_phones: set[str] = set(company.get("phones", []))

    for page in new_pages:
        md = page.get("markdown", "")
        lines = md.split("\n")
        for line in lines:
            for addr in _EMAIL_PATTERN.findall(line):
                if not _is_junk_email(addr.lower()):
                    new_emails.add(addr.lower())
            for phone in _extract_phones_from_line(line):
                new_phones.add(phone)

    # Update company with merged contacts and re-scraped pages
    updated = {
        **company,
        "emails": sorted(new_emails)[:8],
        "phones": sorted(new_phones)[:5],
        "_scraped_pages": company.get("_scraped_pages", []) + new_pages,
        "_merged_markdown": company.get("_merged_markdown", "") + "\n".join(
            f"\n\n--- [CONTACT-GAP PAGE: {p['url']}] ---\n{p['markdown']}"
            for p in new_pages
        ),
    }

    # Re-validate contacts with the new data
    revalidated = validate_contacts(updated)

    found_emails = revalidated.get("validated_emails", [])
    found_number = revalidated.get("company_number", "")
    print(
        f"         [ContactGap] After gap search — emails={found_emails} "
        f"company_number={found_number!r}",
        file=sys.stderr,
    )
    return revalidated


# ── Main Pipeline ───────────────────────────────────────────────────────────

def run_pipeline(query: str, num: int = DEFAULT_NUM) -> list[dict]:
    """
    Full lead generation pipeline:
      DISCOVER → SCRAPE → EXTRACT → NORMALIZE → VALIDATE → CONFIDENCE → ENRICH → VERIFY → DEDUPLICATE
    """
    # ── DISCOVER ──────────────────────────────────────────────────────────
    print(f"🔍 Searching Google for: {query!r}", file=sys.stderr)
    results = search_companies(query, num)
    print(f"   Found {len(results)} results", file=sys.stderr)

    company_urls = [(r, r["link"]) for r in results if r.get("link")]

    # ── SCRAPE → EXTRACT → NORMALIZE ──────────────────────────────────────
    companies = []
    for i, (search_result, url) in enumerate(company_urls):
        print(f"   [{i+1}/{len(company_urls)}] Scraping {url} …", file=sys.stderr)
        try:
            scraped = scrape_company(url)
            time.sleep(COMPANY_DELAY)
            info   = extract_business_info(scraped)
            merged = merge_company_data(search_result, info)

            # Stash raw scraped pages and merged markdown for ENRICH stage
            # (private keys prefixed with _ — stripped before returning to caller)
            merged["_scraped_pages"]    = scraped.get("pages", [])
            merged["_merged_markdown"]  = scraped.get("markdown", "")

            success_count = len(info.get("pages_visited", {}).get("success", []))
            fail_count    = len(info.get("pages_visited", {}).get("failed", []))
            print(
                f"         ✓ {success_count} pages scraped, {fail_count} failed  "
                f"| raw emails={len(merged['emails'])} phones={len(merged['phones'])}",
                file=sys.stderr,
            )
            companies.append(merged)

        except Exception as e:
            print(f"   ⚠️  Failed to scrape {url}: {e}", file=sys.stderr)
            companies.append({
                "name":              search_result.get("title", ""),
                "domain":            search_result.get("domain", ""),
                "website":           url,
                "search_snippet":    search_result.get("snippet", ""),
                "description":       "",
                "page_title":        "",
                "keywords":          "",
                "emails":            [],
                "phones":            [],
                "socials":           {},
                "address":           "",
                "street":            "",
                "city":              "",
                "state":             "",
                "country":           "",
                "postal_code":       "",
                "source":            "google_search_only",
                "scrape_error":      str(e),
                "_scraped_pages":    [],
                "_merged_markdown":  "",
            })

    # ── VALIDATE ──────────────────────────────────────────────────────────
    total_email_rejected = 0
    total_phone_rejected = 0

    validated_companies = []
    for c in companies:
        vc = validate_contacts(c)
        total_email_rejected += len(vc.get("rejected_emails", []))
        total_phone_rejected += len(vc.get("rejected_phones", []))
        validated_companies.append(vc)

    print(
        f"   [Validate] emails rejected={total_email_rejected}  "
        f"phones rejected={total_phone_rejected}",
        file=sys.stderr,
    )

    # ── CONTACT-GAP FALLBACK ───────────────────────────────────────────────
    # For companies that left VALIDATE with no email AND no phone, run a
    # targeted Serper + Firecrawl recovery search (at most 2 extra pages/company).
    # This is the only stage that makes additional network calls beyond the
    # initial SCRAPE.  It never fabricates data.
    gap_filled = []
    for c in validated_companies:
        has_email  = bool(c.get("validated_emails"))
        has_phone  = bool(c.get("company_number") or c.get("validated_phones"))
        if not has_email or not has_phone:
            c = _contact_gap_search(c)
        gap_filled.append(c)
    validated_companies = gap_filled

    # ── CONFIDENCE SCORE ──────────────────────────────────────────────────
    for c in validated_companies:
        c["confidence"] = score_confidence(c)

    # ── ENRICH ────────────────────────────────────────────────────────────
    enriched_companies = []
    for c in validated_companies:
        ec = enrich_company(c)
        enriched_companies.append(ec)

    # ── VERIFY ────────────────────────────────────────────────────────────
    # Cross-checks enriched data against already-scraped Firecrawl pages.
    # No new HTTP calls. Updates source_url, last_verified, confidence.
    verified_companies = []
    for c in enriched_companies:
        vc = verify_company_data(c)
        verified_companies.append(vc)

    # ── DEDUPLICATE ───────────────────────────────────────────────────────
    companies = deduplicate_companies(verified_companies)
    print(f"   ✅ {len(companies)} unique companies after dedup", file=sys.stderr)

    # Strip internal staging keys before returning
    for c in companies:
        c.pop("_scraped_pages",   None)
        c.pop("_merged_markdown", None)

    return companies


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI-Powered Lead Generation — Research Engine"
    )
    parser.add_argument("--query", "-q", required=True, help="Search query (e.g. 'AI startups in San Francisco')")
    parser.add_argument("--num", "-n", type=int, default=DEFAULT_NUM, help=f"Number of results (default: {DEFAULT_NUM})")
    parser.add_argument("--jsonl", action="store_true", help="Output one JSON object per line")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    try:
        companies = run_pipeline(args.query, args.num)
    except Exception as e:
        print(json.dumps({"error": str(e), "status": "failed"}), file=sys.stderr)
        sys.exit(1)

    output = {
        "query": args.query,
        "total": len(companies),
        "companies": companies,
        "status": "success",
    }

    if args.jsonl:
        for c in companies:
            print(json.dumps(c, indent=2 if args.pretty else None, ensure_ascii=False))
    else:
        indent = 2 if args.pretty else None
        print(json.dumps(output, indent=indent, ensure_ascii=False))


if __name__ == "__main__":
    main()