from anthropic import AsyncAnthropic

from models.chunk_anonymization import ArticleAnonymizationResult
from prompts import load_prompt
from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage

TOOL_NAME = "submit_anonymized"
MAX_TOKENS = 32_000
SYSTEM_PROMPT = load_prompt("chunk_anonymization")


class AnonymizationError(Exception):
    pass


class AnthropicAnonymizationClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def anonymize_article(self, chunks: list[str]) -> tuple[list[str], TokenUsage]:
        if not chunks:
            return [], TokenUsage()

        user_content = self._build_user_content(chunks)
        chunk_count = len(chunks)

        log_pretty(
            "Anonymizing article",
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
                        "Submit anonymized chunk text for every chunk_index. "
                        "Return the full chunk text with only listed named entities "
                        "replaced by XX; do not rewrite other text."
                    ),
                    "input_schema": ArticleAnonymizationResult.model_json_schema(),
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
        parsed = ArticleAnonymizationResult.model_validate(tool_input)
        return self._map_results(parsed, chunk_count), usage

    @staticmethod
    def _build_user_content(chunks: list[str]) -> str:
        parts = [
            "Anonymize each section below. Return one result per chunk_index.\n",
        ]
        for index, chunk in enumerate(chunks):
            parts.append(f"--- chunk_index: {index} ---")
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
                    raise AnonymizationError("Anthropic tool_use input is not an object")
                return tool_input
        raise AnonymizationError("Anthropic returned no submit_anonymized tool_use block")

    @staticmethod
    def _map_results(parsed: ArticleAnonymizationResult, chunk_count: int) -> list[str]:
        if len(parsed.chunks) != chunk_count:
            raise AnonymizationError(
                f"Expected {chunk_count} results, got {len(parsed.chunks)}"
            )

        by_index: dict[int, str] = {}
        for item in parsed.chunks:
            if item.chunk_index in by_index:
                raise AnonymizationError(f"Duplicate chunk_index {item.chunk_index}")
            by_index[item.chunk_index] = item.anonymized_text

        missing = [i for i in range(chunk_count) if i not in by_index]
        if missing:
            raise AnonymizationError(f"Missing chunk_index values: {missing}")

        results = [by_index[i] for i in range(chunk_count)]
        logger.info("Anonymized %d chunks", len(results))
        return results
