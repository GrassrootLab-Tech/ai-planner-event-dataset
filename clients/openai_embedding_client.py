from openai import AsyncOpenAI

from utils.logger import log_pretty, logger


class OpenAIEmbeddingClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        log_pretty("Embedding texts", {
            "model": self._model,
            "text_count": len(texts),
        })

        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )

        embeddings = [item.embedding for item in response.data]
        logger.info("Generated %d embeddings", len(embeddings))
        return embeddings
