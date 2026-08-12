"""
src/models/generation_run.py
─────────────────────────────
Pydantic model + MongoDB schema for a single lead-generation run.

Every click of "Generate Leads" creates ONE document in the
'generation_history' collection.  This document is created at the START
of the run (status = "running") and updated throughout / at completion.

Collection: generation_history
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Log entry ────────────────────────────────────────────────────────────────

class RunLogEntry(BaseModel):
    timestamp: str   = Field(..., description="HH:MM:SS string from the server")
    level: str       = Field(..., description="INFO | SEARCH | FILTER | SCRAPE | EXTRACT | VALIDATION | DATABASE | COMPLETE | ERROR")
    stage: str       = Field(..., description="Which pipeline stage emitted this log")
    message: str     = Field(..., description="Human-readable log message")


# ── Run statistics ────────────────────────────────────────────────────────────

class RunStatistics(BaseModel):
    companies_discovered: int  = Field(default=0)
    companies_processed:  int  = Field(default=0)
    leads_generated:      int  = Field(default=0)
    duplicates:           int  = Field(default=0)
    rejected:             int  = Field(default=0)
    errors:               int  = Field(default=0)
    # Enrichment detail
    with_email:           int  = Field(default=0)
    with_phone:           int  = Field(default=0)
    with_founder:         int  = Field(default=0)
    contacts_found:       int  = Field(default=0)
    # Pipeline call counts
    companyenrich_calls:  int  = Field(default=0)
    serper_calls:         int  = Field(default=0)
    firecrawl_calls:      int  = Field(default=0)
    elapsed_seconds:      float = Field(default=0.0)


# ── Generation run document ───────────────────────────────────────────────────

class GenerationRun(BaseModel):
    """
    Represents a single lead-generation execution.
    Stored as a document in the 'generation_history' MongoDB collection.
    """
    run_id:           str                  = Field(..., description="Unique run identifier, e.g. RUN-abc123")
    category:         str                  = Field(..., description="Industry category searched")
    search_query:     str                  = Field(default="", description="Resolved query string")
    state:            str                  = Field(default="", description="Indian state")
    district:         str                  = Field(default="", description="District/city (may be empty)")
    requested_count:  int                  = Field(..., description="Target number of leads requested")
    generated_count:  int                  = Field(default=0, description="Actual new leads inserted")
    updated_count:    int                  = Field(default=0, description="Existing leads updated (deduped)")
    status:           str                  = Field(default="running", description="running | completed | failed")
    started_at:       str                  = Field(..., description="UTC ISO-8601 start timestamp")
    completed_at:     Optional[str]        = Field(default=None)
    failed_at:        Optional[str]        = Field(default=None)
    duration_seconds: Optional[float]      = Field(default=None)
    created_at:       str                  = Field(..., description="Same as started_at for index purposes")
    source:           str                  = Field(default="lead_generation")
    filters:          dict                 = Field(default_factory=dict, description="All input filters used")
    lead_ids:         list[str]            = Field(default_factory=list, description="MongoDB _id strings of leads created in this run")
    logs:             list[dict]           = Field(default_factory=list, description="Ordered log entries for this run")
    statistics:       dict                 = Field(default_factory=dict, description="Pipeline statistics")
    error_message:    Optional[str]        = Field(default=None)
    pipeline_stats:   Optional[dict]       = Field(default=None)

    class Config:
        extra = "allow"
