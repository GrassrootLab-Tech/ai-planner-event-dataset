from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from vendor_profiles.models.vendor_profile import (
    Category,
    Location,
    PortfolioFile,
    Price,
    Review,
    ServiceArea,
    VendorEvent,
    VendorProfile,
    YearsInBusiness,
)
from vendor_profiles.parsers.base import VendorProfileParser
from vendor_profiles.parsers.text import (
    absolute_url,
    clean_or_none,
    parse_date,
    parse_money,
    section,
    strip_media_variant,
    unescape,
)

_SENTINELS = frozenset(
    {
        "view all",
        "load more",
        "see all photos",
        "request free quote",
        "sort:",
        "recommendedratings: high to lowratings: low to highdate: newest to oldestdate: oldest to newest",
    }
)

# The Bash joins business name and type with a non-breaking space:
#   # Obadiah Parker\xa0Singer from Denver, CO
_H1_RE = re.compile(
    r"^#\s+(?P<name>.+?)\xa0(?P<subcat>.+?)\s+from\s+(?P<city>.+?),\s*(?P<st>[A-Z]{2})\s*$",
    re.MULTILINE,
)
_TRAVEL_RE = re.compile(
    r"Will travel up to\s+(\d+)\s+miles",
    re.IGNORECASE,
)
_AVG_RATING_RE = re.compile(
    r"Avg\s+\*?\*?([\d.]+)\*?\*?",
    re.IGNORECASE,
)
_BOOKINGS_RE = re.compile(
    r"\*?\*?(\d+)\*?\*?\s+Verified Bookings",
    re.IGNORECASE,
)
_MEMBER_SINCE_RE = re.compile(
    r"Member Since\s+\*?\*?(\d{4})\*?\*?",
    re.IGNORECASE,
)
_STARTING_AT_RE = re.compile(
    r"Starting at\s+\*?\*?(?P<body>\$[\d,]+(?:\.\d+)?(?:\s+per\s+\w+)?)\*?\*?",
    re.IGNORECASE,
)
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)",
)
_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)",
)
_REVIEW_BLOCK_RE = re.compile(
    r"Review by\s+(?P<name>.+?)\n+"
    r"(?P<meta>[^\n]+)\n+"
    r"(?P<body>.*?)(?=\nReview by\s+|\nLoad More|\n## |\Z)",
    re.DOTALL | re.IGNORECASE,
)
_REVIEW_META_RE = re.compile(
    r"Reviewed on\s+(?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_EVENT_PAIR_RE = re.compile(
    r"(?P<header>(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},\s+\d{4}"
    r"\s*[•·]\s*.+?)\n+"
    r"(?P<details>[A-Za-z]{3}\s*[•·].+?)(?=\n\n|\n(?:January|February|March|"
    r"April|May|June|July|August|September|October|November|December)|\nLoad More|\Z)",
    re.DOTALL,
)
_BREADCRUMB_ITEM_RE = re.compile(
    r"^\d+\.\s+(?:\[(?P<link>[^\]]+)\]\([^)]+\)|(?P<plain>.+))\s*$",
    re.MULTILINE,
)
_US_STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}
_STATE_CODE_TO_NAME = {code: name.title() for name, code in _US_STATE_NAMES.items()}


class TheBashProfileParser(VendorProfileParser):
    source_host = "thebash.com"

    def parse(self, page_url: str, markdown: str) -> VendorProfile:
        body = self._profile_body(markdown)
        breadcrumbs = self._parse_breadcrumbs(body)
        h1 = self._parse_h1(body)

        business_name = breadcrumbs.get("name") or (h1 or {}).get("name")
        business_name = clean_or_none(business_name)
        if not business_name:
            raise ValueError("business_name is required")

        location, service_area = self._parse_location(body, breadcrumbs, h1)
        prices = self._parse_prices(body)
        portfolio, profile_picture = self._parse_media(body)
        reviews = self._parse_reviews(body)
        upcoming = self._parse_events(section(body, "Upcoming Events", level=3))
        past = self._parse_events(section(body, "Past Events", level=3))
        similar = self._parse_similar(page_url, body)
        badges = self._parse_badges(body)
        services = self._parse_services(body)
        categories = self._parse_categories(breadcrumbs, h1, services)
        description = self._parse_description(body)
        song_list = self._parse_song_list(body)

        return VendorProfile(
            business_name=business_name,
            slug=self._slug_from_url(page_url),
            categories=categories,
            services_provided=services,
            description=description,
            song_list=song_list,
            location=location,
            service_area=service_area,
            prices=prices,
            rating_average=self._parse_rating(body),
            times_booked=self._parse_bookings(body),
            years_in_business=self._parse_member_since(body),
            verified_badges=badges,
            reviews=reviews,
            portfolio_files=portfolio,
            profile_picture=profile_picture,
            past_events=past,
            upcoming_events=upcoming,
            similar_vendors=similar,
        )

    @staticmethod
    def _profile_body(markdown: str) -> str:
        """Prefer content after <!--THE END--> (nav chrome ends there)."""
        marker = "<!--THE END-->"
        idx = markdown.find(marker)
        if idx >= 0:
            return markdown[idx + len(marker) :]
        return markdown

    @staticmethod
    def _slug_from_url(page_url: str) -> str | None:
        path = urlparse(page_url).path.rstrip("/")
        if not path:
            return None
        return path.rsplit("/", 1)[-1] or None

    @staticmethod
    def _none_if_empty(items: list | None):
        if not items:
            return None
        return items

    def _parse_breadcrumbs(self, body: str) -> dict[str, str | None]:
        """Parse the numbered breadcrumb list that precedes the H1.

        Example:
          1. [DJs](/services/dj)
          3. [Colorado DJs](/search/dj-colorado)
          5. [Denver, CO DJs](/search/dj-denver-co)
          7. DJ/Guitarist/Bagpiper- Michael Lancaster
        """
        # Take content from start up to first H1 / first image / See All Photos
        header_end = re.search(
            r"^(?:#\s|!\[|See All Photos)",
            body,
            re.MULTILINE,
        )
        header = body[: header_end.start()] if header_end else body[:2000]

        items: list[str] = []
        for match in _BREADCRUMB_ITEM_RE.finditer(header):
            raw = match.group("link") or match.group("plain") or ""
            text = unescape(raw)
            if text and text != "/":
                items.append(text)

        if not items:
            return {"name": None, "service": None, "state": None, "city_label": None}

        name = items[-1]
        service = items[0] if items else None
        state = None
        city_label = None
        for item in items[1:-1]:
            # "Colorado DJs" / "Denver, CO DJs"
            if "," in item:
                city_label = item
            else:
                # Strip trailing service word(s) to get state name
                state = item

        # Derive state name from "Colorado DJs" → "Colorado"
        if state and service:
            svc = service.rstrip("s")  # DJs → DJ
            for suffix in (f" {service}", f" {svc}", f" {service}s"):
                if state.lower().endswith(suffix.lower()):
                    state = state[: -len(suffix)].strip()
                    break
            # Also try stripping pluralized service from end
            parts = state.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].lower().rstrip("s") == svc.lower().rstrip(
                "s"
            ):
                state = parts[0]

        return {
            "name": name,
            "service": service,
            "state": state,
            "city_label": city_label,
        }

    def _parse_h1(self, body: str) -> dict[str, str] | None:
        match = _H1_RE.search(body)
        if match:
            return {
                "name": unescape(match.group("name")),
                "subcat": unescape(match.group("subcat")),
                "city": unescape(match.group("city")),
                "st": match.group("st"),
            }

        # Fallback: nbsp already normalized away — split on " from "
        loose = re.search(r"^#\s+(?P<rest>.+)$", body, re.MULTILINE)
        if not loose:
            return None
        rest = unescape(loose.group("rest"))
        from_match = re.search(
            r"^(?P<head>.+?)\s+from\s+(?P<city>.+?),\s*(?P<st>[A-Z]{2})\s*$",
            rest,
        )
        if not from_match:
            return {"name": rest, "subcat": "", "city": "", "st": ""}
        head = from_match.group("head").strip()
        # Last whitespace-delimited token is the type (DJ, Photographer, Singer)
        parts = head.rsplit(" ", 1)
        if len(parts) == 2:
            name, subcat = parts[0].strip(), parts[1].strip()
        else:
            name, subcat = head, ""
        return {
            "name": name,
            "subcat": subcat,
            "city": from_match.group("city").strip(),
            "st": from_match.group("st").strip(),
        }

    @staticmethod
    def _singularize_primary(primary: str) -> str:
        # "DJs" → "DJ", "Photographers" → "Photographer", "Singers" → "Singer"
        if primary.endswith("ies"):
            return primary[:-3] + "y"
        if primary.endswith("s") and not primary.endswith("ss"):
            return primary[:-1]
        return primary

    def _parse_categories(
        self,
        breadcrumbs: dict[str, str | None],
        h1: dict[str, str] | None,
        services: list[str] | None,
    ) -> list[Category] | None:
        service = breadcrumbs.get("service")
        h1_subcat = clean_or_none((h1 or {}).get("subcat") or "")
        if not service and not h1_subcat and not services:
            return None
        primary_raw = unescape(service or h1_subcat or (services or [""])[0])
        primary = self._singularize_primary(primary_raw)

        # Services chips are sub-categories; include H1 type if not already listed.
        subcats: list[str] = []
        seen: set[str] = set()
        for label in services or []:
            cleaned = clean_or_none(label)
            if not cleaned or cleaned.lower() in seen:
                continue
            seen.add(cleaned.lower())
            subcats.append(cleaned)
        if h1_subcat and h1_subcat.lower() not in seen:
            subcats.insert(0, h1_subcat)
        if not subcats:
            subcats.append(primary)

        return [
            Category(primary_category=primary, sub_category=sub)
            for sub in subcats
        ]

    def _parse_location(
        self,
        body: str,
        breadcrumbs: dict[str, str | None],
        h1: dict[str, str] | None,
    ) -> tuple[Location | None, ServiceArea | None]:
        city = (h1 or {}).get("city") or None
        state_code = (h1 or {}).get("st") or None
        state_name = breadcrumbs.get("state")

        if state_name:
            state_name = unescape(state_name)
            # "Colorado DJs" residual cleanup
            for svc in filter(None, [breadcrumbs.get("service")]):
                if state_name.lower().endswith(svc.lower()):
                    state_name = state_name[: -len(svc)].strip()
                svc_sing = svc.rstrip("s")
                if state_name.lower().endswith(svc_sing.lower()):
                    state_name = state_name[: -len(svc_sing)].strip()

        if not state_name and state_code:
            state_name = _STATE_CODE_TO_NAME.get(state_code)

        if not state_code and state_name:
            state_code = _US_STATE_NAMES.get(state_name.lower())

        raw_location = None
        if city and state_code:
            raw_location = f"{city}, {state_code}"
        elif city and state_name:
            raw_location = f"{city}, {state_name}"

        location = None
        if city or state_name or raw_location:
            location = Location(
                city=city or None,
                state=state_name or None,
                country="US",
                raw_location=raw_location,
            )

        travel_radius = None
        travel_match = _TRAVEL_RE.search(body)
        if travel_match:
            travel_radius = int(travel_match.group(1))

        service_area = None
        if city or state_name or state_code or travel_radius is not None:
            service_area = ServiceArea(
                city=city or None,
                state=state_name or None,
                state_code=state_code or None,
                travel_radius=travel_radius,
            )

        return location, service_area

    def _parse_description(self, body: str) -> str | None:
        about = section(body, "About Vendor")
        if not about:
            return None
        lines: list[str] = []
        for line in about.splitlines():
            stripped = line.strip()
            if not stripped:
                if lines:
                    lines.append("")
                continue
            lower = unescape(stripped).lower()
            if lower in _SENTINELS:
                break
            if lower.startswith("learn more about this vendor"):
                continue
            lines.append(stripped)
        text = unescape("\n".join(lines).strip())
        # Collapse excess blank lines
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text or None

    def _parse_services(self, body: str) -> list[str] | None:
        services_md = section(body, "Services")
        if not services_md:
            return None
        labels: list[str] = []
        seen: set[str] = set()
        for match in _LINK_RE.finditer(services_md):
            label = unescape(match.group("label"))
            if not label or label.lower() in _SENTINELS:
                continue
            if label.lower().startswith("view a list"):
                continue
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
        return self._none_if_empty(labels)

    def _parse_song_list(self, body: str) -> list[str] | None:
        """Parse ## Song List bullets like '- Rolling in the Deep | Adele'."""
        songs_md = section(body, "Song List")
        if not songs_md:
            return None
        songs: list[str] = []
        seen: set[str] = set()
        for line in songs_md.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = unescape(stripped).lower()
            if lower in _SENTINELS:
                break
            if lower.startswith("get a feel for the songs"):
                continue
            if not stripped.startswith(("- ", "* ")):
                continue
            entry = clean_or_none(stripped[2:])
            if not entry or entry.lower() in seen:
                continue
            seen.add(entry.lower())
            songs.append(entry)
        return self._none_if_empty(songs)

    def _parse_prices(self, body: str) -> list[Price] | None:
        match = _STARTING_AT_RE.search(body)
        if not match:
            return None
        parsed = parse_money(match.group("body"))
        if not parsed:
            return None
        amount, per = parsed
        return [Price(amount=amount, per=per)]

    def _parse_rating(self, body: str) -> float | None:
        # Prefer the stats bullet near the top (before About Vendor)
        header = body.split("## About Vendor", 1)[0]
        match = _AVG_RATING_RE.search(header)
        if not match:
            match = _AVG_RATING_RE.search(body)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        if value < 0 or value > 5:
            return None
        return value

    def _parse_bookings(self, body: str) -> int | None:
        match = _BOOKINGS_RE.search(body)
        if not match:
            return None
        return int(match.group(1))

    def _parse_member_since(self, body: str) -> YearsInBusiness | None:
        match = _MEMBER_SINCE_RE.search(body)
        if not match:
            return None
        return YearsInBusiness(start_year=int(match.group(1)))

    def _parse_badges(self, body: str) -> list[str] | None:
        header = body.split("## About Vendor", 1)[0]
        badges: list[str] = []
        for line in header.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            item = unescape(stripped[2:])
            if not item:
                continue
            lower = item.lower()
            if lower.startswith("avg ") or "verified bookings" in lower:
                continue
            if lower.startswith("member since") or lower.startswith("starting at"):
                continue
            badges.append(item)
        return self._none_if_empty(badges)

    def _parse_reviews(self, body: str) -> list[Review] | None:
        reviews_md = section(body, "Reviews")
        if not reviews_md:
            return None
        reviews: list[Review] = []
        for match in _REVIEW_BLOCK_RE.finditer(reviews_md):
            name = clean_or_none(match.group("name"))
            meta = unescape(match.group("meta") or "")
            body_text = match.group("body") or ""

            # Drop vendor reply blocks (Name: reply) and sentinels
            reply_lines: list[str] = []
            for line in body_text.splitlines():
                stripped = line.strip()
                if not stripped:
                    if reply_lines:
                        reply_lines.append("")
                    continue
                lower = unescape(stripped).lower()
                if lower in _SENTINELS or lower == "view all":
                    break
                # Vendor reply: line ending with ":" that looks like a business name,
                # or a short label followed by reply text on next lines after "VIEW ALL"
                if stripped.endswith(":") and len(stripped) < 80:
                    break
                reply_lines.append(stripped)

            text = clean_or_none("\n".join(reply_lines))
            date_match = _REVIEW_META_RE.search(meta)
            review_date = parse_date(date_match.group("date")) if date_match else None
            reviews.append(
                Review(
                    reviewer_name=name,
                    review_date=review_date,
                    text=text,
                )
            )
        return self._none_if_empty(reviews)

    def _parse_events(self, events_md: str) -> list[VendorEvent] | None:
        if not events_md:
            return None
        events: list[VendorEvent] = []
        for match in _EVENT_PAIR_RE.finditer(events_md):
            header = unescape(match.group("header"))
            details = unescape(match.group("details"))

            # "September 18, 2026 • Wedding"
            parts = re.split(r"\s*[•·]\s*", header, maxsplit=1)
            event_date = parse_date(parts[0]) if parts else None
            event_type = clean_or_none(parts[1]) if len(parts) > 1 else None

            # "Fri • 4:00 PM - 10:00 PM • Rifle, CO"
            detail_parts = re.split(r"\s*[•·]\s*", details)
            location = None
            description = None
            if len(detail_parts) >= 3:
                # day, time range, location
                description = clean_or_none(
                    f"{detail_parts[0]} {detail_parts[1]}".strip()
                )
                location = clean_or_none(detail_parts[-1])
            elif len(detail_parts) == 2:
                description = clean_or_none(detail_parts[0])
                location = clean_or_none(detail_parts[1])
            else:
                description = clean_or_none(details)

            events.append(
                VendorEvent(
                    event_date=event_date,
                    event_type=event_type,
                    location=location,
                    description=description,
                )
            )
        return self._none_if_empty(events)

    def _parse_media(
        self, body: str
    ) -> tuple[list[PortfolioFile] | None, str | None]:
        # Only take images before About Vendor (hero + gallery)
        header = body.split("## About Vendor", 1)[0]
        files: list[PortfolioFile] = []
        seen: set[str] = set()
        profile_picture: str | None = None

        for match in _IMAGE_RE.finditer(header):
            alt = unescape(match.group("alt") or "")
            raw_url = match.group("url").strip()
            alt_lower = alt.lower()
            if "logo" in alt_lower or "badge" in alt_lower:
                continue
            if "the bash" in alt_lower and "hero" not in alt_lower:
                continue
            url = absolute_url(raw_url)
            if not url:
                continue
            if "media-api.xogrp.com" not in url and "cloudfront.net" in url:
                # Brand CDN assets, skip
                continue
            if "media-api.xogrp.com" not in url:
                continue
            canonical = strip_media_variant(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            files.append(PortfolioFile(type="image", url=canonical))
            if profile_picture is None and "hero main" in alt.lower():
                profile_picture = canonical

        if profile_picture is None and files:
            profile_picture = files[0].url

        return self._none_if_empty(files), profile_picture

    def _parse_similar(self, page_url: str, body: str) -> list[str] | None:
        related = section(body, "Related Profiles")
        if not related:
            return None
        urls: list[str] = []
        seen: set[str] = set()
        for match in _LINK_RE.finditer(related):
            href = (match.group("url") or "").strip()
            if not href or href.startswith("#"):
                continue
            absolute = absolute_url(href) or urljoin(page_url, href)
            if not absolute.startswith("http"):
                continue
            # Drop share widgets / empty targets
            if "facebook.com/sharer" in absolute or "twitter.com" in absolute:
                continue
            cleaned = absolute.rstrip("/")
            if cleaned in seen:
                continue
            seen.add(cleaned)
            urls.append(cleaned)
        return self._none_if_empty(urls)
