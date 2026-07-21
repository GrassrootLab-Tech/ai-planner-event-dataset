"""Orchestrate spark ideas: fixed filter → text retrieve → ideas → images."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from clients.gemini_embedding_client import GeminiEmbeddingClient
from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from spark_ideas.constants import SPARK_DISPLAY_COUNT, ThemeFormInput
from spark_ideas.context import build_spark_query, form_summary_for_prompt
from spark_ideas.filter_builder import build_spark_pinecone_filter
from spark_ideas.haiku import SparkIdea, synthesize_spark_ideas
from theme_recommendation.vendors import fetch_vendors_by_ids
from utils.logger import log_pretty

IMAGE_PROBE_TIMEOUT_S = 5.0


@dataclass
class SparkIdeaWithImage:
    idea: str
    image_url: str | None
    image_score: float | None = None
    image_id: str | None = None
    vendor_id: str | None = None
    business_name: str | None = None
    slug: str | None = None


@dataclass
class SparkIdeasResult:
    pinecone_query: str
    pinecone_filter: dict[str, Any]
    chunk_matches: list[dict[str, Any]] = field(default_factory=list)
    stage2_ideas: list[SparkIdea] = field(default_factory=list)
    ideas: list[SparkIdeaWithImage] = field(default_factory=list)


async def recommend_spark_ideas(
    *,
    form: ThemeFormInput,
    embedder: OpenAIEmbeddingClient,
    image_embedder: GeminiEmbeddingClient,
    chunk_index: PineconeClient,
    image_index: PineconeClient,
    anthropic_api_key: str,
    anthropic_model: str,
    top_k: int = 7,
    vendors_collection: Any | None = None,
) -> SparkIdeasResult:
    form_summary = form_summary_for_prompt(form)
    pinecone_query = build_spark_query(form)
    pinecone_filter = build_spark_pinecone_filter(form.event_type)

    query_vectors, _ = await embedder.embed_texts([pinecone_query])
    matches = chunk_index.query(
        query_vectors[0],
        top_k=top_k,
        filter=pinecone_filter,
    )
    chunk_matches = [
        {
            "id": match.id,
            "score": match.score,
            "chunk": str(match.metadata.get("chunk", "")),
            "page_url": str(match.metadata.get("page_url", "")),
            "metadata": match.metadata,
        }
        for match in matches
    ]
    chunk_texts = [str(m["chunk"]) for m in chunk_matches]

    spark_ideas = await synthesize_spark_ideas(
        api_key=anthropic_api_key,
        model=anthropic_model,
        form_summary=form_summary,
        chunk_texts=chunk_texts,
        top_k=SPARK_DISPLAY_COUNT,
    )

    ideas = await _attach_images(image_embedder, image_index, spark_ideas)
    ideas = await _keep_accessible_ideas(ideas, limit=SPARK_DISPLAY_COUNT)
    if vendors_collection is not None:
        ideas = await _attach_vendors(ideas, vendors_collection)

    log_pretty(
        "Spark ideas completed",
        {
            "top_k": top_k,
            "chunk_count": len(chunk_matches),
            "idea_count": len(ideas),
            "filter": pinecone_filter,
            "pinecone_query": pinecone_query,
        },
    )
    return SparkIdeasResult(
        pinecone_query=pinecone_query,
        pinecone_filter=pinecone_filter,
        chunk_matches=chunk_matches,
        stage2_ideas=spark_ideas,
        ideas=ideas,
    )


async def _image_reachable(url: str, client: httpx.AsyncClient) -> bool:
    try:
        response = await client.get(
            url,
            headers={"Range": "bytes=0-0"},
            follow_redirects=True,
            timeout=IMAGE_PROBE_TIMEOUT_S,
        )
        return response.status_code in (200, 206) and len(response.content) >= 1
    except httpx.HTTPError:
        return False


async def _keep_accessible_ideas(
    ideas: list[SparkIdeaWithImage],
    *,
    limit: int,
) -> list[SparkIdeaWithImage]:
    kept: list[SparkIdeaWithImage] = []
    async with httpx.AsyncClient() as client:
        for idea in ideas:
            if not idea.image_url:
                continue
            if await _image_reachable(idea.image_url, client):
                kept.append(idea)
            if len(kept) >= limit:
                break
    return kept


async def _attach_vendors(
    ideas: list[SparkIdeaWithImage],
    vendors_collection: Any,
) -> list[SparkIdeaWithImage]:
    vendor_ids = [i.vendor_id for i in ideas if i.vendor_id]
    vendors = await fetch_vendors_by_ids(vendors_collection, vendor_ids)
    for idea in ideas:
        if not idea.vendor_id:
            continue
        info = vendors.get(idea.vendor_id)
        if not info:
            continue
        idea.business_name = info["business_name"]
        idea.slug = info["slug"]
    return ideas


async def _attach_images(
    image_embedder: GeminiEmbeddingClient,
    image_index: PineconeClient,
    spark_ideas: list[SparkIdea],
) -> list[SparkIdeaWithImage]:
    if not spark_ideas:
        return []

    texts = [item.idea for item in spark_ideas]
    vectors = await image_embedder.embed_texts(texts)

    results: list[SparkIdeaWithImage] = []
    for idea, vector in zip(spark_ideas, vectors):
        matches = image_index.query(vector, top_k=1)
        image_url: str | None = None
        image_score: float | None = None
        image_id: str | None = None
        vendor_id: str | None = None
        if matches:
            match = matches[0]
            image_id = match.id
            image_score = match.score
            raw_url = match.metadata.get("image_url")
            if raw_url:
                image_url = str(raw_url)
            raw_vendor = match.metadata.get("vendor_id")
            if raw_vendor:
                vendor_id = str(raw_vendor)
        results.append(
            SparkIdeaWithImage(
                idea=idea.idea,
                image_url=image_url,
                image_score=image_score,
                image_id=image_id,
                vendor_id=vendor_id,
            )
        )
    return results
