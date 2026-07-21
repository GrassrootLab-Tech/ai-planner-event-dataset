import json
from datetime import datetime
from typing import Any

from models.event_scraped_chunk import EventScrapedChunk
from tags.order import SCALAR_LIST_VALUES


def _pinecone_safe_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return value
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _should_omit_tag_value(value: Any) -> bool:
    """Omit sentinel strings, empty lists, and lists that only contain sentinels."""
    if value is None or value == "":
        return True
    if isinstance(value, str) and value in SCALAR_LIST_VALUES:
        return True
    if isinstance(value, list) and (
        not value or all(item in SCALAR_LIST_VALUES for item in value)
    ):
        return True
    return False


def _clean_tag_value(value: Any) -> Any:
    """Strip sentinel items from string lists; return other values unchanged."""
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item and item not in SCALAR_LIST_VALUES]
    return value


def build_pinecone_metadata(
    chunk_doc: EventScrapedChunk,
    *,
    embedding_model: str,
    page_title: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "chunk": chunk_doc.chunk,
        "page_url": chunk_doc.page_url,
        "parent_section_heading": chunk_doc.parent_section_heading or "",
        "scraped_at": _pinecone_safe_value(chunk_doc.scraped_at),
        "embedding_model": embedding_model,
    }
    if page_title and page_title.strip():
        metadata["page_title"] = page_title.strip()

    if chunk_doc.metadata_tags:
        for key, value in chunk_doc.metadata_tags.items():
            cleaned = _clean_tag_value(value)
            if _should_omit_tag_value(cleaned):
                continue
            metadata[key] = _pinecone_safe_value(cleaned)

    return metadata
