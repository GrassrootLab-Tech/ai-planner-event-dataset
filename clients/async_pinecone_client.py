"""Async Pinecone client using AsyncPinecone (no thread-pool offload)."""

from __future__ import annotations

from typing import Any

from pinecone import AsyncPinecone

from clients.pinecone_client import PineconeMatch


class AsyncPineconeClient:
    """Thin async wrapper around AsyncPinecone + AsyncIndex.query."""

    def __init__(self, api_key: str, index_name: str) -> None:
        self._api_key = api_key
        self._index_name = index_name
        self._pc: AsyncPinecone | None = None
        self._index: Any | None = None

    async def __aenter__(self) -> AsyncPineconeClient:
        self._pc = AsyncPinecone(api_key=self._api_key)
        self._index = await self._pc.index(name=self._index_name)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._index is not None:
            await self._index.close()
            self._index = None
        if self._pc is not None:
            await self._pc.close()
            self._pc = None

    async def query(
        self,
        vector: list[float],
        *,
        top_k: int,
        include_metadata: bool = True,
        filter: dict[str, Any] | None = None,
    ) -> list[PineconeMatch]:
        if self._index is None:
            raise RuntimeError("AsyncPineconeClient must be used as an async context manager")

        kwargs: dict[str, Any] = {
            "vector": vector,
            "top_k": top_k,
            "include_metadata": include_metadata,
        }
        if filter is not None:
            kwargs["filter"] = filter

        response = await self._index.query(**kwargs)
        return [
            PineconeMatch(
                id=match.id,
                score=match.score or 0.0,
                metadata=dict(match.metadata or {}),
            )
            for match in response.matches
        ]
