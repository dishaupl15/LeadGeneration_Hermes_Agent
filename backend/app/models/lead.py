"""
Lead domain model.

This module defines the internal representation of a Lead.
Currently backed by a plain Python dataclass / Pydantic model
so the rest of the application has a stable interface to code against.

When MongoDB is added, this file will grow to include:
  - Motor/Beanie document class
  - Collection name
  - Indexes
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ── Industry category ─────────────────────────────────────────────────────────

class Category(str, Enum):
    REAL_ESTATE            = "Real Estate"
    E_COMMERCE             = "E-Commerce"
    INFORMATION_TECHNOLOGY = "Information Technology"
    HEALTHCARE             = "Healthcare"
    MANUFACTURING          = "Manufacturing"
    EDUCATION              = "Education"
    FINANCE                = "Finance"
    HOTELS                 = "Hotels"
    CONSTRUCTION           = "Construction"
    OTHER                  = "Other"


# ── Core lead model ───────────────────────────────────────────────────────────

class Lead(BaseModel):
    """
    Internal domain model for a CRM lead.

    Fields intentionally mirror the frontend table columns so the API
    contract is obvious:  Company Name | Email | Phone | Address
    """

    id: str = Field(..., description="Unique identifier (UUID or MongoDB ObjectId later)")
    company_name: str  = Field(..., min_length=1, max_length=200, description="Legal or trading name of the company")
    email:        EmailStr = Field(..., description="Primary business contact email")
    phone:        str  = Field(..., description="Contact phone number (any format)")
    address:      str  = Field(..., description="Full street / city / country address")
    category:     Category = Field(..., description="Industry vertical this lead belongs to")

    # ── Audit timestamps ──────────────────────────────────────────────────────
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the lead was created",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the last update (None if never updated)",
    )

    class Config:
        # Allow population by field name AND alias
        populate_by_name = True
        # Pretty JSON examples in auto-generated docs
        json_schema_extra = {
            "example": {
                "id": "abc-123",
                "company_name": "Acme Real Estate Ltd.",
                "email": "contact@acmerealestate.com",
                "phone": "+1-555-0100",
                "address": "100 Main Street, New York, NY 10001, USA",
                "category": "Real Estate",
                "created_at": "2026-08-06T10:00:00Z",
                "updated_at": None,
            }
        }
