"""Decide which tags/enums enter the Haiku prompt based on filled form fields."""

from __future__ import annotations

from tags.registry import TagRegistry
from tags.spec import TagDefinition
from theme_recommendation.constants import (
    ALWAYS_ON_TAGS,
    INPUT_TAG_MAP,
    ThemeFormInput,
)


def _is_filled_str(value: str | None) -> bool:
    return bool(value and value.strip())


def filled_input_keys(form: ThemeFormInput) -> set[str]:
    filled: set[str] = set()
    if _is_filled_str(form.event_type):
        filled.add("event_type")
    if _is_filled_str(form.celebratee):
        filled.add("celebratee")
    if _is_filled_str(form.attendees_age_range):
        filled.add("attendees_age_range")
    if form.attendees:
        filled.add("attendees")
    if _is_filled_str(form.guest_count):
        filled.add("guest_count")
    if _is_filled_str(form.budget):
        filled.add("budget")
    if form.service_type:
        filled.add("service_type")
    if form.start_time is not None or form.end_time is not None:
        filled.add("start_end_time")
    return filled


def active_tag_names(form: ThemeFormInput) -> list[str]:
    """Tag names whose enums go into the LLM context for this request."""
    filled = filled_input_keys(form)
    names: list[str] = []
    seen: set[str] = set()
    for field_key, tag_name in INPUT_TAG_MAP.items():
        if field_key in filled and tag_name not in seen:
            names.append(tag_name)
            seen.add(tag_name)
    for tag_name in ALWAYS_ON_TAGS:
        if tag_name not in seen:
            names.append(tag_name)
            seen.add(tag_name)
    return names


def active_tag_definitions(
    form: ThemeFormInput,
    registry: TagRegistry | None = None,
) -> list[TagDefinition]:
    reg = registry or TagRegistry()
    return [reg.get(name) for name in active_tag_names(form)]


def form_summary_for_prompt(form: ThemeFormInput) -> str:
    """Human-readable answered fields for Haiku (location included but unused for tags)."""
    lines: list[str] = [f"event_type: {form.event_type.strip()}"]
    if _is_filled_str(form.celebratee):
        lines.append(f"celebratee: {form.celebratee.strip()}")
    if _is_filled_str(form.location):
        lines.append(f"location: {form.location.strip()} (not used for filters)")
    if form.event_date is not None:
        lines.append(f"date: {form.event_date.isoformat()}")
    if form.start_time is not None:
        lines.append(f"start_time: {form.start_time.isoformat(timespec='minutes')}")
    if form.end_time is not None:
        lines.append(f"end_time: {form.end_time.isoformat(timespec='minutes')}")
    if form.attendees:
        lines.append(f"attendees: {', '.join(form.attendees)}")
    if _is_filled_str(form.attendees_age_range):
        lines.append(f"attendees_age_range: {form.attendees_age_range.strip()}")
    if _is_filled_str(form.guest_count):
        lines.append(f"guest_count: {form.guest_count.strip()}")
    if form.service_type:
        lines.append(f"service_type: {', '.join(form.service_type)}")
    if _is_filled_str(form.budget):
        lines.append(f"budget: {form.budget.strip()}")
    return "\n".join(lines)
