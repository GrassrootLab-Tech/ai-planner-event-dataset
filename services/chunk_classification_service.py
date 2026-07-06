import asyncio

from clients.openai_classifier_client import OpenAIClassifierClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from utils.logger import log_pretty, logger
from utils.pipeline_status import check_step


class ChunkClassificationService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        classifier: OpenAIClassifierClient,
        *,
        max_concurrency: int = 5,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._classifier = classifier
        self._max_concurrency = max_concurrency

    async def classify_and_store(self, page_url: str) -> int:
        doc = await self._content_repo.get_by_page_url(page_url)
        check_step(
            status=doc.status if doc else None,
            required="chunked",
            step_name="classification",
        )

        chunks = await self._chunks_repo.list_by_page_url(page_url)
        if not chunks:
            raise ValueError(f"No chunks found for page_url={page_url}")

        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def classify_one(chunk_id: str, chunk_doc) -> None:
            async with semaphore:
                is_usable = await self._classifier.classify_chunk(
                    chunk_doc.chunk,
                    parent_section_heading=chunk_doc.parent_section_heading,
                )
                await self._chunks_repo.update_is_usable(chunk_id, is_usable)

        await asyncio.gather(
            *(classify_one(chunk_id, chunk_doc) for chunk_id, chunk_doc in chunks)
        )

        await self._content_repo.update_status(page_url, "usability_classification")

        log_pretty("Classification completed", {
            "page_url": page_url,
            "chunk_count": len(chunks),
        })
        return len(chunks)
