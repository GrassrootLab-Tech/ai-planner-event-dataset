"""Merge Stage1 input_filters into each facet's hardcoded Pinecone filter."""

from __future__ import annotations

import copy
from typing import Any

from theme_recommendation.constants import EVENT_TYPE_TAG
from theme_recommendation.filter_builder import clause_for_tag
from theme_packages.constants import FACET_QUERIES, FACET_TOP_K


class ThemePackagesFilterError(Exception):
    pass


def event_type_from_input_filters(
    input_filters: dict[str, list[str] | bool],
) -> str:
    """Pinecone event_type enum from Stage1 only (e.g. baby_shower, not form text)."""
    value = input_filters.get(EVENT_TYPE_TAG)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ThemePackagesFilterError(
        "Stage1 input_filters missing event_type; cannot build facet filters"
    )


def _substitute_event_type(node: Any, event_type: str) -> Any:
    if isinstance(node, str):
        return node.replace("{event_type}", event_type)
    if isinstance(node, list):
        return [_substitute_event_type(item, event_type) for item in node]
    if isinstance(node, dict):
        return {
            key: _substitute_event_type(value, event_type) for key, value in node.items()
        }
    return node


def _find_or_create_or_clauses(filter_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the mutable $or list inside a facet filter (create if missing)."""
    and_clauses = filter_dict.get("$and")
    if isinstance(and_clauses, list):
        for clause in and_clauses:
            if isinstance(clause, dict) and "$or" in clause:
                or_list = clause["$or"]
                if isinstance(or_list, list):
                    return or_list
                clause["$or"] = []
                return clause["$or"]
        new_or: list[dict[str, Any]] = []
        and_clauses.append({"$or": new_or})
        return new_or

    if "$or" in filter_dict and isinstance(filter_dict["$or"], list):
        return filter_dict["$or"]

    new_or = []
    filter_dict["$or"] = new_or
    return new_or


def build_facet_filter(
    facet_key: str,
    *,
    input_filters: dict[str, list[str] | bool],
) -> dict[str, Any]:
    event_type = event_type_from_input_filters(input_filters)
    spec = FACET_QUERIES[facet_key]
    filter_dict = _substitute_event_type(copy.deepcopy(spec["filter"]), event_type)

    extra_or: list[dict[str, Any]] = []
    for tag_name, value in input_filters.items():
        if tag_name == EVENT_TYPE_TAG:
            continue
        if tag_name == "kid_safe_flag" and value is False:
            continue
        extra_or.append(clause_for_tag(tag_name, value))

    # Only touch $or when Stage1 contributed clauses (avoids empty $or on photo_moments).
    if extra_or:
        or_clauses = _find_or_create_or_clauses(filter_dict)
        or_clauses.extend(extra_or)

    return filter_dict


def build_all_facet_specs(
    *,
    input_filters: dict[str, list[str] | bool],
) -> list[dict[str, Any]]:
    """Return list of {facet_key, query_text, filter, top_k} for parallel retrieval."""
    event_type = event_type_from_input_filters(input_filters)
    specs: list[dict[str, Any]] = []
    for facet_key, facet in FACET_QUERIES.items():
        query_text = str(facet["query_text"]).format(event_type=event_type)
        specs.append(
            {
                "facet_key": facet_key,
                "query_text": query_text,
                "filter": build_facet_filter(
                    facet_key,
                    input_filters=input_filters,
                ),
                "top_k": FACET_TOP_K,
            }
        )
    return specs
