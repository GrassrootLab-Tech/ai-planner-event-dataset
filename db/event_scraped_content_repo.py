from motor.motor_asyncio import AsyncIOMotorCollection

from models.event_scraped_content import EventScrapedContent
from utils.logger import log_pretty, logger


class EventScrapedContentRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def ensure_indexes(self) -> None:
        logger.info("Ensuring indexes on event_scraped_content collection")
        await self._collection.create_index([("page_url", 1), ("scraped_at", -1)])
        await self._collection.create_index([("website", 1), ("scraped_at", -1)])
        logger.info("Indexes ready")

    async def insert(self, doc: EventScrapedContent) -> str:
        log_pretty("Inserting document into MongoDB", doc.to_mongo())
        result = await self._collection.insert_one(doc.to_mongo())
        inserted_id = str(result.inserted_id)
        logger.info("Document saved with id=%s", inserted_id)
        return inserted_id
