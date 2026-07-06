from motor.motor_asyncio import AsyncIOMotorCollection

from models.event_scraped_chunk import EventScrapedChunk
from utils.logger import log_pretty, logger


class EventScrapedChunksRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def ensure_indexes(self) -> None:
        logger.info("Ensuring indexes on event_scraped_chunks collection")
        await self._collection.create_index([("page_url", 1), ("scraped_at", -1)])
        logger.info("Indexes ready")

    async def insert_many(self, docs: list[EventScrapedChunk]) -> list[str]:
        if not docs:
            return []
        payloads = [doc.to_mongo() for doc in docs]
        log_pretty("Inserting chunks into MongoDB", {"count": len(payloads)})
        result = await self._collection.insert_many(payloads)
        inserted_ids = [str(doc_id) for doc_id in result.inserted_ids]
        logger.info("Saved %d chunks", len(inserted_ids))
        return inserted_ids
