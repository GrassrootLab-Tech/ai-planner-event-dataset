"""Orchestrate theme packages: Stage1 filters → facet retrieve → packages → images."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from clients.async_pinecone_client import AsyncPineconeClient
from clients.gemini_embedding_client import GeminiEmbeddingClient
from clients.openai_embedding_client import OpenAIEmbeddingClient
from tags.registry import TagRegistry
from theme_packages.constants import IDEAS_PER_PACKAGE_MAX, ThemeFormInput
from theme_packages.filter_builder import build_all_facet_specs
from theme_packages.haiku import ThemePackage, synthesize_theme_packages
from theme_recommendation.context import (
    active_tag_definitions,
    form_summary_for_prompt,
)
from theme_recommendation.haiku import Stage1Result, infer_theme_filters
from theme_recommendation.vendors import fetch_vendors_by_ids
from utils.logger import log_pretty
from utils.pipeline_cost import TokenUsage

IMAGE_PROBE_TIMEOUT_S = 5.0


@dataclass
class PackageIdeaWithImage:
    idea: str
    image_url: str | None
    image_score: float | None = None
    image_id: str | None = None
    vendor_id: str | None = None
    business_name: str | None = None
    slug: str | None = None


@dataclass
class ThemePackageResult:
    name: str = ""
    ideas: list[PackageIdeaWithImage] = field(default_factory=list)


@dataclass
class ThemePackagesOutcome:
    stage1: Stage1Result
    facet_filters: dict[str, Any] = field(default_factory=dict)
    facet_queries: dict[str, str] = field(default_factory=dict)
    chunk_matches: list[dict[str, Any]] = field(default_factory=list)
    stage2_packages: list[ThemePackage] = field(default_factory=list)
    packages: list[ThemePackageResult] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class Stage1StepResult:
    stage1: Stage1Result
    form_summary: str
    facet_queries: dict[str, str]
    facet_filters: dict[str, Any]
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class FacetRetrieveResult:
    chunk_matches: list[dict[str, Any]]
    chunk_texts: list[str]


@dataclass
class Stage2PackagesResult:
    packages: list[ThemePackage]
    usage: TokenUsage = field(default_factory=TokenUsage)


async def run_stage1_filters(
    *,
    form: ThemeFormInput,
    anthropic_api_key: str,
    anthropic_model: str,
    tag_registry: TagRegistry | None = None,
) -> Stage1StepResult:
    registry = tag_registry or TagRegistry()
    form_summary = form_summary_for_prompt(form)
    tags = active_tag_definitions(form, registry)

    stage1, usage = await infer_theme_filters(
        api_key=anthropic_api_key,
        model=anthropic_model,
        form_summary=form_summary,
        tags=tags,
    )
    facet_specs = build_all_facet_specs(
        input_filters=stage1.input_filters,
    )
    return Stage1StepResult(
        stage1=stage1,
        form_summary=form_summary,
        facet_queries={s["facet_key"]: s["query_text"] for s in facet_specs},
        facet_filters={s["facet_key"]: s["filter"] for s in facet_specs},
        usage=usage,
    )


async def run_facet_retrieve(
    *,
    input_filters: dict[str, list[str] | bool],
    embedder: OpenAIEmbeddingClient,
    pinecone_api_key: str,
    chunk_index_name: str,
) -> FacetRetrieveResult:
    facet_specs = build_all_facet_specs(
        input_filters=input_filters,
    )
    query_texts = [s["query_text"] for s in facet_specs]
    query_vectors, _ = await embedder.embed_texts(query_texts)

    async with AsyncPineconeClient(
        api_key=pinecone_api_key,
        index_name=chunk_index_name,
    ) as chunk_index:
        match_lists = await asyncio.gather(
            *[
                chunk_index.query(
                    vector,
                    top_k=int(spec["top_k"]),
                    filter=spec["filter"],
                )
                for vector, spec in zip(query_vectors, facet_specs)
            ]
        )

    chunk_matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for spec, matches in zip(facet_specs, match_lists):
        for match in matches:
            if match.id in seen_ids:
                continue
            seen_ids.add(match.id)
            chunk_matches.append(
                {
                    "id": match.id,
                    "score": match.score,
                    "facet": spec["facet_key"],
                    "chunk": str(match.metadata.get("chunk", "")),
                    "page_url": str(match.metadata.get("page_url", "")),
                    "metadata": match.metadata,
                }
            )

    chunk_texts = [str(m["chunk"]) for m in chunk_matches if m.get("chunk")]
    log_pretty(
        "Theme packages facet retrieve",
        {"facet_count": len(facet_specs), "chunk_count": len(chunk_matches)},
    )
    return FacetRetrieveResult(chunk_matches=chunk_matches, chunk_texts=chunk_texts)


async def run_stage2_packages(
    *,
    form_summary: str,
    chunk_texts: list[str],
    anthropic_api_key: str,
    anthropic_model: str,
) -> Stage2PackagesResult:
    packages, usage = await synthesize_theme_packages(
        api_key=anthropic_api_key,
        model=anthropic_model,
        form_summary=form_summary,
        chunk_texts=chunk_texts,
    )
    return Stage2PackagesResult(packages=packages, usage=usage)


async def run_attach_package_images(
    *,
    stage2_packages: list[ThemePackage],
    image_embedder: GeminiEmbeddingClient,
    pinecone_api_key: str,
    image_index_name: str,
    vendors_collection: Any | None = None,
) -> list[ThemePackageResult]:
    async with AsyncPineconeClient(
        api_key=pinecone_api_key,
        index_name=image_index_name,
    ) as image_index:
        packages = await _attach_images_to_packages(
            image_embedder,
            image_index,
            stage2_packages,
        )
    packages = await _keep_accessible_packages(packages)
    if vendors_collection is not None:
        packages = await _attach_vendors(packages, vendors_collection)
    log_pretty(
        "Theme packages images attached",
        {
            "package_count": len(packages),
            "idea_counts": [len(p.ideas) for p in packages],
        },
    )
    return packages


async def recommend_theme_packages(
    *,
    form: ThemeFormInput,
    embedder: OpenAIEmbeddingClient,
    image_embedder: GeminiEmbeddingClient,
    pinecone_api_key: str,
    chunk_index_name: str,
    image_index_name: str,
    anthropic_api_key: str,
    anthropic_model: str,
    vendors_collection: Any | None = None,
    tag_registry: TagRegistry | None = None,
) -> ThemePackagesOutcome:
    """Full pipeline (no progressive UI). Prefer step helpers from Streamlit."""
    stage1_step = await run_stage1_filters(
        form=form,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=anthropic_model,
        tag_registry=tag_registry,
    )
    facet_step = await run_facet_retrieve(
        input_filters=stage1_step.stage1.input_filters,
        embedder=embedder,
        pinecone_api_key=pinecone_api_key,
        chunk_index_name=chunk_index_name,
    )
    stage2_step = await run_stage2_packages(
        form_summary=stage1_step.form_summary,
        chunk_texts=facet_step.chunk_texts,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=anthropic_model,
    )
    packages = await run_attach_package_images(
        stage2_packages=stage2_step.packages,
        image_embedder=image_embedder,
        pinecone_api_key=pinecone_api_key,
        image_index_name=image_index_name,
        vendors_collection=vendors_collection,
    )
    return ThemePackagesOutcome(
        stage1=stage1_step.stage1,
        facet_filters=stage1_step.facet_filters,
        facet_queries=stage1_step.facet_queries,
        chunk_matches=facet_step.chunk_matches,
        stage2_packages=stage2_step.packages,
        packages=packages,
        usage=stage1_step.usage + stage2_step.usage,
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


async def _keep_accessible_packages(
    packages: list[ThemePackageResult],
) -> list[ThemePackageResult]:
    async with httpx.AsyncClient() as client:
        result: list[ThemePackageResult] = []
        for package in packages:
            kept: list[PackageIdeaWithImage] = []
            for idea in package.ideas:
                if not idea.image_url:
                    continue
                if await _image_reachable(idea.image_url, client):
                    kept.append(idea)
                if len(kept) >= IDEAS_PER_PACKAGE_MAX:
                    break
            result.append(ThemePackageResult(name=package.name, ideas=kept))
        return result


async def _attach_vendors(
    packages: list[ThemePackageResult],
    vendors_collection: Any,
) -> list[ThemePackageResult]:
    vendor_ids = [
        idea.vendor_id
        for package in packages
        for idea in package.ideas
        if idea.vendor_id
    ]
    vendors = await fetch_vendors_by_ids(vendors_collection, vendor_ids)
    for package in packages:
        for idea in package.ideas:
            if not idea.vendor_id:
                continue
            info = vendors.get(idea.vendor_id)
            if not info:
                continue
            idea.business_name = info["business_name"]
            idea.slug = info["slug"]
    return packages


async def _query_image(
    image_index: AsyncPineconeClient,
    vector: list[float],
) -> tuple[str | None, float | None, str | None, str | None]:
    matches = await image_index.query(vector, top_k=1)
    if not matches:
        return None, None, None, None
    match = matches[0]
    image_url: str | None = None
    vendor_id: str | None = None
    raw_url = match.metadata.get("image_url")
    if raw_url:
        image_url = str(raw_url)
    raw_vendor = match.metadata.get("vendor_id")
    if raw_vendor:
        vendor_id = str(raw_vendor)
    return image_url, match.score, match.id, vendor_id


async def _attach_images_to_packages(
    image_embedder: GeminiEmbeddingClient,
    image_index: AsyncPineconeClient,
    packages: list[ThemePackage],
) -> list[ThemePackageResult]:
    if not packages:
        return []

    flat_ideas = [idea for pkg in packages for idea in pkg.ideas]
    if not flat_ideas:
        return [ThemePackageResult(name=pkg.name) for pkg in packages]

    vectors = await image_embedder.embed_texts(flat_ideas)
    image_results = await asyncio.gather(
        *[_query_image(image_index, vector) for vector in vectors]
    )

    results: list[ThemePackageResult] = []
    offset = 0
    for pkg in packages:
        ideas_with_images: list[PackageIdeaWithImage] = []
        for idea in pkg.ideas:
            image_url, image_score, image_id, vendor_id = image_results[offset]
            offset += 1
            ideas_with_images.append(
                PackageIdeaWithImage(
                    idea=idea,
                    image_url=image_url,
                    image_score=image_score,
                    image_id=image_id,
                    vendor_id=vendor_id,
                )
            )
        results.append(
            ThemePackageResult(name=pkg.name, ideas=ideas_with_images)
        )
    return results
