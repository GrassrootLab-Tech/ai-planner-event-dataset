from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

from vendor_profiles.models.vendor_profile import (
    Category,
    FAQ,
    GigLength,
    Highlight,
    Location,
    Package,
    PortfolioFile,
    Price,
    PriceRange,
    Review,
    ServiceArea,
    SocialMediaLink,
    TeamMember,
    VendorProfile,
    YearsInBusiness,
)
from vendor_profiles.parsers.base import VendorProfileParser
from vendor_profiles.parsers.text import (
    absolute_url,
    clean_or_none,
    paragraphs,
    parse_date,
    parse_money,
    sanitize_phone,
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
_BODY_START = "<!--THE END-->"
_BODY_END = "## Why use Weddingwire to message vendors?"
_BREADCRUMB_LINK_RE = re.compile(
    r"^-\s+\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)\s*$",
    re.MULTILINE,
)
_RATING_RE = re.compile(
    r"(?P<rating>\d+(?:\.\d+)?)\s+out of\s+5\s+rating",
    re.IGNORECASE,
)
_STARTING_PRICE_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?\s+starting\s+price",
    re.IGNORECASE,
)
_USUAL_SPEND_RE = re.compile(
    r"Starting at\s+(\$[\d,]+(?:\.\d+)?)\s+for basic services,"
    r"\s+with couples usually spending around\s+(\$[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PACKAGE_PRICE_RE = re.compile(
    r"^(\$[\d,]+(?:\.\d+)?)\s*/\s*starting\s+price\s*$",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(r"^(?P<hours>\d+(?:\.\d+)?)\s+hours?\s*$", re.IGNORECASE)
_YEARS_RE = re.compile(r"(?P<years>\d+)\+?\s+years?\s+in\s+business", re.IGNORECASE)
_SPEAKS_RE = re.compile(r"We speak\s+(?P<langs>.+)$", re.IGNORECASE)
_CITY_STATE_RE = re.compile(
    r"(?P<city>[A-Za-z .'-]+),\s*(?P<st>[A-Z]{2})\b"
)
_ADDRESS_RE = re.compile(
    r"(?:(?P<city1>[A-Za-z .'-]+),\s*(?P<state_name>[A-Za-z ]+)\s+)?"
    r"(?P<city2>[A-Za-z .'-]+),\s*(?P<st>[A-Z]{2}),\s*(?P<zip>\d{5}(?:-\d{4})?)"
)
_TRAVEL_RE = re.compile(
    r"This vendor will travel up to\s+(?P<radius>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_TEL_RE = re.compile(r"\]\(tel:(?P<tel>[^)\s]+)\)")
_PHONE_LINE_RE = re.compile(r"^\+?\d{7,15}$")
_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_AWARD_WINNER_RE = re.compile(r"x(?P<n>\d+)\s+Award winner", re.IGNORECASE)
_RESPONSE_RE = re.compile(r"^Responds within\s+.+$", re.IGNORECASE | re.MULTILINE)
_REVIEW_BLOCK_RE = re.compile(
    r"^(?:[A-Z]\s*\n+)?"
    r"(?P<name>[A-Za-z][^\n]*?)\s+Sent on\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*\n+"
    r"(?:\d+(?:\.\d+)?\s+out of\s+5\s+rating\s*\n+)?"
    r"(?P<rating>\d+(?:\.\d+)?)\s*\n+"
    r"(?P<title>[^\n]+)\s*\n+"
    r"(?P<body>.*?)(?=^(?:[A-Z]\s*\n+)?[A-Za-z][^\n]*?\s+Sent on\s+\d"
    r"|^We're all about trust|^## |\Z)",
    re.DOTALL | re.MULTILINE,
)
_FAQ_NOISE = frozenset(
    {
        "read all faq",
        "read more faq",
        "read more",
        "any other questions?",
        "reach out about anything you didn't see answered here—no question is too small!",
        "message vendor",
    }
)
_SERVICE_SECTION_STOPS = frozenset(
    {
        "read more",
        "read more faq",
        "view all",
    }
)
_MD_LINK_RE = re.compile(r"^\[([^\]]+)\]\([^)]*\)\s*$")
_HEADING_LINE_RE = re.compile(r"^#+\s+\S")


def _services_section_stop(text: str) -> bool:
    """True when a Services Offered line should end the section."""
    raw = text.strip()
    if not raw:
        return False
    lower = raw.lower()
    if lower in _SERVICE_SECTION_STOPS:
        return True
    if _HEADING_LINE_RE.match(raw):
        return True
    link = _MD_LINK_RE.match(raw)
    if link and link.group(1).strip().lower() in _SERVICE_SECTION_STOPS:
        return True
    return False


_SERVICES_OFFERED_RE = re.compile(
    r"^(?:\*\*Services Offered\*\*|#{1,6}\s+Services Offered)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_FAQ_SECTION_RE = re.compile(
    r"^(?:\*\*(?:Frequently asked questions|FAQ)\*\*|#{1,6}\s+(?:Frequently asked questions|FAQ))\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_NAV_STOPS = frozenset(
    {
        "highlights",
        "about",
        "pricing",
        "availability",
        "faq",
        "reviews",
        "team",
        "map",
    }
)
_SERVICE_NOISE = frozenset(
    {
        "hired",
        "hired?",
        "save",
        "saved",
        "save saved",
        "interested in this vendor?",
        "request pricing",
        "this vendor has no available photos",
        "vendors you may like",
        "### vendors you may like",
        "see other vendors that are popular with couples right now",
        "circle message",
        "start a conversation",
    }
)
_SERVICE_TOTAL_RE = re.compile(r"^\.\.\.\s*\(\d+\s+total\)$", re.IGNORECASE)
_IMAGE_FILE_RE = re.compile(r"\.(?:jpe?g|png|gif|webp)$", re.IGNORECASE)
_SERVICE_FAQ_RE = re.compile(
    r"what\s+(?:.+?\s+)?services\s+do\s+you\s+(?:offer|provide)",
    re.IGNORECASE,
)
_GENRE_FAQ_RE = re.compile(
    r"what\s+music\s+genres\s+do\s+you\s+specialize\s+in",
    re.IGNORECASE,
)
# Visit website: <div class="storefront-summary-website">… data-href="…"
_HTML_WEBSITE_RE = re.compile(
    r"<div\b(?=[^>]*\bstorefront-summary-website\b)[^>]*>"
    r".*?data-href=[\"'](?P<url>[^\"']+)[\"']",
    re.IGNORECASE | re.DOTALL,
)


class WeddingWireProfileParser(VendorProfileParser):
    source_host = "weddingwire.com"

    @staticmethod
    def _is_service_noise(text: str) -> bool:
        lower = text.lower().strip()
        if lower in _SERVICE_NOISE:
            return True
        if _services_section_stop(text):
            return True
        if lower.startswith("### ") and "vendor" in lower:
            return True
        if _SERVICE_TOTAL_RE.match(lower):
            return True
        if _IMAGE_FILE_RE.search(lower):
            return True
        return False

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

        about = self._parse_about(body)
        pricing = self._parse_pricing(body)
        faqs_info = self._parse_faqs(body)
        location, service_area = self._parse_map(body)
        portfolio, profile_picture = self._parse_media(body)
        categories, chips = self._parse_categories_and_chips(body)

        services: list[str] = []
        seen_services: set[str] = set()

        def _add_service(text: str) -> None:
            cleaned = clean_or_none(text)
            if not cleaned or self._is_service_noise(cleaned):
                return
            if _services_section_stop(cleaned):
                return
            key = cleaned.lower()
            if key in seen_services:
                return
            seen_services.add(key)
            services.append(cleaned)

        for item in self._parse_services_offered(body):
            if _services_section_stop(item):
                break
            _add_service(item)
        for item in faqs_info.get("services") or []:
            _add_service(item)
        for chip in chips or []:
            _add_service(chip)

        # Cap noisy long lists: keep top 15 when more than 25 items.
        if len(services) > 25:
            services = services[:15]

        return VendorProfile(
            business_name=business_name,
            slug=self.slug_from_url(page_url),
            phone_number=self._parse_phone(body),
            website=self._parse_website(html),
            business_type=self._parse_business_type(body),
            tagline=None,
            profile_picture=profile_picture,
            categories=categories,
            description=about.get("description"),
            services_provided=self._none_if_empty(services),
            genres_or_styles=faqs_info.get("genres"),
            reasons_to_book_me=about.get("features"),
            faqs=faqs_info.get("faqs"),
            languages=about.get("languages"),
            years_in_business=about.get("years"),
            gig_length=pricing.get("gig_length"),
            team=self._parse_team(body),
            location=location,
            service_area=service_area,
            prices=pricing.get("prices"),
            price_range=pricing.get("price_range"),
            packages=pricing.get("packages"),
            rating_average=self._parse_rating(body),
            reviews=self._parse_reviews(body),
            response_time=self._parse_response_time(body),
            awards=self._parse_awards(body),
            social_media=self._parse_social(body),
            portfolio_files=portfolio,
        )

    # ------------------------------------------------------------------
    # Body / helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _profile_body(markdown: str) -> str:
        start = markdown.find(_BODY_START)
        if start < 0:
            h1 = _H1_RE.search(markdown)
            start = h1.start() if h1 else 0
        else:
            start = start + len(_BODY_START)
        end = markdown.find(_BODY_END, start)
        if end < 0:
            end = len(markdown)
        return markdown[start:end].strip()

    @staticmethod
    def slug_from_url(page_url: str) -> str | None:
        path = urlparse(page_url).path.rstrip("/")
        # /biz/<slug>/<id>.html
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"biz", "reviews"}:
            return parts[1] or None
        return parts[-1].removesuffix(".html") if parts else None

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

    def _parse_business_type(self, body: str) -> str | None:
        crumbs = self._breadcrumb_labels(body)
        # Second crumb is typically the category (after Weddings)
        for label in crumbs:
            lower = label.lower()
            if lower in {"weddings", "home"}:
                continue
            # Skip geo crumbs (Colorado, Denver, Golden, …)
            if self._looks_like_geo_crumb(label):
                continue
            return label
        return None

    def _parse_rating(self, body: str) -> float | None:
        match = _RATING_RE.search(body)
        if not match:
            return None
        try:
            return float(match.group("rating"))
        except ValueError:
            return None

    def _parse_response_time(self, body: str) -> str | None:
        match = _RESPONSE_RE.search(body)
        if not match:
            return None
        return clean_or_none(match.group(0))

    def _parse_categories_and_chips(
        self, body: str
    ) -> tuple[list[Category] | None, list[str]]:
        primary = self._parse_business_type(body)
        chips = self._parse_service_chips(body)
        if not primary and not chips:
            return None, []
        if not primary:
            return None, chips
        # WeddingWire header chips are UI noise (e.g. "Hired?"); mirror primary.
        return [Category(primary_category=primary, sub_category=primary)], chips

    def _parse_service_chips(self, body: str) -> list[str]:
        """Chips between the nav anchors and the rating summary."""
        # After the last [Map](#map) nav link, before "5.0" / "Fantastic"
        matches = list(
            re.finditer(r"^\[Map\]\(#map\)\s*$", body, re.MULTILINE | re.IGNORECASE)
        )
        if not matches:
            return []
        start = matches[0].end()
        rating = re.search(
            r"^\d+(?:\.\d+)?\s*$",
            body[start:],
            re.MULTILINE,
        )
        # Prefer the block that ends at "Fantastic" or "Read all reviews"
        end_m = re.search(
            r"^(?:Fantastic|Read all reviews)",
            body[start:],
            re.MULTILINE | re.IGNORECASE,
        )
        end = start + end_m.start() if end_m else (
            start + rating.start() if rating else start + 400
        )
        chunk = body[start:end]
        chips: list[str] = []
        for line in chunk.splitlines():
            text = unescape(line).strip()
            if not text:
                continue
            if text.startswith("[") or text.startswith("!"):
                continue
            if text.lower() in _NAV_STOPS:
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", text):
                continue
            if text.lower() in {"fantastic", "recommended by 100% of couples"}:
                continue
            if self._is_service_noise(text):
                continue
            if len(text) > 60:
                continue
            chips.append(text)
        return chips

    def _breadcrumb_labels(self, body: str) -> list[str]:
        labels: list[str] = []
        h1 = _H1_RE.search(body)
        chunk = body[: h1.start()] if h1 else body[:2000]
        for match in _BREADCRUMB_LINK_RE.finditer(chunk):
            label = clean_or_none(match.group("label"))
            if label:
                labels.append(label)
        return labels

    @staticmethod
    def _looks_like_geo_crumb(label: str) -> bool:
        lower = label.lower().strip()
        # "Colorado", "Denver", "Denver (City)", "Golden"
        bare = re.sub(r"\s*\([^)]*\)\s*", "", lower).strip()
        if bare in US_STATE_NAMES:
            return True
        if _CITY_STATE_RE.search(label):
            return True
        # Single-token city-ish crumbs without "Wedding"
        if "wedding" in lower or "&" in label or "hair" in lower or "dj" in lower:
            return False
        # Heuristic: short geo name without category words
        return " " not in bare or bare.endswith(" city")

    # ------------------------------------------------------------------
    # About
    # ------------------------------------------------------------------

    def _parse_about(self, body: str) -> dict:
        result: dict = {
            "description": None,
            "features": None,
            "languages": None,
            "years": None,
        }
        # Prefer the longest "About this vendor" block (teaser + full)
        blocks = list(
            re.finditer(
                r"^##\s+About this vendor\s*$",
                body,
                re.MULTILINE | re.IGNORECASE,
            )
        )
        best = ""
        for match in blocks:
            start = match.end()
            nxt = re.search(r"^##\s+\S", body[start:], re.MULTILINE)
            end = start + nxt.start() if nxt else len(body)
            raw = body[start:end].strip()
            if len(raw) > len(best):
                best = raw
        if not best:
            return result

        # Features / Experience are subsections — carve description before them
        cut = len(best)
        for marker in ("### Features", "### Experience", "Links"):
            idx = best.find(marker)
            if 0 <= idx < cut:
                cut = idx
        desc_raw = best[:cut]
        # Drop "Read more" CTAs and image/link lines
        cleaned_lines: list[str] = []
        for line in desc_raw.splitlines():
            text = unescape(line).strip()
            if not text:
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
                continue
            if text.lower() == "read more":
                continue
            if text.startswith("[") or text.startswith("!"):
                continue
            cleaned_lines.append(text)
        paras = paragraphs("\n".join(cleaned_lines))
        result["description"] = "\n\n".join(paras) or None

        # Features chips
        feat_m = re.search(r"^###\s+Features\s*$", best, re.MULTILINE | re.IGNORECASE)
        if feat_m:
            feat_start = feat_m.end()
            feat_end_m = re.search(
                r"^###\s+\S|^##\s+\S|^Links\s*$",
                best[feat_start:],
                re.MULTILINE,
            )
            feat_end = feat_start + feat_end_m.start() if feat_end_m else len(best)
            highlights: list[Highlight] = []
            for line in best[feat_start:feat_end].splitlines():
                text = unescape(line).strip()
                if not text:
                    continue
                if text.startswith("#") or text.startswith("[") or text.startswith("!"):
                    continue
                if text.startswith("- "):
                    continue
                if text.lower() in {"links", "visit website"}:
                    continue
                highlights.append(Highlight(reason_heading=text))
            result["features"] = self._none_if_empty(highlights)

        # Experience: years + languages
        exp_m = re.search(r"^###\s+Experience\s*$", best, re.MULTILINE | re.IGNORECASE)
        if exp_m:
            exp_start = exp_m.end()
            exp_end_m = re.search(
                r"^###\s+\S|^##\s+\S|^Links\s*$",
                best[exp_start:],
                re.MULTILINE,
            )
            exp_end = exp_start + exp_end_m.start() if exp_end_m else len(best)
            for line in best[exp_start:exp_end].splitlines():
                text = unescape(line).strip().lstrip("- ").strip()
                if not text:
                    continue
                years_m = _YEARS_RE.search(text)
                if years_m:
                    try:
                        years = int(years_m.group("years"))
                        result["years"] = YearsInBusiness(
                            start_year=date.today().year - years
                        )
                    except ValueError:
                        pass
                    continue
                speaks_m = _SPEAKS_RE.search(text)
                if speaks_m:
                    langs = [
                        clean_or_none(p)
                        for p in re.split(r",| and ", speaks_m.group("langs"))
                    ]
                    result["languages"] = self._none_if_empty(
                        [x for x in langs if x]
                    )
        return result

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def _parse_pricing(self, body: str) -> dict:
        result: dict = {
            "prices": None,
            "price_range": None,
            "packages": None,
            "gig_length": None,
        }
        raw = section(body, "Pricing", level=2)
        if not raw:
            # Still try header starting price
            self._apply_starting_price(body, result)
            return result

        packages: list[Package] = []
        gig_minutes: list[int] = []
        # Split on "Get more details" package terminators
        blocks = re.split(r"(?m)^Get more details\s*$", raw)
        for block in blocks[:-1] if len(blocks) > 1 else blocks[:1]:
            lines = [unescape(ln).strip() for ln in block.splitlines()]
            lines = [ln for ln in lines if ln]
            # Drop CTAs / summary lines that aren't packages
            lines = [
                ln
                for ln in lines
                if ln.lower()
                not in {
                    "looking for a personalized package?",
                    "reach out to this vendor and share your vision",
                    "get a personalized quote",
                }
                and not _USUAL_SPEND_RE.search(ln)
            ]
            if not lines:
                continue
            title = None
            price: Price | None = None
            offerings: list[str] = []
            desc_parts: list[str] = []
            for i, line in enumerate(lines):
                price_m = _PACKAGE_PRICE_RE.match(line)
                if price_m:
                    money = parse_money(price_m.group(1))
                    if money:
                        price = Price(amount=money[0], per="event")
                    # Title is the previous non-empty line if we haven't set it
                    if title is None and i > 0:
                        title = lines[i - 1]
                    continue
                if _STARTING_PRICE_RE.search(line):
                    continue
                dur = _DURATION_RE.match(line)
                if dur:
                    try:
                        hours = float(dur.group("hours"))
                        gig_minutes.append(int(hours * 60))
                    except ValueError:
                        pass
                    desc_parts.append(line)
                    continue
                if price is not None:
                    # After price line → offerings / description
                    if line.lower().startswith("includes "):
                        desc_parts.append(line)
                    else:
                        offerings.append(line)
                elif title is None and not _PACKAGE_PRICE_RE.match(line):
                    # First line before price is title — defer until we see price
                    pass
            # If no package price found, skip (header-only block)
            if price is None and not offerings:
                continue
            if title is None and lines:
                # Fallback: first line that isn't a price
                for line in lines:
                    if not _PACKAGE_PRICE_RE.match(line) and not _STARTING_PRICE_RE.search(
                        line
                    ):
                        title = line
                        break
            packages.append(
                Package(
                    title=clean_or_none(title),
                    description=clean_or_none(" ".join(desc_parts)) if desc_parts else None,
                    price=price,
                    offerings=offerings,
                )
            )

        result["packages"] = self._none_if_empty(packages)
        if gig_minutes:
            result["gig_length"] = GigLength(
                min_minutes=min(gig_minutes),
                max_minutes=max(gig_minutes),
            )

        # Summary line
        spend = _USUAL_SPEND_RE.search(raw) or _USUAL_SPEND_RE.search(body)
        min_price = None
        max_price = None
        if spend:
            lo = parse_money(spend.group(1))
            hi = parse_money(spend.group(2))
            if lo:
                min_price = lo[0]
            if hi:
                max_price = hi[0]
        if min_price is None:
            start_m = _STARTING_PRICE_RE.search(body)
            if start_m:
                money = parse_money(start_m.group(0))
                if money:
                    min_price = money[0]

        if min_price is not None:
            result["prices"] = [Price(amount=min_price, per="event")]
            result["price_range"] = PriceRange(
                min_price=min_price,
                max_price=max_price,
            )
        return result

    def _apply_starting_price(self, body: str, result: dict) -> None:
        start_m = _STARTING_PRICE_RE.search(body)
        if not start_m:
            return
        money = parse_money(start_m.group(0))
        if not money:
            return
        result["prices"] = [Price(amount=money[0], per="event")]
        result["price_range"] = PriceRange(min_price=money[0])

    # ------------------------------------------------------------------
    # Services Offered
    # ------------------------------------------------------------------

    def _parse_services_offered(self, body: str) -> list[str]:
        """Paras + bullets under Services Offered until View all/Read more/heading."""
        start_m = _SERVICES_OFFERED_RE.search(body)
        if not start_m:
            return []
        start = start_m.end()
        end_m = re.search(
            r"(?im)^(?:read more(?:\s+faq)?\s*$|view all\s*$|"
            r"\[[^\]]*view all[^\]]*\]\([^)]*\)\s*$|"
            r"#{1,6}\s+\S)",
            body[start:],
        )
        end = start + end_m.start() if end_m else len(body)
        raw = body[start:end]

        items: list[str] = []
        para_lines: list[str] = []

        def flush_para() -> None:
            nonlocal para_lines
            if not para_lines:
                return
            para = clean_or_none(" ".join(para_lines))
            para_lines = []
            if para and not _services_section_stop(para):
                items.append(para)

        for line in raw.splitlines():
            text = unescape(line).strip()
            if not text:
                flush_para()
                continue
            if _services_section_stop(text):
                flush_para()
                break
            if text.startswith("!"):
                continue
            if text.startswith("- "):
                flush_para()
                bullet = clean_or_none(text[2:].strip())
                if bullet and _services_section_stop(bullet):
                    break
                if bullet:
                    items.append(bullet)
                continue
            # Skip non-stop markdown links (images already handled via !)
            if text.startswith("[") and "](" in text:
                continue
            para_lines.append(text)

        flush_para()
        return items

    # ------------------------------------------------------------------
    # FAQ
    # ------------------------------------------------------------------

    def _parse_faqs(self, body: str) -> dict:
        result: dict = {"faqs": None, "services": None, "genres": None}
        start_m = _FAQ_SECTION_RE.search(body)
        if not start_m:
            raw = section(body, "FAQ", level=2)
        else:
            start = start_m.end()
            # Close on Read more / Read more FAQ, or # / ## (not ### questions)
            nxt = re.search(
                r"(?im)^(?:read more(?:\s+faq)?\s*$|#{1,2}\s+\S)",
                body[start:],
            )
            end = start + nxt.start() if nxt else len(body)
            raw = body[start:end].strip()
        if not raw:
            return result

        faqs: list[FAQ] = []
        services: list[str] = []
        genres: list[str] = []
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
            if title.lower() in _FAQ_NOISE or title.lower().startswith("read more"):
                break
            content_parts: list[str] = []
            stop_section = False
            for ln in lines[1:]:
                lower = ln.lower()
                if lower in _FAQ_NOISE or lower.startswith("read more"):
                    stop_section = True
                    break
                if ln.startswith("#"):
                    stop_section = True
                    break
                cleaned_ln = ln[2:].strip() if ln.startswith("- ") else ln
                if cleaned_ln:
                    content_parts.append(cleaned_ln)
            content = (
                clean_or_none(", ".join(content_parts)) if content_parts else None
            )
            faqs.append(FAQ(title=title, content=content, order=order))
            order += 1

            if _SERVICE_FAQ_RE.search(title):
                for item in content_parts:
                    if self._is_service_noise(item):
                        continue
                    if item not in services:
                        services.append(item)
            elif _GENRE_FAQ_RE.search(title):
                for item in content_parts:
                    if item not in genres:
                        genres.append(item)

            if stop_section:
                break

        result["faqs"] = self._none_if_empty(faqs)
        result["services"] = self._none_if_empty(services)
        result["genres"] = self._none_if_empty(genres)
        return result

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def _parse_reviews(self, body: str) -> list[Review] | None:
        # Section heading is "Reviews of <name>"
        m = re.search(
            r"^##\s+Reviews of\s+.+$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not m:
            return None
        start = m.end()
        nxt = re.search(r"^##\s+\S", body[start:], re.MULTILINE)
        end = start + nxt.start() if nxt else len(body)
        raw = body[start:end]

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
            # Drop photo counters / initial letters
            body_lines = [
                ln
                for ln in body_lines
                if not re.fullmatch(r"\+?\d+\s+photos?", ln, re.IGNORECASE)
                and not re.fullmatch(r"[A-Z]", ln)
            ]
            body_text = " ".join(body_lines)
            body_text = re.sub(r"\bRead more\b", "", body_text, flags=re.IGNORECASE)
            body_text = re.sub(r"\s{2,}", " ", body_text).strip()
            if title and body_text:
                # Avoid duplicating when title == body (rare)
                if title == body_text:
                    text = title
                else:
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
    # Team
    # ------------------------------------------------------------------

    def _parse_team(self, body: str) -> list[TeamMember] | None:
        raw = section(body, "Team", level=2)
        if not raw:
            return None
        members: list[TeamMember] = []
        lines = [unescape(ln).strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln and ln.lower() != "meet the team"]
        i = 0
        while i < len(lines):
            line = lines[i]
            # Skip images
            if line.startswith("![") or line.startswith("!"):
                i += 1
                continue
            if line.startswith("["):
                i += 1
                continue
            name = clean_or_none(line)
            role = None
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                if (
                    not nxt.startswith("![")
                    and not nxt.startswith("[")
                    and len(nxt) < 80
                ):
                    role = clean_or_none(nxt)
                    i += 2
                else:
                    i += 1
            else:
                i += 1
            if name:
                members.append(TeamMember(name=name, role=role))
        return self._none_if_empty(members)

    # ------------------------------------------------------------------
    # Map / location
    # ------------------------------------------------------------------

    def _parse_map(
        self, body: str
    ) -> tuple[Location | None, ServiceArea | None]:
        travel_radius: str | None = None
        can_nationwide: bool | None = None
        map_location: Location | None = None
        map_service_area: ServiceArea | None = None

        raw = section(body, "Map", level=2)
        if raw:
            travel_m = _TRAVEL_RE.search(raw)
            if travel_m:
                radius = clean_or_none(travel_m.group("radius"))
                if radius:
                    if "no travel restrictions" in radius.lower():
                        can_nationwide = True
                        travel_radius = radius
                    else:
                        travel_radius = radius
            map_location, map_service_area = self._location_from_map_section(
                raw,
                travel_radius=travel_radius,
                can_nationwide=can_nationwide,
            )

        # 1) Header `[Denver, CO](#map)`  2) breadcrumb city  3) Map address
        location = self._location_from_header(body)
        if location is None:
            location = self._location_from_breadcrumbs(body)
        if location is None:
            location = map_location

        service_area: ServiceArea | None = None
        if location is not None and map_service_area is not None:
            # Keep map travel/zip, but city/state follow the preferred location.
            st_code = None
            if location.state:
                st_code = US_STATE_NAMES.get(location.state.lower())
            service_area = ServiceArea(
                city=location.city,
                state=location.state,
                state_code=st_code or map_service_area.state_code,
                service_pincode=map_service_area.service_pincode,
                travel_radius=travel_radius or map_service_area.travel_radius,
                can_travel_nationwide=(
                    can_nationwide
                    if can_nationwide is not None
                    else map_service_area.can_travel_nationwide
                ),
            )
        elif location is not None:
            st_code = None
            if location.state:
                st_code = US_STATE_NAMES.get(location.state.lower())
            service_area = ServiceArea(
                city=location.city,
                state=location.state,
                state_code=st_code,
                travel_radius=travel_radius,
                can_travel_nationwide=can_nationwide,
            )
        return location, service_area

    def _location_from_map_section(
        self,
        raw: str,
        *,
        travel_radius: str | None,
        can_nationwide: bool | None,
    ) -> tuple[Location | None, ServiceArea | None]:
        location: Location | None = None
        service_area: ServiceArea | None = None
        for line in raw.splitlines():
            text = unescape(line).strip()
            if not text or text.lower() in {"location", "travel range"}:
                continue
            if text.startswith("[") or text.startswith("!"):
                continue
            if _PHONE_LINE_RE.match(text):
                continue
            addr = _ADDRESS_RE.search(text)
            if not addr:
                cs = _CITY_STATE_RE.search(text)
                if cs and location is None:
                    city = clean_or_none(cs.group("city"))
                    st = cs.group("st")
                    state_name = STATE_CODE_TO_NAME.get(st)
                    location = Location(
                        city=city,
                        state=state_name,
                        country=country_for_us_state(
                            state=state_name, state_code=st
                        ),
                        raw_location=text,
                    )
                    service_area = ServiceArea(
                        city=city,
                        state=state_name,
                        state_code=st,
                        travel_radius=travel_radius,
                        can_travel_nationwide=can_nationwide,
                    )
                continue
            city = clean_or_none(addr.group("city2"))
            st = addr.group("st")
            zip_code = addr.group("zip")
            state_name = STATE_CODE_TO_NAME.get(st)
            location = Location(
                city=city,
                state=state_name,
                country=country_for_us_state(state=state_name, state_code=st),
                raw_location=text,
            )
            service_area = ServiceArea(
                city=city,
                state=state_name,
                state_code=st,
                service_pincode=zip_code,
                travel_radius=travel_radius,
                can_travel_nationwide=can_nationwide,
            )
            break
        return location, service_area

    def _location_from_breadcrumbs(self, body: str) -> Location | None:
        """City = last breadcrumb link (e.g. Dublin before the vendor name)."""
        crumbs = self._breadcrumb_labels(body)
        if not crumbs:
            return None
        # Second-to-last overall when business name follows; last link crumb is city.
        city = clean_or_none(crumbs[-1])
        if not city:
            return None
        bare_city = re.sub(r"\s*\([^)]*\)\s*", "", city.lower()).strip()
        if bare_city in {"weddings", "home"} or bare_city in US_STATE_NAMES:
            return None
        if "wedding" in bare_city or "&" in city:
            return None

        state_name: str | None = None
        st_code: str | None = None
        for label in crumbs[:-1]:
            bare = re.sub(r"\s*\([^)]*\)\s*", "", label.lower()).strip()
            if bare in US_STATE_NAMES:
                st_code = US_STATE_NAMES[bare]
                state_name = STATE_CODE_TO_NAME.get(st_code)
                break

        raw = f"{city}, {state_name}" if state_name else city
        return Location(
            city=city,
            state=state_name,
            country=country_for_us_state(state=state_name, state_code=st_code),
            raw_location=raw,
        )

    def _location_from_header(self, body: str) -> Location | None:
        for match in _LINK_RE.finditer(body):
            if match.group("url").strip() != "#map":
                continue
            label = clean_or_none(match.group("label"))
            if not label:
                continue
            cs = _CITY_STATE_RE.search(label)
            if not cs:
                continue
            city = clean_or_none(cs.group("city"))
            st = cs.group("st")
            state_name = STATE_CODE_TO_NAME.get(st)
            return Location(
                city=city,
                state=state_name,
                country=country_for_us_state(state=state_name, state_code=st),
                raw_location=label,
            )
        return None

    def _parse_website(self, html: str | None) -> str | None:
        """Vendor site from HTML ``storefront-summary-website`` ``data-href``."""
        if not html:
            return None
        match = _HTML_WEBSITE_RE.search(html)
        if not match:
            return None
        raw = clean_or_none(match.group("url"))
        if not raw:
            return None
        url = absolute_url(raw)
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        host = parsed.netloc.lower().removeprefix("www.")
        if host == "weddingwire.com" or host.endswith(".weddingwire.com"):
            return None
        if host == "weddingwire.us" or host.endswith(".weddingwire.us"):
            return None
        return strip_tracking_params(url)

    def _parse_phone(self, body: str) -> str | None:
        match = _TEL_RE.search(body)
        if match:
            return self._normalize_phone(match.group("tel").strip())
        # WeddingWire often shows the number as a bare line under Map
        raw = section(body, "Map", level=2)
        if raw:
            for line in raw.splitlines():
                text = unescape(line).strip()
                if _PHONE_LINE_RE.match(text):
                    return self._normalize_phone(text)
        return None

    @staticmethod
    def _normalize_phone(tel: str) -> str | None:
        return sanitize_phone(tel)

    # ------------------------------------------------------------------
    # Social / awards / media
    # ------------------------------------------------------------------

    def _parse_social(self, body: str) -> list[SocialMediaLink] | None:
        links: list[SocialMediaLink] = []
        seen: set[str] = set()
        for match in _LINK_RE.finditer(body):
            raw_url = match.group("url").strip()
            # Fix doubled scheme: https://https://...
            while raw_url.startswith("https://https://") or raw_url.startswith(
                "http://https://"
            ):
                raw_url = re.sub(r"^https?://", "", raw_url, count=1)
            url = absolute_url(raw_url)
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            host = parsed.netloc.lower().removeprefix("www.")
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
            path = parsed.path.rstrip("/").lower()
            if path in {"/weddingwire"} or path.endswith("/weddingwire"):
                continue
            if url in seen:
                continue
            seen.add(url)
            links.append(
                SocialMediaLink(
                    platform_type=platform,
                    platform_url=strip_tracking_params(url),
                )
            )
        return self._none_if_empty(links)

    def _parse_awards(self, body: str) -> list[str] | None:
        if not _AWARD_WINNER_RE.search(body):
            return None
        # Years listed as bullet items near the award badge (before H1)
        h1 = _H1_RE.search(body)
        chunk = body[: h1.start()] if h1 else body[:2500]
        years: list[str] = []
        for match in re.finditer(r"^-\s+(\d{4})\s*$", chunk, re.MULTILINE):
            year = match.group(1)
            if year not in years:
                years.append(year)
        if not years:
            return ["WeddingWire Award Winner"]
        return [f"WeddingWire Award Winner {y}" for y in years]

    def _parse_media(
        self, body: str
    ) -> tuple[list[PortfolioFile] | None, str | None]:
        files: list[PortfolioFile] = []
        seen: set[str] = set()
        profile_picture: str | None = None
        owner_headshot: str | None = None

        # Hero gallery: images from H1 until "Interested in this vendor?"
        h1 = _H1_RE.search(body)
        start = h1.end() if h1 else 0
        cut = body.find("Interested in this vendor?", start)
        if cut < 0:
            about = re.search(
                r"^##\s+About this vendor\s*$",
                body,
                re.MULTILINE | re.IGNORECASE,
            )
            cut = about.start() if about else len(body)
        hero = body[start:cut]

        for match in _IMAGE_RE.finditer(hero):
            raw_url = match.group("url").strip()
            url = absolute_url(raw_url)
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            if "cdn" not in host or "weddingwire.com" not in host:
                continue
            if "/vendor/" not in url:
                continue
            canonical = self._strip_image_query(url)
            if "/original/" in canonical and owner_headshot is None:
                owner_headshot = canonical
            if canonical in seen:
                continue
            seen.add(canonical)
            files.append(PortfolioFile(type="image", url=canonical))

        # Owner headshot from Team / sidebar if not in hero
        if owner_headshot is None:
            for match in _IMAGE_RE.finditer(body):
                url = absolute_url(match.group("url").strip())
                if not url:
                    continue
                if "/original/" in url and "weddingwire.com" in url:
                    owner_headshot = self._strip_image_query(url)
                    break

        profile_picture = owner_headshot or (files[0].url if files else None)
        return self._none_if_empty(files), profile_picture
