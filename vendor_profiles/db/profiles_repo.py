from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from utils.logger import logger


class VendorsScrapedProfilesRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection
        self._index_ready = False

    async def ensure_indexes(self) -> None:
        if self._index_ready:
            return
        await self._collection.create_index(
            [("page_url", ASCENDING)],
            unique=True,
            name="page_url_unique",
        )
        self._index_ready = True

    async def exists_as_page_or_parent(self, url: str) -> bool:
        doc = await self._collection.find_one(
            {"$or": [{"page_url": url}, {"parent_page_url": url}]},
            {"_id": 1},
        )
        return doc is not None

    async def insert_pending(
        self,
        page_url: str,
        *,
        parent_page_url: str | None = None,
    ) -> bool:
        """Insert pending profile. Returns False if duplicate (silent)."""
        await self.ensure_indexes()
        try:
            await self._collection.insert_one(
                {
                    "page_url": page_url,
                    "status": "pending",
                    "parent_page_url": parent_page_url,
                }
            )
            return True
        except DuplicateKeyError:
            logger.info("Duplicate page_url skipped: %s", page_url)
            return False

    async def set_status(self, page_url: str, status: str) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": {"status": status}},
        )

    async def set_status_many(self, page_urls: list[str], status: str) -> None:
        if not page_urls:
            return
        await self._collection.update_many(
            {"page_url": {"$in": page_urls}},
            {"$set": {"status": status}},
        )
