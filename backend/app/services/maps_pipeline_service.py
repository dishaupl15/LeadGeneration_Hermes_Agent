"""
app/services/maps_pipeline_service.py
──────────────────────────────────────
Adapter between the isolated google_maps/ discovery module and the existing
CompanyEnrich → Serper → Firecrawl enrichment pipeline.

Pipeline:
  Google Maps Discovery (place_id, name, address, phone, website, lat/lng)
    ↓
  Deduplication (place_id + normalised name + website domain + phone)
    ↓
  Field Completeness Check (identify what's missing per company)
    ↓
  CompanyEnrich (ONLY for missing fields — email, founder, company_number)
    ↓
  Serper Fallback (ONLY for remaining missing fields)
    ↓
  Firecrawl Fallback (ONLY for remaining missing fields, website must exist)
    ↓
  Validation + Confidence Scoring
    ↓
  Final Deduplication
    ↓
  MongoDB

Field priority (per field individually):
  Google Maps > CompanyEnrich > Serper > Firecrawl

Rules:
  - Google Maps data is AUTHORITATIVE — never overwrite it with weaker data.
  - Only call a provider for MISSING fields.
  - Never fabricate data.
  - Keep google_maps module logically isolated — only this file imports from it.
  - Email from Google Maps is rare; use CompanyEnrich → Serper → Firecrawl for email.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(tag: str, msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


# ── Pipeline stats tracker ─────────────────────────────────────────────────

class _PipelineStats:
    def __init__(self):
        self.gmaps_discovered     = 0
        self.gmaps_duplicates     = 0
        self.companyenrich_calls  = 0
        self.companyenrich_filled = 0
        self.serper_calls         = 0
        self.serper_filled        = 0
        self.firecrawl_calls      = 0
        self.firecrawl_filled     = 0
        self.final_companies      = 0
        # Origami enrichment stats
        self.origami_calls            = 0
        self.origami_contacts_found   = 0
        self.origami_founders_found   = 0
        self.origami_emails_found     = 0
        self.origami_skipped          = 0
        # People enrichment orchestrator stats
        self.people_companies_processed = 0
        self.people_contacts_found      = 0
        self.people_emails_found        = 0
        self.people_phones_found        = 0
        self.pdl_calls                  = 0
        self.pdl_contacts               = 0
        self.prospeo_calls              = 0
        self.prospeo_contacts           = 0
        self.contactout_calls           = 0
        self.contactout_contacts        = 0
        self.people_target_reached      = 0
        self.people_auth_failures       = 0
        self.hunter_calls      = 0
        self.hunter_success    = 0
        self.hunter_no_result  = 0
        self.hunter_failed     = 0
        self.hunter_contacts   = 0
        # Legacy PDL-direct fields (kept for backward compat — now populated via orchestrator)
        self.pdl_companies_searched  = 0
        self.pdl_contacts_found      = 0
        self.pdl_emails_found        = 0
        self.pdl_api_calls           = 0
        self.pdl_auth_failures       = 0
        self.pdl_phones_found        = 0

_pipeline_stats: _PipelineStats = _PipelineStats()


def get_pipeline_stats() -> dict:
    s = _pipeline_stats
    return {
        "google_maps_discovered":     s.gmaps_discovered,
        "google_maps_duplicates":     s.gmaps_duplicates,
        "companyenrich_calls":        s.companyenrich_calls,
        "companyenrich_fields_filled": s.companyenrich_filled,
        "serper_calls":               s.serper_calls,
        # Origami stats (inserted between serper/firecrawl and people blocks)
        "origami_calls":              s.origami_calls,
        "origami_contacts_found":     s.origami_contacts_found,
        "origami_founders_found":     s.origami_founders_found,
        "origami_emails_found":       s.origami_emails_found,
        "origami_skipped":            s.origami_skipped,
        "serper_fields_filled":       s.serper_filled,
        "firecrawl_calls":            s.firecrawl_calls,
        "firecrawl_fields_filled":    s.firecrawl_filled,
        "final_valid_companies":      s.final_companies,
        # People enrichment orchestrator
        "people_companies_processed": s.people_companies_processed,
        "people_contacts_found":      s.people_contacts_found,
        "people_emails_found":        s.people_emails_found,
        "people_phones_found":        s.people_phones_found,
        "pdl_calls":                  s.pdl_calls,
        "pdl_contacts":               s.pdl_contacts,
        "prospeo_calls":              s.prospeo_calls,
        "prospeo_contacts":           s.prospeo_contacts,
        "contactout_calls":           s.contactout_calls,
        "contactout_contacts":        s.contactout_contacts,
        "people_target_reached":      s.people_target_reached,
        "people_auth_failures":       s.people_auth_failures,
        # Hunter.io fallback stats
        "hunter_calls":               s.hunter_calls,
        "hunter_success":             s.hunter_success,
        "hunter_no_result":           s.hunter_no_result,
        "hunter_failed":              s.hunter_failed,
        "hunter_contacts":            s.hunter_contacts,
        # Legacy PDL direct stats (kept for backward compat — now populated via orchestrator)
        "pdl_companies_searched":     s.pdl_companies_searched,
        "pdl_contacts_found":         s.pdl_contacts_found,
        "pdl_emails_found":           s.pdl_emails_found,
        "pdl_phones_found":           s.pdl_phones_found,
        "pdl_api_calls":              s.pdl_api_calls,
        "pdl_auth_failures":          s.pdl_auth_failures,
    }


# ── Helper: normalize domain ───────────────────────────────────────────────

def _normalize_domain(url: str) -> str:
    if not url:
        return ""
    u = url.strip().lower()
    if not u.startswith("http"):
        u = "https://" + u
    try:
        parsed = urlparse(u)
        d = parsed.netloc.lstrip("www.")
        return d.split(":")[0].split("/")[0].strip()
    except Exception:
        return ""


def _digits_only(phone: str) -> str:
    return re.sub(r'\D', '', phone or '')


# ── Convert MapBusiness → pipeline dict ────────────────────────────────────

def _maps_biz_to_company(biz) -> dict:
    """
    Convert a google_maps MapBusiness into the flat dict shape used by
    the existing enrichment pipeline.

    Google Maps fields are set as AUTHORITATIVE — marked in _field_verification
    so downstream enrichment knows NOT to overwrite them.
    """
    phone   = biz.phone or None
    website = biz.website or None
    domain  = _normalize_domain(website) if website else ""

    fv: dict = {}
    if phone:
        fv["phone"] = {"value": phone, "verified": True,
                       "status": "google_maps_phone", "source": "google_maps"}
    if website:
        fv["website"] = {"value": website, "verified": True,
                         "status": "google_maps_website", "source": "google_maps"}
    if biz.address:
        fv["address"] = {"value": biz.address, "verified": True,
                         "status": "google_maps_address", "source": "google_maps"}

    return {
        # Identity
        "company_name":     biz.name,
        "website":          website or "",
        "domain":           domain,
        # Contact
        "company_number":   phone,
        "phones":           [phone] if phone else [],
        "email":            None,
        "emails":           [],
        # Address
        "address":          biz.address or "",
        "city":             "",
        "state":            "",
        "country":          "India",
        "postal_code":      "",
        # Geo
        "latitude":         biz.latitude,
        "longitude":        biz.longitude,
        # Google-specific
        "place_id":         biz.place_id,
        "google_maps_uri":  biz.google_maps_uri,
        "primary_type":     biz.primary_type,
        # Founders / enriched fields
        "founder_name":     None,
        "founder_number":   None,
        "source_url":       website or "",
        "sources":          [website] if website else [],
        # Meta
        "description":      "",
        "industry":         biz.primary_type or "",
        "confidence":       0.0,
        "research_source":  "google_maps",
        "research_sources": [website] if website else [],
        "_field_verification": fv,
        "_merged_markdown": "",
        "_scraped_pages":   [],
        "pages_visited":    {"success": [website] if website else [], "failed": []},
        "_ce_enriched":     False,
        "_gmaps_source":    True,       # sentinel — prevents overwriting Maps data
    }


# ── Field completeness check ────────────────────────────────────────────────

def _missing_fields(company: dict) -> list[str]:
    """
    Return the list of fields that are missing and should be enriched.
    Only fields that are genuinely absent (None / empty) are listed.
    Google Maps authoritative fields are never added to the missing list.
    """
    missing = []
    if not company.get("email"):
        missing.append("email")
    if not company.get("founder_name"):
        missing.append("founder_name")
    if not company.get("company_number"):
        missing.append("company_number")
    # address: only missing if completely absent; Google Maps usually provides it
    if not company.get("address"):
        missing.append("address")
    return missing


def _count_filled(before: dict, after: dict, fields: list[str]) -> int:
    """Count how many fields were filled by an enrichment step."""
    filled = 0
    for f in fields:
        had = bool(before.get(f))
        has = bool(after.get(f))
        if not had and has:
            filled += 1
    return filled


# ── Merge enriched data (never overwrite authoritative Google Maps fields) ──

def _safe_merge(base: dict, enriched: dict, source: str) -> dict:
    """
    Merge enriched fields into base dict.
    NEVER overwrites fields that came from Google Maps (_field_verification source == google_maps).
    Priority: google_maps > companyenrich > serper > firecrawl
    """
    updated = dict(base)
    fv = dict(updated.get("_field_verification") or {})

    _SOURCE_PRIORITY = {"google_maps": 0, "companyenrich": 1, "serper": 2, "firecrawl": 3}
    src_rank = _SOURCE_PRIORITY.get(source, 99)

    def _current_rank(field_key: str) -> int:
        existing = fv.get(field_key) or {}
        if isinstance(existing, dict):
            existing_src = (existing.get("source") or "").lower()
            for k, r in _SOURCE_PRIORITY.items():
                if k in existing_src:
                    return r
        return 99  # unknown → lowest priority, can be overwritten

    # email
    if enriched.get("email") and not updated.get("email"):
        if _current_rank("email") >= src_rank:
            updated["email"] = enriched["email"]
            emails = list(updated.get("emails") or [])
            if enriched["email"] not in emails:
                emails.insert(0, enriched["email"])
            updated["emails"] = emails
            fv["email"] = {"value": enriched["email"], "verified": True,
                           "status": f"{source}_email", "source": source}

    # company_number
    if enriched.get("company_number") and not updated.get("company_number"):
        if _current_rank("phone") >= src_rank:
            updated["company_number"] = enriched["company_number"]
            phones = list(updated.get("phones") or [])
            if enriched["company_number"] not in phones:
                phones.insert(0, enriched["company_number"])
            updated["phones"] = phones
            fv["phone"] = {"value": enriched["company_number"], "verified": True,
                           "status": f"{source}_phone", "source": source}

    # address (only if completely absent)
    if enriched.get("address") and not updated.get("address"):
        if _current_rank("address") >= src_rank:
            updated["address"] = enriched["address"]
            for f in ("city", "state", "country", "postal_code"):
                if not updated.get(f) and enriched.get(f):
                    updated[f] = enriched[f]
            fv["address"] = {"value": enriched["address"], "verified": True,
                             "status": f"{source}_address", "source": source}

    # founder_name
    if enriched.get("founder_name") and not updated.get("founder_name"):
        updated["founder_name"]   = enriched["founder_name"]
        updated["founder_number"] = enriched.get("founder_number")
        fv["founder"] = {"value": enriched["founder_name"], "verified": True,
                         "status": f"{source}_founder", "source": source}

    # website (only if Maps didn't provide it)
    if enriched.get("website") and not updated.get("website"):
        if _current_rank("website") >= src_rank:
            updated["website"] = enriched["website"]
            if not updated.get("domain"):
                updated["domain"] = _normalize_domain(enriched["website"])
            fv["website"] = {"value": enriched["website"], "verified": True,
                             "status": f"{source}_website", "source": source}

    updated["_field_verification"] = fv
    return updated


# ── CompanyEnrich enrichment (missing fields only) ─────────────────────────

async def _enrich_via_companyenrich(company: dict, missing: list[str]) -> dict:
    """
    Call CompanyEnrich endpoints for ONLY the fields that are missing.
    Never overwrites existing Google Maps data.
    """
    if not missing:
        return company

    name   = company.get("company_name", "")
    domain = company.get("domain") or _normalize_domain(company.get("website", ""))

    if not domain:
        _log("COMPANYENRICH", f"{name}: no domain — skipping CE enrichment")
        return company

    from app.services.companyenrich_service import (
        is_credits_exhausted, enrich_company_by_domain, find_founder_with_email,
        _normalize_domain as _ce_norm,
    )
    if is_credits_exhausted():
        _log("COMPANYENRICH", f"{name}: credits exhausted — skipping")
        return company

    _pipeline_stats.companyenrich_calls += 1
    _log("COMPANYENRICH", f"{name}: enriching missing fields={missing} domain={domain!r}")

    need_company_data = any(f in missing for f in ("company_number", "address", "email"))
    need_founder      = "founder_name" in missing

    company_data: dict = {}
    founder_name: Optional[str]  = None
    founder_email: Optional[str] = None
    founder_phone: Optional[str] = None

    async def _noop_company() -> dict:
        return {}

    async def _noop_founder():
        return None, None, None, "", ""

    tasks = []
    if need_company_data:
        tasks.append(enrich_company_by_domain(domain))
    else:
        tasks.append(_noop_company())

    if need_founder:
        tasks.append(find_founder_with_email(name, domain))
    else:
        tasks.append(_noop_founder())

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        company_data_raw = results[0] if not isinstance(results[0], Exception) else {}
        founder_result   = results[1] if not isinstance(results[1], Exception) else (None, None, None, "", "")
        company_data     = company_data_raw if isinstance(company_data_raw, dict) else {}
        if isinstance(founder_result, tuple) and len(founder_result) >= 3:
            founder_name, founder_email, founder_phone = founder_result[:3]
    except Exception as exc:
        _log("COMPANYENRICH", f"{name}: enrichment error: {exc}")
        return company

    # Build enriched dict from CE data
    enriched: dict = {}

    if company_data:
        location    = company_data.get("location") or {}
        city_obj    = location.get("city")    or {}
        state_obj   = location.get("state")   or {}
        country_obj = location.get("country") or {}

        ce_phone  = (location.get("phone") or "").strip() or None
        ce_street = (location.get("address") or "").strip()
        ce_postal = (location.get("postal_code") or "").strip()
        ce_city   = (city_obj.get("name",    "") if isinstance(city_obj,    dict) else "").strip()
        ce_state  = (state_obj.get("name",   "") if isinstance(state_obj,   dict) else "").strip()
        ce_country= (country_obj.get("name", "") if isinstance(country_obj, dict) else "").strip()
        ce_website= (company_data.get("website") or "").strip()

        addr_parts = [p for p in [ce_street, ce_city, ce_state, ce_postal, ce_country] if p]
        ce_address = ", ".join(addr_parts)

        if ce_phone:    enriched["company_number"] = ce_phone
        if ce_address:  enriched["address"]   = ce_address
        if ce_city:     enriched["city"]       = ce_city
        if ce_state:    enriched["state"]      = ce_state
        if ce_country:  enriched["country"]    = ce_country
        if ce_postal:   enriched["postal_code"]= ce_postal
        if ce_website and not company.get("website"):
            enriched["website"] = ce_website

    # Founder + email from people search
    from app.services.verify_service import _is_plausible_person_name
    if founder_name and _is_plausible_person_name(founder_name):
        enriched["founder_name"]   = founder_name
        enriched["founder_number"] = founder_phone
    if founder_email:
        enriched["email"] = founder_email

    before = dict(company)
    updated = _safe_merge(company, enriched, "companyenrich")
    filled = _count_filled(before, updated, missing)
    _pipeline_stats.companyenrich_filled += filled
    _log("COMPANYENRICH", f"{name}: fields filled={filled}/{len(missing)} (email={bool(updated.get('email'))}, founder={bool(updated.get('founder_name'))}, phone={bool(updated.get('company_number'))})")
    return updated


# ── Serper fallback (missing fields only) ──────────────────────────────────

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_PATTERNS = [
    re.compile(r'\+91[\s\-]?[6-9]\d{4}[\s\-]?\d{5}'),
    re.compile(r'\b0\d{2,4}[\s\-]\d{6,8}\b'),
    re.compile(r'\b[6-9]\d{9}\b'),  # 10-digit Indian mobile
]
_LEADER_RE = re.compile(
    r'(?i)(founder|co-founder|ceo|chief\s+executive|managing\s+director|chairman|md\b)'
)
_NAME_RE = re.compile(r'\b([A-Z][a-z]{1,20})\s+([A-Z][a-z]{1,20})\b')
_JUNK_EMAIL_LOCALS = frozenset({
    "noreply", "no-reply", "donotreply", "webmaster", "abuse",
    "postmaster", "spam", "admin", "test", "example",
})


def _is_junk_email(addr: str) -> bool:
    addr  = addr.lower().strip()
    local, _, dom = addr.partition("@")
    if not dom or "." not in dom:
        return True
    if local in _JUNK_EMAIL_LOCALS:
        return True
    if "/" in addr or len(local) < 2:
        return True
    return False


async def _serper_snippets(query: str, client) -> str:
    """Run a single Serper query and return merged snippet text."""
    serper_key = os.getenv("SERPER_API_KEY", "")
    if not serper_key or not query.strip():
        return ""
    import httpx
    _pipeline_stats.serper_calls += 1
    try:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
            json={"q": query.strip(), "num": 5},
            timeout=12,
        )
        if resp.status_code == 400:
            return ""
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""
    return "\n".join(
        item.get("snippet", "")
        for item in data.get("organic", [])[:5]
        if item.get("snippet")
    )


async def _enrich_via_serper(company: dict, missing: list[str]) -> dict:
    """
    Use Serper to fill ONLY remaining missing fields.
    Builds targeted queries based on exactly what's missing.
    """
    if not missing:
        return company

    serper_key = os.getenv("SERPER_API_KEY", "")
    if not serper_key:
        return company

    name   = company.get("company_name", "")
    domain = company.get("domain") or ""

    _log("SERPER", f"{name}: fallback for missing={missing}")

    import httpx
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(15),
        limits=httpx.Limits(max_connections=5),
        follow_redirects=True,
    )

    gap_queries: list[str] = []

    if "email" in missing:
        if domain:
            gap_queries.append(f'"{name}" email site:{domain}')
            gap_queries.append(f'"{name}" "@{domain}"')
        gap_queries.append(f'"{name}" contact email India')

    if "founder_name" in missing:
        gap_queries.append(f'"{name}" founder CEO "managing director"')
        if domain:
            gap_queries.append(f'site:{domain} founder CEO')

    if "company_number" in missing:
        if domain:
            gap_queries.append(f'site:{domain} phone contact')
        gap_queries.append(f'"{name}" phone number India')

    if "address" in missing and not company.get("address"):
        gap_queries.append(f'"{name}" office address India')

    try:
        tasks  = [_serper_snippets(q, client) for q in gap_queries]
        texts  = await asyncio.gather(*tasks, return_exceptions=True)
        merged = "\n".join(t for t in texts if isinstance(t, str))
    finally:
        await client.aclose()

    enriched: dict = {}

    # Extract email
    if "email" in missing:
        for addr in _EMAIL_RE.findall(merged):
            al = addr.lower()
            if not _is_junk_email(al):
                if domain:
                    em_dom = al.split("@")[-1]
                    if em_dom == domain or em_dom.endswith("." + domain):
                        enriched["email"] = al
                        break
                else:
                    enriched["email"] = al
                    break

    # Extract founder
    if "founder_name" in missing:
        for line in merged.split("\n"):
            if _LEADER_RE.search(line):
                m = _NAME_RE.search(line)
                if m:
                    from app.services.verify_service import _is_plausible_person_name
                    if _is_plausible_person_name(m.group(0)):
                        enriched["founder_name"] = m.group(0)
                        break

    # Extract phone
    if "company_number" in missing:
        for pat in _PHONE_PATTERNS:
            for m in pat.finditer(merged):
                raw = m.group(0).strip()
                digs = re.sub(r'\D', '', raw)
                if 7 <= len(digs) <= 15:
                    enriched["company_number"] = raw
                    break
            if enriched.get("company_number"):
                break

    before  = dict(company)
    updated = _safe_merge(company, enriched, "serper")
    filled  = _count_filled(before, updated, missing)
    _pipeline_stats.serper_filled += filled
    _log("SERPER", f"{name}: fields filled={filled}/{len(missing)}")
    return updated


# ── Firecrawl fallback (website pages, missing fields only) ───────────────

_USEFUL_PATHS = ["/", "/contact", "/contact-us", "/about", "/about-us",
                 "/team", "/leadership", "/founders"]
_FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

# Per-request website crawl cache (domain → extracted info)
_crawl_cache: dict[str, dict] = {}


def _reset_crawl_cache() -> None:
    global _crawl_cache
    _crawl_cache = {}


async def _scrape_page(url: str, client) -> str:
    """Scrape a single page via Firecrawl. Returns markdown text."""
    fc_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not fc_key:
        return ""
    import httpx
    import json as _json
    _pipeline_stats.firecrawl_calls += 1
    try:
        resp = await client.post(
            _FIRECRAWL_URL,
            headers={
                "Authorization": f"Bearer {fc_key}",
                "Content-Type": "application/json",
            },
            content=_json.dumps({
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": False,
                "timeout": 20000,
            }).encode(),
            timeout=25,
        )
        if resp.status_code in (404, 403, 400, 429):
            return ""
        resp.raise_for_status()
        data = resp.json()
        result = data.get("data") or data
        if isinstance(result, list):
            result = result[0] if result else {}
        return (result.get("markdown") or "")[:10000]
    except Exception:
        return ""


async def _enrich_via_firecrawl(company: dict, missing: list[str]) -> dict:
    """
    Crawl the company website for ONLY remaining missing fields.
    Uses cache to avoid re-crawling the same domain in a single run.
    """
    if not missing:
        return company

    fc_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not fc_key:
        return company

    website = company.get("website") or ""
    domain  = company.get("domain")  or _normalize_domain(website)

    if not website or not domain:
        _log("FIRECRAWL", f"{company.get('company_name','?')}: no website — skipping")
        return company

    name = company.get("company_name", "")
    _log("FIRECRAWL", f"{name}: fallback for missing={missing} domain={domain!r}")

    # Check cache
    if domain in _crawl_cache:
        merged_md = _crawl_cache[domain]
        _log("FIRECRAWL", f"{name}: cache hit for {domain!r}")
    else:
        import httpx
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            limits=httpx.Limits(max_connections=3),
            follow_redirects=True,
        )
        base = website.rstrip("/")
        tasks = [_scrape_page(f"{base}{path}", client) for path in _USEFUL_PATHS]
        try:
            pages = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await client.aclose()

        parts = [p for p in pages if isinstance(p, str) and p.strip()]
        merged_md = "\n\n".join(parts)[:30000]
        _crawl_cache[domain] = merged_md
        _log("FIRECRAWL", f"{name}: crawled {sum(1 for p in pages if isinstance(p, str) and p)} pages")

    # Extract from markdown
    enriched: dict = {}

    if "email" in missing:
        for addr in _EMAIL_RE.findall(merged_md):
            al = addr.lower()
            if not _is_junk_email(al):
                em_dom = al.split("@")[-1]
                if em_dom == domain or em_dom.endswith("." + domain) or not domain:
                    enriched["email"] = al
                    break

    if "founder_name" in missing:
        for line in merged_md.split("\n"):
            if _LEADER_RE.search(line):
                m = _NAME_RE.search(line)
                if m:
                    from app.services.verify_service import _is_plausible_person_name
                    if _is_plausible_person_name(m.group(0)):
                        enriched["founder_name"] = m.group(0)
                        break

    if "company_number" in missing:
        for pat in _PHONE_PATTERNS:
            for m in pat.finditer(merged_md):
                raw = m.group(0).strip()
                digs = re.sub(r'\D', '', raw)
                if 7 <= len(digs) <= 15:
                    enriched["company_number"] = raw
                    break
            if enriched.get("company_number"):
                break

    before  = dict(company)
    updated = _safe_merge(company, enriched, "firecrawl")
    filled  = _count_filled(before, updated, missing)
    _pipeline_stats.firecrawl_filled += filled
    _log("FIRECRAWL", f"{name}: fields filled={filled}/{len(missing)}")
    return updated


# ── Confidence scoring ──────────────────────────────────────────────────────

def _score_confidence(company: dict) -> float:
    score = 0.0
    if company.get("email"):          score += 0.30
    if company.get("company_number"): score += 0.25
    if company.get("address"):        score += 0.15
    if company.get("founder_name"):   score += 0.10
    if company.get("website"):        score += 0.10
    if company.get("domain"):         score += 0.05
    # Bonus for verified fields
    fv = company.get("_field_verification") or {}
    verified = sum(1 for v in fv.values() if isinstance(v, dict) and v.get("verified"))
    if verified >= 2: score += 0.05
    return round(min(score, 1.0), 2)


# ── People enrichment orchestrator ────────────────────────────────────────

async def _enrich_via_people_orchestrator(company: dict) -> dict:
    """
    Run the full people-enrichment waterfall (PDL → Prospeo → ContactOut) for
    one company using the people_enrichment orchestrator.

    The orchestrator is the ONLY layer that calls the three people providers.
    This function does NOT call PDL, Prospeo, or ContactOut directly.

    Waterfall stops as soon as PEOPLE_ENRICHMENT_TARGET (default 2) useful
    contacts are found. Auth failures on any provider are handled internally
    and do NOT break the pipeline.

    Results are cached by company domain inside the orchestrator.
    """
    company_name = company.get("company_name", "")
    domain       = company.get("domain") or _normalize_domain(company.get("website", ""))
    website      = company.get("website") or ""

    if not company_name:
        return company

    try:
        from people_enrichment.orchestrator import enrich_company_contacts
        result = await enrich_company_contacts(
            company_name=company_name,
            domain=domain or None,
            website=website or None,
            origami_contacts=company.get("_origami_contacts") or None,
        )
    except Exception as exc:
        _log("PEOPLE_ENRICH", f"Orchestrator error for {company_name!r} — {type(exc).__name__}: {exc}")
        return company

    # Remove staging field — not persisted to MongoDB
    company.pop("_origami_contacts", None)

    # Attach the enriched contacts list to the company dict
    # Each contact is serialised to a plain dict for MongoDB storage
    contacts_list = []
    for c in result.contacts:
        contacts_list.append({
            "name":         c.name,
            "title":        c.title,
            "email":        c.email,
            "phone":        c.phone,
            "linkedin_url": c.linkedin_url,
            "sources":      list(c.sources),
            "confidence":   c.confidence,
        })
    company["contacts"] = contacts_list

    # ── Promote best contact email → company-level email field ───────────────
    # The people waterfall (PDL → Prospeo → ContactOut) stores emails in
    # contacts[].email but the UI and MongoDB upsert read company["email"].
    # Promote the first available contact email when the company has no email yet.
    if not company.get("email"):
        for ct in contacts_list:
            if ct.get("email"):
                company["email"] = ct["email"]
                # Also keep it in the emails list for backward compat
                emails = list(company.get("emails") or [])
                if ct["email"] not in emails:
                    emails.insert(0, ct["email"])
                company["emails"] = emails
                fv = dict(company.get("_field_verification") or {})
                fv["email"] = {
                    "value":    ct["email"],
                    "verified": True,
                    "status":   f"people_enrichment_{','.join(ct.get('sources', ['unknown']))}",
                    "source":   "people_enrichment",
                }
                company["_field_verification"] = fv
                _log(
                    "PEOPLE_ENRICH",
                    f"{company_name!r} — promoted contact email from "
                    f"{ct.get('name','?')!r} ({ct.get('title','?')!r}) "
                    f"via {','.join(ct.get('sources', []))}",
                )
                break

    # ── Also promote best contact phone → founder_number if not set ──────────
    # Only promote phone if the contact also has a real email (not sandbox).
    # This prevents the ContactOut placeholder +123456789 from appearing.
    if not company.get("founder_number"):
        for ct in contacts_list:
            if ct.get("phone") and ct.get("name") and ct.get("email"):
                company["founder_number"] = ct["phone"]
                if not company.get("founder_name"):
                    company["founder_name"] = ct["name"]
                break

    # Update pipeline stats
    _pipeline_stats.people_companies_processed += 1
    _pipeline_stats.people_contacts_found      += result.contacts_found
    _pipeline_stats.people_emails_found        += result.emails_found
    _pipeline_stats.people_phones_found        += result.phones_found

    if result.target_reached:
        _pipeline_stats.people_target_reached += 1

    # Per-provider drill-down stats
    pdl_ps  = result.provider_stats.get("pdl")
    pro_ps  = result.provider_stats.get("prospeo")
    co_ps   = result.provider_stats.get("contactout")

    if pdl_ps and pdl_ps.called:
        _pipeline_stats.pdl_calls    += pdl_ps.api_calls
        _pipeline_stats.pdl_contacts += pdl_ps.contacts_found
        if pdl_ps.error == "auth_failed":
            _pipeline_stats.people_auth_failures += 1
        # Legacy compat fields
        _pipeline_stats.pdl_companies_searched += 1
        _pipeline_stats.pdl_contacts_found     += pdl_ps.contacts_found
        _pipeline_stats.pdl_emails_found       += pdl_ps.emails_found
        _pipeline_stats.pdl_phones_found       += pdl_ps.phones_found
        _pipeline_stats.pdl_api_calls          += pdl_ps.api_calls
        if pdl_ps.error == "auth_failed":
            _pipeline_stats.pdl_auth_failures += 1

    if pro_ps and pro_ps.called:
        _pipeline_stats.prospeo_calls    += pro_ps.api_calls
        _pipeline_stats.prospeo_contacts += pro_ps.contacts_found
        if pro_ps.error == "auth_failed":
            _pipeline_stats.people_auth_failures += 1

    if co_ps and co_ps.called:
        _pipeline_stats.contactout_calls    += co_ps.api_calls
        _pipeline_stats.contactout_contacts += co_ps.contacts_found
        if co_ps.error == "auth_failed":
            _pipeline_stats.people_auth_failures += 1

    # Hunter fallback stats
    hunter_ps = result.provider_stats.get("hunter")
    if hunter_ps and hunter_ps.called:
        _pipeline_stats.hunter_calls    += hunter_ps.api_calls or 1
        _pipeline_stats.hunter_contacts += hunter_ps.contacts_found
        if hunter_ps.error in ("auth_failed", "no_credits", "rate_limited") or (
            hunter_ps.error and not hunter_ps.error.startswith("no_result")
        ):
            _pipeline_stats.hunter_failed += 1
        elif hunter_ps.contacts_found == 0:
            _pipeline_stats.hunter_no_result += 1
        else:
            _pipeline_stats.hunter_success += 1

    if result.contacts_found == 0:
        _log("PEOPLE_ENRICH", f"{company_name!r} — No useful contacts found")
    else:
        _log(
            "PEOPLE_ENRICH",
            f"{company_name!r} — "
            f"contacts={result.contacts_found} "
            f"emails={result.emails_found} "
            f"phones={result.phones_found} "
            f"providers={result.providers_used} "
            f"target_reached={result.target_reached}",
        )

    return company


# ── Enrich one company: field-level waterfall ──────────────────────────────

async def _enrich_one_company(company: dict) -> dict:
    """
    Run the field-level enrichment waterfall for a single company.
    Only calls providers for fields that are actually missing.
    Stops early when all important fields are filled.
    """
    name = company.get("company_name", "?")

    # Identify what Google Maps gave us
    gmaps_fields = [f for f in ("company_number", "address", "website")
                    if company.get(f)]
    _log("ENRICH", f"{name}: Google Maps provided: {gmaps_fields or ['name only']}")

    # Step 1: CompanyEnrich for missing fields
    missing = _missing_fields(company)
    _log("COMPANYENRICH", f"Enriching missing fields: {missing}")
    if missing:
        company = await _enrich_via_companyenrich(company, missing)

    # Step 2: Serper for remaining missing fields
    remaining = _missing_fields(company)
    _log("SERPER", f"Remaining missing fields: {remaining}")
    if remaining:
        company = await _enrich_via_serper(company, remaining)

    # Step 3: Firecrawl for remaining missing fields (if website exists)
    still_missing = _missing_fields(company)
    _log("FIRECRAWL", f"Remaining missing fields: {still_missing}")
    if still_missing and company.get("website"):
        company = await _enrich_via_firecrawl(company, still_missing)

    # Step 4: Origami — optional decision-maker / founder enrichment layer.
    # Runs BEFORE the PDL→Prospeo→ContactOut waterfall so any contacts Origami
    # finds can complement (not duplicate) the existing people providers.
    # Silently skipped when ORIGAMI_API_KEY is not set.
    try:
        from app.services.origami_service import enrich_company_with_origami, is_configured as origami_configured
        if origami_configured():
            _pipeline_stats.origami_calls += 1
            company = await enrich_company_with_origami(company)
            # Track Origami stats
            origami_people = company.get("people") or []
            _pipeline_stats.origami_contacts_found += len(origami_people)
            _pipeline_stats.origami_emails_found   += sum(1 for p in origami_people if p.get("email"))
            if company.get("founder_status") in ("found", "found_decision_maker"):
                _pipeline_stats.origami_founders_found += 1

            # Step 4b: For Origami contacts that have a name but no email,
            # forward them to Prospeo/Hunter for email lookup.
            # This runs only when Origami found a founder/decision-maker
            # but their email wasn't returned by Origami directly.
            origami_contacts_no_email = [
                c for c in (company.get("_origami_contacts") or [])
                if c.get("name") and not c.get("email")
            ]
            if origami_contacts_no_email and company.get("domain"):
                from app.services.origami_service import _enrich_origami_founder_emails
                company = await _enrich_origami_founder_emails(company)
                # Recount emails after forwarding
                refreshed_people = company.get("people") or []
                _pipeline_stats.origami_emails_found = sum(
                    1 for p in refreshed_people if p.get("email")
                )
        else:
            _pipeline_stats.origami_skipped += 1
    except Exception as _origami_exc:
        _log("ORIGAMI", f"Origami error for {name} — {_origami_exc} (pipeline continues)")
        _pipeline_stats.origami_skipped += 1

    # Step 5: People enrichment waterfall (PDL → Prospeo → ContactOut)
    # The orchestrator handles credit control and stops early when the target
    # number of useful contacts (default 2) is reached.
    # NOTE: run BEFORE scoring so the promoted contact email is counted.
    company = await _enrich_via_people_orchestrator(company)

    # Score confidence (after people enrichment so promoted email boosts score)
    company["confidence"] = _score_confidence(company)

    return company

# ── Main pipeline entry point ──────────────────────────────────────────────

async def run_maps_pipeline(
    category: str,
    state: str,
    district: Optional[str],
    target: int,
    exclude_seen: bool = True,
) -> dict:
    """
    Full Google Maps → Enrichment → MongoDB pipeline.

    Returns a dict with:
      companies        – list of enriched company dicts ready for MongoDB upsert
      gmaps_stats      – MapLeadsStats from the discovery phase
      pipeline_stats   – per-provider call counts
      query            – reconstructed query string
    """
    global _pipeline_stats
    _pipeline_stats = _PipelineStats()
    _reset_crawl_cache()

    # Reset people-enrichment orchestrator cache at pipeline start
    try:
        from people_enrichment.orchestrator import reset_cache as _reset_people_cache
        _reset_people_cache()   # also resets PDL credits flag
    except Exception:
        pass

    t0 = time.monotonic()
    _log("PIPELINE", "Starting Google Maps discovery")
    _log("GOOGLE_MAPS", f"Target: {target}")

    # ── STEP 1: Google Maps Discovery ────────────────────────────────────────
    from google_maps.discovery import discover_businesses
    businesses, gmaps_stats = await discover_businesses(
        category=category,
        state=state,
        district=district,
        target=target,
        exclude_seen=exclude_seen,
    )

    _pipeline_stats.gmaps_discovered = len(businesses)
    _pipeline_stats.gmaps_duplicates = (
        gmaps_stats.duplicates_removed + gmaps_stats.secondary_dupes + gmaps_stats.previously_seen
    )

    _log("GOOGLE_MAPS", f"Discovered: {len(businesses)}")
    _log("GOOGLE_MAPS", f"New unique: {len(businesses)}")
    _log("GOOGLE_MAPS", f"Duplicates skipped: {_pipeline_stats.gmaps_duplicates}")

    if not businesses:
        _log("PIPELINE", "Google Maps returned 0 results — aborting pipeline")
        return {
            "companies":      [],
            "gmaps_stats":    gmaps_stats,
            "pipeline_stats": get_pipeline_stats(),
            "query":          f"{category} companies in {district or state}, India",
        }

    # ── STEP 2: Convert to pipeline dicts ────────────────────────────────────
    companies = [_maps_biz_to_company(biz) for biz in businesses]

    # Log what Google Maps gave us
    n_phone   = sum(1 for c in companies if c.get("company_number"))
    n_website = sum(1 for c in companies if c.get("website"))
    n_address = sum(1 for c in companies if c.get("address"))
    _log("ENRICH", f"Google Maps complete fields — phone:{n_phone}/{len(companies)} website:{n_website}/{len(companies)} address:{n_address}/{len(companies)}")

    all_missing = []
    for c in companies:
        all_missing.extend(_missing_fields(c))
    from collections import Counter
    missing_counts = Counter(all_missing)
    _log("ENRICH", f"Missing fields across all companies: {dict(missing_counts)}")

    # Reset CE credits flag
    from app.services.companyenrich_service import reset_credits_flag
    reset_credits_flag()

    # ── STEP 3: Field-level enrichment (concurrent, bounded) ─────────────────
    _log("PIPELINE", f"Enriching {len(companies)} companies via CompanyEnrich → Serper → Firecrawl")
    sem = asyncio.Semaphore(5)  # max 5 concurrent enrichments

    async def _bounded_enrich(c: dict) -> dict:
        async with sem:
            try:
                return await asyncio.wait_for(_enrich_one_company(c), timeout=120.0)
            except asyncio.TimeoutError:
                _log("ENRICH", f"Timeout enriching {c.get('company_name','?')}")
                return c
            except Exception as exc:
                _log("ENRICH", f"Error enriching {c.get('company_name','?')}: {exc}")
                return c

    enriched = await asyncio.gather(*[_bounded_enrich(c) for c in companies])
    companies = list(enriched)

    # ── STEP 4: Final deduplication by domain ────────────────────────────────
    seen_domains: set[str] = set()
    seen_names:   set[str] = set()
    unique: list[dict] = []
    for c in companies:
        dom  = (c.get("domain") or "").lower()
        name = (c.get("company_name") or "").lower().strip()
        if dom and dom in seen_domains:
            continue
        if dom:
            seen_domains.add(dom)
        elif name and name in seen_names:
            continue
        if name:
            seen_names.add(name)
        unique.append(c)

    _pipeline_stats.final_companies = len(unique)
    elapsed = round(time.monotonic() - t0, 1)

    # ── Final summary log ─────────────────────────────────────────────────────
    ps = get_pipeline_stats()
    n_email   = sum(1 for c in unique if c.get("email"))
    n_phone2  = sum(1 for c in unique if c.get("company_number"))
    n_addr    = sum(1 for c in unique if c.get("address"))
    n_founder = sum(1 for c in unique if c.get("founder_name"))

    _log("PIPELINE", f"Final companies: {len(unique)}")
    _log("PIPELINE", f"Google Maps discovered: {ps['google_maps_discovered']}")
    _log("PIPELINE", f"Google Maps duplicates: {ps['google_maps_duplicates']}")
    _log("PIPELINE", f"CompanyEnrich calls: {ps['companyenrich_calls']}")
    _log("PIPELINE", f"CompanyEnrich fields filled: {ps['companyenrich_fields_filled']}")
    _log("PIPELINE", f"Serper calls: {ps['serper_calls']}")
    _log("PIPELINE", f"Serper fields filled: {ps['serper_fields_filled']}")
    _log("PIPELINE", f"Firecrawl calls: {ps['firecrawl_calls']}")
    _log("PIPELINE", f"Firecrawl fields filled: {ps['firecrawl_fields_filled']}")
    _log("PIPELINE", f"Origami calls: {ps.get('origami_calls', 0)}")
    _log("PIPELINE", f"Origami contacts found: {ps.get('origami_contacts_found', 0)}")
    _log("PIPELINE", f"Origami founders found: {ps.get('origami_founders_found', 0)}")
    _log("PIPELINE", f"Origami emails found: {ps.get('origami_emails_found', 0)}")
    _log("PIPELINE", f"Origami skipped: {ps.get('origami_skipped', 0)}")
    _log("PIPELINE", f"Final valid companies: {len(unique)}")
    _log("PIPELINE", f"  emails: {n_email}/{len(unique)}")
    _log("PIPELINE", f"  phones: {n_phone2}/{len(unique)}")
    _log("PIPELINE", f"  addresses: {n_addr}/{len(unique)}")
    _log("PIPELINE", f"  founders: {n_founder}/{len(unique)}")
    n_contacts   = sum(1 for c in unique if c.get("contacts"))
    n_co_email   = sum(
        sum(1 for ct in c.get("contacts", []) if ct.get("email"))
        for c in unique
    )
    n_co_phone   = sum(
        sum(1 for ct in c.get("contacts", []) if ct.get("phone"))
        for c in unique
    )
    _log("PEOPLE_ENRICH", f"  companies with contacts:   {n_contacts}/{len(unique)}")
    _log("PEOPLE_ENRICH", f"  total contacts found:      {ps['people_contacts_found']}")
    _log("PEOPLE_ENRICH", f"  contacts with email:       {n_co_email}")
    _log("PEOPLE_ENRICH", f"  contacts with phone:       {n_co_phone}")
    _log("PEOPLE_ENRICH", f"  target reached (companies):{ps['people_target_reached']}")
    _log("PEOPLE_ENRICH", f"  PDL calls:                 {ps['pdl_calls']}")
    _log("PEOPLE_ENRICH", f"  Prospeo calls:             {ps['prospeo_calls']}")
    _log("PEOPLE_ENRICH", f"  ContactOut calls:          {ps['contactout_calls']}")
    _log("PEOPLE_ENRICH", f"  auth failures:             {ps['people_auth_failures']}")
    _log("PEOPLE_ENRICH", (
        f"  Hunter: calls={ps['hunter_calls']} "
        f"success={ps['hunter_success']} "
        f"no_result={ps['hunter_no_result']} "
        f"failed={ps['hunter_failed']} "
        f"contacts={ps['hunter_contacts']}"
    ))
    _log("PIPELINE", f"Total elapsed: {elapsed}s")

    # ── API Contribution Report ───────────────────────────────────────────────
    # Printed immediately after the pipeline summary. READ-ONLY — does not
    # modify any company dict or pipeline state. API keys are never logged.
    try:
        from app.services.api_contribution_logger import print_contribution_report
        print_contribution_report(unique, ps)
    except Exception as _cr_exc:
        _log("PIPELINE", f"API contribution report error (non-fatal): {_cr_exc}")

    return {
        "companies":      unique,
        "gmaps_stats":    gmaps_stats,
        "pipeline_stats": ps,
        "query":          f"{category} companies in {district or state}, India",
    }
