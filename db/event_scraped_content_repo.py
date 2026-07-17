from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from models.event_scraped_content import EventScrapedContent, Status
from utils.logger import log_pretty, logger


class EventScrapedContentRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def get_by_page_url(self, page_url: str) -> EventScrapedContent | None:
        doc = await self._collection.find_one({"page_url": page_url})
        if doc is None:
            return None
        doc.pop("_id", None)
        return EventScrapedContent.model_validate(doc)

    async def get_id_by_page_url(self, page_url: str) -> str | None:
        doc = await self._collection.find_one({"page_url": page_url}, {"_id": 1})
        if doc is None:
            return None
        return str(doc["_id"])

    async def get_by_id(self, content_id: str) -> EventScrapedContent | None:
        doc = await self._collection.find_one({"_id": ObjectId(content_id)})
        if doc is None:
            return None
        doc.pop("_id", None)
        return EventScrapedContent.model_validate(doc)

    async def list_by_status(
        self,
        status: Status,
    ) -> list[tuple[str, EventScrapedContent]]:
        cursor = self._collection.find({"status": status})
        docs: list[tuple[str, EventScrapedContent]] = []
        async for raw in cursor:
            content_id = str(raw.pop("_id"))
            docs.append((content_id, EventScrapedContent.model_validate(raw)))
        return docs

    async def update_status(self, page_url: str, status: Status) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": {"status": status}},
        )
        logger.info("Updated status=%s for page_url=%s", status, page_url)

    async def set_claude_batch_queued(self, page_url: str, task_id: str) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {
                "$set": {
                    "status": "claude_batch_queued",
                    "claude_task_id": task_id,
                },
            },
        )
        logger.info(
            "Updated status=claude_batch_queued claude_task_id=%s for page_url=%s",
            task_id,
            page_url,
        )

    async def insert(self, doc: EventScrapedContent) -> str:
        log_pretty("Inserting document into MongoDB", doc.to_mongo())
        result = await self._collection.insert_one(doc.to_mongo())
        inserted_id = str(result.inserted_id)
        logger.info("Document saved with id=%s", inserted_id)
        return inserted_id

    async def replace_by_page_url(self, page_url: str, doc: EventScrapedContent) -> str:
        existing = await self._collection.find_one({"page_url": page_url}, {"_id": 1})
        if existing is None:
            raise ValueError(f"No document to replace for page_url={page_url}")
        payload = doc.to_mongo()
        log_pretty("Replacing document in MongoDB", payload)
        await self._collection.replace_one({"_id": existing["_id"]}, payload)
        replaced_id = str(existing["_id"])
        logger.info("Document replaced with id=%s", replaced_id)
        return replaced_id
