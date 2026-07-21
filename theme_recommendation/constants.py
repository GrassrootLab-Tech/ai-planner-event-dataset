"""Form options and hardcoded input → tag mappings for theme recommendation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

SERVICE_TYPE_OPTIONS: tuple[str, ...] = (
    "Food & Beverage",
    "Entertainment (Musical)",
    "Entertainment (Non Musical)",
    "Photography & Videography",
    "Event Production & Services",
    "Beauty & Wellness",
)

BUDGET_OPTIONS: tuple[str, ...] = (
    "< $1,000",
    "$1,000 – $5,000",
    "$5,000 – $8,000",
    "$8,000 – $15,000",
    "> $15,000",
)

# Form field name → tag name. Filled fields only enter LLM context.
INPUT_TAG_MAP: dict[str, str] = {
    "event_type": "event_type",
    "celebratee": "host_guest_relationship",
    "attendees_age_range": "age_group",
    "attendees": "guest_mix",
    "guest_count": "guest_scale",
    "budget": "budget_tier",
    "service_type": "vendor_category",
    "start_end_time": "time_of_day",
}

# Always included so Haiku can infer from other answers.
ALWAYS_ON_TAGS: tuple[str, ...] = (
    "honoree_gender_skew",
    "kid_safe_flag",
)

AND_CONTENT_CATEGORY = "themes"
AND_IDEA_GRANULARITY: tuple[str, ...] = (
    "mini_theme",
    "full_party_concept",
    "single_element",
    "inspiration_gallery",
)
OR_PHOTO_MOMENT_FLAG = True

EVENT_TYPE_TAG = "event_type"


@dataclass
class ThemeFormInput:
    event_type: str
    celebratee: str | None = None
    location: str | None = None
    event_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    attendees: list[str] = field(default_factory=list)
    attendees_age_range: str | None = None
    guest_count: str | None = None
    service_type: list[str] = field(default_factory=list)
    budget: str | None = None
