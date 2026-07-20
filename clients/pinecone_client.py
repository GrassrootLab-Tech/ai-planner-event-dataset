from dataclasses import dataclass
from typing import Any

from pinecone import Pinecone

from utils.logger import logger


@dataclass(frozen=True)
class PineconeMatch:
    id: str
    score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PineconeRecord:
    id: str
    values: list[float] | None
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

    def list_ids(self, *, limit: int = 100) -> list[str]:
        """Return every vector id in the default namespace."""
        ids: list[str] = []
        for page in self._index.list(limit=limit):
            # SDK may yield a list[str] page or a ListResponse with .vectors
            if isinstance(page, list):
                ids.extend(str(item) for item in page)
                continue
            vectors = getattr(page, "vectors", None)
            if vectors is None:
                continue
            for item in vectors:
                item_id = item if isinstance(item, str) else getattr(item, "id", None)
                if item_id is not None:
                    ids.append(str(item_id))
        return ids

    def fetch_records(
        self,
        ids: list[str],
        *,
        batch_size: int = 100,
    ) -> dict[str, PineconeRecord]:
        if not ids:
            return {}

        records: dict[str, PineconeRecord] = {}
        for start in range(0, len(ids), batch_size):
            batch_ids = ids[start : start + batch_size]
            response = self._index.fetch(ids=batch_ids)
            for vector_id, record in response.vectors.items():
                records[vector_id] = PineconeRecord(
                    id=vector_id,
                    values=list(record.values) if record.values is not None else None,
                    metadata=dict(record.metadata or {}),
                )
        return records

    def fetch(self, ids: list[str], *, batch_size: int = 100) -> dict[str, list[float]]:
        records = self.fetch_records(ids, batch_size=batch_size)
        return {
            vector_id: record.values
            for vector_id, record in records.items()
            if record.values is not None
        }

    def delete(self, ids: list[str], *, batch_size: int = 1000) -> int:
        if not ids:
            return 0

        deleted = 0
        for start in range(0, len(ids), batch_size):
            batch_ids = ids[start : start + batch_size]
            self._index.delete(ids=batch_ids)
            deleted += len(batch_ids)
        logger.info("Deleted %d vectors from Pinecone", deleted)
        return deleted
