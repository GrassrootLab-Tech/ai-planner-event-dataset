from anthropic import AsyncAnthropic

from models.chunk_classification import ArticleClassificationResult
from models.event_scraped_chunk import IsUsable
from prompts import load_prompt
from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage

TOOL_NAME = "submit_classifications"
MAX_TOKENS = 32_000
SYSTEM_PROMPT = load_prompt("chunk_usability")


class ClassificationError(Exception):
    pass


class AnthropicClassifierClient:
    def __init__(self, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def classify_article(
        self,
        chunks: list[tuple[str, str | None]],
    ) -> tuple[list[IsUsable], TokenUsage]:
        if not chunks:
            return [], TokenUsage()

        user_content = self._build_user_content(chunks)
        chunk_count = len(chunks)

        log_pretty(
            "Classifying article",
            {
                "model": self._model,
                "chunk_count": chunk_count,
            },
        )

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_content},
            ],
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": (
                        "Submit usability classifications for every chunk_index. "
                        "Return one usable or not_usable classification and confidence "
                        "score for each chunk."
                    ),
                    "input_schema": ArticleClassificationResult.model_json_schema(),
                },
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        ) as stream:
            response = await stream.get_final_message()

        usage = TokenUsage.from_anthropic(getattr(response, "usage", None))
        log_pretty(
            "Anthropic classification token usage",
            {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "max_tokens": MAX_TOKENS,
            },
        )

        tool_input = self._extract_tool_input(response)
        parsed = ArticleClassificationResult.model_validate(tool_input)
        return self._map_results(parsed, chunk_count), usage

    @staticmethod
    def _build_user_content(chunks: list[tuple[str, str | None]]) -> str:
        parts = ["Classify each section below. Return one result per chunk_index.\n"]
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
                    raise ClassificationError(
                        "Anthropic tool_use input is not an object"
                    )
                return tool_input
        raise ClassificationError(
            "Anthropic returned no submit_classifications tool_use block"
        )

    @staticmethod
    def _map_results(
        parsed: ArticleClassificationResult,
        chunk_count: int,
    ) -> list[IsUsable]:
        if len(parsed.chunks) != chunk_count:
            logger.warning(
                "Classification result count mismatch: expected %d, got %d; "
                "keeping valid indexes and defaulting the rest to not_usable",
                chunk_count,
                len(parsed.chunks),
            )

        by_index: dict[int, IsUsable] = {}
        for item in parsed.chunks:
            index = item.chunk_index
            if index < 0 or index >= chunk_count:
                logger.warning("Ignoring out-of-range chunk_index %d", index)
                continue
            if index in by_index:
                logger.warning(
                    "Duplicate chunk_index %d; keeping first result",
                    index,
                )
                continue
            by_index[index] = IsUsable(
                value=item.classification == "usable",
                confidence=item.confidence,
            )

        missing = [i for i in range(chunk_count) if i not in by_index]
        if missing:
            logger.warning(
                "Missing chunk_index values %s; defaulting to not_usable",
                missing,
            )
            for index in missing:
                by_index[index] = IsUsable(value=False, confidence=0.0)

        results = [by_index[i] for i in range(chunk_count)]
        logger.info(
            "Classification result: %d usable, %d not_usable",
            sum(1 for result in results if result.value),
            sum(1 for result in results if not result.value),
        )
        return results
