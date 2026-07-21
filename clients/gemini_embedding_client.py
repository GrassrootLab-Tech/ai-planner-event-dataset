from __future__ import annotations

from google import genai
from google.genai import types

from utils.logger import log_pretty, logger

DEFAULT_OUTPUT_DIMENSIONALITY = 3072


class GeminiEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-2",
        *,
        output_dimensionality: int = DEFAULT_OUTPUT_DIMENSIONALITY,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._output_dimensionality = output_dimensionality

    @property
    def model(self) -> str:
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # One Content per text so gemini-embedding-2 returns N embeddings, not 1.
        contents = [
            types.Content(parts=[types.Part(text=text)]) for text in texts
        ]
        log_pretty(
            "Gemini embedding texts",
            {
                "model": self._model,
                "text_count": len(texts),
                "output_dimensionality": self._output_dimensionality,
            },
        )
        response = await self._client.aio.models.embed_content(
            model=self._model,
            contents=contents,
            config=types.EmbedContentConfig(
                output_dimensionality=self._output_dimensionality,
            ),
        )
        embeddings = [
            list(item.values) for item in (response.embeddings or []) if item.values
        ]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Gemini returned {len(embeddings)} embeddings for {len(texts)} texts"
            )
        logger.info("Generated %d Gemini embeddings", len(embeddings))
        return embeddings
