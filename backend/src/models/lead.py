"""
src/models/lead.py
───────────────────
Domain model for a CRM Lead.

Responsibility: define the *shape* of a lead as the application understands it
internally — independent of how it arrives over HTTP or how it's stored in the DB.

Phase 2 expansion plan:
  - Replace `Lead(BaseModel)` with a Beanie Document for MongoDB persistence.
  - Add an `index` declaration for common query fields (category, created_at).
  - Motor async methods will live in a repository layer, not here.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ── Industry categories ───────────────────────────────────────────────────────

class Category(str, Enum):
    """
    Enumeration of supported industry verticals.
    Values must match the category labels in the React frontend (categories.js) exactly.
    """
    TECHNOLOGY          = "Technology"
    SAAS                = "SaaS"
    AI                  = "AI"
    FINTECH             = "FinTech"
    HEALTHCARE          = "Healthcare"
    PHARMA              = "Pharma"
    MANUFACTURING       = "Manufacturing"
    CONSTRUCTION        = "Construction"
    REAL_ESTATE         = "Real Estate"
    EDUCATION           = "Education"
    LOGISTICS           = "Logistics"
    AUTOMOTIVE          = "Automotive"
    RETAIL              = "Retail"
    E_COMMERCE          = "E-Commerce"
    HOSPITALITY         = "Hospitality"
    TRAVEL              = "Travel"
    ENERGY              = "Energy"
    AGRICULTURE         = "Agriculture"
    MEDIA               = "Media"
    MARKETING           = "Marketing"
    CONSULTING          = "Consulting"
    LEGAL               = "Legal"
    FINANCE             = "Finance"
    INSURANCE           = "Insurance"
    TELECOMMUNICATIONS  = "Telecommunications"
    CYBERSECURITY       = "Cybersecurity"
    BIOTECH             = "Biotech"
    AEROSPACE           = "Aerospace"


# ── Lead domain model ─────────────────────────────────────────────────────────

class Lead(BaseModel):
    """
    Core CRM lead entity.

    Column mapping (matches the frontend table):
      company_name  →  Company Name
      email         →  Email
      phone         →  Phone
      address       →  Address
    """

    id:           str      = Field(..., description="Unique identifier (UUID / MongoDB ObjectId)")
    company_name: str      = Field(..., min_length=1, max_length=200, description="Trading or legal company name")
    email:        EmailStr = Field(..., description="Primary business contact email")
    phone:        str      = Field(..., description="Contact phone number")
    address:      str      = Field(..., description="Full address including city and country")
    category:     Category = Field(..., description="Industry vertical")

    # Audit fields
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC creation timestamp",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="UTC last-update timestamp",
    )

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "id":           "abc-123",
                "company_name": "Acme Real Estate Ltd.",
                "email":        "contact@acmerealestate.com",
                "phone":        "+91 9876543210",
                "address":      "100 MG Road, Pune, Maharashtra, India",
                "category":     "Real Estate",
                "created_at":   "2026-08-06T10:00:00Z",
                "updated_at":   None,
            }
        }
