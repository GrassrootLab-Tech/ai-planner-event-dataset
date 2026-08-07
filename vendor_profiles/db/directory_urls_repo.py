from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING


class VendorsScrapedDirectoryUrlsRepository:
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

    async def exists_by_page_url(self, page_url: str) -> bool:
        doc = await self._collection.find_one(
            {"page_url": page_url},
            {"_id": 1},
        )
        return doc is not None

    async def upsert_scrape(
        self,
        *,
        page_url: str,
        markdown: str,
        all_links: list[str],
        status: str = "ok",
        error: str | None = None,
        html: str | None = None,
    ) -> None:
        await self.ensure_indexes()
        now = datetime.now(timezone.utc)
        fields: dict = {
            "page_url": page_url,
            "scraped_at": now,
            "all_links": all_links,
            "vendor_profile_urls": [],
            "markdown": markdown,
            "status": status,
        }
        if html is not None:
            fields["html"] = html
        update: dict
        if status == "failed":
            fields["error"] = error or "scrape failed"
            update = {"$set": fields}
        else:
            update = {"$set": fields, "$unset": {"error": ""}}
        await self._collection.update_one(
            {"page_url": page_url},
            update,
            upsert=True,
        )

    async def set_vendor_profile_urls(
        self, page_url: str, vendor_profile_urls: list[str]
    ) -> None:
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": {"vendor_profile_urls": vendor_profile_urls}},
        )
