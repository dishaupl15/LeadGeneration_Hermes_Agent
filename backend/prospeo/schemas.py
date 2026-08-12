"""
prospeo/schemas.py
───────────────────
Pydantic models for the Prospeo module.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Input ─────────────────────────────────────────────────────────────────────

class ProspeoSearchInput(BaseModel):
    """Company information needed to search Prospeo for contacts."""
    company_name: str            = Field(..., min_length=1,
                                          example="Intercom")
    domain:       Optional[str]  = Field(None,
                                          example="intercom.com")
    website:      Optional[str]  = Field(None,
                                          example="https://intercom.com")


# ── Contact output ────────────────────────────────────────────────────────────

class ProspeoContact(BaseModel):
    """A single decision-maker contact returned by Prospeo."""
    name:         Optional[str]  = Field(None,  example="Eoghan McCabe")
    title:        Optional[str]  = Field(None,  example="CEO and co-founder")
    email:        Optional[str]  = Field(None,  example="eoghan@intercom.com")
    phone:        Optional[str]  = Field(None,  example="+353 87 123 4567",
                                          description="Person mobile from Prospeo — null if not provided")
    linkedin_url: Optional[str]  = Field(None,  example="https://linkedin.com/in/eoghanmccabe")
    source:       str            = Field(default="prospeo")
    confidence:   float          = Field(default=0.0, ge=0.0, le=1.0)


# ── Search result ─────────────────────────────────────────────────────────────

class ProspeoSearchResult(BaseModel):
    """Full result for one company contact search."""
    provider:          str                    = Field(default="prospeo")
    success:           bool                   = Field(...)
    company_name:      str                    = Field(...)
    company_domain:    Optional[str]          = Field(None)
    contacts:          list[ProspeoContact]   = Field(default_factory=list)
    contacts_found:    int                    = Field(default=0)
    emails_found:      int                    = Field(default=0)
    phones_found:      int                    = Field(default=0)
    api_calls:         int                    = Field(default=0)
    credits_estimated: int                    = Field(default=0,
                                                       description="Credits reported by Prospeo bulk-enrich")
    elapsed_seconds:   float                  = Field(default=0.0)
    error:             Optional[str]          = Field(None)


# ── Health / auth-test responses ──────────────────────────────────────────────

class ProspeoHealthResponse(BaseModel):
    module:                    str   = "prospeo"
    configured:                bool
    status:                    str
    message:                   str
    max_contacts_per_company:  int
    timeout_seconds:           float


class ProspeoAuthTestResponse(BaseModel):
    PROSPEO_CONFIGURED:     bool
    PROSPEO_KEY_LENGTH:     int
    PROSPEO_HTTP_STATUS:    Optional[int]
    PROSPEO_AUTHENTICATION: str   # "SUCCESS" | "FAILED" | "UNKNOWN"
    plan:                   Optional[str]  = None
    remaining_credits:      Optional[int]  = None
    message:                str
