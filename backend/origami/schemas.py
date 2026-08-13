"""
origami/schemas.py
───────────────────
Pydantic models for the standalone Origami module.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Input ─────────────────────────────────────────────────────────────────────

class OrigamiSearchInput(BaseModel):
    """Minimum information needed to search Origami for contacts at a company."""
    company_name: str            = Field(..., min_length=1, example="ABC Realty")
    domain:       Optional[str]  = Field(None, example="abcrealty.com")
    website:      Optional[str]  = Field(None, example="https://abcrealty.com")
    location:     Optional[str]  = Field(None, example="Mumbai, Maharashtra")
    category:     Optional[str]  = Field(None, example="Real Estate")


# ── Contact output ────────────────────────────────────────────────────────────

class OrigamiContact(BaseModel):
    """A single decision-maker contact returned by Origami."""
    name:         Optional[str]  = Field(None,  example="Rahul Sharma")
    title:        Optional[str]  = Field(None,  example="Founder")
    tier:         int            = Field(default=5,  ge=1, le=5,
                                         description="1=Founder/Owner … 5=Other")
    tier_label:   str            = Field(default="Other",
                                         example="Founder/Owner")
    email:        Optional[str]  = Field(None,  example="rahul@abcrealty.com")
    phone:        Optional[str]  = Field(None,  example="+91 98765 43210")
    linkedin_url: Optional[str]  = Field(None,
                                          example="https://linkedin.com/in/rahulsharma")
    confidence:   float          = Field(default=0.65, ge=0.0, le=1.0)
    source:       str            = Field(default="origami")


# ── Search result ─────────────────────────────────────────────────────────────

class OrigamiSearchResult(BaseModel):
    """Full result for one company contact search."""
    provider:        str                   = Field(default="origami")
    success:         bool
    company_name:    str
    contacts:        list[OrigamiContact]  = Field(default_factory=list)
    contacts_found:  int                   = Field(default=0)
    emails_found:    int                   = Field(default=0)
    phones_found:    int                   = Field(default=0)
    founder_status:  str                   = Field(
                                               default="skipped",
                                               description="found | found_decision_maker | not_found | skipped | error",
                                           )
    elapsed_seconds: float                 = Field(default=0.0)
    error:           Optional[str]         = Field(None)


# ── Health / auth-test responses ──────────────────────────────────────────────

class OrigamiHealthResponse(BaseModel):
    module:           str   = "origami"
    configured:       bool
    status:           str   # "ready" | "no_key"
    message:          str
    base_url:         str
    max_contacts:     int
    timeout_seconds:  float


class OrigamiAuthTestResponse(BaseModel):
    ORIGAMI_CONFIGURED:     bool
    ORIGAMI_KEY_LENGTH:     int
    ORIGAMI_HTTP_STATUS:    Optional[int]
    ORIGAMI_AUTHENTICATION: str            # "SUCCESS" | "FAILED"
    message:                str
