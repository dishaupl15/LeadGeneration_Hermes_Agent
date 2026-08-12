"""
contactout/schemas.py
──────────────────────
Pydantic models for the ContactOut module.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Input ─────────────────────────────────────────────────────────────────────

class ContactOutSearchInput(BaseModel):
    """Company information needed to search ContactOut for contacts."""
    company_name: str           = Field(..., min_length=1, example="Intercom")
    domain:       Optional[str] = Field(None, example="intercom.com")


# ── Contact output ────────────────────────────────────────────────────────────

class ContactOutContact(BaseModel):
    """A single decision-maker contact returned by ContactOut."""
    name:         Optional[str]  = Field(None,  example="Eoghan McCabe")
    title:        Optional[str]  = Field(None,  example="CEO and co-founder")
    email:        Optional[str]  = Field(None,  example="eoghan@intercom.com")
    phone:        Optional[str]  = Field(
                                    None,
                                    example="+353 87 123 4567",
                                    description="Person phone from ContactOut — null if not provided",
                                  )
    linkedin_url: Optional[str]  = Field(None,  example="https://linkedin.com/in/eoghanmccabe")
    source:       str            = Field(default="contactout")
    confidence:   float          = Field(default=0.0, ge=0.0, le=1.0)


# ── Search result ─────────────────────────────────────────────────────────────

class ContactOutSearchResult(BaseModel):
    """Full result for one company contact search."""
    provider:       str                         = Field(default="contactout")
    success:        bool                        = Field(...)
    contacts:       list[ContactOutContact]     = Field(default_factory=list)
    contacts_found: int                         = Field(default=0)
    emails_found:   int                         = Field(default=0)
    phones_found:   int                         = Field(default=0)
    api_calls:      int                         = Field(default=0)
    error:          Optional[str]               = Field(None)


# ── Health / auth-test responses ──────────────────────────────────────────────

class ContactOutHealthResponse(BaseModel):
    module:                   str   = "contactout"
    configured:               bool
    status:                   str
    message:                  str
    max_contacts_per_company: int
    timeout_seconds:          float


class ContactOutAuthTestResponse(BaseModel):
    CONTACTOUT_CONFIGURED:     bool
    CONTACTOUT_TOKEN_LENGTH:   int
    CONTACTOUT_HTTP_STATUS:    Optional[int]
    CONTACTOUT_AUTHENTICATION: str            # "SUCCESS" | "FAILED"
    message:                   str
