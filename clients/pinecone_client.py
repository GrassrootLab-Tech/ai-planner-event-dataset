from dataclasses import dataclass
from typing import Any

from pinecone import Pinecone

from utils.logger import logger


@dataclass(frozen=True)
class PineconeMatch:
    id: str
    score: float
    metadata: dict[str, Any]


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

    def query(
        self,
        vector: list[float],
        *,
        top_k: int,
        include_metadata: bool = True,
        filter: dict[str, Any] | None = None,
    ) -> list[PineconeMatch]:
        kwargs: dict[str, Any] = {
            "vector": vector,
            "top_k": top_k,
            "include_metadata": include_metadata,
        }
        if filter is not None:
            kwargs["filter"] = filter

        response = self._index.query(**kwargs)
        return [
            PineconeMatch(
                id=match.id,
                score=match.score or 0.0,
                metadata=dict(match.metadata or {}),
            )
            for match in response.matches
        ]

    def fetch(self, ids: list[str], *, batch_size: int = 100) -> dict[str, list[float]]:
        if not ids:
            return {}

        vectors: dict[str, list[float]] = {}
        for start in range(0, len(ids), batch_size):
            batch_ids = ids[start : start + batch_size]
            response = self._index.fetch(ids=batch_ids)
            for vector_id, record in response.vectors.items():
                if record.values is not None:
                    vectors[vector_id] = list(record.values)
        return vectors
