"""
google_maps/seen_store.py
──────────────────────────
Cross-request deduplication store for Google Maps place IDs.

Design
──────
Tracks Google Place IDs that have already been returned so that repeated
searches for the same category+area do not keep returning the same companies.

Two layers:
  1. In-memory set (fast, per-process, lost on restart)
  2. MongoDB collection "google_maps_seen" (persistent across restarts)
     — used ONLY if a MongoDB connection is already open (reuses the same
       Motor client as the main app, but writes to a SEPARATE collection).
     — Does NOT touch the "leads" collection.

If MongoDB is unavailable, falls back to in-memory only — the module still
works, just without cross-restart persistence.

Usage
─────
    from google_maps.seen_store import is_seen, mark_seen, load_from_db

    await load_from_db(category, state, district)
    if await is_seen(place_id):
        ...   # skip
    await mark_seen(place_id, name, category, state, district)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from google_maps.config import SEEN_COLLECTION_NAME

# ── In-memory store (scoped per request session, reset via clear_session) ─────
# Key: (category.lower(), state.lower(), district.lower()) → set of place_ids
_SESSION_SEEN: dict[tuple[str, str, str], set[str]] = {}
_store_lock = asyncio.Lock()


def _session_key(category: str, state: str, district: str) -> tuple[str, str, str]:
    return (category.lower().strip(), state.lower().strip(), (district or "").lower().strip())


def _get_in_memory_seen(category: str, state: str, district: str) -> set[str]:
    return _SESSION_SEEN.setdefault(_session_key(category, state, district), set())


# ── MongoDB helpers ───────────────────────────────────────────────────────────

def _get_collection():
    """
    Return the 'google_maps_seen' Motor collection, or None if DB not ready.
    Reuses the app's existing Motor client — does NOT create a new connection.
    """
    try:
        from src.config.mongo import get_db
        db = get_db()
        return db[SEEN_COLLECTION_NAME]
    except Exception:
        return None


async def load_from_db(category: str, state: str, district: str) -> int:
    """
    Load previously seen place IDs from MongoDB into the in-memory store.
    Called once at the start of each discover_businesses() run.

    Returns the number of IDs loaded.
    """
    collection = _get_collection()
    if collection is None:
        return 0

    seen_set = _get_in_memory_seen(category, state, district)
    try:
        cursor = collection.find(
            {
                "category": category.lower().strip(),
                "state":    state.lower().strip(),
                "district": (district or "").lower().strip(),
            },
            {"place_id": 1, "_id": 0},
        )
        docs = await cursor.to_list(length=50_000)
        loaded = 0
        for doc in docs:
            pid = doc.get("place_id", "")
            if pid and pid not in seen_set:
                seen_set.add(pid)
                loaded += 1
        return loaded
    except Exception:
        return 0


async def is_seen(
    place_id: str,
    category: str,
    state: str,
    district: str,
) -> bool:
    """Return True if this place_id was seen before for this search context."""
    seen_set = _get_in_memory_seen(category, state, district)
    return place_id in seen_set


async def mark_seen(
    place_id: str,
    name: str,
    category: str,
    state: str,
    district: str,
) -> None:
    """
    Mark a place_id as seen:
      1. Add to in-memory set.
      2. Upsert into MongoDB (if available).
    """
    seen_set = _get_in_memory_seen(category, state, district)
    seen_set.add(place_id)

    collection = _get_collection()
    if collection is None:
        return

    try:
        await collection.update_one(
            {"place_id": place_id},
            {
                "$set": {
                    "place_id": place_id,
                    "name":     name,
                    "category": category.lower().strip(),
                    "state":    state.lower().strip(),
                    "district": (district or "").lower().strip(),
                    "seen_at":  datetime.now(timezone.utc),
                },
            },
            upsert=True,
        )
    except Exception:
        pass  # MongoDB unavailable — in-memory still works


async def clear_session(category: str, state: str, district: str) -> None:
    """
    Clear the in-memory seen set for this search context.
    Call this to allow re-discovering the same places (e.g. in tests).
    Does NOT modify MongoDB.
    """
    key = _session_key(category, state, district)
    _SESSION_SEEN.pop(key, None)


async def count_seen(category: str, state: str, district: str) -> int:
    """Return how many place IDs are tracked for this search context."""
    return len(_get_in_memory_seen(category, state, district))
