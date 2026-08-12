"""
src/routes/history.py
──────────────────────
Generation History API.

Endpoints
─────────
GET  /history                         list all generation runs + legacy category summaries
GET  /history/legacy                  list legacy categories with lead counts
GET  /history/legacy/{category}/leads leads for a legacy category (no run_id)
GET  /history/{run_id}                single run details (info + stats + logs)
GET  /history/{run_id}/leads          leads that belong to this run (paginated)
DELETE /history/{run_id}              delete a run record (does NOT delete leads)
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from src.config.mongo import (
    get_db,
    collection_for_category,
    COLLECTION_NAME,
    CATEGORIES_COLLECTION,
    ALL_CATEGORIES,
)

HISTORY_COLLECTION = "generation_history"

router = APIRouter(tags=["History"])


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_ts()}] [HISTORY] {msg}", flush=True)


def _serialize_run(doc: dict) -> dict:
    """Convert a MongoDB document to a JSON-serialisable dict."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id", doc.get("run_id", "")))
    return doc


def _serialize_lead(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    for ts_field in ("created_at", "updated_at"):
        if isinstance(doc.get(ts_field), datetime):
            doc[ts_field] = doc[ts_field].isoformat()
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/legacy  — MUST come before GET /history/{run_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/legacy",
    summary="List legacy categories with lead counts",
    response_model=dict,
    tags=["History"],
)
async def list_legacy():
    """
    Return every leads_* collection that has documents, as a list of
    legacy category summaries.  These are leads stored before the
    generation_history feature was introduced (no generation_run_id).
    Also includes leads from any category that has leads without a run_id.
    """
    db = get_db()

    # Discover all known category names from the categories collection
    cat_names: list[str] = []
    try:
        cats_coll = db[CATEGORIES_COLLECTION]
        cursor = cats_coll.find({}, {"name": 1, "_id": 0})
        docs = await cursor.to_list(length=500)
        cat_names = [d["name"] for d in docs if d.get("name")]
    except Exception:
        pass

    if not cat_names:
        cat_names = ALL_CATEGORIES

    # Also check the legacy 'leads' collection
    legacy_entries = []

    # Check per-category collections
    for cat in cat_names:
        coll_name = collection_for_category(cat)
        coll = db[coll_name]
        try:
            # All leads in this collection (includes both legacy and run-tagged)
            total = await coll.count_documents({})
            if total == 0:
                continue
            # Leads without a generation_run_id = true legacy
            legacy_count = await coll.count_documents(
                {"generation_run_id": {"$exists": False}}
            )
            # Most recent lead date
            newest = await coll.find_one(
                {}, {"created_at": 1, "_id": 0}, sort=[("created_at", -1)]
            )
            newest_date = newest.get("created_at") if newest else None
            if isinstance(newest_date, datetime):
                newest_date = newest_date.isoformat()

            legacy_entries.append({
                "type":          "legacy",
                "category":      cat,
                "collection":    coll_name,
                "total_leads":   total,
                "legacy_leads":  legacy_count,
                "newest_lead_at": newest_date,
            })
        except Exception:
            pass

    # Check the root 'leads' collection
    try:
        root_coll = db[COLLECTION_NAME]
        root_total = await root_coll.count_documents({})
        if root_total > 0:
            newest = await root_coll.find_one(
                {}, {"created_at": 1, "_id": 0}, sort=[("created_at", -1)]
            )
            newest_date = newest.get("created_at") if newest else None
            if isinstance(newest_date, datetime):
                newest_date = newest_date.isoformat()
            legacy_entries.append({
                "type":          "legacy",
                "category":      "All (Legacy)",
                "collection":    COLLECTION_NAME,
                "total_leads":   root_total,
                "legacy_leads":  root_total,
                "newest_lead_at": newest_date,
            })
    except Exception:
        pass

    # Sort by total_leads descending
    legacy_entries.sort(key=lambda x: x["total_leads"], reverse=True)

    return {
        "success": True,
        "legacy_categories": legacy_entries,
        "total_categories": len(legacy_entries),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/legacy/{category}/leads
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/legacy/{category}/leads",
    summary="Get leads for a legacy category",
    response_model=dict,
    tags=["History"],
)
async def get_legacy_leads(
    category: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    legacy_only: bool = Query(False, description="Only return leads without a generation_run_id"),
):
    """
    Return leads from a legacy category collection.
    Works for both legacy (no run_id) and all leads in the category.
    """
    db = get_db()

    if category == "All (Legacy)":
        coll_name = COLLECTION_NAME
    else:
        coll_name = collection_for_category(category)

    coll = db[coll_name]

    mongo_filter: dict = {}
    if legacy_only:
        mongo_filter["generation_run_id"] = {"$exists": False}
    if search:
        mongo_filter["company_name"] = {"$regex": search, "$options": "i"}

    total = await coll.count_documents(mongo_filter)
    skip = (page - 1) * per_page
    cursor = coll.find(mongo_filter).sort("created_at", -1).skip(skip).limit(per_page)
    db_docs = await cursor.to_list(length=per_page)

    leads_out = [_serialize_lead(doc) for doc in db_docs]

    return {
        "success": True,
        "category": category,
        "total": total,
        "page": page,
        "per_page": per_page,
        "leads": leads_out,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /history
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history",
    summary="List all generation runs",
    response_model=dict,
    tags=["History"],
)
async def list_history(
    category: Optional[str] = Query(None, description="Filter by category"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: running | completed | failed"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """
    Return generation runs, newest first.
    Optionally filter by category or status.
    """
    db = get_db()
    coll = db[HISTORY_COLLECTION]

    mongo_filter: dict = {}
    if category:
        mongo_filter["category"] = {"$regex": f"^{category}$", "$options": "i"}
    if status_filter:
        mongo_filter["status"] = status_filter

    total = await coll.count_documents(mongo_filter)
    skip = (page - 1) * per_page
    cursor = coll.find(mongo_filter).sort("started_at", -1).skip(skip).limit(per_page)
    docs = await cursor.to_list(length=per_page)

    runs = [_serialize_run(d) for d in docs]

    # Collect unique categories from generation_history for filter tabs
    try:
        all_cats = await coll.distinct("category")
    except Exception:
        all_cats = []

    return {
        "success": True,
        "total": total,
        "page": page,
        "per_page": per_page,
        "runs": runs,
        "categories": sorted(all_cats),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/{run_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/{run_id}",
    summary="Get a single generation run",
    response_model=dict,
    tags=["History"],
)
async def get_run(run_id: str):
    """Return full details for one generation run including logs and statistics."""
    db = get_db()
    coll = db[HISTORY_COLLECTION]
    doc = await coll.find_one({"run_id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"success": True, "run": _serialize_run(doc)}


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/{run_id}/leads
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/{run_id}/leads",
    summary="Get leads generated by a specific run",
    response_model=dict,
    tags=["History"],
)
async def get_run_leads(
    run_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
):
    """
    Return only the leads created during this specific generation run.
    Uses generation_run_id field on each lead document to filter.
    Falls back to lead_ids list if generation_run_id field is absent.
    """
    db = get_db()
    hist_coll = db[HISTORY_COLLECTION]

    # Fetch the run to get category + lead_ids
    run_doc = await hist_coll.find_one({"run_id": run_id}, {"category": 1, "lead_ids": 1, "_id": 0})
    if not run_doc:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    category = run_doc.get("category", "")
    stored_lead_ids: list[str] = run_doc.get("lead_ids", [])

    # Target collection
    coll_name = collection_for_category(category) if category else "leads"
    coll = db[coll_name]

    # Build filter: prefer generation_run_id field; fall back to lead_ids list
    mongo_filter: dict = {"generation_run_id": run_id}
    if search:
        mongo_filter["company_name"] = {"$regex": search, "$options": "i"}

    total = await coll.count_documents(mongo_filter)

    # If no docs found with generation_run_id, fall back to lead_ids
    if total == 0 and stored_lead_ids:
        from bson import ObjectId
        from bson.errors import InvalidId
        oids = []
        for lid in stored_lead_ids:
            try:
                oids.append(ObjectId(lid))
            except (InvalidId, Exception):
                pass
        if oids:
            mongo_filter = {"_id": {"$in": oids}}
            if search:
                mongo_filter["company_name"] = {"$regex": search, "$options": "i"}
            total = await coll.count_documents(mongo_filter)

    skip = (page - 1) * per_page
    cursor = coll.find(mongo_filter).sort("created_at", -1).skip(skip).limit(per_page)
    db_docs = await cursor.to_list(length=per_page)

    leads_out = [_serialize_lead(doc) for doc in db_docs]

    return {
        "success": True,
        "run_id": run_id,
        "category": category,
        "total": total,
        "page": page,
        "per_page": per_page,
        "leads": leads_out,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /history/{run_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete(
    "/history/{run_id}",
    summary="Delete a generation run record",
    response_model=dict,
    tags=["History"],
)
async def delete_run(run_id: str):
    """
    Delete the generation run record.
    Does NOT delete the leads themselves — only removes the history entry.
    """
    db = get_db()
    coll = db[HISTORY_COLLECTION]
    result = await coll.delete_one({"run_id": run_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"success": True, "deleted_run_id": run_id}



def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_ts()}] [HISTORY] {msg}", flush=True)


def _serialize_run(doc: dict) -> dict:
    """Convert a MongoDB document to a JSON-serialisable dict."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id", doc.get("run_id", "")))
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# GET /history
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history",
    summary="List all generation runs",
    response_model=dict,
    tags=["History"],
)
async def list_history(
    category: Optional[str] = Query(None, description="Filter by category"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: running | completed | failed"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """
    Return generation runs, newest first.
    Optionally filter by category or status.
    """
    db = get_db()
    coll = db[HISTORY_COLLECTION]

    mongo_filter: dict = {}
    if category:
        mongo_filter["category"] = {"$regex": f"^{category}$", "$options": "i"}
    if status_filter:
        mongo_filter["status"] = status_filter

    total = await coll.count_documents(mongo_filter)
    skip = (page - 1) * per_page
    cursor = coll.find(mongo_filter).sort("started_at", -1).skip(skip).limit(per_page)
    docs = await cursor.to_list(length=per_page)

    runs = [_serialize_run(d) for d in docs]

    # Collect unique categories for filter tabs
    try:
        all_cats = await coll.distinct("category")
    except Exception:
        all_cats = []

    return {
        "success": True,
        "total": total,
        "page": page,
        "per_page": per_page,
        "runs": runs,
        "categories": sorted(all_cats),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/{run_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/{run_id}",
    summary="Get a single generation run",
    response_model=dict,
    tags=["History"],
)
async def get_run(run_id: str):
    """Return full details for one generation run including logs and statistics."""
    db = get_db()
    coll = db[HISTORY_COLLECTION]
    doc = await coll.find_one({"run_id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"success": True, "run": _serialize_run(doc)}


# ─────────────────────────────────────────────────────────────────────────────
# GET /history/{run_id}/leads
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/history/{run_id}/leads",
    summary="Get leads generated by a specific run",
    response_model=dict,
    tags=["History"],
)
async def get_run_leads(
    run_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
):
    """
    Return only the leads created during this specific generation run.
    Uses generation_run_id field on each lead document to filter.
    Falls back to lead_ids list if generation_run_id field is absent.
    """
    db = get_db()
    hist_coll = db[HISTORY_COLLECTION]

    # Fetch the run to get category + lead_ids
    run_doc = await hist_coll.find_one({"run_id": run_id}, {"category": 1, "lead_ids": 1, "_id": 0})
    if not run_doc:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    category = run_doc.get("category", "")
    stored_lead_ids: list[str] = run_doc.get("lead_ids", [])

    # Target collection
    coll_name = collection_for_category(category) if category else "leads"
    coll = db[coll_name]

    # Build filter: prefer generation_run_id field; fall back to lead_ids list
    mongo_filter: dict = {"generation_run_id": run_id}
    if search:
        mongo_filter["company_name"] = {"$regex": search, "$options": "i"}

    total = await coll.count_documents(mongo_filter)

    # If no docs found with generation_run_id, fall back to lead_ids
    if total == 0 and stored_lead_ids:
        from bson import ObjectId
        from bson.errors import InvalidId
        oids = []
        for lid in stored_lead_ids:
            try:
                oids.append(ObjectId(lid))
            except (InvalidId, Exception):
                pass
        if oids:
            mongo_filter = {"_id": {"$in": oids}}
            if search:
                mongo_filter["company_name"] = {"$regex": search, "$options": "i"}
            total = await coll.count_documents(mongo_filter)

    skip = (page - 1) * per_page
    cursor = coll.find(mongo_filter).sort("created_at", -1).skip(skip).limit(per_page)
    db_docs = await cursor.to_list(length=per_page)

    leads_out = []
    for doc in db_docs:
        doc["id"] = str(doc.pop("_id"))
        for ts_field in ("created_at", "updated_at"):
            if isinstance(doc.get(ts_field), datetime):
                doc[ts_field] = doc[ts_field].isoformat()
        leads_out.append(doc)

    return {
        "success": True,
        "run_id": run_id,
        "category": category,
        "total": total,
        "page": page,
        "per_page": per_page,
        "leads": leads_out,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /history/{run_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete(
    "/history/{run_id}",
    summary="Delete a generation run record",
    response_model=dict,
    tags=["History"],
)
async def delete_run(run_id: str):
    """
    Delete the generation run record.
    Does NOT delete the leads themselves — only removes the history entry.
    """
    db = get_db()
    coll = db[HISTORY_COLLECTION]
    result = await coll.delete_one({"run_id": run_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"success": True, "deleted_run_id": run_id}
