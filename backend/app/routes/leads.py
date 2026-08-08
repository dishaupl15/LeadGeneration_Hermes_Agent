"""
Leads router  –  /leads

All route handlers live here.  Business logic is intentionally kept minimal
for Phase 1 (UI-only); the stubs below are wired and documented so Phase 2
(MongoDB + Hermes) can be dropped in without restructuring.

Current endpoints
─────────────────
GET    /leads              → list all leads (returns empty list for now)
POST   /leads              → create a lead   (echo back a mock response)
GET    /leads/{lead_id}    → get one lead     (returns 404 stub)
PATCH  /leads/{lead_id}    → update a lead   (returns 404 stub)
DELETE /leads/{lead_id}    → delete a lead   (returns 404 stub)
GET    /leads/categories   → list available industry categories
POST   /leads/generate-leads → AI-powered lead generation (returns dummy data for now)
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.models.lead import Category
from app.schemas.lead_schema import (
    ErrorResponse,
    GenerateLeadsRequest,
    GenerateLeadsResponse,
    GeneratedCompany,
    LeadCreateRequest,
    LeadResponse,
    LeadsListResponse,
    LeadUpdateRequest,
    MessageResponse,
)

router = APIRouter(
    prefix="/leads",
    tags=["Leads"],
    responses={
        404: {"model": ErrorResponse, "description": "Lead not found"},
        422: {"description": "Validation error"},
    },
)

# ── In-memory store (Phase 1 placeholder) ─────────────────────────────────────
# Replace with MongoDB collection in Phase 2.
_leads_store: list[dict] = []


# ── Helper ────────────────────────────────────────────────────────────────────

def _find_lead(lead_id: str) -> dict:
    """Return the lead dict or raise 404."""
    for lead in _leads_store:
        if lead["id"] == lead_id:
            return lead
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Lead with id '{lead_id}' not found.",
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/categories",
    summary="List industry categories",
    response_model=list[str],
)
def get_categories():
    """Return every available industry category (mirrors the frontend pill bar)."""
    return [c.value for c in Category]


@router.post(
    "/generate-leads",
    summary="Generate leads using AI",
    response_model=GenerateLeadsResponse,
    status_code=status.HTTP_200_OK,
)
def generate_leads(payload: GenerateLeadsRequest):
    """
    Generate B2B leads for a specific industry and city.

    **Phase 1**: Returns static dummy data for testing the frontend integration.
    **Phase 2**: Will integrate with Hermes AI to generate real leads from web scraping,
    business directories, and enrichment APIs.

    Args:
        payload: Industry, city, and count of leads to generate

    Returns:
        A list of generated companies with contact details
    """
    # ── Dummy data templates ──────────────────────────────────────────────────
    # In Phase 2, replace this entire block with a Hermes AI API call.

    company_prefixes = ["ABC", "XYZ", "Prime", "Global", "Metro", "Elite", "Smart", "Bright"]
    company_suffixes = {
        "Real Estate": ["Builders", "Realty", "Properties", "Estates", "Developers"],
        "E-Commerce": ["Mart", "Shop", "Store", "Bazaar", "Market"],
        "Information Technology": ["Tech", "Solutions", "Systems", "Software", "Digital"],
        "Healthcare": ["Hospital", "Clinic", "Care", "Medical", "Health"],
        "Manufacturing": ["Industries", "Manufacturing", "Fabricators", "Engineering"],
        "Education": ["Academy", "Institute", "School", "College", "University"],
        "Finance": ["Finance", "Capital", "Investments", "Bank", "Financial"],
        "Hotels": ["Hotel", "Inn", "Resorts", "Hospitality", "Suites"],
        "Construction": ["Construction", "Builders", "Infrastructure", "Contractors"],
        "Other": ["Enterprises", "Group", "Corporation", "Services", "Company"],
    }

    # Match industry or fallback to "Other"
    suffixes = company_suffixes.get(payload.industry, company_suffixes["Other"])

    companies = []
    for i in range(payload.count):
        prefix = company_prefixes[i % len(company_prefixes)]
        suffix = suffixes[i % len(suffixes)]
        company_name = f"{prefix} {suffix}"

        # Generate dummy contact details
        email_domain = company_name.lower().replace(" ", "")
        companies.append(
            GeneratedCompany(
                company_name=company_name,
                email=f"info@{email_domain}.com",
                phone=f"+91 {9800000000 + i:010d}",  # Indian phone format
                address=f"{payload.city}, India",
            )
        )

    return GenerateLeadsResponse(
        industry=payload.industry,
        city=payload.city,
        companies=companies,
    )


@router.get(
    "",
    summary="List all leads",
    response_model=LeadsListResponse,
)
def get_leads(
    category: Optional[Category] = Query(None, description="Filter by industry category"),
    search:   Optional[str]      = Query(None, description="Case-insensitive search across all fields"),
    page:     int                = Query(1,    ge=1,  description="Page number (1-based)"),
    per_page: int                = Query(20,   ge=1, le=100, description="Results per page"),
):
    """
    Return a paginated list of leads.

    Supports optional filtering by **category** and a full-text **search**
    across company_name, email, phone, and address.

    Phase 1: returns the in-memory store (starts empty).
    Phase 2: replace body with a MongoDB aggregation query.
    """
    results = list(_leads_store)

    # Category filter
    if category:
        results = [l for l in results if l["category"] == category.value]

    # Simple search filter
    if search:
        q = search.lower()
        results = [
            l for l in results
            if q in l["company_name"].lower()
            or q in l["email"].lower()
            or q in l["phone"].lower()
            or q in l["address"].lower()
        ]

    total = len(results)

    # Pagination
    start = (page - 1) * per_page
    page_results = results[start : start + per_page]

    return LeadsListResponse(
        total=total,
        leads=[LeadResponse(**l) for l in page_results],
        page=page,
        per_page=per_page,
    )


@router.post(
    "",
    summary="Create a new lead",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_lead(payload: LeadCreateRequest):
    """
    Create and persist a new lead.

    Phase 1: stored in the in-memory list.
    Phase 2: insert into MongoDB; Hermes AI enrichment hook goes here.
    """
    now = datetime.now(timezone.utc)
    new_lead = {
        "id":           str(uuid.uuid4()),
        "company_name": payload.company_name,
        "email":        payload.email,
        "phone":        payload.phone,
        "address":      payload.address,
        "category":     payload.category.value,
        "created_at":   now,
        "updated_at":   None,
    }
    _leads_store.append(new_lead)
    return LeadResponse(**new_lead)


@router.get(
    "/{lead_id}",
    summary="Get a single lead",
    response_model=LeadResponse,
)
def get_lead(lead_id: str):
    """Fetch one lead by its ID."""
    lead = _find_lead(lead_id)
    return LeadResponse(**lead)


@router.patch(
    "/{lead_id}",
    summary="Partially update a lead",
    response_model=LeadResponse,
)
def update_lead(lead_id: str, payload: LeadUpdateRequest):
    """
    Apply a partial update to an existing lead.
    Only the fields present in the request body are changed.
    """
    lead = _find_lead(lead_id)

    update_data = payload.model_dump(exclude_none=True)
    if "category" in update_data:
        update_data["category"] = update_data["category"].value

    lead.update(update_data)
    lead["updated_at"] = datetime.now(timezone.utc)

    return LeadResponse(**lead)


@router.delete(
    "/{lead_id}",
    summary="Delete a lead",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
def delete_lead(lead_id: str):
    """Remove a lead permanently."""
    lead = _find_lead(lead_id)
    _leads_store.remove(lead)
    return MessageResponse(message=f"Lead '{lead_id}' deleted successfully.")
