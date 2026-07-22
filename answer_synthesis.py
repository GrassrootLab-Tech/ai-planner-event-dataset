from __future__ import annotations

from anthropic import AsyncAnthropic

from retrieval import RetrievalResult
from utils.logger import log_pretty
from utils.pipeline_cost import TokenUsage

SYSTEM_PROMPT = """You're a friendly, enthusiastic event-planning buddy. Share ideas as your 
own genuine suggestions — never mention sources, documents, or how you know 
things. Keep it conversational, simple, and personal, like advice from a 
friend who loves helping people plan memorable events."""

INSTRUCTIONS = "Respond conversationally in a friendly and engaging tone, as if giving personalized advice. Don't mention the sources in your answer. Don't ask questions in your answer. Keep it simple and easy to understand."

MAX_TOKENS = 4096


def _heading_for_result(result: RetrievalResult) -> str:
    heading = str(result.metadata.get("parent_section_heading") or "").strip()
    return heading or "untitled"


def build_sources_block(results: list[RetrievalResult]) -> str:
    parts: list[str] = []
    for index, result in enumerate(results, start=1):
        heading = _heading_for_result(result)
        chunk = result.chunk.strip() if result.chunk else ""
        parts.append(f"[{index}] ({heading})\n{chunk}")
    return "\n\n".join(parts)


def build_user_message(query: str, results: list[RetrievalResult]) -> str:
    return (
        f'USER QUERY:\n"{query}"\n\n'
        f"SOURCES:\n{build_sources_block(results)}\n\n"
        f"INSTRUCTIONS:\n{INSTRUCTIONS}"
    )


async def synthesize_answer(
    *,
    api_key: str,
    model: str,
    query: str,
    results: list[RetrievalResult],
) -> tuple[str, TokenUsage]:
    if not results:
        return (
            "No sources were retrieved, so I can't answer from the available information.",
            TokenUsage(),
        )

    client = AsyncAnthropic(api_key=api_key)
    user_message = build_user_message(query, results)

    log_pretty(
        "Synthesizing answer",
        {
            "model": model,
            "source_count": len(results),
            "query": query,
        },
    )

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
    log_pretty(
        "Anthropic answer-synthesis token usage",
        {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        },
    )

    text_parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)

    answer = "\n".join(text_parts).strip()
    return answer or "The model returned an empty answer.", usage
