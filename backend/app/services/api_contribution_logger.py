"""
app/services/api_contribution_logger.py
─────────────────────────────────────────
Detailed API contribution logging for every lead-generation run.

Purpose
───────
After the pipeline finishes, analyse the `_field_verification` and
`contacts` data already attached to each company dict and print a
structured report showing exactly what each API contributed.

Contract
────────
  - READ-ONLY: this module never modifies any company dict or pipeline state.
  - Safe to call from run_maps_pipeline() after the final companies list is
    ready — no timing or ordering requirements.
  - API keys are NEVER read, printed, or logged here.

Tracked APIs (in report order)
──────────────────────────────
  Google Maps   — phone, address from discovery; counts come from _field_verification
  CompanyEnrich — email, phone, address, founder via /companies/enrich + /people/search
  Serper        — email, phone, address, founder via snippet extraction
  Firecrawl     — email, phone, address, founder via website crawl
  PDL           — contacts (email, phone) via person/search
  Prospeo       — contacts (email, phone) via people_search
  ContactOut    — contacts (email, phone) via people_search
  Hunter        — email via domain-search
  Origami       — contacts, founder, email via Origami API

Report sections
───────────────
  [API NAME]
  Calls:    X   — API calls made (from _pipeline_stats)
  Success:  X   — calls that returned at least one useful data point
  Failed:   X   — calls that returned nothing useful or errored
  Emails added:    X  — leads where this API was FIRST to fill email
  Phones added:    X  — leads where this API was FIRST to fill company_number
  Founders added:  X  — leads where this API was FIRST to fill founder_name
  Addresses added: X  — leads where this API was FIRST to fill address
  Companies added: X  — leads where this API was the discovery source
  Contacts added:  X  — leads where this API added contacts[] entries

  ========== API CONTRIBUTION REPORT ==========
  (one line per API)

  ========== FINAL COVERAGE ==========
  N leads
  Emails:    X/N
  Phones:    X/N
  Founders:  X/N
  Addresses: X/N
  Contacts:  X/N

  Also shows which API contributed THE MOST of each field type.

Usage
─────
  from app.services.api_contribution_logger import print_contribution_report
  print_contribution_report(companies, pipeline_stats)

The call is non-blocking, synchronous, and safe to run in any context.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional


# ── Source-name normalisation map ─────────────────────────────────────────────
# Maps the raw "source" strings stored in _field_verification to our canonical
# API names used in the report.  Substrings are checked — order matters (more
# specific first).

_SOURCE_MAP: list[tuple[str, str]] = [
    ("google_maps",     "Google Maps"),
    ("googlemaps",      "Google Maps"),
    ("gmaps",           "Google Maps"),
    ("companyenrich",   "CompanyEnrich"),
    ("serper",          "Serper"),
    ("firecrawl",       "Firecrawl"),
    ("pdl",             "PDL"),
    ("people_data_lab", "PDL"),
    ("prospeo",         "Prospeo"),
    ("contactout",      "ContactOut"),
    ("hunter",          "Hunter"),
    ("origami",         "Origami"),
    # Compound / email-forward paths
    ("email_lookup",    "Hunter"),   # origami → hunter email forward
    ("people_enrichment_hunter",   "Hunter"),
    ("people_enrichment_prospeo",  "Prospeo"),
    ("people_enrichment_pdl",      "PDL"),
    ("people_enrichment_contactout", "ContactOut"),
    ("people_enrichment",          "PDL"),    # generic people_enrichment → credit PDL first
]

_ALL_APIS: list[str] = [
    "Google Maps",
    "CompanyEnrich",
    "Serper",
    "Firecrawl",
    "PDL",
    "Prospeo",
    "ContactOut",
    "Hunter",
    "Origami",
]


def _normalise_source(source_raw: str) -> Optional[str]:
    """
    Convert a raw source string from _field_verification to a canonical API name.
    Returns None if the source cannot be mapped to a known API.
    """
    if not source_raw:
        return None
    sl = source_raw.lower().strip()
    for key, canonical in _SOURCE_MAP:
        if key in sl:
            return canonical
    return None


def _source_from_fv(fv_entry: dict) -> Optional[str]:
    """
    Extract and normalise the source from a single _field_verification entry.
    Tries both the 'source' key and the 'status' key (which often encodes source).
    """
    if not isinstance(fv_entry, dict):
        return None
    # Try explicit 'source' first
    raw = fv_entry.get("source") or ""
    canonical = _normalise_source(raw)
    if canonical:
        return canonical
    # Fallback: parse source from 'status' string (e.g. "companyenrich_email")
    raw = fv_entry.get("status") or ""
    return _normalise_source(raw)


# ── Per-company field attribution ─────────────────────────────────────────────

def _attributions_for_company(company: dict) -> dict[str, Optional[str]]:
    """
    Return a mapping of {field: api_name} for the fields that were ACTUALLY FILLED
    for this company, where api_name is whichever API first contributed that field.

    Fields tracked: email, company_number (phone), founder_name, address
    """
    fv = company.get("_field_verification") or {}

    attr: dict[str, Optional[str]] = {
        "email":          None,
        "phone":          None,
        "founder":        None,
        "address":        None,
    }

    # email
    if company.get("email"):
        e_fv = fv.get("email") or {}
        attr["email"] = _source_from_fv(e_fv)
        # Fallback: check research_source / contacts
        if not attr["email"]:
            attr["email"] = _research_source_to_api(company.get("research_source", ""))

    # phone / company_number
    if company.get("company_number"):
        p_fv = fv.get("phone") or {}
        attr["phone"] = _source_from_fv(p_fv)
        if not attr["phone"]:
            attr["phone"] = _research_source_to_api(company.get("research_source", ""))

    # founder
    if company.get("founder_name"):
        f_fv = fv.get("founder") or {}
        attr["founder"] = _source_from_fv(f_fv)
        if not attr["founder"]:
            attr["founder"] = _research_source_to_api(company.get("research_source", ""))

    # address
    if company.get("address"):
        a_fv = fv.get("address") or {}
        attr["address"] = _source_from_fv(a_fv)
        if not attr["address"]:
            # Google Maps is authoritative for address when _gmaps_source is set
            if company.get("_gmaps_source"):
                attr["address"] = "Google Maps"
            else:
                attr["address"] = _research_source_to_api(company.get("research_source", ""))

    return attr


def _research_source_to_api(research_source: str) -> Optional[str]:
    """Map company-level research_source string to a canonical API name."""
    return _normalise_source(research_source or "")


def _contacts_by_source(company: dict) -> dict[str, int]:
    """
    Return {api_name: count} of contacts[] entries attributed to each API.
    A contact may have multiple sources (merged) — credit all of them.
    """
    counts: dict[str, int] = {}
    for ct in (company.get("contacts") or []):
        srcs = ct.get("sources") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        credited: set[str] = set()
        for s in srcs:
            api = _normalise_source(s)
            if api and api not in credited:
                counts[api] = counts.get(api, 0) + 1
                credited.add(api)
    return counts


def _discovery_source(company: dict) -> Optional[str]:
    """
    Return the canonical API name for whichever API discovered this company.
    Google Maps pipeline sets _gmaps_source=True; Hermes sets research_source='hermes'.
    """
    if company.get("_gmaps_source"):
        return "Google Maps"
    rs = company.get("research_source") or ""
    return _normalise_source(rs)


# ── Call count extraction from pipeline_stats ─────────────────────────────────

def _extract_call_counts(pipeline_stats: dict) -> dict[str, dict[str, int]]:
    """
    Build a per-API {calls, success, failed} dict from pipeline_stats.

    pipeline_stats keys are those returned by get_pipeline_stats() in
    maps_pipeline_service.py.
    """
    ps = pipeline_stats or {}

    def _safe(key: str, default: int = 0) -> int:
        return int(ps.get(key, default) or default)

    # Google Maps
    gmaps_calls   = _safe("google_maps_discovered") + _safe("google_maps_duplicates")
    gmaps_success = _safe("google_maps_discovered")
    gmaps_failed  = _safe("google_maps_duplicates")

    # CompanyEnrich  (calls = number of companies where CE was invoked)
    ce_calls   = _safe("companyenrich_calls")
    ce_success = _safe("companyenrich_fields_filled")   # approximate: fields filled ≠ call success
    ce_success = min(ce_success, ce_calls)              # cap at calls
    ce_failed  = max(0, ce_calls - ce_success)

    # Serper
    ser_calls   = _safe("serper_calls")
    ser_success = _safe("serper_fields_filled")
    ser_success = min(ser_success, ser_calls)
    ser_failed  = max(0, ser_calls - ser_success)

    # Firecrawl
    fc_calls   = _safe("firecrawl_calls")
    fc_success = _safe("firecrawl_fields_filled")
    fc_success = min(fc_success, fc_calls)
    fc_failed  = max(0, fc_calls - fc_success)

    # PDL
    pdl_calls   = _safe("pdl_calls")
    pdl_contacts= _safe("pdl_contacts")
    pdl_success = pdl_contacts                       # each contact returned = success
    pdl_failed  = max(0, pdl_calls - pdl_success) if pdl_calls > 0 else 0

    # Prospeo
    pro_calls   = _safe("prospeo_calls")
    pro_contacts= _safe("prospeo_contacts")
    pro_success = pro_contacts
    pro_failed  = max(0, pro_calls - pro_success) if pro_calls > 0 else 0

    # ContactOut
    co_calls    = _safe("contactout_calls")
    co_contacts = _safe("contactout_contacts")
    co_success  = co_contacts
    co_failed   = max(0, co_calls - co_success) if co_calls > 0 else 0

    # Hunter
    h_calls   = _safe("hunter_calls")
    h_success = _safe("hunter_success")
    h_failed  = _safe("hunter_failed")
    if h_calls == 0:
        h_success = h_failed = 0

    # Origami
    ori_calls   = _safe("origami_calls")
    ori_contacts= _safe("origami_contacts_found")
    ori_success = 1 if ori_contacts > 0 else 0        # not per-call success
    ori_failed  = max(0, ori_calls - ori_success) if ori_calls > 0 else 0

    return {
        "Google Maps":    {"calls": gmaps_calls,  "success": gmaps_success,  "failed": gmaps_failed},
        "CompanyEnrich":  {"calls": ce_calls,     "success": ce_success,     "failed": ce_failed},
        "Serper":         {"calls": ser_calls,    "success": ser_success,    "failed": ser_failed},
        "Firecrawl":      {"calls": fc_calls,     "success": fc_success,     "failed": fc_failed},
        "PDL":            {"calls": pdl_calls,    "success": pdl_success,    "failed": pdl_failed},
        "Prospeo":        {"calls": pro_calls,    "success": pro_success,    "failed": pro_failed},
        "ContactOut":     {"calls": co_calls,     "success": co_success,     "failed": co_failed},
        "Hunter":         {"calls": h_calls,      "success": h_success,      "failed": h_failed},
        "Origami":        {"calls": ori_calls,    "success": ori_success,    "failed": ori_failed},
    }


# ── Main report builder ────────────────────────────────────────────────────────

def build_contribution_report(
    companies: list[dict],
    pipeline_stats: dict,
) -> dict:
    """
    Analyse every company dict to determine which API first filled each field.

    Returns a structured report dict — see print_contribution_report() for
    the formatted output.

    This function is READ-ONLY and has no side effects.
    """
    n = len(companies)

    # ── Per-API field contribution counters ───────────────────────────────────
    # emails_added[api]    = count of companies where api was FIRST to fill email
    # phones_added[api]    = count of companies where api was FIRST to fill phone
    # founders_added[api]  = count of companies where api was FIRST to fill founder
    # addresses_added[api] = count of companies where api was FIRST to fill address
    # companies_added[api] = count of companies discovered by this api
    # contacts_added[api]  = total contact records attributed to this api

    emails_added:    dict[str, int] = {a: 0 for a in _ALL_APIS}
    phones_added:    dict[str, int] = {a: 0 for a in _ALL_APIS}
    founders_added:  dict[str, int] = {a: 0 for a in _ALL_APIS}
    addresses_added: dict[str, int] = {a: 0 for a in _ALL_APIS}
    companies_added: dict[str, int] = {a: 0 for a in _ALL_APIS}
    contacts_added:  dict[str, int] = {a: 0 for a in _ALL_APIS}

    # ── Final coverage counters ───────────────────────────────────────────────
    total_email   = 0
    total_phone   = 0
    total_founder = 0
    total_address = 0
    total_contacts = 0

    for company in companies:
        attr = _attributions_for_company(company)

        # Email
        if company.get("email"):
            total_email += 1
            api = attr.get("email")
            if api and api in emails_added:
                emails_added[api] += 1

        # Phone
        if company.get("company_number"):
            total_phone += 1
            api = attr.get("phone")
            if api and api in phones_added:
                phones_added[api] += 1

        # Founder
        if company.get("founder_name"):
            total_founder += 1
            api = attr.get("founder")
            if api and api in founders_added:
                founders_added[api] += 1

        # Address
        if company.get("address"):
            total_address += 1
            api = attr.get("address")
            if api and api in addresses_added:
                addresses_added[api] += 1

        # Discovery source (company)
        disc = _discovery_source(company)
        if disc and disc in companies_added:
            companies_added[disc] += 1

        # Contacts
        ct_by_source = _contacts_by_source(company)
        if ct_by_source:
            total_contacts += sum(ct_by_source.values())
            for api, cnt in ct_by_source.items():
                if api in contacts_added:
                    contacts_added[api] += cnt

    # ── Call counts ───────────────────────────────────────────────────────────
    call_counts = _extract_call_counts(pipeline_stats)

    # ── "Most" winners ────────────────────────────────────────────────────────
    def _winner(counter: dict[str, int]) -> tuple[str, int]:
        best_api  = max(counter, key=lambda a: counter[a], default="N/A")
        best_val  = counter.get(best_api, 0)
        if best_val == 0:
            return "N/A", 0
        return best_api, best_val

    top_email,   top_email_n   = _winner(emails_added)
    top_phone,   top_phone_n   = _winner(phones_added)
    top_founder, top_founder_n = _winner(founders_added)
    top_contact, top_contact_n = _winner(contacts_added)

    return {
        "total_leads":      n,
        "total_email":      total_email,
        "total_phone":      total_phone,
        "total_founder":    total_founder,
        "total_address":    total_address,
        "total_contacts":   total_contacts,
        "call_counts":      call_counts,
        "emails_added":     emails_added,
        "phones_added":     phones_added,
        "founders_added":   founders_added,
        "addresses_added":  addresses_added,
        "companies_added":  companies_added,
        "contacts_added":   contacts_added,
        "top_email":        (top_email,   top_email_n),
        "top_phone":        (top_phone,   top_phone_n),
        "top_founder":      (top_founder, top_founder_n),
        "top_contact":      (top_contact, top_contact_n),
    }


def print_contribution_report(
    companies: list[dict],
    pipeline_stats: dict,
) -> None:
    """
    Build and print the full API contribution report to stdout.

    Call this AFTER the pipeline finishes building the final companies list.
    pipeline_stats is the dict returned by get_pipeline_stats() in
    maps_pipeline_service.py.

    This function NEVER logs API keys, passwords, or sensitive credentials.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    report = build_contribution_report(companies, pipeline_stats)

    n          = report["total_leads"]
    call_counts = report["call_counts"]

    lines: list[str] = [""]
    lines.append(f"[{ts}] ========== API CONTRIBUTION REPORT ==========")
    lines.append("")

    for api in _ALL_APIS:
        cc = call_counts.get(api, {"calls": 0, "success": 0, "failed": 0})
        e  = report["emails_added"].get(api, 0)
        p  = report["phones_added"].get(api, 0)
        f  = report["founders_added"].get(api, 0)
        a  = report["addresses_added"].get(api, 0)
        co = report["companies_added"].get(api, 0)
        ct = report["contacts_added"].get(api, 0)

        lines.append(f"[{ts}] [{api}]")
        lines.append(f"[{ts}]   Calls:            {cc['calls']}")
        lines.append(f"[{ts}]   Success:          {cc['success']}")
        lines.append(f"[{ts}]   Failed:           {cc['failed']}")
        lines.append(f"[{ts}]   Emails added:     {e}")
        lines.append(f"[{ts}]   Phones added:     {p}")
        lines.append(f"[{ts}]   Founders added:   {f}")
        lines.append(f"[{ts}]   Addresses added:  {a}")
        lines.append(f"[{ts}]   Companies added:  {co}")
        lines.append(f"[{ts}]   Contacts added:   {ct}")
        lines.append("")

    # ── Compact summary line ──────────────────────────────────────────────────
    lines.append(f"[{ts}] ─── Compact Summary ───")
    lines.append(
        f"[{ts}]   {'API':<16} "
        f"{'Calls':>6}  {'Success':>7}  {'Failed':>6}  "
        f"{'Emails':>7}  {'Phones':>7}  {'Founders':>9}  {'Addresses':>10}  {'Contacts':>9}"
    )
    lines.append(f"[{ts}]   " + "─" * 95)
    for api in _ALL_APIS:
        cc = call_counts.get(api, {"calls": 0, "success": 0, "failed": 0})
        e  = report["emails_added"].get(api, 0)
        p  = report["phones_added"].get(api, 0)
        f  = report["founders_added"].get(api, 0)
        a  = report["addresses_added"].get(api, 0)
        ct = report["contacts_added"].get(api, 0)
        lines.append(
            f"[{ts}]   {api:<16} "
            f"{cc['calls']:>6}  {cc['success']:>7}  {cc['failed']:>6}  "
            f"{e:>7}  {p:>7}  {f:>9}  {a:>10}  {ct:>9}"
        )
    lines.append("")

    # ── Final coverage ────────────────────────────────────────────────────────
    lines.append(f"[{ts}] ========== FINAL COVERAGE ==========")
    lines.append(f"[{ts}]   {n} leads")
    lines.append(f"[{ts}]   Emails:    {report['total_email']}/{n}")
    lines.append(f"[{ts}]   Phones:    {report['total_phone']}/{n}")
    lines.append(f"[{ts}]   Founders:  {report['total_founder']}/{n}")
    lines.append(f"[{ts}]   Addresses: {report['total_address']}/{n}")
    lines.append(f"[{ts}]   Contacts:  {report['total_contacts']} total across {n} leads")
    lines.append("")

    # ── Top contributors ──────────────────────────────────────────────────────
    top_e,  top_e_n  = report["top_email"]
    top_p,  top_p_n  = report["top_phone"]
    top_f,  top_f_n  = report["top_founder"]
    top_ct, top_ct_n = report["top_contact"]

    lines.append(f"[{ts}]   Most emails contributed:    {top_e}  ({top_e_n})")
    lines.append(f"[{ts}]   Most phones contributed:    {top_p}  ({top_p_n})")
    lines.append(f"[{ts}]   Most founders contributed:  {top_f}  ({top_f_n})")
    lines.append(f"[{ts}]   Most contacts contributed:  {top_ct}  ({top_ct_n})")
    lines.append(f"[{ts}] =============================================")
    lines.append("")

    # Print all at once (avoids interleaving with async log output)
    print("\n".join(lines), flush=True)
