import asyncio

from clients.anthropic_tagging_client import AnthropicTaggingClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from tags.order import order_metadata_tags
from tags.registry import TagRegistry
from utils.logger import log_pretty, logger
from utils.pipeline_cost import usd_for_model
from utils.pipeline_status import check_step


class ChunkTaggingService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        tagger: AnthropicTaggingClient,
        registry: TagRegistry | None = None,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._tagger = tagger
        self._registry = registry or TagRegistry()

    async def tag_and_store(
        self,
        page_url: str,
        *,
        skip_status_check: bool = False,
    ) -> tuple[int, dict[str, float]]:
        if not skip_status_check:
            doc = await self._content_repo.get_by_page_url(page_url)
            check_step(
                status=doc.status if doc else None,
                required="usability_classification",
                step_name="tagging",
            )

        chunks = await self._chunks_repo.list_by_page_url(page_url)
        usable_chunks = [
            (chunk_id, chunk_doc)
            for chunk_id, chunk_doc in chunks
            if chunk_doc.is_usable is not None and chunk_doc.is_usable.value
        ]

        if not usable_chunks:
            logger.warning("No usable chunks to tag for page_url=%s", page_url)
            await self._content_repo.update_status(page_url, "ai_tagged")
            return 0, {"claude_usd": 0.0}

        chunk_inputs = [
            (chunk_doc.chunk, chunk_doc.parent_section_heading)
            for _, chunk_doc in usable_chunks
        ]
        tag_defs = self._registry.all_tags()
        results, usage = await self._tagger.classify_article(tag_defs, chunk_inputs)

        await asyncio.gather(*[
            self._chunks_repo.update_metadata_tags(
                chunk_id,
                order_metadata_tags(tags),
            )
            for (chunk_id, _), tags in zip(usable_chunks, results)
        ])

        await self._content_repo.update_status(page_url, "ai_tagged")

        log_pretty("Tagging completed", {
            "page_url": page_url,
            "usable_chunk_count": len(usable_chunks),
            "tag_count": len(tag_defs),
        })
        return len(usable_chunks), {
            "claude_usd": usd_for_model(self._tagger.model, usage),
        }
