from openai import AsyncOpenAI

from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage


class OpenAIEmbeddingClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def embed_texts(self, texts: list[str]) -> tuple[list[list[float]], TokenUsage]:
        if not texts:
            return [], TokenUsage()

        log_pretty("Embedding texts", {
            "model": self._model,
            "text_count": len(texts),
        })

        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )

        embeddings = [item.embedding for item in response.data]
        usage = TokenUsage.from_openai_embedding(response.usage)
        log_pretty("OpenAI embedding token usage", {
            "input_tokens": usage.input_tokens,
        })
        logger.info("Generated %d embeddings", len(embeddings))
        return embeddings, usage
