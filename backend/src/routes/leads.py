"""
src/routes/leads.py
--------------------
Leads API router.

Production flow for POST /leads/generate-leads:
  UI → FastAPI → Google Maps discovery → CompanyEnrich → Serper → Firecrawl
  → NORMALIZE → VALIDATE → CONFIDENCE
  → [MONGODB PRE-DEDUP]  ← check existing leads by website/company_name
  → INSERT new leads only (skip existing)
  → return ONLY newly inserted leads to UI

Category-wise storage:
  Every generated lead is stored in a collection named leads_{category_slug}.
  e.g.  Construction → leads_construction
        Real Estate  → leads_real_estate
  The 'categories' collection lists all known industry names (seeded on startup).

Endpoints
---------
GET    /leads/categories        list all industry categories (from DB)
POST   /leads/generate-leads    pipeline → upsert MongoDB → return NEW leads only
GET    /leads                   paginated list of stored leads
POST   /leads                   create a lead manually
GET    /leads/{lead_id}         fetch a single lead by ID
PATCH  /leads/{lead_id}         partially update a lead
DELETE /leads/{lead_id}         permanently delete a lead
PATCH  /leads/{lead_id}/status  update CRM status for a lead
GET    /debug/database          MongoDB connectivity + document count
GET    /debug/sample            first 5 documents from the leads collection
"""

import importlib.util
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, status

from src.config.mongo import (
    COLLECTION_NAME,
    CATEGORIES_COLLECTION,
    ALL_CATEGORIES,
    get_db,
    collection_for_category,
    ensure_lead_indexes,
)
from src.controllers.lead_controller import LeadController, LeadNotFoundError
from src.models.lead import Category
from src.schemas.lead_schema import (
    ErrorResponse,
    GenerateLeadsRequest,
    LeadCreateRequest,
    LeadResponse,
    LeadUpdateRequest,
    LeadsListResponse,
    MessageResponse,
    MongoLeadsResponse,
)

router = APIRouter(
    tags=["Leads"],
    responses={
        404: {"model": ErrorResponse, "description": "Lead not found"},
        422: {"description": "Validation error"},
    },
)


def _handle_not_found(exc: LeadNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(tag: str, msg: str) -> None:
    print(f"[{_ts()}] [{tag}] {msg}", flush=True)


# ── Load leadgen pipeline module once at import time ─────────────────────────
_LEADGEN_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tools", "leadgen.py")
)
_leadgen_mod = None


def _get_leadgen():
    global _leadgen_mod
    if _leadgen_mod is not None:
        return _leadgen_mod
    if not os.path.exists(_LEADGEN_PATH):
        return None
    try:
        spec = importlib.util.spec_from_file_location("leadgen", _LEADGEN_PATH)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _leadgen_mod = mod
        return mod
    except Exception as exc:
        _log("PIPELINE", f"WARNING: could not load leadgen.py: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# GET /leads/categories
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/leads/categories",
    summary="List all industry categories",
    response_model=list[str],
    tags=["Leads"],
)
async def get_categories():
    """
    Return all known industry category names.

    Reads from the MongoDB 'categories' collection which is seeded on startup
    with ALL_CATEGORIES from src/config/mongo.py.
    Falls back to the static list if MongoDB is unreachable.
    """
    try:
        db   = get_db()
        coll = db[CATEGORIES_COLLECTION]
        cursor = coll.find({}, {"name": 1, "_id": 0}).sort("name", 1)
        docs   = await cursor.to_list(length=500)
        names  = [d["name"] for d in docs if d.get("name")]
        if names:
            return names
    except Exception:
        pass
    return ALL_CATEGORIES


# ─────────────────────────────────────────────────────────────────────────────
# POST /leads/generate-leads
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/leads/generate-leads",
    summary="Generate B2B leads via Google Maps pipeline, store by category, return only NEW leads",
    response_model=MongoLeadsResponse,
    response_model_exclude_none=False,
    status_code=status.HTTP_200_OK,
    tags=["Leads"],
)
async def generate_leads(payload: GenerateLeadsRequest):
    """
    Production pipeline — Google Maps is the FIRST discovery layer.

    Stages
    ------
    1. [DISCOVERY]   Google Maps Places API → unique companies
    2. [ENRICH]      CompanyEnrich → Serper → Firecrawl (missing fields only)
    3. [CONFIDENCE]  Score 0.0-1.0 per company
    4. [ROUTE DEDUP] Remove within-batch duplicates by website domain
    5. [DB DEDUP]    Query MongoDB: find which candidates already exist
                     (by website URL or company_name as fallback)
    6. [MONGODB]     Upsert ALL into leads_{category} collection
                     (keeps data fresh even for existing leads)
    7. [RESPONSE]    Return ONLY the newly inserted leads to the UI

    Category storage
    ----------------
    Every lead is written to a collection named leads_{category_slug}:
      Construction  → leads_construction
      Real Estate   → leads_real_estate
      FinTech       → leads_fintech
    The 'categories' collection is updated with the industry name on every run.
    """
    t_start = time.monotonic()
    _log("LEADS", "Request received")

    from app.services.companyenrich_service import reset_credits_flag
    reset_credits_flag()

    # ── Resolve request params ────────────────────────────────────────────────
    import re as _re
    industry = payload.industry or ""
    state    = payload.state or ""
    district = payload.district or payload.city or ""
    target   = payload.resolved_target()

    if payload.query and not industry:
        query = payload.query.strip()
        m = _re.match(r'^(.+?)\s+companies?\s+in\s+(.+)$', query, _re.IGNORECASE)
        if m:
            industry = m.group(1).strip()
            if not state:
                district = m.group(2).strip()
    else:
        try:
            query = payload.resolved_query()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )

    if not industry:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide 'industry' (and optionally 'state', 'district', 'target').",
        )
    if not state:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'state' is required for lead generation (e.g. 'Maharashtra').",
        )

    query = f"{industry} companies in {district or state}, India"
    _log("LEADS", f"industry={industry!r} state={state!r} district={district!r} target={target}")

    # ── Stage 1: Google Maps pipeline ─────────────────────────────────────────
    _log("PIPELINE", "Starting Google Maps discovery")
    from app.services.maps_pipeline_service import run_maps_pipeline, get_pipeline_stats
    try:
        maps_result = await run_maps_pipeline(
            category=industry,
            state=state,
            district=district or None,
            target=target,
            exclude_seen=True,
        )
    except Exception as exc:
        _log("DISCOVERY", f"Google Maps pipeline ERROR — {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    pipeline_companies: list[dict] = maps_result.get("companies", [])
    ps = maps_result.get("pipeline_stats", {})
    _log("PIPELINE", f"Google Maps pipeline returned {len(pipeline_companies)} companies")

    if not pipeline_companies:
        _log("LEADS", "No companies found — returning empty result")
        return MongoLeadsResponse(
            success=True,
            inserted=0,
            updated=0,
            total=0,
            query=query,
            timestamp=datetime.now(timezone.utc).isoformat(),
            leads=[],
            pipeline_stats={
                "google_maps_discovered": ps.get("google_maps_discovered", 0),
                "google_maps_duplicates": ps.get("google_maps_duplicates", 0),
                "companyenrich_calls":    ps.get("companyenrich_calls", 0),
                "serper_calls":           ps.get("serper_calls", 0),
                "firecrawl_calls":        ps.get("firecrawl_calls", 0),
                "elapsed_seconds":        round(time.monotonic() - t_start, 1),
            },
        )

    # ── Stage 4: Route-level dedup (within-batch) + cap ───────────────────────
    seen_websites: set[str] = set()
    unique: list[dict] = []
    for c in pipeline_companies:
        key = c.get("website", "").lower().strip().rstrip("/")
        if key and key in seen_websites:
            continue
        if key:
            seen_websites.add(key)
        else:
            key = c.get("company_name", "").lower().strip()
            if key and key in seen_websites:
                continue
            if key:
                seen_websites.add(key)
        unique.append(c)

    _log("DEDUP", f"After route-level dedup: {len(unique)} unique companies")

    if len(unique) > target:
        unique.sort(key=lambda c: c.get("confidence", 0.0), reverse=True)
        unique = unique[:target]
        _log("DEDUP", f"Capped to target={target}")

    # ── MongoDB setup ─────────────────────────────────────────────────────────
    db        = get_db()
    coll_name = collection_for_category(industry)   # e.g. "leads_construction"
    coll      = db[coll_name]
    _log("MONGODB", f"Target collection: '{coll_name}' ({len(unique)} companies to process)")

    # Ensure indexes exist for this category collection (non-fatal)
    try:
        await ensure_lead_indexes(db, industry)
    except Exception as _idx_exc:
        _log("MONGODB", f"Index warning (non-fatal): {_idx_exc}")

    # Register this category in the categories collection
    try:
        cats_coll = db[CATEGORIES_COLLECTION]
        await cats_coll.update_one(
            {"name": industry},
            {"$set": {"name": industry, "collection": coll_name}},
            upsert=True,
        )
    except Exception as _cat_exc:
        _log("MONGODB", f"Category register warning (non-fatal): {_cat_exc}")

    # ── Stage 5: MongoDB pre-dedup ────────────────────────────────────────────
    # Collect the identifiers we're about to process, then ask MongoDB which
    # already exist.  This is a single bulk query — not one per company.
    candidate_websites = [
        c.get("website", "").lower().strip().rstrip("/")
        for c in unique
        if c.get("website", "").strip()
    ]
    candidate_names = [
        c.get("company_name", "")
        for c in unique
        if c.get("company_name", "").strip()
    ]

    existing_websites: set[str] = set()
    existing_names:    set[str] = set()

    if candidate_websites:
        async for doc in coll.find(
            {"website": {"$in": candidate_websites}},
            {"website": 1, "_id": 0},
        ):
            w = (doc.get("website") or "").lower().strip().rstrip("/")
            if w:
                existing_websites.add(w)

    if candidate_names:
        async for doc in coll.find(
            {"company_name": {"$in": candidate_names}},
            {"company_name": 1, "_id": 0},
        ):
            n = (doc.get("company_name") or "").lower().strip()
            if n:
                existing_names.add(n)

    _log("DEDUP", (
        f"MongoDB pre-check → {len(existing_websites)} existing websites, "
        f"{len(existing_names)} existing names in '{coll_name}'"
    ))

    # Classify each company as NEW or DUPLICATE
    new_companies:  list[dict] = []
    dupe_companies: list[dict] = []
    for c in unique:
        w = (c.get("website") or "").lower().strip().rstrip("/")
        n = (c.get("company_name") or "").lower().strip()
        is_dup = (w and w in existing_websites) or (not w and n and n in existing_names)
        if is_dup:
            dupe_companies.append(c)
        else:
            new_companies.append(c)

    _log("DEDUP", (
        f"New leads to insert: {len(new_companies)} | "
        f"Already in DB (will update silently, NOT returned to UI): {len(dupe_companies)}"
    ))

    # ── Stage 6: MongoDB upsert (ALL companies — keeps data fresh) ───────────
    now            = datetime.now(timezone.utc)
    inserted_count = 0
    updated_count  = 0

    # Track keys for newly inserted docs so we can fetch them back
    new_website_keys: list[str] = []
    new_name_keys:    list[str] = []

    # Social-media domain filter (applied to research_sources list)
    _SOCIAL_DOMS = frozenset({
        "instagram.com", "facebook.com", "linkedin.com", "twitter.com",
        "x.com", "youtube.com", "tiktok.com", "pinterest.com",
    })

    def _is_official_source(u: str) -> bool:
        try:
            d = urlparse(u).netloc.lower().lstrip("www.")
            return not any(d == s or d.endswith("." + s) for s in _SOCIAL_DOMS)
        except Exception:
            return True

    for company in unique:
        website        = (company.get("website") or "").strip()
        email          = company.get("email")
        company_number = company.get("company_number")
        founder_name   = company.get("founder_name")
        founder_number = company.get("founder_number")
        source_url     = company.get("source_url") or website or None
        confidence     = company.get("confidence", 0.0)
        research_src   = company.get("research_source", "serper_firecrawl")
        rsources       = list(company.get("research_sources") or [])
        rsources       = [u for u in rsources if _is_official_source(u)]
        if source_url and source_url not in rsources and _is_official_source(source_url):
            rsources = [source_url] + rsources

        has_contact   = bool(email or company_number)
        last_verified = now.isoformat() if has_contact else None
        field_verification = company.get("_field_verification") or {}

        set_fields: dict = {
            "company_name":        company.get("company_name", ""),
            "category":            industry,       # ← always store the category
            "website":             website,
            "emails":              company.get("emails", []),
            "phones":              company.get("phones", []),
            "address":             company.get("address", ""),
            "city":                company.get("city", ""),
            "state":               company.get("state", ""),
            "country":             company.get("country", ""),
            "postal_code":         company.get("postal_code", ""),
            "sources":             company.get("sources", []),
            "updated_at":          now,
            "email":               email,
            "company_number":      company_number,
            "founder_name":        founder_name,
            "founder_number":      founder_number,
            "source_url":          source_url,
            "confidence":          confidence,
            "research_source":     research_src,
            "research_sources":    rsources,
            "_field_verification": field_verification,
            # Google Maps geo fields
            "place_id":            company.get("place_id"),
            "google_maps_uri":     company.get("google_maps_uri"),
            "primary_type":        company.get("primary_type"),
            "latitude":            company.get("latitude"),
            "longitude":           company.get("longitude"),
            # People enrichment contacts (PDL → Prospeo → ContactOut)
            "contacts":            company.get("contacts", []),
        }
        if last_verified:
            set_fields["last_verified"] = last_verified

        filter_key = (
            {"website": website}
            if website
            else {"company_name": company.get("company_name", "")}
        )
        result = await coll.update_one(
            filter_key,
            {"$set": set_fields, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

        is_insert = bool(result.upserted_id)
        if is_insert:
            inserted_count += 1
        else:
            updated_count += 1

        # Track new insertions so we can fetch them back for the response
        if is_insert:
            if website:
                new_website_keys.append(website)
            else:
                new_name_keys.append(company.get("company_name", ""))

        _log("MONGODB", (
            f"{'INSERT' if is_insert else 'UPDATE'}: "
            f"{company.get('company_name', '?')} | "
            f"category={industry!r} | "
            f"email={'YES' if email else 'NO'} | "
            f"phone={'YES' if company_number else 'NO'} | "
            f"confidence={confidence}"
        ))

    _log("MONGODB", (
        f"Done — inserted={inserted_count} updated={updated_count} "
        f"collection='{coll_name}'"
    ))

    # Update lead_count in categories collection
    try:
        total_in_coll = await coll.count_documents({})
        await db[CATEGORIES_COLLECTION].update_one(
            {"name": industry},
            {"$set": {"lead_count": total_in_coll}},
        )
    except Exception:
        pass

    # ── Stage 7: Fetch newly inserted docs from MongoDB for the response ───────
    # IMPORTANT: we only return docs that were INSERTED this run (upserted_id set).
    # Existing/updated docs are silently refreshed but NOT shown to the user.
    if not new_website_keys and not new_name_keys:
        db_docs: list[dict] = []
        _log("RESPONSE", "No new leads inserted — returning empty list to UI")
    else:
        conditions = []
        if new_website_keys:
            conditions.append({"website": {"$in": new_website_keys}})
        if new_name_keys:
            conditions.append({"company_name": {"$in": new_name_keys}})

        fetch_filter: dict = {"$or": conditions} if len(conditions) > 1 else conditions[0]
        cursor  = coll.find(fetch_filter).sort("created_at", -1)
        db_docs = await cursor.to_list(length=inserted_count + 10)

    leads_out: list[dict] = []
    for doc in db_docs:
        doc["id"] = str(doc.pop("_id"))
        for ts_field in ("created_at", "updated_at"):
            if isinstance(doc.get(ts_field), datetime):
                doc[ts_field] = doc[ts_field].isoformat()
        leads_out.append(doc)

    elapsed = round(time.monotonic() - t_start, 1)

    # ── Summary log ───────────────────────────────────────────────────────────
    n_email    = sum(1 for c in unique if c.get("email"))
    n_phone    = sum(1 for c in unique if c.get("company_number"))
    n_address  = sum(1 for c in unique if c.get("address"))
    n_founder  = sum(1 for c in unique if c.get("founder_name"))
    n_contacts = sum(1 for c in unique if c.get("contacts"))
    n_contact_emails = sum(
        sum(1 for ct in c.get("contacts", []) if ct.get("email"))
        for c in unique
    )
    n_contact_phones = sum(
        sum(1 for ct in c.get("contacts", []) if ct.get("phone"))
        for c in unique
    )
    _log("LEADS", (
        f"COMPLETE in {elapsed}s | "
        f"pipeline_total={len(unique)} | "
        f"new_inserted={inserted_count} | "
        f"already_existed={updated_count} | "
        f"returned_to_ui={len(leads_out)} | "
        f"email={n_email}/{len(unique)} | "
        f"phone={n_phone}/{len(unique)} | "
        f"address={n_address}/{len(unique)} | "
        f"founder={n_founder}/{len(unique)} | "
        f"contacts={n_contacts}/{len(unique)} | "
        f"contact_emails={n_contact_emails} | "
        f"contact_phones={n_contact_phones} | "
        f"gmaps_discovered={ps.get('google_maps_discovered', 0)} | "
        f"gmaps_dupes={ps.get('google_maps_duplicates', 0)} | "
        f"ce_calls={ps.get('companyenrich_calls', 0)} | "
        f"serper_calls={ps.get('serper_calls', 0)} | "
        f"firecrawl_calls={ps.get('firecrawl_calls', 0)}"
    ))

    final_pipeline_stats = {
        "google_maps_discovered":      ps.get("google_maps_discovered", 0),
        "google_maps_duplicates":      ps.get("google_maps_duplicates", 0),
        "companyenrich_calls":         ps.get("companyenrich_calls", 0),
        "companyenrich_fields_filled": ps.get("companyenrich_fields_filled", 0),
        "serper_calls":                ps.get("serper_calls", 0),
        "serper_fields_filled":        ps.get("serper_fields_filled", 0),
        "firecrawl_calls":             ps.get("firecrawl_calls", 0),
        "firecrawl_fields_filled":     ps.get("firecrawl_fields_filled", 0),
        "final_valid_companies":       ps.get("final_valid_companies", len(unique)),
        "db_dedup_skipped":            len(dupe_companies),  # ← new: how many were dupes
        # People enrichment orchestrator
        "people_companies_processed":  ps.get("people_companies_processed", 0),
        "people_contacts_found":       ps.get("people_contacts_found", 0),
        "people_emails_found":         ps.get("people_emails_found", 0),
        "people_phones_found":         ps.get("people_phones_found", 0),
        "people_target_reached":       ps.get("people_target_reached", 0),
        "people_auth_failures":        ps.get("people_auth_failures", 0),
        "pdl_calls":                   ps.get("pdl_calls", 0),
        "pdl_contacts":                ps.get("pdl_contacts", 0),
        "prospeo_calls":               ps.get("prospeo_calls", 0),
        "prospeo_contacts":            ps.get("prospeo_contacts", 0),
        "contactout_calls":            ps.get("contactout_calls", 0),
        "contactout_contacts":         ps.get("contactout_contacts", 0),
        # Legacy compat
        "pdl_companies_searched":      ps.get("pdl_companies_searched", 0),
        "pdl_contacts_found":          ps.get("pdl_contacts_found", 0),
        "pdl_emails_found":            ps.get("pdl_emails_found", 0),
        "pdl_phones_found":            ps.get("pdl_phones_found", 0),
        "pdl_api_calls":               ps.get("pdl_api_calls", 0),
        "pdl_auth_failures":           ps.get("pdl_auth_failures", 0),
        "elapsed_seconds":             elapsed,
    }

    return MongoLeadsResponse(
        success=True,
        inserted=inserted_count,
        updated=updated_count,
        total=len(leads_out),
        query=query,
        timestamp=datetime.now(timezone.utc).isoformat(),
        leads=leads_out,
        pipeline_stats=final_pipeline_stats,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /leads
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/leads",
    summary="List stored leads from MongoDB",
    response_model=MongoLeadsResponse,
    tags=["Leads"],
)
async def get_leads(
    category: Optional[str] = Query(
        None,
        description="Filter by industry category — reads from the category-specific collection",
    ),
    search:   Optional[str] = Query(None, description="Filter by company name (case-insensitive)"),
    page:     int           = Query(1,   ge=1),
    per_page: int           = Query(100, ge=1, le=500),
):
    """
    Fetch stored leads from MongoDB — no AI, no scraping.

    If `category` is provided, reads from the category-specific collection
    (e.g. leads_construction).  Otherwise reads from the legacy 'leads' collection.
    """
    db         = get_db()
    coll_name  = collection_for_category(category) if category else COLLECTION_NAME
    collection = db[coll_name]

    mongo_filter: dict = {}
    if search:
        mongo_filter["company_name"] = {"$regex": search, "$options": "i"}

    total   = await collection.count_documents(mongo_filter)
    skip    = (page - 1) * per_page
    cursor  = collection.find(mongo_filter).sort("created_at", -1).skip(skip).limit(per_page)
    db_docs = await cursor.to_list(length=per_page)

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
        query=category or "",
        timestamp=datetime.now(timezone.utc).isoformat(),
        leads=leads_out,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Manual CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/leads",
    summary="Create a new lead manually",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Leads"],
)
def create_lead(payload: LeadCreateRequest):
    return LeadController.create_lead(payload)


@router.get(
    "/leads/{lead_id}",
    summary="Get a single lead",
    response_model=LeadResponse,
    tags=["Leads"],
)
def get_lead(lead_id: str):
    try:
        return LeadController.get_lead(lead_id)
    except LeadNotFoundError as exc:
        raise _handle_not_found(exc)


@router.patch(
    "/leads/{lead_id}",
    summary="Partially update a lead",
    response_model=LeadResponse,
    tags=["Leads"],
)
def update_lead(lead_id: str, payload: LeadUpdateRequest):
    try:
        return LeadController.update_lead(lead_id, payload)
    except LeadNotFoundError as exc:
        raise _handle_not_found(exc)


@router.delete(
    "/leads/{lead_id}",
    summary="Delete a lead",
    response_model=MessageResponse,
    tags=["Leads"],
)
def delete_lead(lead_id: str):
    try:
        return LeadController.delete_lead(lead_id)
    except LeadNotFoundError as exc:
        raise _handle_not_found(exc)


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /leads/{lead_id}/status
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel as _StatusBodyBase


class _StatusUpdateBody(_StatusBodyBase):
    status:   str
    category: Optional[str] = None


@router.patch(
    "/leads/{lead_id}/status",
    summary="Update CRM status for a lead",
    response_model=dict,
    tags=["Leads"],
)
async def update_lead_status(lead_id: str, payload: _StatusUpdateBody):
    """
    Update the CRM status field for a lead.
    Valid values: new | contacted | follow_up | interested | not_interested | closed

    The `category` param routes to the correct per-category collection.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    VALID_STATUSES = {
        "", "new", "contacted", "follow_up",
        "interested", "not_interested", "closed",
    }
    if payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}'",
        )

    db         = get_db()
    coll_name  = collection_for_category(payload.category) if payload.category else COLLECTION_NAME
    collection = db[coll_name]

    try:
        oid = ObjectId(lead_id)
        flt = {"_id": oid}
    except (InvalidId, Exception):
        flt = {"id": lead_id}

    result = await collection.update_one(
        flt,
        {"$set": {"status_update": payload.status, "updated_at": datetime.now(timezone.utc)}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' not found")

    return {"success": True, "lead_id": lead_id, "status": payload.status}


# ─────────────────────────────────────────────────────────────────────────────
# Debug endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/debug/database",
    summary="MongoDB connectivity check",
    response_model=dict,
    tags=["Debug"],
)
async def debug_database():
    """Show connection status, database name, and per-category lead counts."""
    db   = get_db()
    coll = db[COLLECTION_NAME]

    # Legacy leads count
    legacy_count = await coll.count_documents({})

    # Per-category counts
    cats_coll   = db[CATEGORIES_COLLECTION]
    cats_cursor = cats_coll.find({}, {"name": 1, "collection": 1, "_id": 0}).sort("name", 1)
    cats_docs   = await cats_cursor.to_list(length=500)

    category_counts: dict = {}
    for cat in cats_docs:
        cat_name  = cat.get("name", "")
        cat_coll  = cat.get("collection") or collection_for_category(cat_name)
        count     = await db[cat_coll].count_documents({})
        if count > 0:
            category_counts[cat_name] = count

    return {
        "connected":       True,
        "database":        db.name,
        "legacy_collection": COLLECTION_NAME,
        "legacy_count":    legacy_count,
        "categories_collection": CATEGORIES_COLLECTION,
        "category_lead_counts":  category_counts,
    }


@router.get(
    "/debug/sample",
    summary="First 5 documents from leads collection",
    response_model=list[dict[str, Any]],
    tags=["Debug"],
)
async def debug_sample():
    db     = get_db()
    coll   = db[COLLECTION_NAME]
    cursor = coll.find({}, {"_id": 0}).limit(5)
    docs   = await cursor.to_list(length=5)
    return docs
