"""
src/controllers/lead_controller.py
------------------------------------
LeadController: pure business logic, zero HTTP / FastAPI coupling.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from src.config.mongo import COLLECTION_NAME, get_db
from src.models.lead import Category
from src.schemas.lead_schema import (
    GeneratedCompany,
    GenerateLeadsRequest,
    InsertLeadsResponse,
    LeadCreateRequest,
    LeadResponse,
    LeadsListResponse,
    LeadUpdateRequest,
    MessageResponse,
)


# ── Custom exception ──────────────────────────────────────────────────────────

class LeadNotFoundError(Exception):
    """Raised when a lead ID cannot be found in the store."""

    def __init__(self, lead_id: str):
        super().__init__(f"Lead with id '{lead_id}' not found.")
        self.lead_id = lead_id


# ── Dummy data templates ──────────────────────────────────────────────────────

_COMPANY_PREFIXES: list[str] = [
    "ABC", "XYZ", "Prime", "Global", "Metro",
    "Elite", "Smart", "Bright", "Royal", "Pioneer",
]

_COMPANY_SUFFIXES: dict[str, list[str]] = {
    "Real Estate":            ["Builders", "Realty", "Properties", "Estates", "Developers"],
    "E-Commerce":             ["Mart", "Shop", "Store", "Bazaar", "Market"],
    "Information Technology": ["Tech", "Solutions", "Systems", "Software", "Digital"],
    "Healthcare":             ["Hospital", "Clinic", "Care", "Medical", "Health"],
    "Manufacturing":          ["Industries", "Manufacturing", "Fabricators", "Engineering", "Works"],
    "Education":              ["Academy", "Institute", "School", "College", "University"],
    "Finance":                ["Finance", "Capital", "Investments", "Bank", "Financial"],
    "Hotels":                 ["Hotel", "Inn", "Resorts", "Hospitality", "Suites"],
    "Construction":           ["Construction", "Builders", "Infrastructure", "Contractors", "Projects"],
    "Other":                  ["Enterprises", "Group", "Corporation", "Services", "Company"],
}


# ── Controller ────────────────────────────────────────────────────────────────

class LeadController:
    """
    Stateless controller.
    In-memory _store is used only by the CRUD endpoints (Phase 1).
    generate_leads writes directly to MongoDB.
    """

    _store: list[dict] = []

    # ── Private helpers ───────────────────────────────────────────────────────

    @classmethod
    def _find(cls, lead_id: str) -> dict:
        for lead in cls._store:
            if lead["id"] == lead_id:
                return lead
        raise LeadNotFoundError(lead_id)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    # ── Generate leads + persist to MongoDB ──────────────────────────────────

    @classmethod
    async def generate_leads(cls, payload: GenerateLeadsRequest) -> InsertLeadsResponse:
        """
        Build lead data for the requested industry and city, deduplicate by
        company_name + website, and insert every unique company into MongoDB.

        Phase 2: replace the dummy-data block with a Hermes AI API call.
        The dedup + insert logic below stays unchanged.
        """
        suffixes = _COMPANY_SUFFIXES.get(payload.industry, _COMPANY_SUFFIXES["Other"])
        companies: list[GeneratedCompany] = []

        for i in range(payload.count):
            prefix = _COMPANY_PREFIXES[i % len(_COMPANY_PREFIXES)]
            suffix = suffixes[i % len(suffixes)]
            company_name = f"{prefix} {suffix}"
            domain = company_name.lower().replace(" ", "")
            website = f"https://www.{domain}.com"

            companies.append(
                GeneratedCompany(
                    company_name=company_name,
                    website=website,
                    emails=[f"info@{domain}.com", f"sales@{domain}.com"],
                    phones=[f"+91 {9800000000 + i:010d}"],
                    address=f"{payload.city}, {payload.industry} District",
                    city=payload.city,
                    state="Maharashtra",
                    country="India",
                )
            )

        # ── Deduplicate by company_name + website ─────────────────────────────
        seen: set[tuple[str, str]] = set()
        unique: list[GeneratedCompany] = []
        for c in companies:
            key = (c.company_name.lower(), c.website.lower())
            if key not in seen:
                seen.add(key)
                unique.append(c)

        print(f"Saving {len(unique)} companies...")

        # ── Build MongoDB documents with all required fields ──────────────────
        now = cls._now()
        docs = [
            {
                "company_name": c.company_name,
                "website":      c.website,
                "emails":       c.emails,
                "phones":       c.phones,
                "address":      c.address,
                "city":         c.city,
                "state":        c.state,
                "country":      c.country,
                "created_at":   now,
            }
            for c in unique
        ]

        # ── Insert into MongoDB ───────────────────────────────────────────────
        db = get_db()
        collection = db[COLLECTION_NAME]
        result = await collection.insert_many(docs)
        inserted = len(result.inserted_ids)

        print("Saved successfully.")
        print(f"Total inserted: {inserted}")

        return InsertLeadsResponse(success=True, inserted=inserted)

    # ── CRUD (Phase 1 — in-memory) ────────────────────────────────────────────

    @classmethod
    def list_leads(
        cls,
        category: Optional[Category] = None,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> LeadsListResponse:
        results = list(cls._store)
        if category:
            results = [l for l in results if l["category"] == category.value]
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
        page_slice = results[(page - 1) * per_page : page * per_page]
        return LeadsListResponse(
            total=total,
            leads=[LeadResponse(**l) for l in page_slice],
            page=page,
            per_page=per_page,
        )

    @classmethod
    def create_lead(cls, payload: LeadCreateRequest) -> LeadResponse:
        now = cls._now()
        doc = {
            "id":           str(uuid.uuid4()),
            "company_name": payload.company_name,
            "email":        str(payload.email),
            "phone":        payload.phone,
            "address":      payload.address,
            "category":     payload.category.value,
            "created_at":   now,
            "updated_at":   None,
        }
        cls._store.append(doc)
        return LeadResponse(**doc)

    @classmethod
    def get_lead(cls, lead_id: str) -> LeadResponse:
        return LeadResponse(**cls._find(lead_id))

    @classmethod
    def update_lead(cls, lead_id: str, payload: LeadUpdateRequest) -> LeadResponse:
        doc = cls._find(lead_id)
        updates = payload.model_dump(exclude_none=True)
        if "category" in updates:
            updates["category"] = updates["category"].value
        doc.update(updates)
        doc["updated_at"] = cls._now()
        return LeadResponse(**doc)

    @classmethod
    def delete_lead(cls, lead_id: str) -> MessageResponse:
        doc = cls._find(lead_id)
        cls._store.remove(doc)
        return MessageResponse(message=f"Lead '{lead_id}' deleted successfully.")

    @staticmethod
    def list_categories() -> list[str]:
        return [c.value for c in Category]
