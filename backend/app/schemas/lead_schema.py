"""
Pydantic schemas (DTOs) for the Lead resource.

Separation of concerns:
  models/lead.py      → internal domain / storage model
  schemas/lead_schema → what the API accepts (requests) and returns (responses)

This makes it safe to change the DB schema without breaking the API contract
and vice-versa.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.lead import Category


# ── Request schemas ───────────────────────────────────────────────────────────

class LeadCreateRequest(BaseModel):
    """Payload required to create a new lead (POST /leads)."""

    company_name: str      = Field(..., min_length=1, max_length=200, example="Acme Corp")
    email:        EmailStr = Field(..., example="hello@acme.com")
    phone:        str      = Field(..., example="+1-555-0100")
    address:      str      = Field(..., example="100 Main St, New York, NY")
    category:     Category = Field(..., example=Category.REAL_ESTATE)


class LeadUpdateRequest(BaseModel):
    """All fields optional so callers can send partial updates (PATCH /leads/{id})."""

    company_name: Optional[str]      = Field(None, min_length=1, max_length=200)
    email:        Optional[EmailStr] = None
    phone:        Optional[str]      = None
    address:      Optional[str]      = None
    category:     Optional[Category] = None


class GenerateLeadsRequest(BaseModel):
    """Request payload for AI-powered lead generation (POST /generate-leads)."""

    industry: str = Field(
        ...,
        min_length=1,
        max_length=100,
        example="Real Estate",
        description="Target industry/category"
    )
    city: str = Field(
        ...,
        min_length=1,
        max_length=100,
        example="Pune",
        description="City or region to search for leads"
    )
    count: int = Field(
        default=10,
        ge=1,
        le=100,
        example=10,
        description="Number of leads to generate (1-100)"
    )


# ── Response schemas ──────────────────────────────────────────────────────────

class LeadResponse(BaseModel):
    """Shape returned for a single lead."""

    id:           str      = Field(..., example="abc-123")
    company_name: str      = Field(..., example="Acme Corp")
    email:        EmailStr = Field(..., example="hello@acme.com")
    phone:        str      = Field(..., example="+1-555-0100")
    address:      str      = Field(..., example="100 Main St, New York, NY")
    category:     Category = Field(..., example=Category.REAL_ESTATE)
    created_at:   datetime
    updated_at:   Optional[datetime] = None

    class Config:
        from_attributes = True   # allows ORM / Beanie document → schema conversion


class LeadsListResponse(BaseModel):
    """Paginated list of leads."""

    total:   int              = Field(..., example=42)
    leads:   list[LeadResponse]
    page:    int              = Field(default=1, example=1)
    per_page: int             = Field(default=20, example=20)


class GeneratedCompany(BaseModel):
    """A single company in the AI-generated leads response."""

    company_name: str = Field(..., example="ABC Builders")
    email:        str = Field(..., example="info@abcbuilders.com")
    phone:        str = Field(..., example="+91 9876543210")
    address:      str = Field(..., example="Pune, Maharashtra")


class GenerateLeadsResponse(BaseModel):
    """Response from the lead generation endpoint."""

    industry:  str                   = Field(..., example="Real Estate")
    city:      str                   = Field(..., example="Pune")
    companies: list[GeneratedCompany] = Field(..., example=[
        {
            "company_name": "ABC Builders",
            "email": "info@abcbuilders.com",
            "phone": "+91 9876543210",
            "address": "Pune, Maharashtra"
        },
        {
            "company_name": "XYZ Realty",
            "email": "contact@xyzrealty.com",
            "phone": "+91 9988776655",
            "address": "Pune, Maharashtra"
        }
    ])


# ── Generic / utility schemas ─────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Generic success/status message."""

    message: str = Field(..., example="Lead Generation Backend Running")


class ErrorResponse(BaseModel):
    """Uniform error shape returned for 4xx / 5xx responses."""

    detail: str = Field(..., example="Lead with id 'abc-123' not found.")
    code:   Optional[str] = Field(None, example="NOT_FOUND")
