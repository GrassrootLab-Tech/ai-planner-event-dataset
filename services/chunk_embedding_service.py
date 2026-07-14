from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from utils.logger import log_pretty, logger
from utils.pinecone_metadata import build_pinecone_metadata
from utils.pipeline_status import check_step


class ChunkEmbeddingService:
    def __init__(
        self,
        content_repo: EventScrapedContentRepository,
        chunks_repo: EventScrapedChunksRepository,
        embedder: OpenAIEmbeddingClient,
        pinecone: PineconeClient,
    ) -> None:
        self._content_repo = content_repo
        self._chunks_repo = chunks_repo
        self._embedder = embedder
        self._pinecone = pinecone

    async def embed_and_store(self, page_url: str, *, skip_status_check: bool = False) -> int:
        if not skip_status_check:
            doc = await self._content_repo.get_by_page_url(page_url)
            check_step(
                status=doc.status if doc else None,
                required="anonymized",
                step_name="embedding",
            )

        chunks = await self._chunks_repo.list_by_page_url(page_url)
        usable_chunks = [
            (chunk_id, chunk_doc)
            for chunk_id, chunk_doc in chunks
            if chunk_doc.is_usable is not None and chunk_doc.is_usable.value
        ]

        if not usable_chunks:
            logger.warning("No usable chunks to embed for page_url=%s", page_url)
            await self._content_repo.update_status(page_url, "embedded")
            return 0

        texts = [chunk_doc.chunk for _, chunk_doc in usable_chunks]
        embeddings = await self._embedder.embed_texts(texts)

        vectors = [
            {
                "id": chunk_id,
                "values": embedding,
                "metadata": build_pinecone_metadata(
                    chunk_doc,
                    embedding_model=self._embedder.model,
                ),
            }
            for (chunk_id, chunk_doc), embedding in zip(usable_chunks, embeddings)
        ]
        self._pinecone.upsert(vectors)

        await self._content_repo.update_status(page_url, "embedded")

        log_pretty("Embedding completed", {
            "page_url": page_url,
            "embedded_chunk_count": len(usable_chunks),
        })
        return len(usable_chunks)
