"""
reddit/schemas.py
──────────────────
Pydantic models for the standalone Reddit lead-generation module.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Input ─────────────────────────────────────────────────────────────────────

class RedditSearchInput(BaseModel):
    """Request payload for Reddit lead search."""
    category: str            = Field(..., min_length=1, example="Manufacturing")
    location: str            = Field(..., min_length=1, example="Pune")
    limit:    int            = Field(default=25, ge=1, le=100,
                                     description="Max leads to return (1–100)")


# ── Raw Reddit post ────────────────────────────────────────────────────────────

class RedditPost(BaseModel):
    """A single Reddit post as returned by the API (before lead extraction)."""
    post_id:       str
    title:         str
    text:          str            = ""
    author:        Optional[str]  = None
    subreddit:     str
    post_url:      str
    created_utc:   float          = 0.0
    score:         int            = 0
    num_comments:  int            = 0
    search_query:  str            = ""


# ── Extracted lead candidate ──────────────────────────────────────────────────

class RedditLeadCandidate(BaseModel):
    """
    A lead candidate extracted from a Reddit post.

    Fields are populated only when clearly stated in the post.
    Nothing is fabricated — unknown fields stay None.
    """
    # Reddit post metadata
    post_id:         str
    post_title:      str
    post_text:       str            = ""
    post_url:        str
    subreddit:       str
    author:          Optional[str]  = None
    post_score:      int            = 0
    post_created_utc: float         = 0.0
    search_query:    str            = ""
    search_location: str            = ""

    # Extracted company/person fields
    company_name:    Optional[str]  = None
    founder_name:    Optional[str]  = None
    designation:     Optional[str]  = None   # job title mentioned in post
    email:           Optional[str]  = None
    phone:           Optional[str]  = None
    website:         Optional[str]  = None
    city:            Optional[str]  = None
    state:           Optional[str]  = None
    country:         str            = "India"

    # Lead quality
    has_contact_info: bool          = False  # email or phone found
    has_company:      bool          = False  # company name found
    relevance_score:  float         = 0.0   # 0.0–1.0


# ── Search result ─────────────────────────────────────────────────────────────

class RedditSearchResult(BaseModel):
    """Full result for one Reddit lead-generation search."""
    success:          bool
    category:         str
    location:         str
    queries_run:      int                       = 0
    posts_discovered: int                       = 0
    candidates:       list[RedditLeadCandidate] = Field(default_factory=list)
    candidates_found: int                       = 0
    elapsed_seconds:  float                     = 0.0
    error:            Optional[str]             = None


# ── Health / auth-test responses ──────────────────────────────────────────────

class RedditHealthResponse(BaseModel):
    module:     str   = "reddit"
    configured: bool
    status:     str   # "ready" | "no_credentials"
    message:    str
    max_posts:  int
    max_queries: int
    timeout_seconds: float


class RedditAuthTestResponse(BaseModel):
    REDDIT_CONFIGURED:     bool
    REDDIT_CLIENT_ID_HINT: str
    REDDIT_HTTP_STATUS:    Optional[int]
    REDDIT_AUTHENTICATION: str            # "SUCCESS" | "FAILED"
    username:              Optional[str]  # Reddit username if auth succeeded
    message:               str
