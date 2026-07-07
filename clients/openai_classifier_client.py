from openai import AsyncOpenAI

from models.chunk_classification import ArticleClassificationResult
from models.event_scraped_chunk import IsUsable
from prompts import load_prompt
from utils.logger import log_pretty, logger

CLASSIFICATION_SYSTEM_PROMPT = load_prompt("chunk_usability")


class ClassificationError(Exception):
    pass


class OpenAIClassifierClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def classify_article(
        self,
        chunks: list[tuple[str, str | None]],
    ) -> list[IsUsable]:
        user_content = self._build_user_content(chunks)
        chunk_count = len(chunks)

        log_pretty("Classifying article", {
            "model": self._model,
            "chunk_count": chunk_count,
        })

        response = await self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=ArticleClassificationResult,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ClassificationError("OpenAI returned no parsed classification result")

        return self._map_results(parsed, chunk_count)

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
    def _map_results(parsed: ArticleClassificationResult, chunk_count: int) -> list[IsUsable]:
        if len(parsed.chunks) != chunk_count:
            raise ClassificationError(
                f"Expected {chunk_count} classifications, got {len(parsed.chunks)}"
            )

        by_index: dict[int, IsUsable] = {}
        for item in parsed.chunks:
            if item.chunk_index in by_index:
                raise ClassificationError(f"Duplicate chunk_index: {item.chunk_index}")
            by_index[item.chunk_index] = IsUsable(
                value=item.classification == "usable",
                confidence=item.confidence,
            )

        missing = [i for i in range(chunk_count) if i not in by_index]
        if missing:
            raise ClassificationError(f"Missing chunk_index values: {missing}")

        results = [by_index[i] for i in range(chunk_count)]
        logger.info(
            "Classification result: %d usable, %d not_usable",
            sum(1 for r in results if r.value),
            sum(1 for r in results if not r.value),
        )
        return results
