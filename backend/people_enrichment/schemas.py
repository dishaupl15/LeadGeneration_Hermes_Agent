"""
people_enrichment/schemas.py
──────────────────────────────
Pydantic models for the people-enrichment orchestrator output.
These are the ONLY types returned from the orchestrator.
Provider-specific types (PeopleDataLabsContact, ProspeoContact, etc.) are
never exposed beyond this layer.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Single merged contact ─────────────────────────────────────────────────────

class EnrichedContact(BaseModel):
    """
    One decision-maker contact after deduplication and merging across providers.

    sources: list of provider names that contributed data for this contact.
    """
    name:         Optional[str]        = Field(None)
    title:        Optional[str]        = Field(None)
    email:        Optional[str]        = Field(None)
    phone:        Optional[str]        = Field(None)
    linkedin_url: Optional[str]        = Field(None)
    sources:      list[str]            = Field(default_factory=list)
    confidence:   float                = Field(default=0.0, ge=0.0, le=1.0)


# ── Per-provider stats ────────────────────────────────────────────────────────

class ProviderStats(BaseModel):
    called:         bool = False
    contacts_found: int  = 0
    emails_found:   int  = 0
    phones_found:   int  = 0
    api_calls:      int  = 0
    error:          Optional[str] = None
    skipped_reason: Optional[str] = None   # "target_reached" | "auth_failed" | "not_configured"


# ── Full orchestrator result (single company) ─────────────────────────────────

class PeopleEnrichmentResult(BaseModel):
    """
    Final output of the people-enrichment orchestrator for one company.
    """
    contacts:        list[EnrichedContact]     = Field(default_factory=list)
    contacts_found:  int                       = Field(default=0)
    emails_found:    int                       = Field(default=0)
    phones_found:    int                       = Field(default=0)
    contacts_with_both: int                    = Field(default=0,
        description="Contacts that have both email AND phone")
    pdl_contacts:    int                       = Field(default=0,
        description="Contacts attributed to PDL (may be merged)")
    prospeo_contacts: int                      = Field(default=0,
        description="Contacts attributed to Prospeo (may be merged)")
    contactout_contacts: int                   = Field(default=0,
        description="Contacts attributed to ContactOut (may be merged)")
    providers_used:  list[str]                 = Field(default_factory=list)
    provider_stats:  dict[str, ProviderStats]  = Field(default_factory=dict)
    target_contacts: int                       = Field(default=2)
    target_reached:  bool                      = Field(default=False)
    elapsed_seconds: float                     = Field(default=0.0)
    error:           Optional[str]             = Field(None)


# ── Batch run statistics (across many companies) ──────────────────────────────

class PeopleEnrichmentBatchStats(BaseModel):
    """
    Aggregated statistics for a batch run across multiple companies.
    Returned by batch_enrich_contacts().
    """
    companies_processed:   int   = 0
    companies_with_contacts: int = 0
    total_contacts:        int   = 0
    contacts_with_email:   int   = 0
    contacts_with_phone:   int   = 0
    contacts_with_both:    int   = 0
    pdl_contacts:          int   = 0
    prospeo_contacts:      int   = 0
    contactout_contacts:   int   = 0
    provider_failures:     dict[str, int] = Field(default_factory=dict,
        description="provider_name → count of companies where it returned an error")
    elapsed_seconds:       float = 0.0
