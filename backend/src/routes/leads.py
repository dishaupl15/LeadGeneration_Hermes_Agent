"""
src/routes/leads.py
--------------------
Leads API router.

Endpoints
---------
GET    /leads/categories        list all industry categories
POST   /leads/generate-leads    call Hermes agent, upsert to MongoDB, return DB docs
GET    /leads                   paginated list of stored leads
POST   /leads                   create a lead manually
GET    /leads/{lead_id}         fetch a single lead by ID
PATCH  /leads/{lead_id}         partially update a lead
DELETE /leads/{lead_id}         permanently delete a lead
GET    /debug/database          MongoDB connectivity + document count
GET    /debug/sample            first 5 documents from the leads collection
"""

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from src.config.mongo import COLLECTION_NAME, get_db
from src.controllers.lead_controller import LeadController, LeadNotFoundError
from src.models.lead import Category
from src.schemas.lead_schema import (
    ErrorResponse,
    GenerateLeadsRequest,
    MongoLeadsResponse,
    LeadCreateRequest,
    LeadResponse,
    LeadsListResponse,
    LeadUpdateRequest,
    MessageResponse,
)
from app.services.hermes_service import call_hermes_agent

router = APIRouter(
    tags=["Leads"],
    responses={
        404: {"model": ErrorResponse, "description": "Lead not found"},
        422: {"description": "Validation error"},
    },
)


def _handle_not_found(exc: LeadNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/leads/categories", summary="List all industry categories",
            response_model=list[str], tags=["Leads"])
def get_categories():
    return LeadController.list_categories()


# ── Generate leads via Hermes agent ──────────────────────────────────────────

@router.post(
    "/leads/generate-leads",
    summary="Generate B2B leads via Hermes agent, upsert to MongoDB, return DB documents",
    response_model=MongoLeadsResponse,
    status_code=status.HTTP_200_OK,
    tags=["Leads"],
)
async def generate_leads(payload: GenerateLeadsRequest):
    """
    Full flow:
    1. Resolve query from request body.
    2. Call Hermes Agent → lead-generation-search skill → leadgen.py.
    3. Deduplicate companies by website (case-insensitive).
    4. Upsert each company into MongoDB:
         - website already exists → update fields, set updated_at
         - new company            → insert with created_at
    5. Fetch the upserted documents back from MongoDB by website.
    6. Return MongoDB documents to the frontend (not raw Hermes output).
    """
    # ── 1. Resolve query ──────────────────────────────────────────────────────
    try:
        query = payload.resolved_query()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # ── 2. Call Hermes ────────────────────────────────────────────────────────
    try:
        hermes_result = await call_hermes_agent(query, num=payload.count)
    except RuntimeError as exc:
        import traceback
        traceback.print_exc()
        print(f"[generate_leads] RuntimeError repr: {exc!r}")
        print(f"[generate_leads] RuntimeError args: {exc.args!r}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hermes agent error: {exc}",
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[generate_leads] Unexpected exception: {type(exc).__name__}: {exc!r}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected error in lead generation: {type(exc).__name__}: {exc}",
        )

    raw_companies: list[dict] = hermes_result.get("companies", [])

    # ── 3. Deduplicate by website (domain-level) ──────────────────────────────
    seen_websites: set[str] = set()
    unique: list[dict] = []
    for c in raw_companies:
        key = c.get("website", "").lower().strip().rstrip("/")
        if key and key not in seen_websites:
            seen_websites.add(key)
            unique.append(c)
        elif not key:
            # No website — deduplicate by company_name instead
            name_key = c.get("company_name", "").lower().strip()
            if name_key and name_key not in seen_websites:
                seen_websites.add(name_key)
                unique.append(c)

    print(f"Upserting {len(unique)} companies into MongoDB...")

    # ── 4. Upsert each company (insert new, update existing by website) ───────
    db = get_db()
    collection = db[COLLECTION_NAME]
    now = datetime.now(timezone.utc)
    inserted_count = 0
    updated_count  = 0
    upserted_websites: list[str] = []

    for company in unique:
        website = company.get("website", "").strip()

        # Fields to always set on insert (only applied when document is new)
        on_insert = {"created_at": now}

        # Fields to set on every upsert (insert or update)
        set_fields = {
            "company_name": company.get("company_name", ""),
            "website":      website,
            "emails":       company.get("emails", []),
            "phones":       company.get("phones", []),
            "address":      company.get("address", ""),
            "city":         company.get("city", ""),
            "state":        company.get("state", ""),
            "country":      company.get("country", ""),
            "postal_code":  company.get("postal_code", ""),
            "sources":      company.get("sources", []),
            "updated_at":   now,
        }

        # Match on website if present, otherwise on company_name
        filter_key = (
            {"website": website}
            if website
            else {"company_name": company.get("company_name", "")}
        )

        result = await collection.update_one(
            filter_key,
            {
                "$set":         set_fields,
                "$setOnInsert": on_insert,
            },
            upsert=True,
        )

        if result.upserted_id:
            inserted_count += 1
        else:
            updated_count += 1

        upserted_websites.append(website or company.get("company_name", ""))

    print(f"MongoDB upsert complete — inserted: {inserted_count}, updated: {updated_count}")

    # ── 5. Fetch the upserted documents from MongoDB ──────────────────────────
    # Build a filter that matches all the websites/names we just upserted
    website_list  = [w for w in upserted_websites if w.startswith("http")]
    name_list     = [w for w in upserted_websites if not w.startswith("http")]

    fetch_filter: dict = {}
    if website_list and name_list:
        fetch_filter = {"$or": [
            {"website":      {"$in": website_list}},
            {"company_name": {"$in": name_list}},
        ]}
    elif website_list:
        fetch_filter = {"website": {"$in": website_list}}
    elif name_list:
        fetch_filter = {"company_name": {"$in": name_list}}

    cursor = collection.find(fetch_filter).sort("updated_at", -1)
    db_docs = await cursor.to_list(length=len(unique) + 10)

    # Serialize ObjectId → string for JSON response
    leads_out = []
    for doc in db_docs:
        doc["id"] = str(doc.pop("_id"))
        # Ensure datetime fields are serializable
        for ts_field in ("created_at", "updated_at"):
            if isinstance(doc.get(ts_field), datetime):
                doc[ts_field] = doc[ts_field].isoformat()
        leads_out.append(doc)

    print(f"Returning {len(leads_out)} documents from MongoDB to frontend")

    return MongoLeadsResponse(
        success=True,
        inserted=inserted_count,
        updated=updated_count,
        total=len(leads_out),
        query=hermes_result.get("query", query),
        timestamp=hermes_result.get("timestamp", now.isoformat()),
        leads=leads_out,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get(
    "/leads",
    summary="List all leads from MongoDB",
    response_model=MongoLeadsResponse,
    tags=["Leads"],
)
async def get_leads(
    search:   Optional[str] = Query(None, description="Filter by company name (case-insensitive)"),
    page:     int           = Query(1,   ge=1),
    per_page: int           = Query(100, ge=1, le=500),
):
    """
    Fetch documents directly from MongoDB — no Hermes, no AI, no scraping.
    Returns the same MongoLeadsResponse shape as POST /leads/generate-leads
    so the frontend can use a single data model for both endpoints.
    """
    db = get_db()
    collection = db[COLLECTION_NAME]

    # Build filter
    mongo_filter: dict = {}
    if search:
        mongo_filter["company_name"] = {"$regex": search, "$options": "i"}

    # Count total matching docs
    total = await collection.count_documents(mongo_filter)

    # Fetch page
    skip = (page - 1) * per_page
    cursor = collection.find(mongo_filter).sort("created_at", -1).skip(skip).limit(per_page)
    db_docs = await cursor.to_list(length=per_page)

    # Serialize ObjectId → string
    leads_out = []
    for doc in db_docs:
        doc["id"] = str(doc.pop("_id"))
        for ts_field in ("created_at", "updated_at"):
            if isinstance(doc.get(ts_field), datetime):
                doc[ts_field] = doc[ts_field].isoformat()
        leads_out.append(doc)

    return MongoLeadsResponse(
        success=True,
        inserted=0,
        updated=0,
        total=total,
        query="",
        timestamp=datetime.now(timezone.utc).isoformat(),
        leads=leads_out,
    )


@router.post("/leads", summary="Create a new lead manually",
             response_model=LeadResponse, status_code=status.HTTP_201_CREATED,
             tags=["Leads"])
def create_lead(payload: LeadCreateRequest):
    return LeadController.create_lead(payload)


@router.get("/leads/{lead_id}", summary="Get a single lead",
            response_model=LeadResponse, tags=["Leads"])
def get_lead(lead_id: str):
    try:
        return LeadController.get_lead(lead_id)
    except LeadNotFoundError as exc:
        raise _handle_not_found(exc)


@router.patch("/leads/{lead_id}", summary="Partially update a lead",
              response_model=LeadResponse, tags=["Leads"])
def update_lead(lead_id: str, payload: LeadUpdateRequest):
    try:
        return LeadController.update_lead(lead_id, payload)
    except LeadNotFoundError as exc:
        raise _handle_not_found(exc)


@router.delete("/leads/{lead_id}", summary="Delete a lead",
               response_model=MessageResponse, tags=["Leads"])
def delete_lead(lead_id: str):
    try:
        return LeadController.delete_lead(lead_id)
    except LeadNotFoundError as exc:
        raise _handle_not_found(exc)


# ── Debug endpoints ───────────────────────────────────────────────────────────

@router.get("/debug/database", summary="MongoDB connectivity check",
            response_model=dict, tags=["Debug"])
async def debug_database():
    db = get_db()
    collection = db[COLLECTION_NAME]
    count = await collection.count_documents({})
    return {
        "connected":      True,
        "database":       db.name,
        "collection":     COLLECTION_NAME,
        "document_count": count,
    }


@router.get("/debug/sample", summary="First 5 documents from leads collection",
            response_model=list[dict[str, Any]], tags=["Debug"])
async def debug_sample():
    db = get_db()
    collection = db[COLLECTION_NAME]
    cursor = collection.find({}, {"_id": 0}).limit(5)
    docs = await cursor.to_list(length=5)
    return docs
