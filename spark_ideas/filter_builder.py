"""Static Pinecone filter for spark ideas retrieval."""

from __future__ import annotations

from typing import Any

from tags.registry import TagRegistry

_SENTINEL = "not_applicable"


def _has_real_value_clause(tag_name: str, registry: TagRegistry) -> dict[str, Any]:
    """Match when the tag has a real enum value (excludes not_applicable and empty lists).

    Pinecone `$ne` only accepts string/bool/number — not `[]` — so we use `$in`
    over allowed values instead.
    """
    tag = registry.get(tag_name)
    allowed = [v for v in (tag.values or ()) if v != _SENTINEL]
    return {tag_name: {"$in": allowed}}


def build_spark_pinecone_filter(event_type: str) -> dict[str, Any]:
    registry = TagRegistry()
    return {
        "$and": [
            {"event_type": {"$eq": event_type.strip()}},
            {
                "$or": [
                    _has_real_value_clause("statement_piece", registry),
                    {"photo_moment_flag": {"$eq": True}},
                    _has_real_value_clause("personalization_element", registry),
                ]
            },
        ]
    }
