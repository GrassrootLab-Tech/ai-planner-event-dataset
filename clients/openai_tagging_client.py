from openai import AsyncOpenAI
from pydantic import BaseModel

from models.chunk_tagging import build_group_result_model, chunk_item_to_tag_dict
from tags.prompt_builder import build_group_system_prompt
from tags.schema import TagValue
from tags.spec import TagDefinition
from utils.logger import log_pretty, logger


class TaggingError(Exception):
    pass


class OpenAITaggingClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def classify_group(
        self,
        group_id: str,
        tags: list[TagDefinition],
        chunks: list[tuple[str, str | None]],
    ) -> list[dict[str, TagValue]]:
        if not chunks:
            return []

        system_prompt = build_group_system_prompt(group_id, tags)
        user_content = self._build_user_content(chunks)
        response_model = build_group_result_model(group_id, tags)
        chunk_count = len(chunks)
        tag_names = [tag.name for tag in tags]

        log_pretty("Tagging group", {
            "group_id": group_id,
            "model": self._model,
            "chunk_count": chunk_count,
            "tag_count": len(tags),
        })

        response = await self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format=response_model,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise TaggingError(f"OpenAI returned no parsed result for group '{group_id}'")

        return self._map_results(parsed, chunk_count, tag_names, group_id)

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
    def _map_results(
        parsed: BaseModel,
        chunk_count: int,
        tag_names: list[str],
        group_id: str,
    ) -> list[dict[str, TagValue]]:
        chunks = parsed.chunks  # type: ignore[attr-defined]
        if len(chunks) != chunk_count:
            raise TaggingError(
                f"Group '{group_id}': expected {chunk_count} results, got {len(chunks)}"
            )

        by_index: dict[int, dict[str, TagValue]] = {}
        for item in chunks:
            if item.chunk_index in by_index:
                raise TaggingError(
                    f"Group '{group_id}': duplicate chunk_index {item.chunk_index}"
                )
            by_index[item.chunk_index] = chunk_item_to_tag_dict(item, tag_names)

        missing = [i for i in range(chunk_count) if i not in by_index]
        if missing:
            raise TaggingError(f"Group '{group_id}': missing chunk_index values: {missing}")

        results = [by_index[i] for i in range(chunk_count)]
        logger.info("Group '%s' tagged %d chunks", group_id, len(results))
        return results
