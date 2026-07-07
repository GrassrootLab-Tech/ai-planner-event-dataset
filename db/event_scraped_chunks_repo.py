from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from models.event_scraped_chunk import EventScrapedChunk, IsUsable
from utils.logger import log_pretty, logger


class EventScrapedChunksRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def list_by_page_url(self, page_url: str) -> list[tuple[str, EventScrapedChunk]]:
        cursor = self._collection.find({"page_url": page_url}).sort("_id", 1)
        results: list[tuple[str, EventScrapedChunk]] = []
        async for doc in cursor:
            chunk_id = str(doc.pop("_id"))
            results.append((chunk_id, EventScrapedChunk.model_validate(doc)))
        return results

    async def update_is_usable(self, chunk_id: str, is_usable: IsUsable) -> None:
        await self._collection.update_one(
            {"_id": ObjectId(chunk_id)},
            {"$set": {"is_usable": is_usable.model_dump()}},
        )

    async def update_metadata_tags(self, chunk_id: str, tags: dict) -> None:
        await self._collection.update_one(
            {"_id": ObjectId(chunk_id)},
            {"$set": {"metadata_tags": tags}},
        )

    async def insert_many(self, docs: list[EventScrapedChunk]) -> list[str]:
        if not docs:
            return []
        payloads = [doc.to_mongo() for doc in docs]
        log_pretty("Inserting chunks into MongoDB", {"count": len(payloads)})
        result = await self._collection.insert_many(payloads)
        inserted_ids = [str(doc_id) for doc_id in result.inserted_ids]
        logger.info("Saved %d chunks", len(inserted_ids))
        return inserted_ids
