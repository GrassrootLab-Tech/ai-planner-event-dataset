from anthropic import AsyncAnthropic
from pydantic import BaseModel

from models.chunk_tagging import build_result_model, chunk_item_to_tag_dict
from tags.prompt_builder import build_system_prompt
from tags.schema import TagValue
from tags.spec import TagDefinition
from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage

TOOL_NAME = "submit_tags"
MAX_TOKENS = 32_000


class TaggingError(Exception):
    pass


class AnthropicTaggingClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def classify_article(
        self,
        tags: list[TagDefinition],
        chunks: list[tuple[str, str | None]],
    ) -> tuple[list[dict[str, TagValue]], TokenUsage]:
        if not chunks:
            return [], TokenUsage()

        system_prompt = build_system_prompt(tags)
        user_content = self._build_user_content(chunks)
        response_model = build_result_model(tags)
        chunk_count = len(chunks)
        tag_names = [tag.name for tag in tags]

        log_pretty(
            "Tagging article",
            {
                "model": self._model,
                "chunk_count": chunk_count,
                "tag_count": len(tags),
            },
        )

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content},
            ],
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": (
                        "Submit tagging results for every chunk_index. "
                        "Return only tag values; do not include chunk text. "
                        "For multi-value tags return a list; for single tags return a string."
                    ),
                    "input_schema": response_model.model_json_schema(),
                },
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        ) as stream:
            response = await stream.get_final_message()

        usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
        log_pretty(
            "Anthropic token usage",
            {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "max_tokens": MAX_TOKENS,
            },
        )

        tool_input = self._extract_tool_input(response)
        parsed = response_model.model_validate(tool_input)
        return self._map_results(parsed, chunk_count, tag_names), usage

    @staticmethod
    def _build_user_content(chunks: list[tuple[str, str | None]]) -> str:
        parts = ["Tag each section below. Return one result per chunk_index.\n"]
        for index, (chunk, parent_heading) in enumerate(chunks):
            parts.append(f"--- chunk_index: {index} ---")
            if parent_heading:
                parts.append(f"parent_section_heading: {parent_heading}")
            parts.append(chunk)
            parts.append("")
        return "\n".join(parts)

    @staticmethod
    def _extract_tool_input(response: object) -> dict:
        content = getattr(response, "content", None) or []
        for block in content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == TOOL_NAME
            ):
                tool_input = getattr(block, "input", None)
                if not isinstance(tool_input, dict):
                    raise TaggingError("Anthropic tool_use input is not an object")
                return tool_input
        raise TaggingError("Anthropic returned no submit_tags tool_use block")

    @staticmethod
    def _map_results(
        parsed: BaseModel,
        chunk_count: int,
        tag_names: list[str],
    ) -> list[dict[str, TagValue]]:
        chunks = parsed.chunks  # type: ignore[attr-defined]
        if len(chunks) != chunk_count:
            raise TaggingError(f"Expected {chunk_count} results, got {len(chunks)}")

        by_index: dict[int, dict[str, TagValue]] = {}
        for item in chunks:
            if item.chunk_index in by_index:
                raise TaggingError(f"Duplicate chunk_index {item.chunk_index}")
            by_index[item.chunk_index] = chunk_item_to_tag_dict(item, tag_names)

        missing = [i for i in range(chunk_count) if i not in by_index]
        if missing:
            raise TaggingError(f"Missing chunk_index values: {missing}")

        results = [by_index[i] for i in range(chunk_count)]
        logger.info("Tagged %d chunks", len(results))
        return results
