"""
src/routes/leads.py
--------------------
Leads API router.

Production flow for POST /leads/generate-leads:
  UI → FastAPI → Serper discovery → Firecrawl research → contact-gap search
  → NORMALIZE → VALIDATE → CONFIDENCE → ENRICH → VERIFY → DEDUPLICATE
  → MongoDB → UI

Hermes Desktop Agent is NOT called from this route under any circumstances.

Endpoints
---------
GET    /leads/categories        list all industry categories
POST   /leads/generate-leads    Serper+Firecrawl pipeline, upsert MongoDB, return docs
GET    /leads                   paginated list of stored leads
POST   /leads                   create a lead manually
GET    /leads/{lead_id}         fetch a single lead by ID
PATCH  /leads/{lead_id}         partially update a lead
DELETE /leads/{lead_id}         permanently delete a lead
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

from src.config.mongo import COLLECTION_NAME, get_db
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
from app.services.discovery_service import discover_leads

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


# ── Categories ────────────────────────────────────────────────────────────────

@router.get(
    "/leads/categories",
    summary="List all industry categories",
    response_model=list[str],
    tags=["Leads"],
)
def get_categories():
    return LeadController.list_categories()


# ═══════════════════════════════════════════════════════════════════════════════
# POST /leads/generate-leads — main production endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/leads/generate-leads",
    summary="Generate B2B leads via Serper + Firecrawl (NO Hermes), upsert to MongoDB",
    response_model=MongoLeadsResponse,
    status_code=status.HTTP_200_OK,
    tags=["Leads"],
)
async def generate_leads(payload: GenerateLeadsRequest):
    """
    Production pipeline — Hermes Desktop Agent is NOT called.

    Stages
    ------
    [DISCOVERY]      Multi-query Serper → candidate company URLs
    [FILTER]         Reject directories / social / Wikipedia / 404s
    [FIRECRAWL]      Concurrent multi-page scrapes per company
    [CONTACT_SEARCH] Gap-fill missing email/phone/address/founder via Serper
    [EXTRACTION]     Per-company extraction summary log
    [NORMALIZE]      Map to internal schema
    [VALIDATE]       Reject junk emails/phones (leadgen.py)
    [CONFIDENCE]     Score 0.0–1.0 per company (leadgen.py)
    [ENRICH]         Founder discovery from official pages (leadgen.py)
    [VERIFY]         Cross-check contacts vs scraped pages (leadgen.py)
    [DEDUP]          Remove duplicate companies by domain/website
    [MONGODB]        Upsert each unique company document
    """
    t_start = time.monotonic()
    _log("LEADS", "Request received — Hermes will NOT be called")

    # ── Resolve query ─────────────────────────────────────────────────────────
    try:
        query = payload.resolved_query()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    _log("LEADS", f"query={query!r}  count={payload.count}")

    # ── DISCOVERY + FILTER + FIRECRAWL + CONTACT_SEARCH + EXTRACTION ─────────
    try:
        discovery_result = await discover_leads(query, num=payload.count)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        _log("DISCOVERY", f"ERROR — {type(exc).__name__}: {exc!r}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discovery pipeline error: {type(exc).__name__}: {exc}",
        )

    raw_companies: list[dict] = discovery_result.get("companies", [])
    disc_stats = discovery_result.get("_stats", {})
    _log("DISCOVERY", f"Returned {len(raw_companies)} companies from discovery")

    # ── NORMALIZE (already done inside discover_leads; log confirmation) ──────
    _log("NORMALIZE", f"Received {len(raw_companies)} normalized company dicts")

    pipeline_companies = list(raw_companies)
    lg = _get_leadgen()

    if lg is None:
        _log("PIPELINE", "WARNING: leadgen.py not found — skipping VALIDATE/CONFIDENCE/ENRICH/VERIFY")
    else:
        # ── VALIDATE ──────────────────────────────────────────────────────────
        _log("VALIDATE", f"Validating contacts for {len(pipeline_companies)} companies")
        validated: list[dict] = []
        total_email_rejected = 0
        total_phone_rejected = 0
        for c in pipeline_companies:
            try:
                vc = lg.validate_contacts(c)
            except Exception as exc:
                _log("VALIDATE", f"Warning for {c.get('company_name','?')}: {exc}")
                vc = c
            total_email_rejected += len(vc.get("rejected_emails", []))
            total_phone_rejected += len(vc.get("rejected_phones", []))
            validated.append(vc)
        _log("VALIDATE", (
            f"Done — emails_rejected={total_email_rejected}  "
            f"phones_rejected={total_phone_rejected}"
        ))
        pipeline_companies = validated

        # ── CONFIDENCE ────────────────────────────────────────────────────────
        _log("CONFIDENCE", f"Scoring {len(pipeline_companies)} companies")
        for c in pipeline_companies:
            if not c.get("confidence"):
                try:
                    c["confidence"] = lg.score_confidence(c)
                except Exception:
                    c["confidence"] = 0.0
        scores = [c.get("confidence", 0.0) for c in pipeline_companies]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
        _log("CONFIDENCE", f"Done — avg_score={avg_score}")

        # ── ENRICH — verify_service already ran comprehensive founder searches  ──
        # during discovery (verify_company per-company).  We do NOT re-run
        # blocking Serper calls here.  Just validate any founder name that was
        # set, and log the result.
        _log("ENRICH", f"Post-verify founder validation for {len(pipeline_companies)} companies")
        from app.services.verify_service import _is_plausible_person_name
        for c in pipeline_companies:
            name = c.get("company_name", "?")
            fn   = c.get("founder_name")
            if fn and not _is_plausible_person_name(fn):
                _log("ENRICH", f"{name} — rejected implausible founder {fn!r}")
                c["founder_name"] = None
            else:
                _log("ENRICH", f"{name} — founder={fn!r}")

        # ── VERIFY ────────────────────────────────────────────────────────────
        _log("VERIFY", f"Cross-checking contacts for {len(pipeline_companies)} companies")
        verified: list[dict] = []
        for c in pipeline_companies:
            name = c.get("company_name", "?")
            try:
                vc = lg.verify_company_data(c)
                vr = vc.get("verification", {})
                _log("VERIFY", (
                    f"{name} — "
                    f"email={'✓' if vr.get('email',{}).get('verified') else '✗'}  "
                    f"phone={'✓' if vr.get('company_number',{}).get('verified') else '✗'}  "
                    f"confidence={vc.get('confidence', 0.0)}"
                ))
            except Exception as exc:
                _log("VERIFY", f"Warning for {name}: {exc}")
                vc = c
            verified.append(vc)
        pipeline_companies = verified

        # ── DEDUP via leadgen ─────────────────────────────────────────────────
        _log("DEDUP", f"Deduplicating {len(pipeline_companies)} companies via leadgen")
        try:
            pipeline_companies = lg.deduplicate_companies(pipeline_companies)
        except Exception as exc:
            _log("DEDUP", f"Warning: {exc}")
        _log("DEDUP", f"After dedup: {len(pipeline_companies)} unique companies")

    # ── Route-level dedup by website URL ─────────────────────────────────────
    seen_websites: set[str] = set()
    unique: list[dict] = []
    for c in pipeline_companies:
        key = c.get("website", "").lower().strip().rstrip("/")
        if key and key in seen_websites:
            continue
        if key:
            seen_websites.add(key)
        else:
            # Fall back to company name as dedup key
            key = c.get("company_name", "").lower().strip()
            if key and key in seen_websites:
                continue
            if key:
                seen_websites.add(key)
        unique.append(c)

    _log("DEDUP", f"After route-level dedup: {len(unique)} unique companies")

    # Cap at requested count — only return the best N valid companies
    if len(unique) > payload.count:
        # Sort by confidence descending so the best companies come first
        unique.sort(key=lambda c: c.get("confidence", 0.0), reverse=True)
        unique = unique[: payload.count]
        _log("DEDUP", f"Capped to requested count={payload.count}")

    # ── MONGODB upsert ────────────────────────────────────────────────────────
    _log("MONGODB", f"Upserting {len(unique)} companies")
    db         = get_db()
    collection = db[COLLECTION_NAME]
    now        = datetime.now(timezone.utc)
    inserted_count = 0
    updated_count  = 0
    upserted_keys: list[str] = []

    for company in unique:
        website        = company.get("website", "").strip()
        email          = company.get("email")
        company_number = company.get("company_number")
        founder_name   = company.get("founder_name")
        founder_number = company.get("founder_number")
        source_url     = company.get("source_url") or website or None
        confidence     = company.get("confidence", 0.0)
        research_src   = company.get("research_source", "serper_firecrawl")
        rsources       = list(company.get("research_sources") or [])

        # Strip social-media / non-official URLs from research_sources
        # These can leak in via the ENRICH stage's Serper results
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
        rsources = [u for u in rsources if _is_official_source(u)]
        if source_url and source_url not in rsources and _is_official_source(source_url):
            rsources = [source_url] + rsources

        has_contact = bool(email or company_number)
        last_verified = now.isoformat() if has_contact else None

        set_fields: dict = {
            "company_name":    company.get("company_name", ""),
            "website":         website,
            "emails":          company.get("emails", []),
            "phones":          company.get("phones", []),
            "address":         company.get("address", ""),
            "city":            company.get("city", ""),
            "state":           company.get("state", ""),
            "country":         company.get("country", ""),
            "postal_code":     company.get("postal_code", ""),
            "sources":         company.get("sources", []),
            "updated_at":      now,
            "email":           email,
            "company_number":  company_number,
            "founder_name":    founder_name,
            "founder_number":  founder_number,
            "source_url":      source_url,
            "confidence":      confidence,
            "research_source":  research_src,
            "research_sources": rsources,
        }
        if last_verified:
            set_fields["last_verified"] = last_verified

        filter_key = (
            {"website": website}
            if website
            else {"company_name": company.get("company_name", "")}
        )
        result = await collection.update_one(
            filter_key,
            {"$set": set_fields, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        if result.upserted_id:
            inserted_count += 1
        else:
            updated_count += 1
        upserted_keys.append(website or company.get("company_name", ""))

        _log("MONGODB", (
            f"{'INSERT' if result.upserted_id else 'UPDATE'}: "
            f"{company.get('company_name','?')} | "
            f"email={'YES' if email else 'NO'} | "
            f"phone={'YES' if company_number else 'NO'} | "
            f"confidence={confidence}"
        ))

    _log("MONGODB", f"Done — inserted={inserted_count}  updated={updated_count}")

    # ── Fetch upserted docs from MongoDB ──────────────────────────────────────
    website_list = [k for k in upserted_keys if k.startswith("http")]
    name_list    = [k for k in upserted_keys if not k.startswith("http")]

    if website_list and name_list:
        fetch_filter: dict = {"$or": [
            {"website":      {"$in": website_list}},
            {"company_name": {"$in": name_list}},
        ]}
    elif website_list:
        fetch_filter = {"website": {"$in": website_list}}
    elif name_list:
        fetch_filter = {"company_name": {"$in": name_list}}
    else:
        fetch_filter = {}

    cursor  = collection.find(fetch_filter).sort("updated_at", -1)
    db_docs = await cursor.to_list(length=len(unique) + 10)

    leads_out: list[dict] = []
    for doc in db_docs:
        doc["id"] = str(doc.pop("_id"))
        for ts_field in ("created_at", "updated_at"):
            if isinstance(doc.get(ts_field), datetime):
                doc[ts_field] = doc[ts_field].isoformat()
        leads_out.append(doc)

    elapsed = round(time.monotonic() - t_start, 1)

    # ── Final summary log ─────────────────────────────────────────────────────
    n_email   = sum(1 for c in unique if c.get("email"))
    n_phone   = sum(1 for c in unique if c.get("company_number"))
    n_address = sum(1 for c in unique if c.get("address"))
    n_founder = sum(1 for c in unique if c.get("founder_name"))
    _log("LEADS", (
        f"COMPLETE in {elapsed}s | "
        f"returned={len(leads_out)} | "
        f"email={n_email}/{len(unique)} | "
        f"phone={n_phone}/{len(unique)} | "
        f"address={n_address}/{len(unique)} | "
        f"founder={n_founder}/{len(unique)} | "
        f"serper_calls={disc_stats.get('serper_calls',0)} | "
        f"firecrawl_calls={disc_stats.get('firecrawl_calls',0)} | "
        f"llm_calls=0 | "
        f"404_filtered={disc_stats.get('filtered_404',0)} | "
        f"duplicates={disc_stats.get('duplicates',0)} | "
        f"[NO HERMES CALLED]"
    ))

    return MongoLeadsResponse(
        success=True,
        inserted=inserted_count,
        updated=updated_count,
        total=len(leads_out),
        query=discovery_result.get("query", query),
        timestamp=discovery_result.get("timestamp", now.isoformat()),
        leads=leads_out,
    )


# ── CRUD endpoints ────────────────────────────────────────────────────────────

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
    """Fetch stored leads from MongoDB — no Hermes, no AI, no scraping."""
    db         = get_db()
    collection = db[COLLECTION_NAME]

    mongo_filter: dict = {}
    if search:
        mongo_filter["company_name"] = {"$regex": search, "$options": "i"}

    total  = await collection.count_documents(mongo_filter)
    skip   = (page - 1) * per_page
    cursor = collection.find(mongo_filter).sort("created_at", -1).skip(skip).limit(per_page)
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
        query="",
        timestamp=datetime.now(timezone.utc).isoformat(),
        leads=leads_out,
    )


@router.post(
    "/leads",
    summary="Create a new lead manually",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Leads"],
)
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
    db         = get_db()
    collection = db[COLLECTION_NAME]
    count      = await collection.count_documents({})
    return {
        "connected":      True,
        "database":       db.name,
        "collection":     COLLECTION_NAME,
        "document_count": count,
    }


@router.get("/debug/sample", summary="First 5 documents from leads collection",
            response_model=list[dict[str, Any]], tags=["Debug"])
async def debug_sample():
    db         = get_db()
    collection = db[COLLECTION_NAME]
    cursor     = collection.find({}, {"_id": 0}).limit(5)
    docs       = await cursor.to_list(length=5)
    return docs
