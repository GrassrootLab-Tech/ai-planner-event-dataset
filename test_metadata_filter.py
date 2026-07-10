#!/usr/bin/env python3
"""Metadata-filter Pinecone retrieval test (Haiku tags + vector search).

Usage:
    python test_metadata_filter.py
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from config import Settings
from retrieval import RetrievalResult
from retrieval_metadata_filter import (
    MetadataFilterRetriever,
    QueryTagInference,
    format_filter_debug,
)
from utils.logger import log_pretty, logger, setup_logging

QUERY = (
    "I am throwing anniversary party for my spouse , recommend some good theme ideas"
)
TOP_K = 5
OUTPUT_DIR = Path("output")


def timestamped_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"query_results_metadata_filter_{stamp}.txt"


def format_results_text(
    query: str,
    index_name: str,
    results: list[RetrievalResult],
    inference: QueryTagInference,
    pinecone_filter: dict | None,
) -> str:
    lines = [
        f"Query: {query}",
        f"Index: {index_name}",
        f"Approach: metadata_filter",
        f"Results: {len(results)}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        format_filter_debug(inference, pinecone_filter),
        "",
    ]

    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                "=" * 80,
                f"[{index}] score={round(result.content_similarity, 4)}",
                f"id: {result.id}",
                f"page_url: {result.page_url}",
                "",
                result.chunk,
                "",
            ]
        )

    return "\n".join(lines)


async def search(query: str, top_k: int = 5, output_path: Path | None = None) -> Path:
    settings = Settings()
    output_path = output_path or timestamped_output_path()

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")
    if not settings.pinecone_api_key:
        raise ValueError("PINECONE_API_KEY is required")
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required")

    embedder = OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )
    chunk_index = PineconeClient(
        api_key=settings.pinecone_api_key,
        index_name=settings.pinecone_index_name,
    )
    retriever = MetadataFilterRetriever(
        embedder,
        chunk_index,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_model=settings.anthropic_query_tagging_model,
    )

    outcome = await retriever.retrieve(query, top_k=top_k)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        format_results_text(
            query,
            settings.pinecone_index_name,
            outcome.results,
            outcome.inference,
            outcome.filter,
        ),
        encoding="utf-8",
    )

    log_pretty(
        "Metadata filter retrieval results",
        {
            "query": query,
            "index": settings.pinecone_index_name,
            "model": settings.anthropic_query_tagging_model,
            "top_k": top_k,
            "result_count": len(outcome.results),
            "must_have": outcome.inference.must_have,
            "good_to_have": outcome.inference.good_to_have,
            "filter": outcome.filter,
            "output_path": str(output_path),
        },
    )
    logger.info("Wrote results to %s", output_path)
    return output_path


def main() -> None:
    setup_logging()
    asyncio.run(search(QUERY, top_k=TOP_K))


if __name__ == "__main__":
    main()
