from tags.schema import TagValue

METADATA_TAG_ORDER: tuple[str, ...] = (
    "content_format",
    "content_category",
    "idea_granularity",
    "event_type",
    "age_group",
    "theme",
    "theme_family",
    "vendor_category",
    "procurement_mode",
    "budget_tier",
    "guest_scale",
    "venue_type",
    "setting",
    "kid_safe_flag",
    "milestone",
    "honoree_interest",
    "honoree_gender_skew",
    "host_guest_relationship",
    "guest_mix",
    "licensed_ip_flag",
    "color_palette",
    "aesthetic_style",
    "formality_level",
    "season",
    "effort_level",
    "prep_lead_time",
    "decor_element",
    "statement_piece",
    "activity_element",
    "food_element",
    "dessert_element",
    "photo_moment_flag",
    "vendor_cooccurrence",
    "rental_needs",
    "cultural_tradition",
    "dietary_tags",
    "holiday_tie_in",
    "time_of_day",
    "weather_dependency",
    "space_requirement",
    "trend_year",
    "beverage_element",
    "favor_element",
    "stationery_element",
    "personalization_element",
    "music_element",
    "budget_signal",
    "cuisine_style",
    "region_relevance",
    "gifting_context",
)


SCALAR_LIST_VALUES = frozenset({"not_applicable", "none", "any", "unspecified"})


def normalize_metadata_tags(tags: dict[str, TagValue]) -> dict[str, TagValue]:
    result = dict(tags)

    licensed_ip = result.get("licensed_ip_flag")
    if isinstance(licensed_ip, list):
        result["licensed_ip_flag"] = {"ip_names": licensed_ip} if licensed_ip else False
    elif licensed_ip is True:
        result["licensed_ip_flag"] = {"ip_names": []}
    elif licensed_ip is False:
        result["licensed_ip_flag"] = False

    for key, value in result.items():
        if key == "licensed_ip_flag":
            continue
        if (
            isinstance(value, list)
            and len(value) == 1
            and value[0] in SCALAR_LIST_VALUES
        ):
            result[key] = value[0]

    return result


def order_metadata_tags(tags: dict[str, TagValue]) -> dict[str, TagValue]:
    tags = normalize_metadata_tags(tags)
    ordered: dict[str, TagValue] = {}
    for key in METADATA_TAG_ORDER:
        if key in tags:
            ordered[key] = tags[key]
    for key, value in tags.items():
        if key not in ordered:
            ordered[key] = value
    return ordered
