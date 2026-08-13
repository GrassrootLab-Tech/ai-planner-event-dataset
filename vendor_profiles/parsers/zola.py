from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from vendor_profiles.models.vendor_profile import (
    Category,
    FAQ,
    Location,
    MarketServed,
    PortfolioFile,
    Price,
    PriceRange,
    Review,
    ServiceArea,
    SocialMediaLink,
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
    strip_tracking_params,
    unescape,
)
from vendor_profiles.parsers.us_states import (
    STATE_CODE_TO_NAME,
    US_STATE_NAMES,
    country_for_us_state,
)

_H1_RE = re.compile(r"^#\s+(?P<name>.+)\s*$", re.MULTILINE)
_BREADCRUMB_START = "- [Wedding Vendors](/wedding-vendors)/"
_BODY_ENDS = (
    "Want to learn more about their pricing?",
    "## Explore other vendors serving",
)
_BREADCRUMB_LINK_RE = re.compile(
    r"^-\s+\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)/?\s*$",
    re.MULTILINE,
)
_BOLD_FIELD_RE = re.compile(
    r"\*\*(?P<label>[^*]+):\*\*\s*(?P<value>.+)",
)
_RATING_RE = re.compile(
    r"Rating:\s*(?P<rating>\d+(?:\.\d+)?)\s*\((?P<count>[\d,]+)\s+reviews?\)",
    re.IGNORECASE,
)
_PRICES_START_RE = re.compile(
    r"Prices\s+start\s+at\s+(\$[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_TIMES_BOOKED_RE = re.compile(
    r"(?P<count>[\d,]+)\s+Zola\s+couples\s+have\s+booked",
    re.IGNORECASE,
)
_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_CITY_STATE_CRUMB_RE = re.compile(
    r"^(?P<city>[A-Za-z .'-]+),\s*(?P<st>[A-Z]{2})\b"
)
_REVIEW_BLOCK_RE = re.compile(
    r"^-\s+(?P<initials>\S+)\s*\n+"
    r"[ \t]*(?P<name>[^\n]+)\s*\n+"
    r"[ \t]*Rating:\s*(?P<rating>\d+(?:\.\d+)?)\s*\n+"
    r"[ \t]*•\s*(?P<date>[A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s*\n+"
    r"(?:[ \t]*###\s+(?P<title>[^\n]+)\s*\n+)?"
    r"(?P<body>.*?)(?=^-\s+\S|\Z)",
    re.DOTALL | re.MULTILINE,
)
_PREFERRED_VENDOR_LINK_RE = re.compile(
    r'\]\((?P<path>/wedding-vendors/[^)\s]+)(?:\s+"[^"]*")?\)'
)
_NEXT_DATA_RE = re.compile(
    # HasData scrapes often drop id="__NEXT_DATA__" but keep the JSON payload
    r'<script[^>]*>\s*(?P<json>\{"props"\s*:\s*\{"pageProps".*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_FAQ_NOISE = frozenset(
    {
        "chevrondown",
        "downcaret",
        "ask them a question",
    }
)
_GENRE_GROUPS = frozenset({"musical genres", "cuisines"})
_SERVICE_GROUPS = frozenset(
    {
        "services",
        "dietary accommodations",
        "meal types",
        "beverage services",
        "drink types",
        "event types",
    }
)


class ZolaProfileParser(VendorProfileParser):
    source_host = "zola.com"

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

        services_info = self._parse_services(body)
        pricing = self._parse_pricing(body)
        location, service_area = self._parse_location(body)
        portfolio, profile_picture = self._parse_media(body)
        fields = self._parse_bold_fields(body)

        return VendorProfile(
            business_name=business_name,
            slug=self._slug_from_url(page_url),
            business_type=fields.get("type"),
            tagline=self._parse_tagline(body, business_name),
            website=self._parse_website(body),
            profile_picture=profile_picture,
            categories=self._parse_categories(body, fields),
            description=self._parse_description(body, business_name),
            services_provided=services_info.get("services"),
            genres_or_styles=services_info.get("genres"),
            faqs=self._parse_faqs(body),
            location=location,
            service_area=service_area,
            markets_served=self._parse_markets_served(html),
            prices=pricing.get("prices"),
            price_range=pricing.get("price_range"),
            rating_average=self._parse_rating(body),
            reviews=self._parse_reviews(body),
            # Lives just after the body cut ("Want to learn more…")
            times_booked=self._parse_times_booked(markdown),
            awards=self._parse_awards(body),
            similar_vendors=self._parse_similar_vendors(body),
            social_media=self._parse_social(body),
            portfolio_files=portfolio,
        )

    # ------------------------------------------------------------------
    # Body / helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _profile_body(markdown: str) -> str:
        start = markdown.find(_BREADCRUMB_START)
        if start < 0:
            h1 = _H1_RE.search(markdown)
            start = h1.start() if h1 else 0
        end = len(markdown)
        for marker in _BODY_ENDS:
            idx = markdown.find(marker, start)
            if 0 <= idx < end:
                end = idx
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
    def _strip_image_query(url: str) -> str:
        return url.split("?", 1)[0]

    # ------------------------------------------------------------------
    # Identity / header
    # ------------------------------------------------------------------

    def _parse_business_name(self, body: str) -> str | None:
        match = _H1_RE.search(body)
        if not match:
            return None
        return clean_or_none(match.group("name"))

    def _parse_bold_fields(self, body: str) -> dict[str, str]:
        """Parse **Category:** / **Type:** / **Genres:** style fields."""
        out: dict[str, str] = {}
        # Prefer the pricing / header block before About
        about = re.search(r"^##\s+About\s+", body, re.MULTILINE | re.IGNORECASE)
        chunk = body[: about.start()] if about else body[:2500]
        for match in _BOLD_FIELD_RE.finditer(chunk):
            label = unescape(match.group("label")).strip().lower()
            value = clean_or_none(match.group("value"))
            if value:
                out[label] = value
        return out

    def _parse_tagline(self, body: str, business_name: str) -> str | None:
        about = section(body, f"About {business_name}", level=2)
        if not about:
            # Fallback: any ## About …
            m = re.search(r"^##\s+About\s+.+$", body, re.MULTILINE | re.IGNORECASE)
            if m:
                about = section(body, m.group(0).lstrip("#").strip(), level=2)
        if not about:
            return None

        # Drop the ### business_name heading if present
        lines = [unescape(ln).strip() for ln in about.splitlines()]
        lines = [ln for ln in lines if ln]
        # Skip ### Name
        if lines and lines[0].startswith("###"):
            lines = lines[1:]
        if not lines:
            return None
        candidate = lines[0]
        lower = candidate.lower()
        # Skip if it's already a social/website link line or CTA
        if candidate.startswith("[") or lower in {"get a quote", "save"}:
            return None
        # Tagline is a short non-prose line before the social links / description
        if len(candidate) > 120:
            return None
        return clean_or_none(candidate)

    def _parse_website(self, body: str) -> str | None:
        for match in _LINK_RE.finditer(body):
            label = unescape(match.group("label") or "").strip().lower()
            if label != "website":
                continue
            url = absolute_url(match.group("url").strip())
            if not url:
                continue
            return strip_tracking_params(url) or None
        return None

    def _parse_rating(self, body: str) -> float | None:
        match = _RATING_RE.search(body)
        if not match:
            return None
        try:
            return float(match.group("rating"))
        except ValueError:
            return None

    def _parse_categories(
        self,
        body: str,
        fields: dict[str, str],
    ) -> list[Category] | None:
        # Breadcrumbs: Wedding Vendors → Bands and DJs → Colorado … → Aurora, CO …
        primary = None
        for match in _BREADCRUMB_LINK_RE.finditer(body):
            label = clean_or_none(match.group("label"))
            if not label:
                continue
            if label.lower() == "wedding vendors":
                continue
            # Skip city crumb ("Aurora, CO bands and DJs")
            if _CITY_STATE_CRUMB_RE.match(label):
                continue
            # Skip state crumb ("Colorado bands and DJs")
            first = label.split()[0].lower()
            if first in US_STATE_NAMES:
                continue
            primary = label
            break

        if not primary:
            return None
        sub = fields.get("category") or primary
        return [Category(primary_category=primary, sub_category=sub)]

    # ------------------------------------------------------------------
    # About / services
    # ------------------------------------------------------------------

    def _parse_description(self, body: str, business_name: str) -> str | None:
        about = section(body, f"About {business_name}", level=2)
        if not about:
            m = re.search(r"^##\s+About\s+(.+)$", body, re.MULTILINE | re.IGNORECASE)
            if m:
                about = section(body, f"About {m.group(1).strip()}", level=2)
        if not about:
            return None

        # Drop ### heading, tagline, social links, CTAs, badge images
        cleaned_lines: list[str] = []
        for line in about.splitlines():
            text = unescape(line).strip()
            if not text:
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
                continue
            if text.startswith("###"):
                continue
            if text.startswith("[") or text.startswith("!"):
                continue
            if text.lower() in {"get a quote", "save"}:
                continue
            cleaned_lines.append(text)

        raw = "\n".join(cleaned_lines).strip()
        # Drop short tagline-like first paragraph if it's a single short line
        paras = paragraphs(raw)
        if not paras:
            return None
        # If first para looks like a tagline (short, no period) and more follow, drop it
        if (
            len(paras) > 1
            and len(paras[0]) < 80
            and "." not in paras[0]
            and not paras[0].startswith("Operating")
        ):
            paras = paras[1:]
        return "\n\n".join(paras) or None

    def _parse_services(self, body: str) -> dict:
        result: dict = {"services": None, "genres": None}
        raw = section(body, "Services", level=2)
        if not raw:
            return result

        groups: dict[str, list[str]] = {}
        current: str | None = None
        for line in raw.splitlines():
            text = unescape(line).strip()
            if not text:
                continue
            h3 = re.match(r"^###\s+(.+)$", text)
            if h3:
                current = unescape(h3.group(1)).strip()
                groups.setdefault(current, [])
                continue
            if current is None:
                continue
            if text.startswith("- "):
                item = clean_or_none(text[2:])
            else:
                continue
            if item:
                groups[current].append(item)

        services: list[str] = []
        genres: list[str] = []
        seen_svc: set[str] = set()
        for label, items in groups.items():
            key = label.lower()
            if key in _GENRE_GROUPS:
                for item in items:
                    if item not in genres:
                        genres.append(item)
            elif key in _SERVICE_GROUPS:
                for item in items:
                    sk = item.lower()
                    if sk in seen_svc:
                        continue
                    seen_svc.add(sk)
                    services.append(item)

        result["services"] = self._none_if_empty(services)
        result["genres"] = self._none_if_empty(genres)
        return result

    def _parse_faqs(self, body: str) -> list[FAQ] | None:
        raw = section(body, "Frequently asked questions", level=2)
        if not raw:
            return None

        faqs: list[FAQ] = []
        # Split on ### headings
        blocks = re.split(r"(?m)^###\s+", raw)
        order = 0
        for block in blocks[1:]:
            lines = [unescape(ln).strip() for ln in block.splitlines()]
            lines = [ln for ln in lines if ln]
            if not lines:
                continue
            title = clean_or_none(lines[0])
            if not title:
                continue
            content_parts: list[str] = []
            for ln in lines[1:]:
                lower = ln.lower()
                if lower in _FAQ_NOISE:
                    continue
                if re.fullmatch(r"\d+\s+Answers?", ln, re.IGNORECASE):
                    continue
                content_parts.append(ln)
            content = clean_or_none(" ".join(content_parts)) if content_parts else None
            faqs.append(FAQ(title=title, content=content, order=order))
            order += 1
        return self._none_if_empty(faqs)

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def _parse_pricing(self, body: str) -> dict:
        result: dict = {"prices": None, "price_range": None}
        match = _PRICES_START_RE.search(body)
        if not match:
            return result
        money = parse_money(match.group(1))
        if not money:
            return result
        amount = money[0]
        result["prices"] = [Price(amount=amount, per="event")]
        result["price_range"] = PriceRange(min_price=amount)
        return result

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def _parse_location(
        self, body: str
    ) -> tuple[Location | None, ServiceArea | None]:
        location: Location | None = None
        service_area: ServiceArea | None = None

        crumbs: list[str] = []
        for match in _BREADCRUMB_LINK_RE.finditer(body):
            label = clean_or_none(match.group("label"))
            if label:
                crumbs.append(label)

        # Find city, ST crumb: "Aurora, CO bands and DJs"
        for label in crumbs:
            city_m = _CITY_STATE_CRUMB_RE.match(label)
            if not city_m:
                continue
            city = clean_or_none(city_m.group("city"))
            st = city_m.group("st")
            state_name = STATE_CODE_TO_NAME.get(st)
            location = Location(
                city=city,
                state=state_name,
                country=country_for_us_state(state=state_name, state_code=st),
                raw_location=f"{city}, {st}" if city else label,
            )
            service_area = ServiceArea(
                city=city,
                state=state_name,
                state_code=st,
            )
            break

        return location, service_area

    def _parse_markets_served(self, html: str | None) -> list[MarketServed] | None:
        """Pull homeMarkets / travelMarkets from __NEXT_DATA__ storefront."""
        storefront = self._next_data_storefront(html)
        if not storefront:
            return None
        markets = storefront.get("markets")
        if not isinstance(markets, dict):
            return None

        out: list[MarketServed] = []
        seen: set[str] = set()
        for key in ("homeMarkets", "travelMarkets"):
            entries = markets.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                market = entry.get("market")
                if not isinstance(market, dict):
                    continue
                label = clean_or_none(market.get("label"))
                if not label or label in seen:
                    continue
                seen.add(label)
                fee = bool(entry.get("travelFeeRequired", False))
                out.append(
                    MarketServed(
                        location=label,
                        is_additional_fee_required=fee,
                    )
                )
        return self._none_if_empty(out)

    @staticmethod
    def _next_data_storefront(html: str | None) -> dict | None:
        if not html:
            return None
        match = _NEXT_DATA_RE.search(html)
        if not match:
            return None
        try:
            data = json.loads(match.group("json"))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        props = data.get("props")
        if not isinstance(props, dict):
            return None
        page_props = props.get("pageProps")
        if not isinstance(page_props, dict):
            return None
        storefront = page_props.get("storefront")
        return storefront if isinstance(storefront, dict) else None

    # ------------------------------------------------------------------
    # Social / awards / similar
    # ------------------------------------------------------------------

    def _parse_social(self, body: str) -> list[SocialMediaLink] | None:
        links: list[SocialMediaLink] = []
        seen: set[str] = set()
        for match in _LINK_RE.finditer(body):
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
            elif "twitter.com" in host or host == "x.com" or host.endswith(".x.com"):
                platform = "twitter"
            elif "youtube.com" in host or "youtu.be" in host:
                platform = "youtube"
            if not platform:
                continue
            # Skip Zola's own social accounts
            path = urlparse(url).path.rstrip("/").lower()
            if path in {"/zola", "@zola"} or path.endswith("/zola"):
                continue
            if url in seen:
                continue
            seen.add(url)
            links.append(SocialMediaLink(platform_type=platform, platform_url=url))
        return self._none_if_empty(links)

    def _parse_awards(self, body: str) -> list[str] | None:
        awards: list[str] = []
        for match in _IMAGE_RE.finditer(body):
            alt = clean_or_none(match.group("alt"))
            if not alt:
                continue
            if "best of zola" in alt.lower():
                if alt not in awards:
                    awards.append(alt)
        return self._none_if_empty(awards)

    def _parse_similar_vendors(self, body: str) -> list[str] | None:
        m = re.search(
            r"^##\s+Preferred vendors of\s+.+$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not m:
            return None
        start = m.end()
        nxt = re.search(r"^##\s+\S", body[start:], re.MULTILINE)
        end = start + nxt.start() if nxt else len(body)
        raw = body[start:end]

        urls: list[str] = []
        seen: set[str] = set()
        # Preferred-vendor cards nest images inside the link label, so pull
        # the href: ](/wedding-vendors/... "Name")
        for match in _PREFERRED_VENDOR_LINK_RE.finditer(raw):
            path = match.group("path").strip()
            url = f"https://www.zola.com{path}"
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return self._none_if_empty(urls)

    def _parse_times_booked(self, body: str) -> int | None:
        match = _TIMES_BOOKED_RE.search(body)
        if not match:
            return None
        try:
            return int(match.group("count").replace(",", ""))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def _parse_reviews(self, body: str) -> list[Review] | None:
        raw = section(body, "Reviews", level=2)
        if not raw:
            return None

        reviews: list[Review] = []
        for match in _REVIEW_BLOCK_RE.finditer(raw):
            name = clean_or_none(match.group("name"))
            try:
                rating = float(match.group("rating"))
            except ValueError:
                rating = None
            review_date = parse_date(match.group("date"))
            title = clean_or_none(match.group("title"))
            body_raw = match.group("body") or ""
            body_lines = [
                unescape(ln).strip()
                for ln in body_raw.splitlines()
                if unescape(ln).strip()
            ]
            body_text = " ".join(body_lines)
            body_text = re.sub(r"\bSee more\b", "", body_text, flags=re.IGNORECASE)
            body_text = re.sub(r"\s{2,}", " ", body_text).strip()
            if title and body_text:
                text = f"{title}\n\n{body_text}"
            elif body_text:
                text = body_text
            elif title:
                text = title
            else:
                text = None
            if not name and not text:
                continue
            reviews.append(
                Review(
                    reviewer_name=name,
                    rating=rating,
                    text=text,
                    review_date=review_date,
                )
            )
        return self._none_if_empty(reviews)

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def _parse_media(
        self, body: str
    ) -> tuple[list[PortfolioFile] | None, str | None]:
        files: list[PortfolioFile] = []
        seen: set[str] = set()
        profile_picture: str | None = None

        # Hero gallery: images from top until About
        cut_at = len(body)
        about_m = re.search(r"^##\s+About\s+", body, re.MULTILINE | re.IGNORECASE)
        if about_m:
            cut_at = about_m.start()
        hero = body[:cut_at]

        # Performance samples section (video thumbnails)
        samples = section(body, "Performance samples", level=2)
        chunks = [hero, samples]

        for chunk in chunks:
            for match in _IMAGE_RE.finditer(chunk):
                alt = unescape(match.group("alt") or "")
                raw_url = match.group("url").strip()
                url = absolute_url(raw_url)
                if not url:
                    continue
                host = urlparse(url).netloc.lower()
                if "images.zola.com" not in host:
                    continue
                if "best of zola" in alt.lower():
                    continue
                canonical = self._strip_image_query(url)
                if canonical in seen:
                    continue
                seen.add(canonical)
                if profile_picture is None:
                    profile_picture = canonical
                files.append(PortfolioFile(type="image", url=canonical))

        return self._none_if_empty(files), profile_picture
