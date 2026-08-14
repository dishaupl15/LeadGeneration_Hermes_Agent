"""
reddit/search.py
─────────────────
Reddit lead discovery: query generation + post extraction + lead normalization.

Responsibilities
────────────────
  1. Generate multiple relevant search queries from (category, location)
  2. Fan out across queries using reddit/client.py (OAuth2 API — no scraping)
  3. Deduplicate posts by post_id
  4. Extract lead candidates from posts (never fabricate — only what is stated)
  5. Normalize candidates to the shape expected by the MongoDB leads pipeline

Isolation contract
──────────────────
  ✅ Imports ONLY from: reddit/config.py, reddit/client.py, reddit/schemas.py
     + standard library + httpx + pydantic
  🚫 Does NOT import from google_maps/, maps_pipeline_service, people_enrichment,
     pdl_service, hunter_service, origami_service, or any app.services.*
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Optional

from reddit.client import search_reddit_posts
from reddit.config import REDDIT_MAX_QUERIES
from reddit.schemas import RedditLeadCandidate, RedditPost


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [REDDIT] {msg}", flush=True)


# ── Query generation ──────────────────────────────────────────────────────────

_QUERY_TEMPLATES = [
    "{category} {location}",
    "{category} company {location}",
    "{category} business {location}",
    "{category} supplier {location}",
    "{category} manufacturer {location}",
    "{category} services {location}",
    "{category} startup {location}",
    "{category} India {location}",
    "looking for {category} {location}",
    "{category} vendor {location}",
]


def generate_search_queries(category: str, location: str, max_queries: int = REDDIT_MAX_QUERIES) -> list[str]:
    """
    Generate diverse Reddit search queries from a category + location pair.
    Caps the result at max_queries to respect the REDDIT_MAX_QUERIES setting.
    Deduplicates the generated list.
    """
    queries: list[str] = []
    cat_lower  = category.strip().lower()
    loc_lower  = location.strip().lower()

    for tmpl in _QUERY_TEMPLATES:
        q = tmpl.format(category=cat_lower, location=loc_lower).strip()
        if q and q not in queries:
            queries.append(q)
        if len(queries) >= max_queries:
            break

    _log(f"Generated {len(queries)} queries for category={category!r} location={location!r}")
    return queries


# ── Regex patterns for extraction ─────────────────────────────────────────────

_EMAIL_RE  = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RES = [
    re.compile(r'\+91[\s\-]?[6-9]\d{4}[\s\-]?\d{5}'),
    re.compile(r'\b0\d{2,4}[\s\-]\d{6,8}\b'),
    re.compile(r'\b[6-9]\d{9}\b'),
]
_URL_RE    = re.compile(r'https?://[^\s\)\]\"\'<>]+')
_COMPANY_SUFFIXES = r'(?:pvt\.?\s*ltd\.?|private\s+limited|limited|ltd\.?|llp|llc|inc\.?|corp\.?|co\.?|group|industries|solutions|services|technologies|tech|systems|enterprises|ventures|associates)'
_COMPANY_RE = re.compile(
    rf'\b([A-Z][a-zA-Z0-9\s&\-]{{2,50}}\s+{_COMPANY_SUFFIXES})\b',
    re.IGNORECASE,
)
# Founder/CEO mention patterns
_LEADER_RE  = re.compile(
    r'(?i)(?:founder|co-founder|ceo|chief\s+executive|managing\s+director|chairman|md\b|owner|director)',
)
_NAME_RE    = re.compile(r'\b([A-Z][a-z]{2,20})\s+([A-Z][a-z]{2,20})\b')

_JUNK_EMAIL_LOCALS = frozenset({
    "noreply", "no-reply", "donotreply", "webmaster", "abuse",
    "postmaster", "spam", "admin", "test", "example", "support", "info",
    "contact", "hello", "sales",
})

_SOCIAL_DOMAINS = frozenset({
    "reddit.com", "youtube.com", "facebook.com", "twitter.com",
    "x.com", "instagram.com", "tiktok.com", "linkedin.com",
})

# Junk words that should never be treated as company names
_JUNK_WORDS = frozenset({
    "company", "business", "startup", "services", "industry", "industries",
    "all", "any", "the", "this", "that", "there", "their", "they",
    "looking", "need", "want", "help", "like", "just", "good", "best",
})


# ── Low-level extraction helpers ──────────────────────────────────────────────

def _extract_email(text: str) -> Optional[str]:
    for addr in _EMAIL_RE.findall(text):
        local = addr.split("@")[0].lower()
        if local in _JUNK_EMAIL_LOCALS:
            continue
        if len(local) < 2:
            continue
        return addr.lower()
    return None


def _extract_phone(text: str) -> Optional[str]:
    for pat in _PHONE_RES:
        m = pat.search(text)
        if m:
            raw = m.group(0).strip()
            digits = re.sub(r'\D', '', raw)
            if 7 <= len(digits) <= 15:
                return raw
    return None


def _extract_website(text: str) -> Optional[str]:
    for url in _URL_RE.findall(text):
        url = url.rstrip(".,;!?)")
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            dom = p.netloc.lower().lstrip("www.")
            if any(dom == s or dom.endswith("." + s) for s in _SOCIAL_DOMAINS):
                continue
            if p.scheme in ("http", "https") and "." in dom:
                return url
        except Exception:
            continue
    return None


def _extract_company(text: str) -> Optional[str]:
    """
    Extract a company name that has a registered suffix (Pvt Ltd, Inc, etc.).
    Returns None when nothing clear is found — never fabricates.
    """
    matches = _COMPANY_RE.findall(text)
    if not matches:
        return None
    for m in matches:
        name = m.strip()
        words = name.lower().split()
        if not words:
            continue
        # Reject if the first word is a junk word
        if words[0] in _JUNK_WORDS:
            continue
        if len(name) < 5:
            continue
        return name
    return None


def _extract_founder(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Return (founder_name, designation) when a leader is explicitly named.
    Returns (None, None) when not found.
    """
    for line in text.split("\n"):
        if _LEADER_RE.search(line):
            # Try to extract a 2-word name near the leader keyword
            m = _NAME_RE.search(line)
            if m:
                name = m.group(0)
                # Ensure it's not a junk word combo
                parts = name.lower().split()
                if all(p not in _JUNK_WORDS for p in parts) and len(parts) == 2:
                    # Find what role was mentioned
                    role_m = _LEADER_RE.search(line)
                    role = role_m.group(0).strip() if role_m else None
                    return name, role
    return None, None


def _post_relevance(post: RedditPost, category: str, location: str) -> float:
    """
    Assign a 0.0–1.0 relevance score to a Reddit post.
    Higher = more relevant to the category + location lead search.
    """
    score = 0.0
    cat_lower = category.lower()
    loc_lower = location.lower()
    full_text = (post.title + " " + post.text).lower()

    # Location match
    if loc_lower in full_text:
        score += 0.3
    # Category match
    if cat_lower in full_text:
        score += 0.3
    # Has business contact signals
    if _EMAIL_RE.search(full_text):
        score += 0.15
    for pat in _PHONE_RES:
        if pat.search(full_text):
            score += 0.1
            break
    if _URL_RE.search(full_text):
        score += 0.05
    if _COMPANY_RE.search(full_text):
        score += 0.1
    # Engagement bonus (normalized, capped)
    score += min(post.score / 500, 0.05)

    return round(min(score, 1.0), 2)


# ── Core extraction ────────────────────────────────────────────────────────────

def extract_lead_candidate(
    post: RedditPost,
    category: str,
    location: str,
) -> Optional[RedditLeadCandidate]:
    """
    Parse a Reddit post into a RedditLeadCandidate.

    Rules:
      - Never fabricate company/person/email/phone
      - Skip posts with relevance < 0.15 (noise filter)
      - Skip deleted/empty posts (no title + no text)
    """
    # Skip completely empty posts
    if not post.title.strip() and not post.text.strip():
        return None

    full_text = post.title + "\n" + post.text
    relevance = _post_relevance(post, category, location)

    # Minimum relevance threshold — skip pure noise
    if relevance < 0.15:
        return None

    # Extract optional fields — only when clearly stated
    company  = _extract_company(full_text)
    email    = _extract_email(full_text)
    phone    = _extract_phone(full_text)
    website  = _extract_website(full_text)
    founder, designation = _extract_founder(full_text)

    has_contact = bool(email or phone)
    has_company = bool(company)

    return RedditLeadCandidate(
        post_id=post.post_id,
        post_title=post.title[:500],
        post_text=post.text[:2000],
        post_url=post.post_url,
        subreddit=post.subreddit,
        author=post.author,
        post_score=post.score,
        post_created_utc=post.created_utc,
        search_query=post.search_query,
        search_location=location,

        company_name=company,
        founder_name=founder,
        designation=designation,
        email=email,
        phone=phone,
        website=website,

        has_contact_info=has_contact,
        has_company=has_company,
        relevance_score=relevance,
    )


# ── Fan-out search ─────────────────────────────────────────────────────────────

async def fan_out_search(
    queries: list[str],
    posts_per_query: int = 10,
) -> list[RedditPost]:
    """
    Execute up to REDDIT_MAX_QUERIES searches concurrently.
    Deduplicates posts by post_id across all query results.
    Returns merged, deduplicated list.
    """
    sem = asyncio.Semaphore(3)  # max 3 concurrent Reddit API calls

    async def _bounded_search(q: str) -> list[RedditPost]:
        async with sem:
            posts, err = await search_reddit_posts(
                query=q,
                limit=posts_per_query,
                sort="relevance",
                time_filter="year",
            )
            if err:
                _log(f"Query {q!r} error: {err}")
            return posts

    results = await asyncio.gather(
        *[_bounded_search(q) for q in queries],
        return_exceptions=True,
    )

    seen_ids: set[str] = set()
    merged: list[RedditPost] = []
    for batch in results:
        if isinstance(batch, Exception):
            _log(f"Fan-out gather error: {batch}")
            continue
        for post in batch:
            if post.post_id not in seen_ids:
                seen_ids.add(post.post_id)
                merged.append(post)

    _log(f"Fan-out complete: {len(merged)} unique posts from {len(queries)} queries")
    return merged


# ── Main public entry point ────────────────────────────────────────────────────

async def run_reddit_search(
    category: str,
    location: str,
    limit: int = 25,
) -> dict:
    """
    Full Reddit search pipeline.

    Returns a dict with:
      candidates        — list[RedditLeadCandidate]  (relevance-sorted)
      posts_discovered  — int  (raw posts fetched)
      queries_run       — int
      elapsed_seconds   — float
      error             — str | None
    """
    t0 = time.monotonic()
    _log(f"Search started — category={category!r} location={location!r} limit={limit}")

    # Step 1: generate queries
    queries = generate_search_queries(category, location, max_queries=REDDIT_MAX_QUERIES)
    _log(f"Queries ({len(queries)}): {queries}")

    # Step 2: fan-out search
    posts_per_query = max(5, min(25, limit))
    try:
        posts = await fan_out_search(queries, posts_per_query=posts_per_query)
    except Exception as exc:
        _log(f"Fan-out error: {exc}")
        return {
            "candidates": [],
            "posts_discovered": 0,
            "queries_run": len(queries),
            "elapsed_seconds": round(time.monotonic() - t0, 2),
            "error": str(exc),
        }

    _log(f"Posts discovered: {len(posts)}")

    # Step 3: extract lead candidates
    candidates: list[RedditLeadCandidate] = []
    for post in posts:
        try:
            cand = extract_lead_candidate(post, category, location)
            if cand is not None:
                candidates.append(cand)
        except Exception as exc:
            _log(f"Extraction error for post {post.post_id}: {exc}")

    # Step 4: sort by relevance, then cap at limit
    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    candidates = candidates[:limit]

    elapsed = round(time.monotonic() - t0, 2)
    _log(f"Valid candidates: {len(candidates)}")
    _log(f"Completed in {elapsed}s")

    return {
        "candidates": candidates,
        "posts_discovered": len(posts),
        "queries_run": len(queries),
        "elapsed_seconds": elapsed,
        "error": None,
    }


# ── Convert RedditLeadCandidate → MongoDB lead dict ───────────────────────────

def candidate_to_lead_doc(
    candidate: RedditLeadCandidate,
    category: str,
    run_id: str,
) -> dict:
    """
    Convert a RedditLeadCandidate to the flat dict shape expected by the
    existing leads MongoDB collections (leads_{slug}).

    Only sets fields when they are actually known — never fabricates.
    Sets:
      source         = "reddit"
      platform       = "reddit"      (for LeadsTable source column)
      research_source = "reddit"     (for history / debug)
      status         = "new"         (injected by $setOnInsert in the upsert)
      generation_run_id              (injected by $setOnInsert)
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # company_name: use extracted name, or fall back to author handle,
    # or the post title (truncated) — some Reddit leads have no company name
    company_name = (
        candidate.company_name
        or (f"r/{candidate.subreddit} — {candidate.post_title[:60]}")
    )

    doc: dict = {
        # Core CRM fields
        "company_name":   company_name,
        "category":       category,
        "email":          candidate.email,
        "emails":         [candidate.email] if candidate.email else [],
        "company_number": candidate.phone,
        "phones":         [candidate.phone] if candidate.phone else [],
        "website":        candidate.website or "",
        "address":        "",
        "city":           candidate.city or "",
        "state":          candidate.state or "",
        "country":        candidate.country or "India",
        "postal_code":    "",
        # Founder / person
        "founder_name":   candidate.founder_name,
        "founder_number": None,
        "designation":    candidate.designation,
        # Source metadata
        "source":         "reddit",
        "platform":       "reddit",
        "research_source": "reddit",
        "research_sources": [candidate.post_url] if candidate.post_url else [],
        "source_url":     candidate.post_url,
        # Reddit-specific fields
        "post_id":        candidate.post_id,
        "post_title":     candidate.post_title,
        "post_text":      candidate.post_text,
        "post_url":       candidate.post_url,
        "subreddit":      candidate.subreddit,
        "reddit_author":  candidate.author,
        "post_score":     candidate.post_score,
        "search_keywords": candidate.search_query,
        "search_location": candidate.search_location,
        # Quality
        "confidence":     candidate.relevance_score,
        # Timestamps (created_at + status set by $setOnInsert in upsert)
        "updated_at":     now,
    }

    return doc
