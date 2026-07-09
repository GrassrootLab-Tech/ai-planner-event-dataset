import json
from datetime import datetime
from typing import Any

from models.event_scraped_chunk import EventScrapedChunk


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


def build_pinecone_metadata(
    chunk_doc: EventScrapedChunk,
    *,
    embedding_model: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "chunk": chunk_doc.chunk,
        "page_url": chunk_doc.page_url,
        "parent_section_heading": chunk_doc.parent_section_heading or "",
        "scraped_at": _pinecone_safe_value(chunk_doc.scraped_at),
        "embedding_model": embedding_model,
    }

    if chunk_doc.metadata_tags:
        for key, value in chunk_doc.metadata_tags.items():
            metadata[key] = _pinecone_safe_value(value)

    return metadata
