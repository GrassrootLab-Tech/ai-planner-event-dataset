from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from utils.logger import logger

SCRAPE_ELIGIBLE_STATUSES = ("staged", "failed")


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
        await self._collection.create_index(
            [("status", ASCENDING)],
            name="status_idx",
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

    async def list_scrape_candidates(self, limit: int) -> list[dict]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        cursor = (
            self._collection.find(
                {"status": {"$in": list(SCRAPE_ELIGIBLE_STATUSES)}},
                {"page_url": 1},
            )
            .sort("_id", ASCENDING)
            .limit(limit)
        )
        docs: list[dict] = []
        async for doc in cursor:
            page_url = doc.get("page_url")
            if isinstance(page_url, str) and page_url.strip():
                docs.append({"page_url": page_url})
        return docs

    async def save_scrape(
        self,
        page_url: str,
        *,
        html: str,
        markdown: str,
    ) -> bool:
        now = datetime.now(timezone.utc)
        result = await self._collection.update_one(
            {
                "page_url": page_url,
                "status": {"$in": list(SCRAPE_ELIGIBLE_STATUSES)},
            },
            {
                "$set": {
                    "html": html,
                    "markdown": markdown,
                    "scraped_at": now,
                    "status": "scraped",
                },
                "$unset": {"error": ""},
            },
        )
        return result.modified_count == 1

    async def mark_failed(self, page_url: str, error: str) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": {"status": "failed", "error": error}},
        )
