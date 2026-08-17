from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from utils.logger import logger
from vendor_profiles.sources import DISABLED_STAGE_SCRAPE_HOSTS

SCRAPE_ELIGIBLE_STATUSES = ("staged", "failed")
EXTRACT_ELIGIBLE_STATUS = "scraped"
EXTRACTED_STATUS = "extracted"
EXTRACTION_FAILED_STATUS = "extraction_failed"
EXTRACTION_SKIPPED_STATUS = "extraction_skipped"


def _scrape_host_exclusion_query() -> dict | None:
    if not DISABLED_STAGE_SCRAPE_HOSTS:
        return None
    # page_url contains host (e.g. thumbtack.com); keep FIFO for other sources.
    alt = "|".join(
        sorted(
            (h.replace(".", r"\.") for h in DISABLED_STAGE_SCRAPE_HOSTS),
            key=len,
            reverse=True,
        )
    )
    return {"page_url": {"$not": {"$regex": alt, "$options": "i"}}}


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
            [("status", ASCENDING), ("_id", ASCENDING)],
            name="status_id_idx",
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
        query: dict = {"status": {"$in": list(SCRAPE_ELIGIBLE_STATUSES)}}
        exclusion = _scrape_host_exclusion_query()
        if exclusion:
            query.update(exclusion)
        cursor = (
            self._collection.find(
                query,
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

    async def list_staged_page(self, *, skip: int, limit: int) -> list[dict]:
        """Page of staged profiles (no sort)."""
        if skip < 0:
            raise ValueError("skip must be >= 0")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        cursor = (
            self._collection.find(
                {"status": "staged"},
                {"page_url": 1},
            )
            .skip(skip)
            .limit(limit)
        )
        docs: list[dict] = []
        async for doc in cursor:
            page_url = doc.get("page_url")
            if isinstance(page_url, str) and page_url.strip():
                docs.append({"page_url": page_url})
        return docs

    async def delete_by_page_urls(self, page_urls: list[str]) -> int:
        if not page_urls:
            return 0
        result = await self._collection.delete_many(
            {"page_url": {"$in": page_urls}}
        )
        return int(result.deleted_count)

    async def list_extract_candidates(self, limit: int) -> list[dict]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        cursor = self._collection.find(
            {"status": EXTRACT_ELIGIBLE_STATUS},
            {"page_url": 1},
        ).limit(limit)
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
        status: str = "scraped",
        error: str | None = None,
    ) -> bool:
        """Persist scrape payload. status is usually scraped, or failed (e.g. access denied)."""
        if status not in ("scraped", "failed"):
            raise ValueError("status must be 'scraped' or 'failed'")
        now = datetime.now(timezone.utc)
        fields: dict = {
            "html": html,
            "markdown": markdown,
            "scraped_at": now,
            "status": status,
        }
        update: dict
        if status == "failed":
            fields["error"] = error or "scrape failed"
            update = {"$set": fields}
        else:
            update = {"$set": fields, "$unset": {"error": ""}}
        result = await self._collection.update_one(
            {
                "page_url": page_url,
                "status": {"$in": list(SCRAPE_ELIGIBLE_STATUSES)},
            },
            update,
        )
        return result.modified_count == 1

    async def mark_failed(self, page_url: str, error: str) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": {"status": "failed", "error": error}},
        )

    async def mark_extraction_failed(self, page_url: str, error: str) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": {"status": EXTRACTION_FAILED_STATUS, "error": error}},
        )

    async def mark_extraction_skipped(self, page_url: str, reason: str) -> bool:
        """Transition scraped → extraction_skipped. Returns False if not currently scraped."""
        result = await self._collection.update_one(
            {"page_url": page_url, "status": EXTRACT_ELIGIBLE_STATUS},
            {
                "$set": {
                    "status": EXTRACTION_SKIPPED_STATUS,
                    "error": reason,
                }
            },
        )
        return result.modified_count == 1

    async def find_scraped_by_page_url(self, page_url: str) -> dict | None:
        return await self._collection.find_one(
            {"page_url": page_url},
            {"page_url": 1, "markdown": 1, "html": 1, "status": 1},
        )

    async def mark_extracted(self, page_url: str) -> bool:
        """Transition scraped → extracted. Returns False if not currently scraped."""
        result = await self._collection.update_one(
            {"page_url": page_url, "status": EXTRACT_ELIGIBLE_STATUS},
            {"$set": {"status": EXTRACTED_STATUS}},
        )
        return result.modified_count == 1
