"""PartySlate listing URL → API URL conversion and listing JSON → profile URLs."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

PARTYSLATE_BASE = "https://www.partyslate.com"

EVENT_TYPE_SLUGS = frozenset(
    {
        "luncheon",
        "fundraiser",
        "bat-mitzvah",
        "bar-mitzvah",
        "adult-birthday",
        "kids-birthday",
        "1st-birthday",
        "quinceanera",
        "sweet-16",
        "dinner-party",
        "holiday-party",
        "anniversary-party",
        "cocktail-party",
        "baby-shower",
        "graduation-party",
        "retirement-party",
        "corporate-event",
        "corporate-holiday-party",
        "conference-summit",
        "awards-show",
        "fashion-show",
        "product-launch",
        "experiential-activation",
        "pop-up-installation",
        "festival",
        "premiere",
        "employee-event",
        "opening-party",
        "sporting-event",
        "wedding",
        "wedding-shower",
        "rehearsal-dinner",
        "bachelor-bachelorette-party",
        "engagement-party",
        "proposal",
        "sangeet",
        "gala",
    }
)

CATEGORY_SLUGS = frozenset(
    {
        "vendors",
        "planner",
        "photographer",
        "design-decor-floral",
        "caterer",
        "rentals",
        "entertainment",
        "bakery-desserts",
        "invitations-print",
        "videographer",
        "agency",
        "hair-makeup-stylist",
        "av-and-technology",
        "favors-gifts",
        "staffing",
        "parking-transportation",
    }
)


def convert_partyslate_url(input_url: str) -> str:
    """Convert a find-venues / find-vendors page URL into its internal API URL."""
    parsed = urlparse(input_url)
    parts = [p for p in parsed.path.split("/") if p]
    original_params = parse_qsl(parsed.query, keep_blank_values=True)

    if not parts:
        raise ValueError("URL must start with /find-venues or /find-vendors")
    if parts[0] == "find-venues":
        return _build_venues_api_url(parts, original_params)
    if parts[0] == "find-vendors":
        return _build_vendors_api_url(parts, original_params)
    raise ValueError("URL must start with /find-venues or /find-vendors")


def _build_venues_api_url(
    parts: list[str], original_params: list[tuple[str, str]]
) -> str:
    rest = parts[1:]
    near_idx = rest.index("near") if "near" in rest else -1

    event_type = ""
    if near_idx > 0:
        event_type = re.sub(r"-venues$", "", rest[0])

    place_slug = rest[near_idx + 1] if near_idx != -1 and near_idx + 1 < len(rest) else ""

    types_idx = rest.index("types") if "types" in rest else -1
    types = rest[types_idx + 1] if types_idx != -1 and types_idx + 1 < len(rest) else ""

    params: list[tuple[str, str]] = []
    if event_type:
        params.append(("eventType", event_type))
    params.extend(
        [
            ("placeSlug", place_slug),
            ("types", types),
            ("amenities", ""),
            ("beverageOptions", ""),
            ("bounds", ""),
            ("cateringOptions", ""),
            ("diversityClassifications", ""),
        ]
    )
    # Carry over original query (e.g. page=138); later keys override.
    merged = dict(params)
    for key, value in original_params:
        merged[key] = value
    query = urlencode(list(merged.items()))
    return f"{PARTYSLATE_BASE}/api/find-venues?{query}"


def _split_vendor_slug(slug: str) -> tuple[str, str]:
    if slug in EVENT_TYPE_SLUGS:
        return slug, ""
    if slug in CATEGORY_SLUGS:
        return "", slug

    tokens = slug.split("-")
    for i in range(len(tokens) - 1, 0, -1):
        event_type_candidate = "-".join(tokens[:i])
        category_candidate = "-".join(tokens[i:])
        if (
            event_type_candidate in EVENT_TYPE_SLUGS
            and category_candidate in CATEGORY_SLUGS
        ):
            return event_type_candidate, category_candidate

    fallback = slug.split("-")
    category = fallback.pop() if fallback else ""
    return "-".join(fallback), category


def _build_vendors_api_url(
    parts: list[str], original_params: list[tuple[str, str]]
) -> str:
    rest = parts[1:]
    event_type = ""
    category = ""

    if rest and rest[0] != "area":
        event_type, category = _split_vendor_slug(rest[0])

    # Generic catch-all: API omits category when it is "vendors".
    if category == "vendors":
        category = ""

    area_idx = rest.index("area") if "area" in rest else -1
    location = (
        rest[area_idx + 1] if area_idx != -1 and area_idx + 1 < len(rest) else ""
    )

    params: list[tuple[str, str]] = []
    if category:
        params.append(("category", category))
    if location:
        params.append(("location", location))
    if event_type:
        params.append(("eventType", event_type))

    merged = dict(params)
    for key, value in original_params:
        merged[key] = value
    query = urlencode(list(merged.items()))
    return f"{PARTYSLATE_BASE}/api/find-vendors.json?{query}"


def profile_kind(api_url: str) -> str:
    path = urlparse(api_url).path.lower()
    if "find-venues" in path:
        return "venues"
    return "vendors"


def extract_json_payload(hasdata_body: dict[str, Any]) -> dict[str, Any] | None:
    """Unwrap PartySlate listing JSON from a HasData scrape body."""
    candidates: list[str] = []
    for key in ("text", "content", "html", "markdown"):
        val = hasdata_body.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append(val.strip())

    if not candidates and isinstance(hasdata_body, dict):
        if any(
            k in hasdata_body
            for k in ("vendors", "venues", "companies", "results", "data")
        ):
            return hasdata_body

    for raw in candidates:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        pre = re.search(r"<pre[^>]*>(.*?)</pre>", raw, flags=re.I | re.S)
        if pre:
            try:
                parsed = json.loads(pre.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        for match in re.finditer(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw):
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    return None


def listing_profile_urls(payload: dict[str, Any], kind: str) -> list[str]:
    """Build profile URLs from top-level vendors[] / venues[] slugs only."""
    key = "venues" if kind == "venues" else "vendors"
    items = payload.get(key) or []
    urls: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if not isinstance(slug, str):
            continue
        slug = slug.strip()
        if not slug or "/" in slug or slug in seen:
            continue
        seen.add(slug)
        urls.append(f"{PARTYSLATE_BASE}/{kind}/{slug}")
    return urls


def is_partyslate_host(page_url: str) -> bool:
    host = urlparse(page_url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host == "partyslate.com" or host.endswith(".partyslate.com")


def is_partyslate_venue_profile(page_url: str) -> bool:
    path = urlparse(page_url).path.lower()
    return path.startswith("/venues/")
