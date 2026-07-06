from motor.motor_asyncio import AsyncIOMotorCollection

from models.event_scraped_content import EventScrapedContent, Status
from utils.logger import log_pretty, logger


class EventScrapedContentRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def ensure_indexes(self) -> None:
        logger.info("Ensuring indexes on event_scraped_content collection")
        await self._collection.create_index([("page_url", 1), ("scraped_at", -1)])
        await self._collection.create_index([("website", 1), ("scraped_at", -1)])
        logger.info("Indexes ready")

    async def get_by_page_url(self, page_url: str) -> EventScrapedContent | None:
        doc = await self._collection.find_one({"page_url": page_url})
        if doc is None:
            return None
        doc.pop("_id", None)
        return EventScrapedContent.model_validate(doc)

    async def update_status(self, page_url: str, status: Status) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": {"status": status}},
        )
        logger.info("Updated status=%s for page_url=%s", status, page_url)

    async def insert(self, doc: EventScrapedContent) -> str:
        log_pretty("Inserting document into MongoDB", doc.to_mongo())
        result = await self._collection.insert_one(doc.to_mongo())
        inserted_id = str(result.inserted_id)
        logger.info("Document saved with id=%s", inserted_id)
        return inserted_id
