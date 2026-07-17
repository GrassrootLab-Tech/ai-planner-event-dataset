import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from clients.anthropic_tagging_client import AnthropicTaggingClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from tags.order import order_metadata_tags
from tags.registry import TagRegistry
from tags.schema import TagValue
from utils.claude_batch_ids import append_claude_batch_id
from utils.logger import log_pretty, logger
from utils.pipeline_status import check_step


@dataclass
class TagBatchCollector:
    page_urls: list[str] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)

    def add(self, page_url: str, request: dict) -> None:
        self.page_urls.append(page_url)
        self.requests.append(request)

    def __bool__(self) -> bool:
        return bool(self.requests)


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

    async def prepare_tag_request(
        self,
        page_url: str,
        *,
        skip_status_check: bool = False,
    ) -> tuple[str, dict, int] | None:
        """Build one batch request for the page.

        Returns (page_url, request, usable_count), or None if there were no
        usable chunks (status already set to ai_tagged).
        """
        doc = await self._content_repo.get_by_page_url(page_url)
        if not skip_status_check:
            check_step(
                status=doc.status if doc else None,
                required="usability_classification",
                step_name="tagging",
            )

        content_id = await self._content_repo.get_id_by_page_url(page_url)
        if content_id is None:
            raise ValueError(f"No content document for page_url={page_url}")

        chunks = await self._chunks_repo.list_by_page_url(page_url)
        usable_chunks = [
            (chunk_id, chunk_doc)
            for chunk_id, chunk_doc in chunks
            if chunk_doc.is_usable is not None and chunk_doc.is_usable.value
        ]

        if not usable_chunks:
            logger.warning("No usable chunks to tag for page_url=%s", page_url)
            await self._content_repo.update_status(page_url, "ai_tagged")
            return None

        chunk_inputs = [
            (chunk_doc.chunk, chunk_doc.parent_section_heading)
            for _, chunk_doc in usable_chunks
        ]
        tag_defs = self._registry.all_tags()
        request = self._tagger.build_batch_request(
            content_id,
            tag_defs,
            chunk_inputs,
            page_url=page_url,
            page_title=doc.page_title if doc else None,
        )
        return page_url, request, len(usable_chunks)

    async def submit_collected_batch(self, collector: TagBatchCollector) -> str:
        if not collector.requests:
            raise ValueError("No tagging requests to submit")

        batch_id = await self._tagger.submit_batch(collector.requests)
        for page_url in collector.page_urls:
            await self._content_repo.set_claude_batch_queued(page_url, batch_id)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        path = append_claude_batch_id(
            timestamp=timestamp,
            batch_id=batch_id,
            no_of_messages=len(collector.requests),
        )
        log_pretty("Tagging batch submitted", {
            "claude_task_id": batch_id,
            "no_of_messages": len(collector.requests),
            "batch_ids_path": str(path),
        })
        return batch_id

    async def tag_and_store(
        self,
        page_url: str,
        *,
        skip_status_check: bool = False,
    ) -> tuple[int, dict[str, float]]:
        prepared = await self.prepare_tag_request(
            page_url,
            skip_status_check=skip_status_check,
        )
        if prepared is None:
            return 0, {"claude_usd": 0.0}

        page_url, request, usable_count = prepared
        collector = TagBatchCollector()
        collector.add(page_url, request)
        await self.submit_collected_batch(collector)
        return usable_count, {"claude_usd": 0.0}

    async def apply_tag_results(
        self,
        page_url: str,
        results: list[dict[str, TagValue]],
    ) -> int:
        chunks = await self._chunks_repo.list_by_page_url(page_url)
        usable_chunks = [
            (chunk_id, chunk_doc)
            for chunk_id, chunk_doc in chunks
            if chunk_doc.is_usable is not None and chunk_doc.is_usable.value
        ]
        if len(results) != len(usable_chunks):
            raise ValueError(
                f"Tag result count mismatch for page_url={page_url}: "
                f"expected {len(usable_chunks)}, got {len(results)}"
            )

        await asyncio.gather(*[
            self._chunks_repo.update_metadata_tags(
                chunk_id,
                order_metadata_tags(tags),
            )
            for (chunk_id, _), tags in zip(usable_chunks, results)
        ])
        await self._content_repo.update_status(page_url, "ai_tagged")

        log_pretty("Tagging results applied", {
            "page_url": page_url,
            "usable_chunk_count": len(usable_chunks),
        })
        return len(usable_chunks)

    @property
    def registry(self) -> TagRegistry:
        return self._registry
