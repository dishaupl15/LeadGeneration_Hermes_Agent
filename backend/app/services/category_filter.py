"""
app/services/category_filter.py
─────────────────────────────────
Final category validation stage — runs AFTER enrichment, BEFORE MongoDB.

Purpose
───────
Ensures every lead returned to the UI and stored in MongoDB genuinely
belongs to the user-selected category.

How it works
────────────
1.  Build a "text fingerprint" for each company from all available text
    signals: company_name, description, industry field, primary_type
    (Google Maps), scraped content, Serper snippets, CE description, etc.
2.  Check the fingerprint against:
    a. POSITIVE signals — terms that strongly indicate the category.
    b. NEGATIVE signals — terms that rule out the category entirely.
3.  Score: each positive hit adds points; the company passes when the
    score exceeds the configured threshold.
4.  Log every decision with the category, candidate, result, and reason.

Rules
─────
- GENERIC: this module works for EVERY category — no special-case code
  for any single category.  All per-category config is in _CATEGORY_CONFIG.
- NEVER fabricate: we only inspect data that the pipeline already collected.
- A company with NO text at all (name only, no description) is accepted
  conservatively to avoid silently losing valid leads from new areas
  where enrichment APIs returned nothing.  These pass with a
  "name_only_passed" reason — the caller may tighten this if desired.
- Safe to call with missing fields — all lookups are guarded with .get().

Public interface
────────────────
  validate_category(company: dict, category: str) -> CategoryResult
  filter_companies(companies, category, log_prefix="") -> (valid, rejected)
  log_filter_summary(category, location, requested, candidates, valid, rejected)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [CATEGORY FILTER] {msg}", flush=True)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class CategoryResult:
    accepted:    bool
    score:       float
    reason:      str
    signals_hit: list[str] = field(default_factory=list)
    neg_hit:     Optional[str] = None   # first negative signal that fired


# ═══════════════════════════════════════════════════════════════════════════════
# PER-CATEGORY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
#
# Structure per category:
#   "positive" : list of keyword patterns (substrings, case-insensitive)
#                Each hit contributes +1.0 to the score.
#   "strong"   : list of high-confidence patterns; each hit contributes +2.0.
#                Use for terms that ALONE confirm the category.
#   "negative" : list of patterns; ANY hit → immediate REJECT.
#   "threshold": minimum score required to ACCEPT (default 1.0).
#                Set higher for categories where positive terms can appear
#                accidentally (e.g. "construction" appears in many non-construction
#                company descriptions).
#
# Pattern rules:
#   - All patterns are case-insensitive substring matches by default.
#   - Prefix with "^" to anchor to the START of the fingerprint (rare).
#   - Wrap in \b...\b for word-boundary matches (slower, use sparingly).
#
# IMPORTANT: keep patterns short and specific — avoid single-character patterns.
# ═══════════════════════════════════════════════════════════════════════════════

_CATEGORY_CONFIG: dict[str, dict] = {

    # ─────────────────────────────────────────────────────────────────────────
    # AI / Artificial Intelligence
    # ─────────────────────────────────────────────────────────────────────────
    "ai": {
        "strong": [
            "artificial intelligence", "machine learning", "deep learning",
            "generative ai", "gen ai", "large language model", "llm",
            "natural language processing", "nlp", "computer vision",
            "ai platform", "ai solutions", "ai software", "ai products",
            "ai services", "ai company", "ai startup", "ai technology",
            "ai powered", "ai-powered", "ai driven", "ai-driven",
            "intelligent automation", "conversational ai", "ai chatbot",
            "ai assistant", "ai analytics", "predictive ai",
            "neural network", "transformer model", "foundation model",
            "responsible ai", "ai consulting", "ai research",
            "data science platform", "mlops", "ai infrastructure",
        ],
        "positive": [
            "data science", "predictive analytics", "cognitive computing",
            "robotic process automation", "rpa", "intelligent", "automation",
            "recommendation engine", "speech recognition", "image recognition",
            "anomaly detection", "text analytics", "sentiment analysis",
        ],
        "negative": [
            # Clearly unrelated businesses
            "nuts trader", "nuts shop", "grocery", "supermarket", "kirana",
            "hotel", "restaurant", "dhaba", "cafe", "food court",
            "hardware store", "stationery", "book store", "pharmacy",
            "medical store", "clothes", "apparel", "fashion",
            "jewellery", "jewelry", "saree", "textile",
            "petrol pump", "fuel station", "automobile dealer",
            "real estate broker", "property agent", "flat",
            "school", "college", "coaching", "tuition",
            "gym", "fitness", "yoga", "salon", "beauty parlour",
            "plumber", "electrician", "carpenter",
            "transport", "cargo", "logistics firm",
            "travel agent", "tour operator",
            "construction company", "builder", "contractor",
        ],
        "threshold": 2.0,   # require at least one strong hit
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Manufacturing
    # ─────────────────────────────────────────────────────────────────────────
    "manufacturing": {
        "strong": [
            "manufacturing", "manufacturer", "fabrication", "fabricator",
            "industrial production", "production plant", "production facility",
            "factory", "foundry", "casting", "forging", "machining",
            "precision engineering", "machine shop", "tooling",
            "auto components", "industrial components", "precision components",
            "assembly line", "mass production", "batch production",
        ],
        "positive": [
            "machinery", "equipment manufacturer", "industrial",
            "plant", "production", "process industry",
            "steel", "metal", "alloy", "polymer", "composite",
            "mold", "die casting", "cnc", "lathe", "press shop",
        ],
        "negative": [
            "restaurant", "hotel", "dhaba", "cafe", "grocery",
            "medical store", "pharmacy", "hospital",
            "retail shop", "kirana", "supermarket",
            "software company", "it services", "digital agency",
            "real estate broker", "property agent",
            "school", "college", "coaching",
            "travel agent", "tour operator",
            "logistics only", "transport only",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Construction
    # ─────────────────────────────────────────────────────────────────────────
    "construction": {
        "strong": [
            "construction", "contractor", "civil contractor", "civil works",
            "civil engineering", "building contractor", "building construction",
            "infrastructure developer", "road construction", "bridge construction",
            "construction company", "construction firm", "construction group",
            "turnkey construction", "epc contractor", "general contractor",
        ],
        "positive": [
            "builder", "developer", "real estate developer",
            "residential project", "commercial project",
            "structural", "foundation", "rcc", "concrete",
            "site development", "earthwork", "excavation",
            "plumbing contractor", "electrical contractor",
            "interior contractor", "fit-out",
        ],
        "negative": [
            "grocery", "kirana", "supermarket", "restaurant",
            "hotel", "dhaba", "cafe", "food",
            "medical store", "pharmacy", "hospital",
            "software", "it services", "digital",
            "school", "college", "coaching",
            "travel", "tourism",
            "retail", "clothing", "apparel",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Real Estate
    # ─────────────────────────────────────────────────────────────────────────
    "real estate": {
        "strong": [
            "real estate", "realty", "property developer", "property dealer",
            "housing developer", "real estate company", "real estate firm",
            "property consultant", "real estate broker", "real estate agent",
            "real estate investment", "residential developer",
            "commercial real estate", "real estate services",
        ],
        "positive": [
            "builder", "developer", "apartments", "villas", "flats",
            "plotted development", "township", "housing project",
            "property management", "land development",
            "commercial spaces", "office spaces", "leasing",
        ],
        "negative": [
            "grocery", "kirana", "supermarket", "restaurant",
            "software", "it services",
            "manufacturing", "factory", "fabrication",
            "medical", "pharmacy",
            "school", "college",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Information Technology / IT
    # ─────────────────────────────────────────────────────────────────────────
    "it": {
        "strong": [
            "information technology", "it services", "software development",
            "software company", "web development", "app development",
            "saas", "cloud computing", "cloud services", "it consulting",
            "erp", "crm software", "it solutions", "digital transformation",
            "devops", "cybersecurity", "managed it services",
            "software product", "software platform",
        ],
        "positive": [
            "technology company", "tech startup", "digital agency",
            "mobile app", "web app", "api development",
            "database", "server", "networking", "it infrastructure",
            "system integrator", "it outsourcing",
        ],
        "negative": [
            "grocery", "kirana", "supermarket", "restaurant", "hotel",
            "manufacturing", "factory", "fabrication",
            "medical store", "pharmacy",
            "school", "coaching",
            "real estate broker", "property",
            "travel agent", "tour",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Fintech
    # ─────────────────────────────────────────────────────────────────────────
    "fintech": {
        "strong": [
            "fintech", "financial technology", "digital payments", "payment gateway",
            "neobank", "neo bank", "lending platform", "wealthtech",
            "insurtech", "regtech", "digital banking", "digital lending",
            "peer to peer lending", "p2p lending", "robo advisor",
            "upi payments", "digital wallet", "payment solutions",
            "financial software", "fintech startup", "fintech company",
        ],
        "positive": [
            "payments", "digital finance", "nbfc", "microfinance",
            "remittance", "forex platform", "investment platform",
            "trading platform", "stock broking", "mutual fund platform",
            "blockchain finance", "cryptocurrency exchange",
            "credit scoring", "loan management",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "medical store", "pharmacy",
            "school", "coaching",
            "real estate broker", "property dealer",
            "travel agent", "tour operator",
            "construction company",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Healthcare
    # ─────────────────────────────────────────────────────────────────────────
    "healthcare": {
        "strong": [
            "healthcare", "hospital", "multispecialty hospital", "clinic",
            "medical center", "diagnostics", "health services",
            "patient care", "healthcare provider", "medical services",
            "telemedicine", "health tech", "healthtech",
        ],
        "positive": [
            "medical", "doctor", "physician", "nursing", "pharmacy",
            "pathology", "radiology", "icu", "emergency care",
            "health insurance", "wellness", "rehabilitation",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "software only", "it services only",
            "school", "college", "coaching",
            "real estate", "property",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Pharma
    # ─────────────────────────────────────────────────────────────────────────
    "pharma": {
        "strong": [
            "pharmaceutical", "pharmaceuticals", "pharma company",
            "drug manufacturer", "drug manufacturing", "medicine manufacturer",
            "active pharmaceutical", "api manufacturer", "generic drug",
            "formulation", "bulk drug", "biopharma", "biopharmaceutical",
            "clinical trials", "contract manufacturing pharma",
        ],
        "positive": [
            "dosage form", "tablet", "capsule", "injectable",
            "nutraceutical", "ayurvedic medicine", "herbal medicine",
            "cdmo", "cmo pharma",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "software only", "it services only",
            "school", "college", "coaching",
            "real estate", "construction",
            "automobile dealer",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Logistics
    # ─────────────────────────────────────────────────────────────────────────
    "logistics": {
        "strong": [
            "logistics company", "logistics services", "freight forwarding",
            "supply chain", "warehousing", "last mile delivery",
            "courier services", "cargo company", "transport company",
            "fleet management", "third party logistics", "3pl",
            "cold chain logistics", "express delivery",
        ],
        "positive": [
            "transport", "shipping", "distribution", "fulfilment",
            "packaging", "moving company", "relocation services",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "medical store", "pharmacy",
            "school", "college", "coaching",
            "real estate", "property",
            "software development",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Education
    # ─────────────────────────────────────────────────────────────────────────
    "education": {
        "strong": [
            "edtech", "education company", "e-learning", "online learning",
            "learning management", "training institute", "academy",
            "educational services", "school", "college", "university",
            "coaching institute", "skill development",
        ],
        "positive": [
            "curriculum", "course platform", "teaching", "tutoring",
            "exam preparation", "upskilling", "vocational training",
            "certificate program", "online courses",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "medical store", "pharmacy",
            "real estate", "property",
            "logistics", "transport",
            "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Retail / FMCG
    # ─────────────────────────────────────────────────────────────────────────
    "retail": {
        "strong": [
            "retail chain", "retail store", "supermarket", "hypermarket",
            "departmental store", "consumer goods", "fmcg",
            "grocery retail", "retail brand", "retail company",
            "b2c retail", "direct to consumer", "d2c brand",
        ],
        "positive": [
            "distribution", "wholesale", "merchandise", "pos",
            "store chain", "franchise", "outlet",
        ],
        "negative": [
            "software", "it services", "technology company",
            "manufacturing", "factory", "fabrication",
            "medical", "hospital",
            "school", "college", "coaching",
            "real estate", "property",
            "logistics", "transport",
            "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Agriculture
    # ─────────────────────────────────────────────────────────────────────────
    "agriculture": {
        "strong": [
            "agriculture company", "agribusiness", "agri input",
            "agri output", "farming company", "crop science",
            "seeds company", "fertilizer company", "pesticide company",
            "agricultural produce", "food processing agriculture",
            "dairy company", "poultry company",
        ],
        "positive": [
            "irrigation", "organic farming", "horticulture",
            "agro", "agri", "cultivation", "harvest",
            "soil management", "greenhouse",
        ],
        "negative": [
            "software", "it services",
            "manufacturing", "factory",
            "medical", "hospital",
            "school", "college",
            "real estate", "property",
            "construction",
            "restaurant", "hotel",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Automotive
    # ─────────────────────────────────────────────────────────────────────────
    "automotive": {
        "strong": [
            "automobile manufacturer", "automotive company", "car manufacturer",
            "two wheeler manufacturer", "vehicle manufacturer",
            "auto components manufacturer", "auto parts manufacturer",
            "automotive oem", "automotive supplier", "ev manufacturer",
            "electric vehicle company",
        ],
        "positive": [
            "automobile dealer", "car dealer", "commercial vehicle",
            "auto ancillary", "automotive engineering",
            "vehicle assembly", "automotive electronics",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "software only", "it services only",
            "medical", "hospital",
            "school", "college",
            "real estate", "property",
            "logistics only", "transport only",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Energy
    # ─────────────────────────────────────────────────────────────────────────
    "energy": {
        "strong": [
            "solar energy company", "renewable energy company",
            "solar panel manufacturer", "wind energy company",
            "power generation company", "electric utility",
            "energy storage", "energy solutions", "clean energy",
            "biomass energy", "hydropower",
        ],
        "positive": [
            "solar", "wind", "power", "electricity",
            "energy efficiency", "ev charging", "smart grid",
            "oil and gas", "natural gas",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "software only", "it services only",
            "medical", "hospital",
            "school", "college",
            "real estate", "property",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Biotech
    # ─────────────────────────────────────────────────────────────────────────
    "biotech": {
        "strong": [
            "biotechnology company", "biotech company", "life sciences",
            "bioscience", "biopharma", "genomics company",
            "cell therapy", "gene therapy", "biomanufacturing",
            "biological research", "bioprocess",
        ],
        "positive": [
            "molecular biology", "clinical", "diagnostics biotech",
            "proteomics", "genomics", "fermentation",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "software only", "it services only",
            "school", "college", "coaching",
            "real estate", "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Hospitality
    # ─────────────────────────────────────────────────────────────────────────
    "hospitality": {
        "strong": [
            "hotel", "resort", "hospitality company", "luxury hotel",
            "boutique hotel", "hotel chain", "accommodation provider",
            "guesthouse", "lodge", "inn", "motel",
        ],
        "positive": [
            "rooms", "suites", "food and beverage", "banquet",
            "event venue", "catering", "tourism",
        ],
        "negative": [
            "grocery", "kirana", "supermarket",
            "manufacturing", "factory",
            "software", "it services",
            "school", "college",
            "real estate developer",
            "construction company",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Food & Beverage
    # ─────────────────────────────────────────────────────────────────────────
    "food": {
        "strong": [
            "food processing company", "food manufacturing company",
            "food and beverage company", "food brand", "packaged food",
            "fmcg food", "beverage company", "snack manufacturer",
            "dairy manufacturer", "food company",
        ],
        "positive": [
            "food products", "bakery", "confectionery",
            "catering company", "restaurant chain",
            "ready to eat", "frozen food",
        ],
        "negative": [
            "software", "it services",
            "manufacturing unrelated", "factory unrelated",
            "school", "college",
            "real estate", "property",
            "construction",
            "medical", "hospital",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # SaaS
    # ─────────────────────────────────────────────────────────────────────────
    "saas": {
        "strong": [
            "saas company", "software as a service", "cloud software",
            "cloud platform", "subscription software", "software platform",
            "cloud-based software", "cloud application", "saas product",
            "b2b saas", "enterprise saas",
        ],
        "positive": [
            "cloud", "subscription", "software product",
            "api platform", "workflow automation",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "medical", "hospital",
            "school", "coaching",
            "real estate", "property",
            "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Textile
    # ─────────────────────────────────────────────────────────────────────────
    "textile": {
        "strong": [
            "textile manufacturer", "textile company", "garment manufacturer",
            "garment company", "apparel manufacturer", "fabric manufacturer",
            "yarn manufacturer", "weaving company", "spinning company",
            "knitting company", "dyeing company",
        ],
        "positive": [
            "clothing manufacturer", "fashion brand",
            "readymade garments", "export garments",
        ],
        "negative": [
            "software", "it services",
            "restaurant", "hotel",
            "school", "college",
            "real estate", "property",
            "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Chemicals
    # ─────────────────────────────────────────────────────────────────────────
    "chemicals": {
        "strong": [
            "chemical manufacturer", "chemical company", "specialty chemicals",
            "agrochemicals", "petrochemicals", "fine chemicals",
            "industrial chemicals", "chemical exporter",
        ],
        "positive": [
            "polymer", "pigment", "dye manufacturer",
            "solvents", "reagents", "adhesives",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "software", "it services",
            "school", "college",
            "real estate", "property",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Finance
    # ─────────────────────────────────────────────────────────────────────────
    "finance": {
        "strong": [
            "financial services company", "investment company",
            "asset management company", "wealth management company",
            "stock broking", "mutual fund company", "nbfc",
            "insurance company", "financial advisory", "banking services",
        ],
        "positive": [
            "investment", "portfolio", "fund management",
            "equity", "debt fund", "ipo advisory",
            "tax advisory", "financial planning",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "school", "college", "coaching",
            "real estate developer",
            "construction company",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Media
    # ─────────────────────────────────────────────────────────────────────────
    "media": {
        "strong": [
            "media company", "digital media company", "news agency",
            "publishing house", "broadcasting company", "content company",
            "entertainment company", "film production", "media group",
        ],
        "positive": [
            "journalism", "editorial", "magazine", "newspaper",
            "radio station", "television channel", "streaming",
            "content creation", "production house",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "school", "college",
            "real estate", "property",
            "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Telecom
    # ─────────────────────────────────────────────────────────────────────────
    "telecom": {
        "strong": [
            "telecom company", "telecommunications company",
            "internet service provider", "isp", "broadband company",
            "mobile network operator", "telecom services",
            "network infrastructure", "telecom solutions",
        ],
        "positive": [
            "mobile", "broadband", "fiber", "wi-fi solutions",
            "network", "connectivity", "5g",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "school", "college",
            "real estate", "property",
            "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Consulting
    # ─────────────────────────────────────────────────────────────────────────
    "consulting": {
        "strong": [
            "consulting firm", "management consultancy", "business consulting",
            "strategy consulting", "consulting company", "advisory firm",
            "management advisory", "consulting services",
        ],
        "positive": [
            "advisory", "strategy", "transformation",
            "process improvement", "operational consulting",
            "hr consulting", "tax consulting", "legal consulting",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "school", "college",
            "real estate developer",
            "construction company",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # Cybersecurity
    # ─────────────────────────────────────────────────────────────────────────
    "cybersecurity": {
        "strong": [
            "cybersecurity company", "information security company",
            "it security firm", "network security", "endpoint security",
            "penetration testing", "cyber defense", "soc services",
            "security operations center", "vapt", "cyber risk",
        ],
        "positive": [
            "firewall", "antivirus", "encryption",
            "data protection", "compliance security",
            "ethical hacking", "cloud security",
        ],
        "negative": [
            "grocery", "kirana", "restaurant", "hotel",
            "manufacturing", "factory",
            "school", "college",
            "real estate", "property",
            "construction",
        ],
        "threshold": 2.0,
    },

    # ─────────────────────────────────────────────────────────────────────────
    # E-Commerce
    # ─────────────────────────────────────────────────────────────────────────
    "ecommerce": {
        "strong": [
            "ecommerce company", "e-commerce company", "online store",
            "online marketplace", "d2c brand", "direct to consumer",
            "online retail brand", "b2c platform", "online shopping platform",
        ],
        "positive": [
            "online sales", "digital storefront", "cart",
            "online orders", "dropshipping", "marketplace seller",
        ],
        "negative": [
            "manufacturing", "factory",
            "school", "college",
            "real estate", "property",
            "construction",
            "hospital", "medical",
        ],
        "threshold": 2.0,
    },

}

# ── Alias map: normalise user-provided category strings ───────────────────────
_ALIASES: dict[str, str] = {
    # AI / ML
    "ai": "ai",
    "artificial intelligence": "ai",
    "machine learning": "ai",
    "ml": "ai",
    "deep learning": "ai",
    "generative ai": "ai",
    "gen ai": "ai",
    # IT
    "it": "it",
    "information technology": "it",
    "software": "it",
    "tech": "it",
    "technology": "it",
    # Manufacturing
    "manufacturing": "manufacturing",
    "fabrication": "manufacturing",
    "industrial": "manufacturing",
    "manufacturer": "manufacturing",
    # Construction
    "construction": "construction",
    "contractor": "construction",
    "civil": "construction",
    # Real Estate
    "real estate": "real estate",
    "realty": "real estate",
    "property": "real estate",
    # Fintech
    "fintech": "fintech",
    "financial technology": "fintech",
    # Healthcare
    "healthcare": "healthcare",
    "health": "healthcare",
    "medical": "healthcare",
    # Pharma
    "pharma": "pharma",
    "pharmaceutical": "pharma",
    "pharmaceuticals": "pharma",
    # Logistics
    "logistics": "logistics",
    "transport": "logistics",
    "transportation": "logistics",
    # Education
    "education": "education",
    "edtech": "education",
    # Retail
    "retail": "retail",
    "fmcg": "retail",
    # Agriculture
    "agriculture": "agriculture",
    "agri": "agriculture",
    "agro": "agriculture",
    "farming": "agriculture",
    # Automotive
    "automotive": "automotive",
    "automobile": "automotive",
    "auto": "automotive",
    # Energy
    "energy": "energy",
    "solar": "energy",
    "renewable energy": "energy",
    # Biotech
    "biotech": "biotech",
    "biotechnology": "biotech",
    "life sciences": "biotech",
    # Hospitality
    "hospitality": "hospitality",
    "hotel": "hospitality",
    # Food
    "food": "food",
    "food and beverage": "food",
    "f&b": "food",
    # SaaS
    "saas": "saas",
    "software as a service": "saas",
    # Textile
    "textile": "textile",
    "garment": "textile",
    "apparel": "textile",
    # Chemicals
    "chemicals": "chemicals",
    "chemical": "chemicals",
    # Finance
    "finance": "finance",
    "financial services": "finance",
    # Media
    "media": "media",
    "entertainment": "media",
    # Telecom
    "telecom": "telecom",
    "telecommunications": "telecom",
    # Consulting
    "consulting": "consulting",
    "consultancy": "consulting",
    # Cybersecurity
    "cybersecurity": "cybersecurity",
    "cyber security": "cybersecurity",
    "information security": "cybersecurity",
    # E-Commerce
    "ecommerce": "ecommerce",
    "e-commerce": "ecommerce",
}


def _normalise_category(raw: str) -> Optional[str]:
    """Return the canonical category key, or None if unknown."""
    key = raw.strip().lower()
    return _ALIASES.get(key) or _ALIASES.get(key.replace("-", " ")) or None


def _build_fingerprint(company: dict) -> str:
    """
    Concatenate all available text signals into one lowercase string for
    keyword matching.  Fields tried (in order):
      company_name, description, industry, primary_type (Google Maps),
      _merged_markdown (Firecrawl), services, search_query, CE raw industry,
      category field.
    """
    parts: list[str] = []

    def _add(val):
        if val and isinstance(val, str):
            parts.append(val.strip().lower())

    _add(company.get("company_name"))
    _add(company.get("description"))
    _add(company.get("industry"))
    _add(company.get("primary_type"))             # Google Maps primary type
    _add(company.get("category"))
    _add(company.get("_merged_markdown", "")[:3000])  # first 3KB of scraped content
    _add(company.get("source_url"))

    # CompanyEnrich raw data
    ce_raw = company.get("_companyenrich_raw") or {}
    _add(ce_raw.get("industry"))
    _add(ce_raw.get("description"))
    _add(ce_raw.get("seo_description"))

    # Services list
    services = company.get("services") or []
    if isinstance(services, list):
        parts.extend(str(s).strip().lower() for s in services if s)

    # Search query used to discover this company (has category name in it)
    _add(company.get("search_query"))

    # Website domain as weak signal
    website = company.get("website") or ""
    _add(website)

    return " | ".join(p for p in parts if p)


def validate_category(company: dict, category: str) -> CategoryResult:
    """
    Validate that a company belongs to the given category.

    Returns a CategoryResult with accepted=True/False plus scoring details.

    For unknown categories (not in _CATEGORY_CONFIG), we accept all companies
    conservatively (cannot validate what we don't know).
    """
    canonical = _normalise_category(category)
    cfg = _CATEGORY_CONFIG.get(canonical) if canonical else None

    company_name = company.get("company_name") or "(unknown)"

    # ── Unknown category → accept conservatively ─────────────────────────────
    if cfg is None:
        return CategoryResult(
            accepted=True,
            score=0.0,
            reason="unknown_category_pass",
        )

    fingerprint = _build_fingerprint(company)

    # ── No text at all → accept conservatively (name-only, no enrichment) ────
    if not fingerprint.strip() or fingerprint.strip() == company_name.lower():
        return CategoryResult(
            accepted=True,
            score=0.0,
            reason="name_only_passed",
        )

    # ── Check negative signals first (instant reject) ────────────────────────
    for neg in cfg.get("negative", []):
        if neg.lower() in fingerprint:
            return CategoryResult(
                accepted=False,
                score=0.0,
                reason=f"negative_signal:{neg}",
                neg_hit=neg,
            )

    # ── Score positive signals ────────────────────────────────────────────────
    score = 0.0
    hits: list[str] = []

    for term in cfg.get("strong", []):
        if term.lower() in fingerprint:
            score += 2.0
            hits.append(f"+2:{term}")

    for term in cfg.get("positive", []):
        if term.lower() in fingerprint:
            score += 1.0
            hits.append(f"+1:{term}")

    threshold = cfg.get("threshold", 2.0)

    if score >= threshold:
        return CategoryResult(
            accepted=True,
            score=score,
            reason=f"score:{score:.1f}>={threshold}",
            signals_hit=hits,
        )

    # ── No positive signals → check if name alone is a strong positive ───────
    # Some companies use very clear category names (e.g. "XYZ AI Solutions")
    # even if the description wasn't enriched.
    name_fp = (company_name or "").lower()
    for term in cfg.get("strong", []):
        if term.lower() in name_fp:
            return CategoryResult(
                accepted=True,
                score=2.0,
                reason=f"name_strong_match:{term}",
                signals_hit=[f"+2:{term}"],
            )

    return CategoryResult(
        accepted=False,
        score=score,
        reason=f"score:{score:.1f}<{threshold}_no_positive_signals",
        signals_hit=hits,
    )


def filter_companies(
    companies: list[dict],
    category: str,
    log_prefix: str = "",
) -> tuple[list[dict], list[dict]]:
    """
    Split companies into (valid, rejected) based on category validation.

    Logs every decision in the required format:
      [CATEGORY FILTER] Selected category: AI  Candidate: ABC Nuts  Result: REJECTED  ...
      [CATEGORY FILTER] Selected category: AI  Candidate: XYZ AI    Result: ACCEPTED  ...

    Returns (valid_list, rejected_list).
    """
    canonical = _normalise_category(category)
    cfg_exists = canonical is not None and canonical in _CATEGORY_CONFIG

    valid:    list[dict] = []
    rejected: list[dict] = []

    prefix = f"[{log_prefix}] " if log_prefix else ""

    for company in companies:
        name = company.get("company_name") or "(unknown)"
        result = validate_category(company, category)

        if result.accepted:
            valid.append(company)
            _log(
                f"{prefix}Category: {category!r}  "
                f"Candidate: {name!r}  "
                f"Result: ACCEPTED  "
                f"Reason: {result.reason}"
                + (f"  Signals: {result.signals_hit[:3]}" if result.signals_hit else "")
            )
        else:
            rejected.append(company)
            _log(
                f"{prefix}Category: {category!r}  "
                f"Candidate: {name!r}  "
                f"Result: REJECTED  "
                f"Reason: {result.reason}"
                + (f"  Negative_signal: {result.neg_hit!r}" if result.neg_hit else "")
            )

    return valid, rejected


def log_filter_summary(
    category:   str,
    location:   str,
    requested:  int,
    candidates: int,
    valid:      int,
    rejected:   int,
    reasons:    Optional[dict] = None,
) -> None:
    """
    Print the end-of-run filter summary.

    ─── CATEGORY FILTER SUMMARY ───────────────────────────────
    Requested category : AI
    Location           : Bengaluru
    Requested leads    : 100
    Candidates found   : 120
    Valid leads        : 87
    Rejected           : 33
    Rejection reasons  : {negative_signal:nuts trader: 5, score<threshold: 28}
    ───────────────────────────────────────────────────────────
    """
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [
        "",
        f"[{ts}] ─── CATEGORY FILTER SUMMARY ───────────────────────────",
        f"[{ts}]   Requested category : {category}",
        f"[{ts}]   Location           : {location}",
        f"[{ts}]   Requested leads    : {requested}",
        f"[{ts}]   Candidates found   : {candidates}",
        f"[{ts}]   Valid leads        : {valid}",
        f"[{ts}]   Rejected           : {rejected}",
    ]
    if reasons:
        lines.append(f"[{ts}]   Rejection reasons  : {reasons}")
    if valid < requested:
        lines.append(
            f"[{ts}]   ⚠ Only {valid} valid leads found; "
            f"{requested - valid} candidates could not be found or were rejected by category validation."
        )
    lines.append(f"[{ts}] ──────────────────────────────────────────────────────")
    lines.append("")
    print("\n".join(lines), flush=True)
