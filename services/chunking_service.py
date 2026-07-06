import hashlib
from pathlib import Path
from urllib.parse import urlparse

from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from models.event_scraped_chunk import EventScrapedChunk
from utils.logger import log_pretty, logger
from utils.markdown_chunker import chunk_markdown
from utils.markdown_cleaner import clean_markdown


class ChunkingService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        output_dir: Path,
        *,
        min_chars: int = 100,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._output_dir = output_dir
        self._min_chars = min_chars

    async def chunk_and_store(self, page_url: str) -> int:
        doc = await self._content_repo.get_by_page_url(page_url)
        if doc is None:
            raise ValueError(f"No scraped content found for page_url={page_url}")

        if doc.status != "scraped":
            logger.info(
                "Skipping chunking for page_url=%s (status=%s)",
                page_url,
                doc.status,
            )
            return 0

        cleaned = clean_markdown(doc.markdown)
        output_path = self._write_cleaned_markdown(page_url, cleaned)

        chunk_results = chunk_markdown(cleaned, min_chars=self._min_chars)
        chunk_docs = [
            EventScrapedChunk(
                page_url=page_url,
                chunk=result.chunk,
                parent_section_heading=result.parent_section_heading,
                scraped_at=doc.scraped_at,
            )
            for result in chunk_results
        ]

        await self._chunks_repo.insert_many(chunk_docs)
        await self._content_repo.update_status(page_url, "chunked")

        log_pretty("Chunking completed", {
            "page_url": page_url,
            "chunk_count": len(chunk_docs),
            "cleaned_markdown_path": str(output_path),
        })
        return len(chunk_docs)

    def _write_cleaned_markdown(self, page_url: str, cleaned: str) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        slug = self._url_slug(page_url)
        output_path = self._output_dir / f"{slug}.md"
        output_path.write_text(cleaned, encoding="utf-8")
        logger.info("Wrote cleaned markdown to %s", output_path)
        return output_path

    @staticmethod
    def _url_slug(page_url: str) -> str:
        parsed = urlparse(page_url)
        path = parsed.path.strip("/").replace("/", "_") or "root"
        host = parsed.netloc.replace(".", "_")
        digest = hashlib.sha256(page_url.encode()).hexdigest()[:8]
        return f"{host}_{path}_{digest}"
