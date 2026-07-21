"""Haiku synthesis for spark ideas (single LLM call)."""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from utils.logger import log_pretty

SPARK_TOOL = "submit_spark_ideas"
MAX_TOKENS = 4096


class SparkIdeasError(Exception):
    pass


class SparkIdea(BaseModel):
    idea: str = Field(
        description="One concise conversational spark idea (1-2 short sentences)"
    )


class SparkIdeasResponse(BaseModel):
    ideas: list[SparkIdea] = Field(description="List of spark ideas")


def _extract_tool_input(response: object, tool_name: str) -> dict[str, Any]:
    content = getattr(response, "content", None) or []
    for block in content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == tool_name
        ):
            tool_input = getattr(block, "input", None)
            if not isinstance(tool_input, dict):
                raise SparkIdeasError(
                    f"Anthropic tool_use input is not an object for {tool_name}"
                )
            return tool_input
    raise SparkIdeasError(f"Anthropic returned no {tool_name} tool_use block")


async def synthesize_spark_ideas(
    *,
    api_key: str,
    model: str,
    form_summary: str,
    chunk_texts: list[str],
    top_k: int = 7,
) -> list[SparkIdea]:
    client = AsyncAnthropic(api_key=api_key)
    sources = "\n\n".join(
        f"[{i}] {text.strip()}"
        for i, text in enumerate(chunk_texts, start=1)
        if text.strip()
    )
    if not sources:
        sources = (
            "(no retrieved chunks; invent plausible spark ideas from the form alone)"
        )

    system = (
        "You suggest unique, mind-blowing “spark” ideas that make a party "
        "instantly memorable — statement pieces, photo moments, and "
        "personalization that add unexpected sparkle. "
        "Take inspiration from the retrieved source chunks: remix and adapt "
        "what’s in them into fresh ideas for this form, rather than inventing "
        "from scratch when sources are present. If there are no sources, invent "
        "plausible ideas from the form alone. "
        "Speak in a warm, conversational host-planner voice. "
        "Keep each idea to 1–2 short sentences. "
        "Do not mention sources, chunk numbers, or tags. "
        f"Return exactly {top_k} ideas."
    )
    user = (
        f"FORM:\n{form_summary}\n\n"
        f"SOURCES:\n{sources}\n\n"
        f"Return exactly {top_k} spark ideas. "
        "Draw each idea from the sources when possible."
    )

    log_pretty(
        "Spark ideas synthesis",
        {"model": model, "top_k": top_k, "source_count": len(chunk_texts)},
    )

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[
            {
                "name": SPARK_TOOL,
                "description": "Submit the list of spark ideas.",
                "input_schema": SparkIdeasResponse.model_json_schema(),
            },
        ],
        tool_choice={"type": "tool", "name": SPARK_TOOL},
    )

    usage = getattr(response, "usage", None)
    log_pretty(
        "Spark ideas token usage",
        {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    )

    tool_input = _extract_tool_input(response, SPARK_TOOL)
    parsed = SparkIdeasResponse.model_validate(tool_input)
    ideas = [
        SparkIdea(idea=item.idea.strip())
        for item in parsed.ideas
        if item.idea.strip()
    ]
    if not ideas:
        raise SparkIdeasError("Haiku returned no spark ideas")
    return ideas[:top_k]
