from typing import Any

from pinecone import Pinecone

from utils.logger import logger


class PineconeClient:
    def __init__(self, api_key: str, index_name: str) -> None:
        self._index = Pinecone(api_key=api_key).Index(index_name)

    def upsert(self, vectors: list[dict[str, Any]], *, batch_size: int = 100) -> int:
        if not vectors:
            return 0

        response = self._index.upsert(vectors=vectors, batch_size=batch_size)
        upserted_count = response.upserted_count or len(vectors)
        logger.info("Upserted %d vectors to Pinecone", upserted_count)
        return upserted_count
