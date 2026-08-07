from __future__ import annotations

import random
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from utils.url import clean_page_url

PROCESSED_STATUS = "processed"


@dataclass(frozen=True)
class SerpResultRef:
    doc_id: ObjectId
    index: int


@dataclass
class StagePage:
    page_url: str
    page_title: str | None = None
    source_url: str = ""
    category_slug: str = ""
    city_slug: str = ""
    refs: list[SerpResultRef] = field(default_factory=list)


def _round_robin_cat_city(pages: list[StagePage]) -> deque[StagePage]:
    """Mix category+city within one source via round-robin."""
    buckets: dict[tuple[str, str], deque[StagePage]] = defaultdict(deque)
    for page in pages:
        buckets[(page.category_slug, page.city_slug)].append(page)

    queues = list(buckets.values())
    ordered: deque[StagePage] = deque()
    while queues:
        next_queues: list[deque[StagePage]] = []
        for queue in queues:
            ordered.append(queue.popleft())
            if queue:
                next_queues.append(queue)
        queues = next_queues
    return ordered


def _select_even_batch(candidates: list[StagePage], batch_size: int) -> list[StagePage]:
    """Even sources + cat/city; avoid consecutive same source when possible."""
    by_source: dict[str, list[StagePage]] = defaultdict(list)
    for page in candidates:
        by_source[page.source_url or ""].append(page)

    source_queues: dict[str, deque[StagePage]] = {
        source: _round_robin_cat_city(pages) for source, pages in by_source.items()
    }
    source_order = sorted(source_queues.keys())
    selected: list[StagePage] = []

    while len(selected) < batch_size and source_order:
        for source in list(source_order):
            if len(selected) >= batch_size:
                break
            queue = source_queues[source]
            selected.append(queue.popleft())
            if not queue:
                source_order.remove(source)
                del source_queues[source]

    return selected


class VendorsSerpResultsRepository:
    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def _collect_unprocessed(
        self, *, query: dict[str, Any] | None = None
    ) -> list[StagePage]:
        filter_query: dict[str, Any] = {
            "status": "ok",
            "results.0": {"$exists": True},
        }
        if query:
            filter_query.update(query)

        cursor = self._collection.find(
            filter_query,
            {
                "results": 1,
                "source_url": 1,
                "category": 1,
                "category_slug": 1,
                "city": 1,
                "city_slug": 1,
            },
        )

        # cleaned_url -> StagePage (first wins for title/source/cat/city; refs accumulate)
        by_url: dict[str, StagePage] = {}

        async for doc in cursor:
            doc_id = doc["_id"]
            source_url = str(doc.get("source_url") or "")
            category_slug = str(
                doc.get("category_slug") or doc.get("category") or ""
            )
            city_slug = str(doc.get("city_slug") or doc.get("city") or "")
            results: list[Any] = doc.get("results") or []

            for index, item in enumerate(results):
                if not isinstance(item, dict):
                    continue
                if item.get("status") == PROCESSED_STATUS:
                    continue
                raw_url = item.get("url")
                if not isinstance(raw_url, str) or not raw_url.strip():
                    continue
                page_url = clean_page_url(raw_url.strip())
                if not page_url:
                    continue

                ref = SerpResultRef(doc_id=doc_id, index=index)
                existing = by_url.get(page_url)
                if existing is not None:
                    existing.refs.append(ref)
                    continue

                title = item.get("title")
                page_title = title.strip() if isinstance(title, str) else None
                if page_title == "":
                    page_title = None

                by_url[page_url] = StagePage(
                    page_url=page_url,
                    page_title=page_title,
                    source_url=source_url,
                    category_slug=category_slug,
                    city_slug=city_slug,
                    refs=[ref],
                )

        return list(by_url.values())

    async def pick_unprocessed_batch(self, batch_size: int) -> list[StagePage]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        candidates = await self._collect_unprocessed()
        return _select_even_batch(candidates, batch_size)

    async def pick_random_unprocessed_by_domain(
        self, domain: str, batch_size: int
    ) -> list[StagePage]:
        """Random sample of unprocessed URLs whose source_url contains domain."""
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        keyword = domain.strip()
        if not keyword:
            raise ValueError("domain must be a non-empty keyword")

        candidates = await self._collect_unprocessed(
            query={
                "source_url": {
                    "$regex": re.escape(keyword),
                    "$options": "i",
                }
            }
        )
        if len(candidates) <= batch_size:
            return candidates
        return random.sample(candidates, batch_size)

    async def mark_results_processed(self, refs: list[SerpResultRef]) -> None:
        for ref in refs:
            await self._collection.update_one(
                {"_id": ref.doc_id},
                {"$set": {f"results.{ref.index}.status": PROCESSED_STATUS}},
            )
