#!/usr/bin/env python3
"""Hybrid Pinecone retrieval test (content + tag similarity).

Usage:
    python test.py
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from config import Settings
from retrieval import RetrievalResult, Retriever
from utils.logger import log_pretty, logger, setup_logging

QUERY = "I'm planning my daughter's birthday party and already have the venue, cake, and decorations sorted. Looking for some unique or fun ideas to make the day feel extra special and memorable — something beyond the usual games and activities."
TOP_K = 5
CANDIDATE_POOL = 100
OUTPUT_DIR = Path("output")


def timestamped_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"query_results_{stamp}.txt"


def format_results_text(
    query: str, index_name: str, results: list[RetrievalResult]
) -> str:
    lines = [
        f"Query: {query}",
        f"Index: {index_name}",
        f"Results: {len(results)}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]

    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                "=" * 80,
                f"[{index}] combined={round(result.combined_score, 4)} "
                f"content={round(result.content_similarity, 4)} "
                f"tag={round(result.tag_similarity, 4)}",
                f"id: {result.id}",
                f"page_url: {result.page_url}",
                "",
                result.chunk,
                "",
            ]
        )

    return "\n".join(lines)


async def search(
    query: str,
    top_k: int = 10,
    candidate_pool: int = 100,
    output_path: Path | None = None,
) -> Path:
    settings = Settings()
    output_path = output_path or timestamped_output_path()

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")
    if not settings.pinecone_api_key:
        raise ValueError("PINECONE_API_KEY is required")

    embedder = OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )
    chunk_index = PineconeClient(
        api_key=settings.pinecone_api_key,
        index_name=settings.pinecone_index_name,
    )
    tags_index = PineconeClient(
        api_key=settings.pinecone_api_key,
        index_name=settings.pinecone_tags_index_name,
    )
    retriever = Retriever(embedder, chunk_index, tags_index)

    results = await retriever.retrieve(
        query,
        candidate_pool=candidate_pool,
        top_k=top_k,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        format_results_text(query, settings.pinecone_index_name, results),
        encoding="utf-8",
    )

    log_pretty(
        "Hybrid retrieval results",
        {
            "query": query,
            "index": settings.pinecone_index_name,
            "tags_index": settings.pinecone_tags_index_name,
            "candidate_pool": candidate_pool,
            "top_k": top_k,
            "result_count": len(results),
            "output_path": str(output_path),
        },
    )
    logger.info("Wrote full chunks to %s", output_path)
    return output_path


def main() -> None:
    setup_logging()
    asyncio.run(
        search(
            QUERY,
            top_k=TOP_K,
            candidate_pool=CANDIDATE_POOL,
        )
    )


if __name__ == "__main__":
    main()
