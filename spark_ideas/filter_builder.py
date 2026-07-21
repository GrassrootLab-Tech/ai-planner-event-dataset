"""Static Pinecone filter for spark ideas retrieval."""

from __future__ import annotations

from typing import Any


def _field_exists(tag_name: str) -> dict[str, Any]:
    """Match when the tag is present.

    Sentinel / empty values are omitted at upsert time, so existence == real value.
    """
    return {tag_name: {"$exists": True}}


def build_spark_pinecone_filter(event_type: str) -> dict[str, Any]:
    return {
        "$and": [
            {"event_type": {"$eq": event_type.strip()}},
            {
                "$or": [
                    _field_exists("statement_piece"),
                    {"photo_moment_flag": {"$eq": True}},
                    _field_exists("personalization_element"),
                ]
            },
        ]
    }
