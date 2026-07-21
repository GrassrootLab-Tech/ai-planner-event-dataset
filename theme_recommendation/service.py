"""Orchestrate theme recommendation: filters → text retrieve → themes → images."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from clients.gemini_embedding_client import GeminiEmbeddingClient
from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from tags.registry import TagRegistry
from theme_recommendation.constants import ThemeFormInput
from theme_recommendation.context import (
    active_tag_definitions,
    form_summary_for_prompt,
)
from theme_recommendation.filter_builder import build_theme_pinecone_filter
from theme_recommendation.haiku import (
    Stage1Result,
    ThemeIdea,
    infer_theme_filters,
    synthesize_themes,
)
from theme_recommendation.vendors import fetch_vendors_by_ids
from utils.logger import log_pretty

THEME_DISPLAY_COUNT = 6
IMAGE_PROBE_TIMEOUT_S = 5.0


@dataclass
class ThemeWithImage:
    title: str
    description: str
    image_url: str | None
    image_score: float | None = None
    image_id: str | None = None
    vendor_id: str | None = None
    business_name: str | None = None
    slug: str | None = None


@dataclass
class ThemeRecommendationResult:
    stage1: Stage1Result
    pinecone_filter: dict[str, Any] | None
    chunk_matches: list[dict[str, Any]] = field(default_factory=list)
    stage2_themes: list[ThemeIdea] = field(default_factory=list)
    themes: list[ThemeWithImage] = field(default_factory=list)


async def recommend_themes(
    *,
    form: ThemeFormInput,
    embedder: OpenAIEmbeddingClient,
    image_embedder: GeminiEmbeddingClient,
    chunk_index: PineconeClient,
    image_index: PineconeClient,
    anthropic_api_key: str,
    anthropic_model: str,
    top_k: int = 5,
    vendors_collection: Any | None = None,
    tag_registry: TagRegistry | None = None,
) -> ThemeRecommendationResult:
    registry = tag_registry or TagRegistry()
    form_summary = form_summary_for_prompt(form)
    tags = active_tag_definitions(form, registry)

    stage1 = await infer_theme_filters(
        api_key=anthropic_api_key,
        model=anthropic_model,
        form_summary=form_summary,
        tags=tags,
    )
    pinecone_filter = build_theme_pinecone_filter(stage1.input_filters)

    query_vectors, _ = await embedder.embed_texts([stage1.pinecone_query])
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

    theme_ideas = await synthesize_themes(
        api_key=anthropic_api_key,
        model=anthropic_model,
        form_summary=form_summary,
        chunk_texts=chunk_texts,
        top_k=THEME_DISPLAY_COUNT,
    )

    themes = await _attach_images(image_embedder, image_index, theme_ideas)
    themes = await _keep_accessible_themes(themes, limit=THEME_DISPLAY_COUNT)
    if vendors_collection is not None:
        themes = await _attach_vendors(themes, vendors_collection)

    log_pretty(
        "Theme recommendation completed",
        {
            "top_k": top_k,
            "chunk_count": len(chunk_matches),
            "theme_count": len(themes),
            "filter": pinecone_filter,
        },
    )
    return ThemeRecommendationResult(
        stage1=stage1,
        pinecone_filter=pinecone_filter,
        chunk_matches=chunk_matches,
        stage2_themes=theme_ideas,
        themes=themes,
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


async def _keep_accessible_themes(
    themes: list[ThemeWithImage],
    *,
    limit: int,
) -> list[ThemeWithImage]:
    kept: list[ThemeWithImage] = []
    async with httpx.AsyncClient() as client:
        for theme in themes:
            if not theme.image_url:
                continue
            if await _image_reachable(theme.image_url, client):
                kept.append(theme)
            if len(kept) >= limit:
                break
    return kept


async def _attach_vendors(
    themes: list[ThemeWithImage],
    vendors_collection: Any,
) -> list[ThemeWithImage]:
    vendor_ids = [t.vendor_id for t in themes if t.vendor_id]
    vendors = await fetch_vendors_by_ids(vendors_collection, vendor_ids)
    for theme in themes:
        if not theme.vendor_id:
            continue
        info = vendors.get(theme.vendor_id)
        if not info:
            continue
        theme.business_name = info["business_name"]
        theme.slug = info["slug"]
    return themes


async def _attach_images(
    image_embedder: GeminiEmbeddingClient,
    image_index: PineconeClient,
    theme_ideas: list[ThemeIdea],
) -> list[ThemeWithImage]:
    if not theme_ideas:
        return []

    texts = [f"{t.title}:{t.description}" for t in theme_ideas]
    vectors = await image_embedder.embed_texts(texts)

    results: list[ThemeWithImage] = []
    for theme, vector in zip(theme_ideas, vectors):
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
            ThemeWithImage(
                title=theme.title,
                description=theme.description,
                image_url=image_url,
                image_score=image_score,
                image_id=image_id,
                vendor_id=vendor_id,
            )
        )
    return results
