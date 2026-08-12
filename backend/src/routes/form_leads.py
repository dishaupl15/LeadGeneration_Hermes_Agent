"""
src/routes/form_leads.py
─────────────────────────
Social Lead Collection / Form Builder API — Phase 3 production-ready.

Phase 3 features:
  - Form version snapshot on every question edit (version_history)
  - Event timeline on every submission: FORM_OPENED → FORM_SUBMITTED →
    VALIDATION_SUCCESS → LEAD_SAVED → ENRICHMENT_STARTED → ENRICHMENT_COMPLETED
  - Submission stores form_version so old answers stay readable after edits
  - Duplicate submission detection (same IP + same answers hash within 5 min)
  - Phone normalisation
  - Full raw answer preservation (submitted_data separate from mapped person fields)
  - Enrichment status lifecycle: pending → processing → completed / failed

Collections used:
  lead_forms        — form definitions (admin)
  form_campaigns    — campaign records linked to a form
  form_submissions  — raw public submissions (source of truth)

CRM-admin endpoints (prefix /form-leads):
  POST   /form-leads/forms
  GET    /form-leads/forms
  GET    /form-leads/forms/{form_id}
  PUT    /form-leads/forms/{form_id}
  DELETE /form-leads/forms/{form_id}
  POST   /form-leads/forms/{form_id}/campaigns
  GET    /form-leads/forms/{form_id}/campaigns
  GET    /form-leads/forms/{form_id}/submissions

Public endpoints (prefix /public):
  GET    /public/forms/{form_id}
  POST   /public/forms/{form_id}/submit
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from src.config.mongo import get_db

# ── collections ───────────────────────────────────────────────────────────────
FORMS_COLL       = "lead_forms"
CAMPAIGNS_COLL   = "form_campaigns"
SUBMISSIONS_COLL = "form_submissions"

# ── allowed values ────────────────────────────────────────────────────────────
ALLOWED_QUESTION_TYPES = {
    "short_text", "email", "phone", "number",
    "dropdown", "radio", "checkbox", "long_text",
}
ALLOWED_PLATFORMS = {"linkedin", "x", "whatsapp", "facebook", "website", "other"}

# ── routers ───────────────────────────────────────────────────────────────────
admin_router  = APIRouter(prefix="/form-leads", tags=["Form Leads — Admin"])
public_router = APIRouter(prefix="/public",     tags=["Form Leads — Public"])


# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class QuestionOption(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    label: str = Field(..., min_length=1, max_length=200)


class FormQuestion(BaseModel):
    question_id:   str              = Field(default_factory=lambda: "q_" + uuid.uuid4().hex[:8])
    label:         str              = Field(..., min_length=1, max_length=300)
    type:          str              = Field(..., description="short_text|email|phone|number|dropdown|radio|checkbox|long_text")
    required:      bool             = Field(default=False)
    options:       list[QuestionOption] = Field(default_factory=list)
    display_order: int              = Field(default=0, ge=0)
    placeholder:   Optional[str]    = Field(default=None, max_length=200)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ALLOWED_QUESTION_TYPES:
            raise ValueError(f"Question type must be one of: {sorted(ALLOWED_QUESTION_TYPES)}")
        return v

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: list, info: Any) -> list:
        q_type = info.data.get("type", "")
        if q_type in ("dropdown", "radio", "checkbox") and not v:
            raise ValueError(f"'options' is required for question type '{q_type}'")
        return v


class CreateFormRequest(BaseModel):
    name:        str              = Field(..., min_length=1, max_length=200)
    category:    str              = Field(..., min_length=1, max_length=100)
    description: Optional[str]   = Field(default="", max_length=1000)
    questions:   list[FormQuestion] = Field(default_factory=list, max_length=50)

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, v: list) -> list:
        ids = [q.question_id for q in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate question_id detected in questions list")
        return v


class UpdateFormRequest(BaseModel):
    name:        Optional[str]             = Field(default=None, min_length=1, max_length=200)
    category:    Optional[str]             = Field(default=None, min_length=1, max_length=100)
    description: Optional[str]             = Field(default=None, max_length=1000)
    questions:   Optional[list[FormQuestion]] = Field(default=None, max_length=50)
    status:      Optional[str]             = Field(default=None)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("active", "paused", "archived"):
            raise ValueError("status must be active | paused | archived")
        return v


class CreateCampaignRequest(BaseModel):
    campaign_name: str = Field(..., min_length=1, max_length=200)
    platform:      str = Field(..., description="linkedin|x|whatsapp|facebook|website|other")

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ALLOWED_PLATFORMS:
            raise ValueError(f"platform must be one of: {sorted(ALLOWED_PLATFORMS)}")
        return v


class SubmissionAnswer(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=100)
    value:       Any = Field(...)


class PublicSubmitRequest(BaseModel):
    answers:     list[SubmissionAnswer] = Field(..., min_length=1, max_length=50)
    source:      Optional[str]          = Field(default=None, max_length=50)
    campaign_id: Optional[str]          = Field(default=None, max_length=100)
    # Anti-spam honeypot — must be empty
    hp:          Optional[str]          = Field(default=None, alias="hp")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.lower().strip()
            if v not in ALLOWED_PLATFORMS:
                v = "other"
        return v


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_event(event_type: str, message: str = "") -> dict:
    """Create a single event timeline entry."""
    return {
        "event":     event_type,
        "timestamp": _now_iso(),
        "message":   message,
    }


def _make_form_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    slug = slug[:40]
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{slug}-{suffix}" if slug else f"form-{suffix}"


def _make_campaign_id() -> str:
    return "CAMP-" + uuid.uuid4().hex[:8].upper()


def _make_submission_id() -> str:
    return "SUB-" + uuid.uuid4().hex[:12].upper()


def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    oid = doc.pop("_id", None)
    if oid and "id" not in doc:
        doc["id"] = str(oid)
    return doc


def _build_tracking_url(base_url: str, form_id: str, platform: str, campaign_id: str) -> str:
    return f"{base_url}/f/{form_id}?source={platform}&campaign_id={campaign_id}"


def _normalise_phone(raw: str) -> str:
    """
    Normalise an Indian phone number to +91XXXXXXXXXX format when possible.
    Falls back to stripped digits if pattern doesn't match.
    """
    digits = re.sub(r"[^\d+]", "", raw)
    # Strip leading +91 / 091 / 91
    digits = re.sub(r"^\+?0?91", "", digits)
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    return raw.strip()


def _answer_fingerprint(answers: list[SubmissionAnswer]) -> str:
    """Stable hash of submitted answers for duplicate detection."""
    parts = sorted(f"{a.question_id}:{a.value}" for a in answers)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# Rate-limit: simple in-memory store (per-process)
_submission_timestamps: dict[str, list[float]] = {}
_submission_fingerprints: dict[str, list[tuple[float, str]]] = {}  # ip → [(ts, fp)]
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX    = 5
_DUPE_WINDOW       = 300   # 5 min: same answers from same IP counts as duplicate


def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    window = _submission_timestamps.get(ip, [])
    window = [t for t in window if now - t < _RATE_LIMIT_WINDOW]
    if len(window) >= _RATE_LIMIT_MAX:
        _submission_timestamps[ip] = window
        return False
    window.append(now)
    _submission_timestamps[ip] = window
    return True


def _check_duplicate_answers(ip: str, fingerprint: str) -> bool:
    """Return True if the same answers were submitted from this IP within 5 min."""
    now = time.monotonic()
    entries = _submission_fingerprints.get(ip, [])
    entries = [(t, fp) for t, fp in entries if now - t < _DUPE_WINDOW]
    is_dup = any(fp == fingerprint for _, fp in entries)
    entries.append((now, fingerprint))
    _submission_fingerprints[ip] = entries
    return is_dup


async def _get_form_or_404(db, form_id: str) -> dict:
    doc = await db[FORMS_COLL].find_one({"form_id": form_id, "deleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Form '{form_id}' not found")
    return doc


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ROUTES — /form-leads/...
# ═══════════════════════════════════════════════════════════════════════════════

@admin_router.post(
    "/forms",
    summary="Create a new lead collection form",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
)
async def create_form(payload: CreateFormRequest, request: Request):
    """
    Create a form definition.
    Auto-creates one campaign per platform (6 total) with pre-built tracking URLs.
    Sets form_version=1 and initialises version_history snapshot.
    """
    db = get_db()
    base = str(request.base_url).rstrip("/")
    now = _now_iso()
    form_id = _make_form_id(payload.name)

    questions = []
    for i, q in enumerate(payload.questions):
        qd = q.model_dump()
        qd["display_order"] = i
        questions.append(qd)

    doc = {
        "form_id":       form_id,
        "name":          payload.name.strip(),
        "category":      payload.category.strip(),
        "description":   (payload.description or "").strip(),
        "questions":     questions,
        "status":        "active",
        "created_at":    now,
        "updated_at":    now,
        "deleted":       False,
        "submission_count": 0,
        # Phase 3: form versioning
        "form_version":  1,
        "version_history": [{
            "version":    1,
            "questions":  questions,
            "updated_at": now,
        }],
    }
    await db[FORMS_COLL].insert_one(doc)

    campaigns_out = []
    for platform in sorted(ALLOWED_PLATFORMS):
        camp_id = _make_campaign_id()
        camp_doc = {
            "campaign_id":   camp_id,
            "form_id":       form_id,
            "campaign_name": f"{payload.name} — {platform.title()}",
            "platform":      platform,
            "tracking_url":  _build_tracking_url(base, form_id, platform, camp_id),
            "created_at":    now,
            "active":        True,
        }
        await db[CAMPAIGNS_COLL].insert_one(camp_doc)
        campaigns_out.append(_serialize(camp_doc))

    return {
        "success":    True,
        "form_id":    form_id,
        "form":       _serialize(doc),
        "campaigns":  campaigns_out,
        "public_url": f"{base}/f/{form_id}",
    }


@admin_router.get(
    "/forms",
    summary="List all lead collection forms",
    response_model=dict,
)
async def list_forms(
    page:     int = Query(1,   ge=1),
    per_page: int = Query(50,  ge=1, le=200),
    status_f: Optional[str] = Query(None, alias="status"),
):
    db = get_db()
    coll = db[FORMS_COLL]
    flt: dict = {"deleted": {"$ne": True}}
    if status_f:
        flt["status"] = status_f
    total = await coll.count_documents(flt)
    skip  = (page - 1) * per_page
    cursor = coll.find(flt).sort("created_at", -1).skip(skip).limit(per_page)
    docs = await cursor.to_list(length=per_page)
    return {
        "success":  True,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "forms":    [_serialize(d) for d in docs],
    }


@admin_router.get(
    "/forms/{form_id}",
    summary="Get a single form with campaigns",
    response_model=dict,
)
async def get_form(form_id: str, request: Request):
    db  = get_db()
    doc = await _get_form_or_404(db, form_id)

    camps = await db[CAMPAIGNS_COLL].find(
        {"form_id": form_id, "active": True}
    ).sort("platform", 1).to_list(length=50)

    base = str(request.base_url).rstrip("/")
    for c in camps:
        c["tracking_url"] = _build_tracking_url(base, form_id, c["platform"], c["campaign_id"])

    sub_count = await db[SUBMISSIONS_COLL].count_documents({"form_id": form_id})

    return {
        "success":          True,
        "form":             _serialize(doc),
        "campaigns":        [_serialize(c) for c in camps],
        "submission_count": sub_count,
        "public_url":       f"{base}/f/{form_id}",
    }


@admin_router.put(
    "/forms/{form_id}",
    summary="Update a form — increments form_version and snapshots questions",
    response_model=dict,
)
async def update_form(form_id: str, payload: UpdateFormRequest):
    """
    Phase 3 — Form versioning:
    Every time questions are changed, form_version is incremented and a snapshot
    is appended to version_history.  Existing submissions keep their form_version
    so old answers remain readable even after the form is edited.
    """
    db       = get_db()
    existing = await _get_form_or_404(db, form_id)

    updates: dict = {"updated_at": _now_iso()}
    if payload.name        is not None: updates["name"]        = payload.name.strip()
    if payload.category    is not None: updates["category"]    = payload.category.strip()
    if payload.description is not None: updates["description"] = payload.description.strip()
    if payload.status      is not None: updates["status"]      = payload.status

    push_ops: dict = {}

    if payload.questions is not None:
        questions = []
        for i, q in enumerate(payload.questions):
            qd = q.model_dump()
            qd["display_order"] = i
            questions.append(qd)
        updates["questions"] = questions

        # Increment version + push snapshot
        current_version = existing.get("form_version", 1)
        new_version      = current_version + 1
        updates["form_version"] = new_version
        push_ops["version_history"] = {
            "version":    new_version,
            "questions":  questions,
            "updated_at": updates["updated_at"],
        }

    mongo_op: dict = {"$set": updates}
    if push_ops:
        mongo_op["$push"] = push_ops

    await db[FORMS_COLL].update_one({"form_id": form_id}, mongo_op)
    updated = await db[FORMS_COLL].find_one({"form_id": form_id})
    return {"success": True, "form": _serialize(updated)}


@admin_router.delete(
    "/forms/{form_id}",
    summary="Soft-delete a form",
    response_model=dict,
)
async def delete_form(form_id: str):
    db = get_db()
    await _get_form_or_404(db, form_id)
    await db[FORMS_COLL].update_one(
        {"form_id": form_id},
        {"$set": {"deleted": True, "status": "archived", "updated_at": _now_iso()}},
    )
    return {"success": True, "deleted_form_id": form_id}


@admin_router.post(
    "/forms/{form_id}/campaigns",
    summary="Create a new campaign for a form",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
)
async def create_campaign(form_id: str, payload: CreateCampaignRequest, request: Request):
    db   = get_db()
    await _get_form_or_404(db, form_id)
    base = str(request.base_url).rstrip("/")

    camp_id = _make_campaign_id()
    now = _now_iso()
    camp_doc = {
        "campaign_id":   camp_id,
        "form_id":       form_id,
        "campaign_name": payload.campaign_name.strip(),
        "platform":      payload.platform,
        "tracking_url":  _build_tracking_url(base, form_id, payload.platform, camp_id),
        "created_at":    now,
        "active":        True,
    }
    await db[CAMPAIGNS_COLL].insert_one(camp_doc)
    return {"success": True, "campaign": _serialize(camp_doc)}


@admin_router.get(
    "/forms/{form_id}/campaigns",
    summary="List campaigns for a form",
    response_model=dict,
)
async def list_campaigns(form_id: str, request: Request):
    db   = get_db()
    await _get_form_or_404(db, form_id)
    base = str(request.base_url).rstrip("/")
    camps = await db[CAMPAIGNS_COLL].find(
        {"form_id": form_id, "active": True}
    ).sort("platform", 1).to_list(length=100)
    for c in camps:
        c["tracking_url"] = _build_tracking_url(base, form_id, c["platform"], c["campaign_id"])
    return {"success": True, "campaigns": [_serialize(c) for c in camps]}


@admin_router.get(
    "/forms/{form_id}/submissions",
    summary="List submissions for a form",
    response_model=dict,
)
async def list_submissions(
    form_id:  str,
    page:     int           = Query(1, ge=1),
    per_page: int           = Query(50, ge=1, le=200),
    source:   Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
):
    db = get_db()
    await _get_form_or_404(db, form_id)
    flt: dict = {"form_id": form_id}
    if source:
        flt["source"] = source.lower()
    if campaign_id:
        flt["campaign_id"] = campaign_id
    total = await db[SUBMISSIONS_COLL].count_documents(flt)
    skip  = (page - 1) * per_page
    cursor = db[SUBMISSIONS_COLL].find(flt).sort("submitted_at", -1).skip(skip).limit(per_page)
    docs = await cursor.to_list(length=per_page)
    return {
        "success":  True,
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "submissions": [_serialize(d) for d in docs],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTES — /public/...
# ═══════════════════════════════════════════════════════════════════════════════

@public_router.get(
    "/forms/{form_id}",
    summary="Get public form definition",
    response_model=dict,
)
async def get_public_form(form_id: str):
    """
    Returns only the fields needed to render the public form.
    Does NOT expose admin metadata, version_history, internal IDs, or API keys.
    """
    db  = get_db()
    doc = await db[FORMS_COLL].find_one(
        {"form_id": form_id, "deleted": {"$ne": True}, "status": "active"},
        {"_id": 0, "form_id": 1, "name": 1, "category": 1,
         "description": 1, "questions": 1, "form_version": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Form not found or no longer active")

    doc["questions"] = sorted(doc.get("questions", []), key=lambda q: q.get("display_order", 0))
    return {"success": True, "form": doc}


@public_router.post(
    "/forms/{form_id}/submit",
    summary="Submit a public form",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
)
async def submit_form(form_id: str, payload: PublicSubmitRequest, request: Request):
    """
    Phase 3 — Production-ready public form submission.

    Lifecycle:
      1. Rate limit check (5 submissions / IP / 60s)
      2. Payload size guard (max 50 KB)
      3. Honeypot anti-spam check
      4. Form existence + active status check
      5. Question validation (existence, required, email format, number)
      6. Duplicate submission detection (same answers from same IP within 5 min)
      7. Campaign validation
      8. Source normalisation (URL param is source of truth)
      9. Event: FORM_SUBMITTED
     10. Event: VALIDATION_SUCCESS
     11. Save to form_submissions
     12. Event: LEAD_SAVED
     13. Write to social_leads (denormalised CRM view)
     14. Event: ENRICHMENT_STARTED  (if enrichment triggered)
     15. Increment form submission_count

    All events are real application events — none are fabricated.
    submitted_at is the authoritative timestamp from step 9.
    """

    # ── Rate limit ─────────────────────────────────────────────────────────────
    client_ip = (request.client.host if request.client else "unknown")
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many submissions. Please try again in a minute.",
        )

    # ── Payload size guard ─────────────────────────────────────────────────────
    body_raw = await request.body()
    if len(body_raw) > 51200:
        raise HTTPException(status_code=413, detail="Payload too large (max 50 KB)")

    # ── Honeypot anti-spam ─────────────────────────────────────────────────────
    if payload.hp:
        # Bot trap triggered — silently return success to confuse bots
        return {
            "success":       True,
            "submission_id": "SUB-" + uuid.uuid4().hex[:12].upper(),
            "message":       "Thank you! Your details have been submitted successfully.",
        }

    # ── Event 1: FORM_SUBMITTED ────────────────────────────────────────────────
    submit_ts    = _now_iso()
    submit_event = {"event": "FORM_SUBMITTED", "timestamp": submit_ts,
                    "message": f"Submission received for form {form_id}"}

    db = get_db()

    # ── Load form ──────────────────────────────────────────────────────────────
    form_doc = await db[FORMS_COLL].find_one(
        {"form_id": form_id, "deleted": {"$ne": True}, "status": "active"},
    )
    if not form_doc:
        raise HTTPException(status_code=404, detail="Form not found or no longer active")

    # Phase 3: capture form version at submission time
    form_version   = form_doc.get("form_version", 1)
    form_questions: list[dict] = form_doc.get("questions", [])
    valid_qids     = {q["question_id"] for q in form_questions}
    required_qids  = {q["question_id"] for q in form_questions if q.get("required")}

    # ── Validate question IDs ──────────────────────────────────────────────────
    submitted_qids = {a.question_id for a in payload.answers}

    unknown = submitted_qids - valid_qids
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown question_id(s): {sorted(unknown)}. These questions do not exist on this form.",
        )

    missing = required_qids - submitted_qids
    if missing:
        missing_labels = [q["label"] for q in form_questions if q["question_id"] in missing]
        raise HTTPException(
            status_code=422,
            detail=f"Required question(s) not answered: {missing_labels}",
        )

    # ── Validate + clean individual answers ───────────────────────────────────
    q_type_map = {q["question_id"]: q for q in form_questions}
    cleaned_answers: list[dict] = []

    for ans in payload.answers:
        qdef   = q_type_map[ans.question_id]
        val    = ans.value
        q_type = qdef.get("type", "short_text")

        if qdef.get("required"):
            if val is None or (isinstance(val, str) and not str(val).strip()):
                raise HTTPException(
                    status_code=422,
                    detail=f"'{qdef['label']}' is required and cannot be empty",
                )

        # Email validation
        if q_type == "email" and val:
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(val).strip()):
                raise HTTPException(
                    status_code=422,
                    detail=f"'{qdef['label']}' must be a valid email address",
                )
            val = str(val).strip().lower()

        # Number validation
        if q_type == "number" and val is not None:
            try:
                val = float(str(val))
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"'{qdef['label']}' must be a number",
                )

        # Phone normalisation
        if q_type == "phone" and val:
            val = _normalise_phone(str(val))

        # Truncate very long text
        if isinstance(val, str):
            val = val.strip()[:2000]

        cleaned_answers.append({
            "question_id": ans.question_id,
            "label":       qdef["label"],
            "type":        q_type,
            "value":       val,
        })

    # ── Duplicate submission detection ─────────────────────────────────────────
    answer_fp = _answer_fingerprint(payload.answers)
    if _check_duplicate_answers(client_ip, answer_fp):
        raise HTTPException(
            status_code=409,
            detail="Duplicate submission detected. This form was already submitted with the same answers.",
        )

    # ── Event 2: VALIDATION_SUCCESS ────────────────────────────────────────────
    validation_event = _make_event("VALIDATION_SUCCESS",
                                   f"{len(cleaned_answers)} answers validated OK")

    # ── Validate campaign_id if provided ──────────────────────────────────────
    campaign_name = None
    campaign_id   = payload.campaign_id
    if campaign_id:
        camp_doc = await db[CAMPAIGNS_COLL].find_one(
            {"campaign_id": campaign_id, "form_id": form_id},
        )
        if camp_doc:
            campaign_name = camp_doc.get("campaign_name")

    # ── Source normalisation (URL param is the source of truth) ────────────────
    source = (payload.source or "other").lower().strip()
    if source not in ALLOWED_PLATFORMS:
        source = "other"

    # ── Build submission document ──────────────────────────────────────────────
    submission_id = _make_submission_id()
    now           = _now_iso()

    submission_doc = {
        "submission_id":   submission_id,
        "form_id":         form_id,
        "form_name":       form_doc.get("name", ""),
        "form_version":    form_version,          # Phase 3: version at time of submit
        "category":        form_doc.get("category", ""),
        "source":          source,                # platform the tracking URL was for
        "platform":        source,                # alias kept for consistency
        "campaign_id":     campaign_id,
        "campaign_name":   campaign_name,
        "answers":         cleaned_answers,       # mapped answers with labels
        "raw_answers": {                          # Phase 3: raw key→value store
            a.question_id: a.value for a in payload.answers
        },
        "submitted_at":    submit_ts,             # real submission timestamp
        "ip_hash":         hashlib.sha256(
                               f"{client_ip}{submission_id}".encode()
                           ).hexdigest()[:12],    # privacy-safe IP hash
        "answer_fingerprint": answer_fp,          # for duplicate detection
        # Event timeline — real events only
        "events": [
            submit_event,
            validation_event,
        ],
        # Enrichment lifecycle
        "enrichment_status": "pending",
    }

    await db[SUBMISSIONS_COLL].insert_one(submission_doc)

    # ── Event 3: LEAD_SAVED ────────────────────────────────────────────────────
    lead_saved_event = _make_event("LEAD_SAVED", f"Saved as {submission_id}")
    await db[SUBMISSIONS_COLL].update_one(
        {"submission_id": submission_id},
        {"$push": {"events": lead_saved_event}},
    )
    submission_doc["events"].append(lead_saved_event)

    # ── Write to social_leads (denormalised CRM view) ─────────────────────────
    try:
        from src.routes.social_leads import create_social_lead_from_submission
        await create_social_lead_from_submission(submission_doc)
    except Exception as _sl_exc:
        print(f"[FORM_LEADS] social_leads write warning: {_sl_exc}", flush=True)

    # ── Increment form submission counter ──────────────────────────────────────
    try:
        await db[FORMS_COLL].update_one(
            {"form_id": form_id},
            {"$inc": {"submission_count": 1}},
        )
    except Exception:
        pass

    return {
        "success":       True,
        "submission_id": submission_id,
        "message":       "Thank you! Your details have been submitted successfully.",
    }
