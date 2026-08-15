"""
hunter/schemas.py
──────────────────
Pydantic models for the Hunter.io module.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HunterContact(BaseModel):
    """
    A single contact returned by Hunter.io /email-finder or /domain-search.
    """
    name:         Optional[str]  = Field(None)
    first_name:   Optional[str]  = Field(None)
    last_name:    Optional[str]  = Field(None)
    title:        Optional[str]  = Field(None)
    email:        Optional[str]  = Field(None)
    email_score:  int            = Field(default=0,
        description="Hunter confidence score 0–100")
    sources:      list[str]      = Field(default_factory=lambda: ["hunter"])
    confidence:   float          = Field(default=0.0, ge=0.0, le=1.0)


class HunterResult(BaseModel):
    """
    Result of a Hunter.io call for one company.
    """
    contacts:       list[HunterContact] = Field(default_factory=list)
    contacts_found: int                 = Field(default=0)
    emails_found:   int                 = Field(default=0)
    # Counters for pipeline stats
    calls:          int                 = Field(default=0)
    success:        int                 = Field(default=0)
    no_result:      int                 = Field(default=0)
    failed:         int                 = Field(default=0)
    # Error code when not successful
    error:          Optional[str]       = Field(None,
        description=(
            "auth_failed | no_credits | rate_limited | "
            "not_configured | no_domain | no_name | timeout | http_<N> | None"
        ))
    skipped_reason: Optional[str]       = Field(None)
