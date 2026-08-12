"""
people_enrichment/scoring.py
──────────────────────────────
Role priority ordering and confidence re-scoring for merged contacts.

Used after dedup to re-rank the final merged contact list.
ZERO imports from outside people_enrichment/.
"""
from __future__ import annotations

from typing import Optional


# ── Role priority (lower = higher priority) ───────────────────────────────────

ROLE_PRIORITY: dict[str, int] = {
    "founder":                     0,
    "co_founder":                  1,
    "owner":                       2,
    "ceo":                         3,
    "managing_director":           4,
    "coo":                         5,
    "director":                    6,
    "hr":                          7,
    "talent_acquisition":          8,
    "recruitment":                 9,
    "hr_manager":                 10,
    "talent_acquisition_manager": 11,
    "other":                      99,
}

# Title keyword → role mapping (same rules shared across all three providers)
_ROLE_RULES: list[tuple[list[str], str]] = [
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
    (["hr manager", "human resources manager"],                "hr_manager"),
    (["human resources", " hr ", "hrd"],                       "hr"),
    (["head of talent", "talent acquisition head",
      "talent acquisition director", "vp talent"],             "talent_acquisition"),
    (["talent acquisition manager"],                           "talent_acquisition_manager"),
    (["talent acquisition", "talent partner"],                 "talent_acquisition"),
    (["recruitment manager", "head of recruitment",
      "recruitment director"],                                 "recruitment"),
    (["recruiter", "recruiting", "recruitment"],               "recruitment"),
]


def classify_role(title: str) -> str:
    """Return the role key for a given job title string."""
    if not title:
        return "other"
    tl = f" {title.lower().strip()} "
    for keywords, role in _ROLE_RULES:
        for kw in keywords:
            if kw in tl:
                return role
    return "other"


# ── Re-scoring ────────────────────────────────────────────────────────────────

def rescore(contact: dict) -> float:
    """
    Recompute confidence for a merged contact.

    The providers each have their own scoring, but after merging data from
    multiple sources the combined record may be stronger. We recompute here.

    Max 1.0, never 0.0 if the contact has useful data.
    """
    score = contact.get("confidence", 0.0)

    # Bonus for multi-source corroboration (same person in 2+ providers)
    sources = contact.get("sources") or []
    if len(sources) >= 2:
        score = min(score + 0.05, 0.98)
    if len(sources) >= 3:
        score = min(score + 0.03, 0.98)

    # Email+phone bonus (most complete contact)
    if contact.get("email") and contact.get("phone"):
        score = min(score + 0.03, 0.98)

    return round(score, 3)


# ── Final ranking ─────────────────────────────────────────────────────────────

def rank_contacts(contacts: list[dict]) -> list[dict]:
    """
    Sort merged contacts by:
      1. Usefulness tier: email+phone > email-only > phone-only > identity-only
      2. Role priority (founder first)
      3. Confidence (descending)

    Rescores confidence before sorting.
    """
    def _tier(c: dict) -> int:
        has_email = bool(c.get("email"))
        has_phone = bool(c.get("phone"))
        if has_email and has_phone:
            return 0
        if has_email:
            return 1
        if has_phone:
            return 2
        return 3   # identity only

    for c in contacts:
        c["confidence"] = rescore(c)

    contacts.sort(key=lambda c: (
        _tier(c),
        ROLE_PRIORITY.get(classify_role(c.get("title", "")), 99),
        -c.get("confidence", 0.0),
    ))
    return contacts


# ── Contact usefulness for target calculation ─────────────────────────────────

def is_useful(contact: dict) -> bool:
    """
    True when the contact meets the minimum 'useful' bar:
      name + (email OR phone)

    Title is NOT required — it affects ranking priority only.
    """
    return (
        bool((contact.get("name") or "").strip()) and
        (bool(contact.get("email")) or bool(contact.get("phone")))
    )
