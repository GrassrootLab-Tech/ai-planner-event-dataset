import asyncio

from clients.openai_tagging_client import OpenAITaggingClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from tags.groups import TAG_GROUPS
from tags.order import order_metadata_tags
from tags.registry import TagRegistry
from tags.schema import TagValue
from utils.logger import log_pretty, logger
from utils.pipeline_status import check_step


class ChunkTaggingService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        tagger: OpenAITaggingClient,
        registry: TagRegistry | None = None,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._tagger = tagger
        self._registry = registry or TagRegistry()

    async def tag_and_store(self, page_url: str) -> int:
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
            return 0

        chunk_inputs = [
            (chunk_doc.chunk, chunk_doc.parent_section_heading)
            for _, chunk_doc in usable_chunks
        ]

        merged_tags: list[dict[str, TagValue]] = [
            {} for _ in usable_chunks
        ]

        async def tag_group(
            group_id: str,
            tag_names: list[str],
        ) -> list[dict[str, TagValue]]:
            tag_defs = self._registry.get_many(tag_names)
            return await self._tagger.classify_group(group_id, tag_defs, chunk_inputs)

        group_results = await asyncio.gather(*[
            tag_group(group_id, tag_names)
            for group_id, tag_names in TAG_GROUPS.items()
        ])

        for group_tags_per_chunk in group_results:
            for index, group_tags in enumerate(group_tags_per_chunk):
                merged_tags[index] = {**merged_tags[index], **group_tags}

        await asyncio.gather(*[
            self._chunks_repo.update_metadata_tags(
                chunk_id,
                order_metadata_tags(tags),
            )
            for (chunk_id, _), tags in zip(usable_chunks, merged_tags)
        ])

        await self._content_repo.update_status(page_url, "ai_tagged")

        log_pretty("Tagging completed", {
            "page_url": page_url,
            "usable_chunk_count": len(usable_chunks),
            "group_count": len(TAG_GROUPS),
        })
        return len(usable_chunks)
