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
"""

import os

import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()

# ── Module-level state ────────────────────────────────────────────────────────
_client: motor.motor_asyncio.AsyncIOMotorClient | None = None
_db:     motor.motor_asyncio.AsyncIOMotorDatabase | None = None

DB_NAME = "crm"
COLLECTION_NAME = "leads"


async def connect_db() -> None:
    """
    Open the Motor connection.  Call this once at application startup.
    Prints a confirmation line when the ping succeeds.
    """
    global _client, _db

    uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/crm")

    try:
        _client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        # Force an actual network round-trip to confirm reachability
        await _client.admin.command("ping")
        _db = _client[DB_NAME]
        print("✅ Connected to MongoDB")
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
