"""
src/schemas/lead_schema.py
───────────────────────────
Pydantic DTOs (Data Transfer Objects) for the Lead resource.

Why separate from models/?
  - models/lead.py   → internal domain representation / future DB document
  - schemas/         → what the API *accepts* (requests) and *returns* (responses)

This boundary lets the API contract evolve independently from the storage layer.
For example, you can add internal DB fields to Lead without exposing them in
LeadResponse, or accept different input shapes without changing the model.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from src.models.lead import Category


# ── Request schemas ───────────────────────────────────────────────────────────

class LeadCreateRequest(BaseModel):
    """Payload to create a single lead  (POST /leads)."""

    company_name: str      = Field(..., min_length=1, max_length=200, example="Acme Corp")
    email:        EmailStr = Field(..., example="hello@acme.com")
    phone:        str      = Field(..., example="+91 9876543210")
    address:      str      = Field(..., example="Pune, Maharashtra, India")
    category:     Category = Field(..., example=Category.REAL_ESTATE)


class LeadUpdateRequest(BaseModel):
    """Partial update payload  (PATCH /leads/{id}).  All fields optional."""

    company_name: Optional[str]      = Field(None, min_length=1, max_length=200)
    email:        Optional[EmailStr] = None
    phone:        Optional[str]      = None
    address:      Optional[str]      = None
    category:     Optional[Category] = None


class GenerateLeadsRequest(BaseModel):
    """
    Request payload for Hermes-powered lead generation.
    POST /leads/generate-leads

    Accepts either:
      - query  : free-form natural language  (e.g. "Real estate companies in Pune")
      - OR the legacy industry + city + count fields (still supported)
    """

    query: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=500,
        example="Real estate companies in Pune",
        description="Natural-language search query sent to the Hermes agent",
    )
    # Legacy fields kept for backward compatibility
    industry: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        example="Real Estate",
        description="Target industry / category (legacy — prefer query)",
    )
    city: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        example="Pune",
        description="City or region (legacy — prefer query)",
    )
    count: int = Field(
        default=10,
        ge=1,
        le=100,
        example=10,
        description="Number of leads to generate (1 – 100)",
    )

    def resolved_query(self) -> str:
        """Return the effective query string regardless of which fields were sent."""
        if self.query:
            return self.query
        parts = []
        if self.industry:
            parts.append(self.industry)
        if self.city:
            parts.append(f"in {self.city}")
        if not parts:
            raise ValueError("Provide either 'query' or both 'industry' and 'city'.")
        return " ".join(parts)


# ── Response schemas ──────────────────────────────────────────────────────────

class LeadResponse(BaseModel):
    """Single lead returned by the API."""

    id:           str      = Field(..., example="abc-123")
    company_name: str      = Field(..., example="Acme Corp")
    email:        EmailStr = Field(..., example="hello@acme.com")
    phone:        str      = Field(..., example="+91 9876543210")
    address:      str      = Field(..., example="Pune, Maharashtra, India")
    category:     Category = Field(..., example=Category.REAL_ESTATE)
    created_at:   datetime
    updated_at:   Optional[datetime] = None

    class Config:
        from_attributes = True   # enables ORM-mode / Beanie document coercion


class LeadsListResponse(BaseModel):
    """Paginated list of leads."""

    total:    int              = Field(..., example=42)
    leads:    list[LeadResponse]
    page:     int              = Field(default=1,  ge=1, example=1)
    per_page: int              = Field(default=20, ge=1, example=20)


class GeneratedCompany(BaseModel):
    """A single company returned by the generate-leads endpoint."""

    company_name: str       = Field(..., example="ABC Builders")
    website:      str       = Field(default="", example="https://abcbuilders.com")
    emails:       list[str] = Field(default_factory=list, example=["info@abcbuilders.com"])
    phones:       list[str] = Field(default_factory=list, example=["+91 9876543210"])
    address:      str       = Field(default="", example="Baner Road, Pune")
    city:         str       = Field(default="", example="Pune")
    state:        str       = Field(default="", example="Maharashtra")
    country:      str       = Field(default="India", example="India")


class GenerateLeadsResponse(BaseModel):
    """Full response from POST /leads/generate-leads."""

    industry:  str                    = Field(..., example="Real Estate")
    city:      str                    = Field(..., example="Pune")
    companies: list[GeneratedCompany] = Field(
        ...,
        example=[
            {
                "company_name": "ABC Builders",
                "website":      "https://abcbuilders.com",
                "emails":       ["info@abcbuilders.com"],
                "phones":       ["+91 9876543210"],
                "address":      "Baner Road",
                "city":         "Pune",
                "state":        "Maharashtra",
                "country":      "India",
            },
        ],
    )


class InsertLeadsResponse(BaseModel):
    """Returned by generate-leads after persisting to MongoDB."""

    success:  bool = Field(..., example=True)
    inserted: int  = Field(..., example=8)


class HermesCompany(BaseModel):
    """A single company as returned by the Hermes / leadgen.py pipeline."""

    company_name: str       = Field(default="", example="ABC Builders")
    website:      str       = Field(default="", example="https://abcbuilders.com")
    emails:       list[str] = Field(default_factory=list)
    phones:       list[str] = Field(default_factory=list)
    address:      str       = Field(default="")
    city:         str       = Field(default="")
    state:        str       = Field(default="")
    country:      str       = Field(default="")
    postal_code:  str       = Field(default="")
    sources:      list[str] = Field(default_factory=list)

    class Config:
        extra = "allow"


class HermesLeadsResponse(BaseModel):
    """Legacy — kept for backward compatibility. Not used by routes."""

    success:   bool              = Field(..., example=True)
    inserted:  int               = Field(..., example=8)
    query:     str               = Field(..., example="Real estate companies in Pune")
    timestamp: str               = Field(..., example="2026-08-06T12:00:00+00:00")
    companies: list[HermesCompany] = Field(default_factory=list)


class MongoLeadDoc(BaseModel):
    """
    A single lead document as stored in and returned from MongoDB.

    _id is serialized to 'id' (string) before returning to the frontend.
    All fields use the same names as the MongoDB document — no mapping needed.

    Legacy fields (emails, phones, website, etc.) are kept unchanged so old
    documents without the enriched fields continue to deserialise correctly.
    New enriched fields are all Optional with safe defaults.
    """

    id:           str       = Field(..., example="64f1a2b3c4d5e6f7a8b9c0d1")
    company_name: str       = Field(default="")
    website:      str       = Field(default="")

    # ── Legacy contact arrays (kept for backward compat) ──────────────────
    emails:       list[str] = Field(default_factory=list)
    phones:       list[str] = Field(default_factory=list)

    # ── Address fields ─────────────────────────────────────────────────────
    address:      str       = Field(default="")
    city:         str       = Field(default="")
    state:        str       = Field(default="")
    country:      str       = Field(default="")
    postal_code:  str       = Field(default="")
    sources:      list[str] = Field(default_factory=list)

    # ── Enriched contact fields (new — None on old documents) ─────────────
    email:          Optional[str]   = Field(default=None,
                                            description="Best single validated business email")
    company_number: Optional[str]   = Field(default=None,
                                            description="Best single business/switchboard phone")
    founder_name:   Optional[str]   = Field(default=None,
                                            description="Publicly listed founder/CEO name")
    founder_number: Optional[str]   = Field(default=None,
                                            description="Publicly listed founder professional number")
    source_url:     Optional[str]   = Field(default=None,
                                            description="URL where the lead/contact was found")
    last_verified:  Optional[str]   = Field(default=None,
                                            description="UTC ISO timestamp of last successful enrichment")
    confidence:     float           = Field(default=0.0,
                                            description="Evidence-based confidence score 0.0–1.0")

    # ── Hermes source trace ────────────────────────────────────────────────
    research_source:  Optional[str]       = Field(
        default=None,
        description="Research engine that generated this lead (e.g. 'hermes')"
    )
    research_sources: list[str]           = Field(
        default_factory=list,
        description="URLs of pages Hermes researched to build this lead"
    )

    # ── Audit timestamps ───────────────────────────────────────────────────
    created_at:   Optional[str] = Field(default=None)
    updated_at:   Optional[str] = Field(default=None)

    # ── Field-level evidence model ─────────────────────────────────────────
    # Internal waterfall metadata: which provider contributed each field.
    # Stored in MongoDB so audit tools can show provider breakdown.
    # Shape: {"email": {"value": "...", "source": "hunter", "status": "hunter_valid"}, ...}
    # Note: stored in MongoDB as "_field_verification" but exposed here without leading underscore.
    field_verification: Optional[dict] = Field(default=None, alias="_field_verification")

    class Config:
        extra = "allow"                # tolerate any extra fields stored in MongoDB
        populate_by_name = True        # allow both alias and field name


class MongoLeadsResponse(BaseModel):
    """
    Response returned by POST /leads/generate-leads.

    Contains documents fetched directly from MongoDB after the upsert —
    NOT the raw Hermes output. The frontend always displays this data.
    """

    success:   bool             = Field(..., example=True)
    inserted:  int              = Field(..., example=5,  description="New documents created")
    updated:   int              = Field(..., example=3,  description="Existing documents updated")
    total:     int              = Field(..., example=8,  description="Total documents returned")
    query:     str              = Field(..., example="Real estate companies in Pune")
    timestamp: str              = Field(..., example="2026-08-06T12:00:00+00:00")
    leads:     list[MongoLeadDoc] = Field(default_factory=list)

    # Pipeline statistics exposed for audit tooling
    # Shape: {serper_calls, firecrawl_calls, hunter_calls, apollo_calls,
    #          pdl_calls, google_places_calls, llm_calls, hermes_calls,
    #          elapsed_seconds, ...}
    pipeline_stats: Optional[dict] = Field(
        default=None,
        description="Provider call counts and execution statistics from the pipeline run",
    )


# ── Utility schemas ───────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Generic success / status message."""

    message: str = Field(..., example="Lead Generation Backend Running")


class ErrorResponse(BaseModel):
    """Uniform error envelope returned for 4xx / 5xx responses."""

    detail: str            = Field(..., example="Lead with id 'abc-123' not found.")
    code:   Optional[str]  = Field(None, example="NOT_FOUND")
