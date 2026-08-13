from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from utils.logger import logger


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
        await self._collection.create_index(
            [("source", ASCENDING), ("slug", ASCENDING)],
            unique=True,
            name="source_slug_unique",
        )
        self._index_ready = True

    async def upsert_extracted(
        self,
        *,
        page_url: str,
        source: str,
        profile_fields: dict[str, Any],
    ) -> bool:
        """Upsert extracted profile. Returns False if duplicate (silent)."""
        await self.ensure_indexes()
        now = datetime.now(timezone.utc)
        doc = {
            "page_url": page_url,
            "extracted_at": now,
            "source": source,
            **profile_fields,
        }
        try:
            await self._collection.update_one(
                {"page_url": page_url},
                {"$set": doc},
                upsert=True,
            )
            return True
        except DuplicateKeyError:
            logger.info(
                "Duplicate extracted profile skipped: page_url=%s source=%s slug=%s",
                page_url,
                source,
                profile_fields.get("slug"),
            )
            return False
