from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from vendor_profiles.models.vendor_profile import (
    Category,
    Highlight,
    Location,
    Package,
    PortfolioFile,
    Price,
    PriceRange,
    Review,
    SocialMediaLink,
    VendorProfile,
)
from vendor_profiles.parsers.base import VendorProfileParser
from vendor_profiles.parsers.text import (
    absolute_url,
    clean_or_none,
)
from vendor_profiles.parsers.us_states import STATE_CODE_TO_NAME, country_for_us_state

_H1_RE = re.compile(r"^#\s+(?P<name>.+)\s*$", re.MULTILINE)
_FOOTER_START = "## Eventective"
_BREADCRUMB_RE = re.compile(
    r"^\d+\.\s+\[(?P<label>[^\]]+)\]\((?P<url>https?://(?:www\.)?eventective\.com/[^)]+)\)\s*$",
    re.MULTILINE,
)
_HEADER_PRICE_RE = re.compile(
    r"\$(?P<min>[\d,]+(?:\.\d+)?)\s*-\s*\$(?P<max>[\d,]+(?:\.\d+)?)\s*/\s*event",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"^(?P<raw>.+,\s*(?P<city>[A-Za-z .'-]+),\s*(?P<st>[A-Z]{2}))\s*$",
    re.MULTILINE,
)
_TEL_RE = re.compile(r"\]\(tel:(?P<tel>[^)\s]+)\)")
_WEBSITE_RE = re.compile(
    r"\[Website\]\((?P<url>https?://[^)\s]+)\)",
    re.IGNORECASE,
)
_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_MEDIA_HOST = "media.eventective.com"
_LG_SUFFIX_RE = re.compile(r"_lg(?=\.\w+$)", re.IGNORECASE)
_PACKAGE_BLOCK_RE = re.compile(
    r"^Details\s*\n+"
    r"(?P<title>[^\n]+)\s*\n+"
    r"(?:(?P<capacity>\d+\s*-\s*\d+\s+people)\s*\n+)?"
    r"(?P<price>\$[^\n]+)",
    re.MULTILINE | re.IGNORECASE,
)
_PKG_PRICE_RANGE_RE = re.compile(
    r"\$(?P<min>[\d,]+(?:\.\d+)?)\s*-\s*\$(?P<max>[\d,]+(?:\.\d+)?)"
    r"(?:\s+per\s+event)?",
    re.IGNORECASE,
)
_PKG_PRICE_SINGLE_RE = re.compile(
    r"\$(?P<amt>[\d,]+(?:\.\d+)?)(?:\s+per\s+event)?",
    re.IGNORECASE,
)
_REC_RE = re.compile(
    r"\*\*(?P<title>.+?)\*\*\s*—\s*(?P<who>[^\n]+)\s*\n+"
    r"(?P<body>.*?)(?=\n\*\*|\n\d+\.\s+\[Write A Recommendation|\n## |\Z)",
    re.DOTALL,
)
_FEATURES_RE = re.compile(
    r"\*\*Features\*\*\s*\n+"
    r"(?:-\s+)?(?:Special Features:\s*)?(?P<body>.+?)(?=\n## |\n\*\*|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_DESC_NOISE = frozenset(
    {
        "read more",
        "recommendations",
        "write a recommendation",
        "website",
        "phone",
        "view photos",
    }
)
_OWN_SOCIAL_PATHS = frozenset(
    {
        "/eventective",
        "/@eventective",
        "/company/eventective",
    }
)
_SLUG_ID_RE = re.compile(r"-\d+$")
_BARE_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class EventectiveProfileParser(VendorProfileParser):
    source_host = "eventective.com"

    def parse(
        self,
        page_url: str,
        markdown: str,
        *,
        html: str | None = None,
    ) -> VendorProfile:
        body = self._profile_body(markdown)
        header = self._first_header_block(body)
        business_name = self._parse_business_name(body)
        if not business_name:
            raise ValueError("business_name is required")

        category_label = self._parse_breadcrumb(body)
        categories = None
        business_type = None
        if category_label:
            business_type = category_label
            categories = [
                Category(
                    primary_category=category_label,
                    sub_category=category_label,
                )
            ]

        price_range, prices = self._parse_header_price(header)
        packages = self._parse_pricing(body)
        portfolio, profile_picture = self._parse_media(body)

        return VendorProfile(
            business_name=business_name,
            slug=self.slug_from_url(page_url),
            phone_number=self._parse_phone(header),
            website=self._parse_website(header),
            business_type=business_type,
            profile_picture=profile_picture,
            categories=categories,
            description=self._parse_description(header),
            reasons_to_book_me=self._parse_additional_info(body),
            location=self._parse_location(header),
            prices=prices,
            price_range=price_range,
            packages=packages,
            reviews=self._parse_recommendations(body),
            social_media=self._parse_social(body),
            portfolio_files=portfolio,
        )

    # ------------------------------------------------------------------
    # Body / helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _profile_body(markdown: str) -> str:
        end = markdown.find(_FOOTER_START)
        if end < 0:
            end = len(markdown)
        chunk = markdown[:end]
        h1 = _H1_RE.search(chunk)
        if not h1:
            return chunk.strip()

        pre = chunk[: h1.start()]
        starts = [h1.start()]
        media = re.search(
            r"!\[.*?\]\(https?://media\.eventective\.com/",
            pre,
        )
        if media:
            starts.append(media.start())
        crumb = _BREADCRUMB_RE.search(pre)
        if crumb:
            starts.append(crumb.start())
        return chunk[min(starts) :].strip()

    @staticmethod
    def _first_header_block(body: str) -> str:
        h1s = list(_H1_RE.finditer(body))
        if not h1s:
            return body
        start = h1s[0].start()
        if len(h1s) > 1:
            return body[start : h1s[1].start()]
        pricing = re.search(r"^##\s+Event Pricing\s*$", body, re.MULTILINE)
        end = pricing.start() if pricing else len(body)
        return body[start:end]

    @staticmethod
    def _none_if_empty(items: list | None):
        if not items:
            return None
        return items

    @staticmethod
    def _amount(text: str) -> float | None:
        cleaned = text.replace(",", "").strip().lstrip("$")
        try:
            return float(cleaned)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Identity / header
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_business_name(body: str) -> str | None:
        match = _H1_RE.search(body)
        if not match:
            return None
        return clean_or_none(match.group("name"))

    @staticmethod
    def slug_from_url(page_url: str) -> str | None:
        path = urlparse(page_url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        if not parts:
            return None
        stem = parts[-1].removesuffix(".html")
        # /{id}/{Name}.html — keep the name segment as-is
        if len(parts) >= 2 and parts[-2].isdigit():
            return stem or None
        # /{city-st}/{slug}-{id}.html — strip listing id
        stripped = _SLUG_ID_RE.sub("", stem)
        return stripped or stem or None

    @staticmethod
    def _parse_breadcrumb(body: str) -> str | None:
        for match in _BREADCRUMB_RE.finditer(body):
            url = match.group("url")
            path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
            # City crumb: denver-co ; category: denver-co/photographers
            if len(path_parts) >= 2:
                return clean_or_none(match.group("label"))
        return None

    def _parse_location(self, header: str) -> Location | None:
        match = _ADDRESS_RE.search(header)
        if not match:
            return None
        city = clean_or_none(match.group("city"))
        st = match.group("st").upper()
        state = STATE_CODE_TO_NAME.get(st)
        raw = clean_or_none(match.group("raw"))
        if not raw:
            return None
        return Location(
            city=city,
            state=state,
            country=country_for_us_state(state=state, state_code=st),
            raw_location=raw,
        )

    def _parse_header_price(
        self, header: str
    ) -> tuple[PriceRange | None, list[Price] | None]:
        match = _HEADER_PRICE_RE.search(header)
        if not match:
            return None, None
        min_amt = self._amount(match.group("min"))
        max_amt = self._amount(match.group("max"))
        if min_amt is None:
            return None, None
        price_range = PriceRange(min_price=min_amt, max_price=max_amt)
        prices = [Price(amount=min_amt, per="event")]
        return price_range, prices

    def _parse_description(self, header: str) -> str | None:
        price = _HEADER_PRICE_RE.search(header)
        if not price:
            return None
        rest = header[price.end() :]
        lines: list[str] = []
        for line in rest.splitlines():
            stripped = line.strip()
            if not stripped:
                if lines:
                    break
                continue
            if stripped.startswith("["):
                break
            if "tel:" in stripped:
                break
            if re.match(r"^\[\]\(", stripped):
                break
            if stripped.startswith("#"):
                break
            lower = stripped.lower()
            if any(lower.startswith(n) for n in _DESC_NOISE):
                continue
            if lower.startswith("view photos"):
                continue
            lines.append(stripped)
        if not lines:
            return None
        text = _BARE_URL_RE.sub("", " ".join(lines))
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
        return clean_or_none(text)

    @staticmethod
    def _parse_phone(header: str) -> str | None:
        match = _TEL_RE.search(header)
        if not match:
            return None
        raw = unquote(match.group("tel")).strip()
        if not raw:
            return None
        chars: list[str] = []
        for i, ch in enumerate(raw):
            if ch.isdigit():
                chars.append(ch)
            elif ch == "+" and i == 0:
                chars.append(ch)
        return "".join(chars) or None

    @staticmethod
    def _parse_website(header: str) -> str | None:
        match = _WEBSITE_RE.search(header)
        if not match:
            return None
        url = absolute_url(match.group("url").strip())
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return None
        return url

    # ------------------------------------------------------------------
    # Pricing packages
    # ------------------------------------------------------------------

    def _parse_pricing(self, body: str) -> list[Package] | None:
        section_match = re.search(
            r"^##\s+Event Pricing\s*$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not section_match:
            return None
        start = section_match.end()
        next_h = re.search(r"^##\s+", body[start:], re.MULTILINE)
        end = start + next_h.start() if next_h else len(body)
        chunk = body[start:end]

        packages: list[Package] = []
        for match in _PACKAGE_BLOCK_RE.finditer(chunk):
            title = clean_or_none(match.group("title"))
            if not title:
                continue
            price_line = match.group("price")
            capacity = clean_or_none(match.group("capacity") or "")
            offerings = [capacity] if capacity else []

            range_match = _PKG_PRICE_RANGE_RE.search(price_line)
            single = None
            prices: list[Price] = []
            main: Price | None = None

            if range_match and "-" in price_line:
                min_amt = self._amount(range_match.group("min"))
                max_amt = self._amount(range_match.group("max"))
                if min_amt is not None:
                    main = Price(amount=min_amt, per="event")
                    prices.append(main)
                    if max_amt is not None and max_amt != min_amt:
                        prices.append(Price(amount=max_amt, per="event"))
            else:
                single = _PKG_PRICE_SINGLE_RE.search(price_line)
                if single:
                    amt = self._amount(single.group("amt"))
                    if amt is not None:
                        main = Price(amount=amt, per="event")

            packages.append(
                Package(
                    title=title,
                    price=main,
                    prices=prices,
                    offerings=offerings,
                )
            )
        return self._none_if_empty(packages)

    # ------------------------------------------------------------------
    # Recommendations / additional info
    # ------------------------------------------------------------------

    def _parse_recommendations(self, body: str) -> list[Review] | None:
        section_match = re.search(
            r"^##\s+Recommendations\s*$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not section_match:
            return None
        start = section_match.end()
        next_h = re.search(r"^##\s+", body[start:], re.MULTILINE)
        end = start + next_h.start() if next_h else len(body)
        chunk = body[start:end]

        reviews: list[Review] = []
        for match in _REC_RE.finditer(chunk):
            title = clean_or_none(match.group("title"))
            who = clean_or_none(match.group("who"))
            body_text = clean_or_none(
                re.sub(r"\s+", " ", match.group("body") or "").strip()
            )
            if not title and not body_text:
                continue
            if title and body_text:
                text = f"{title}\n\n{body_text}"
            else:
                text = title or body_text
            reviews.append(
                Review(
                    reviewer_name=who,
                    text=text,
                    rating=None,
                    review_date=None,
                )
            )
        return self._none_if_empty(reviews)

    def _parse_additional_info(self, body: str) -> list[Highlight] | None:
        section_match = re.search(
            r"^##\s+Additional Info\s*$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not section_match:
            return None
        start = section_match.end()
        next_h = re.search(r"^##\s+", body[start:], re.MULTILINE)
        end = start + next_h.start() if next_h else len(body)
        chunk = body[start:end]

        features = _FEATURES_RE.search(chunk)
        if not features:
            return None
        text = clean_or_none(features.group("body"))
        if not text:
            return None
        return [Highlight(reason_description=text)]

    # ------------------------------------------------------------------
    # Social / media
    # ------------------------------------------------------------------

    def _parse_social(self, body: str) -> list[SocialMediaLink] | None:
        links: list[SocialMediaLink] = []
        seen: set[str] = set()
        for match in _LINK_RE.finditer(body):
            label = (match.group("label") or "").strip()
            # Eventective vendor socials are empty-label links in the header
            if label:
                continue
            url = absolute_url(match.group("url").strip())
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            host = parsed.netloc.lower().removeprefix("www.")
            if "eventective.com" in host:
                continue
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
            elif "linkedin.com" in host:
                platform = "linkedin"
            if not platform:
                continue
            path = parsed.path.rstrip("/").lower()
            if path in _OWN_SOCIAL_PATHS or path.endswith("/eventective"):
                continue
            if url in seen:
                continue
            seen.add(url)
            links.append(
                SocialMediaLink(platform_type=platform, platform_url=url)
            )
        return self._none_if_empty(links)

    def _parse_media(
        self, body: str
    ) -> tuple[list[PortfolioFile] | None, str | None]:
        files: list[PortfolioFile] = []
        seen: set[str] = set()
        for match in _IMAGE_RE.finditer(body):
            raw_url = match.group("url").strip()
            url = absolute_url(raw_url)
            if not url:
                continue
            host = urlparse(url).netloc.lower().removeprefix("www.")
            if host != _MEDIA_HOST:
                continue
            canonical = _LG_SUFFIX_RE.sub("", url)
            if canonical in seen:
                continue
            seen.add(canonical)
            files.append(PortfolioFile(type="image", url=canonical))
        profile = files[0].url if files else None
        return self._none_if_empty(files), profile
