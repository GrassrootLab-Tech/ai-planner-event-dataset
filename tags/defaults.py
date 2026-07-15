from tags.schema import TagValue
from tags.spec import TagDefinition

TAG_DEFAULTS: dict[str, str] = {
    "content_format": "unspecified",
    "content_category": "unspecified",
    "idea_granularity": "unspecified",
    "event_type": "unspecified",
    "age_group": "unspecified",
    "theme": "not_applicable",
    "theme_family": "not_applicable",
    "vendor_category": "none",
    "procurement_mode": "unspecified",
    "budget_tier": "unspecified",
    "guest_scale": "unspecified",
    "venue_type": "unspecified",
    "setting": "unspecified",
    "milestone": "not_applicable",
    "honoree_interest": "not_applicable",
    "honoree_gender_skew": "unspecified",
    "host_guest_relationship": "unspecified",
    "guest_mix": "unspecified",
    "licensed_ip_flag": "none",
    "color_palette": "not_applicable",
    "aesthetic_style": "unspecified",
    "formality_level": "unspecified",
    "season": "unspecified",
    "effort_level": "unspecified",
    "prep_lead_time": "unspecified",
    "decor_element": "not_applicable",
    "statement_piece": "not_applicable",
    "activity_element": "not_applicable",
    "food_element": "not_applicable",
    "dessert_element": "not_applicable",
    "vendor_cooccurrence": "none",
    "rental_needs": "none",
    "cultural_tradition": "not_applicable",
    "dietary_tags": "not_applicable",
    "holiday_tie_in": "none",
    "time_of_day": "unspecified",
    "weather_dependency": "none",
    "space_requirement": "unspecified",
    "trend_year": "unspecified",
    "beverage_element": "not_applicable",
    "favor_element": "not_applicable",
    "stationery_element": "not_applicable",
    "personalization_element": "not_applicable",
    "music_element": "not_applicable",
    "budget_signal": "none",
    "cuisine_style": "not_applicable",
    "region_relevance": "unspecified",
    "gifting_context": "not_applicable",
}


def fill_missing_tag_defaults(
    values: dict[str, TagValue],
    tags: list[TagDefinition],
) -> dict[str, TagValue]:
    result: dict[str, TagValue] = {}
    for tag in tags:
        if tag.name in values:
            result[tag.name] = values[tag.name]
        elif tag.value_type == "bool":
            raise ValueError(f"Missing required boolean tag: {tag.name}")
        else:
            result[tag.name] = TAG_DEFAULTS[tag.name]
    return result
