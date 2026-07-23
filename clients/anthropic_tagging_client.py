from typing import Any

import json_repair
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from models.chunk_tagging import build_result_model, chunk_item_to_tag_dict
from tags.defaults import fill_missing_tag_defaults
from tags.prompt_builder import build_system_prompt
from tags.schema import TagValue
from tags.spec import TagDefinition
from utils.logger import log_pretty, logger
from utils.pipeline_cost import TokenUsage

TOOL_NAME = "submit_tags"
MAX_TOKENS = 45_000
CACHE_TTL = "1h"
_TOOL_DESCRIPTION = (
    "Submit tagging results for every chunk_index. "
    "Always include boolean tags. Omit unclassified non-boolean tags. "
    "Do not include chunk text. "
    "For multi-value tags return a list; for single tags return a string."
)


class TaggingError(Exception):
    pass


class AnthropicTaggingClient:
    def __init__(
        self,
        client: AsyncAnthropic,
        model: str,
        *,
        cache: bool = False,
    ) -> None:
        self._client = client
        self._model = model
        self._cache = cache

    @property
    def model(self) -> str:
        return self._model

    def build_batch_request(
        self,
        custom_id: str,
        tags: list[TagDefinition],
        chunks: list[tuple[str, str | None]],
        *,
        page_url: str,
        page_title: str | None = None,
    ) -> dict:
        if not chunks:
            raise TaggingError("Cannot build tagging request with no chunks")

        system_prompt = build_system_prompt(tags)
        user_content = self._build_user_content(
            chunks,
            page_url=page_url,
            page_title=page_title,
        )
        response_model = build_result_model(tags)
        return {
            "custom_id": custom_id,
            "params": {
                "model": self._model,
                "max_tokens": MAX_TOKENS,
                "system": self._system_param(system_prompt),
                "messages": [
                    {"role": "user", "content": user_content},
                ],
                "tools": [
                    {
                        "name": TOOL_NAME,
                        "description": _TOOL_DESCRIPTION,
                        "input_schema": response_model.model_json_schema(),
                    },
                ],
                "tool_choice": {"type": "tool", "name": TOOL_NAME},
            },
        }

    async def submit_batch(self, requests: list[dict]) -> str:
        if not requests:
            raise TaggingError("Cannot submit empty tagging batch")

        log_pretty(
            "Submitting tagging batch",
            {
                "model": self._model,
                "request_count": len(requests),
                "cache": self._cache,
            },
        )
        batch = await self._client.messages.batches.create(requests=requests)
        logger.info(
            "Queued tagging batch id=%s request_count=%d",
            batch.id,
            len(requests),
        )
        return batch.id

    def parse_message_result(
        self,
        message: object,
        tags: list[TagDefinition],
        chunk_count: int,
    ) -> tuple[list[dict[str, TagValue]], TokenUsage, dict]:
        usage = TokenUsage.from_anthropic(getattr(message, "usage", None))
        tool_input = self.extract_tool_input(message)
        normalized = self.normalize_tool_input(tool_input)
        response_model = build_result_model(tags)
        parsed = response_model.model_validate(normalized)
        return self.map_results(parsed, chunk_count, tags), usage, normalized

    def _system_param(self, system_prompt: str) -> str | list[dict]:
        if not self._cache:
            return system_prompt
        return [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": CACHE_TTL},
            },
        ]

    @staticmethod
    def _build_user_content(
        chunks: list[tuple[str, str | None]],
        *,
        page_url: str,
        page_title: str | None = None,
    ) -> str:
        parts = ["Tag each section below. Return one result per chunk_index.\n"]
        parts.append(f"page_url: {page_url}")
        if page_title:
            parts.append(f"page_title: {page_title}")
        parts.append("")
        for index, (chunk, parent_heading) in enumerate(chunks):
            parts.append(f"--- chunk_index: {index} ---")
            if parent_heading:
                parts.append(f"parent_section_heading: {parent_heading}")
            parts.append(chunk)
            parts.append("")
        return "\n".join(parts)

    @staticmethod
    def extract_tool_input(response: object) -> dict:
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
    def normalize_tool_input(tool_input: dict) -> dict:
        """Coerce common malformed tool payloads without changing valid ones."""
        data = dict(tool_input)
        chunks = data.get("chunks")
        if isinstance(chunks, str):
            data["chunks"] = AnthropicTaggingClient._parse_chunks_json(chunks)
        return data

    @staticmethod
    def _parse_chunks_json(raw: str) -> list[Any]:
        text = raw.strip()
        parsed: Any = AnthropicTaggingClient._loads_repaired_json(text)
        if parsed is None:
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1 or end <= start:
                raise TaggingError(
                    "Anthropic tool_use chunks is a non-JSON string"
                )
            parsed = AnthropicTaggingClient._loads_repaired_json(
                text[start : end + 1]
            )
            if parsed is None:
                raise TaggingError(
                    "Anthropic tool_use chunks string could not be parsed as JSON"
                )
        if not isinstance(parsed, list):
            raise TaggingError("Anthropic tool_use chunks JSON is not a list")
        return parsed

    @staticmethod
    def _loads_repaired_json(raw: str) -> Any | None:
        try:
            return json_repair.loads(raw)
        except Exception:
            return None

    @staticmethod
    def map_results(
        parsed: BaseModel,
        chunk_count: int,
        tags: list[TagDefinition],
    ) -> list[dict[str, TagValue]]:
        chunks = parsed.chunks  # type: ignore[attr-defined]
        if len(chunks) != chunk_count:
            logger.warning(
                "Tagging result count mismatch: expected %d, got %d; "
                "keeping valid indexes and defaulting the rest",
                chunk_count,
                len(chunks),
            )

        by_index: dict[int, dict[str, TagValue]] = {}
        for item in chunks:
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
            sparse_tags = chunk_item_to_tag_dict(item)
            by_index[index] = fill_missing_tag_defaults(sparse_tags, tags)

        missing = [i for i in range(chunk_count) if i not in by_index]
        if missing:
            logger.warning(
                "Missing chunk_index values %s; filling with defaults",
                missing,
            )
            defaults = AnthropicTaggingClient._default_tags(tags)
            for index in missing:
                by_index[index] = defaults

        results = [by_index[i] for i in range(chunk_count)]
        logger.info("Tagged %d chunks", len(results))
        return results

    @staticmethod
    def _default_tags(tags: list[TagDefinition]) -> dict[str, TagValue]:
        bools = {tag.name: False for tag in tags if tag.value_type == "bool"}
        return fill_missing_tag_defaults(bools, tags)
