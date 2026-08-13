"""
src/config/mongo.py
────────────────────
Shared Motor (async MongoDB) client.

Design
──────
A single AsyncIOMotorClient is created once at process start (via FastAPI's
lifespan hook in main.py) and stored in this module-level object.
Every part of the app that needs the DB imports `get_db()` from here — no
re-connecting on every request.

Usage
─────
    from src.config.mongo import get_db
    db = get_db()
    collection = db["leads"]

Collections
───────────
  categories          — stores all known industry category names
  leads               — legacy fallback collection (no specific category)
  leads_{slug}        — per-category lead collections (e.g. leads_construction)
  google_maps_seen    — cross-request place_id dedup store
"""

import os
import re

import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()

# ── Module-level state ────────────────────────────────────────────────────────
_client: motor.motor_asyncio.AsyncIOMotorClient | None = None
_db:     motor.motor_asyncio.AsyncIOMotorDatabase | None = None

DB_NAME = "crm"
COLLECTION_NAME = "leads"         # legacy fallback — keep for backward compat
CATEGORIES_COLLECTION = "categories"  # stores known industry category names


# ── All known category names (mirrors src/models/lead.py Category enum) ──────
ALL_CATEGORIES: list[str] = [
    "Technology", "SaaS", "AI", "FinTech", "Healthcare", "Pharma",
    "Manufacturing", "Construction", "Real Estate", "Education", "Logistics",
    "Automotive", "Retail", "E-Commerce", "Hospitality", "Travel", "Energy",
    "Agriculture", "Media", "Marketing", "Consulting", "Legal", "Finance",
    "Insurance", "Telecommunications", "Cybersecurity", "Biotech", "Aerospace",
]


def collection_for_category(category: str) -> str:
    """
    Return the MongoDB collection name for a given industry category.

    Each category gets its own collection so leads are separated by industry:
      'Construction'  → 'leads_construction'
      'Real Estate'   → 'leads_real_estate'
      'FinTech'       → 'leads_fintech'
      ''  / None      → 'leads'   (fallback)

    Rules:
      - Lowercase
      - Spaces and hyphens → underscores
      - Special chars stripped
      - Prefixed with 'leads_'
    """
    if not category:
        return COLLECTION_NAME
    slug = category.strip().lower()
    slug = re.sub(r"[\s\-]+", "_", slug)
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    slug = slug.strip("_")
    return f"leads_{slug}" if slug else COLLECTION_NAME


async def _seed_categories(db: motor.motor_asyncio.AsyncIOMotorDatabase) -> None:
    """
    Ensure the 'categories' collection is populated with all known category names.
    Uses upsert so existing docs are never duplicated.
    Each document: { name: "Construction", slug: "leads_construction", lead_count: 0 }
    """
    coll = db[CATEGORIES_COLLECTION]
    for cat_name in ALL_CATEGORIES:
        slug = collection_for_category(cat_name)
        await coll.update_one(
            {"name": cat_name},
            {"$setOnInsert": {
                "name":       cat_name,
                "slug":       slug,
                "collection": slug,
            }},
            upsert=True,
        )
    # Ensure an index on name for fast lookup
    await coll.create_index("name", unique=True, background=True)
    print(f"✅ Categories collection seeded ({len(ALL_CATEGORIES)} categories)")


async def ensure_lead_indexes(
    db: motor.motor_asyncio.AsyncIOMotorDatabase,
    category: str,
) -> None:
    """
    Ensure indexes on a category-specific leads collection.
    Called lazily the first time a category collection is written to.
    Indexes:
      - website (unique-ish, used for deduplication)
      - company_name
      - created_at (for sorted queries)
      - status     (for status filter counts)
    """
    coll_name = collection_for_category(category)
    coll = db[coll_name]
    await coll.create_index("website", background=True, sparse=True)
    await coll.create_index("company_name", background=True)
    await coll.create_index("created_at", background=True)
    await coll.create_index("status", background=True)


async def _ensure_history_indexes(db: motor.motor_asyncio.AsyncIOMotorDatabase) -> None:
    """Create indexes on the generation_history collection."""
    coll = db["generation_history"]
    await coll.create_index("run_id", unique=True, background=True)
    await coll.create_index("started_at", background=True)
    await coll.create_index("category", background=True)
    await coll.create_index("status", background=True)
    print("✅ generation_history indexes ensured")

    # ── Form Leads indexes ────────────────────────────────────────────────────
    forms_coll = db["lead_forms"]
    await forms_coll.create_index("form_id", unique=True, background=True)
    await forms_coll.create_index("category", background=True)
    await forms_coll.create_index("status", background=True)
    await forms_coll.create_index("created_at", background=True)

    camps_coll = db["form_campaigns"]
    await camps_coll.create_index("campaign_id", unique=True, background=True)
    await camps_coll.create_index("form_id", background=True)
    await camps_coll.create_index("platform", background=True)

    subs_coll = db["form_submissions"]
    await subs_coll.create_index("submission_id", unique=True, background=True)
    await subs_coll.create_index("form_id", background=True)
    await subs_coll.create_index("source", background=True)
    await subs_coll.create_index("campaign_id", background=True)
    await subs_coll.create_index("submitted_at", background=True)
    print("✅ form_leads indexes ensured")

    # ── Social Leads Phase 2 indexes ──────────────────────────────────────────
    sl_coll = db["social_leads"]
    await sl_coll.create_index("submission_id", unique=True, background=True)
    await sl_coll.create_index("platform", background=True)
    await sl_coll.create_index("category", background=True)
    await sl_coll.create_index("form_id", background=True)
    await sl_coll.create_index("campaign_id", background=True)
    await sl_coll.create_index("submitted_at", background=True)
    await sl_coll.create_index(
        [("platform", 1), ("category", 1), ("form_id", 1)],
        background=True,
        name="platform_category_form",
    )
    print("✅ social_leads indexes ensured")


async def connect_db() -> None:
    """
    Open the Motor connection.  Call this once at application startup.
    Prints a confirmation line when the ping succeeds.
    Also seeds the categories collection with all known category names.
    """
    global _client, _db

    uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/crm")

    try:
        _client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        # Force an actual network round-trip to confirm reachability
        await _client.admin.command("ping")
        _db = _client[DB_NAME]
        print("✅ Connected to MongoDB")
        # Seed category names into the 'categories' collection
        await _seed_categories(_db)
        # Ensure indexes on generation_history collection
        await _ensure_history_indexes(_db)
    except Exception as exc:
        print(f"❌ MongoDB connection failed: {exc}")
        raise


async def close_db() -> None:
    """Close the Motor connection.  Call this on application shutdown."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        print("🔌 MongoDB connection closed")


def get_db() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    """Return the shared database handle.  Raises if connect_db() was not called."""
    if _db is None:
        raise RuntimeError("Database not initialised — call connect_db() first.")
    return _db
