from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, create_model

from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from retrieval import RetrievalResult
from tags.order import SCALAR_LIST_VALUES
from tags.registry import TagRegistry
from tags.spec import TagDefinition
from utils.logger import log_pretty

TOOL_NAME = "submit_query_tags"
MAX_TOKENS = 4096
FILTERABLE_PRIORITIES = frozenset({"Critical", "Important"})
SKIP_TAG_NAMES = frozenset({"licensed_ip_flag"})
SENTINEL_TAG_VALUES = SCALAR_LIST_VALUES


class QueryTagInferenceError(Exception):
    pass


@dataclass
class QueryTagInference:
    must_have: dict[str, list[str] | bool] = field(default_factory=dict)
    good_to_have: dict[str, list[str] | bool] = field(default_factory=dict)


@dataclass
class MetadataFilterRetrievalResult:
    results: list[RetrievalResult]
    inference: QueryTagInference
    filter: dict[str, Any] | None


def filterable_tags(tag_registry: TagRegistry) -> list[TagDefinition]:
    return [
        tag
        for tag in tag_registry.all_tags()
        if tag.priority in FILTERABLE_PRIORITIES and tag.name not in SKIP_TAG_NAMES
    ]


def _build_system_prompt(tags: list[TagDefinition]) -> str:
    lines = [
        "You extract party-planning metadata tags from a user search query.",
        "Use only the allowed tag names and values listed below.",
        "For bool tags use true/false. For other tags return a list of allowed values.",
        "",
        "must_have: only hard constraints clearly stated in the query. Keep this small and precise.",
        "good_to_have: be extensive. Infer many soft preferences that would improve retrieval recall.",
        "Include related themes, aesthetics, activities, decor, food, guest mix, season, effort,",
        "budget signals, and other relevant tags even when only lightly implied.",
        "Prefer a rich good_to_have set over a sparse one. Still use only allowed values — do not invent tags.",
        "Omit a tag only when it has no reasonable connection to the query.",
        "",
        "Allowed tags:",
    ]
    for tag in tags:
        if tag.value_type == "bool":
            values = "true | false"
        elif tag.values:
            preview = ", ".join(tag.values[:20])
            if len(tag.values) > 20:
                preview += ", ..."
            values = preview
        else:
            values = "(free text values)"
        lines.append(f"- {tag.name} [{tag.priority}]: {values}")
    return "\n".join(lines)


def _build_tag_bucket_model(
    tags: list[TagDefinition], model_name: str
) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for tag in tags:
        if tag.value_type == "bool":
            fields[tag.name] = (
                bool | None,
                Field(default=None, description=f"Optional bool for {tag.name}"),
            )
        else:
            fields[tag.name] = (
                list[str] | None,
                Field(default=None, description=f"Optional values for {tag.name}"),
            )
    return create_model(model_name, **fields)


def _build_response_model(tags: list[TagDefinition]) -> type[BaseModel]:
    must_model = _build_tag_bucket_model(tags, "MustHaveTags")
    good_model = _build_tag_bucket_model(tags, "GoodToHaveTags")
    return create_model(
        "QueryTagInferenceResponse",
        must_have=(
            must_model,
            Field(description="Sparse hard constraints clearly stated in the query"),
        ),
        good_to_have=(
            good_model,
            Field(
                description=(
                    "Extensive soft preferences to improve recall; include many related tags"
                )
            ),
        ),
    )


def _normalize_bucket(
    raw: BaseModel,
    tags_by_name: dict[str, TagDefinition],
) -> dict[str, list[str] | bool]:
    cleaned: dict[str, list[str] | bool] = {}
    data = raw.model_dump(exclude_none=True)

    for tag_name, value in data.items():
        tag = tags_by_name.get(tag_name)
        if tag is None:
            continue

        if tag.value_type == "bool":
            if isinstance(value, bool):
                cleaned[tag_name] = value
            continue

        if not isinstance(value, list):
            continue

        allowed = set(tag.values) if tag.values else None
        values: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item:
                continue
            if item in SENTINEL_TAG_VALUES:
                continue
            if allowed is not None and item not in allowed:
                continue
            values.append(item)

        if values:
            cleaned[tag_name] = values

    return cleaned


def _extract_tool_input(response: object) -> dict[str, Any]:
    content = getattr(response, "content", None) or []
    for block in content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == TOOL_NAME
        ):
            tool_input = getattr(block, "input", None)
            if not isinstance(tool_input, dict):
                raise QueryTagInferenceError(
                    "Anthropic tool_use input is not an object"
                )
            return tool_input
    raise QueryTagInferenceError(f"Anthropic returned no {TOOL_NAME} tool_use block")


async def infer_query_tags(
    *,
    api_key: str,
    model: str,
    query: str,
    tag_registry: TagRegistry | None = None,
) -> QueryTagInference:
    registry = tag_registry or TagRegistry()
    tags = filterable_tags(registry)
    if not tags:
        return QueryTagInference()

    tags_by_name = {tag.name: tag for tag in tags}
    response_model = _build_response_model(tags)
    client = AsyncAnthropic(api_key=api_key)

    log_pretty(
        "Inferring query tags",
        {
            "model": model,
            "tag_count": len(tags),
            "query": query,
        },
    )

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=_build_system_prompt(tags),
        messages=[{"role": "user", "content": query}],
        tools=[
            {
                "name": TOOL_NAME,
                "description": (
                    "Submit must_have (sparse hard constraints) and good_to_have "
                    "(extensive soft preferences) metadata tags inferred from the query."
                ),
                "input_schema": response_model.model_json_schema(),
            },
        ],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )

    usage = getattr(response, "usage", None)
    log_pretty(
        "Anthropic query-tag token usage",
        {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    )

    tool_input = _extract_tool_input(response)
    parsed = response_model.model_validate(tool_input)
    inference = QueryTagInference(
        must_have=_normalize_bucket(parsed.must_have, tags_by_name),  # type: ignore[attr-defined]
        good_to_have=_normalize_bucket(parsed.good_to_have, tags_by_name),  # type: ignore[attr-defined]
    )
    log_pretty(
        "Inferred query tags",
        {
            "must_have": inference.must_have,
            "good_to_have": inference.good_to_have,
        },
    )
    return inference


def _clause_for_tag(tag_name: str, value: list[str] | bool) -> dict[str, Any]:
    if isinstance(value, bool):
        return {tag_name: value}
    return {tag_name: {"$in": value}}


def build_pinecone_filter(inference: QueryTagInference) -> dict[str, Any] | None:
    must_clauses = [
        _clause_for_tag(tag_name, value)
        for tag_name, value in inference.must_have.items()
    ]
    good_clauses = [
        _clause_for_tag(tag_name, value)
        for tag_name, value in inference.good_to_have.items()
    ]

    if not must_clauses and not good_clauses:
        return None

    if must_clauses and good_clauses:
        return {"$and": [*must_clauses, {"$or": good_clauses}]}

    if must_clauses:
        if len(must_clauses) == 1:
            return must_clauses[0]
        return {"$and": must_clauses}

    if len(good_clauses) == 1:
        return good_clauses[0]
    return {"$or": good_clauses}


class MetadataFilterRetriever:
    def __init__(
        self,
        embedder: OpenAIEmbeddingClient,
        chunk_index: PineconeClient,
        *,
        anthropic_api_key: str,
        anthropic_model: str,
        tag_registry: TagRegistry | None = None,
    ) -> None:
        self._embedder = embedder
        self._chunk_index = chunk_index
        self._anthropic_api_key = anthropic_api_key
        self._anthropic_model = anthropic_model
        self._tag_registry = tag_registry or TagRegistry()

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> MetadataFilterRetrievalResult:
        inference = await infer_query_tags(
            api_key=self._anthropic_api_key,
            model=self._anthropic_model,
            query=query,
            tag_registry=self._tag_registry,
        )
        pinecone_filter = build_pinecone_filter(inference)
        query_vector = (await self._embedder.embed_texts([query]))[0]
        matches = self._chunk_index.query(
            query_vector,
            top_k=top_k,
            filter=pinecone_filter,
        )

        results = [
            RetrievalResult(
                id=match.id,
                chunk=str(match.metadata.get("chunk", "")),
                page_url=str(match.metadata.get("page_url", "")),
                content_similarity=match.score,
                tag_similarity=0.0,
                combined_score=match.score,
                metadata=match.metadata,
            )
            for match in matches
        ]

        log_pretty(
            "Metadata filter retrieval completed",
            {
                "top_k": top_k,
                "result_count": len(results),
                "filter": pinecone_filter,
            },
        )
        return MetadataFilterRetrievalResult(
            results=results,
            inference=inference,
            filter=pinecone_filter,
        )


def format_filter_debug(
    inference: QueryTagInference, pinecone_filter: dict[str, Any] | None
) -> str:
    return "\n".join(
        [
            f"must_have: {json.dumps(inference.must_have, ensure_ascii=False)}",
            f"good_to_have: {json.dumps(inference.good_to_have, ensure_ascii=False)}",
            f"pinecone_filter: {json.dumps(pinecone_filter, ensure_ascii=False)}",
        ]
    )
