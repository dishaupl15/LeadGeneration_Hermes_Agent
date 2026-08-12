"""
prospeo/contact_mapper.py
──────────────────────────
Maps raw Prospeo person objects → normalised ProspeoContact dicts.

Responsibilities:
  - Classify role from current_job_title / job_history
  - Score confidence (company match + role priority + email verified)
  - Extract email and mobile from enriched person objects ONLY
    (never from un-enriched search results — those never contain real values)
  - Validate email format and reject junk addresses
  - Reject noise / irrelevant titles

ZERO imports from outside prospeo/.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Role priority table ───────────────────────────────────────────────────────
# (order = priority: lower index = higher priority)
_ROLE_RULES: list[tuple[list[str], str]] = [
    # co-founder must come before founder so "co-founder" doesn't match founder
    (["co-founder", "cofounder", "co founder"],               "co_founder"),
    (["founder"],                                              "founder"),
    (["owner", "proprietor"],                                  "owner"),
    (["chief executive", "ceo"],                               "ceo"),
    (["managing director", " md "],                            "managing_director"),
    (["coo", "chief operating"],                               "coo"),
    (["chairman", "chairperson", "president"],                 "ceo"),
    (["director"],                                             "director"),
    (["head of hr", "head hr", "head of human",
      "vp hr", "vp of hr", "chief human", "chro"],            "hr"),
    # hr_manager must come before the broad "human resources" / " hr " rules
    (["hr manager", "human resources manager"],                "hr_manager"),
    (["human resources", " hr ", "hrd"],                       "hr"),
    (["head of talent", "talent acquisition head",
      "talent acquisition director", "vp talent"],             "talent_acquisition"),
    # talent_acquisition_manager before the shorter talent_acquisition
    (["talent acquisition manager"],                           "talent_acquisition_manager"),
    (["talent acquisition", "talent partner"],                 "talent_acquisition"),
    (["recruitment manager", "head of recruitment",
      "recruitment director"],                                 "recruitment"),
    (["recruiter", "recruiting", "recruitment"],               "recruitment"),
]

ROLE_PRIORITY: dict[str, int] = {
    "founder":                    0,
    "co_founder":                 1,
    "owner":                      2,
    "ceo":                        3,
    "managing_director":          4,
    "coo":                        5,
    "director":                   6,
    "hr":                         7,
    "talent_acquisition":         8,
    "recruitment":                9,
    "hr_manager":                10,
    "talent_acquisition_manager":11,
    "other":                     99,
}

# Titles we always reject (not relevant decision-makers)
_NOISE_TITLES: frozenset[str] = frozenset({
    "intern", "trainee", "fresher", "student", "apprentice",
    "sales executive", "marketing executive", "software engineer",
    "developer", "programmer", "data scientist", "data analyst",
    "accountant", "finance analyst", "auditor",
    "admin", "receptionist", "secretary",
    "operations executive", "business analyst",
})

# Seniority labels returned by Prospeo that are always welcome.
# These are the VALID API values (confirmed by live probe).
# NOTE: "VP" is NOT valid — Prospeo returns HTTP 400 INVALID_FILTERS for it.
#       The valid value is "Vice President".
_WANTED_SENIORITIES: frozenset[str] = frozenset({
    "Founder/Owner", "C-Suite", "Vice President", "Director",
    "Head", "Partner", "Manager", "Senior",
})

# Email locals we always reject
_JUNK_EMAIL_LOCALS: frozenset[str] = frozenset({
    "noreply", "no-reply", "donotreply", "webmaster", "abuse",
    "postmaster", "spam", "admin", "test", "example",
    "info", "contact", "support", "sales", "enquiry",
    "enquiries", "hello", "office", "careers",
})

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


# ── Role classification ───────────────────────────────────────────────────────

def classify_role(title: str) -> str:
    """Return a role key for the given job title string."""
    if not title:
        return "other"
    tl = f" {title.lower().strip()} "
    for keywords, role in _ROLE_RULES:
        for kw in keywords:
            if kw in tl:
                return role
    return "other"


def is_relevant_title(title: str, seniority: str | None = None) -> bool:
    """
    Return True if this person is a relevant decision-maker.
    Fast-reject noise titles; accept by seniority or role classification.
    """
    if not title:
        return False
    tl = title.lower().strip()

    for noise in _NOISE_TITLES:
        if noise in tl:
            return False

    # Accept if Prospeo assigned a wanted seniority
    if seniority and seniority in _WANTED_SENIORITIES:
        return True

    role = classify_role(title)
    if role != "other":
        return True

    # Accept director unless it's "non-executive" / "independent"
    if "director" in tl and "non-executive" not in tl and "independent" not in tl:
        return True

    return False


# ── Email helpers ─────────────────────────────────────────────────────────────

def _is_valid_email(email: str) -> bool:
    if not email:
        return False
    addr = email.lower().strip()
    if not _EMAIL_RE.match(addr):
        return False
    local, _, dom = addr.partition("@")
    if not dom or "." not in dom:
        return False
    if local in _JUNK_EMAIL_LOCALS:
        return False
    if dom in ("example.com", "test.com", "dummy.com", "null.com"):
        return False
    return True


def extract_email(person: dict) -> Optional[str]:
    """
    Extract email from an ENRICHED Prospeo person object.
    Returns None when not revealed or invalid.
    Never fabricates.
    """
    email_obj = person.get("email") or {}
    if not isinstance(email_obj, dict):
        return None
    if not email_obj.get("revealed"):
        return None
    addr = (email_obj.get("email") or "").strip().lower()
    return addr if _is_valid_email(addr) else None


def extract_mobile(person: dict) -> Optional[str]:
    """
    Extract mobile from an ENRICHED Prospeo person object.
    Returns E.164 string or None.
    Never fabricates — only returns when revealed=True.
    """
    mob_obj = person.get("mobile") or {}
    if not isinstance(mob_obj, dict):
        return None
    if not mob_obj.get("revealed"):
        return None
    # Prefer the clean E.164 number
    number = (mob_obj.get("mobile") or "").strip()
    if not number:
        number = (mob_obj.get("mobile_international") or "").strip()
    return number or None


def extract_linkedin(person: dict) -> Optional[str]:
    url = (person.get("linkedin_url") or "").strip()
    return url or None


# ── Company match ─────────────────────────────────────────────────────────────

def company_matches(
    person: dict,
    company_obj: dict | None,
    target_domain: str,
    target_name: str,
) -> tuple[bool, float]:
    """
    Check whether this Prospeo person is currently employed at the target company.

    Uses:
      1. Prospeo's company.website  (strongest — exact domain match)
      2. Prospeo's company.name     (fuzzy name overlap)
      3. person.job_history current entry as fallback

    Returns (matches: bool, strength: float 0.0–1.0)
    """
    target_domain = (target_domain or "").lower().strip().lstrip("www.").rstrip("/")
    target_name   = (target_name or "").lower().strip()

    def _domain_of(url: str) -> str:
        url = (url or "").lower().strip()
        # strip scheme
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
        return url.lstrip("www.").split("/")[0].strip()

    def _name_overlap(a: str, b: str) -> float:
        _noise = {"pvt", "ltd", "limited", "inc", "corp", "the", "group",
                  "private", "and", "&", "co", "company"}
        wa = set(a.lower().split()) - _noise
        wb = set(b.lower().split()) - _noise
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / max(len(wa), 1)

    # ── Try company object from Prospeo ──────────────────────────────────────
    if company_obj and isinstance(company_obj, dict):
        comp_website = company_obj.get("website") or ""
        comp_name    = (company_obj.get("name") or "").lower().strip()

        if target_domain and comp_website:
            cd = _domain_of(comp_website)
            if cd and (cd == target_domain or cd.endswith("." + target_domain)):
                return True, 1.0

        if target_name and comp_name:
            overlap = _name_overlap(target_name, comp_name)
            if overlap >= 0.50:
                return True, min(0.55 + overlap * 0.4, 0.95)

    # ── Try job_history current entry ─────────────────────────────────────────
    for job in (person.get("job_history") or []):
        if not job.get("current"):
            continue
        jname = (job.get("company_name") or "").lower().strip()
        if target_name and jname:
            overlap = _name_overlap(target_name, jname)
            if overlap >= 0.50:
                return True, min(0.45 + overlap * 0.35, 0.85)

    return False, 0.0


# ── Confidence scoring ────────────────────────────────────────────────────────

def compute_confidence(
    person: dict,
    company_obj: dict | None,
    target_domain: str,
    target_name: str,
    has_email: bool,
) -> float:
    """Score 0.0–0.98 for this contact's quality."""
    matches, strength = company_matches(person, company_obj, target_domain, target_name)
    if not matches:
        return 0.0

    score = strength * 0.40  # company match (max 0.40)

    # Role score (max 0.28)
    title = (person.get("current_job_title") or "").strip()
    role  = classify_role(title)
    _role_score = {
        "founder":                    0.28,
        "co_founder":                 0.28,
        "owner":                      0.25,
        "ceo":                        0.23,
        "managing_director":          0.22,
        "coo":                        0.18,
        "director":                   0.16,
        "hr":                         0.13,
        "talent_acquisition":         0.11,
        "recruitment":                0.09,
        "hr_manager":                 0.08,
        "talent_acquisition_manager": 0.07,
        "other":                      0.03,
    }
    score += _role_score.get(role, 0.03)

    # Email availability (max 0.20)
    if has_email:
        score += 0.20

    # Verified-email bonus (max 0.10)
    email_obj = person.get("email") or {}
    if isinstance(email_obj, dict) and email_obj.get("status") == "VERIFIED":
        score += 0.10

    return round(min(score, 0.98), 3)


# ── Main mapper ───────────────────────────────────────────────────────────────

def map_search_result(
    result: dict,
    target_domain: str,
    target_name: str,
) -> Optional[dict]:
    """
    Map a single Prospeo /search-person result (no email/mobile revealed yet)
    to a candidate dict that includes the person_id and role metadata.

    Returns None if the person is not relevant or doesn't match the company.
    """
    person     = result.get("person") or {}
    company    = result.get("company")
    title      = (person.get("current_job_title") or "").strip()

    # Derive seniority from the current job entry
    current_seniority: Optional[str] = None
    current_job_key = person.get("current_job_key")
    for job in (person.get("job_history") or []):
        if job.get("current") and (
            current_job_key is None or job.get("job_key") == current_job_key
        ):
            current_seniority = job.get("seniority")
            break

    if not is_relevant_title(title, current_seniority):
        return None

    matches, strength = company_matches(person, company, target_domain, target_name)
    if not matches:
        return None

    person_id = person.get("person_id") or ""
    if not person_id:
        return None

    full_name = (
        person.get("full_name")
        or f"{person.get('first_name','').strip()} {person.get('last_name','').strip()}".strip()
        or None
    )
    if not full_name:
        return None

    role = classify_role(title)

    return {
        "person_id":        person_id,
        "name":             full_name,
        "title":            title,
        "role":             role,
        "linkedin_url":     extract_linkedin(person),
        "match_strength":   strength,
        # email/mobile not available from search — will be filled after bulk enrich
        "email":            None,
        "phone":            None,
        "confidence":       0.0,   # recalculated after enrichment
        "_raw_person":      person,
        "_raw_company":     company,
    }


def map_enriched_result(
    candidate: dict,
    enriched_person: dict,
    enriched_company: dict | None,
    target_domain: str,
    target_name: str,
) -> dict:
    """
    Merge enriched email / mobile into a candidate dict and recompute confidence.
    """
    email  = extract_email(enriched_person)
    mobile = extract_mobile(enriched_person)

    # LinkedIn may be richer after enrichment
    linkedin = extract_linkedin(enriched_person) or candidate.get("linkedin_url")

    conf = compute_confidence(
        enriched_person,
        enriched_company or candidate.get("_raw_company"),
        target_domain,
        target_name,
        has_email=bool(email),
    )

    return {
        "name":        candidate["name"],
        "title":       candidate["title"],
        "role":        candidate["role"],
        "email":       email,
        "phone":       mobile,
        "linkedin_url": linkedin,
        "source":      "prospeo",
        "confidence":  conf,
    }
