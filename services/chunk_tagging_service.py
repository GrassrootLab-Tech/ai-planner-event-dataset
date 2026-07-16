import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from clients.anthropic_tagging_client import AnthropicTaggingClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from tags.order import order_metadata_tags
from tags.registry import TagRegistry
from utils.logger import log_pretty, logger
from utils.pipeline_cost import usd_for_model
from utils.pipeline_status import check_step

OUTPUT_DIR = Path("output/ai_tagging")


class ChunkTaggingService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        tagger: AnthropicTaggingClient,
        registry: TagRegistry | None = None,
        *,
        output_dir: Path = OUTPUT_DIR,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._tagger = tagger
        self._registry = registry or TagRegistry()
        self._output_dir = output_dir

    async def tag_and_store(
        self,
        page_url: str,
        *,
        skip_status_check: bool = False,
    ) -> tuple[int, dict[str, float]]:
        doc = await self._content_repo.get_by_page_url(page_url)
        if not skip_status_check:
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
        results, usage, raw_output = await self._tagger.classify_article(
            tag_defs,
            chunk_inputs,
            page_url=page_url,
            page_title=doc.page_title if doc else None,
        )

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"{self._url_slug(page_url)}.txt"
        output_path.write_text(
            json.dumps(raw_output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

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
            "claude_output_path": str(output_path),
        })
        return len(usable_chunks), {
            "claude_usd": usd_for_model(self._tagger.model, usage),
        }

    @staticmethod
    def _url_slug(page_url: str) -> str:
        parsed = urlparse(page_url)
        path = parsed.path.strip("/").replace("/", "_") or "root"
        host = parsed.netloc.replace(".", "_")
        digest = hashlib.sha256(page_url.encode()).hexdigest()[:8]
        return f"{host}_{path}_{digest}"
