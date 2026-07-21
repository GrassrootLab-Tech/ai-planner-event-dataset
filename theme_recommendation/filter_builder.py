"""Build Pinecone metadata filters: hardcoded AND + LLM OR (plus photo_moment_flag)."""

from __future__ import annotations

from typing import Any

from theme_recommendation.constants import (
    AND_CONTENT_CATEGORY,
    AND_IDEA_GRANULARITY,
    EVENT_TYPE_TAG,
    OR_PHOTO_MOMENT_FLAG,
)


def clause_for_tag(tag_name: str, value: list[str] | bool) -> dict[str, Any]:
    if isinstance(value, bool):
        return {tag_name: value}
    return {tag_name: {"$in": value}}


def build_theme_pinecone_filter(
    input_filters: dict[str, list[str] | bool],
) -> dict[str, Any] | None:
    and_clauses: list[dict[str, Any]] = [
        clause_for_tag("content_category", [AND_CONTENT_CATEGORY]),
        clause_for_tag("idea_granularity", list(AND_IDEA_GRANULARITY)),
    ]

    event_type_value = input_filters.get(EVENT_TYPE_TAG)
    if isinstance(event_type_value, list) and event_type_value:
        and_clauses.append(clause_for_tag(EVENT_TYPE_TAG, event_type_value))

    or_clauses: list[dict[str, Any]] = [
        clause_for_tag("photo_moment_flag", OR_PHOTO_MOMENT_FLAG),
    ]
    for tag_name, value in input_filters.items():
        if tag_name == EVENT_TYPE_TAG:
            continue
        if tag_name == "kid_safe_flag" and value is False:
            continue
        or_clauses.append(clause_for_tag(tag_name, value))

    if and_clauses and or_clauses:
        return {"$and": [*and_clauses, {"$or": or_clauses}]}
    if and_clauses:
        if len(and_clauses) == 1:
            return and_clauses[0]
        return {"$and": and_clauses}
    if len(or_clauses) == 1:
        return or_clauses[0]
    return {"$or": or_clauses}
