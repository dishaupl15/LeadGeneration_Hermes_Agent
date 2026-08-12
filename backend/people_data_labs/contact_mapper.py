"""
people_data_labs/contact_mapper.py
────────────────────────────────────
Maps raw PDL person records to clean PeopleDataLabsContact dicts.

Responsibilities:
  - Extract name, title, email, LinkedIn from PDL person dict
  - Classify the role into a standard email_type
  - Score confidence based on company match quality, role, email presence
  - Validate and normalise emails (reject junk/pattern-generated addresses)
  - Deduplicate by email

This module has ZERO imports from outside people_data_labs/.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Role classification ───────────────────────────────────────────────────────
# Maps title keywords → email_type string.
# Ordered so the FIRST match wins (highest-priority roles listed first).

_ROLE_RULES: list[tuple[list[str], str]] = [
    (["founder", "co-founder", "cofounder", "co founder"],     "founder"),
    (["co-founder", "cofounder"],                               "co_founder"),
    (["owner", "proprietor", "promoter"],                       "owner"),
    (["chief executive", "ceo"],                                "ceo"),
    (["managing director", " md "],                             "managing_director"),
    (["chairman", "chairperson"],                               "ceo"),          # treat as top-level
    (["president"],                                             "ceo"),
    (["director"],                                              "director"),
    (["head of hr", "head hr", "head of human resource",
      "vp hr", "vp of hr", "chief human", "chro"],             "hr"),
    (["human resources", " hr ", "hrd"],                       "hr"),
    (["talent acquisition manager", "talent acquisition lead",
      "head of talent", "vp talent"],                           "talent_acquisition"),
    (["talent acquisition", "talent partner"],                  "talent_acquisition"),
    (["recruitment manager", "head of recruitment",
      "vp recruitment"],                                        "recruitment"),
    (["recruiter", "recruiting", "recruitment"],                "recruitment"),
]

# Titles that make a person NOT a relevant decision-maker
_NOISE_TITLES: frozenset[str] = frozenset({
    "intern", "trainee", "fresher", "student", "apprentice",
    "sales executive", "marketing executive", "software engineer",
    "developer", "programmer", "data scientist", "data analyst",
    "accountant", "accountancy", "finance analyst", "auditor",
    "admin", "receptionist", "secretary",
    "operations executive", "business analyst",
})

# PDL job_title_levels that indicate decision-maker seniority
_PRIORITY_LEVELS: frozenset[str] = frozenset({
    "founder", "c_suite", "owner", "partner", "vp", "director",
})

# Junk email prefixes — always reject these
_JUNK_EMAIL_LOCALS: frozenset[str] = frozenset({
    "noreply", "no-reply", "donotreply", "webmaster", "abuse",
    "postmaster", "spam", "admin", "test", "example",
    "info", "contact", "support", "sales", "enquiry",
    "enquiries", "hello", "office", "careers",
})

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


# ── Helpers ───────────────────────────────────────────────────────────────────

def classify_role(title: str) -> str:
    """Return the email_type string for the given job title."""
    if not title:
        return "other"
    tl = f" {title.lower().strip()} "
    for keywords, role in _ROLE_RULES:
        for kw in keywords:
            if kw in tl:
                return role
    return "other"


def is_relevant_contact(title: str, levels: list[str] | None = None) -> bool:
    """
    Return True if this person is a relevant business decision-maker.
    Rejects noise titles (interns, junior devs, etc.).
    """
    if not title:
        return False
    tl = title.lower().strip()

    # Fast reject by noise title
    for noise in _NOISE_TITLES:
        if noise in tl:
            return False

    # Accept if PDL level indicates seniority
    if levels:
        for lvl in levels:
            if lvl in _PRIORITY_LEVELS:
                return True

    # Accept by role classification
    role = classify_role(title)
    if role != "other":
        return True

    # Accept "director" if not preceded by "non-executive"
    if "director" in tl and "non-executive" not in tl and "independent" not in tl:
        return True

    return False


def _is_valid_email(email: str, domain: Optional[str] = None) -> bool:
    """Return True if the email looks like a real professional address."""
    if not email:
        return False
    addr = email.lower().strip()
    if not _EMAIL_RE.match(addr):
        return False
    local, _, dom = addr.partition("@")
    if not dom or "." not in dom:
        return False
    # Reject junk locals
    if local in _JUNK_EMAIL_LOCALS:
        return False
    # Reject obvious placeholder domains
    if dom in ("example.com", "test.com", "dummy.com", "null.com"):
        return False
    return True


def _extract_linkedin(person: dict) -> Optional[str]:
    """Extract the cleanest LinkedIn URL from a PDL person record."""
    # profiles[] is the canonical place
    for profile in (person.get("profiles") or []):
        network = (profile.get("network") or "").lower()
        url = (profile.get("url") or "").strip()
        if network == "linkedin" and url:
            return url
    # Fallback: linkedin_url top-level field (older PDL format)
    url = (person.get("linkedin_url") or "").strip()
    return url or None


def _extract_email(person: dict) -> Optional[str]:
    """
    Extract a professional email from a PDL person record.
    Returns None if PDL did not provide one — NEVER fabricates.
    """
    # Primary: work_email field
    email = (person.get("work_email") or "").strip().lower()
    if email and _is_valid_email(email):
        return email

    # Secondary: emails[] list
    for entry in (person.get("emails") or []):
        if isinstance(entry, dict):
            addr = (entry.get("address") or "").strip().lower()
        else:
            addr = str(entry).strip().lower()
        if addr and _is_valid_email(addr):
            return addr

    return None


def _extract_phone(person: dict) -> Optional[str]:
    """
    Extract the person's direct phone number from PDL.
    Returns None if PDL did not provide one — NEVER copies company phone.
    """
    numbers = person.get("phone_numbers") or []
    if numbers:
        first = numbers[0]
        if isinstance(first, dict):
            return (first.get("number") or first.get("value") or "").strip() or None
        return str(first).strip() or None
    return None


def _company_matches_person(person: dict, company_name: str, domain: str) -> tuple[bool, float]:
    """
    Check whether the PDL person's CURRENT employer matches the target company.

    Returns (matches: bool, match_strength: float 0.0–1.0).
    Prefers current employment over former.
    """
    cur_website = (person.get("job_company_website") or "").lower().strip()
    cur_website = re.sub(r'^https?://(www\.)?', '', cur_website).rstrip('/')
    cur_name    = (person.get("job_company_name") or "").lower().strip()

    target_dom  = (domain or "").lower().replace("www.", "").rstrip("/")
    target_name = (company_name or "").lower().strip()

    # Exact domain match — strongest signal
    if target_dom and cur_website:
        if cur_website == target_dom or cur_website.endswith("." + target_dom):
            return True, 1.0

    # Name overlap
    if target_name and cur_name:
        noise = {"pvt", "ltd", "limited", "inc", "corp", "the", "group",
                 "hospital", "hospitals", "clinic", "and", "&"}
        t_words = set(target_name.split()) - noise
        c_words = set(cur_name.split()) - noise
        if t_words and c_words:
            overlap = len(t_words & c_words) / max(len(t_words), 1)
            if overlap >= 0.50:
                return True, min(0.6 + overlap * 0.3, 0.95)

    return False, 0.0


def compute_confidence(
    person: dict,
    company_name: str,
    domain: str,
    has_email: bool,
) -> float:
    """
    Score 0.0–1.0 for the quality of this contact match.

    Factors:
      - Company match strength (domain vs name)
      - Current vs former employment
      - Role relevance (founder > ceo > director > hr > other)
      - Email availability
    """
    score = 0.0

    matches, strength = _company_matches_person(person, company_name, domain)
    if not matches:
        return 0.0  # reject entirely

    # Base: company match quality (max 0.4)
    score += strength * 0.40

    # Current employment bonus (max 0.15)
    levels = person.get("job_title_levels") or []
    if "founder" in levels or "c_suite" in levels:
        score += 0.15
    elif "director" in levels or "vp" in levels or "owner" in levels:
        score += 0.10
    elif "partner" in levels:
        score += 0.08
    else:
        score += 0.05

    # Role relevance (max 0.25)
    title = (person.get("job_title") or "").lower()
    role  = classify_role(title)
    _role_score = {
        "founder":            0.25,
        "co_founder":         0.25,
        "owner":              0.22,
        "ceo":                0.20,
        "managing_director":  0.20,
        "director":           0.15,
        "hr":                 0.12,
        "talent_acquisition": 0.10,
        "recruitment":        0.08,
        "other":              0.03,
    }
    score += _role_score.get(role, 0.03)

    # Email availability (max 0.20)
    if has_email:
        score += 0.20

    return round(min(score, 0.98), 2)  # cap at 0.98 — never give perfect 1.0


def map_person_to_contact(
    person: dict,
    company_name: str,
    domain: str,
) -> Optional[dict]:
    """
    Map a raw PDL person dict → a clean contact dict.
    Returns None if the person doesn't match the company or has a noise title.
    """
    title = (person.get("job_title") or "").strip()

    # Check relevance
    levels = person.get("job_title_levels") or []
    if not is_relevant_contact(title, levels):
        return None

    # Check company match
    matches, _ = _company_matches_person(person, company_name, domain)
    if not matches:
        return None

    # Build name
    first = (person.get("first_name") or "").strip()
    last  = (person.get("last_name")  or "").strip()
    full  = f"{first} {last}".strip() or (person.get("full_name") or "").strip() or None

    if not full:
        return None

    # Reject names that look like company names
    full_lower = (full or "").lower()
    _co_words = {"ltd", "limited", "pvt", "inc", "corp", "group", "hospital",
                 "technologies", "solutions", "services", "builders"}
    if any(w in full_lower.split() for w in _co_words):
        return None

    email       = _extract_email(person)
    phone       = _extract_phone(person)
    linkedin    = _extract_linkedin(person)
    role        = classify_role(title)
    confidence  = compute_confidence(person, company_name, domain, has_email=bool(email))

    return {
        "name":           full,
        "designation":    title or None,
        "email":          email,
        "phone":          phone,
        "email_type":     role,
        "linkedin_url":   linkedin,
        "company_name":   (person.get("job_company_name") or company_name).strip() or None,
        "company_domain": domain or None,
        "source":         "people_data_labs",
        "confidence":     confidence,
    }
