"""Check MongoDB connection and current data structure."""
import asyncio, os
import motor.motor_asyncio
from dotenv import load_dotenv
load_dotenv(".env", override=True)

async def main():
    uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/crm")
    client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
        db = client["crm"]
        colls = await db.list_collection_names()
        print(f"✅ Connected to MongoDB!")
        print(f"   URI: {uri}")
        print(f"   Collections in 'crm': {colls}")

        if "leads" in colls:
            count = await db["leads"].count_documents({})
            print(f"\n   'leads' collection: {count} total documents")
            # Check category distribution
            pipeline = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}]
            cursor = db["leads"].aggregate(pipeline)
            cats = await cursor.to_list(length=100)
            if cats:
                print(f"\n   Current category breakdown:")
                for c in sorted(cats, key=lambda x: -(x["count"])):
                    print(f"     '{c['_id']}': {c['count']} docs")
            else:
                print("\n   No category field found in any document!")

            # Sample doc keys
            doc = await db["leads"].find_one()
            if doc:
                print(f"\n   Sample doc fields: {[k for k in doc.keys() if not k.startswith('_')]}")

        # Check ALL collection names to see what categories exist
        print(f"\n   All collections: {colls}")

    except Exception as e:
        print(f"❌ Connection FAILED: {e}")
    finally:
        client.close()

asyncio.run(main())
