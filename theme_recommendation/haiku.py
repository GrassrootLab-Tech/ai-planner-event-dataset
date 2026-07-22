"""Haiku stage1 (enums + query) and stage2 (theme titles/descriptions)."""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, create_model

from tags.order import SCALAR_LIST_VALUES
from tags.spec import TagDefinition
from utils.logger import log_pretty
from utils.pipeline_cost import TokenUsage

STAGE1_TOOL = "submit_theme_filters"
STAGE2_TOOL = "submit_themes"
MAX_TOKENS = 4096
SENTINEL_TAG_VALUES = SCALAR_LIST_VALUES


class ThemeRecommendationError(Exception):
    pass


class ThemeIdea(BaseModel):
    title: str = Field(description="2-3 word theme title")
    description: str = Field(description="10-15 word short description")


class Stage1Result(BaseModel):
    input_filters: dict[str, list[str] | bool]
    pinecone_query: str


def _extract_tool_input(response: object, tool_name: str) -> dict[str, Any]:
    content = getattr(response, "content", None) or []
    for block in content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == tool_name
        ):
            tool_input = getattr(block, "input", None)
            if not isinstance(tool_input, dict):
                raise ThemeRecommendationError(
                    f"Anthropic tool_use input is not an object for {tool_name}"
                )
            return tool_input
    raise ThemeRecommendationError(f"Anthropic returned no {tool_name} tool_use block")


def _coerce_to_str_list(value: Any) -> list[str] | None:
    """Accept a bare string or list from the model; return a list of strings."""
    if isinstance(value, str):
        return [value] if value else None
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return None


def _normalize_filters(
    raw: dict[str, Any],
    tags_by_name: dict[str, TagDefinition],
) -> dict[str, list[str] | bool]:
    cleaned: dict[str, list[str] | bool] = {}
    for tag_name, value in raw.items():
        tag = tags_by_name.get(tag_name)
        if tag is None:
            continue
        if tag.value_type == "bool":
            if isinstance(value, bool):
                # kid_safe_flag: only keep true (child-focused events); never filter on false
                if tag_name == "kid_safe_flag" and value is False:
                    continue
                cleaned[tag_name] = value
            continue
        items = _coerce_to_str_list(value)
        if not items:
            continue
        allowed = set(tag.values) if tag.values else None
        values: list[str] = []
        for item in items:
            if item in SENTINEL_TAG_VALUES:
                continue
            if allowed is not None and item not in allowed:
                continue
            values.append(item)
        if values:
            cleaned[tag_name] = values
    return cleaned


def _build_stage1_filters_model(tags: list[TagDefinition]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for tag in tags:
        if tag.name == "kid_safe_flag":
            fields[tag.name] = (
                bool | None,
                Field(
                    default=None,
                    description=(
                        "true only for child-focused events; omit otherwise "
                        "(do not set false)"
                    ),
                ),
            )
        elif tag.value_type == "bool":
            fields[tag.name] = (
                bool | None,
                Field(default=None, description=f"Optional bool for {tag.name}"),
            )
        else:
            fields[tag.name] = (
                str | list[str] | None,
                Field(
                    default=None,
                    description=(f"One enum or a list of allowed enums for {tag.name}"),
                ),
            )
    return create_model("ThemeInputFilters", **fields)


def _build_stage1_response_model(tags: list[TagDefinition]) -> type[BaseModel]:
    filters_model = _build_stage1_filters_model(tags)
    return create_model(
        "ThemeStage1Response",
        input_filters=(
            filters_model,
            Field(description="Chosen enum values for active input filter tags"),
        ),
        pinecone_query=(
            str,
            Field(
                description=(
                    "Beautiful pinecone search query, max 15 words, "
                    "e.g. theme ideas for this wedding for my friend"
                )
            ),
        ),
    )


def _stage1_system_prompt(tags: list[TagDefinition]) -> str:
    lines = [
        "You map party-planning form answers to metadata filter enums and a short search query.",
        "Use only the allowed tag names and values listed below.",
        "For bool tags use true/false. For other tags return a list of allowed values.",
        "Choose one or multiple enums per tag as needed. Omit a tag if you cannot map confidently.",
        "honoree_gender_skew must be inferred from the form answers when possible.",
        "kid_safe_flag: set true ONLY if the event is clearly for a child "
        "(e.g. kids birthday, baby shower guest kids, family with young children). "
        "Otherwise omit kid_safe_flag entirely — never set it to false.",
        "pinecone_query: max 15 words recommending theme ideas for the event/celebratee.",
        "Allowed tags:",
    ]
    for tag in tags:
        if tag.value_type == "bool":
            values = "true | false"
        elif tag.values:
            values = ", ".join(tag.values)
        else:
            values = "(free text values)"
        lines.append(f"- {tag.name} [{tag.value_type}]: {values}")
    return "\n".join(lines)


async def infer_theme_filters(
    *,
    api_key: str,
    model: str,
    form_summary: str,
    tags: list[TagDefinition],
) -> tuple[Stage1Result, TokenUsage]:
    if not tags:
        raise ThemeRecommendationError("No active tags for theme filter inference")

    tags_by_name = {tag.name: tag for tag in tags}
    response_model = _build_stage1_response_model(tags)
    client = AsyncAnthropic(api_key=api_key)

    log_pretty(
        "Theme stage1 filter inference",
        {"model": model, "tag_count": len(tags), "form_summary": form_summary},
    )

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=_stage1_system_prompt(tags),
        messages=[
            {
                "role": "user",
                "content": (
                    "Map these form answers to filter enums and a pinecone query.\n\n"
                    f"{form_summary}"
                ),
            }
        ],
        tools=[
            {
                "name": STAGE1_TOOL,
                "description": (
                    "Submit input_filters (chosen enums) and a short pinecone_query "
                    "for theme recommendation retrieval."
                ),
                "input_schema": response_model.model_json_schema(),
            },
        ],
        tool_choice={"type": "tool", "name": STAGE1_TOOL},
    )

    usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
    log_pretty(
        "Theme stage1 token usage",
        {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        },
    )

    tool_input = _extract_tool_input(response, STAGE1_TOOL)
    parsed = response_model.model_validate(tool_input)
    raw_filters = parsed.input_filters.model_dump(exclude_none=True)  # type: ignore[attr-defined]
    query = str(parsed.pinecone_query).strip()  # type: ignore[attr-defined]
    if not query:
        raise ThemeRecommendationError("Haiku returned an empty pinecone_query")

    result = Stage1Result(
        input_filters=_normalize_filters(raw_filters, tags_by_name),
        pinecone_query=query,
    )
    log_pretty(
        "Theme stage1 result",
        {
            "input_filters": result.input_filters,
            "pinecone_query": result.pinecone_query,
        },
    )
    return result, usage


class Stage2Response(BaseModel):
    themes: list[ThemeIdea] = Field(
        description="List of theme ideas with short title and description"
    )


async def synthesize_themes(
    *,
    api_key: str,
    model: str,
    form_summary: str,
    chunk_texts: list[str],
    top_k: int = 5,
) -> tuple[list[ThemeIdea], TokenUsage]:
    client = AsyncAnthropic(api_key=api_key)
    sources = "\n\n".join(
        f"[{i}] {text.strip()}"
        for i, text in enumerate(chunk_texts, start=1)
        if text.strip()
    )
    if not sources:
        sources = "(no retrieved chunks)"

    system = (
        "You write party theme ideas grounded in the retrieved sources. "
        f"Return exactly {top_k} themes. "
        "Each title is 2-3 words. Each description is 10-15 words. "
        "Do not mention sources."
    )
    user = (
        f"FORM:\n{form_summary}\n\n"
        f"SOURCES:\n{sources}\n\n"
        f"Return exactly {top_k} themes."
    )

    log_pretty(
        "Theme stage2 synthesis",
        {"model": model, "top_k": top_k, "source_count": len(chunk_texts)},
    )

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[
            {
                "name": STAGE2_TOOL,
                "description": "Submit the list of theme ideas.",
                "input_schema": Stage2Response.model_json_schema(),
            },
        ],
        tool_choice={"type": "tool", "name": STAGE2_TOOL},
    )

    usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
    log_pretty(
        "Theme stage2 token usage",
        {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        },
    )

    tool_input = _extract_tool_input(response, STAGE2_TOOL)
    parsed = Stage2Response.model_validate(tool_input)
    themes = [
        ThemeIdea(title=t.title.strip(), description=t.description.strip())
        for t in parsed.themes
        if t.title.strip() and t.description.strip()
    ]
    if not themes:
        raise ThemeRecommendationError("Haiku returned no themes")
    return themes[:top_k], usage
