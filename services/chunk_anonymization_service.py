from __future__ import annotations

import asyncio
from typing import Protocol

from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage, usd_for_model
from utils.pipeline_status import check_step


class AnonymizerClient(Protocol):
    @property
    def model(self) -> str: ...

    async def anonymize_article(
        self,
        chunks: list[str],
    ) -> tuple[list[str], TokenUsage]: ...


class ChunkAnonymizationService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        anonymizer: AnonymizerClient,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._anonymizer = anonymizer

    async def anonymize_and_store(
        self,
        page_url: str,
        *,
        skip_status_check: bool = False,
    ) -> tuple[int, dict[str, float]]:
        if not skip_status_check:
            doc = await self._content_repo.get_by_page_url(page_url)
            check_step(
                status=doc.status if doc else None,
                required="ai_tagged",
                step_name="anonymization",
            )

        chunks = await self._chunks_repo.list_by_page_url(page_url)
        usable_chunks = [
            (chunk_id, chunk_doc)
            for chunk_id, chunk_doc in chunks
            if chunk_doc.is_usable is not None and chunk_doc.is_usable.value
        ]

        if not usable_chunks:
            logger.warning("No usable chunks to anonymize for page_url=%s", page_url)
            await self._content_repo.update_status(page_url, "anonymized")
            return 0, {"claude_usd": 0.0}

        before_texts = [chunk_doc.chunk for _, chunk_doc in usable_chunks]
        after_texts, usage = await self._anonymizer.anonymize_article(before_texts)

        await asyncio.gather(*[
            self._chunks_repo.update_chunk(chunk_id, after)
            for (chunk_id, _), after in zip(usable_chunks, after_texts)
        ])

        await self._content_repo.update_status(page_url, "anonymized")

        log_pretty("Anonymization completed", {
            "page_url": page_url,
            "usable_chunk_count": len(usable_chunks),
        })
        return len(usable_chunks), {
            "claude_usd": usd_for_model(self._anonymizer.model, usage),
        }
