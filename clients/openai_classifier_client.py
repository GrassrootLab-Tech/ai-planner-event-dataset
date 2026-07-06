from openai import AsyncOpenAI

from models.chunk_classification import ChunkClassificationResult
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

    async def classify_chunk(
        self,
        chunk: str,
        *,
        parent_section_heading: str | None = None,
    ) -> IsUsable:
        user_content = chunk
        if parent_section_heading:
            user_content = (
                f"Parent section heading: {parent_section_heading}\n\n"
                f"Section content:\n{chunk}"
            )

        log_pretty("Classifying chunk", {
            "model": self._model,
            "parent_section_heading": parent_section_heading,
            "chunk_preview": chunk[:200],
        })

        response = await self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=ChunkClassificationResult,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ClassificationError("OpenAI returned no parsed classification result")

        is_usable = IsUsable(
            value=parsed.classification == "usable",
            confidence=parsed.confidence,
        )
        logger.info(
            "Classification result: value=%s confidence=%.2f",
            is_usable.value,
            is_usable.confidence,
        )
        return is_usable
