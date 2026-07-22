"""Pinecone filter for spark ideas: Stage1 event_type + spark signals + input_filters."""

from __future__ import annotations

from typing import Any

from theme_packages.filter_builder import event_type_from_input_filters
from theme_recommendation.constants import EVENT_TYPE_TAG
from theme_recommendation.filter_builder import clause_for_tag


def _field_exists(tag_name: str) -> dict[str, Any]:
    """Match when the tag is present.

    Sentinel / empty values are omitted at upsert time, so existence == real value.
    """
    return {tag_name: {"$exists": True}}


def build_spark_pinecone_filter(
    input_filters: dict[str, list[str] | bool],
) -> dict[str, Any]:
    """AND event_type + spark-signal OR + Stage1 input_filters OR (except event_type)."""
    event_type = event_type_from_input_filters(input_filters)
    and_clauses: list[dict[str, Any]] = [
        {"event_type": {"$eq": event_type}},
        {
            "$or": [
                _field_exists("statement_piece"),
                {"photo_moment_flag": {"$eq": True}},
                _field_exists("personalization_element"),
            ]
        },
    ]

    input_or: list[dict[str, Any]] = []
    for tag_name, value in input_filters.items():
        if tag_name == EVENT_TYPE_TAG:
            continue
        if tag_name == "kid_safe_flag" and value is False:
            continue
        input_or.append(clause_for_tag(tag_name, value))
    if input_or:
        and_clauses.append({"$or": input_or})

    return {"$and": and_clauses}
