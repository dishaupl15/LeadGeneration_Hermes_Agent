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
from app.services import companyenrich_service as _companyenrich

# ── Config ────────────────────────────────────────────────────────────────────
SERPER_API_KEY    = os.getenv("SERPER_API_KEY", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
COMPANYENRICH_API_KEY = os.getenv("COMPANYENRICH_API_KEY", "")

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
    "pharma":         [
        # CE industry field values that will appear in _merged_markdown
        "pharma", "pharmaceutical", "pharmaceuticals", "pharmacy",
        "biopharma", "biopharmaceutical",
        "life science", "life sciences",
        # Drug/medicine compound terms
        "drug manufacturer", "drug manufacturing", "drug company",
        "medicine manufacturer", "medicine manufacturing",
        "generic drug", "bulk drug",
        "api manufacturer", "api manufacturing",
        "active pharmaceutical",
        # Process/product description terms
        "clinical", "formulation", "dosage", "tablet", "capsule",
        "injectable",
        "pharma company", "pharma manufacturing",
        "pharmaceutical company", "pharmaceutical manufacturing",
        "pharmaceutical manufacturer",
        "specialty pharma", "nutraceutical",
        "ayurvedic", "herbal medicine",
        "contract manufacturing", "cmo", "cdmo",
        "clinical trials",
    ],
    "biotech":        ["biotech", "biotechnology", "life science", "life sciences",
                       "bioscience", "biopharma", "biopharmaceutical", "genomics",
                       "cell therapy", "gene therapy", "biological", "bioprocess",
                       "biomanufacturing"],
    "manufacturing":  [
        # Core manufacturing terms — these will always appear in CE industry field
        "manufacturing", "manufacturer", "manufacturers",
        "fabrication", "fabricator", "fabricators",
        # Compound CE industry field variants
        "industrial manufacturing", "engineering manufacturing",
        "precision manufacturing", "precision engineering",
        "metal fabrication", "auto components", "automotive component",
        "machine tools", "machine shop",
        "precision components", "industrial components",
        "engineering works", "industrial automation",
        # Description-level terms common in mfg company descriptions
        "machinery", "factory", "plant", "foundry",
        "casting", "forging", "molding", "tooling",
        "machined", "fabricated",
        "manufacturing unit", "production facility",
        "electrical panel", "pump", "valve", "welding",
    ],
    "education":      ["edtech", "education", "e-learning", "online learning",
                       "training", "academy", "institute", "university", "school"],
    # ecommerce: requires SPECIFIC online-retail evidence — "retail" alone is insufficient
    # because logistics/services companies also mention "retail" as a sector they serve.
    # A company that BUILDS e-commerce websites is NOT an e-commerce company.
    "ecommerce":      ["ecommerce", "e-commerce", "online store", "online storefront",
                       "online retail", "online shopping", "online marketplace",
                       "b2c marketplace", "retail platform", "d2c", "direct-to-consumer",
                       "direct to consumer", "consumer brand", "online sales",
                       "sells products online", "sells online"],
    # saas: requires SaaS-specific evidence
    "saas":           ["saas", "software as a service", "cloud software", "cloud platform",
                       "subscription software", "software platform", "cloud-based software",
                       "cloud application", "software product", "b2b saas", "enterprise saas"],
    # construction: matches CE structured industry field values AND description text.
    # _merged_markdown for CE candidates = "{name} {ce_industry} {ce_desc}", so all
    # CE industry field variants must appear here as substring keywords.
    "construction":   [
        # Bare CE industry field values (most common returns from CompanyEnrich)
        "construction", "contractor", "civil engineer",
        "infrastructure", "builder",
        # Compound CE industry field variants
        "civil contractor", "civil construction",
        "building construction", "construction company",
        "construction contractor", "construction and infrastructure",
        "construction services", "engineering & construction",
        "construction & engineering", "construction & infrastructure",
        "real estate & construction", "real estate and construction",
        "infrastructure construction", "general contractor",
        "building contractor", "builder contractor",
        "engineering services", "building services",
        "building materials", "construction materials",
        "construction firm", "construction group",
        # Real estate / developer overlaps explicitly requested
        "real estate developer", "property developer", "infrastructure developer",
        "real estate builder",
    ],
    # ── New categories ──────────────────────────────────────────────────────────
    "retail":         [
        "retail", "retailer", "retail store", "retail chain", "retail outlet",
        "retail trade", "fmcg", "consumer goods", "supermarket", "hypermarket",
        "departmental store", "grocery", "convenience store",
        "shop", "shopping", "merchandise", "point of sale",
        "b2c retail", "consumer retail", "physical retail",
        "distribution and retail", "wholesale and retail",
    ],
    "agriculture":    [
        "agriculture", "agricultural", "agri", "agro",
        "farming", "farm", "agribusiness", "agri-business",
        "horticulture", "crop", "seeds", "fertilizer", "pesticide",
        "irrigation", "dairy", "poultry", "livestock",
        "food processing", "milling", "organic farming",
        "agri input", "agri output", "agricultural produce",
        "soil", "harvest", "cultivation", "plantation",
    ],
    "logistics":      [
        "logistics", "logistics company", "transport", "transportation",
        "freight", "courier", "shipping", "supply chain",
        "warehousing", "distribution", "last mile",
        "cargo", "fleet management", "trucking",
    ],
    "hospitality":    [
        "hotel", "hospitality", "resort", "accommodation", "motel",
        "guesthouse", "inn", "lodge", "tourism", "travel agency",
        "tour operator", "hospitality company",
    ],
    "finance":        [
        "financial services", "investment", "banking", "insurance",
        "nbfc", "wealth management", "asset management",
        "stock broker", "mutual fund", "financial planning",
        "credit", "lending", "loans", "microfinance",
    ],
    "food":           [
        "food", "food processing", "food manufacturing", "food company",
        "restaurant", "cafe", "catering", "bakery", "beverage",
        "snacks", "packaged food", "food and beverage",
        "fmcg food", "consumer food",
    ],
    "textile":        [
        "textile", "garment", "apparel", "clothing", "fashion",
        "fabric", "yarn", "fibre", "weaving", "knitting",
        "spinning", "dyeing", "readymade garment",
        "textile manufacturing", "garment manufacturing",
    ],
    "automotive":     [
        "automotive", "automobile", "auto", "vehicle", "car",
        "two wheeler", "four wheeler", "commercial vehicle",
        "auto components", "auto parts", "automotive manufacturer",
        "car dealer", "vehicle manufacturer",
    ],
    "chemicals":      [
        "chemicals", "chemical", "specialty chemicals",
        "agrochemicals", "petrochemicals", "fine chemicals",
        "industrial chemicals", "chemical manufacturer",
        "chemical company", "polymer", "dye", "pigment",
    ],
    "energy":         [
        "energy", "solar", "renewable energy", "power",
        "oil and gas", "wind energy", "biomass", "hydro",
        "electricity", "power generation", "energy company",
        "solar panel", "solar power",
    ],
    "media":          [
        "media", "entertainment", "publishing", "news", "broadcast",
        "digital media", "content", "film", "television", "radio",
        "streaming", "media company", "news agency",
    ],
    "telecom":        [
        "telecom", "telecommunications", "telecom services",
        "internet service", "broadband", "mobile network",
        "telecom company", "isp", "network provider",
    ],
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
        "pharma": "pharma", "pharmaceutical": "pharma", "pharmaceuticals": "pharma",
        "pharmaceutical company": "pharma", "pharmaceuticals company": "pharma",
        "biotech": "biotech", "bio tech": "biotech", "biotechnology": "biotech",
        "life science": "biotech", "life sciences": "biotech",
        "manufacturing": "manufacturing", "fabrication": "manufacturing", "fabricator": "manufacturing",
        "fabricators": "manufacturing", "manufacture": "manufacturing", "manufacturer": "manufacturing",
        "industrial": "manufacturing", "engineering works": "manufacturing",
        "machine shop": "manufacturing", "foundry": "manufacturing",
        "production": "manufacturing", "assembly": "manufacturing",
        "components": "manufacturing", "parts": "manufacturing",
        "factory": "manufacturing", "plant": "manufacturing",
        "education": "education", "edtech": "education",
        "ecommerce": "ecommerce", "e-commerce": "ecommerce",
        "saas": "saas", "software as a service": "saas",
        "construction": "construction", "contractor": "construction",
        "civil contractor": "construction", "builder": "construction",
        "civil construction": "construction", "infrastructure": "construction",
        "building construction": "construction", "civil": "construction",
        # retail
        "retail": "retail", "retail trade": "retail", "retail store": "retail",
        "retail company": "retail", "retail shop": "retail",
        "fmcg": "retail", "consumer goods": "retail",
        # agriculture
        "agriculture": "agriculture", "agri": "agriculture", "agro": "agriculture",
        "farming": "agriculture", "farm": "agriculture", "agribusiness": "agriculture",
        "agricultural": "agriculture", "horticulture": "agriculture",
        "dairy": "agriculture", "poultry": "agriculture",
        # logistics
        "logistics": "logistics", "transport": "logistics", "transportation": "logistics",
        "freight": "logistics", "courier": "logistics", "shipping": "logistics",
        # hospitality
        "hospitality": "hospitality", "hotel": "hospitality", "resort": "hospitality",
        "tourism": "hospitality", "travel": "hospitality",
        # finance
        "finance": "finance", "financial services": "finance", "banking": "finance",
        "insurance": "finance", "investment": "finance", "nbfc": "finance",
        "wealth management": "finance",
        # food & beverage
        "food": "food", "food and beverage": "food", "f&b": "food",
        "restaurant": "food", "food processing": "food", "beverage": "food",
        "food manufacturing": "food",
        # textile
        "textile": "textile", "garment": "textile", "apparel": "textile",
        "clothing": "textile", "fashion": "textile",
        # auto / automotive
        "automotive": "automotive", "automobile": "automotive", "auto": "automotive",
        "vehicles": "automotive", "car manufacturer": "automotive",
        # chemicals
        "chemicals": "chemicals", "chemical": "chemicals", "specialty chemicals": "chemicals",
        "agrochemicals": "chemicals", "petrochemicals": "chemicals",
        # energy
        "energy": "energy", "solar": "energy", "renewable energy": "energy",
        "power": "energy", "oil and gas": "energy",
        # media
        "media": "media", "entertainment": "media", "publishing": "media",
        "news": "media", "digital media": "media",
        # telecom
        "telecom": "telecom", "telecommunications": "telecom", "telecom services": "telecom",
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


def _domain_matches_company(domain: str, company_name: str, ce_verified: bool = False) -> bool:
    """
    Verify the company name is plausibly associated with this domain.

    For CompanyEnrich candidates, `ce_verified=True` is passed when the domain
    was returned directly by CE /companies/enrich for this company — that
    explicit CE relationship is treated as authoritative.

    For all others, we require token overlap between the domain stem and the
    company name, or fall back to allowing it only when the name is non-generic
    and no clear contradiction exists.

    The CRITICAL fix: the previous implementation always returned True for
    non-generic brand names, allowing "QULEISS Technologies" to pass with
    domain="refrens.com". We now detect obvious mismatches.
    """
    if not domain or not company_name:
        return True  # can't judge without both

    # Reject outright if the name itself is generic regardless of domain
    if _is_generic_company_name(company_name):
        return False

    # If CompanyEnrich explicitly returned this domain for this company
    # (i.e. the enrichment API call confirmed the relationship), trust it.
    if ce_verified:
        return True

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

    # ── Compound-slug check ───────────────────────────────────────────────────
    # Domains like "diwacivilcontractor.com" have a slug stem "diwacivilcontractor"
    # which tokenizes as ONE token (no hyphens/underscores to split on).
    # The company name "Diwa Civil Contractor" tokenizes as ["diwa","civil","contractor"].
    # Standard token-overlap fails because "diwacivilcontractor" ≠ any individual token.
    #
    # Fix: check whether ALL significant name tokens appear as substrings inside
    # the domain stem (in order is not required — just presence). This correctly
    # accepts "Diwa Civil Contractor" → "diwacivilcontractor.com" while still
    # rejecting "QULEISS Technologies" → "refrens.com" because "quleiss" and
    # "technologies" (removed by _STOP) → only "quleiss" must appear in "refrens" → False.
    slug = domain.split(".")[0].lower()  # raw slug without TLD
    # All name tokens must appear as substrings in the slug
    if name_tokens and all(tok in slug for tok in name_tokens):
        return True
    # Also try: at least the first/most-distinctive name token in the slug
    # combined with high overlap (≥ 60% of name tokens in slug)
    if name_tokens:
        matches_in_slug = sum(1 for tok in name_tokens if tok in slug)
        if matches_in_slug >= max(1, len(name_tokens) - 1):
            # All but at most one token found in slug → strong signal
            return True

    # No token overlap between domain stem and company name.
    # Before rejecting, check if the name might just be a brand with a creative domain.
    # We allow it only when the name is SHORT (≤ 2 non-stop tokens) — these are likely
    # brand names like "Cred" (dreamplug.io) or "Meesho" (meesho.com ✓ overlaps).
    # For longer names with NO overlap, we treat it as a likely mismatch.
    if len(name_tokens) >= 3:
        # Long name with zero domain overlap — high confidence mismatch
        # e.g. "QULEISS Technologies" (after stop removal → {"quleiss"}) vs "refrens"
        # Wait — name_tokens after stop removal for "QULEISS Technologies" = {"quleiss"}
        # stem_tokens for "refrens" = {"refrens"} — no overlap → reject
        return False

    # Short brand names (1–2 significant tokens) with no domain overlap:
    # allow, because creative domain names are common for short brand names.
    return True


def _has_industry_relevance(text: str, industry_key: str, fuzzy: bool = False) -> bool:
    """Return True if scraped text mentions any keyword for the given industry.

    When `fuzzy=True` and no keyword list is found, falls back to checking
    whether the industry_key itself (or its individual tokens) appear in the text.
    This ensures requests for categories not in _INDUSTRY_KEYWORDS still match
    companies whose name/description clearly contains the requested term.

    IMPORTANT: If no keyword list exists for the industry_key and fuzzy=False,
    the company is REJECTED (returns False). Unknown categories must not silently
    pass all checks. Use fuzzy=True in the expansion/fallback path only.
    """
    if not industry_key:
        return False  # no industry specified → cannot validate → reject
    keywords = _INDUSTRY_KEYWORDS.get(industry_key, [])
    tl = text.lower()
    if keywords:
        if any(kw in tl for kw in keywords):
            return True
        # Fuzzy: also check if the industry key token appears directly in text
        if fuzzy and industry_key.lower() in tl:
            return True
        return False
    # No keyword list defined for this industry_key
    if fuzzy:
        # Accept if the raw industry term or any of its words appear in the text
        if industry_key.lower() in tl:
            return True
        for token in industry_key.lower().split():
            if len(token) >= 4 and token in tl:
                return True
        return False
    # Industry key has no keyword definition and fuzzy=False — reject rather than silently pass.
    return False


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


def _detect_industry(text: str) -> str:
    """
    Detect the most likely industry of a company from its text content.

    Scans the text against every entry in _INDUSTRY_KEYWORDS and returns
    the industry key with the most keyword matches. Returns "unknown" if
    no matches are found.

    This is used ONLY for logging the [CATEGORY] detected_industry field —
    it is NOT used for accept/reject decisions (those are done by
    _has_industry_relevance with the REQUESTED category).
    """
    if not text:
        return "unknown"
    tl = text.lower()
    best_key   = "unknown"
    best_count = 0
    for key, keywords in _INDUSTRY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in tl)
        if count > best_count:
            best_count = count
            best_key   = key
    return best_key if best_count > 0 else "unknown"


def validate_candidate(
    company: dict,
    query: str,
) -> tuple[bool, str]:
    """
    Post-extraction validation gate.  Called inside _process_candidate().

    Returns (True, "") if the company passes all checks.
    Returns (False, reason) if any check fails — the candidate is dropped.

    Checks (in order):
      1. company_name is not a generic page title / aggregator title
      2. domain is present
      3. domain ↔ name coherence
      4. industry relevance — category must match (strict, uses fuzzy matching
         so partial/indirect evidence is accepted)
      NOTE: Location is NOT a rejection criterion. Any Indian city is valid.
    """
    name        = (company.get("company_name") or "").strip()
    domain      = (company.get("domain") or "").strip()
    md          = company.get("_merged_markdown") or ""
    description = (company.get("description") or "").strip()

    # 1. Real business name
    if _is_generic_company_name(name):
        _log("CATEGORY", f"{name!r} | REJECTED — generic/page-title name")
        return False, f"generic/page-title name {name!r}"

    # 2. Must have a domain
    if not domain:
        return False, "no domain — cannot verify official website"

    # 3. Domain ↔ name coherence
    ce_enriched = company.get("_ce_enriched", False)
    if not _domain_matches_company(domain, name, ce_verified=ce_enriched):
        return False, f"name {name!r} does not match domain {domain!r}"

    # 4. Industry relevance
    industry_key  = _normalise_industry_key(query)
    industry_text = " ".join((md, description)).lower()

    ce_industry_field = ""
    if company.get("_ce_enriched"):
        ce_industry_field = (company.get("industry") or description).lower()

    # 4.b. Hard disqualifiers for strict categories
    disqualifiers = _CE_CATEGORY_DISQUALIFIERS.get(industry_key, [])
    if disqualifiers:
        if company.get("_ce_enriched") and ce_industry_field:
            for dq in disqualifiers:
                if dq in ce_industry_field:
                    detected = _detect_industry(industry_text)
                    _log("CATEGORY", (
                        f"{name} | requested={industry_key!r} | "
                        f"detected={detected!r} | ce_industry={ce_industry_field[:60]!r} | "
                        f"REJECTED — CE industry contains disqualifier {dq!r}"
                    ))
                    return False, (
                        f"CE industry field {ce_industry_field[:60]!r} contains "
                        f"disqualifier {dq!r} for category {industry_key!r}"
                    )
        for dq in disqualifiers:
            if dq in industry_text:
                detected = _detect_industry(industry_text)
                _log("CATEGORY", (
                    f"{name} | requested={industry_key!r} | "
                    f"detected={detected!r} | "
                    f"REJECTED — content contains disqualifier {dq!r}"
                ))
                return False, (
                    f"company content contains disqualifier {dq!r} for category {industry_key!r}"
                )

    # 4.c. Pharma-specific disqualifiers
    if industry_key == "pharma":
        _PHARMA_DISQ = (
            "hotel", "resort", "spa", "dentist", "dentistry",
            "lasik", "eye surgery", "eye clinic", "vision correction",
        )
        check_text = ce_industry_field if company.get("_ce_enriched") else industry_text
        for term in _PHARMA_DISQ:
            if term in check_text:
                detected = _detect_industry(industry_text)
                _log("CATEGORY", (
                    f"{name} | requested={industry_key!r} | "
                    f"detected={detected!r} | REJECTED — pharma disqualifier {term!r}"
                ))
                return False, f"pharma candidate contains irrelevant term {term!r}"

    # 4.d. Industry keyword check (fuzzy)
    if not _has_industry_relevance(industry_text, industry_key):
        detected = _detect_industry(industry_text)
        _log("CATEGORY", (
            f"{name} | requested={industry_key!r} | "
            f"detected={detected!r} | "
            f"REJECTED — no {industry_key!r} keywords in content"
        ))
        return False, f"no {industry_key!r} keywords in scraped content or description"

    detected = _detect_industry(industry_text)
    _log("CATEGORY", (
        f"{name} | requested={industry_key!r} | "
        f"detected={detected!r} | ACCEPTED"
    ))

    # 4.e. Ecommerce service-provider rejection
    if industry_key == "ecommerce":
        _ECOMMERCE_DISQ = [
            "web development", "website development", "web design",
            "e-commerce development", "ecommerce development",
            "digital marketing", "seo agency", "it services company",
            "software development company", "last mile delivery",
            "logistics company", "fulfillment company",
        ]
        for dq in _ECOMMERCE_DISQ:
            if dq in industry_text:
                _log("CATEGORY", (
                    f"{name} | requested={industry_key!r} | "
                    f"REJECTED — ecommerce service provider: {dq!r}"
                ))
                return False, f"ecommerce candidate is a service provider: {dq!r}"
        if company.get("_ce_enriched") and ce_industry_field:
            _NON_EC = [
                "logistics", "delivery", "fulfillment", "warehousing",
                "digital marketing", "web development", "software development",
                "it services", "transportation", "supply chain",
            ]
            for non_ec in _NON_EC:
                if non_ec in ce_industry_field:
                    _log("CATEGORY", (
                        f"{name} | requested={industry_key!r} | "
                        f"REJECTED — CE industry={ce_industry_field[:60]!r} → {non_ec!r}"
                    ))
                    return False, f"ecommerce rejected — CE industry {non_ec!r}"

    # 4.f. Manufacturing disqualifiers
    if industry_key == "manufacturing":
        for term in (
            "hotel", "resort", "spa", "restaurant", "cafe",
            "salon", "dentist", "hospital", "school", "college",
            "university", "media", "magazine", "news",
            "event management",
        ):
            if term in industry_text:
                _log("CATEGORY", (
                    f"{name} | requested={industry_key!r} | "
                    f"REJECTED — manufacturing disqualifier {term!r}"
                ))
                return False, f"manufacturing candidate contains irrelevant term {term!r}"

    # NOTE: No location/city/Pune filter — India-wide search, any city is valid.
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

def _normalize_email(addr: str) -> str:
    """
    Strip mailto: prefix and markdown link wrappers from an email string.
    e.g. "mailto:info@example.com"                     -> "info@example.com"
         "[info@example.com](mailto:info@example.com)" -> "info@example.com"
    """
    addr = addr.strip()
    m = re.match(r'^\[.*?\]\(mailto:([^)]+)\)$', addr)
    if m:
        return m.group(1).strip().lower()
    m = re.match(r'^\[([^\]]+)\]\([^)]*\)$', addr)
    if m:
        candidate = m.group(1).strip().lower()
        if '@' in candidate:
            return candidate
    if addr.lower().startswith('mailto:'):
        return addr[7:].strip().lower()
    return addr.lower()


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
    Build India-wide Serper queries for company discovery.

    Strategy: always search India-wide. If a city was specified in the query,
    include it as an OPTIONAL keyword in some queries to bias toward that city,
    but do NOT make it a hard filter — valid companies anywhere in India are
    accepted.

    No Serper operator syntax (-site:, site:, inurl:) — filtered in Python.
    """
    industry, city = _parse_query(query)
    ind_norm = industry.lower().strip()

    _SYNONYMS: dict[str, list[str]] = {
        "manufacturing":  ["industrial manufacturing", "engineering manufacturing",
                           "factory manufacturers", "manufacturing firms"],
        "it":             ["software", "technology", "software development", "IT services"],
        "real estate":    ["property developers", "builders", "realty", "housing developers"],
        "fintech":        ["financial technology", "payments company", "fintech startup"],
        "healthcare":     ["hospital", "medical services", "health services", "clinic"],
        "pharma":         ["pharmaceutical", "pharma manufacturing", "drug manufacturer",
                           "medicine company"],
        "education":      ["edtech", "training institute", "academy", "e-learning"],
        "ecommerce":      ["online store", "e-commerce", "online retail", "D2C brand"],
        "construction":   ["builder", "contractor", "infrastructure", "civil contractor"],
        "logistics":      ["transport", "freight", "courier", "supply chain"],
        "hospitality":    ["hotel", "resort", "accommodation"],
        "retail":         ["retail store", "retail chain", "FMCG", "consumer goods"],
        "finance":        ["financial services", "investment", "NBFC", "banking"],
        "biotech":        ["biotechnology", "life sciences", "biopharma"],
        "chemicals":      ["chemical manufacturer", "specialty chemicals", "agrochemicals"],
        "automotive":     ["automobile", "auto components", "vehicle manufacturer"],
        "textile":        ["garment manufacturer", "apparel company", "fabric manufacturer"],
        "food":           ["food processing", "food manufacturing", "food and beverage"],
        "energy":         ["solar energy", "renewable energy", "power generation"],
        "agriculture":    ["agribusiness", "farming company", "agri input", "horticulture"],
        "media":          ["media company", "entertainment", "digital media", "publishing"],
        "telecom":        ["telecommunications", "internet service provider", "broadband"],
        "saas":           ["SaaS company", "cloud software", "software platform"],
    }
    synonyms = _SYNONYMS.get(ind_norm, [industry])

    # Always India-wide. City (if given) is an optional signal in first few queries.
    queries = [
        f"{industry} companies India",
        f"{industry} companies in India",
        f"Indian {industry} companies",
        f"{synonyms[0]} companies India",
        f"{synonyms[1] if len(synonyms) > 1 else industry} companies India",
        f"{industry} companies India official website",
        f"top {industry} companies India",
        f"{synonyms[-1] if synonyms else industry} firms India",
    ]
    # If a city was specified, prepend 2 city-biased queries (still India-wide fallback)
    if city:
        queries = [
            f"{industry} companies in {city}",
            f"{industry} companies {city} India",
        ] + queries

    return queries


async def _serper_search(
    client: httpx.AsyncClient,
    q: str,
    num: int = 10,
    page: int = 1,
) -> list[dict]:
    """Run a single Serper search. Returns a list of result dicts.

    Valid Serper /search parameters: q (str), num (int 1–100), gl (str), hl (str),
    page (int), autocorrect (bool), tbs (str).  Any unknown key causes HTTP 400.

    Returns an empty list tagged with {"_serper_400": True} as the first element
    when the query was rejected with HTTP 400, so callers can detect this case
    and skip pagination for that query.
    """
    if not SERPER_API_KEY:
        _log("DISCOVERY", "SERPER_API_KEY not set — skipping search")
        return []
    if not q or not q.strip():
        _log("DISCOVERY", "Empty query — skipping Serper call")
        return []

    safe_num = max(1, min(num, 100))

    _stats.serper_calls += 1
    try:
        payload = {"q": q.strip(), "num": safe_num}
        if page and page > 1:
            payload["page"] = page
        resp = await client.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=_T_SERPER,
        )
        if resp.status_code == 400:
            _log("DISCOVERY", f"Serper 400 for {q!r} — {resp.text[:200]}")
            return [{"_serper_400": True}]   # sentinel so caller skips pagination
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        _log("DISCOVERY", f"Serper HTTP {exc.response.status_code} for {q!r}: {exc.response.text[:200]}")
        return []
    except Exception as exc:
        _log("DISCOVERY", f"Serper error for {q!r}: {exc}")
        return []

    results = []

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


def _build_companyenrich_queries(query: str) -> list[str]:
    """
    Build category-specific search queries for CompanyEnrich /companies/search.

    Each query is tightly bound to BOTH the requested industry/category AND
    the requested city/location so that changing the category produces entirely
    different, relevant results.

    CompanyEnrich queries are short plain-text phrases — no operators.
    """
    industry, city = _parse_query(query)
    ind_norm = industry.lower().strip()

    # Category → list of alternative phrasings, ordered from most to least specific.
    # Each entry will be combined with the city to form a query.
    _CATEGORY_PHRASES: dict[str, list[str]] = {
        "manufacturing":  [
            "manufacturing company",
            "engineering manufacturing",
            "industrial manufacturer",
            "factory manufacturer",
            "precision engineering",
            "fabrication company",
            "auto components manufacturer",
            "metal fabrication",
            "industrial components",
            "machinery manufacturer",
            "precision components",
            "engineering works",
        ],
        "it":             [
            "IT company",
            "software company",
            "technology company",
            "software development",
            "IT services",
        ],
        "real estate":    [
            "real estate company",
            "property developer",
            "builder developer",
            "realty company",
            "housing developer",
        ],
        "fintech":        [
            "fintech company",
            "financial technology",
            "payments company",
            "lending fintech",
            "digital payments",
        ],
        "healthcare":     [
            "healthcare company",
            "hospital",
            "medical services",
            "health clinic",
            "diagnostics center",
        ],
        "pharma":         [
            "pharmaceutical company",
            "pharma company",
            "drug manufacturer",
            "medicine company",
            "biotech pharma",
            "pharmaceutical manufacturer",
            "generic drug company",
            "bulk drug manufacturer",
            "API manufacturer",
            "life sciences company",
            "contract pharmaceutical",
            "pharma manufacturing",
        ],
        "biotech":        [
            "biotech company",
            "biotechnology",
            "life sciences company",
            "biopharma",
            "genomics company",
        ],
        "education":      [
            "education company",
            "edtech company",
            "training institute",
            "online learning",
            "educational academy",
        ],
        "ecommerce":      [
            "ecommerce company",
            "online retail",
            "e-commerce startup",
            "online marketplace",
            "D2C brand",
            "online store",
            "direct to consumer brand",
        ],
        "saas":           [
            "SaaS company",
            "software as a service",
            "cloud software company",
            "SaaS product",
            "B2B SaaS",
            "subscription software",
        ],
        "construction":   [
            "construction company",
            "civil contractor",
            "infrastructure company",
            "builder contractor",
        ],
        "logistics":      [
            "logistics company",
            "transport company",
            "freight company",
            "supply chain",
            "courier services",
        ],
        "hospitality":    [
            "hotel company",
            "hospitality company",
            "resort",
            "accommodation services",
        ],
        "finance":        [
            "financial services company",
            "investment company",
            "NBFC",
            "wealth management",
        ],
        "retail":         [
            "retail company",
            "retail chain",
            "FMCG company",
            "consumer goods company",
            "supermarket chain",
            "retail store",
            "departmental store",
            "retail trade company",
        ],
        "agriculture":    [
            "agriculture company",
            "agribusiness company",
            "farming company",
            "agricultural company",
            "agri input company",
            "fertilizer company",
            "seeds company",
            "dairy company",
            "horticulture company",
        ],
        "food":           [
            "food company",
            "food processing company",
            "food manufacturing company",
            "packaged food company",
            "food and beverage company",
        ],
        "textile":        [
            "textile company",
            "garment manufacturer",
            "apparel company",
            "fabric manufacturer",
            "clothing company",
        ],
        "automotive":     [
            "automotive company",
            "automobile manufacturer",
            "auto components company",
            "vehicle manufacturer",
        ],
        "chemicals":      [
            "chemical company",
            "specialty chemicals company",
            "agrochemicals company",
            "chemical manufacturer",
        ],
        "energy":         [
            "energy company",
            "solar energy company",
            "renewable energy company",
            "power company",
        ],
        "media":          [
            "media company",
            "entertainment company",
            "digital media company",
            "publishing company",
        ],
        "telecom":        [
            "telecom company",
            "telecommunications company",
            "internet service provider",
            "broadband company",
        ],
    }

    phrases = _CATEGORY_PHRASES.get(ind_norm)
    if not phrases:
        # Fallback for unknown categories: use the raw industry term
        phrases = [
            f"{industry} company",
            f"{industry} firm",
            f"{industry} services",
        ]

    if city:
        return [f"{phrase} {city}" for phrase in phrases]
    else:
        return [f"{phrase} India" for phrase in phrases]


# Category keyword sets — used to filter CompanyEnrich results for relevance.
# Rules:
# - Check the CE structured `industry` field FIRST (authoritative).
# - Only fall through to description if industry field is absent.
# - Keywords must be SPECIFIC to the category — generic words like "retail",
#   "commerce", "marketplace", "technology", "services" are NOT sufficient alone.
# - A company that PROVIDES services to a category ≠ a company IN that category.
_CE_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "manufacturing":  [
        # Prefix stems — match "manufacturing/manufacturer/manufacturers/fabrication/fabricator"
        "manufactur", "fabricat",
        # Bare CE industry field values that CE commonly returns for mfg companies
        "industrial manufacturing", "engineering manufacturing",
        "precision manufacturing", "precision engineering",
        "metal fabrication", "auto components", "auto parts",
        "automotive components", "automotive manufacturing",
        "industrial automation", "machine tools", "machine shop",
        "plastic manufacturing", "rubber manufacturing",
        "chemical manufacturing", "process manufacturing",
        "precision components", "industrial components",
        "engineering works", "engineering firm",
        "machiner", "tooling", "casting", "forging",
        "foundry", "production facility",
        "industrial manufacturer", "components manufacturer",
        "parts manufacturer",
    ],
    "it":             [
        # Use full phrases/words — NOT bare "it " or " it" which match anything
        "software development", "software company", "software products",
        "software solutions", "it services", "it company",
        "information technology", "saas", "cloud software",
        "technology platform", "software platform",
        "devops", "cybersecurity", "erp", "data analytics",
        "web development company", "app development company",
    ],
    "real estate":    [
        "real estate", "realty", "property developer", "builder developer",
        "residential developer", "commercial property", "housing developer",
        "land development", "apartment developer", "villa developer",
    ],
    "fintech":        [
        "fintech", "financial technology", "payments company",
        "lending platform", "neobank", "insurtech", "wealthtech",
        "digital banking", "upi payments", "digital wallet",
        "loan platform", "investment platform", "nbfc",
        "remittance", "crypto", "blockchain finance",
    ],
    "healthcare":     [
        "healthcare", "hospital", "medical center", "health clinic",
        "diagnostics", "telemedicine", "health tech", "medical services",
        "pharmaceutical company", "dental clinic",
    ],
    "pharma":         [
        # Bare CE industry field values — CE commonly returns just "pharma"/"Pharma"
        # or "Pharmaceutical" for Indian pharma companies
        "pharma", "pharmaceutical", "pharmaceuticals",
        "biopharma", "biopharmaceutical",
        "life science", "life sciences",
        # Drug/medicine compound terms (not bare "drug" or "medicine" alone — too broad)
        "drug manufacturer", "drug manufacturing",
        "medicine manufacturer", "medicine manufacturing",
        "generic drug", "bulk drug",
        "api manufacturer", "api manufacturing",
        "active pharmaceutical",
        # Process/product CE field values
        "pharma company", "pharma manufacturing",
        "pharmaceutical company", "pharmaceutical manufacturing",
        "pharmaceutical manufacturer",
        "clinical research", "contract research",
        "formulation", "dosage form",
        "tablet manufacturer", "capsule manufacturer",
        "injectable manufacturer",
        "specialty pharma", "nutraceutical",
        "ayurvedic", "herbal medicine",
        "contract manufacturing organisation", "cmo", "cdmo",
        "life sciences company",
    ],
    "biotech":        [
        "biotech", "biotechnology", "life sciences", "biopharma",
        "genomics", "bioscience", "cell therapy", "gene therapy",
        "biomanufacturing",
    ],
    "education":      [
        "education company", "edtech", "e-learning platform",
        "online learning", "training institute", "educational academy",
        "school", "college", "university",
    ],
    # ecommerce: STRICT — must operate an online store/marketplace/D2C business
    # A web dev agency or logistics company is NOT ecommerce.
    "ecommerce":      [
        "ecommerce", "e-commerce company", "e-commerce business",
        "online store", "online storefront", "online retail",
        "online shopping", "online marketplace", "b2c marketplace",
        "retail platform", "d2c brand", "d2c company",
        "direct-to-consumer", "direct to consumer",
        "consumer brand", "sells products online",
        "online sales", "digital storefront",
    ],
    # saas: must be a SaaS product company, not just any software company
    "saas":           [
        "saas", "software as a service", "cloud software",
        "cloud platform", "subscription software",
        "software platform", "cloud application",
        "cloud-based software", "b2b saas", "enterprise saas",
        "saas product", "saas company",
    ],
    # construction: include single-word bare terms because CE's industry field
    # commonly returns short values like "construction", "contractor", "builder".
    # Multi-word phrases are kept for description-level matching.
    # Also include CE-style industry values: "civil engineering", "infrastructure",
    # "engineering services", "real estate & construction", etc.
    "construction":   [
        # CE structured industry field values (exact/substring matches)
        "construction", "constructor", "contractor",
        "civil engineering", "civil engineer",
        "infrastructure", "infrastructur",
        "engineering & construction", "construction & engineering",
        "construction & infrastructure", "real estate & construction",
        "real estate and construction",
        # Multi-word phrase matches for industry / description text
        "civil contractor", "construction company", "civil construction",
        "infrastructure construction", "building construction",
        "building contractor", "builder contractor",
        "general contractor", "construction contractor",
        "construction and infrastructure", "construction services",
        "engineering services", "building services",
        "building materials", "construction materials",
        # Single high-signal tokens for description-level matching
        "builder", "developer",
        # Common CE industry groupings that include construction
        "real estate developer", "property developer",
        "construction firm", "construction group",
    ],
    "logistics":      [
        "logistics company", "transport company", "freight company",
        "supply chain", "courier services", "warehousing",
        "distribution company",
    ],
    "hospitality":    [
        "hotel chain", "hospitality company", "resort company",
        "accommodation services", "hotel management",
    ],
    "finance":        [
        "financial services company", "investment company",
        "nbfc", "wealth management firm", "insurance company",
        "banking services",
    ],
    # ── New categories ────────────────────────────────────────────────────────
    "retail":         [
        "retail", "retailer", "retail chain", "retail store",
        "fmcg", "consumer goods", "supermarket", "hypermarket",
        "departmental store", "grocery chain", "convenience store",
        "b2c retail", "physical retail", "merchandise",
        "distribution and retail", "wholesale and retail",
        "retail trade", "retail outlet",
    ],
    "agriculture":    [
        "agriculture", "agricultural", "agri", "agro",
        "farming", "agribusiness", "agri-business",
        "horticulture", "crop sciences", "seeds company",
        "fertilizer company", "pesticide company",
        "irrigation company", "dairy company", "poultry company",
        "agri input", "agri output", "agricultural produce",
        "food processing", "milling", "organic farming",
    ],
    "food":           [
        "food company", "food processing", "food manufacturing",
        "restaurant chain", "food and beverage", "packaged food",
        "bakery company", "beverage company", "catering company",
        "fmcg food", "consumer food brand",
    ],
    "textile":        [
        "textile", "garment manufacturer", "apparel company",
        "clothing manufacturer", "fabric manufacturer",
        "textile manufacturing", "garment manufacturing",
        "yarn manufacturer", "weaving company",
    ],
    "automotive":     [
        "automotive", "automobile", "auto manufacturer",
        "vehicle manufacturer", "auto components", "auto parts",
        "automotive manufacturing", "car manufacturer",
        "two wheeler manufacturer",
    ],
    "chemicals":      [
        "chemicals", "chemical company", "chemical manufacturer",
        "specialty chemicals", "agrochemicals", "petrochemicals",
        "fine chemicals", "industrial chemicals",
        "chemical manufacturing",
    ],
    "energy":         [
        "energy company", "solar energy", "renewable energy",
        "solar power", "wind energy", "power generation",
        "oil and gas", "energy solutions",
    ],
    "media":          [
        "media company", "entertainment company", "publishing house",
        "news company", "digital media", "broadcast company",
        "media group", "content company",
    ],
    "telecom":        [
        "telecom company", "telecommunications", "internet service provider",
        "broadband company", "mobile network", "network provider",
        "isp", "telecom services",
    ],
}

# Terms that DISQUALIFY a company from a category even if keywords match.
# Key = category, Value = list of disqualifying phrases.
# If ANY disqualifier appears in the CE structured industry field, the result is rejected.
_CE_CATEGORY_DISQUALIFIERS: dict[str, list[str]] = {
    "ecommerce": [
        # Companies that BUILD e-commerce solutions are NOT e-commerce companies
        "web development", "website development", "web design",
        "e-commerce development", "ecommerce development",
        "digital marketing", "seo", "search engine optimization",
        "software development company", "it services",
        "logistics", "last mile", "delivery company",
        "supply chain", "warehousing", "fulfillment",
        "consulting", "agency",
    ],
    "manufacturing": [
        # Only truly unrelated industries — NOT "consulting" or "agency" because
        # many legit manufacturers offer engineering consulting or trade via agents.
        "marketing agency", "real estate developer", "hotel",
        "education company", "school", "restaurant", "media company",
        "software company", "information technology", "fintech",
        "insurance", "banking",
    ],
    "pharma": [
        # Non-pharma industries that might incidentally mention drug/medicine
        "hotel", "spa", "wellness resort", "beauty salon",
        "information technology", "software", "fintech",
        "real estate", "logistics", "food delivery",
        "marketing agency", "media", "news",
    ],
    "saas": [
        "it services company", "outsourcing", "consulting",
        "web development", "digital marketing",
    ],
    # ── STRICT disqualifiers for retail — reject anything NOT in retail trade ─
    # Hotels, real estate, agriculture, tourism, detective agencies, news, and
    # other non-retail businesses must be HARD REJECTED for retail queries.
    "retail": [
        # Hospitality / tourism
        "hotel", "resort", "accommodation", "hospitality", "motel", "inn",
        "lodge", "tourism", "travel agency", "tour operator",
        # Real estate
        "real estate", "property developer", "builder", "realty", "housing",
        # Agriculture
        "agriculture", "agricultural", "farming", "agribusiness", "horticulture",
        "dairy farm", "poultry farm",
        # Detective / security
        "detective", "investigation", "private investigator", "security agency",
        "detective agency",
        # News / media
        "news", "newspaper", "media company", "publishing", "broadcast",
        "news agency", "television", "radio",
        # IT / software (not retail)
        "software development", "information technology", "it services",
        "saas", "cloud software",
        # Education
        "school", "college", "university", "edtech",
        # Healthcare
        "hospital", "clinic", "healthcare", "medical services",
        # Finance
        "nbfc", "insurance company", "investment company",
        "financial technology", "fintech", "banking",
    ],
    # ── STRICT disqualifiers for agriculture — reject anything NOT in agri ────
    # Hotels, real estate, tourism, detectives, news, etc. must be HARD REJECTED.
    "agriculture": [
        # Hospitality / tourism
        "hotel", "resort", "accommodation", "hospitality", "motel", "inn",
        "lodge", "tourism", "travel agency", "tour operator",
        # Real estate
        "real estate", "property developer", "builder", "realty", "housing",
        # Retail (non-agri retail)
        "supermarket", "hypermarket", "departmental store",
        "convenience store", "retail chain", "retail trade",
        # Detective / security
        "detective", "investigation", "private investigator", "security agency",
        # News / media
        "news", "newspaper", "media company", "publishing", "broadcast",
        "news agency", "television", "radio",
        # IT / software
        "software development", "information technology", "it services",
        "saas", "cloud software", "fintech",
        # Education
        "school", "college", "university", "edtech",
        # Healthcare
        "hospital", "clinic", "healthcare",
        # Finance
        "nbfc", "insurance company", "investment company",
        "financial technology", "banking",
        # Manufacturing (non-agri)
        "auto components", "precision engineering", "metal fabrication",
        "automotive", "automobile",
    ],
}


# Generic/junk keywords — any result whose name consists ONLY of these terms
# combined with a city is rejected (e.g. "Pune Jobs", "Pune Beauties", "Pune Pulse").
_CE_JUNK_NAME_PATTERNS = re.compile(
    r'(?i)^(?:pune|mumbai|delhi|bangalore|bengaluru|india|maharashtra|'
    r'hyderabad|chennai|kolkata|jaipur|ahmedabad|surat|noida|gurgaon|gurugram)\s*'
    r'(?:jobs?|careers?|pulse|news|media|beauties?|beauty|fashion|lifestyle|'
    r'events?|classifieds?|deals?|offers?|listings?|directory|yellow\s*pages?|'
    r'pages?|times|herald|mirror|post|today|daily|weekly|monthly|buzz|'
    r'click|connect|link|hub|network|portal|online|web|digital|dot|'
    r'info|guide|help|support|services?|solutions?|mart|bazaar|shop|'
    r'store|market|mall|plaza|point|place|zone|city|town|local|'
    r'matrimon|matrimony|astro|vastu|puja|temple|spiritual|'
    r'cricket|sport|sports?|fitness|gym|yoga|'
    r'rental|rentals?|hostel|pg|accommodation|hotel|resort)?$'
    r'|^(?:jobs?|careers?|naukri|recruitment|hiring)\s+(?:in\s+)?(?:pune|mumbai|india|delhi).*$'
    r'|^(?:top|best|leading|list\s+of|directory\s+of)\s+.*(?:companies|firms|agencies|services).*$',
)


def _is_category_relevant(result: dict, category_key: str) -> bool:
    """
    Return True if a CompanyEnrich search result is relevant to the requested category.

    Strategy (priority order):
      1. Use the structured CE `industry` field as the authoritative signal.
         If the industry field clearly maps to the requested category → accept.
         If the industry field clearly maps to a DIFFERENT category → reject.
      2. Only if the industry field is absent/vague, check description.
      3. Apply category-specific disqualifiers (e.g. "web development agency"
         should never qualify as an e-commerce company).

    Rejects junk results like "Pune Jobs", "Pune Beauties", etc.
    """
    name        = (result.get("name") or result.get("company_name") or "").strip()
    ce_industry = (result.get("industry") or "").strip().lower()
    description = (result.get("description") or result.get("seo_description") or "").strip().lower()

    # Reject outright if the name matches junk patterns
    if _CE_JUNK_NAME_PATTERNS.match(name):
        return False

    # Reject if the name is a known generic phrase
    if _is_generic_company_name(name):
        return False

    keywords     = _CE_CATEGORY_KEYWORDS.get(category_key, [])
    disqualifiers = _CE_CATEGORY_DISQUALIFIERS.get(category_key, [])

    if not keywords:
        # No keyword definition for this category → reject rather than silently pass.
        # Logging so operators know when a new category needs keywords added.
        _log("CE_FILTER", f"No keyword definition for category={category_key!r} — rejecting {name!r}")
        return False  # unknown category — hard reject

    # ── Step 1: Check CE structured industry field (most authoritative) ───────
    if ce_industry:
        # Check disqualifiers against industry field first
        if any(dq in ce_industry for dq in disqualifiers):
            return False  # industry field explicitly contradicts the category

        # Check if industry field matches the category
        if any(kw in ce_industry for kw in keywords):
            return True  # industry field confirms the category

        # Industry field is populated but doesn't match — for strict categories
        # (ecommerce, saas) treat non-matching industry as disqualifying.
        # For manufacturing and pharma: allow if description has strong evidence,
        # because CE sometimes categorises them under adjacent fields
        # (e.g. "Specialty Chemicals" for a pharma company, "Engineering" for a mfg co).
        _STRICT_CATEGORIES = {"ecommerce", "saas"}
        _SEMI_STRICT_CATEGORIES = {"manufacturing", "pharma", "biotech"}
        if category_key in _STRICT_CATEGORIES:
            # Industry field present but wrong → reject outright
            strong_desc = any(kw in description for kw in keywords[:8])
            if not strong_desc:
                return False
        elif category_key in _SEMI_STRICT_CATEGORIES:
            # Allow if description has any matching keyword (more lenient)
            if not any(kw in description for kw in keywords):
                return False

    # ── Step 2: Check description (only for absent/vague industry fields) ─────
    # Apply disqualifiers to description
    if any(dq in description for dq in disqualifiers):
        return False

    # Check description for category keywords
    if any(kw in description for kw in keywords):
        return True

    # Name check as last resort (only non-strict categories)
    _STRICT_CATEGORIES = {"ecommerce", "saas"}
    if category_key not in _STRICT_CATEGORIES:
        name_lower = name.lower()
        if any(kw in name_lower for kw in keywords):
            return True

    return False


def _is_location_relevant_ce(result: dict, city: str) -> bool:
    """
    Return True if a CompanyEnrich result is associated with the requested city.

    STRICT: checks ONLY structured location fields (city, state, address).
    Does NOT check description or company name — a company that "serves Pune"
    or "has clients in Pune" is NOT a Pune company.

    Valid for Pune: Pune, Pimpri, Pimpri-Chinchwad, Hinjewadi, Wakad, Kharadi,
    Magarpatta, Hadapsar, Baner, and other clearly Pune-area sub-locations.
    A Bengaluru-only company MUST be rejected for a Pune query.
    """
    if not city:
        return True

    city_l = city.lower().strip()
    # Build a set of acceptable city/region tokens
    city_tokens = {city_l}
    # Add known sub-areas for Pune
    if city_l == "pune":
        city_tokens |= {
            "pimpri", "chinchwad", "pcmc", "hadapsar", "kharadi", "baner",
            "wakad", "hinjewadi", "viman nagar", "koregaon", "aundh",
            "bavdhan", "magarpatta", "kothrud", "shivajinagar",
            "deccan", "yerawada", "wagholi",
        }

    # Extract ONLY structured location fields — do NOT check description or name
    location    = result.get("location") or {}
    city_obj    = location.get("city")    or {}
    state_obj   = location.get("state")   or {}

    result_city    = (city_obj.get("name", "") if isinstance(city_obj,    dict) else "").lower().strip()
    result_state   = (state_obj.get("name", "") if isinstance(state_obj,   dict) else "").lower().strip()
    result_address = (location.get("address") or "").lower()

    # Build a combined string from ONLY verified location fields
    location_combined = f"{result_city} {result_state} {result_address}"

    matched = any(tok in location_combined for tok in city_tokens)

    # For Pune queries: also accept Maharashtra state when city is unspecified
    # (some CE records only have state, not city)
    if not matched and city_l == "pune":
        if "maharashtra" in result_state:
            # Maharashtra but no specific city — accept tentatively
            # (will be rejected later by validate_candidate if no Pune evidence in content)
            matched = True

    return matched


async def _normalize_company_search_result(result: dict) -> dict:
    """Normalize CompanyEnrich search result to our discovery candidate shape."""
    website = (result.get("website") or "" ).strip().rstrip("/")
    domain = _domain(website) or (result.get("domain") or "").strip().lower()
    title = (result.get("name") or result.get("company_name") or result.get("legalName") or "").strip()
    snippet = (result.get("description") or result.get("industry") or "").strip()
    if not website and domain:
        website = f"https://{domain}"

    return {
        "title":  title,
        "link":   website,
        "domain": domain,
        "snippet": snippet,
        "source": "companyenrich",
        "raw": result,
    }


def _merge_companyenrich_details(company: dict, details: Optional[dict]) -> dict:
    """Merge CompanyEnrich enrichment details into the candidate without overwriting valid data."""
    if not details:
        return company

    updated = dict(company)

    existing_emails = list(updated.get("emails") or [])
    existing_phones = list(updated.get("phones") or [])

    # Preserve an existing company name if present.
    if not updated.get("company_name"):
        updated_name = (details.get("company_name") or details.get("name") or details.get("legalName") or "").strip()
        if updated_name:
            updated["company_name"] = updated_name

    email = details.get("email")
    if email:
        if email not in existing_emails:
            existing_emails.insert(0, email)
        if not updated.get("email"):
            updated["email"] = email

    phone = details.get("company_number") or details.get("phone") or details.get("phone_number")
    if phone:
        if phone not in existing_phones:
            existing_phones.insert(0, phone)
        if not updated.get("company_number"):
            updated["company_number"] = phone

    if existing_emails:
        updated["emails"] = existing_emails[:6]
    if existing_phones:
        updated["phones"] = existing_phones[:5]

    if not updated.get("address") and details.get("address"):
        updated["address"] = details["address"]
    if not updated.get("city") and details.get("city"):
        updated["city"] = details["city"]
    if not updated.get("state") and details.get("state"):
        updated["state"] = details["state"]
    if not updated.get("country") and details.get("country"):
        updated["country"] = details["country"]
    if not updated.get("postal_code") and details.get("postal_code"):
        updated["postal_code"] = details["postal_code"]

    if not updated.get("founder_name"):
        founder = details.get("founder_name") or details.get("founder")
        if founder:
            updated["founder_name"] = founder
    if not updated.get("founder_number") and details.get("founder_number"):
        updated["founder_number"] = details["founder_number"]

    if not updated.get("source_url") and details.get("source_url"):
        updated["source_url"] = details["source_url"]

    # Avoid removing valid values with nulls from CompanyEnrich.
    if updated.get("company_name") and not updated.get("company_name").strip():
        updated["company_name"] = company.get("company_name")

    return updated


async def _companyenrich_search(query: str, want: int, location_scope: str = "india") -> list[dict]:
    """
    PRIMARY discovery via CompanyEnrich /companies/search.

    Strategy:
      1. Build category-specific, India-wide queries.
      2. Run each query sequentially; stop when we have enough candidates.
      3. Filter every result:
           a. category relevance (industry field first, then description)
           b. location relevance: always India-wide (location_scope="india" default)
           c. domain identity pre-check (CE name vs domain stem)
           d. junk name rejection
      4. Return normalized candidate dicts (source="companyenrich").

    This function is ONLY for discovery — full enrichment happens later in
    _process_ce_candidate().
    """
    if not COMPANYENRICH_API_KEY:
        _log("DISCOVERY", "COMPANYENRICH_API_KEY not set — skipping CompanyEnrich search")
        return []

    # Credit-saving: bail early if 402 already seen this run
    from app.services.companyenrich_service import is_credits_exhausted
    if is_credits_exhausted():
        _log("DISCOVERY", "CompanyEnrich credits exhausted (402) — skipping CE search")
        return []

    industry, city = _parse_query(query)
    category_key   = _normalise_industry_key(query)

    # Always search India-wide — no Pune/Maharashtra rewrite needed
    expanded_query = f"{industry} companies in India"
    _log("DISCOVERY", f"India-wide CE search: {expanded_query!r}")

    ce_queries     = _build_companyenrich_queries(expanded_query)
    # Buffer: want * 3 gives more raw candidates to work through filtering.
    target         = want * 3

    _log("CE_DISCOVERY", (
        f"Query={query!r} scope={location_scope!r} category={category_key!r} "
        f"queries={len(ce_queries)} buffer_target={target}"
    ))

    candidates:   list[dict]    = []
    seen_domains: set[str]      = set()
    total_raw                   = 0
    total_junk                  = 0
    total_off_category          = 0
    total_off_location          = 0
    total_identity_fail         = 0
    candidate_index             = 0

    for q in ce_queries:
        if len(candidates) >= target:
            break

        page_size = min(max(20, want * 2), 50)
        _log("CE_DISCOVERY", f"CE search query: {q!r}")

        try:
            results = await _companyenrich.search_companies(q, page=1, page_size=page_size)
        except Exception as exc:
            _log("CE_DISCOVERY", f"CompanyEnrich search error for {q!r}: {exc}")
            continue

        total_raw += len(results)

        for result in results:
            if len(candidates) >= target:
                break

            name   = (result.get("name") or result.get("company_name") or "").strip()
            domain = _companyenrich._normalize_domain(result.get("domain") or result.get("website") or "")
            website= (result.get("website") or (f"https://{domain}" if domain else "")).strip().rstrip("/")

            if not domain or not website:
                continue
            if not _is_official(website):
                total_junk += 1
                continue
            if domain in seen_domains:
                continue

            candidate_index += 1
            _log("CE_DISCOVERY", f"Candidate {candidate_index}: {name!r} ({domain})")

            # ── Category relevance gate (industry field first) ────────────────
            if not _is_category_relevant(result, category_key):
                total_off_category += 1
                _log("CE_FILTER", f"Rejected category: {name!r}")
                detected_ind = (result.get("industry") or result.get("description") or "")[:60]
                _log("CATEGORY", (
                    f"{name} | requested={category_key!r} | "
                    f"detected={detected_ind!r} | REJECTED (CE discovery filter)"
                ))
                continue
            _log("CE_FILTER", f"Accepted category: {name!r}")
            _log("CATEGORY", (
                f"{name} | requested={category_key!r} | "
                f"detected={(result.get('industry') or '')[:60]!r} | ACCEPTED (CE filter)"
            ))

            # ── Location relevance gate: always India-wide ────────────────────
            # No city/Pune filtering — accept any company from India.
            # The CE search query already targets India, so any result is valid.
            _log("CE_FILTER", f"Accepted location (India-wide): {name!r}")

            # ── Identity pre-check: CE name must plausibly belong to CE domain ─
            if not _domain_matches_company(domain, name, ce_verified=False):
                total_identity_fail += 1
                _log("CE_IDENTITY", f"Rejected company/domain mismatch: {name!r} -> {domain}")
                continue

            seen_domains.add(domain)

            snippet = (result.get("description") or result.get("industry") or "").strip()
            candidates.append({
                "title":   name,
                "link":    website,
                "domain":  domain,
                "snippet": snippet,
                "source":  "companyenrich",
                # Carry raw CE result for _process_ce_candidate
                "_ce_raw": result,
            })

    _log("CE_DISCOVERY", (
        f"CompanyEnrich search complete (scope={location_scope!r}): raw={total_raw} accepted={len(candidates)} "
        f"off_category={total_off_category} off_location={total_off_location} "
        f"identity_fail={total_identity_fail} junk={total_junk}"
    ))
    return candidates


async def discover_candidates(
    query: str,
    want: int,
    location_scope: str = "india",
) -> list[dict]:
    """
    Run company discovery using CompanyEnrich as the ONLY discovery source.

    `location_scope` controls geographic strictness:
      "india"       — any India company (default, India-wide)
      "maharashtra" — any Maharashtra city
      "pune"        — Pune/surroundings only

    Serper is NOT used for discovery.
    """
    ce_candidates = await _companyenrich_search(query, want, location_scope=location_scope)

    if not ce_candidates:
        _log("DISCOVERY", f"CE exhausted at scope={location_scope!r} — 0 candidates")
    elif len(ce_candidates) < want:
        _log("DISCOVERY", (
            f"CE scope={location_scope!r} — found {len(ce_candidates)}/{want} candidates"
        ))
    else:
        _log("DISCOVERY", (
            f"CE scope={location_scope!r} — found {len(ce_candidates)} candidates (want={want})"
        ))

    return ce_candidates

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

    Per-field source tracking (requirement 22):
      email_source, phone_source, address_source, founder_source
    are derived from _field_verification to make it clear whether each field
    came from CompanyEnrich or a Serper/Firecrawl fallback.
    """
    emails = c.get("emails", [])
    phones = c.get("phones", [])
    email  = c.get("email") or (emails[0] if emails else None)
    company_number = c.get("company_number") or (phones[0] if phones else None)
    sources = c.get("sources") or c.get("research_sources") or []

    # ── Per-field source extraction ───────────────────────────────────────────
    fv = c.get("_field_verification") or {}

    def _field_source(field_key: str, default_source: str) -> str:
        """Return the source string for a single field from _field_verification."""
        entry = fv.get(field_key) or {}
        if isinstance(entry, dict):
            src = entry.get("source") or entry.get("status") or ""
            if src:
                # Normalise source labels so they're human-readable
                if "companyenrich" in src.lower():
                    return "companyenrich"
                if "serper" in src.lower():
                    return "serper_fallback"
                if "firecrawl" in src.lower():
                    return "firecrawl_fallback"
                return src
        return default_source

    # The overall research_source determines the default per-field source
    research_source = c.get("research_source", "serper_firecrawl")
    _default_src = "companyenrich" if research_source == "companyenrich" else "serper_firecrawl"

    email_source   = _field_source("email",   _default_src) if email           else None
    phone_source   = _field_source("phone",   _default_src) if company_number  else None
    address_source = _field_source("address", _default_src) if c.get("address") else None
    founder_source = _field_source("founder", _default_src) if c.get("founder_name") else None

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
        "founder_number":   c.get("founder_number"),
        "source_url":       c.get("source_url") or c.get("website", ""),
        "sources":          sources,
        # Contact gap status
        "email_status":     c.get("email_status", ""),
        "phone_status":     c.get("phone_status", ""),
        # Metadata
        "description":      c.get("description", ""),
        "confidence":       c.get("confidence", 0.0),   # carry through verify_service score
        "last_verified":    None,
        # Research source trace — preserve actual source (companyenrich vs serper_firecrawl)
        "research_source":  research_source,
        "research_sources": sources,
        # Per-field source tracking (requirement 22)
        # These make it explicit which provider contributed each field.
        # NEVER label CE data as "serper_firecrawl".
        "email_source":     email_source,
        "phone_source":     phone_source,
        "address_source":   address_source,
        "founder_source":   founder_source,
        "company_name_source": research_source,
        # Pipeline internal keys (used by ENRICH + VERIFY, stripped before storage)
        "_scraped_pages":   c.get("_scraped_pages", []),
        "_merged_markdown": c.get("_merged_markdown", ""),
        "pages_visited":    c.get("pages_visited", {"success": [], "failed": []}),
        # CRITICAL: carry field-level verification evidence from verify_service
        # This populates the provider source breakdown in the audit report.
        "_field_verification": c.get("_field_verification", {}),
        "_serper_title":    c.get("_serper_title", ""),
        "_ce_enriched":     c.get("_ce_enriched", False),
        # CE structured industry field (used by validate_candidate for CE company checks)
        "industry":         c.get("industry", ""),
        # Pre-validated lists (VALIDATE stage will re-check)
        "validated_emails": emails,
        "validated_phones": [{"number": p, "type": "unknown"} for p in phones],
        "services":         [],
        "socials":          {},
    }

# ═══════════════════════════════════════════════════════════════════════════════
# Per-company processing + public entry point
# ═══════════════════════════════════════════════════════════════════════════════

async def _process_ce_candidate(
    search_result: dict,
    sem: asyncio.Semaphore,
    query: str = "",
) -> Optional[dict]:
    """
    Process a CompanyEnrich-discovered candidate.

    Strict CE-first pipeline per company:
      1. CE /companies/enrich → name, phone, address, website (authoritative identity)
      2. Identity guard: CE-returned name+domain must be consistent
      3. CE /people/search + /people/email → founder + email
      4. Field-level Serper fallback ONLY for phone/address/email if CE returned nothing
         — founder is NEVER fetched from Serper for CE candidates
      5. validate_candidate()
      6. normalize_company() with correct research_source

    verify_company() Serper calls are skipped for fields already provided by CE.
    """
    url    = search_result["link"]
    name   = search_result.get("title", url)
    domain = search_result.get("domain", "")

    _log("CE_ENRICH", f"Starting exact-company enrichment: {name!r} (domain={domain!r})")

    # ── CE Step 1: company enrichment + people/founder concurrently ───────────
    try:
        enrich_data, (founder_name, founder_email, founder_phone, src, fstatus) = \
            await asyncio.gather(
                _companyenrich.enrich_company_by_domain(domain),
                _companyenrich.find_founder_with_email(name, domain),
            )
    except Exception as exc:
        _log("CE_ENRICH", f"CE enrichment failed for {domain!r}: {exc}")
        enrich_data   = {}
        founder_name  = None
        founder_email = None
        founder_phone = None
        fstatus       = "companyenrich_error"
        src           = ""

    # ── CE Step 2: Identity guard — verify CE-returned name belongs to domain ──
    # After /companies/enrich we have the AUTHORITATIVE CE name for this domain.
    # If CE returned a company name that contradicts the domain, reject the candidate.
    ce_name = (enrich_data.get("name") or enrich_data.get("legalName") or "").strip() if enrich_data else ""
    # Normalize ce_domain_from_enrich the same way as `domain` was normalized at discovery
    # time (via _companyenrich._normalize_domain).  Without this, "www.diwacivilcontractor.com"
    # from the /companies/enrich response would not equal the already-normalized discovery
    # domain "diwacivilcontractor.com", causing a false identity rejection.
    ce_domain_raw = (enrich_data.get("domain") or "").strip() if enrich_data else ""
    ce_domain_from_enrich = _companyenrich._normalize_domain(ce_domain_raw) if ce_domain_raw else ""

    # If CE's enrich returned a domain that is DIFFERENT from the discovery domain, reject.
    if ce_domain_from_enrich and ce_domain_from_enrich != domain:
        _log("CE_IDENTITY", (
            f"Rejected company/domain mismatch: CE enrich returned domain={ce_domain_from_enrich!r} "
            f"but discovery domain was {domain!r} for name={name!r}"
        ))
        return None

    # Check the CE name against the domain using ce_verified=True
    # (the enrich call has confirmed this domain belongs to this company)
    canonical_name = ce_name if (ce_name and not _is_generic_company_name(ce_name)) else name
    if not _domain_matches_company(domain, canonical_name, ce_verified=True):
        _log("CE_IDENTITY", f"Rejected company/domain mismatch: {canonical_name!r} -> {domain}")
        return None

    # Additional check: if the search result name and the CE name are both real brand names
    # but share no tokens and the domain stem matches neither, it's likely a data error.
    if ce_name and not _is_generic_company_name(ce_name):
        # CE-verified: the enrich call confirmed ce_name for this domain
        canonical_name = ce_name
        _log("CE_IDENTITY", f"Verified company/domain consistency: {canonical_name!r} -> {domain}")
    else:
        # No CE name — derive from domain stem as last resort
        canonical_name = domain.split(".")[0].replace("-", " ").title() if domain else name
        if _is_generic_company_name(canonical_name):
            _log("CE_ENRICH", f"Skipped — no usable company name for domain {domain!r}")
            return None

    # Extract enriched fields
    location    = enrich_data.get("location") or {} if enrich_data else {}
    city_obj    = location.get("city")    or {}
    state_obj   = location.get("state")   or {}
    country_obj = location.get("country") or {}

    ce_website  = (enrich_data.get("website") or f"https://{domain}").strip() if enrich_data else f"https://{domain}"
    ce_phone    = (location.get("phone") or "").strip()
    ce_street   = (location.get("address") or "").strip()
    ce_postal   = (location.get("postal_code") or "").strip()
    ce_city     = (city_obj.get("name",    "") if isinstance(city_obj,    dict) else "").strip()
    ce_state    = (state_obj.get("name",   "") if isinstance(state_obj,   dict) else "").strip()
    ce_country  = (country_obj.get("name", "") if isinstance(country_obj, dict) else "").strip()
    ce_industry = (enrich_data.get("industry") or "") if enrich_data else ""
    ce_desc     = (enrich_data.get("description") or enrich_data.get("seo_description") or "") if enrich_data else ""

    addr_parts   = [p for p in [ce_street, ce_city, ce_state, ce_postal, ce_country] if p]
    ce_address   = ", ".join(addr_parts) if addr_parts else ""

    website = ce_website or url

    _log("CE_ENRICH", f"Company fields: phone={bool(ce_phone)} address={bool(ce_address)} for {canonical_name!r}")

    # ── CE Step 3: Founder validation ─────────────────────────────────────────
    # Founder comes ONLY from CE /people/search — never from Serper snippets.
    # Validate using _is_plausible_person_name before accepting.
    from app.services.verify_service import _is_plausible_person_name
    if founder_name:
        if _is_plausible_person_name(founder_name):
            _log("CE_PEOPLE", f"{canonical_name}: founder={founder_name!r} source={src}")
        else:
            _log("CE_FOUNDER", f"Rejected unverified founder: {founder_name!r}")
            founder_name = None
    else:
        _log("CE_FOUNDER", f"No verified founder found for {canonical_name!r}")

    # ── CE Step 4: Email normalization + logging ──────────────────────────────
    # Normalize mailto:/markdown wrappers before any domain check (Req 3)
    if founder_email:
        founder_email = _normalize_email(founder_email)
        # Accept CE email if domain matches OR is a subdomain of company domain.
        # Also accept when the root domain (ignoring TLD) matches — CE sometimes
        # returns an email on a different TLD (.in vs .com) for the same company.
        email_dom = founder_email.split("@")[-1].lower() if "@" in founder_email else ""
        domain_root = domain.split(".")[0] if domain else ""
        email_root  = email_dom.split(".")[0] if email_dom else ""
        domain_ok = (
            email_dom == domain
            or email_dom.endswith("." + domain)
            or (domain_root and email_root and domain_root == email_root)
        )
        if domain_ok:
            _log("CE_EMAIL", f"{canonical_name}: email={founder_email!r} source=companyenrich")
        else:
            # Domain mismatch — keep the email anyway if it looks valid;
            # CE is authoritative and the domain may legitimately differ (Req 4/5)
            _log("CE_EMAIL", f"{canonical_name}: email domain {email_dom!r} differs from {domain!r} — keeping CE email")
    else:
        if fstatus and "400" in str(fstatus):
            _log("CE_EMAIL", f"Person email unavailable: status=400")
        _log("CE_EMAIL", f"Field-level fallback required: email for {canonical_name!r}")

    # Assemble company dict from CE data
    company: dict = {
        "company_name":     canonical_name,
        "website":          website,
        "domain":           domain,
        "emails":           [founder_email] if founder_email else [],
        "phones":           [ce_phone] if ce_phone else [],
        "address":          ce_address,
        "city":             ce_city,
        "state":            ce_state,
        "country":          ce_country or "India",
        "postal_code":      ce_postal,
        "email":            founder_email,
        "company_number":   ce_phone or None,
        "founder_name":     founder_name,
        "founder_number":   founder_phone or None,
        "source_url":       website,
        "sources":          [website],
        "description":      ce_desc,
        "industry":         ce_industry,     # CE structured industry field for validate_candidate()
        "email_status":     "" if founder_email else "not_publicly_found",
        "phone_status":     "" if ce_phone else "not_publicly_found",
        # research_source is CE — preserved through normalize_company()
        "research_source":  "companyenrich",
        "research_sources": [website],
        # Provide enough content for validate_candidate() industry check
        "_merged_markdown": f"{canonical_name} {ce_industry} {ce_desc}",
        "_scraped_pages":   [],
        "pages_visited":    {"success": [website] if website else [], "failed": []},
        "_field_verification": {
            "phone":   {"value": ce_phone,      "verified": bool(ce_phone),      "status": "companyenrich_phone",   "source": "companyenrich.com"} if ce_phone       else {},
            "address": {"value": ce_address,    "verified": bool(ce_address),    "status": "companyenrich_address", "source": "companyenrich.com"} if ce_address     else {},
            "founder": {"value": founder_name,  "verified": bool(founder_name),  "status": fstatus,                 "source": src}                 if founder_name   else {},
            "email":   {"value": founder_email, "verified": bool(founder_email), "status": "companyenrich_email",   "source": "companyenrich.com"} if founder_email  else {},
        },
        "_serper_title": search_result.get("title", ""),
        # Mark that CE has already verified identity — prevents double enrichment
        # from overwriting CE data with lower-confidence values
        "_ce_enriched":  True,
    }

    # ── Field-level Serper fallback: ONLY for phone/address/email — NOT founder ──
    # Founder is explicitly excluded: if CE has no founder, founder_name = None.
    # All Serper gap searches are domain-scoped to prevent cross-company contamination.
    missing_fields = []
    if not company["emails"]:    missing_fields.append("email")
    if not company["phones"]:    missing_fields.append("phone")
    if not company["address"]:   missing_fields.append("address")
    # Deliberately NOT including "founder" — no Serper founder search for CE candidates

    if missing_fields:
        _log("CE_ENRICH", f"{canonical_name}: field-level Serper fallback for {missing_fields}")
        # Use contact_gap_search but with founder already set to prevent it from
        # running the founder Serper query. We set a sentinel to block founder search.
        company_for_gap = dict(company)
        company_for_gap["_skip_founder_gap"] = True
        # Pass the required city so address validation can reject wrong-location results
        _, _req_city = _parse_query(query) if query else ("", "")
        company_for_gap["_required_city"] = _req_city.lower() if _req_city else ""
        company = await _contact_gap_search_no_founder(company_for_gap)

    # ── Firecrawl: SKIP for CE candidates unless name is completely missing ────
    # CE-enriched companies already have authoritative data. Firecrawl is expensive
    # and would create unnecessary cost. Only use it if we have no name at all.
    if _is_generic_company_name(company.get("company_name", "")):
        try:
            scrape = await scrape_company_pages(url, sem)
            if not scrape.get("_is_404"):
                scraped_info = extract_company_info(scrape, search_result)
                if scraped_info.get("company_name") and not _is_generic_company_name(scraped_info["company_name"]):
                    company["company_name"] = scraped_info["company_name"]
                # Extend markdown for industry check
                company["_merged_markdown"] = (
                    company.get("_merged_markdown", "") + "\n" + scrape.get("markdown", "")
                )[:20000]
                company["_scraped_pages"]  = scrape.get("pages", [])
                company["pages_visited"]   = scrape.get("pages_visited", company["pages_visited"])
                _stats.firecrawl_calls += 1
        except Exception as exc:
            _log("CE_ENRICH", f"Firecrawl fallback failed for {url}: {exc}")

    # ── Skip verify_company() Serper calls for CE-verified fields ─────────────
    # verify_company() would run Serper searches for every field, overwriting
    # authoritative CE data with lower-confidence search results.
    # Instead: only apply address quality check (synchronous, no API calls)
    # and name cleanup.
    from app.services.verify_service import verify_address_local, _is_plausible_person_name as _ipp
    if company.get("address"):
        clean_addr, addr_status = verify_address_local(company["address"], domain)
        if clean_addr:
            company["address"] = clean_addr
            company["_field_verification"]["address"]["status"] = addr_status
        else:
            # CE address failed quality check — keep it anyway (CE is authoritative)
            # but log it
            _log("CE_ENRICH", f"{canonical_name}: CE address quality check: {addr_status!r} — keeping CE value")

    # ── Final candidate validation ────────────────────────────────────────────
    if query:
        ok, reason = validate_candidate(company, query)
        if not ok:
            _log("CE_VALIDATE", f"{company.get('company_name','?')!r}: REJECTED — {reason}")
            return None

    # ── Confidence score (simple, no verify_company overhead) ─────────────────
    score = 0.0
    if company.get("email"):          score += 0.30
    if company.get("company_number"): score += 0.25
    if company.get("address"):        score += 0.10
    if company.get("founder_name"):   score += 0.10
    if company.get("domain"):         score += 0.05
    score = round(min(score, 1.0), 2)
    company["confidence"] = score

    # ── Normalize ─────────────────────────────────────────────────────────────
    normalized = normalize_company(company)

    _log("CE_VALIDATE", f"{normalized['company_name']!r}: VALID")
    _log("CE_ENRICH", (
        f"{normalized['company_name']} | domain={normalized['domain']} | "
        f"email={'✓ ' + str(normalized['email']) if normalized['email'] else '✗'} | "
        f"phone={'✓' if normalized['company_number'] else '✗'} | "
        f"address={'✓' if normalized['address'] else '✗'} | "
        f"founder={'✓ ' + str(normalized['founder_name']) if normalized['founder_name'] else '✗'} | "
        f"confidence={score}"
    ))
    return normalized


async def _contact_gap_search_no_founder(company: dict) -> dict:
    """
    Field-level Serper fallback for CE candidates — email, phone, address ONLY.
    Founder search is explicitly excluded: if CE has no founder, it stays null.
    All searches are domain-scoped to prevent cross-company contamination.
    """
    name   = company.get("company_name", "")
    domain = company.get("domain", "")
    emails = set(company.get("emails", []))
    phones = set(company.get("phones", []))
    addr   = company.get("address", "")

    gap_queries: list[tuple[str, str]] = []

    if not emails and domain:
        # Domain-scoped email search only
        gap_queries.append(("email", f'"{name}" email site:{domain}'))
        gap_queries.append(("email_at", f'"{name}" "@{domain}"'))
    if not phones and domain:
        gap_queries.append(("phone", f'site:{domain} phone contact'))
    if not addr and domain:
        gap_queries.append(("address", f'site:{domain} address office'))

    if not gap_queries:
        return company

    _log("CE_ENRICH", f"{name}: Serper field fallback for {[g[0] for g in gap_queries]}")

    client = _get_http_client()
    tasks  = [_gap_serper_snippets(client, q) for _, q in gap_queries]
    texts  = await asyncio.gather(*tasks, return_exceptions=True)

    merged = "\n".join(t for t in texts if isinstance(t, str))
    updated = dict(company)

    # Extract emails — must match company domain
    if not emails and domain:
        for addr_str in _EMAIL_RE.findall(merged):
            al = addr_str.lower()
            if not _is_junk_email(al):
                email_dom = al.split("@")[-1]
                if email_dom == domain or email_dom.endswith("." + domain):
                    emails.add(al)
                    _log("CE_EMAIL", f"{name}: field fallback found email={al!r} source=serper_fallback")
                    break  # take first valid match only

    # Extract phones
    if not phones:
        new_phones = _extract_phones(merged)
        if new_phones:
            phones.update(new_phones[:2])

    # Extract address
    if not updated.get("address"):
        addr_info = _extract_address(merged)
        if addr_info["full"]:
            # Location guard: if the company came from a city-specific query,
            # ensure the Serper-found address actually satisfies that location.
            # This prevents accepting a Bengaluru address for a Pune-query company.
            candidate_city = (addr_info.get("city") or "").lower()
            skip_addr = False
            # Check if any known city in the address conflicts with the required city
            # We check the city field and the full address string
            addr_full_lower = addr_info["full"].lower()
            _DISALLOW_FOR_PUNE = {
                "bangalore", "bengaluru", "karnataka",
                "mumbai", "delhi", "hyderabad", "chennai",
                "kolkata", "noida", "gurugram", "gurgaon",
                "ahmedabad", "surat", "jaipur", "lucknow",
            }
            # No city-based address filtering — accept any Indian address
            skip_addr = False

            if not skip_addr:
                updated.update({
                    "address":     addr_info["full"],
                    "city":        addr_info["city"]    or updated.get("city", ""),
                    "state":       addr_info["state"]   or updated.get("state", ""),
                    "country":     addr_info["country"] or updated.get("country", ""),
                    "postal_code": addr_info["postal_code"] or updated.get("postal_code", ""),
                })
                # Mark source as serper fallback
                fv = dict(updated.get("_field_verification") or {})
                fv["address"] = {
                    "value":    addr_info["full"],
                    "verified": True,
                    "status":   "serper_fallback",
                    "source":   "serper.dev",
                }
                updated["_field_verification"] = fv

    all_emails = list(emails)
    seen_digits: set[str] = set()
    all_phones: list[str] = []
    for p in list(phones):
        d = re.sub(r'\D', '', p)
        if d not in seen_digits:
            seen_digits.add(d)
            all_phones.append(p)

    updated["emails"] = all_emails[:6]
    updated["phones"] = all_phones[:5]
    if all_emails:
        updated["email"]            = all_emails[0]
        updated["email_status"]     = ""
        # Mark source as serper fallback if it came from Serper
        fv = dict(updated.get("_field_verification") or {})
        fv["email"] = {"value": all_emails[0], "verified": True,
                       "status": "serper_fallback", "source": "serper.dev"}
        updated["_field_verification"] = fv
    if all_phones:
        updated["company_number"] = all_phones[0]
        updated["phone_status"]   = ""

    return updated


async def _process_candidate(
    search_result: dict,
    sem: asyncio.Semaphore,
    query: str = "",
) -> Optional[dict]:
    """
    Route a candidate to the correct processing path:
      - CompanyEnrich candidates → _process_ce_candidate()
      - Serper candidates → Firecrawl scrape + extraction path.
    Location is NOT a rejection criterion — India-wide search.
    """
    if search_result.get("source") == "companyenrich":
        return await _process_ce_candidate(search_result, sem, query=query)

    # ── Original Serper/Firecrawl path ────────────────────────────────────────
    url  = search_result["link"]
    name = search_result.get("title", url)
    dom  = search_result.get("domain", "")

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

        # If this candidate originated from CompanyEnrich search, merge enrichment details
        # before verification, but never overwrite valid existing fields with null.
        if search_result.get("source") == "companyenrich":
            details = search_result.get("_companyenrich_details")
            if details:
                company = _merge_companyenrich_details(company, details)

        # CONTEXT VERIFICATION (verify each field is actually associated with this company)
        verify_sem = asyncio.Semaphore(_vs._SEM_SIZE)
        company = await _vs.verify_company(company, verify_sem)

        # CANDIDATE VALIDATION — reject generic names, missing domains, off-industry content
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
    Full company discovery + enrichment pipeline.

    Geographic strategy: always search India-wide directly.
    No Pune → Maharashtra → India fallback — every request is India-wide.
    Category relevance is always strictly enforced.

    Hermes is NEVER called.
    """
    global _stats
    _stats = _Stats()
    t0 = time.monotonic()

    MIN_COMPANIES = 5
    # Result requirement: target ≥ MIN_COMPANIES; every result needs a real email;
    # company_number (phone) is also collected whenever publicly available.
    from app.services.companyenrich_service import reset_credits_flag
    reset_credits_flag()

    _log("DISCOVERY", f"START — query={query!r}  count={num}  min={MIN_COMPANIES}  [CE-PRIMARY India-wide]")

    sem = asyncio.Semaphore(_FIRECRAWL_CONCURRENCY)
    valid_companies: list[dict] = []
    seen_domains:    set[str]   = set()
    ce_accepted = 0
    ce_rejected = 0

    # Single India-wide pass — no geo expansion loop
    still_need  = max(num, MIN_COMPANIES)
    buffer_want = still_need * 4

    _log("DISCOVERY", f"India-wide pass — need={still_need} fetching buffer={buffer_want} candidates")

    candidates = await discover_candidates(query, buffer_want, location_scope="india")

    if not candidates:
        _log("DISCOVERY", "India-wide search returned 0 candidates")
    else:
        _log("DISCOVERY", f"India-wide search returned {len(candidates)} candidates")

        for i, candidate in enumerate(candidates):
            if len(valid_companies) >= max(num, MIN_COMPANIES):
                break

            dom = candidate.get("domain", "").lower()
            if dom and dom in seen_domains:
                continue

            name = candidate.get("title", candidate.get("domain", f"#{i+1}"))
            _log("CE_DISCOVERY", (
                f"have={len(valid_companies)}/{max(num, MIN_COMPANIES)} "
                f"— processing: {name!r}"
            ))

            result = await _process_candidate(
                candidate, sem, query=query
            )

            if isinstance(result, dict) and result.get("company_name"):
                result_domain = result.get("domain", "").lower()
                if result_domain and result_domain in seen_domains:
                    _log("CE_DISCOVERY", f"Skipping duplicate domain after processing: {result_domain}")
                    continue
                valid_companies.append(result)
                if result_domain:
                    seen_domains.add(result_domain)
                ce_accepted += 1
                _log("CE_DISCOVERY", (
                    f"ACCEPTED {len(valid_companies)}: {result['company_name']!r}"
                ))
            else:
                ce_rejected += 1

    # ── Final summary ─────────────────────────────────────────────────────────
    _log("DISCOVERY", (
        f"All passes complete — accepted={ce_accepted} rejected={ce_rejected} "
        f"valid={len(valid_companies)}"
    ))

    # ── Deduplicate by domain (safety net) ────────────────────────────────────
    dedup_seen: set[str] = set()
    unique: list[dict] = []
    for c in valid_companies:
        d = c.get("domain", "").lower()
        if d and d in dedup_seen:
            _stats.duplicates += 1
            continue
        if d:
            dedup_seen.add(d)
        unique.append(c)

    # ── FINAL CATEGORY GATE ───────────────────────────────────────────────────
    # Hard-reject any company whose content does not match the requested category.
    # This is the last line of defence before results are handed to the route.
    industry_key = _normalise_industry_key(query)
    category_validated: list[dict] = []
    for c in unique:
        cname = c.get("company_name", "?")
        check_text = " ".join(filter(None, [
            c.get("_merged_markdown", ""),
            c.get("description", ""),
            c.get("industry", ""),
        ])).lower()
        detected = _detect_industry(check_text)
        if _has_industry_relevance(check_text, industry_key):
            category_validated.append(c)
            _log("CATEGORY", (
                f"{cname} | requested={industry_key!r} | "
                f"detected={detected!r} | FINAL GATE: ACCEPTED"
            ))
        else:
            _log("CATEGORY", (
                f"{cname} | requested={industry_key!r} | "
                f"detected={detected!r} | "
                f"ce_industry={c.get('industry','?')!r} | FINAL GATE: REJECTED"
            ))
    if len(category_validated) < len(unique):
        _log("DISCOVERY", (
            f"Final category gate removed "
            f"{len(unique) - len(category_validated)} category-mismatched companies"
        ))
    unique = category_validated

    elapsed = time.monotonic() - t0

    _log("DISCOVERY", f"CompanyEnrich accepted: {ce_accepted}")
    _log("DISCOVERY", f"CompanyEnrich rejected: {ce_rejected}")
    _log("DISCOVERY", f"Serper fallback fields used: {_stats.serper_calls}")
    _log("DISCOVERY", f"Firecrawl fallback fields used: {_stats.firecrawl_calls}")
    _log("DISCOVERY", f"Final valid companies: {len(unique)}")
    _log("DISCOVERY", (
        f"DONE in {elapsed:.1f}s — "
        f"candidates_total={ce_accepted + ce_rejected} valid={len(unique)} "
        f"email={sum(1 for c in unique if c.get('email'))}/{len(unique)} "
        f"phone={sum(1 for c in unique if c.get('company_number'))}/{len(unique)} "
        f"address={sum(1 for c in unique if c.get('address'))}/{len(unique)} "
        f"founder={sum(1 for c in unique if c.get('founder_name'))}/{len(unique)}"
    ))

    return {
        "query":     query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "companies": unique,
        "total":     len(unique),
        "status":    "success" if unique else "no_candidates",
        "_elapsed":  round(elapsed, 1),
        "_stats":    vars(_stats),
    }
