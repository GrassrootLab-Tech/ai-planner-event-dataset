import asyncio

from clients.anthropic_classifier_client import AnthropicClassifierClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from utils.logger import log_pretty
from utils.pipeline_cost import usd_for_model
from utils.pipeline_status import check_step


class ChunkClassificationService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        classifier: AnthropicClassifierClient,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._classifier = classifier

    async def classify_and_store(
        self,
        page_url: str,
        *,
        skip_status_check: bool = False,
    ) -> tuple[int, dict[str, float]]:
        if not skip_status_check:
            doc = await self._content_repo.get_by_page_url(page_url)
            check_step(
                status=doc.status if doc else None,
                required="chunked",
                step_name="classification",
            )

        chunks = await self._chunks_repo.list_by_page_url(page_url)
        if not chunks:
            raise ValueError(f"No chunks found for page_url={page_url}")

        chunk_inputs = [
            (chunk_doc.chunk, chunk_doc.parent_section_heading)
            for _, chunk_doc in chunks
        ]
        results, usage = await self._classifier.classify_article(chunk_inputs)

        await asyncio.gather(*[
            self._chunks_repo.update_is_usable(chunk_id, is_usable)
            for (chunk_id, _), is_usable in zip(chunks, results)
        ])

        await self._content_repo.update_status(page_url, "usability_classification")

        log_pretty("Classification completed", {
            "page_url": page_url,
            "chunk_count": len(chunks),
        })
        return len(chunks), {
            "claude_usd": usd_for_model(self._classifier.model, usage),
        }
