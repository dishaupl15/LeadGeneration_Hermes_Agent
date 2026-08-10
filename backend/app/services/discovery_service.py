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
_CANDIDATE_MULT = 6

# Pages to scrape per company: (path, full_content)
# full_content=True keeps headers/footers so phone/email in nav bar is captured
# Expanded to cover team/founders/locations/management pages for richer enrichment
_PAGES: list[tuple[str, bool]] = [
    ("/",             True),
    ("/contact-us",   True),
    ("/contact",      True),
    ("/about-us",     False),
    ("/about",        False),
    ("/team",         False),
    ("/leadership",   False),
    ("/founders",     False),
    ("/management",   False),
    ("/locations",    False),
    ("/office",       False),
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
    # Startup / company directories
    "f6s.com", "startupindia.gov.in", "tracxn.com", "rocketlane.com",
    # Lead / data aggregator platforms
    "aeroleads.com", "apollo.io", "zoominfo.com", "rocketreach.co",
    "lusha.com", "clearbit.com", "leadfeeder.com", "datanyze.com",
    # Global commercial RE firms whose Pune page is not a Pune company
    # (their Indian sub-pages cover all of India, not Pune specifically)
    "savills.in", "cushmanwakefield.com", "jll.com", "cbre.com",
    "colliers.com", "knightfrank.com", "anarock.com",
    # FinTech/startup directories and ecosystem sites
    "wellfound.com", "angellist.com", "ycombinator.com",
    "builtinpune.in", "builtinmumbai.com", "startupindia.gov.in",
    "inc42.com", "yourstory.com", "entrackr.com", "vccircle.com",
    "techcrunch.com", "businessinsider.com", "Forbes.com", "forbes.com",
    "cataloxy.in", "cataloxy.com",
    "meetfrank.com", "workatastartup.com", "huntyourtribe.com",
    "startupjobs.asia", "cutshort.io", "hirist.tech",
    "f6s.com", "crunchbase.com", "tracxn.com",
    # Property listing aggregators (India)
    "hometrust.in", "indiaproperty.com", "property.sulekha.com",
    "proplocator.in", "realestatemall.com",
})

# Titles that indicate job/career/listing pages — never a company
_JOB_PAGE_TITLE_RE = re.compile(
    r'(?i)(\b\d+\s+(?:remote|hybrid|onsite|open)\s+(?:jobs?|positions?|roles?)'
    r'|\bjobs?\s+(?:in|at|for)\b'
    r'|\bcareers?\s+(?:in|at|for)\b'
    r'|\bhiring\s+(?:in|at|for|now)\b'
    r'|\bwork\s+(?:in|at|for)\s+\w+'
    r'|\bvacancies?\s+(?:in|at)\b'
    r'|\b(?:software|fintech|blockchain)\s+development\s+(?:company\s+)?in\b'
    r'|\bstartups?\s+(?:in|to\s+watch)\b'
    r'|\b(?:top|best|leading)\s+\d*\s*(?:companies|startups?|firms)\b'
    r'|\blist\s+of\b'
    r'|\bdirectory\b'
    r')',
)

# Snippet indicators that this is NOT a company page
_ARTICLE_SNIPPET_RE = re.compile(
    r'(?i)(here\s+(?:are|is)\s+(?:a\s+list|the\s+top|\d+)'
    r'|\bwe\s+(?:have\s+)?(?:compiled|listed|curated|gathered)\b'
    r'|\bthis\s+(?:article|post|guide|list)\b'
    r'|\bcheck\s+out\s+(?:our|this|the)\b'
    r'|\bfeatured\s+(?:in|on)\s+(?:the\s+)?list\b'
    r')',
)

# Blocked page titles — any of these patterns mean the URL is not a company homepage
_BLOCKED_TITLE_RE = re.compile(
    r'(?i)(404|not\s+found|page\s+not\s+found|file\s+not\s+found'
    r'|access\s+denied|error\s+page|under\s+construction'
    r'|coming\s+soon|domain\s+for\s+sale'
    # List/aggregator pages — these are never individual companies
    r'|top\s+\d+\s+(?:real\s+estate|companies|developers|builders|brokers|agents|fintech|startup)'
    r'|list\s+of\s+(?:all\s+)?(?:real\s+estate|companies|startups?|fintech)'
    r'|best\s+(?:real\s+estate|builders|developers|brokers|fintech|startup)\s+in'
    r'|reviews?\s*\|'
    r'|\d{4}\s+reviews?'
    # Job pages
    r'|\d+\s+(?:remote|hybrid|onsite|jobs?|positions?)\s+(?:in|at|for)'
    r'|jobs?\s+in\s+\w+'
    r'|careers?\s+in\s+\w+'
    r'|hiring\s+(?:in|at|for)'
    # Category/directory pages
    r'|(?:fintech|startup|companies|firms)\s+in\s+\w+\s*[\-–|]'
    r'|(?:startups?|companies)\s+list'
    r'|directory\s+of'
    # Software development service pages (not companies in the industry)
    r'|(?:fintech|blockchain|crypto)\s+software\s+development\s+(?:in|company|services)'
    r'|(?:fintech|blockchain)\s+(?:development|solutions)\s+(?:company|services?)\s+in'
    r')',
)

# Separate — used only for company_name cleanup (more aggressive, not for candidate rejection)
_AGGREGATOR_NAME_RE = re.compile(
    r'(?i)((?:real\s+estate\s+)?(?:companies|developers|builders|brokers|agents)\s+in\s+\w+'
    r'|top\s+real\s+estate|commercial\s+real\s+estate\s+agency\s+in'
    r'|reviews?\s*\|)',
)

# ── Candidate validation ───────────────────────────────────────────────────────

# Names that are page titles / generic phrases, not real business names.
# Any company_name that matches (case-insensitive, stripped) is rejected.
_GENERIC_COMPANY_NAMES: frozenset[str] = frozenset({
    # Navigation / UI labels
    "contact", "contact us", "contactus", "contacts", "get in touch",
    "reach us", "reach out", "write to us", "connect with us",
    "home", "homepage", "welcome", "index",
    "about", "about us", "aboutus", "our story", "who we are",
    "services", "our services", "solutions", "our solutions",
    "products", "our products", "offerings",
    # Error pages
    "page not found", "404", "error", "403", "500",
    "access denied", "coming soon", "under construction", "domain for sale",
    # Auth pages
    "login", "sign in", "signin", "sign up", "signup", "register",
    # Generic industry / city terms that are not company names
    "fintech", "fin tech", "finance", "financial services", "banking",
    "real estate", "realty", "property", "properties",
    "it", "information technology", "software", "tech", "technology",
    "startup", "startups", "company", "companies", "firm", "firms",
    "business", "businesses", "enterprise", "enterprises",
    # Location terms alone
    "pune", "mumbai", "delhi", "bangalore", "bengaluru", "india",
    "maharashtra", "india pvt ltd",
    # Aggregator/list page titles — exactly the kind of junk page titles
    # mentioned in the brief that must NEVER become company names
    "fintech startups in pune", "fintech companies in pune",
    "fintech startups", "fintech companies",
    "startups in pune", "companies in pune", "top fintech", "best fintech",
    "fintech pune", "pune fintech",
    "real estate companies in pune", "real estate companies",
    "it companies in pune", "it companies",
    "software companies in pune", "software companies",
    "startups in pune india", "tech startups in pune",
    "top 10 fintech", "top 10 startups", "top 10 companies",
    "best fintech startups", "leading fintech companies",
    # Job / careers pages
    "jobs", "careers", "hiring", "vacancies", "open positions",
    # Common tab titles
    "news", "blog", "media", "press", "gallery", "faq", "faqs",
    "privacy policy", "terms", "terms of service", "terms and conditions",
    "sitemap", "cookie policy",
    # Additional generic page/section titles
    "investors", "investor relations", "our team", "leadership",
    "management", "board of directors", "partners", "portfolio",
    "testimonials", "case studies", "events", "downloads", "resources",
})

# Regex for names that look like list/article/SEO page titles
_GENERIC_NAME_RE = re.compile(
    r'(?i)^(?:'
    # "Top N X in Y", "Best X in Y", "List of X in Y"
    r'(?:top|best|leading|list\s+of)\s+\d*\s*\w+'
    r'|(?:top|best|leading)\s+(?:fintech|companies|startups?|firms|real\s+estate)'
    r'|\d+\s+(?:fintech|companies|startups?|firms|real\s+estate)'
    # Pure city/industry combos with "in"
    r'|(?:fintech|startup|tech|software|it|real\s+estate)\s+(?:in\s+)?(?:pune|mumbai|india|delhi|bangalore)'
    r'|(?:pune|mumbai|india)\s+(?:fintech|startup|tech|software|it|real\s+estate)'
    # Just a generic industry word + "company/companies/startup(s)"
    r'|(?:fintech|tech|software|it|digital|real\s+estate)\s+(?:company|companies|startups?|solutions?|firms?)'
    # Industry alone as the entire name (single/two-word pure industry terms)
    r'|fintech|fin\s+tech|real\s+estate|information\s+technology'
    r'|e[\-\s]?commerce|health\s*(?:tech|care)'
    # "X in Y" patterns where X is an industry and Y is a city — these are article titles
    r'|(?:fintech|startup|software|it|tech|real\s+estate|companies)\s+in\s+\w+'
    r')',
)

# Keywords that must appear in scraped content for industry relevance.
# Maps normalised industry token → list of keyword alternatives (OR logic).
# A company passes if ANY keyword from its industry group is found.
_INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "fintech":        ["fintech", "fin-tech", "financial technology", "payments", "lending",
                       "neobank", "neo bank", "insurtech", "wealthtech", "regtech",
                       "digital banking", "digital payment", "upi", "wallet", "loan",
                       "credit", "investment platform", "trading platform", "nbfc",
                       "microfinance", "remittance", "blockchain", "cryptocurrency",
                       "robo-advisor", "open banking"],
    "real estate":    ["real estate", "property", "realty", "builder", "developer",
                       "residential", "commercial property", "flat", "apartment",
                       "land development", "construction", "housing"],
    "it":             ["software", "information technology", "it services", "saas",
                       "cloud", "devops", "cybersecurity", "erp", "it consulting",
                       "web development", "app development", "data analytics"],
    "healthcare":     ["healthcare", "hospital", "clinic", "medical", "pharma",
                       "diagnostics", "telemedicine", "health tech"],
    "education":      ["edtech", "education", "e-learning", "online learning",
                       "training", "academy", "institute", "university", "school"],
    "ecommerce":      ["ecommerce", "e-commerce", "online store", "marketplace",
                       "retail", "d2c", "direct to consumer"],
}

# Pune-relevance keywords — must appear in scraped content or address
_PUNE_KEYWORDS: list[str] = [
    "pune", "pimpri", "chinchwad", "pcmc", "hadapsar", "kharadi", "baner",
    "wakad", "hinjewadi", "viman nagar", "koregaon park", "aundh", "bavdhan",
    "magarpatta", "kothrud", "shivajinagar", "deccan", "swargate",
    "yerawada", "wagholi", "vishrantwadi",
]


def _normalise_industry_key(query: str) -> str:
    """Map a user query to a known industry key, or return the raw industry token."""
    industry, _ = _parse_query(query)
    il = industry.lower().strip()
    # Direct mappings
    _MAP = {
        "fintech": "fintech", "fin tech": "fintech", "financial technology": "fintech",
        "real estate": "real estate", "realty": "real estate", "property": "real estate",
        "it": "it", "information technology": "it", "software": "it", "tech": "it",
        "healthcare": "healthcare", "health": "healthcare",
        "education": "education", "edtech": "education",
        "ecommerce": "ecommerce", "e-commerce": "ecommerce",
    }
    return _MAP.get(il, il)


def _is_generic_company_name(name: str) -> bool:
    """Return True if name is a generic page title / phrase, not a real business name."""
    if not name:
        return True
    nl = name.lower().strip()
    # Exact match in frozen set
    if nl in _GENERIC_COMPANY_NAMES:
        return True
    # Regex patterns (list titles, city+industry combos, etc.)
    if _GENERIC_NAME_RE.match(nl):
        return True
    # Single-word names that are pure generic nouns
    if nl in {"fintech", "startup", "company", "finance", "tech", "pune",
              "mumbai", "india", "software", "solutions", "services", "digital"}:
        return True
    # Names that are just a city name + noise
    for city in ("pune", "mumbai", "delhi", "bangalore", "bengaluru"):
        if nl == city or nl == city + " india":
            return True
    return False


def _domain_matches_company(domain: str, company_name: str) -> bool:
    """
    Verify the company name is plausibly associated with this domain.

    The domain must "belong" to the company — we check for token overlap
    between the domain stem and the company name.  This prevents accepting
    a page where a generic title like "Contact Us" or "Fintech" was
    mis-extracted as the company name for some unrelated domain.

    Rules:
      - If either is missing, pass (can't judge).
      - Strip stop-words, then check for ANY token overlap between the
        domain stem and the company name.
      - If there is token overlap → pass (domain belongs to the company).
      - If there is NO overlap AND the name is generic → reject definitively.
      - If there is NO overlap AND the name looks like a real brand
        (not a generic phrase) → still pass, because many companies use
        brand names that share no words with their domain
        (e.g. "Cred" on "dreamplug.io", "Razorpay" on "razorpay.com" ✓).
    """
    if not domain or not company_name:
        return True  # can't judge without both

    # Reject outright if the name itself is generic regardless of domain
    if _is_generic_company_name(company_name):
        return False

    # Extract stem: "mypayments.in" → "mypayments"
    stem = domain.split(".")[0].lower().replace("-", " ").replace("_", " ")
    name_lower = company_name.lower()

    # Tokenise both sides (ignore very short tokens ≤ 2 chars)
    stem_tokens = {t for t in re.split(r'\W+', stem) if len(t) >= 3}
    name_tokens = {t for t in re.split(r'\W+', name_lower) if len(t) >= 3}

    # Remove generic stop-words from both sides before comparing
    _STOP = {"pvt", "ltd", "private", "limited", "inc", "llp", "llc",
              "and", "the", "for", "com", "org", "net", "india",
              "technologies", "technology", "solutions", "services",
              "group", "global", "digital", "systems", "ventures"}
    name_tokens -= _STOP
    stem_tokens -= _STOP

    if not name_tokens:
        # Name reduced entirely to stop-words (e.g. "India Pvt Ltd") — can't judge
        return True

    # Token overlap → domain belongs to this company
    if stem_tokens & name_tokens:
        return True

    # No overlap — allow if the name looks like a real brand name
    # (i.e. it is NOT a generic phrase).  Many legitimate companies have
    # creative brand names that share no words with their domain stem.
    return True  # pass through; _is_generic_company_name already handled generics above


def _has_industry_relevance(text: str, industry_key: str) -> bool:
    """Return True if scraped text mentions any keyword for the given industry."""
    if not industry_key:
        return True  # unknown industry — pass through
    keywords = _INDUSTRY_KEYWORDS.get(industry_key, [])
    if not keywords:
        return True  # no keyword list for this industry — pass through
    tl = text.lower()
    return any(kw in tl for kw in keywords)


def _has_pune_relevance(company: dict) -> bool:
    """Return True if address, city, or scraped content mentions Pune or surroundings."""
    # Check structured address fields first
    for field in ("city", "address", "state"):
        val = (company.get(field) or "").lower()
        if any(kw in val for kw in _PUNE_KEYWORDS):
            return True
    # Check domain (e.g. company uses .in TLD registered in Pune area)
    domain = (company.get("domain") or "").lower()
    # Some companies have "pune" in their domain
    if any(kw in domain for kw in ("pune", "pcmc", "pimpri")):
        return True
    # Fall back to full scraped markdown
    md = (company.get("_merged_markdown") or "").lower()
    return any(kw in md for kw in _PUNE_KEYWORDS)


def validate_candidate(company: dict, query: str) -> tuple[bool, str]:
    """
    Post-extraction validation gate.  Called inside _process_candidate()
    after extract_company_info() + contact_gap_search() + verify_company().

    Returns (True, "") if the company passes all checks.
    Returns (False, reason) if any check fails — the candidate is dropped.

    Checks (in order):
      1. company_name is not a generic page title / aggregator title
      2. domain is present (we must have an official domain)
      3. domain ↔ name coherence (name is not a mis-extraction from the page)
      4. industry relevance  (scraped content mentions the requested industry)
      5. Pune relevance      (content / address mentions Pune or surroundings)
         — only enforced when the query asks for Pune
    """
    name   = (company.get("company_name") or "").strip()
    domain = (company.get("domain") or "").strip()
    md     = company.get("_merged_markdown") or ""

    # 1. Real business name — never a page title or generic phrase
    if _is_generic_company_name(name):
        return False, f"generic/page-title name {name!r}"

    # 2. Must have a resolvable domain
    if not domain:
        return False, "no domain — cannot verify official website"

    # 3. Domain ↔ name: reject if the name is generic (already caught above
    #    but _domain_matches_company also rejects generic names paired with
    #    any domain so we keep it for belt-and-suspenders).
    if not _domain_matches_company(domain, name):
        return False, f"name {name!r} does not match domain {domain!r}"

    # 4. Industry relevance — scraped content must mention the industry
    industry_key = _normalise_industry_key(query)
    if not _has_industry_relevance(md, industry_key):
        # Also accept if the company name itself contains a strong industry signal
        # (some companies have very short homepages that don't repeat keywords)
        name_has_industry = _has_industry_relevance(name, industry_key)
        # Also accept if domain contains industry signal (e.g. "finpay.in")
        domain_has_industry = _has_industry_relevance(domain, industry_key)
        if not name_has_industry and not domain_has_industry:
            return False, f"no {industry_key!r} keywords in scraped content, name, or domain"

    # 5. Pune relevance — required when query is for Pune
    _, city = _parse_query(query)
    if city and city.lower() in _PUNE_KEYWORDS:
        if not _has_pune_relevance(company):
            return False, "no Pune/Pimpri/Hinjewadi relevance in content or address"

    # 6. Extra: reject global enterprise companies without Pune evidence
    # (e.g. Fiserv, FIS, Visa, Mastercard appearing without Pune content)
    if city and city.lower() in _PUNE_KEYWORDS:
        _GLOBAL_CORPS = frozenset({
            "fiserv", "fis", "visa", "mastercard", "paypal", "stripe",
            "razorpay", "paytm", "phonepe", "googlepay", "amazon",
            "microsoft", "google", "apple", "meta", "ibm", "oracle",
            "accenture", "infosys", "wipro", "tcs", "cognizant",
            "hsbc", "citibank", "barclays", "jpmorgan", "goldman",
        })
        domain_stem = (domain or "").split(".")[0].lower()
        if domain_stem in _GLOBAL_CORPS:
            # Only accept if there's explicit Pune evidence in scraped content
            if not _has_pune_relevance(company):
                return False, f"global corp {domain_stem!r} with no Pune operation evidence"

    return True, ""

# Path patterns that indicate list/aggregator/blog pages (not company homepages)
_AGGREGATOR_PATH_RE = re.compile(
    r'(?i)/(?:blog|blogs|news|article|articles|top[-_]?\d+|best[-_]?\d*'
    r'|list[-_]of|guide|reviews?|directory|search|category|tag'
    r'|media|magazine|pdf|document'
    r'|en/[a-z-]+/offices?'          # e.g. cushmanwakefield.com/en/india/offices/pune
    r'|real[-_]?estate[-_]?(?:companies|agents|developers|in)'
    r')[\-/]'
    r'|/offices/[a-z]'               # e.g. savills.in/offices/estate-agents-in-pune
    r'|/c/[a-z]'                     # e.g. aeroleads.com/c/company-name
    r'|/companies/[a-z]',            # e.g. f6s.com/companies/real-estate/india/...
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
    """
    Build targeted search queries to surface OFFICIAL COMPANY WEBSITES.
    Goal: find individual company domains, not articles/directories/job pages.

    For "FinTech in Pune" returns 8 targeted queries that together surface
    company homepages, contact pages, and leadership pages.

    Key principles:
    - Use explicit negative exclusions for major aggregators/social/job-sites
    - Use location-anchor phrases ("based in Pune", "Pune office") to require
      local presence evidence in results
    - Use "pvt ltd" / "private limited" to force Indian registered companies
    - Include founder/CEO searches to surface leadership pages of real companies
    - Use intitle: sparingly (can reduce recall) but helps precision
    """
    industry, city = _parse_query(query)
    if city:
        neg = (
            f'-site:linkedin.com -site:naukri.com -site:indeed.com '
            f'-site:glassdoor.com -site:justdial.com -site:indiamart.com '
            f'-site:crunchbase.com -site:tracxn.com -site:inc42.com '
            f'-site:yourstory.com -site:moneycontrol.com -site:economictimes.com '
            f'-site:wikipedia.org -site:ambitionbox.com -site:zaubacorp.com'
        )
        return [
            # Query 1: company + city — general company discovery
            (f'{industry} company {city} {neg}'),
            # Query 2: companies plural (targets list-search but with negative filters)
            (f'{industry} companies {city} official website {neg}'),
            # Query 3: location-anchor — requires Pune presence signal in result
            (f'{industry} "{city}" "based in {city}" OR "{city} office" OR '
             f'"{city} headquarters" OR "headquartered in {city}"'),
            # Query 4: contact page — official company contact pages
            (f'{industry} {city} "contact us" "pvt ltd" OR "private limited" {neg}'),
            # Query 5: founder/CEO search — surfaces company leadership pages
            (f'{industry} {city} founder OR CEO OR "managing director" '
             f'"pvt ltd" OR "private limited" {neg}'),
            # Query 6: official website search — "pvt ltd" is a strong company signal
            (f'{industry} "{city}" "pvt ltd" OR "private limited" '
             f'OR "LLP" official website -inurl:jobs -inurl:careers {neg}'),
            # Query 7: headquarters-specific — surfaces companies with registered offices
            (f'{industry} "{city}" headquarters OR "registered office" '
             f'OR "corporate office" {neg}'),
            # Query 8: direct domain-style searches — .com and .in TLD focus
            (f'"{industry}" "{city}" site:.in OR site:.co.in OR site:.com '
             f'-site:linkedin.com -site:naukri.com -site:indeed.com '
             f'-site:justdial.com -site:crunchbase.com -site:inc42.com'),
        ]
    return [
        f'"{query}" company official website -inurl:jobs',
        f'"{query}" "contact us" -site:linkedin.com -site:naukri.com',
        f'"{query}" CEO OR founder "pvt ltd" OR "private limited"',
        f'"{query}" "about us" -inurl:blog -inurl:article',
        f'"{query}" "pvt ltd" OR "private limited" OR "LLP" contact',
        f'"{query}" headquarters OR "registered office" official',
    ]


async def _serper_search(client: httpx.AsyncClient, q: str, num: int = 10) -> list[dict]:
    """Run a single Serper search. Returns a list of result dicts.

    Valid Serper /search parameters: q (str), num (int 1–100), gl (str), hl (str),
    page (int), autocorrect (bool), tbs (str).  Any unknown key causes HTTP 400.
    """
    if not SERPER_API_KEY:
        _log("DISCOVERY", "SERPER_API_KEY not set — skipping search")
        return []
    if not q or not q.strip():
        _log("DISCOVERY", "Empty query — skipping Serper call")
        return []

    # Serper accepts num in range [1, 100]; clamp to avoid 400
    safe_num = max(1, min(num, 100))

    _stats.serper_calls += 1
    try:
        resp = await client.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": q.strip(), "num": safe_num},
            timeout=_T_SERPER,
        )
        if resp.status_code == 400:
            _log("DISCOVERY", f"Serper 400 Bad Request for {q!r} — response: {resp.text[:200]}")
            return []
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        _log("DISCOVERY", f"Serper HTTP {exc.response.status_code} for {q!r}: {exc.response.text[:200]}")
        return []
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
    tasks  = [_serper_search(client, q, num=min(15, max(target, 10))) for q in queries]
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

            # Reject job/career/article/list page titles
            if _JOB_PAGE_TITLE_RE.search(title):
                n_bad_title += 1
                _log("FILTER", f"Rejected (job/article title): {title!r} — {link}")
                continue

            # Reject snippets that look like articles/directories
            snippet = r.get("snippet", "")
            if _ARTICLE_SNIPPET_RE.search(snippet) and not r.get("source") == "knowledge_graph":
                n_dir += 1
                _log("FILTER", f"Rejected (article snippet): {title!r} — {link}")
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

            # Reject deep sub-page URLs (5+ path segments = likely a directory sub-page)
            # e.g. /companies/real-estate/india/maharashtra/pune/co
            #      /en/india/cities/pune/office (Colliers, JLL sub-pages)
            # Note: 4 segments is too aggressive — many legit company pages like
            # /about-us/leadership/team/management have 4 segments.
            path_segments = [s for s in parsed_path.strip("/").split("/") if s]
            if len(path_segments) >= 5:
                n_dir += 1
                _log("FILTER", f"Rejected (deep sub-page {len(path_segments)} segments): {link}")
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
    # Industry/city bare words that are never a company name
    "fintech", "fin tech", "startup", "startups", "pune", "mumbai",
    "india", "finance", "technology", "tech", "software", "digital",
    "company", "companies", "firm", "firms",
    # Aggregator page titles
    "fintech startups in pune", "fintech companies in pune",
    "startups in pune", "companies in pune",
    "fintech pune", "pune fintech",
    # Job / misc navigation
    "jobs", "careers", "news", "blog", "media", "press",
    "privacy policy", "terms", "sitemap",
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
    r'|[®™©]\s*(?:official\s+\S+.*|\.\.\.*|\s*$)'
    r'|\s*!\s*(?:residential|commercial|luxury|premium|real\s+estate|'
    r'properties|projects|builders|developers).*$',
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
    # Clean og:site_name of common suffixes too
    og_name = _STRIP_OFFICIAL_RE.sub("", og_name).strip()
    og_name = _STRIP_GEO_SUFFIX_RE.sub("", og_name).strip()
    # Remove leading "[Official]" bracket-patterns
    og_name = re.sub(r'^\[.*?\]\s*', '', og_name).strip()
    raw_title  = (metadata.get("title") or "").strip()

    def _clean_title(t: str) -> str:
        """Strip marketing/geo suffixes from a page title."""
        # Remove leading [Official] or [Verified] bracket patterns
        t = re.sub(r'^\[.*?\]\s*', '', t).strip()
        t = _STRIP_GEO_SUFFIX_RE.sub("", t).strip()
        t = _STRIP_OFFICIAL_RE.sub("", t).strip()
        t = _STRIP_BRAND_PREFIX_RE.sub("", t).strip()
        t = _STRIP_SUFFIX_RE.sub("", t).strip()
        # Strip colon + anything after for verbose titles like "Gera: Premium Real Estate..."
        t = re.sub(r'\s*:\s*(?:Premium|Luxury|Leading|Top|Best|Official).*$', '', t, flags=re.IGNORECASE).strip()
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
    # Strip fintech/startup category prefixes: "FinTech Startups in Pune — Acme Pay"
    serper_title = re.sub(
        r'(?i)^(?:fintech|fin\s*tech|startup|tech|software|it)\s+'
        r'(?:companies?|startups?|firms?)?\s*(?:in\s+\w+\s*)?[—\-–|]\s*',
        "", serper_title,
    ).strip()
    if serper_title.lower() in _GENERIC_TITLES:
        serper_title = ""
    if serper_title and (_BLOCKED_TITLE_RE.search(serper_title) or _AGGREGATOR_NAME_RE.search(serper_title)):
        serper_title = ""
    # Reject serper title if it looks like a generic industry+city combination
    if serper_title and _GENERIC_NAME_RE.match(serper_title.lower()):
        serper_title = ""

    domain_raw  = search_result.get("domain", "")
    domain_name = domain_raw.split(".")[0].replace("-", " ").title() if domain_raw else ""

    # Priority: og:site_name → page title segment → serper title → domain stem
    # At each step, reject if the candidate is a generic phrase.
    company_name = ""
    for candidate in (og_name, title_name, serper_title, domain_name):
        c = (candidate or "").strip()
        if c and not _is_generic_company_name(c):
            company_name = c
            break
    # Last resort: domain stem as-is (even if short) — better than nothing
    if not company_name:
        company_name = domain_name

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
    if not q or not q.strip():
        return ""
    _stats.serper_calls += 1
    try:
        resp = await client.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": q.strip(), "num": 5},
            timeout=_T_SERPER,
        )
        if resp.status_code == 400:
            _log("CONTACT_SEARCH", f"Serper 400 Bad Request for {q!r} — response: {resp.text[:200]}")
            return ""
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        _log("CONTACT_SEARCH", f"Serper HTTP {exc.response.status_code} for {q!r}: {exc.response.text[:200]}")
        return ""
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
        gap_queries.append(("email_at", f'"{name}" "@{domain}"' if domain else f'"{name}" official email'))
    if not phones:
        q = f'"{name}" phone number site:{domain}' if domain else f'"{name}" phone number'
        gap_queries.append(("phone", q))
    if not addr:
        city = company.get("city", "")
        gap_queries.append(("address", f'"{name}" office address {city}'.strip()))
    if not founder:
        # Use multiple targeted queries to maximize founder discovery
        gap_queries.append(("founder", f'"{name}" founder CEO "managing director"'))
        if domain:
            gap_queries.append(("founder_site", f'site:{domain} founder OR CEO OR "co-founder"'))

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
                    candidate_name = m.group(0)
                    # Validate it looks like a real person name
                    from app.services.verify_service import _is_plausible_person_name
                    if _is_plausible_person_name(candidate_name):
                        updated["founder_name"] = candidate_name
                        _log("CONTACT_SEARCH", f"{name}: found founder from gap search: {candidate_name!r}")
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
    Preserves _scraped_pages, _merged_markdown, and _field_verification
    (populated by verify_service) for ENRICH/VERIFY stages and MongoDB storage.
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
        "confidence":       c.get("confidence", 0.0),   # carry through verify_service score
        "last_verified":    None,
        # Research source trace
        "research_source":  "serper_firecrawl",
        "research_sources": sources,
        # Pipeline internal keys (used by ENRICH + VERIFY, stripped before storage)
        "_scraped_pages":   c.get("_scraped_pages", []),
        "_merged_markdown": c.get("_merged_markdown", ""),
        "pages_visited":    c.get("pages_visited", {"success": [], "failed": []}),
        # CRITICAL: carry field-level verification evidence from verify_service
        # This populates the provider source breakdown in the audit report.
        "_field_verification": c.get("_field_verification", {}),
        "_serper_title":    c.get("_serper_title", ""),
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
    query: str = "",
) -> Optional[dict]:
    """
    Scrape + extract + gap-search + context-verify + validate one candidate.
    Returns a normalized company dict, or None if validation fails.
    """
    url  = search_result["link"]
    name = search_result.get("title", url)
    dom  = search_result.get("domain", "")

    # Pre-filter: if the domain is clearly a global corp and the query requests
    # a city, do a quick name-relevance check before expensive Firecrawl call
    if query:
        _, city = _parse_query(query)
        if city and city.lower() in _PUNE_KEYWORDS:
            _GLOBAL_SIGNAL_DOMS = {
                "fiserv.com", "fisglobal.com", "visa.com", "mastercard.com",
                "paypal.com", "stripe.com", "accenture.com", "ibm.com",
                "oracle.com", "cognizant.com", "wipro.com", "infosys.com",
            }
            if dom in _GLOBAL_SIGNAL_DOMS:
                snippet = (search_result.get("snippet") or "").lower()
                title_l = (name or "").lower()
                if not any(kw in snippet or kw in title_l for kw in _PUNE_KEYWORDS):
                    _log("FILTER", f"Pre-filter: global corp {dom!r} has no Pune evidence in snippet")
                    return None

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

        # CANDIDATE VALIDATION — reject generic names, missing domains,
        # off-industry content, and non-Pune companies
        if query:
            ok, reason = validate_candidate(company, query)
            if not ok:
                _log("VALIDATE", f"Rejected {company.get('company_name','?')!r} ({reason}) — {url}")
                return None

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

    # Steps 2–5: scrape + extract + gap-search + validate all candidates concurrently
    tasks   = [_process_candidate(c, sem, query=query) for c in candidates]
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
    # Print rejected count for monitoring
    rejected = len(candidates) - len([r for r in results if isinstance(r, dict) and r.get("company_name")])
    _log("VALIDATION", f"Rejected invalid candidates: {rejected} | Valid companies: {len(unique)}")

    return {
        "query":     query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "companies": unique,
        "total":     len(unique),
        "status":    "success",
        "_elapsed":  round(elapsed, 1),
        "_stats":    vars(_stats),
    }
