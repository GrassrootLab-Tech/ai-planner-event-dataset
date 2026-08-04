from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING


class VendorsExtractedProfilesRepository:
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

    async def upsert_extracted(
        self,
        *,
        page_url: str,
        source: str,
        profile_fields: dict[str, Any],
    ) -> None:
        await self.ensure_indexes()
        now = datetime.now(timezone.utc)
        doc = {
            "page_url": page_url,
            "extracted_at": now,
            "source": source,
            **profile_fields,
        }
        await self._collection.update_one(
            {"page_url": page_url},
            {"$set": doc},
            upsert=True,
        )
