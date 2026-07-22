"""Facet query specs and display constants for theme packages."""

from __future__ import annotations

from typing import Any

from theme_recommendation.constants import (
    BUDGET_OPTIONS,
    SERVICE_TYPE_OPTIONS,
    ThemeFormInput,
)

PACKAGE_COUNT = 3
IDEAS_PER_PACKAGE_MIN = 6
IDEAS_PER_PACKAGE_MAX = 7
FACET_TOP_K = 3

def _field_exists(tag_name: str) -> dict[str, Any]:
    """Match when the tag is present.

    Sentinel / empty values are omitted at upsert time, so existence == real value.
    """
    return {tag_name: {"$exists": True}}


# Per-facet retrieval templates. Runtime always uses FACET_TOP_K (ignores top_k below).
# Element/theme fields use $exists — sentinels like not_applicable are never stored.
FACET_QUERIES: dict[str, dict[str, Any]] = {
    "vibe_theme": {
        "query_text": "Overall vibe, mood, and creative theme concept for a {event_type} party",
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$eq": "themes"}},
                {"$or": [_field_exists("theme")]},
            ]
        },
    },
    "food": {
        "query_text": "Food and main dish ideas for a {event_type} party",
        "top_k": 4,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$eq": "food"}},
                _field_exists("food_element"),
            ]
        },
    },
    "desserts": {
        "query_text": "Dessert and cake ideas for a {event_type} party",
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$eq": "desserts"}},
                _field_exists("dessert_element"),
            ]
        },
    },
    "beverages": {
        "query_text": "Drinks and beverage ideas for a {event_type} party",
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$eq": "beverages"}},
                _field_exists("beverage_element"),
            ]
        },
    },
    "decor": {
        "query_text": "Decor and atmosphere setup ideas for a {event_type} party",
        "top_k": 4,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$eq": "decor"}},
                _field_exists("decor_element"),
            ]
        },
    },
    "lighting": {
        "query_text": "Lighting setup and ambiance ideas for a {event_type} party",
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$eq": "lighting"}},
                _field_exists("decor_element"),
            ]
        },
    },
    "entertainment": {
        "query_text": "Entertainment, games, and activity ideas for a {event_type} party",
        "top_k": 4,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {
                    "content_category": {
                        "$in": ["entertainment", "games", "activities"]
                    }
                },
                _field_exists("activity_element"),
            ]
        },
    },
    "gifting": {
        "query_text": "Party favors and gifting ideas for a {event_type} party",
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$in": ["gifting", "favors"]}},
                _field_exists("gifting_context"),
            ]
        },
    },
    "diy_projects": {
        "query_text": "DIY craft and project ideas for a {event_type} party",
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"content_category": {"$eq": "diy_projects"}},
                {"procurement_mode": {"$eq": "diy_makeable"}},
            ]
        },
    },
    "photo_moments": {
        "query_text": (
            "Unique, photogenic, standout moments and visuals for a {event_type} party"
        ),
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {"photo_moment_flag": {"$eq": True}},
            ]
        },
    },
    "statement_spark": {
        "query_text": (
            "Statement pieces, personalized details, and special favor ideas "
            "for a {event_type} party"
        ),
        "top_k": 3,
        "filter": {
            "$and": [
                {"event_type": {"$eq": "{event_type}"}},
                {
                    "$or": [
                        _field_exists("statement_piece"),
                        _field_exists("personalization_element"),
                        _field_exists("favor_element"),
                    ]
                },
            ]
        },
    },
}

__all__ = [
    "BUDGET_OPTIONS",
    "SERVICE_TYPE_OPTIONS",
    "ThemeFormInput",
    "PACKAGE_COUNT",
    "IDEAS_PER_PACKAGE_MIN",
    "IDEAS_PER_PACKAGE_MAX",
    "FACET_TOP_K",
    "FACET_QUERIES",
]
