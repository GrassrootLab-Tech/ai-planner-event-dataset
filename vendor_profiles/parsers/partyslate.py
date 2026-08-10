from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from vendor_profiles.models.vendor_profile import (
    Category,
    FAQ,
    Location,
    LogisticDetails,
    Package,
    PortfolioFile,
    PressMention,
    Price,
    PriceRange,
    ServiceArea,
    SocialMediaLink,
    TeamMember,
    VendorEvent,
    VendorProfile,
    YearsInBusiness,
)
from vendor_profiles.parsers.base import VendorProfileParser
from vendor_profiles.parsers.text import (
    absolute_url,
    clean_or_none,
    paragraphs,
    parse_money,
    section,
    unescape,
)
from vendor_profiles.parsers.us_states import STATE_CODE_TO_NAME
from vendor_profiles.partyslate_listing_api import is_partyslate_venue_profile

_SENTINELS = frozenset(
    {
        "view all",
        "request a quote",
        "request info",
        "phone number",
        "favorite",
        "call",
        "photos",
        "albums",
        "overviewgallery",
        "testimonials",
        "vendor connections",
        "unclaimed",
    }
)

_H1_RE = re.compile(r"^#\s+(?P<name>.+)\s*$", re.MULTILINE)
_BASED_IN_RE = re.compile(
    r"^Based in\s+(?P<city>.+?),\s*(?P<st>[A-Z]{2}),\s*(?P<country>[A-Za-z.]+)\s*$",
    re.MULTILINE,
)
_RESPONSE_RE = re.compile(
    r"Average Response Time\s+(?P<body>.+)",
    re.IGNORECASE,
)
_FOUNDED_RE = re.compile(
    r"^Founded in\s+(?P<year>\d{4})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)")
_LINK_RE = re.compile(r"\[(?P<label>[^\]]*)\]\((?P<url>[^)]*)\)")
_BULLET_RE = re.compile(r"^-\s+(?P<body>.+)$", re.MULTILINE)
_ALBUM_LINK_RE = re.compile(
    r"\[(?P<body>.*?)]\((?P<url>/events/\d+|https?://[^)\s]*/events/\d+)\)",
    re.DOTALL,
)
_BOLD_TITLE_RE = re.compile(r"\*\*(?P<title>.+?)\*\*")
_PACKAGE_BLOCK_RE = re.compile(
    r"-\s+###\s+(?P<title>.+?)(?=\n-\s+###|\n## |\Z)",
    re.DOTALL,
)
_PRESS_ITEM_RE = re.compile(
    r"-\s+\[\*\*(?P<title>.+?)\*\*\s*(?:\\?\s*\n\s*)?(?P<publisher>[^\]]+)?\]"
    r"\((?P<url>[^)]+)\)",
    re.DOTALL,
)
_TEAM_COUNTER_RE = re.compile(r"^(\d+)/(\d+)\s*$", re.MULTILINE)
_TEAM_MEMBER_RE = re.compile(
    r"^###\s+(?P<name>.+)\s*\n+"
    r"(?P<role>[^\n#]+)\n+"
    r"(?P<bio>.*?)(?=\n### |\n## |\Z)",
    re.DOTALL | re.MULTILINE,
)
_ABOUT_HEADING_RE = re.compile(r"^##\s+About\s+.+$", re.MULTILINE | re.IGNORECASE)
_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
# Fallback when JSON-LD is missing: escaped Next.js payload fields
_HTML_PHONE_RE = re.compile(r'\\"phone\\":\\"(?P<phone>[^"\\]+)\\"')
_HTML_WEBSITE_RE = re.compile(r'\\"websiteUrl\\":\\"(?P<url>https?:[^"\\]+)\\"')
_HTML_PRICE_RE = re.compile(
    r'\\"minimumSpendCents\\":(?P<cents>\d+),'
    r'\\"notes\\":\\"(?P<notes>.*?)\\"',
)
_FOOTER_START = "Get the latest trends"
_BREADCRUMB_STARTS = (
    "1. [Find Venues](/find-venues)",
    "1. [Find Vendors](/find-vendors)",
)
_STREET_ADDRESS_RE = re.compile(
    r"^(?P<raw>.+,\s*(?P<city>[A-Za-z .'-]+),\s*(?P<st>[A-Z]{2})"
    r"\s+(?P<zip>\d{5}(?:-\d{4})?),\s*(?P<country>[A-Za-z.]+))\s*$",
    re.MULTILINE,
)
_CAPACITY_RE = re.compile(
    r"^Max\s+(?P<kind>Standing|Seated)\s*\n+\s*(?P<n>\d+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_EVENT_SPACE_LINK_RE = re.compile(
    r"\[(?P<body>.*?)]\((?P<url>/event-spaces/\d+|https?://[^)\s]*/event-spaces/\d+)\)",
    re.DOTALL,
)
_OUTSIDE_POLICY_RE = re.compile(
    r"^Outside\s+(?:caterers|suppliers)\s+allowed\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_UNCLAIMED_RE = re.compile(r"^Unclaimed\s*$", re.MULTILINE | re.IGNORECASE)


class PartySlateProfileParser(VendorProfileParser):
    source_host = "partyslate.com"

    def parse(
        self,
        page_url: str,
        markdown: str,
        *,
        html: str | None = None,
    ) -> VendorProfile:
        if is_partyslate_venue_profile(page_url):
            return self._parse_venue(page_url, markdown, html=html)

        body = self._profile_body(markdown)
        contact = self._parse_html_contact(html)
        business_name = self._parse_business_name(body) or contact.get("name")
        if not business_name:
            raise ValueError("business_name is required")

        services = self._parse_services(body)
        categories = self._parse_categories(body, services)
        location, service_area = self._parse_location(body)
        about_text, years = self._parse_about(body)
        pricing = self._parse_pricing(body, html=html, business_name=business_name)
        team, team_size = self._parse_team(body)
        portfolio, profile_picture = self._parse_media(body)
        logistic_details = (
            LogisticDetails(team_size=team_size) if team_size is not None else None
        )

        return VendorProfile(
            business_name=business_name,
            slug=self._slug_from_url(page_url),
            phone_number=contact.get("phone_number"),
            website=contact.get("website"),
            unclaimed=self._parse_unclaimed(body),
            categories=categories,
            services_provided=services,
            description=about_text,
            years_in_business=years,
            location=location,
            service_area=service_area,
            available_in=self._parse_available_in(body),
            response_time=self._parse_response_time(body),
            faqs=self._parse_faqs(body),
            packages=pricing.get("packages"),
            prices=pricing.get("prices"),
            price_range=pricing.get("price_range"),
            past_events=self._parse_albums(body),
            portfolio_files=portfolio,
            profile_picture=profile_picture,
            team=team,
            logistic_details=logistic_details,
            press_and_recognition=self._parse_press(body),
            social_media=self._parse_social(body),
        )

    def _parse_venue(
        self,
        page_url: str,
        markdown: str,
        *,
        html: str | None = None,
    ) -> VendorProfile:
        body = self._profile_body(markdown)
        contact = self._parse_html_contact(html)
        business_name = self._parse_business_name(body) or contact.get("name")
        if not business_name:
            raise ValueError("business_name is required")

        location, service_area = self._parse_venue_location(body)
        about_text, years = self._parse_about(body)
        event_packages, style_tag = self._parse_event_spaces(body)
        pricing = self._parse_pricing(body, html=html, business_name=business_name)
        packages = list(event_packages or [])
        if pricing.get("packages"):
            packages.extend(pricing["packages"])
        team, team_size = self._parse_team(body)
        portfolio, profile_picture = self._parse_media(body)
        logistic_details = (
            LogisticDetails(team_size=team_size) if team_size is not None else None
        )
        sub = style_tag or "Venue"
        categories = [Category(primary_category="Venue", sub_category=sub)]

        return VendorProfile(
            business_name=business_name,
            slug=self._slug_from_url(page_url),
            phone_number=contact.get("phone_number"),
            website=contact.get("website"),
            unclaimed=self._parse_unclaimed(body),
            business_type="Venue",
            categories=categories,
            services_provided=self._parse_amenities(body),
            description=about_text,
            years_in_business=years,
            location=location,
            service_area=service_area,
            booking_notes=self._parse_venue_booking_notes(body),
            has_event_space=bool(event_packages),
            response_time=self._parse_response_time(body),
            faqs=self._parse_faqs(body),
            packages=self._none_if_empty(packages),
            prices=pricing.get("prices"),
            price_range=pricing.get("price_range"),
            past_events=self._parse_albums(body),
            portfolio_files=portfolio,
            profile_picture=profile_picture,
            team=team,
            logistic_details=logistic_details,
            press_and_recognition=self._parse_press(body),
            social_media=self._parse_social(body),
        )

    @classmethod
    def _parse_html_contact(cls, html: str | None) -> dict[str, str | None]:
        """Extract name / phone / website from PartySlate page HTML.

        Prefers schema.org LocalBusiness JSON-LD; falls back to escaped
        Next.js payload fields (phone / websiteUrl).
        """
        out: dict[str, str | None] = {
            "name": None,
            "phone_number": None,
            "website": None,
        }
        if not html:
            return out

        for match in _LD_JSON_RE.finditer(html):
            raw = match.group(1).strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_type = node.get("@type")
                types = (
                    {node_type}
                    if isinstance(node_type, str)
                    else set(node_type or [])
                )
                if "LocalBusiness" not in types and "Organization" not in types:
                    continue
                if not out["name"]:
                    out["name"] = clean_or_none(node.get("name"))
                if not out["phone_number"]:
                    out["phone_number"] = clean_or_none(node.get("telephone"))
                if not out["website"]:
                    website = clean_or_none(node.get("url"))
                    # Prefer the vendor's own site; skip PartySlate page URLs
                    if website and "partyslate.com" not in website.lower():
                        out["website"] = website
            if out["phone_number"] or out["website"]:
                break

        if not out["phone_number"]:
            phone_m = _HTML_PHONE_RE.search(html)
            if phone_m:
                out["phone_number"] = clean_or_none(phone_m.group("phone"))
        if not out["website"]:
            web_m = _HTML_WEBSITE_RE.search(html)
            if web_m:
                out["website"] = clean_or_none(web_m.group("url"))

        return out

    @staticmethod
    def _profile_body(markdown: str) -> str:
        start = -1
        for sentinel in _BREADCRUMB_STARTS:
            idx = markdown.find(sentinel)
            if idx >= 0:
                start = idx
                break
        if start < 0:
            cover = re.search(r"!\[Cover photo", markdown)
            start = cover.start() if cover else 0
        end = markdown.find(_FOOTER_START, start)
        if end < 0:
            end = len(markdown)
        return markdown[start:end].strip()

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

    @staticmethod
    def _canonical_url(url: str) -> str | None:
        abs_url = absolute_url(url)
        if not abs_url:
            return None
        return abs_url.split("?", 1)[0]

    def _parse_business_name(self, body: str) -> str | None:
        match = _H1_RE.search(body)
        if not match:
            return None
        return clean_or_none(match.group("name"))

    @staticmethod
    def _parse_unclaimed(body: str) -> bool | None:
        # Bare "Unclaimed" badge line above the H1 (vendors + venues)
        if _UNCLAIMED_RE.search(body):
            return True
        return None

    def _parse_categories(
        self, body: str, services: list[str] | None
    ) -> list[Category] | None:
        h1 = _H1_RE.search(body)
        if not h1:
            return None
        # Bare line directly above the H1 is the vendor type chip
        before = body[: h1.start()].rstrip()
        primary = None
        for line in reversed(before.splitlines()):
            text = unescape(line).strip()
            if not text:
                continue
            if text.startswith("!") or text.startswith("[") or text.startswith("#"):
                continue
            if text.lower() in _SENTINELS:
                continue
            primary = clean_or_none(text)
            break
        if not primary:
            return None
        sub = (services or [primary])[0]
        return [Category(primary_category=primary, sub_category=sub)]

    def _parse_location(
        self, body: str
    ) -> tuple[Location | None, ServiceArea | None]:
        match = _BASED_IN_RE.search(body)
        if not match:
            return None, None
        city = clean_or_none(match.group("city"))
        state_code = match.group("st")
        country_raw = clean_or_none(match.group("country"))
        country = "US" if country_raw and country_raw.upper() in {"USA", "US"} else country_raw
        state_name = STATE_CODE_TO_NAME.get(state_code)
        raw_location = f"{city}, {state_code}" if city and state_code else None
        location = Location(
            city=city,
            state=state_name,
            country=country,
            raw_location=raw_location,
        )
        service_area = ServiceArea(
            city=city,
            state=state_name,
            state_code=state_code,
        )
        return location, service_area

    def _parse_venue_location(
        self, body: str
    ) -> tuple[Location | None, ServiceArea | None]:
        match = _STREET_ADDRESS_RE.search(body)
        if not match:
            return None, None
        city = clean_or_none(match.group("city"))
        state_code = match.group("st")
        zip_code = clean_or_none(match.group("zip"))
        country_raw = clean_or_none(match.group("country"))
        country = (
            "US"
            if country_raw and country_raw.upper() in {"USA", "US"}
            else country_raw
        )
        state_name = STATE_CODE_TO_NAME.get(state_code)
        raw_location = clean_or_none(match.group("raw"))
        location = Location(
            city=city,
            state=state_name,
            country=country,
            raw_location=raw_location,
        )
        service_area = ServiceArea(
            city=city,
            state=state_name,
            state_code=state_code,
            service_pincode=zip_code,
        )
        return location, service_area

    def _parse_amenities(self, body: str) -> list[str] | None:
        raw = section(body, "Amenities", level=2)
        if not raw:
            return None
        amenities: list[str] = []
        for match in _BULLET_RE.finditer(raw):
            item = clean_or_none(match.group("body"))
            if item and item.lower() not in _SENTINELS:
                amenities.append(item)
        return self._none_if_empty(amenities)

    def _parse_venue_booking_notes(self, body: str) -> list[str] | None:
        notes: list[str] = []
        for match in _CAPACITY_RE.finditer(body):
            kind = match.group("kind").capitalize()
            notes.append(f"Max {kind}: {match.group('n')}")
        for match in _OUTSIDE_POLICY_RE.finditer(body):
            text = clean_or_none(match.group(0))
            if text and text not in notes:
                notes.append(text)
        return self._none_if_empty(notes)

    def _parse_event_spaces(
        self, body: str
    ) -> tuple[list[Package] | None, str | None]:
        match = re.search(
            r"^##\s+Event Spaces(?:\s+\d+)?\s*$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            return None, None
        start = match.end()
        next_heading = re.search(r"^##\s+\S", body[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(body)
        raw = body[start:end]

        packages: list[Package] = []
        first_style: str | None = None
        for space in _EVENT_SPACE_LINK_RE.finditer(raw):
            inner = space.group("body")
            title_match = _BOLD_TITLE_RE.search(inner)
            title = clean_or_none(title_match.group("title")) if title_match else None

            segments: list[str] = []
            parts = re.split(r"[ \t]*\\?\s*\n[ \t]*\\?\s*", inner)
            for part in parts:
                text = unescape(part).strip()
                text = re.sub(r"!\[.*?\]\([^)]+\)", "", text).strip()
                text = re.sub(r"\*\*", "", text).strip()
                if not text:
                    continue
                if text.lower() in _SENTINELS:
                    continue
                if title and text == title:
                    continue
                # Skip summary-style "200 max standing" lines if any leak in
                if re.match(r"^\d+\s+max\s+(standing|seated)\s*$", text, re.I):
                    continue
                segments.append(text)

            offerings: list[str] = []
            i = 0
            while i < len(segments):
                seg = segments[i]
                if (
                    seg.isdigit()
                    and i + 1 < len(segments)
                    and segments[i + 1].lower() in {"seated", "standing"}
                ):
                    offerings.append(f"{seg} {segments[i + 1].capitalize()}")
                    i += 2
                    continue
                if seg.isdigit():
                    # Leading photo-count digit on the card, not capacity
                    i += 1
                    continue
                offerings.append(seg)
                if first_style is None:
                    first_style = seg
                i += 1

            if not title and not offerings:
                continue
            packages.append(Package(title=title, offerings=offerings))

        return self._none_if_empty(packages), first_style

    def _parse_response_time(self, body: str) -> str | None:
        match = _RESPONSE_RE.search(body)
        if not match:
            return None
        return clean_or_none(match.group("body"))

    def _parse_about(
        self, body: str
    ) -> tuple[str | None, YearsInBusiness | None]:
        match = _ABOUT_HEADING_RE.search(body)
        if not match:
            return None, None
        start = match.end()
        # Cut at next ## heading or ### Available In
        next_heading = re.search(
            r"^##\s+\S|^###\s+Available In\s*$",
            body[start:],
            re.MULTILINE | re.IGNORECASE,
        )
        end = start + next_heading.start() if next_heading else len(body)
        about_md = body[start:end].strip()

        years = None
        founded = _FOUNDED_RE.search(about_md)
        if founded:
            years = YearsInBusiness(start_year=int(founded.group("year")))

        lines: list[str] = []
        for line in about_md.splitlines():
            stripped = unescape(line).strip()
            if not stripped:
                if lines:
                    lines.append("")
                continue
            if _FOUNDED_RE.match(stripped):
                continue
            if stripped.lower() in _SENTINELS:
                continue
            lines.append(line.strip())
        text = unescape("\n".join(lines).strip())
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return (text or None), years

    def _parse_available_in(self, body: str) -> list[str] | None:
        raw = section(body, "Available In", level=3)
        if not raw:
            return None
        cities: list[str] = []
        for match in _BULLET_RE.finditer(raw):
            item = clean_or_none(match.group("body"))
            if item and item.lower() not in _SENTINELS:
                cities.append(item)
        return self._none_if_empty(cities)

    def _parse_services(self, body: str) -> list[str] | None:
        raw = section(body, "Services", level=2)
        if not raw:
            return None
        services: list[str] = []
        for match in _BULLET_RE.finditer(raw):
            item = clean_or_none(match.group("body"))
            if item and item.lower() not in _SENTINELS:
                services.append(item)
        return self._none_if_empty(services)

    def _parse_faqs(self, body: str) -> list[FAQ] | None:
        # Heading is "## FAQs 9" — section() needs exact heading text, so scan
        match = re.search(r"^##\s+FAQs(?:\s+\d+)?\s*$", body, re.MULTILINE | re.IGNORECASE)
        if not match:
            return None
        start = match.end()
        next_heading = re.search(r"^##\s+\S", body[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(body)
        raw = body[start:end].strip()
        if not raw:
            return None

        faqs: list[FAQ] = []
        current_q: str | None = None
        current_a: list[str] = []

        def flush() -> None:
            nonlocal current_q, current_a
            if current_q is None:
                return
            content = clean_or_none("\n\n".join(current_a))
            faqs.append(
                FAQ(title=current_q, content=content, order=len(faqs))
            )
            current_q = None
            current_a = []

        for para in re.split(r"\n\s*\n", raw):
            text = clean_or_none(para.replace("\\\n", " ").replace("\n", " "))
            if not text:
                continue
            if text.lower() in _SENTINELS or text.lower() == "view all":
                flush()
                break
            if text.endswith("?"):
                flush()
                current_q = text
            elif current_q is not None:
                current_a.append(text)
        flush()
        return self._none_if_empty(faqs)

    def _parse_pricing(
        self,
        body: str,
        *,
        html: str | None = None,
        business_name: str | None = None,
    ) -> dict:
        result: dict = {
            "packages": None,
            "prices": None,
            "price_range": None,
        }
        raw = section(body, "Pricing Packages", level=2)
        packages: list[Package] = []
        min_amounts: list[float] = []

        if raw and "hasn't listed their pricing" not in unescape(raw).lower():
            for match in _PACKAGE_BLOCK_RE.finditer(raw):
                title = clean_or_none(match.group("title").split("\n", 1)[0])
                block = match.group(0)
                content_lines: list[str] = []
                for line in block.splitlines()[1:]:
                    text = unescape(line).strip()
                    if not text or text.startswith("- ###"):
                        continue
                    if text.lower() in {"request a quote", "view all"}:
                        continue
                    content_lines.append(text)

                description = None
                package_prices: list[Price] = []
                used_indices: set[int] = set()
                i = 0
                while i < len(content_lines):
                    line = content_lines[i]
                    money = parse_money(line)
                    if money:
                        amount, per = money
                        if per in {"and", "up", "amp", "spend"}:
                            per = "event"
                        package_prices.append(Price(amount=amount, per=per))
                        min_amounts.append(amount)
                        used_indices.add(i)
                        if i > 0 and description is None:
                            description = content_lines[i - 1]
                            used_indices.add(i - 1)
                        i += 1
                        continue
                    if description is None and not line.startswith("$"):
                        description = line
                        used_indices.add(i)
                    i += 1

                # Remaining body text → offerings (one list item per paragraph)
                leftover_lines = [
                    content_lines[idx]
                    for idx in range(len(content_lines))
                    if idx not in used_indices
                ]
                offerings = paragraphs("\n\n".join(leftover_lines)) if leftover_lines else []

                packages.append(
                    Package(
                        title=title,
                        description=description,
                        prices=package_prices,
                        offerings=offerings,
                    )
                )

        # HTML notes only enrich existing markdown packages (never create packages)
        html_packages = self._parse_html_packages(html, business_name=business_name)
        if html_packages and packages:
            by_amount = {
                pkg.prices[0].amount: pkg
                for pkg in html_packages
                if pkg.prices
            }
            for pkg in packages:
                if pkg.offerings:
                    continue
                key = pkg.prices[0].amount if pkg.prices else None
                html_pkg = by_amount.get(key) if key is not None else None
                if html_pkg is None and len(html_packages) == 1:
                    html_pkg = html_packages[0]
                if html_pkg and html_pkg.offerings:
                    pkg.offerings = list(html_pkg.offerings)

        result["packages"] = self._none_if_empty(packages)
        if min_amounts:
            lo = min(min_amounts)
            result["price_range"] = PriceRange(min_price=lo)
            result["prices"] = [Price(amount=lo, per="event")]
        return result

    @classmethod
    def _parse_html_packages(
        cls,
        html: str | None,
        *,
        business_name: str | None = None,
    ) -> list[Package]:
        """Pull pricing cards from the escaped Next.js payload (notes → offerings)."""
        if not html:
            return []
        packages: list[Package] = []
        for match in _HTML_PRICE_RE.finditer(html):
            cents = int(match.group("cents"))
            amount = cents / 100.0
            notes_raw = match.group("notes")
            # Unescape JSON string fragments (\n, \", \uXXXX)
            try:
                notes = json.loads(f'"{notes_raw}"')
            except json.JSONDecodeError:
                notes = notes_raw.replace("\\n", "\n").replace('\\"', '"')
            notes = unescape(notes or "").strip()
            offerings = paragraphs(notes) if notes else []
            title = (
                f"{business_name} Pricing" if business_name else "Pricing"
            )
            packages.append(
                Package(
                    title=title,
                    description="Minimum Spend",
                    prices=[Price(amount=amount, per="event")],
                    offerings=offerings,
                )
            )
        return packages

    def _parse_albums(self, body: str) -> list[VendorEvent] | None:
        match = re.search(
            r"^##\s+Event Albums(?:\s+\d+)?\s*$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            return None
        start = match.end()
        next_heading = re.search(r"^##\s+\S", body[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(body)
        raw = body[start:end]

        events: list[VendorEvent] = []
        for album in _ALBUM_LINK_RE.finditer(raw):
            inner = album.group("body")
            title_match = _BOLD_TITLE_RE.search(inner)
            title = clean_or_none(title_match.group("title")) if title_match else None

            # Soft-break segments after the bold title
            segments: list[str] = []
            # Split on soft breaks (trailing spaces + optional backslash)
            parts = re.split(r"[ \t]*\\?\s*\n[ \t]*\\?\s*", inner)
            for part in parts:
                text = unescape(part).strip()
                text = re.sub(r"!\[.*?\]\([^)]+\)", "", text).strip()
                text = re.sub(r"\*\*", "", text).strip()
                # Drop leading photo-count digits
                text = re.sub(r"^\d+\s*", "", text).strip()
                if not text:
                    continue
                if text.lower().startswith("credited by"):
                    continue
                if text.lower() in _SENTINELS:
                    continue
                segments.append(text)

            # segments typically: [title, location, event_type]
            location = None
            event_type = None
            for seg in segments:
                if title and seg == title:
                    continue
                if "," in seg and (
                    re.search(r"\b[A-Z]{2}\b", seg) or "USA" in seg.upper()
                ):
                    location = seg
                else:
                    event_type = seg

            if not title and not location and not event_type:
                continue
            events.append(
                VendorEvent(
                    description=title,
                    location=location,
                    event_type=event_type,
                )
            )
        return self._none_if_empty(events)

    def _parse_media(
        self, body: str
    ) -> tuple[list[PortfolioFile] | None, str | None]:
        files: list[PortfolioFile] = []
        seen: set[str] = set()
        profile_picture: str | None = None

        for match in _IMAGE_RE.finditer(body):
            alt = unescape(match.group("alt") or "")
            raw_url = match.group("url").strip()
            canonical = self._canonical_url(raw_url)
            if not canonical:
                continue
            alt_lower = alt.lower()

            if "brand-image" in canonical or (
                "companies/" in canonical and "cover" not in canonical
                and "team-member" not in canonical and "photos/" not in canonical
            ):
                if "brand-image" in canonical or "logo" in alt_lower:
                    if profile_picture is None:
                        profile_picture = canonical
                    continue

            if "team-member" in canonical:
                continue

            is_cover = "cover photo" in alt_lower or "companies-cover-image" in canonical
            is_album = "featured photo" in alt_lower or "/photos/" in canonical
            if not (is_cover or is_album):
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            files.append(PortfolioFile(type="image", url=canonical))

        return self._none_if_empty(files), profile_picture

    def _parse_team(
        self, body: str
    ) -> tuple[list[TeamMember] | None, int | None]:
        raw = section(body, "Meet The Team", level=2)
        if not raw:
            return None, None

        team_size = None
        counter = _TEAM_COUNTER_RE.search(raw)
        if counter:
            team_size = int(counter.group(2))

        members: list[TeamMember] = []
        for match in _TEAM_MEMBER_RE.finditer(raw):
            name = clean_or_none(match.group("name"))
            role = clean_or_none(match.group("role"))
            bio = clean_or_none(
                re.sub(r"\s+", " ", unescape(match.group("bio") or ""))
            )
            if not name and not role and not bio:
                continue
            members.append(TeamMember(name=name, role=role, bio=bio))

        if team_size is None and members:
            team_size = len(members)
        return self._none_if_empty(members), team_size

    def _parse_press(self, body: str) -> list[PressMention] | None:
        match = re.search(
            r"^##\s+Press\s*(?:&(?:amp;)?\s*)?Recognition(?:\s+\d+)?\s*$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            return None
        start = match.end()
        next_heading = re.search(r"^##\s+\S", body[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(body)
        raw = body[start:end]

        mentions: list[PressMention] = []
        for item in _PRESS_ITEM_RE.finditer(raw):
            title = clean_or_none(
                re.sub(r"\s+", " ", item.group("title").replace("\\", ""))
            )
            publisher = clean_or_none(item.group("publisher") or "")
            url = absolute_url(item.group("url").strip())
            if not title and not url:
                continue
            mentions.append(
                PressMention(title=title, publisher=publisher, url=url)
            )
        return self._none_if_empty(mentions)

    def _parse_social(self, body: str) -> list[SocialMediaLink] | None:
        raw = section(body, "Follow Us", level=2)
        if not raw:
            return None
        # Stop before Visit Website / Call CTAs
        cut = re.search(r"\[Visit Website\]|^\s*Call\s*$", raw, re.MULTILINE)
        if cut:
            raw = raw[: cut.start()]

        links: list[SocialMediaLink] = []
        seen: set[str] = set()
        for match in _LINK_RE.finditer(raw):
            url = absolute_url(match.group("url").strip())
            if not url:
                continue
            host = urlparse(url).netloc.lower().removeprefix("www.")
            platform = None
            if "instagram.com" in host:
                platform = "instagram"
            elif "facebook.com" in host:
                platform = "facebook"
            elif "tiktok.com" in host:
                platform = "tiktok"
            elif "pinterest.com" in host:
                platform = "pinterest"
            elif "twitter.com" in host or "x.com" in host:
                platform = "twitter"
            if not platform:
                continue
            if url in seen:
                continue
            seen.add(url)
            links.append(SocialMediaLink(platform_type=platform, platform_url=url))
        return self._none_if_empty(links)
