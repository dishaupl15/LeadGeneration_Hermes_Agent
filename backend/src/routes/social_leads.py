"""
src/routes/social_leads.py
───────────────────────────
Phase 3 — Social Leads dashboard API (production-ready).

Features:
  - Enrichment status lifecycle: pending → processing → completed / failed / not_requested
  - Event timeline on every lead (FORM_SUBMITTED, VALIDATION_SUCCESS, LEAD_SAVED, …)
  - Export endpoint: GET /social-leads/export (CSV, honours all active filters)
  - History endpoint: "Social Form Collection" type clearly separated from "Lead Generation Run"
  - landing_timestamp preserved
  - enrichment_started_at / enrichment_completed_at / enrichment_error stored
  - Lazy backfill: any form_submission not yet in social_leads is synced on first read

Collections:
  form_submissions  — source of truth (written by form_leads.py, never modified here)
  social_leads      — denormalised CRM view (created on submit trigger or lazy sync)

Endpoints
─────────
GET  /social-leads                     list leads (server-side filtered, paginated, sorted)
GET  /social-leads/stats               platform / category / form / campaign counts
GET  /social-leads/history             grouped history for History panel (Social Form Collection)
GET  /social-leads/export              CSV export (respects all active filters)
POST /social-leads/seed-test-data      insert realistic test data (dev / QA)
GET  /social-leads/{submission_id}     single lead detail (all answers + events + enrichment)
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.config.mongo import get_db

SOCIAL_LEADS_COLL = "social_leads"
SUBMISSIONS_COLL  = "form_submissions"
CAMPAIGNS_COLL    = "form_campaigns"
FORMS_COLL        = "lead_forms"

ALLOWED_PLATFORMS = {"linkedin", "x", "whatsapp", "facebook", "website", "other"}

router = APIRouter(prefix="/social-leads", tags=["Social Leads"])


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _extract_person(answers: list[dict]) -> dict:
    """
    Extract standard person fields from the answers list.
    Matches by question label (case-insensitive) with partial-match fallback.
    Falls back to empty string — never raises.
    """
    label_map: dict[str, str] = {}
    for ans in answers:
        lbl = (ans.get("label") or "").lower().strip()
        val = str(ans.get("value") or "").strip()
        if lbl:
            label_map[lbl] = val

    def _pick(*keys: str) -> str:
        # exact match
        for k in keys:
            if k in label_map and label_map[k]:
                return label_map[k]
        # partial match
        for stored_key, val in label_map.items():
            for k in keys:
                if k in stored_key or stored_key in k:
                    return val
        return ""

    return {
        "name":        _pick("name", "full name", "your name", "contact name"),
        "email":       _pick("email", "email address", "e-mail"),
        "phone":       _pick("phone", "phone number", "mobile", "contact number", "whatsapp"),
        "company":     _pick("company", "company name", "organisation", "organization", "business"),
        "designation": _pick("designation", "title", "job title", "role", "position"),
    }


async def _upsert_social_lead(db, submission: dict) -> None:
    """
    Create the social_leads document for a submission (idempotent — skips if already exists).
    Uses submission_id as unique key.
    """
    sub_id = submission.get("submission_id", "")
    if not sub_id:
        return

    answers = submission.get("answers", [])
    person  = _extract_person(answers)
    now_iso = datetime.now(timezone.utc).isoformat()

    form_id     = submission.get("form_id", "")
    campaign_id = submission.get("campaign_id")
    source_url: Optional[str] = None
    if form_id:
        source_url = f"/f/{form_id}"
        if campaign_id:
            source_url += f"?campaign_id={campaign_id}"

    # Prefer explicit platform field; fall back to source for backward compat
    platform = submission.get("platform") or submission.get("source") or "other"

    doc = {
        "submission_id":           sub_id,
        "lead_type":               "form_submission",
        "record_type":             "social_form_collection",
        "platform":                platform,
        "form_id":                 form_id,
        "form_name":               submission.get("form_name", ""),
        "form_version":            submission.get("form_version", 1),
        "category":                submission.get("category", ""),
        "campaign_id":             campaign_id,
        "campaign_name":           submission.get("campaign_name"),
        "person":                  person,
        "answers":                 answers,
        "raw_answers":             submission.get("raw_answers", {}),
        "submitted_at":            submission.get("submitted_at", now_iso),
        "landing_timestamp":       submission.get("landing_timestamp"),
        "created_at":              now_iso,
        "source_url":              source_url,
        "events":                  submission.get("events", []),
        # Enrichment lifecycle — honour what the submission already says, default to pending
        "enrichment_status":       submission.get("enrichment_status", "pending"),
        "enrichment_started_at":   submission.get("enrichment_started_at"),
        "enrichment_completed_at": submission.get("enrichment_completed_at"),
        "enrichment_error":        submission.get("enrichment_error"),
    }

    await db[SOCIAL_LEADS_COLL].update_one(
        {"submission_id": sub_id},
        {"$setOnInsert": doc},
        upsert=True,
    )


async def _sync_missing_social_leads(db) -> None:
    """
    Lazy backfill: find any form_submissions that don't yet have a social_leads
    document and create one.  Capped at 200 per call to avoid blocking requests.
    """
    try:
        existing_ids = set()
        async for doc in db[SOCIAL_LEADS_COLL].find({}, {"submission_id": 1, "_id": 0}):
            sid = doc.get("submission_id")
            if sid:
                existing_ids.add(sid)

        cursor = db[SUBMISSIONS_COLL].find({}).sort("submitted_at", -1).limit(200)
        async for sub in cursor:
            if sub.get("submission_id") not in existing_ids:
                await _upsert_social_lead(db, sub)
    except Exception as exc:
        print(f"[SOCIAL_LEADS] sync warning: {exc}", flush=True)


def _build_filter(
    platform:    Optional[str],
    category:    Optional[str],
    form_id:     Optional[str],
    campaign_id: Optional[str],
    search:      Optional[str],
) -> dict:
    flt: dict = {}
    if platform:
        p = platform.lower().strip()
        if p in ALLOWED_PLATFORMS:
            flt["platform"] = p
    if category:
        flt["category"] = {"$regex": f"^{re.escape(category.strip())}$", "$options": "i"}
    if form_id:
        flt["form_id"] = form_id.strip()
    if campaign_id:
        flt["campaign_id"] = campaign_id.strip()
    if search:
        q = re.escape(search.strip())
        flt["$or"] = [
            {"person.name":    {"$regex": q, "$options": "i"}},
            {"person.email":   {"$regex": q, "$options": "i"}},
            {"person.company": {"$regex": q, "$options": "i"}},
            {"form_name":      {"$regex": q, "$options": "i"}},
        ]
    return flt


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC HELPER — called from form_leads.py submit endpoint
# ═══════════════════════════════════════════════════════════════════════════════

async def create_social_lead_from_submission(submission: dict) -> None:
    """
    Called by the form submission endpoint immediately after saving.
    Non-fatal — logs and continues on any error.
    """
    try:
        db = get_db()
        await _upsert_social_lead(db, submission)
    except Exception as exc:
        print(f"[SOCIAL_LEADS] WARNING: could not create social lead: {exc}", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
# GET /social-leads
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "",
    summary="List social leads — server-side filtered, paginated, sorted",
    response_model=dict,
)
async def list_social_leads(
    platform:    Optional[str] = Query(None, description="linkedin|x|whatsapp|facebook|website|other"),
    category:    Optional[str] = Query(None),
    form_id:     Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
    search:      Optional[str] = Query(None, description="Search name, email, company, form name"),
    sort_by:     str           = Query("submitted_at",
                                       description="submitted_at|person.name|platform|category|form_name"),
    sort_dir:    int           = Query(-1, description="-1 newest first, 1 oldest first"),
    page:        int           = Query(1, ge=1),
    per_page:    int           = Query(50, ge=1, le=200),
):
    """
    Returns paginated social leads from MongoDB.
    All filtering and sorting happen server-side — nothing is loaded client-side en masse.
    """
    db = get_db()
    await _sync_missing_social_leads(db)

    coll = db[SOCIAL_LEADS_COLL]
    flt  = _build_filter(platform, category, form_id, campaign_id, search)

    total = await coll.count_documents(flt)
    skip  = (page - 1) * per_page

    allowed_sorts = {"submitted_at", "person.name", "platform", "category", "form_name"}
    if sort_by not in allowed_sorts:
        sort_by = "submitted_at"
    sort_dir = 1 if sort_dir == 1 else -1

    cursor = coll.find(flt).sort(sort_by, sort_dir).skip(skip).limit(per_page)
    docs   = await cursor.to_list(length=per_page)

    return {
        "success":  True,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "leads":    [_serialize(d) for d in docs],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /social-leads/stats
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/stats",
    summary="Platform / category / form / campaign counts",
    response_model=dict,
)
async def get_social_stats(
    platform:    Optional[str] = Query(None),
    category:    Optional[str] = Query(None),
    form_id:     Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
):
    """
    Returns real MongoDB aggregation counts.
    All numbers come directly from the database — nothing is hard-coded or fabricated.
    """
    db   = get_db()
    await _sync_missing_social_leads(db)
    coll = db[SOCIAL_LEADS_COLL]

    base_flt = _build_filter(platform, category, form_id, campaign_id, None)

    # Total
    total = await coll.count_documents(base_flt)

    # Platform counts
    platform_pipeline = [
        {"$match": base_flt},
        {"$group": {"_id": "$platform", "count": {"$sum": 1}}},
        {"$sort":  {"count": -1}},
    ]
    platform_docs   = await coll.aggregate(platform_pipeline).to_list(length=20)
    platform_counts = {d["_id"]: d["count"] for d in platform_docs}

    # Category counts
    cat_pipeline = [
        {"$match": base_flt},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort":  {"count": -1}},
    ]
    cat_docs       = await coll.aggregate(cat_pipeline).to_list(length=50)
    category_counts = [{"category": d["_id"], "count": d["count"]} for d in cat_docs]

    # Form counts
    form_pipeline = [
        {"$match": base_flt},
        {"$group": {"_id": {"form_id": "$form_id", "form_name": "$form_name"}, "count": {"$sum": 1}}},
        {"$sort":  {"count": -1}},
    ]
    form_docs   = await coll.aggregate(form_pipeline).to_list(length=50)
    form_counts = [
        {"form_id": d["_id"]["form_id"], "form_name": d["_id"]["form_name"], "count": d["count"]}
        for d in form_docs
    ]

    # Campaign counts
    camp_pipeline = [
        {"$match": {**base_flt, "campaign_id": {"$ne": None}}},
        {"$group": {
            "_id": {"campaign_id": "$campaign_id", "campaign_name": "$campaign_name"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    camp_docs      = await coll.aggregate(camp_pipeline).to_list(length=100)
    campaign_counts = [
        {
            "campaign_id":   d["_id"]["campaign_id"],
            "campaign_name": d["_id"]["campaign_name"],
            "count":         d["count"],
        }
        for d in camp_docs
    ]

    return {
        "success":         True,
        "total":           total,
        "platform_counts": platform_counts,
        "category_counts": category_counts,
        "form_counts":     form_counts,
        "campaign_counts": campaign_counts,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /social-leads/history  — grouped social form submission history
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/history",
    summary="Grouped social lead history for the History panel",
    response_model=dict,
)
async def get_social_leads_history(
    platform:    Optional[str] = Query(None),
    category:    Optional[str] = Query(None),
    form_id:     Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
):
    """
    Returns social lead submissions grouped by platform → category → form → campaign.
    Each group carries: count, first_submission, last_submission.

    Clearly labelled as "Social Form Collection" so History UI can distinguish
    these groups from "Lead Generation Run" entries.
    """
    db = get_db()
    await _sync_missing_social_leads(db)
    coll = db[SOCIAL_LEADS_COLL]

    base_flt = _build_filter(platform, category, form_id, campaign_id, None)

    pipeline = [
        {"$match": base_flt},
        {
            "$group": {
                "_id": {
                    "platform":      "$platform",
                    "category":      "$category",
                    "form_id":       "$form_id",
                    "form_name":     "$form_name",
                    "campaign_id":   "$campaign_id",
                    "campaign_name": "$campaign_name",
                },
                "count":            {"$sum": 1},
                "first_submission": {"$min": "$submitted_at"},
                "last_submission":  {"$max": "$submitted_at"},
            }
        },
        {"$sort": {"last_submission": -1}},
    ]
    docs = await coll.aggregate(pipeline).to_list(length=500)

    groups = []
    for d in docs:
        key = d["_id"]
        groups.append({
            "entry_type":    "social_form_collection",   # Phase 3: explicit type label
            "platform":      key.get("platform", "other"),
            "category":      key.get("category", ""),
            "form_id":       key.get("form_id", ""),
            "form_name":     key.get("form_name", ""),
            "campaign_id":   key.get("campaign_id"),
            "campaign_name": key.get("campaign_name"),
            "count":         d["count"],
            "first_submission": d.get("first_submission"),
            "last_submission":  d.get("last_submission"),
        })

    total = await coll.count_documents(base_flt)
    return {"success": True, "total": total, "groups": groups}


# ═══════════════════════════════════════════════════════════════════════════════
# GET /social-leads/export  — CSV export with active filters
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/export",
    summary="Export social leads as CSV (respects all active filters)",
)
async def export_social_leads(
    platform:    Optional[str] = Query(None),
    category:    Optional[str] = Query(None),
    form_id:     Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
    search:      Optional[str] = Query(None),
):
    """
    Streams a UTF-8 CSV of the matching social leads.
    Only exports leads that match the supplied filters — never exports unrelated leads.

    Columns: Submission ID, Name, Email, Phone, Company, Designation,
             Platform, Category, Form, Campaign, Submitted At, Enrichment Status
    """
    db   = get_db()
    coll = db[SOCIAL_LEADS_COLL]
    flt  = _build_filter(platform, category, form_id, campaign_id, search)

    cursor = coll.find(flt).sort("submitted_at", -1).limit(5000)
    docs   = await cursor.to_list(length=5000)

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # Header
    writer.writerow([
        "Submission ID", "Name", "Email", "Phone", "Company", "Designation",
        "Platform", "Category", "Form", "Campaign", "Submitted At",
        "Enrichment Status",
    ])

    for d in docs:
        p = d.get("person") or {}
        writer.writerow([
            d.get("submission_id", ""),
            p.get("name", ""),
            p.get("email", ""),
            p.get("phone", ""),
            p.get("company", ""),
            p.get("designation", ""),
            d.get("platform", ""),
            d.get("category", ""),
            d.get("form_name", ""),
            d.get("campaign_name", ""),
            d.get("submitted_at", ""),
            d.get("enrichment_status", ""),
        ])

    # Build a meaningful filename from the active filters
    parts = []
    if platform:     parts.append(platform)
    if category:     parts.append(category.replace(" ", "_"))
    if form_id:      parts.append(form_id[:20])
    if campaign_id:  parts.append(campaign_id[:20])
    filename = "social_leads" + ("_" + "_".join(parts) if parts else "") + ".csv"

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# POST /social-leads/seed-test-data
# ═══════════════════════════════════════════════════════════════════════════════

class _SeedRequest(BaseModel):
    clear_existing: bool = Field(
        default=False,
        description="If true, delete existing social_leads and related form_submissions first",
    )


@router.post(
    "/seed-test-data",
    summary="Insert realistic test social lead submissions (dev/QA only)",
    response_model=dict,
)
async def seed_test_data(payload: _SeedRequest):
    """
    Creates 10 realistic test leads across LinkedIn, X, and WhatsApp:
      LinkedIn × Real Estate  (3),  LinkedIn × Construction (2)
      X × Real Estate         (2),  X × Construction        (1)
      WhatsApp × Real Estate  (1),  WhatsApp × Construction (1)

    Forms and campaigns are created if they don't already exist.
    Uses stable submission_ids so calling multiple times is safe (upsert logic skips dupes).
    """
    db  = get_db()
    now = datetime.now(timezone.utc)

    if payload.clear_existing:
        test_sub_ids = [
            "SUB-TEST-LI-RE-001","SUB-TEST-LI-RE-002","SUB-TEST-LI-RE-003",
            "SUB-TEST-LI-CO-001","SUB-TEST-LI-CO-002",
            "SUB-TEST-X-RE-001","SUB-TEST-X-RE-002",
            "SUB-TEST-X-CO-001",
            "SUB-TEST-WA-RE-001","SUB-TEST-WA-CO-001",
        ]
        await db[SOCIAL_LEADS_COLL].delete_many({"submission_id": {"$in": test_sub_ids}})
        await db[SUBMISSIONS_COLL].delete_many({"submission_id": {"$in": test_sub_ids}})

    _TEST_FORM_RE  = "real-estate-investor-survey-TEST01"
    _TEST_FORM_CON = "construction-survey-TEST01"

    # ── Ensure test forms ──────────────────────────────────────────────────────
    async def _ensure_form(form_id: str, name: str, category: str, questions: list) -> None:
        if not await db[FORMS_COLL].find_one({"form_id": form_id}):
            await db[FORMS_COLL].insert_one({
                "form_id": form_id, "name": name, "category": category,
                "description": f"Test form for {category}",
                "questions": questions, "status": "active",
                "created_at": now.isoformat(), "updated_at": now.isoformat(),
                "deleted": False, "submission_count": 0, "form_version": 1,
            })

    re_questions = [
        {"question_id": "q_name",        "label": "Full Name",        "type": "short_text", "required": True,  "options": [], "display_order": 0},
        {"question_id": "q_email",       "label": "Email Address",    "type": "email",      "required": True,  "options": [], "display_order": 1},
        {"question_id": "q_phone",       "label": "Phone Number",     "type": "phone",      "required": False, "options": [], "display_order": 2},
        {"question_id": "q_company",     "label": "Company Name",     "type": "short_text", "required": False, "options": [], "display_order": 3},
        {"question_id": "q_designation", "label": "Designation",      "type": "short_text", "required": False, "options": [], "display_order": 4},
        {"question_id": "q_investment",  "label": "Investment Budget", "type": "dropdown",  "required": False, "display_order": 5,
         "options": [{"value": "10l_50l","label":"₹10L–₹50L"},{"value":"50l_1cr","label":"₹50L–₹1Cr"},{"value":"1cr_plus","label":"₹1Cr+"}]},
    ]
    con_questions = [
        {"question_id": "q_name",        "label": "Full Name",    "type": "short_text", "required": True,  "options": [], "display_order": 0},
        {"question_id": "q_email",       "label": "Email Address","type": "email",      "required": True,  "options": [], "display_order": 1},
        {"question_id": "q_phone",       "label": "Phone Number", "type": "phone",      "required": False, "options": [], "display_order": 2},
        {"question_id": "q_company",     "label": "Company Name", "type": "short_text", "required": False, "options": [], "display_order": 3},
        {"question_id": "q_designation", "label": "Designation",  "type": "short_text", "required": False, "options": [], "display_order": 4},
        {"question_id": "q_project",     "label": "Project Type", "type": "dropdown",   "required": False, "display_order": 5,
         "options": [{"value":"residential","label":"Residential"},{"value":"commercial","label":"Commercial"},{"value":"industrial","label":"Industrial"}]},
    ]
    await _ensure_form(_TEST_FORM_RE,  "Real Estate Investor Survey", "Real Estate",  re_questions)
    await _ensure_form(_TEST_FORM_CON, "Construction Survey",         "Construction", con_questions)

    # ── Ensure test campaigns ──────────────────────────────────────────────────
    CAMPAIGNS = {
        "CAMP-TEST-RE-LI": {"form_id": _TEST_FORM_RE,  "campaign_name": "Pune Real Estate August 2026", "platform": "linkedin"},
        "CAMP-TEST-RE-X":  {"form_id": _TEST_FORM_RE,  "campaign_name": "Pune RE X Campaign",           "platform": "x"},
        "CAMP-TEST-RE-WA": {"form_id": _TEST_FORM_RE,  "campaign_name": "RE WhatsApp Blast",            "platform": "whatsapp"},
        "CAMP-TEST-CO-LI": {"form_id": _TEST_FORM_CON, "campaign_name": "Construction LinkedIn Aug",    "platform": "linkedin"},
        "CAMP-TEST-CO-X":  {"form_id": _TEST_FORM_CON, "campaign_name": "Construction X Drive",         "platform": "x"},
        "CAMP-TEST-CO-WA": {"form_id": _TEST_FORM_CON, "campaign_name": "Construction WA Outreach",     "platform": "whatsapp"},
    }
    for cid, camp in CAMPAIGNS.items():
        if not await db[CAMPAIGNS_COLL].find_one({"campaign_id": cid}):
            await db[CAMPAIGNS_COLL].insert_one({
                "campaign_id": cid, "form_id": camp["form_id"],
                "campaign_name": camp["campaign_name"], "platform": camp["platform"],
                "tracking_url": f"/f/{camp['form_id']}?source={camp['platform']}&campaign_id={cid}",
                "created_at": now.isoformat(), "active": True,
            })

    # ── Test submissions ───────────────────────────────────────────────────────
    from datetime import timedelta

    def _ts(offset_min: int = 0) -> str:
        return (now - timedelta(minutes=offset_min)).isoformat()

    def _sub(sub_id, form_id, form_name, category, source, camp_id, camp_name, answers, offset):
        ts = _ts(offset)
        return {
            "submission_id": sub_id, "form_id": form_id, "form_name": form_name,
            "form_version": 1, "category": category, "source": source, "platform": source,
            "campaign_id": camp_id, "campaign_name": camp_name, "answers": answers,
            "raw_answers": {a["question_id"]: a["value"] for a in answers},
            "submitted_at": ts,
            "events": [
                {"event": "FORM_SUBMITTED",    "timestamp": ts, "message": f"Submission received for form {form_id}"},
                {"event": "VALIDATION_SUCCESS","timestamp": ts, "message": f"{len(answers)} answers validated OK"},
                {"event": "LEAD_SAVED",        "timestamp": ts, "message": f"Saved as {sub_id}"},
            ],
            "enrichment_status": "not_requested",
        }

    def _re_answers(name, email, phone, company, designation, budget):
        return [
            {"question_id":"q_name",       "label":"Full Name",        "type":"short_text","value": name},
            {"question_id":"q_email",      "label":"Email Address",    "type":"email",     "value": email},
            {"question_id":"q_phone",      "label":"Phone Number",     "type":"phone",     "value": phone},
            {"question_id":"q_company",    "label":"Company Name",     "type":"short_text","value": company},
            {"question_id":"q_designation","label":"Designation",      "type":"short_text","value": designation},
            {"question_id":"q_investment", "label":"Investment Budget","type":"dropdown",  "value": budget},
        ]

    def _con_answers(name, email, phone, company, designation, project):
        return [
            {"question_id":"q_name",       "label":"Full Name",    "type":"short_text","value": name},
            {"question_id":"q_email",      "label":"Email Address","type":"email",     "value": email},
            {"question_id":"q_phone",      "label":"Phone Number", "type":"phone",     "value": phone},
            {"question_id":"q_company",    "label":"Company Name", "type":"short_text","value": company},
            {"question_id":"q_designation","label":"Designation",  "type":"short_text","value": designation},
            {"question_id":"q_project",    "label":"Project Type", "type":"dropdown",  "value": project},
        ]

    submissions = [
        # LinkedIn × Real Estate (3)
        _sub("SUB-TEST-LI-RE-001",_TEST_FORM_RE,"Real Estate Investor Survey","Real Estate","linkedin","CAMP-TEST-RE-LI","Pune Real Estate August 2026",
             _re_answers("Rahul Sharma","rahul.sharma@gmail.com","9876543210","ABC Realty","Founder","1cr_plus"),10),
        _sub("SUB-TEST-LI-RE-002",_TEST_FORM_RE,"Real Estate Investor Survey","Real Estate","linkedin","CAMP-TEST-RE-LI","Pune Real Estate August 2026",
             _re_answers("Priya Mehta","priya.mehta@propertyhub.in","9823456789","PropertyHub India","Director","50l_1cr"),25),
        _sub("SUB-TEST-LI-RE-003",_TEST_FORM_RE,"Real Estate Investor Survey","Real Estate","linkedin","CAMP-TEST-RE-LI","Pune Real Estate August 2026",
             _re_answers("Amit Desai","amit.desai@desaigroup.com","9988776655","Desai Group","MD","1cr_plus"),60),
        # LinkedIn × Construction (2)
        _sub("SUB-TEST-LI-CO-001",_TEST_FORM_CON,"Construction Survey","Construction","linkedin","CAMP-TEST-CO-LI","Construction LinkedIn Aug",
             _con_answers("Suresh Patil","suresh@patilconstruction.com","9876012345","Patil Construction","CEO","commercial"),90),
        _sub("SUB-TEST-LI-CO-002",_TEST_FORM_CON,"Construction Survey","Construction","linkedin","CAMP-TEST-CO-LI","Construction LinkedIn Aug",
             _con_answers("Kavita Joshi","kavita.joshi@joshibuilders.in","9765432109","Joshi Builders","Partner","residential"),120),
        # X × Real Estate (2)
        _sub("SUB-TEST-X-RE-001",_TEST_FORM_RE,"Real Estate Investor Survey","Real Estate","x","CAMP-TEST-RE-X","Pune RE X Campaign",
             _re_answers("Deepak Nair","deepak.nair@nairhomes.com","9845123456","Nair Homes","CMO","50l_1cr"),150),
        _sub("SUB-TEST-X-RE-002",_TEST_FORM_RE,"Real Estate Investor Survey","Real Estate","x","CAMP-TEST-RE-X","Pune RE X Campaign",
             _re_answers("Swati Kulkarni","swati.k@kulkarnigroup.in","9871234567","Kulkarni Group","VP","10l_50l"),200),
        # X × Construction (1)
        _sub("SUB-TEST-X-CO-001",_TEST_FORM_CON,"Construction Survey","Construction","x","CAMP-TEST-CO-X","Construction X Drive",
             _con_answers("Ravi Kumar","ravi.kumar@kumarinfra.com","9800012345","Kumar Infra","Site Engineer","industrial"),240),
        # WhatsApp × Real Estate (1)
        _sub("SUB-TEST-WA-RE-001",_TEST_FORM_RE,"Real Estate Investor Survey","Real Estate","whatsapp","CAMP-TEST-RE-WA","RE WhatsApp Blast",
             _re_answers("Neha Singh","neha.singh@singhestates.in","9712345678","Singh Estates","COO","1cr_plus"),300),
        # WhatsApp × Construction (1)
        _sub("SUB-TEST-WA-CO-001",_TEST_FORM_CON,"Construction Survey","Construction","whatsapp","CAMP-TEST-CO-WA","Construction WA Outreach",
             _con_answers("Vikram Rao","vikram.rao@raobuilders.com","9823401234","Rao Builders","Engineer","commercial"),360),
    ]

    inserted = 0
    skipped  = 0
    for sub in submissions:
        existing = await db[SUBMISSIONS_COLL].find_one({"submission_id": sub["submission_id"]})
        if not existing:
            await db[SUBMISSIONS_COLL].insert_one(dict(sub))
            inserted += 1
        else:
            skipped += 1
        await _upsert_social_lead(db, sub)

    total = await db[SOCIAL_LEADS_COLL].count_documents({})
    return {
        "success":          True,
        "inserted":         inserted,
        "skipped_existing": skipped,
        "total_social_leads": total,
        "message": f"Seeded {inserted} new test submissions ({skipped} already existed).",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /social-leads/{submission_id}  — MUST be last (dynamic path segment)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/{submission_id}",
    summary="Get a single social lead by submission_id (full detail)",
    response_model=dict,
)
async def get_social_lead(submission_id: str):
    """
    Returns the full lead detail including:
      - person fields (name, email, phone, company, designation)
      - all form answers with labels
      - source attribution (platform, form, campaign)
      - event timeline (FORM_SUBMITTED → VALIDATION_SUCCESS → LEAD_SAVED → …)
      - enrichment status and timestamps
    """
    db   = get_db()
    coll = db[SOCIAL_LEADS_COLL]
    doc  = await coll.find_one({"submission_id": submission_id})

    if not doc:
        # Lazy sync: try pulling from form_submissions
        sub = await db[SUBMISSIONS_COLL].find_one({"submission_id": submission_id})
        if not sub:
            raise HTTPException(status_code=404, detail=f"Lead '{submission_id}' not found")
        await _upsert_social_lead(db, sub)
        doc = await coll.find_one({"submission_id": submission_id})

    if not doc:
        raise HTTPException(status_code=404, detail=f"Lead '{submission_id}' not found")

    # Enrich campaign_name if missing
    if doc.get("campaign_id") and not doc.get("campaign_name"):
        camp = await db[CAMPAIGNS_COLL].find_one(
            {"campaign_id": doc["campaign_id"]}, {"campaign_name": 1}
        )
        if camp:
            doc["campaign_name"] = camp.get("campaign_name")

    return {"success": True, "lead": _serialize(doc)}
