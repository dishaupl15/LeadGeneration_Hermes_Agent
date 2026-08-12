"""
people_enrichment/dedup.py
───────────────────────────
Deduplication and merging logic for contacts from multiple providers.

Deduplication keys (checked in priority order):
  1. Normalised email            (strongest — email is unique per person)
  2. Normalised phone            (strong — mobile numbers are personal)
  3. Normalised LinkedIn URL     (strong — unique profile URL)
  4. Normalised name + domain    (weakest — fuzzy fallback)

When the same person appears in more than one provider:
  - Merge their fields, preferring the strongest available value.
  - Keep email from whichever provider has a professional/verified email.
  - Keep phone from whichever provider has a real number.
  - Combine sources[] from all matching records.
  - Take the highest confidence score.

ZERO imports from outside people_enrichment/.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _norm_email(email: Optional[str]) -> str:
    if not email:
        return ""
    return email.strip().lower()


def _norm_phone(phone: Optional[str]) -> str:
    """Strip all non-digit characters for comparison."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone.strip())
    # Use last 10 digits for comparison (handles +country-code variance)
    return digits[-10:] if len(digits) >= 10 else digits


def _norm_linkedin(url: Optional[str]) -> str:
    if not url:
        return ""
    u = url.strip().lower().rstrip("/")
    # Strip scheme and www
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u


def _norm_name_key(name: Optional[str], domain: Optional[str]) -> str:
    """Composite key: normalised name tokens + domain."""
    if not name:
        return ""
    noise = {"mr", "mrs", "ms", "dr", "prof", "sir", "jr", "sr"}
    tokens = [t.lower() for t in name.strip().split() if t.lower() not in noise]
    if len(tokens) < 2:
        return ""   # single-word name — too ambiguous for dedup
    name_part = " ".join(tokens)
    dom = (domain or "").lower().strip().lstrip("www.")
    return f"{name_part}|{dom}" if dom else ""


# ── Email quality ─────────────────────────────────────────────────────────────

_JUNK_LOCALS: frozenset[str] = frozenset({
    "info", "contact", "hello", "support", "sales", "admin",
    "noreply", "no-reply", "office", "careers",
})


def _email_quality(email: Optional[str]) -> int:
    """
    Return an integer quality score for ranking emails.
    Higher = better. Used to prefer professional emails over generic ones.
    """
    if not email:
        return 0
    addr = email.strip().lower()
    local, _, dom = addr.partition("@")
    if local in _JUNK_LOCALS:
        return 1
    # Generic domains (gmail, yahoo, etc.) are weaker than company domains
    generic = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
               "yahoo.co.in", "rediffmail.com"}
    if dom in generic:
        return 2
    return 3   # professional/company email — best


# ── Core merge function ───────────────────────────────────────────────────────

def _merge_into(base: dict, incoming: dict) -> dict:
    """
    Merge `incoming` contact fields into `base`.
    Stronger values win. Never overwrite a real value with None.
    """
    merged = dict(base)

    # Email: prefer higher quality
    if not merged.get("email") or _email_quality(incoming.get("email")) > _email_quality(merged.get("email")):
        if incoming.get("email"):
            merged["email"] = incoming["email"]

    # Phone: prefer any real phone over None
    if not merged.get("phone") and incoming.get("phone"):
        merged["phone"] = incoming["phone"]

    # LinkedIn: prefer any URL over None
    if not merged.get("linkedin_url") and incoming.get("linkedin_url"):
        merged["linkedin_url"] = incoming["linkedin_url"]

    # Title: prefer longer/more specific title
    if incoming.get("title"):
        if not merged.get("title") or len(incoming["title"]) > len(merged.get("title", "")):
            merged["title"] = incoming["title"]

    # Name: keep as-is (first seen wins; names are usually consistent)
    if not merged.get("name") and incoming.get("name"):
        merged["name"] = incoming["name"]

    # Confidence: take the highest
    merged["confidence"] = max(
        merged.get("confidence", 0.0),
        incoming.get("confidence", 0.0),
    )

    # Sources: union (preserve order, deduplicate)
    existing_sources = list(merged.get("sources", []))
    for s in incoming.get("sources", []):
        if s not in existing_sources:
            existing_sources.append(s)
    merged["sources"] = existing_sources

    return merged


# ── Main dedup function ───────────────────────────────────────────────────────

def dedup_and_merge(
    contacts: list[dict],
    company_domain: Optional[str] = None,
) -> list[dict]:
    """
    Deduplicate a list of raw contact dicts (from any combination of providers).

    Each dict must have at minimum:
      name, title, email, phone, linkedin_url, sources, confidence

    Returns a deduplicated, merged list sorted by confidence descending.

    Dedup key priority:
      1. email
      2. phone
      3. linkedin_url
      4. name + domain
    """
    # Each "bucket" is a list of raw contacts that belong to the same person
    buckets: list[list[dict]] = []

    def _find_bucket(contact: dict) -> Optional[int]:
        email    = _norm_email(contact.get("email"))
        phone    = _norm_phone(contact.get("phone"))
        linkedin = _norm_linkedin(contact.get("linkedin_url"))
        namekey  = _norm_name_key(contact.get("name"), company_domain)

        for i, bucket in enumerate(buckets):
            rep = bucket[0]   # representative of this bucket
            # 1. Email match
            if email and email == _norm_email(rep.get("email")):
                return i
            # 2. Phone match
            if phone and len(phone) >= 7 and phone == _norm_phone(rep.get("phone")):
                return i
            # 3. LinkedIn match
            if linkedin and linkedin == _norm_linkedin(rep.get("linkedin_url")):
                return i
            # 4. Name+domain match (only if both sides have a valid key)
            rep_namekey = _norm_name_key(rep.get("name"), company_domain)
            if namekey and rep_namekey and namekey == rep_namekey:
                return i
        return None

    for contact in contacts:
        bucket_idx = _find_bucket(contact)
        if bucket_idx is not None:
            buckets[bucket_idx].append(contact)
        else:
            buckets.append([contact])

    # Merge each bucket into a single contact
    merged: list[dict] = []
    for bucket in buckets:
        combined = dict(bucket[0])
        # Ensure sources is a list
        if not isinstance(combined.get("sources"), list):
            combined["sources"] = [combined["sources"]] if combined.get("sources") else []
        for extra in bucket[1:]:
            combined = _merge_into(combined, extra)
        merged.append(combined)

    # Sort: confidence desc, then by source richness (email+phone > email > phone)
    def _sort_key(c: dict) -> tuple:
        has_email = 1 if c.get("email") else 0
        has_phone = 1 if c.get("phone") else 0
        return (-c.get("confidence", 0.0), -(has_email + has_phone))

    merged.sort(key=_sort_key)
    return merged


# ── Usefulness check ──────────────────────────────────────────────────────────

def is_useful_contact(contact: dict) -> bool:
    """
    A contact is 'useful' for the waterfall target check when it has:
      - real name
      - email OR phone

    Title is NOT required for usefulness — it affects ranking only.
    A contact with name + email but no title is still useful.
    A contact with name + phone but no title is still useful.
    """
    has_name  = bool((contact.get("name") or "").strip())
    has_email = bool((contact.get("email") or "").strip())
    has_phone = bool((contact.get("phone") or "").strip())
    return has_name and (has_email or has_phone)


def count_useful(contacts: list[dict]) -> int:
    """Count contacts that meet the 'useful' threshold."""
    return sum(1 for c in contacts if is_useful_contact(c))
