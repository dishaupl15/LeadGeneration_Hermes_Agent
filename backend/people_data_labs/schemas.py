"""
people_data_labs/schemas.py
────────────────────────────
Pydantic schemas for the PDL contact-discovery module.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Input ─────────────────────────────────────────────────────────────────────

class PDLCompanyInput(BaseModel):
    """Minimum information needed to search PDL for contacts at a company."""
    company_name: str          = Field(..., min_length=1, example="Getwell Hospital")
    domain:       Optional[str] = Field(None, example="getwellhospitals.com")
    website:      Optional[str] = Field(None, example="https://getwellhospitals.com")
    place_id:     Optional[str] = Field(None, example="ChIJtest123")
    phone:        Optional[str] = Field(None, example="+91 9876543210")
    address:      Optional[str] = Field(None, example="Nagpur, Maharashtra")


# ── Contact output ────────────────────────────────────────────────────────────

class PeopleDataLabsContact(BaseModel):
    """A single business contact discovered via PDL."""
    name:           Optional[str]   = Field(None,  example="Rajiv Sharma")
    designation:    Optional[str]   = Field(None,  example="Head of Human Resources")
    email:          Optional[str]   = Field(None,  example="rajiv.sharma@getwellhospitals.com")
    phone:          Optional[str]   = Field(None,  example="+91 9988776655",
                                            description="Person-level phone from PDL — null if not provided")
    email_type:     Optional[str]   = Field(
        None, example="hr",
        description=(
            "Role classification: founder | co_founder | owner | ceo | "
            "managing_director | director | hr | talent_acquisition | recruitment | other"
        ),
    )
    linkedin_url:   Optional[str]   = Field(None,  example="https://www.linkedin.com/in/rajivsharma")
    company_name:   Optional[str]   = Field(None,  example="Getwell Hospital")
    company_domain: Optional[str]   = Field(None,  example="getwellhospitals.com")
    source:         str             = Field(default="people_data_labs")
    confidence:     float           = Field(default=0.0, ge=0.0, le=1.0, example=0.92)


# ── Search result ─────────────────────────────────────────────────────────────

class PeopleDataLabsResult(BaseModel):
    """Full result for one company search."""
    company_name:    str                      = Field(..., example="Getwell Hospital")
    company_domain:  Optional[str]            = Field(None)
    contacts:        list[PeopleDataLabsContact] = Field(default_factory=list)
    contacts_found:  int                      = Field(default=0)
    emails_found:    int                      = Field(default=0)
    phones_found:    int                      = Field(default=0)
    pdl_api_calls:   int                      = Field(default=0)
    elapsed_seconds: float                    = Field(default=0.0)
    error:           Optional[str]            = Field(None,
                                                       description="'auth_failed' | error message | None")


# ── Health response ───────────────────────────────────────────────────────────

class PDLHealthResponse(BaseModel):
    module:                  str   = "people_data_labs"
    configured:              bool
    status:                  str
    message:                 str
    max_contacts_per_company: int
    timeout_seconds:         float
