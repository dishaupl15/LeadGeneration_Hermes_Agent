"""
contactout/contact_mapper.py
─────────────────────────────
Maps raw ContactOut profile objects → normalised ContactOutContact dicts.

Responsibilities:
  - Classify role from current job title
  - Score confidence (company match + role priority + email availability)
  - Extract emails and phones from ContactOut contact_info ONLY
    (never fabricate — only return values actually present in the response)
  - Validate and normalise email format
  - Normalise phone numbers
  - Prefer decision-makers but retain any plausible company employee
    (no profile is discarded solely because of an unrecognised title)

ZERO imports from outside contactout/.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Role priority table ───────────────────────────────────────────────────────
# (order = priority: lower index = higher priority)
# Matching is case-insensitive substring against " {title.lower()} " (padded).
_ROLE_RULES: list[tuple[list[str], str]] = [
    # Co-founder variants — checked before plain "founder"
    (["co-founder", "cofounder", "co founder"],                      "co_founder"),
    # Founder
    (["founder"],                                                     "founder"),
    # Owner / Proprietor
    (["owner", "proprietor", "proprietress"],                        "owner"),
    # CEO / Chairman / President
    (["chief executive", "ceo"],                                     "ceo"),
    (["chairman", "chairwoman", "chairperson",
      "co-chairman", "co chairman", "president"],                    "ceo"),
    # Managing Director / MD
    (["managing director", "managing partner"],                      "managing_director"),
    # Standalone "md" only as whole word to avoid false positives
    ([" md "],                                                        "managing_director"),
    # COO
    (["coo", "chief operating"],                                     "coo"),
    # Other C-suite / Chief roles
    (["chief ", "c-suite", "csuite"],                                "c_suite"),
    # Executive Director
    (["executive director"],                                         "director"),
    # Director (must come after "executive director")
    (["director"],                                                    "director"),
    # General Manager / GM
    (["general manager", " gm "],                                    "general_manager"),
    # Principal
    (["principal"],                                                   "principal"),
    # Partner
    (["partner"],                                                     "partner"),
    # Promoter
    (["promoter"],                                                    "owner"),
    # Head of … (generic)
    (["head of", "head,"],                                           "head"),
    # VP / Vice President
    (["vice president", " vp "],                                     "vp"),
    # HR-specific
    (["head of hr", "head hr", "head of human",
      "vp hr", "vp of hr", "chief human", "chro"],                  "hr"),
    (["hr manager", "human resources manager"],                      "hr_manager"),
    (["human resources", " hr ", "hrd"],                             "hr"),
    # Talent Acquisition
    (["head of talent", "talent acquisition head",
      "talent acquisition director", "vp talent"],                   "talent_acquisition"),
    (["talent acquisition manager"],                                  "talent_acquisition_manager"),
    (["talent acquisition", "talent partner"],                       "talent_acquisition"),
    # Recruitment
    (["recruitment manager", "head of recruitment",
      "recruitment director"],                                        "recruitment"),
    (["recruiter", "recruiting", "recruitment"],                     "recruitment"),
]

ROLE_PRIORITY: dict[str, int] = {
    "founder":                     0,
    "co_founder":                  1,
    "owner":                       2,
    "ceo":                         3,
    "managing_director":           4,
    "coo":                         5,
    "c_suite":                     6,
    "director":                    7,
    "general_manager":             8,
    "principal":                   9,
    "partner":                    10,
    "head":                       11,
    "vp":                         12,
    "hr":                         13,
    "talent_acquisition":         14,
    "recruitment":                15,
    "hr_manager":                 16,
    "talent_acquisition_manager": 17,
    "other":                      98,   # plausible employee — kept but ranked last
}

# Titles we always hard-reject (noise / definitely not decision-makers)
_NOISE_TITLES: frozenset[str] = frozenset({
    "intern", "trainee", "fresher", "student", "apprentice",
    "sales executive", "marketing executive", "software engineer",
    "developer", "programmer", "data scientist", "data analyst",
    "accountant", "finance analyst", "auditor",
    "admin", "receptionist", "secretary",
    "operations executive", "business analyst",
})

# Email locals we always reject
_JUNK_EMAIL_LOCALS: frozenset[str] = frozenset({
    "noreply", "no-reply", "donotreply", "webmaster", "abuse",
    "postmaster", "spam", "admin", "test", "example",
    "info", "contact", "support", "sales", "enquiry",
    "enquiries", "hello", "office", "careers",
})

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

# Reject null / N/A string placeholders ContactOut sometimes sends
_NULL_STRINGS: frozenset[str] = frozenset({"null", "n/a", "na", "none", "", "undefined"})


# ── Role classification ───────────────────────────────────────────────────────

def classify_role(title: str) -> str:
    """Return a role key for the given job title string (case-insensitive)."""
    if not title:
        return "other"
    tl = f" {title.lower().strip()} "
    for keywords, role in _ROLE_RULES:
        for kw in keywords:
            if kw in tl:
                return role
    return "other"


def is_noise_title(title: str) -> bool:
    """
    Return True ONLY for clear non-decision-maker noise titles.
    This is the hard reject gate — keep it narrow.
    """
    if not title:
        return False
    tl = title.lower().strip()
    for noise in _NOISE_TITLES:
        if noise in tl:
            return True
    return False


def is_decision_maker(title: str) -> bool:
    """Return True if the title maps to a known decision-maker role."""
    if not title:
        return False
    role = classify_role(title)
    return role != "other"


def is_relevant_title(title: str) -> bool:
    """
    Return True if this person is worth keeping.

    Rules (in order):
      1. Hard-reject noise titles (intern, developer, accountant, etc.)
      2. Accept if the title maps to any known decision-maker role.
      3. Accept directors that are not explicitly non-executive/independent.
      4. Accept anything else — per spec, if ContactOut returns a profile for
         the requested company we keep it even with an unrecognised title.
         It is ranked last (role="other") but NOT discarded.
    """
    if not title:
        # Titleless profile: keep it — we still have name/email/phone
        return True
    if is_noise_title(title):
        return False
    # All non-noise titles are kept; decision_maker flag affects ranking only
    return True


# ── Email helpers ─────────────────────────────────────────────────────────────

def _is_valid_email(email: str) -> bool:
    if not email:
        return False
    addr = email.lower().strip()
    if addr in _NULL_STRINGS:
        return False
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


def normalise_email(raw: str) -> Optional[str]:
    """Lowercase, strip whitespace, reject invalid/null values."""
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if cleaned in _NULL_STRINGS:
        return None
    return cleaned if _is_valid_email(cleaned) else None


# ── Phone helpers ─────────────────────────────────────────────────────────────

def normalise_phone(raw: str) -> Optional[str]:
    """
    Basic phone normalisation.
    Returns cleaned string or None.
    Never generates or guesses a phone number.
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.lower() in _NULL_STRINGS:
        return None
    # Reject known sandbox/test placeholder numbers
    if cleaned in ("+123456789", "123456789", "+1 123-456-789", "0000000000"):
        return None
    # Strip common junk characters but preserve + prefix and digits
    digits_only = re.sub(r"[^\d+]", "", cleaned)
    if len(digits_only) < 7:
        return None
    # Return the original (cleaned) string if it looks phone-like
    return cleaned


# ── Contact-availability check ────────────────────────────────────────────────

def has_contact_availability(profile: dict) -> bool:
    """
    ContactOut contact_availability is a dict of booleans, e.g.:
      {"personal_email": True, "work_email": True, "phone": True}
    Returns True if any contact data type is available.
    """
    avail = profile.get("contact_availability")
    if isinstance(avail, dict):
        return any(avail.values())
    if isinstance(avail, bool):
        return avail
    # Fall back to checking actual contact_info fields
    ci = profile.get("contact_info") or {}
    emails = ci.get("work_emails") or ci.get("emails") or []
    phones = ci.get("phones") or []
    return bool(emails or phones)


# ── Extract contacts from profile ────────────────────────────────────────────

def extract_best_email(profile: dict) -> Optional[str]:
    """
    Extract the best email from contact_info.

    ContactOut response structure (verified by live API probe):
      contact_info = {
        "emails":            [...],   # all emails (personal + work combined)
        "personal_emails":   [...],   # personal only
        "work_emails":       [...],   # professional/work emails  ← PREFER THESE
        "work_email_status": {...},   # verification status per address
        "phones":            [...],
      }

    Priority: work_emails → emails (excluding personal_emails entries)
    Falls back to any valid email in emails[].
    Only returns values explicitly present in the API response.
    """
    ci = profile.get("contact_info") or {}

    work_emails     = ci.get("work_emails")     or []
    all_emails      = ci.get("emails")          or []
    personal_emails = set(ci.get("personal_emails") or [])

    # 1. Try work_emails first (professional addresses)
    for raw in work_emails:
        addr = normalise_email(raw if isinstance(raw, str) else (raw or {}).get("email", ""))
        if addr:
            return addr

    # 2. Try emails[] excluding personal_emails (to prefer work addresses)
    for raw in all_emails:
        candidate = raw if isinstance(raw, str) else (raw or {}).get("email", "")
        if candidate in personal_emails:
            continue
        addr = normalise_email(candidate)
        if addr:
            return addr

    # 3. Fall back to any valid address in emails[]
    for raw in all_emails:
        addr = normalise_email(raw if isinstance(raw, str) else (raw or {}).get("email", ""))
        if addr:
            return addr

    return None


def extract_best_phone(profile: dict) -> Optional[str]:
    """
    Extract the best phone from contact_info.
    Only returns values explicitly present in the API response.
    Never generates or guesses.
    """
    ci = profile.get("contact_info") or {}
    for raw in (ci.get("phones") or []):
        num = normalise_phone(raw if isinstance(raw, str) else str(raw or ""))
        if num:
            return num
    return None


def extract_linkedin(profile: dict) -> Optional[str]:
    """Extract LinkedIn URL from profile."""
    url = (profile.get("linkedin") or profile.get("linkedin_url") or "").strip()
    return url or None


# ── Company match ─────────────────────────────────────────────────────────────

def _name_overlap(a: str, b: str) -> float:
    _noise = {"pvt", "ltd", "limited", "inc", "corp", "the", "group",
              "private", "and", "&", "co", "company"}
    wa = set(a.lower().split()) - _noise
    wb = set(b.lower().split()) - _noise
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), 1)


def company_matches(profile: dict, target_domain: str, target_name: str) -> tuple[bool, float]:
    """
    Check whether this ContactOut profile is currently employed at the target company.
    Returns (matches: bool, strength: float 0.0–1.0).
    """
    target_domain = (target_domain or "").lower().strip().lstrip("www.").rstrip("/")
    target_name   = (target_name or "").lower().strip()

    # Check current_company fields
    current = profile.get("current_company") or profile.get("company") or {}
    if isinstance(current, str):
        current = {"name": current}

    comp_name   = (current.get("name") or "").lower().strip()
    comp_domain = (current.get("domain") or current.get("website") or "").lower().strip().lstrip("www.")

    if target_domain and comp_domain:
        if comp_domain == target_domain or comp_domain.endswith("." + target_domain):
            return True, 1.0

    if target_name and comp_name:
        overlap = _name_overlap(target_name, comp_name)
        if overlap >= 0.50:
            return True, min(0.55 + overlap * 0.4, 0.95)

    # Fallback: check experience list
    for exp in (profile.get("experience") or []):
        if not isinstance(exp, dict):
            continue
        if not (exp.get("is_current") or exp.get("current")):
            continue
        exp_name = (exp.get("company") or exp.get("company_name") or "").lower().strip()
        if target_name and exp_name:
            overlap = _name_overlap(target_name, exp_name)
            if overlap >= 0.50:
                return True, min(0.45 + overlap * 0.35, 0.85)

    return False, 0.0


# ── Confidence scoring ────────────────────────────────────────────────────────

def compute_confidence(
    profile: dict,
    target_domain: str,
    target_name: str,
    has_email: bool,
) -> float:
    """Score 0.0–0.98 for this contact's quality."""
    matches, strength = company_matches(profile, target_domain, target_name)
    if not matches:
        return 0.0

    score = strength * 0.40  # company match (max 0.40)

    title = extract_title(profile)
    role  = classify_role(title)
    _role_score = {
        "founder":                    0.28,
        "co_founder":                 0.28,
        "owner":                      0.25,
        "ceo":                        0.23,
        "managing_director":          0.22,
        "coo":                        0.18,
        "c_suite":                    0.18,
        "director":                   0.16,
        "general_manager":            0.15,
        "principal":                  0.14,
        "partner":                    0.13,
        "head":                       0.12,
        "vp":                         0.12,
        "hr":                         0.11,
        "talent_acquisition":         0.09,
        "recruitment":                0.08,
        "hr_manager":                 0.07,
        "talent_acquisition_manager": 0.06,
        "other":                      0.03,   # plausible employee — kept but low score
    }
    score += _role_score.get(role, 0.03)

    if has_email:
        score += 0.20

    return round(min(score, 0.98), 3)


# ── Name / title extraction ───────────────────────────────────────────────────

def extract_name(profile: dict) -> Optional[str]:
    name = (
        profile.get("full_name")
        or profile.get("name")
        or ""
    ).strip()
    if not name:
        first = (profile.get("first_name") or "").strip()
        last  = (profile.get("last_name")  or "").strip()
        name  = f"{first} {last}".strip()
    return name or None


def extract_title(profile: dict) -> str:
    return (
        profile.get("title")
        or profile.get("current_title")
        or profile.get("headline")
        or ""
    ).strip()


# ── Main mapper ───────────────────────────────────────────────────────────────

def map_profile(
    profile: dict,
    target_domain: str,
    target_name: str,
) -> Optional[dict]:
    """
    Map a single ContactOut profile to a normalised contact dict.

    Rejection rules (narrow — per spec):
      - Hard-noise title (intern, developer, accountant, etc.)
      - Company does NOT match target AND no contact info available
      - Sandbox/test profile: company clearly unrelated AND only has
        placeholder email/phone (e.g. example.com email, +123456789)
    """
    title = extract_title(profile)

    # ── Hard-reject noise titles only ────────────────────────────────────────
    if is_noise_title(title):
        return None

    # ── Sandbox / fake-data guard ─────────────────────────────────────────────
    # ContactOut sandbox tokens always return the same fake profile regardless
    # of the company queried. Detect it: company doesn't match AND the only
    # contact data is obviously fake (example.com email or +123456789 phone).
    matches, strength = company_matches(profile, target_domain, target_name)
    if not matches:
        ci = profile.get("contact_info") or {}
        raw_emails = (ci.get("work_emails") or []) + (ci.get("emails") or [])
        raw_phones = ci.get("phones") or []

        # Check if all emails are on fake/placeholder domains
        real_email_found = False
        for raw in raw_emails:
            addr = normalise_email(raw if isinstance(raw, str) else (raw or {}).get("email", ""))
            if addr:
                dom = addr.split("@")[-1]
                if dom not in ("example.com", "test.com", "dummy.com"):
                    real_email_found = True
                    break

        # Check if all phones are placeholder values
        real_phone_found = False
        for raw in raw_phones:
            num = normalise_phone(raw if isinstance(raw, str) else str(raw or ""))
            if num:
                real_phone_found = True
                break

        if not real_email_found and not real_phone_found:
            # No real contact data AND company doesn't match — discard
            return None

        # Company doesn't match but has real contact data — keep with low strength
        email = extract_best_email(profile)
        phone = extract_best_phone(profile)
        if not (email or phone):
            return None
        strength = 0.30

    name = extract_name(profile)
    if not name:
        return None

    email    = extract_best_email(profile)
    phone    = extract_best_phone(profile)
    linkedin = extract_linkedin(profile)
    role     = classify_role(title)

    confidence = compute_confidence(
        profile, target_domain, target_name, has_email=bool(email)
    )
    # Ensure non-zero confidence for retained profiles
    if confidence == 0.0:
        confidence = round(strength * 0.30, 3)

    return {
        "name":         name,
        "title":        title or None,
        "email":        email,
        "phone":        phone,
        "linkedin_url": linkedin,
        "source":       "contactout",
        "confidence":   confidence,
        "role":         role,         # internal only — stripped before returning
    }
