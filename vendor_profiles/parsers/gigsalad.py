from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

from vendor_profiles.models.vendor_profile import (
    Category,
    GigLength,
    Highlight,
    Location,
    LogisticDetails,
    PortfolioFile,
    Price,
    PriceRange,
    Review,
    ServiceArea,
    SetupRequirement,
    TeamMember,
    VendorEvent,
    VendorProfile,
)
from vendor_profiles.parsers.base import VendorProfileParser
from vendor_profiles.parsers.text import (
    absolute_url,
    clean_or_none,
    paragraphs,
    parse_date,
    parse_money,
    section,
    strip_md_escapes,
    unescape,
)
from vendor_profiles.parsers.us_states import STATE_CODE_TO_NAME, country_for_us_state

_SENTINELS = frozenset(
    {
        "read more",
        "show more",
        "show less",
        "show more show less",
        "write a review",
        "show all reviews",
        "save to my favorites",
        "get a free quick quote",
        "get a free quote",
    }
)

_H1_RE = re.compile(r"^#\s+(?P<name>.+)\s*$", re.MULTILINE)
_RATING_RE = re.compile(r"^([\d.]+)\s+\((\d+)\)\s*$", re.MULTILINE)
_BOOKINGS_RE = re.compile(
    r"^(\d+)\s+Verified bookings\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RESPONSE_RE = re.compile(
    r"^(Responds in .+)$",
    re.IGNORECASE | re.MULTILINE,
)
_CITY_STATE_RE = re.compile(
    r"^([A-Za-z][A-Za-z .'-]+),\s*([A-Z]{2})\s*$",
    re.MULTILINE,
)
_TRAVEL_MILES_RE = re.compile(
    r"Travels(?:\s+up\s+to)?\s+(\d+)\s*mi(?:les?)?",
    re.IGNORECASE,
)
_TRAVEL_ANY_RE = re.compile(r"^Travels any\s*$", re.IGNORECASE | re.MULTILINE)
_TRAVEL_HRS_RE = re.compile(
    r"Travels\s+([\d.]+)\s+hrs?",
    re.IGNORECASE,
)
# Header chip / Services offered category links (hyphenated path segments).
_CATEGORY_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<url>https?://(?:www\.)?gigsalad\.com/"
    r"(?P<primary>[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)/"
    r"(?P<sub>[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)"
    r"(?:/[A-Z]{2}/[^)\s]*)?)\)",
)
_PRICE_AND_UP_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:&(?:amp;)?\s*)?(?:and\s+)?up",
    re.IGNORECASE,
)
_PRICE_RANGE_SPAN_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*[-–—]\s*\$\s*([\d,]+(?:\.\d+)?)",
)
_CTA_LINE_RE = re.compile(
    r"^(?:Save\s+)?\[Get a free quote\]|^\[\]\(https?://(?:www\.)?gigsalad\.com/?\)$",
    re.IGNORECASE,
)
_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)")
_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)")
_YOUTUBE_THUMB_RE = re.compile(
    r"https?://img\.youtube\.com/vi/(?P<id>[A-Za-z0-9_-]+)/",
    re.IGNORECASE,
)
_PRICE_RANGE_RE = re.compile(
    r"^Price range:\s*(?P<body>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_LANGUAGES_RE = re.compile(
    r"^Languages:\s*(?P<body>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_GIG_LENGTH_RE = re.compile(
    r"^Gig length:\s*(?P<body>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_GIG_RANGE_RE = re.compile(
    r"(\d+)\s*-\s*(\d+)\s*minutes?",
    re.IGNORECASE,
)
_INSURANCE_RE = re.compile(
    r"^Insurance:\s*(?P<body>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_UNIONS_RE = re.compile(
    r"^Unions:\s*(?P<body>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_REVIEW_SPLIT_RE = re.compile(
    r"!\[Small thumbnail image for reviewer\s+(?P<name>[^\]]+)\]\([^)]+\)",
    re.IGNORECASE,
)
_REVIEW_TITLE_RE = re.compile(
    r"###\s+\[(?P<title>[^\]]+)\]\([^)]+/review/\d+\)",
    re.IGNORECASE,
)
_MONTH_HEADER_RE = re.compile(
    r"^######\s+(?P<month>January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+(?P<year>\d{4})\s*$",
    re.MULTILINE,
)
_EVENT_DAY_RE = re.compile(r"^###\s+(?P<day>\d{1,2})\s*$", re.MULTILINE)
_HEADER_BADGES = frozenset({"top performer", "featured"})
_FOOTER_START = "With us, **planners have the confidence"


class GigSaladProfileParser(VendorProfileParser):
    source_host = "gigsalad.com"

    def parse(
        self,
        page_url: str,
        markdown: str,
        *,
        html: str | None = None,
    ) -> VendorProfile:
        body = self._profile_body(markdown)
        business_name = self._parse_business_name(body)
        if not business_name:
            raise ValueError("business_name is required")

        header = self._header_block(body)
        location, service_area = self._parse_location(header)
        services, categories = self._parse_services_and_categories(body, header)
        portfolio, profile_picture = self._parse_media(body, business_name)
        reviews = self._parse_reviews(body)
        upcoming = self._parse_events(
            self._section_loose(body, "Upcoming booked events", level=3)
        )
        past = self._parse_events(
            self._section_loose(body, "Past booked events", level=3)
        )
        glance = self._parse_at_a_glance(body)
        reasons = self._parse_reasons(body)
        booking_notes = self._parse_booking_notes(body)
        setup_requirements = self._parse_setup_requirements(body)
        song_list = self._parse_song_list(body)
        influences = self._parse_influences(body)
        team = self._parse_team(body)
        logistic_details = (
            LogisticDetails(team_size=len(team)) if team else None
        )

        return VendorProfile(
            business_name=business_name,
            slug=self.slug_from_url(page_url),
            booking_url=self._booking_url(page_url),
            categories=categories,
            services_provided=services,
            description=self._parse_overview(body),
            about=self._parse_about(body),
            reasons_to_book_me=reasons,
            booking_notes=booking_notes,
            languages=glance.get("languages"),
            song_list=song_list,
            gig_length=glance.get("gig_length"),
            unions=glance.get("unions"),
            influences_and_inspiration=influences,
            team=team,
            location=location,
            service_area=service_area,
            prices=glance.get("prices"),
            price_range=glance.get("price_range"),
            rating_average=self._parse_rating(header),
            times_booked=self._parse_bookings(header),
            response_time=self._parse_response_time(header),
            verified_badges=self._parse_badges(header),
            insurance_info=glance.get("insurance_info"),
            reviews=reviews,
            portfolio_files=portfolio,
            profile_picture=profile_picture,
            past_events=past,
            upcoming_events=upcoming,
            setup_requirements=setup_requirements,
            logistic_details=logistic_details,
        )

    @staticmethod
    def _profile_body(markdown: str) -> str:
        start_markers = ("← Back to", "[← Back to")
        start = -1
        for marker in start_markers:
            idx = markdown.find(marker)
            if idx >= 0:
                start = idx
                break
        if start < 0:
            h1 = re.search(r"^#\s+", markdown, re.MULTILINE)
            start = h1.start() if h1 else 0

        end = markdown.find(_FOOTER_START, start)
        if end < 0:
            end = len(markdown)
        return markdown[start:end].strip()

    @staticmethod
    def slug_from_url(page_url: str) -> str | None:
        path = urlparse(page_url).path.rstrip("/")
        if not path:
            return None
        return path.rsplit("/", 1)[-1] or None

    @staticmethod
    def _booking_url(page_url: str) -> str | None:
        base = page_url.rstrip("/")
        if not base:
            return None
        if base.endswith("/contact"):
            return base
        return f"{base}/contact"

    @staticmethod
    def _none_if_empty(items: list | None):
        if not items:
            return None
        return items

    @staticmethod
    def _drop_sentinels(text: str) -> str:
        lines: list[str] = []
        for line in text.splitlines():
            stripped = unescape(line).strip()
            lower = stripped.lower()
            if lower in _SENTINELS or lower.startswith("« previous"):
                continue
            if stripped == "* * *" or stripped == "***":
                continue
            if _CTA_LINE_RE.match(stripped):
                break
            lines.append(line)
        return "\n".join(lines).strip()

    def _section_loose(self, markdown: str, heading: str, *, level: int) -> str:
        """Like section(), but do not stop on ``### <digits>`` day headings."""
        pattern = re.compile(
            rf"^#{{{level}}}\s+{re.escape(heading)}\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        match = pattern.search(markdown)
        if not match:
            return ""
        start = match.end()
        next_heading = re.compile(
            rf"^#{{1,{level}}}\s+(?!\d+\s*$)(\S.+)$",
            re.MULTILINE,
        )
        next_match = next_heading.search(markdown, start)
        end = next_match.start() if next_match else len(markdown)
        return markdown[start:end].strip()

    def _parse_business_name(self, body: str) -> str | None:
        match = _H1_RE.search(body)
        if not match:
            return None
        return clean_or_none(match.group("name"))

    def _header_block(self, body: str) -> str:
        """Hero content until gallery / overview / reviews (includes pre-H1 badges)."""
        end_match = re.search(
            r"^(!\[Gallery photo|^## Overview|^## Reviews|"
            r"!\[Promotional video)",
            body,
            re.MULTILINE,
        )
        end = end_match.start() if end_match else min(len(body), 3500)
        return body[:end]

    @staticmethod
    def _parse_price_text(
        text: str,
    ) -> tuple[list[Price] | None, PriceRange | None]:
        """Parse GigSalad price strings into prices (lower amount) + price_range."""
        cleaned = unescape(text or "").strip()
        if not cleaned or "contact for rates" in cleaned.lower():
            return None, None

        span = _PRICE_RANGE_SPAN_RE.search(cleaned)
        if span:
            lo = float(span.group(1).replace(",", ""))
            hi = float(span.group(2).replace(",", ""))
            return (
                [Price(amount=lo, per="event")],
                PriceRange(min_price=lo, max_price=hi),
            )

        and_up = _PRICE_AND_UP_RE.search(cleaned)
        if and_up:
            amount = float(and_up.group(1).replace(",", ""))
            return (
                [Price(amount=amount, per="event")],
                PriceRange(min_price=amount),
            )

        money = parse_money(cleaned)
        if not money:
            return None, None
        amount, per = money
        return [Price(amount=amount, per=per)], PriceRange(min_price=amount)

    def _parse_rating(self, header: str) -> float | None:
        match = _RATING_RE.search(header)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        if value < 0 or value > 5:
            return None
        return value

    def _parse_bookings(self, header: str) -> int | None:
        match = _BOOKINGS_RE.search(header)
        if not match:
            return None
        return int(match.group(1))

    def _parse_response_time(self, header: str) -> str | None:
        match = _RESPONSE_RE.search(header)
        if not match:
            return None
        return clean_or_none(match.group(1))

    def _parse_badges(self, header: str) -> list[str] | None:
        badges: list[str] = []
        seen: set[str] = set()
        for line in header.splitlines():
            item = unescape(line).strip()
            if not item:
                continue
            lower = item.lower()
            if lower in _HEADER_BADGES and lower not in seen:
                seen.add(lower)
                badges.append(item)
        return self._none_if_empty(badges)

    def _parse_location(
        self, header: str
    ) -> tuple[Location | None, ServiceArea | None]:
        city = None
        state_code = None
        for match in _CITY_STATE_RE.finditer(header):
            city = clean_or_none(match.group(1))
            state_code = match.group(2)
            break

        state_name = STATE_CODE_TO_NAME.get(state_code) if state_code else None
        raw_location = f"{city}, {state_code}" if city and state_code else None

        location = None
        if city or state_name or raw_location:
            location = Location(
                city=city,
                state=state_name,
                country=country_for_us_state(
                    state=state_name, state_code=state_code
                ),
                raw_location=raw_location,
            )

        travel_radius = None
        can_travel_nationwide = None
        miles = _TRAVEL_MILES_RE.search(header)
        if miles:
            travel_radius = f"{miles.group(1)} miles"
        elif _TRAVEL_ANY_RE.search(header):
            can_travel_nationwide = True
        else:
            hrs = _TRAVEL_HRS_RE.search(header)
            if hrs:
                travel_radius = f"{hrs.group(1)} hours"

        service_area = None
        if (
            city
            or state_name
            or state_code
            or travel_radius is not None
            or can_travel_nationwide
        ):
            service_area = ServiceArea(
                city=city,
                state=state_name,
                state_code=state_code,
                travel_radius=travel_radius,
                can_travel_nationwide=can_travel_nationwide,
            )
        return location, service_area

    def _parse_services_and_categories(
        self, body: str, header: str
    ) -> tuple[list[str] | None, list[Category] | None]:
        """Primary = header chip label; sub = first Services offered item."""
        # Header chip (person icon) — first matching category link only
        primary: str | None = None
        for match in _CATEGORY_LINK_RE.finditer(header):
            primary = clean_or_none(match.group("label"))
            if primary:
                break

        services: list[str] = []
        seen: set[str] = set()
        services_md = section(body, "Services offered", level=3)
        if services_md:
            for match in _CATEGORY_LINK_RE.finditer(services_md):
                label = clean_or_none(match.group("label"))
                if not label:
                    continue
                key = label.lower()
                if "frequently asked questions" in key:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                services.append(label)

        # If services section empty, fall back to header chip as sole service
        if not services and primary:
            services = [primary]

        categories = None
        if primary:
            sub = services[0] if services else primary
            categories = [
                Category(primary_category=primary, sub_category=sub)
            ]

        return self._none_if_empty(services), categories

    def _parse_media(
        self, body: str, business_name: str
    ) -> tuple[list[PortfolioFile] | None, str | None]:
        files: list[PortfolioFile] = []
        seen: set[str] = set()
        profile_picture: str | None = None
        name_lower = business_name.lower()

        for match in _IMAGE_RE.finditer(body):
            alt = unescape(match.group("alt") or "")
            raw_url = match.group("url").strip()
            url = absolute_url(raw_url)
            if not url:
                continue
            alt_lower = alt.lower()

            if "initial-icons" in url or "event_planners" in url:
                continue

            # Avatar / profile picture
            if (
                profile_picture is None
                and "_fullsize" in url
                and alt_lower == name_lower
            ):
                profile_picture = url
                continue

            if alt_lower.startswith("gallery photo"):
                if url in seen:
                    continue
                seen.add(url)
                files.append(PortfolioFile(type="image", url=url))
                continue

            if alt_lower.startswith("promotional video thumbnail"):
                yt = _YOUTUBE_THUMB_RE.search(url)
                if yt:
                    video_url = f"https://www.youtube.com/watch?v={yt.group('id')}"
                else:
                    video_url = url
                if video_url in seen:
                    continue
                seen.add(video_url)
                files.append(PortfolioFile(type="video", url=video_url))

        if profile_picture is None:
            # Fallback: first fullsize avatar with matching alt anywhere
            for match in _IMAGE_RE.finditer(body):
                alt = unescape(match.group("alt") or "")
                url = absolute_url(match.group("url").strip())
                if (
                    url
                    and "_fullsize" in url
                    and alt.lower() == name_lower
                ):
                    profile_picture = url
                    break

        return self._none_if_empty(files), profile_picture

    def _clean_section_text(self, text: str) -> str | None:
        if not text:
            return None
        cleaned = self._drop_sentinels(text)
        cleaned = strip_md_escapes(unescape(cleaned))
        cleaned = re.sub(r"[ \t]*\\\s*\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned or None

    def _parse_overview(self, body: str) -> str | None:
        return self._clean_section_text(section(body, "Overview", level=2))

    def _parse_about(self, body: str) -> str | None:
        return self._clean_section_text(section(body, "About", level=3))

    def _parse_reasons(self, body: str) -> list[Highlight] | None:
        raw = section(body, "What to expect", level=3)
        if not raw:
            return None
        cleaned = self._drop_sentinels(raw)
        items: list[Highlight] = []
        for para in paragraphs(cleaned):
            if para.lower() in _SENTINELS:
                continue
            items.append(Highlight(reason_description=para))
        return self._none_if_empty(items)

    def _parse_booking_notes(self, body: str) -> list[str] | None:
        raw = section(body, "Additional booking notes", level=3)
        if not raw:
            return None
        cleaned = self._drop_sentinels(raw)
        notes = [p for p in paragraphs(cleaned) if p.lower() not in _SENTINELS]
        return self._none_if_empty(notes)

    def _parse_influences(self, body: str) -> list[str] | None:
        raw = section(body, "Influences and inspiration", level=3)
        if not raw:
            return None
        cleaned = self._drop_sentinels(raw)
        items: list[str] = []
        for para in paragraphs(cleaned):
            if para.lower() in _SENTINELS:
                continue
            # Comma-separated name/style lists with no sentence punctuation
            if para.count(",") >= 2 and not re.search(r"[.!?]", para):
                for part in para.split(","):
                    item = clean_or_none(part)
                    if item:
                        items.append(item)
            else:
                items.append(para)
        return self._none_if_empty(items)

    @staticmethod
    def _is_junk_setup_item(text: str) -> bool:
        lower = text.lower().strip()
        if "report this profile" in lower:
            return True
        if "gigsalad.com/cdn-cgi/image" in lower:
            return True
        if re.match(r"^!\[.*\]\(https?://(?:www\.)?gigsalad\.com/", text.strip()):
            return True
        return False

    def _parse_setup_requirements(self, body: str) -> list[SetupRequirement] | None:
        raw = section(body, "Setup requirements", level=3)
        if not raw:
            return None
        cleaned = self._drop_sentinels(raw)
        cleaned = strip_md_escapes(unescape(cleaned))
        items: list[str] = []
        numbered = re.split(r"(?:^|\n)\s*\d+\.\s+", cleaned)
        if len(numbered) > 1:
            for chunk in numbered[1:]:
                text = re.sub(r"\s+", " ", chunk).strip()
                if (
                    text
                    and text.lower() not in _SENTINELS
                    and not self._is_junk_setup_item(text)
                ):
                    items.append(text)
        else:
            for para in paragraphs(cleaned):
                if para.lower() not in _SENTINELS and not self._is_junk_setup_item(
                    para
                ):
                    items.append(para)

        requirements = [SetupRequirement(description=item) for item in items]
        return self._none_if_empty(requirements)

    def _parse_song_list(self, body: str) -> list[str] | None:
        """Extract song lines when set list has a soft-break block (≥5 songs).

        GigSalad soft-breaks are trailing double-spaces (``  \\n``), sometimes
        with a literal backslash. Long prose soft-breaks are skipped. The last
        song often lacks a trailing soft-break — still include short `` - ``
        lines once a soft-break block is underway.
        """
        raw = section(body, "Set list", level=3)
        if not raw:
            return None
        cleaned = self._drop_sentinels(raw)
        soft_lines: list[str] = []
        seen_soft = False
        for line in cleaned.splitlines():
            is_soft = line.endswith("  ") or line.rstrip().endswith("\\")
            entry = clean_or_none(strip_md_escapes(line.rstrip(" \\")))
            if not entry or entry.lower() in _SENTINELS:
                continue
            if len(entry) > 120:
                continue
            if is_soft:
                seen_soft = True
                soft_lines.append(entry)
            elif seen_soft and " - " in entry:
                soft_lines.append(entry)
            elif seen_soft:
                # Outro prose without song marker — stop
                break
        if len(soft_lines) < 5:
            return None
        return soft_lines

    def _parse_team(self, body: str) -> list[TeamMember] | None:
        raw = section(body, "Team", level=3)
        if not raw:
            return None
        cleaned = self._drop_sentinels(raw)
        members: list[TeamMember] = []
        for line in cleaned.splitlines():
            item = clean_or_none(line)
            if not item or item.lower() in _SENTINELS:
                continue
            parts = item.split()
            if len(parts) >= 3:
                name = " ".join(parts[:2])
                role = " ".join(parts[2:])
            elif len(parts) == 2:
                name, role = parts[0], parts[1]
            else:
                name, role = parts[0], None
            members.append(TeamMember(name=name, role=role))
        return self._none_if_empty(members)

    def _parse_at_a_glance(self, body: str) -> dict:
        booking = section(body, "Booking information", level=2)
        # Prefer "### At a glance" when present; else scan whole booking block
        glance = section(booking, "At a glance", level=3) if booking else ""
        src = glance or booking
        result: dict = {
            "prices": None,
            "price_range": None,
            "languages": None,
            "gig_length": None,
            "insurance_info": None,
            "unions": None,
        }
        if not src:
            return result

        price_match = _PRICE_RANGE_RE.search(src)
        if price_match:
            body_text = unescape(price_match.group("body")).strip()
            prices, price_range = self._parse_price_text(body_text)
            result["prices"] = prices
            result["price_range"] = price_range
        if result["prices"] is None:
            # Header fallback (some profiles only show price above the fold)
            header = self._header_block(body)
            for line in header.splitlines():
                text = unescape(line).strip()
                prices, price_range = self._parse_price_text(text)
                if prices or price_range:
                    result["prices"] = prices
                    result["price_range"] = price_range
                    break

        lang_match = _LANGUAGES_RE.search(src)
        if lang_match:
            langs = [
                clean_or_none(p)
                for p in re.split(r"[,/]", unescape(lang_match.group("body")))
            ]
            langs = [x for x in langs if x]
            result["languages"] = self._none_if_empty(langs)

        gig_match = _GIG_LENGTH_RE.search(src)
        if gig_match:
            range_match = _GIG_RANGE_RE.search(unescape(gig_match.group("body")))
            if range_match:
                result["gig_length"] = GigLength(
                    min_minutes=int(range_match.group(1)),
                    max_minutes=int(range_match.group(2)),
                )

        ins_match = _INSURANCE_RE.search(src)
        if ins_match:
            result["insurance_info"] = clean_or_none(ins_match.group("body"))

        unions_match = _UNIONS_RE.search(src)
        if unions_match:
            unions = [
                clean_or_none(p)
                for p in re.split(r"[,;]", unescape(unions_match.group("body")))
            ]
            unions = [x for x in unions if x]
            result["unions"] = self._none_if_empty(unions)

        return result

    def _parse_reviews(self, body: str) -> list[Review] | None:
        reviews_md = section(body, "Reviews", level=2)
        if not reviews_md:
            return None

        reviews: list[Review] = []
        splits = list(_REVIEW_SPLIT_RE.finditer(reviews_md))
        for i, match in enumerate(splits):
            name = clean_or_none(match.group("name"))
            start = match.end()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(reviews_md)
            block = reviews_md[start:end]

            review_date: date | None = None
            for line in block.splitlines():
                stripped = unescape(line).strip()
                if not stripped:
                    continue
                parsed = parse_date(stripped)
                if parsed:
                    review_date = parsed
                    break

            title_match = _REVIEW_TITLE_RE.search(block)
            title = clean_or_none(title_match.group("title")) if title_match else None

            body_lines: list[str] = []
            past_title = title_match is None
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped:
                    if body_lines:
                        body_lines.append("")
                    continue
                lower = unescape(stripped).lower()
                if lower in _SENTINELS or lower.startswith("hired as:"):
                    break
                if lower.startswith("[show more]") or lower.startswith("[write a review]"):
                    break
                if _REVIEW_TITLE_RE.match(stripped):
                    past_title = True
                    continue
                if not past_title:
                    # Skip name/date/verified lines before title
                    if parse_date(unescape(stripped)):
                        continue
                    if lower in {"verified", "verified review"}:
                        continue
                    if name and unescape(stripped).lower() == name.lower():
                        continue
                    continue
                body_lines.append(stripped)

            body_text = clean_or_none("\n".join(body_lines))
            parts = [p for p in (title, body_text) if p]
            text = "\n\n".join(parts) if parts else None
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
        current_month: str | None = None
        current_year: int | None = None
        lines = events_md.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = unescape(line).strip()
            lower = stripped.lower()
            if lower in {"show more", "show less", "show more show less"}:
                i += 1
                continue

            month_match = _MONTH_HEADER_RE.match(line.strip())
            if month_match:
                current_month = month_match.group("month")
                current_year = int(month_match.group("year"))
                i += 1
                continue

            day_match = _EVENT_DAY_RE.match(line.strip())
            if day_match and current_month and current_year:
                day = int(day_match.group(1))
                # Collect following non-empty lines until next day/month/sentinel
                fields: list[str] = []
                j = i + 1
                while j < len(lines):
                    nxt = unescape(lines[j]).strip()
                    if not nxt or nxt == "•":
                        j += 1
                        continue
                    if _EVENT_DAY_RE.match(lines[j].strip()) or _MONTH_HEADER_RE.match(
                        lines[j].strip()
                    ):
                        break
                    if nxt.lower() in {"show more", "show less"}:
                        break
                    # Skip weekday-only lines like "Tuesday"
                    if re.fullmatch(
                        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
                        nxt,
                    ):
                        j += 1
                        continue
                    fields.append(nxt)
                    j += 1

                event_type = fields[0] if fields else None
                time_range = None
                location = None
                for field in fields[1:]:
                    if re.search(r"\d{1,2}:\d{2}\s*(am|pm)", field, re.IGNORECASE):
                        time_range = field
                    elif _CITY_STATE_RE.match(field) or (
                        "," in field and len(field) < 80
                    ):
                        location = field

                try:
                    event_date = date(
                        current_year,
                        _month_number(current_month),
                        day,
                    )
                except ValueError:
                    event_date = None

                events.append(
                    VendorEvent(
                        event_date=event_date,
                        event_type=clean_or_none(event_type),
                        location=clean_or_none(location),
                        description=clean_or_none(time_range),
                    )
                )
                i = j
                continue

            i += 1

        return self._none_if_empty(events)


_MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _month_number(name: str) -> int:
    return _MONTH_NUMBERS[name.lower()]
