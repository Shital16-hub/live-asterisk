import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import CollectionInvalid
from dotenv import load_dotenv
from datetime import datetime
# mongodb://root:xbTNLR4G8C8g4ge6@198.27.69.154:27017/admin?authSource=admin
# mongodb://root:xbTNLR4G8C8g4ge6@51.81.232.138:27018/admin?authSource=admin

# Load .env variables
load_dotenv()

class TranscriptLogger:
    """
    Async logger for `towing_services_transcripts_logs`.
    Ensures the collection exists and upserts with a fixed ISO-8601 timestamp string.
    """
    COLLECTION_NAME = "towing_services_transcripts_logs"
    TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # e.g., "2025-06-21T08:30:00Z"

    def __init__(self, client: AsyncIOMotorClient, db):
        self.client = client
        self.db = db
        self.collection = db[self.COLLECTION_NAME]

    @classmethod
    async def create(cls):
        host    = os.getenv("MONGO_HOST", "localhost")
        port    = int(os.getenv("MONGO_PORT", 27017))
        user    = os.getenv("MONGO_INITDB_ROOT_USERNAME")
        pwd     = os.getenv("MONGO_INITDB_ROOT_PASSWORD")
        db_name = os.getenv("MONGO_INITDB_DATABASE", "admin")

        if not (user and pwd):
            print("[TranscriptLogger] Missing MongoDB credentials in environment")
            raise RuntimeError("Missing MongoDB credentials in environment")

        uri = f"mongodb://{user}:***@{host}:{port}/{db_name}?authSource=admin"
        print(f"[TranscriptLogger] Connecting to MongoDB at {uri}")
        real_uri = f"mongodb://{user}:{pwd}@{host}:{port}/{db_name}?authSource=admin"
        client = AsyncIOMotorClient(real_uri)
        db = client[db_name]

        # Create the collection if it doesn't exist
        existing = await db.list_collection_names()
        if cls.COLLECTION_NAME not in existing:
            try:
                await db.create_collection(cls.COLLECTION_NAME)
                print(f"[TranscriptLogger] Created collection: {cls.COLLECTION_NAME}")
            except CollectionInvalid:
                pass

        print(f"[TranscriptLogger] Using collection: {cls.COLLECTION_NAME}")
        return cls(client, db)

    async def upsert_log(self, log_id: str, data: dict):
        """
        Upsert a document by log_id, merging `data` and setting `timestamp`
        to the current UTC time in ISO-8601 format.
        """
        ts_str = datetime.utcnow().strftime(self.TIMESTAMP_FORMAT)
        payload = {**data, "timestamp": ts_str}
        try:
            result = await self.collection.update_one(
                {"log_id": log_id},
                {"$set": payload},
                upsert=True
            )
            print(f"[TranscriptLogger] Upserted log for {log_id}: upserted_id={getattr(result, 'upserted_id', None)}, modified_count={getattr(result, 'modified_count', None)}")
            return result
        except Exception as e:
            print(f"[TranscriptLogger] ERROR during upsert_log for {log_id}: {e}")
            raise

async def main():
    # Initialize the logger
    logger = await TranscriptLogger.create()

    # Example upsert
    result = await logger.upsert_log(
        log_id="abc1234",
        data={
            "caller": "John Doe",
            "transcript": "Hi, I need a tow to 123 Maple St.",
            "status": "pending"
        }
    )

    print("Upserted ID:", result.upserted_id)
    print("Modified count:", result.modified_count)

    # Close client
    logger.client.close()

if __name__ == "__main__":
    asyncio.run(main())