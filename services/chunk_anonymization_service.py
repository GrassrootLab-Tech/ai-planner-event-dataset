import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlparse

from clients.anthropic_anonymization_client import AnthropicAnonymizationClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from utils.logger import log_pretty, logger
from utils.pipeline_cost import usd_for_model
from utils.pipeline_status import check_step

OUTPUT_DIR = Path("output/anonymization")
SECTION_SEP = "==================="


class ChunkAnonymizationService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        anonymizer: AnthropicAnonymizationClient,
        *,
        output_dir: Path = OUTPUT_DIR,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._anonymizer = anonymizer
        self._output_dir = output_dir

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

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"{self._url_slug(page_url)}.txt"
        output_path.write_text(
            self._format_before_after(before_texts, after_texts),
            encoding="utf-8",
        )

        await asyncio.gather(*[
            self._chunks_repo.update_chunk(chunk_id, after)
            for (chunk_id, _), after in zip(usable_chunks, after_texts)
        ])

        await self._content_repo.update_status(page_url, "anonymized")

        log_pretty("Anonymization completed", {
            "page_url": page_url,
            "usable_chunk_count": len(usable_chunks),
            "output_path": str(output_path),
        })
        return len(usable_chunks), {
            "claude_usd": usd_for_model(self._anonymizer.model, usage),
        }

    @staticmethod
    def _format_before_after(before_texts: list[str], after_texts: list[str]) -> str:
        parts: list[str] = []
        for index, (before, after) in enumerate(zip(before_texts, after_texts)):
            parts.extend([
                SECTION_SEP,
                f"chunk_{index}_before",
                SECTION_SEP,
                before,
                SECTION_SEP,
                f"chunk_{index}_after",
                SECTION_SEP,
                after,
            ])
        return "\n".join(parts) + "\n"

    @staticmethod
    def _url_slug(page_url: str) -> str:
        parsed = urlparse(page_url)
        path = parsed.path.strip("/").replace("/", "_") or "root"
        host = parsed.netloc.replace(".", "_")
        digest = hashlib.sha256(page_url.encode()).hexdigest()[:8]
        return f"{host}_{path}_{digest}"
