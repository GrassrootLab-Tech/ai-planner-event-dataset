from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import unquote, urlparse, parse_qs, urlencode, urlunparse

from vendor_profiles.models.vendor_profile import (
    Category,
    Highlight,
    Location,
    LogisticDetails,
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
    parse_money,
    strip_media_variant,
    unescape,
)
from vendor_profiles.parsers.us_states import STATE_CODE_TO_NAME, country_for_us_state

_H1_RE = re.compile(r"^#\s+(?P<name>.+)\s*$", re.MULTILINE)
_RATING_RE = re.compile(
    r"(?P<rating>\d+(?:\.\d+)?)\s+out of\s+5(?:\.0)?\s+stars?\s+and\s+"
    r"(?P<count>[\d,]+)\s+reviews?",
    re.IGNORECASE,
)
_STARTING_PRICE_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?\s+starting\s+price",
    re.IGNORECASE,
)
_USUAL_SPEND_RE = re.compile(
    r"Couples\s+usually\s+spend\s+(\$[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_YEARS_RE = re.compile(
    r"(?P<years>\d+)\+?\s+years?\s+in\s+business",
    re.IGNORECASE,
)
_SPEAKS_RE = re.compile(r"^Speaks\s+(?P<langs>.+)$", re.IGNORECASE | re.MULTILINE)
_RESPONSE_RE = re.compile(
    r"Typically\s+responds\s+within\s+\*?\*?(?P<body>[^*\n]+)",
    re.IGNORECASE,
)
_TRAVEL_NATIONWIDE_RE = re.compile(
    r"Travel\s+area:\s*No\s+travel\s+restrictions",
    re.IGNORECASE,
)
_TEL_RE = re.compile(r"\[([^\]]*)\]\(tel:(?P<tel>[^)\s]+)\)")
_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CITY_STATE_RE = re.compile(
    r"(?P<city>[A-Za-z .'-]+),\s*(?P<st>[A-Z]{2})\b"
)
_SLUG_LOC_RE = re.compile(
    r"-(?P<city>[a-z0-9]+(?:-(?:village|springs|heights|beach|park|hills|"
    r"hill|falls|city|grove|creek|ridge))?)"
    r"-(?P<st>[a-z]{2})-\d+/?$",
    re.IGNORECASE,
)
_CHIP_SPLIT_RE = re.compile(r"\.(?=[A-Z])")
_US_DATE_RE = re.compile(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})$")
_FULL_REVIEW_RE = re.compile(
    r"^Avatar[A-Za-z0-9]*\s*\n+"
    r"(?P<name>[^\n]+)\n+"
    r"(?P<rating>\d+(?:\.\d+)?)\n+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\n+"
    r"(?P<body>.*?)(?=^Avatar[A-Za-z0-9]*\s*$|^Response from |^View more\s*$"
    r"|^Circle Message\s*$|^Contact\s*$|^### |\Z)",
    re.DOTALL | re.MULTILINE,
)
_COMPACT_REVIEW_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*[•·]\s*(?P<name>[^\n]+)\n+"
    r"(?P<body>.*?)(?=^\d{1,2}/\d{1,2}/\d{4}\s*[•·]|^Contact\s*$"
    r"|^### |\Z)",
    re.DOTALL | re.MULTILINE,
)
_BREADCRUMB_LINK_RE = re.compile(
    r"^\d+\.\s+\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)",
    re.MULTILINE,
)
_AWARD_YEARS_RE = re.compile(
    r"^(?P<years>(?:\d{4}\.)+\d{4})(?:\.(?P<more>\+\d+\s+more\.?))?\s*$",
    re.MULTILINE,
)

_ANCHOR_STOPS = (
    "Details",
    "Awards and Affiliations",
    "Meet the team",
    "Availability",
    "Reviews",
    "Contact",
    "What couples loved about this vendor",
    "About this vendor",
    "Photo Shoot Types",
    "Photo & Video",
    "Photo & Video Styles",
    "Music Genres",
    "Music Services",
    "Instruments",
    "Equipment",
    "Wedding Activities",
)

_DETAIL_GROUP_LABELS = (
    "Equipment",
    "Instruments",
    "Music Genres",
    "Music Services",
    "Photo Shoot Types",
    "Photo & Video",
    "Photo & Video Styles",
    "Wedding Activities",
)

_GENRE_STYLE_GROUPS = frozenset({"Music Genres", "Photo & Video Styles"})
_EQUIPMENT_GROUPS = frozenset({"Equipment"})
_SERVICE_GROUPS = frozenset(
    {
        "Music Services",
        "Instruments",
        "Photo & Video",
        "Photo Shoot Types",
        "Wedding Activities",
    }
)

_ABOUT_NOISE = frozenset(
    {
        "hall of fame award",
        "the knot peace of mind badge",
        "the knot peace of mind",
        "learn more",
        "message vendor",
        "no business details yet",
        "no team details yet",
        "read more",
        "book with confidence knowing we're in your corner. if plans change, "
        "the knot peace of mind helps with rebooking support and cost assistance "
        "so you can stay focused on the moments that matter most.",
    }
)

_BODY_START = "[Skip to Main Content]"
_BODY_ENDS = (
    "### Wedding vendors in",
    "Wedding vendors in",
    "## Why use The Knot",
)


class TheKnotProfileParser(VendorProfileParser):
    source_host = "theknot.com"

    def parse(
        self,
        page_url: str,
        markdown: str,
        *,
        html: str | None = None,
    ) -> VendorProfile:
        del html  # The Knot contact fields are in markdown
        body = self._profile_body(markdown)
        business_name = self._parse_business_name(body)
        if not business_name:
            raise ValueError("business_name is required")

        details = self._parse_details(body)
        services = details.get("services")
        genres = details.get("genres")
        equipment = details.get("equipment")
        team = self._parse_team(body)
        logistic = None
        if equipment or team:
            logistic = LogisticDetails(
                equipment_provided=equipment,
                team_size=len(team) if team else None,
            )
        location, service_area = self._parse_location(body, page_url)
        pricing = self._parse_pricing(body)
        portfolio, profile_picture = self._parse_media(body)
        about_facts = self._parse_about_facts(body)

        return VendorProfile(
            business_name=business_name,
            slug=self.slug_from_url(page_url),
            tagline=self._parse_tagline(body),
            # Breadcrumbs sit after the profile body cut — use full markdown
            categories=self._parse_categories(markdown, services),
            description=self._parse_description(body),
            reasons_to_book_me=self._parse_chips(body),
            services_provided=services,
            genres_or_styles=genres,
            languages=about_facts.get("languages"),
            years_in_business=about_facts.get("years"),
            response_time=about_facts.get("response_time"),
            location=location,
            service_area=service_area,
            phone_number=self._parse_phone(body),
            website=self._parse_website(body),
            social_media=self._parse_social(body),
            prices=pricing.get("prices"),
            price_range=pricing.get("price_range"),
            packages=pricing.get("packages"),
            rating_average=self._parse_rating(body),
            reviews=self._parse_reviews(body),
            awards=self._parse_awards(body),
            verified_badges=self._parse_badges(body),
            team=team,
            logistic_details=logistic,
            portfolio_files=portfolio,
            profile_picture=profile_picture,
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
        end = len(markdown)
        for marker in _BODY_ENDS:
            idx = markdown.find(marker, start)
            if 0 <= idx < end:
                end = idx
        return markdown[start:end].strip()

    @staticmethod
    def slug_from_url(page_url: str) -> str | None:
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
    def _anchor_section(body: str, anchor: str, stops: tuple[str, ...] | None = None) -> str:
        """Slice between a bare anchor line and the next stop line / heading."""
        stop_names = stops or _ANCHOR_STOPS
        pattern = re.compile(
            rf"^(?:###\s+)?{re.escape(anchor)}\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        match = pattern.search(body)
        if not match:
            return ""
        start = match.end()
        stop_alts = "|".join(re.escape(s) for s in stop_names if s.lower() != anchor.lower())
        next_re = re.compile(
            rf"^(?:###\s+(?:\S.+)|(?:{stop_alts})\s*)$",
            re.IGNORECASE | re.MULTILINE,
        )
        nxt = next_re.search(body, start)
        end = nxt.start() if nxt else len(body)
        return body[start:end].strip()

    @staticmethod
    def _parse_us_date(text: str) -> date | None:
        match = _US_DATE_RE.match((text or "").strip())
        if not match:
            return None
        try:
            return date(
                int(match.group("y")),
                int(match.group("m")),
                int(match.group("d")),
            )
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Identity / header
    # ------------------------------------------------------------------

    def _parse_business_name(self, body: str) -> str | None:
        match = _H1_RE.search(body)
        if not match:
            return None
        return clean_or_none(match.group("name"))

    def _parse_tagline(self, body: str) -> str | None:
        h1 = _H1_RE.search(body)
        if not h1:
            return None
        # Tagline sits between H1 and the star-rating link
        rating = re.search(
            r"\[\d+(?:\.\d+)?\s+out of\s+5",
            body[h1.end() :],
            re.IGNORECASE,
        )
        if not rating:
            return None
        chunk = body[h1.end() : h1.end() + rating.start()]
        candidates: list[str] = []
        for line in chunk.splitlines():
            text = unescape(line).strip()
            if not text:
                continue
            lower = text.lower()
            if lower in {"share", "booked?", "request quote"}:
                continue
            if text.startswith("[") or text.startswith("!"):
                continue
            if lower.startswith("the knot peace of mind"):
                continue
            candidates.append(text)
        # Prefer a descriptive line that isn't a location/price chip
        for text in candidates:
            if parse_money(text):
                continue
            if _CITY_STATE_RE.search(text):
                continue
            if text.lower().startswith("travel area"):
                continue
            return text
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
        self, body: str, services: list[str] | None
    ) -> list[Category] | None:
        primary = None
        # Prefer numbered breadcrumb item #2 (category without geo)
        for match in _BREADCRUMB_LINK_RE.finditer(body):
            label = clean_or_none(match.group("label"))
            if not label:
                continue
            # Skip the root "Wedding Vendors"
            if label.lower() == "wedding vendors":
                continue
            # First category-level crumb (e.g. DJs, Wedding Bands)
            primary = label
            break
        if not primary:
            # Sparse profiles: bare text after Wedding Vendors crumb
            crumb = re.search(
                r"1\.\s+\[Wedding Vendors\][^\n]*\n(?:\s*/\s*\n)*\s*"
                r"(?P<label>[A-Za-z][^\n]+)",
                body,
                re.IGNORECASE,
            )
            if crumb:
                label = clean_or_none(crumb.group("label"))
                if label and not label.startswith("[") and "photos" not in label.lower():
                    primary = label
        if not primary:
            return None
        sub = (services or [primary])[0]
        return [Category(primary_category=primary, sub_category=sub)]

    def _parse_chips(self, body: str) -> list[Highlight] | None:
        raw = self._anchor_section(body, "What couples loved about this vendor")
        if not raw:
            return None
        # First non-empty paragraph is the chip strip
        text = None
        for para in re.split(r"\n\s*\n", raw):
            cleaned = clean_or_none(para.replace("\n", " "))
            if cleaned:
                text = cleaned
                break
        if not text:
            return None
        chips = [c.strip(" .") for c in _CHIP_SPLIT_RE.split(text) if c.strip(" .")]
        if not chips:
            return None
        return [Highlight(reason_description=c) for c in chips]

    # ------------------------------------------------------------------
    # About
    # ------------------------------------------------------------------

    def _parse_description(self, body: str) -> str | None:
        raw = self._anchor_section(body, "About this vendor")
        if not raw:
            # Also try ### form via section-like match already covered by
            # _anchor_section's optional ### prefix
            return None

        # Cut trailing inline "Details <Label> …" blob when present
        inline_cut = re.search(
            r"\bDetails\s+(?:Instruments|Equipment|Music Genres|Photo)\b",
            raw,
            re.IGNORECASE,
        )
        if inline_cut:
            raw = raw[: inline_cut.start()]

        # Stop at Peace of Mind / Prices heading remnants
        for marker in (
            "The Knot Peace of Mind Badge",
            "The Knot Peace of Mind",
            "### Prices",
            "No business details yet",
            "No team details yet",
        ):
            idx = raw.find(marker)
            if idx >= 0 and marker.startswith("No "):
                # Drop the placeholder line but keep prior prose
                continue
            if idx >= 0 and not marker.startswith("No "):
                raw = raw[:idx]

        lines: list[str] = []
        for line in raw.splitlines():
            text = unescape(line).strip()
            if not text:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            lower = text.lower()
            if lower in _ABOUT_NOISE:
                continue
            if lower.startswith("award winner"):
                continue
            if lower.startswith("thanks to recommendations"):
                continue
            if text.startswith("![") or text.startswith("["):
                continue
            if _RESPONSE_RE.search(text):
                continue
            if _YEARS_RE.search(text):
                continue
            if _SPEAKS_RE.match(text):
                continue
            if re.search(r"small team\s*\(", lower):
                continue
            # Skip ALL-CAPS owner name / role lines (short, no period)
            if text.isupper() and len(text) < 80 and "." not in text:
                continue
            if re.fullmatch(r"[A-Za-z .\"'&-]+", text) and text == text.title() and len(text) < 40:
                # Likely a role like "Events Director" when paired near owner — skip short title-case solo lines without verbs
                if " " in text and not any(
                    w in lower
                    for w in ("is", "are", "we", "our", "the", "a ", "for", "with")
                ):
                    # Keep if it looks like prose; role lines are 1-3 words
                    if len(text.split()) <= 3:
                        continue
            lines.append(text)

        # Drop trailing empty and placeholder lines
        while lines and (not lines[-1] or lines[-1].lower() in _ABOUT_NOISE):
            lines.pop()
        text = "\n".join(lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Join soft single newlines into paragraphs for cleaner description
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        cleaned_paras: list[str] = []
        for p in paras:
            if p.lower() in {"no business details yet", "no team details yet"}:
                continue
            cleaned_paras.append(re.sub(r"\s*\n\s*", " ", p))
        return "\n\n".join(cleaned_paras) or None

    def _parse_about_facts(self, body: str) -> dict:
        out: dict = {
            "languages": None,
            "years": None,
            "response_time": None,
        }
        speaks = _SPEAKS_RE.search(body)
        if speaks:
            langs = [
                clean_or_none(p)
                for p in speaks.group("langs").split(",")
            ]
            out["languages"] = self._none_if_empty([x for x in langs if x])

        years_m = _YEARS_RE.search(body)
        if years_m:
            years = int(years_m.group("years"))
            out["years"] = YearsInBusiness(
                start_year=datetime.now().year - years
            )

        resp = _RESPONSE_RE.search(body)
        if resp:
            out["response_time"] = clean_or_none(
                f"Typically responds within {resp.group('body').strip()}"
            )
        return out

    # ------------------------------------------------------------------
    # Details groups
    # ------------------------------------------------------------------

    def _parse_details(self, body: str) -> dict:
        raw = self._anchor_section(
            body,
            "Details",
            stops=(
                "Awards and Affiliations",
                "Meet the team",
                "Availability",
                "Reviews",
                "Contact",
            ),
        )
        result: dict = {
            "services": None,
            "genres": None,
            "equipment": None,
        }
        if not raw:
            return result

        # Normalize Photo &amp; Video labels
        raw_norm = unescape(raw)
        groups: dict[str, list[str]] = {}
        current: str | None = None
        for line in raw_norm.splitlines():
            text = line.strip()
            if not text:
                continue
            # Match known group labels (with optional &amp;)
            label = None
            for known in _DETAIL_GROUP_LABELS:
                if text.lower() == known.lower():
                    label = known
                    break
                if text.lower() == known.lower().replace("&", "&amp;").lower():
                    label = known
                    break
            if label:
                current = label
                groups.setdefault(current, [])
                continue
            if current is None:
                continue
            if text.startswith("- "):
                item = clean_or_none(text[2:])
            else:
                item = clean_or_none(text)
            if not item:
                continue
            # Stop if we hit another section anchor mid-stream
            if item in _ANCHOR_STOPS or item.startswith("Why were"):
                break
            groups[current].append(item)

        services: list[str] = []
        genres: list[str] = []
        equipment: list[str] = []
        instruments: list[str] = []
        seen_svc: set[str] = set()
        for label, items in groups.items():
            if label in _GENRE_STYLE_GROUPS:
                for item in items:
                    if item not in genres:
                        genres.append(item)
            elif label in _EQUIPMENT_GROUPS:
                for item in items:
                    if item not in equipment:
                        equipment.append(item)
            elif label == "Instruments":
                for item in items:
                    if item.lower() not in seen_svc:
                        seen_svc.add(item.lower())
                        instruments.append(item)
            elif label in _SERVICE_GROUPS:
                for item in items:
                    key = item.lower()
                    if key in seen_svc:
                        continue
                    seen_svc.add(key)
                    services.append(item)
        # Instruments last so sub_category prefers Music Services / Photo items
        services.extend(instruments)

        result["services"] = self._none_if_empty(services)
        result["genres"] = self._none_if_empty(genres)
        result["equipment"] = self._none_if_empty(equipment)
        return result

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def _parse_pricing(self, body: str) -> dict:
        result: dict = {"prices": None, "price_range": None, "packages": None}
        amount = None
        start_m = _STARTING_PRICE_RE.search(body)
        if start_m:
            money = parse_money(start_m.group(0))
            if money:
                amount = money[0]
        if amount is None:
            usual = _USUAL_SPEND_RE.search(body)
            if usual:
                money = parse_money(usual.group(1))
                if money:
                    amount = money[0]
        if amount is not None:
            result["prices"] = [Price(amount=amount, per="event")]
            result["price_range"] = PriceRange(min_price=amount)

        result["packages"] = self._parse_packages(body)
        return result

    def _parse_packages(self, body: str) -> list[Package] | None:
        """Parse package cards under ### Prices & packages."""
        prices_m = re.search(
            r"^###\s+Prices\s*&(?:amp;)?\s*packages\s*$",
            body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not prices_m:
            return None
        start = prices_m.end()
        # Window ends at footnotes / Details / THE END marker
        stop_m = re.search(
            r"^(?:Details|<!--THE END-->|-\s+Starting prices|"
            r"Couples usually spend|Are you interested|"
            r"Looking for more pricing)\s*",
            body[start:],
            re.MULTILINE | re.IGNORECASE,
        )
        raw = body[start : start + stop_m.start()] if stop_m else body[start:]
        if "no pricing details yet" in unescape(raw).lower():
            return None

        # Prefer bullet cards when present (carousel); else prose cards
        bullet_start = re.search(r"(?m)^-\s+\S", raw)
        if bullet_start:
            packages = self._packages_from_bullets(raw[bullet_start.start() :])
            if packages:
                return packages
        return self._packages_from_prose(raw)

    @classmethod
    def _packages_from_bullets(cls, raw: str) -> list[Package] | None:
        packages: list[Package] = []
        # Split on top-level "- " lines
        blocks = re.split(r"(?m)^-\s+", raw)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = [
                unescape(ln).strip()
                for ln in block.splitlines()
                if unescape(ln).strip()
            ]
            pkg = cls._package_from_lines(lines)
            if pkg:
                packages.append(pkg)
        return cls._none_if_empty(packages)

    @classmethod
    def _packages_from_prose(cls, raw: str) -> list[Package] | None:
        packages: list[Package] = []
        lines = [unescape(ln).strip() for ln in raw.splitlines()]
        current: list[str] = []
        for line in lines:
            if not line:
                continue
            lower = line.lower()
            if lower.startswith("couples usually spend"):
                continue
            if lower in {
                "showing slides 1 to 3 out of 3",
                "get a personalized quote",
                "reach out and share your wedding details.",
                "are you interested?",
                "looking for more pricing details?",
                "no pricing details yet",
            }:
                continue
            if lower.startswith("showing slides"):
                continue
            money = parse_money(line)
            # New card starts on a non-money, non-noise line when previous card
            # already has a price
            if (
                current
                and money is None
                and lower not in {"starting price", "* * *", "most popular."}
                and not re.match(r"^\d+\s+hours?$", lower)
                and any(parse_money(x) for x in current)
            ):
                pkg = cls._package_from_lines(current)
                if pkg:
                    packages.append(pkg)
                current = [line]
                continue
            current.append(line)
        if current:
            pkg = cls._package_from_lines(current)
            if pkg:
                packages.append(pkg)
        return cls._none_if_empty(packages)

    @staticmethod
    def _package_from_lines(lines: list[str]) -> Package | None:
        skip = {"starting price", "* * *", "most popular.", "most popular"}
        cleaned = [ln for ln in lines if ln.lower() not in skip]
        if not cleaned:
            return None
        title: str | None = None
        amount: float | None = None
        offerings: list[str] = []
        for line in cleaned:
            lower = line.lower()
            if lower.startswith("couples usually spend"):
                continue
            if lower.startswith("starting prices may not"):
                continue
            money = parse_money(line)
            if money and amount is None and (
                line.strip().startswith("$")
                or re.fullmatch(r"\$[\d,]+(?:\.\d+)?", line.strip())
            ):
                amount = money[0]
                continue
            if title is None:
                title = line
                continue
            offerings.append(line)
        # Require a real dollar amount — drops footnotes / empty pricing blurbs
        if amount is None or title is None:
            return None
        return Package(
            title=clean_or_none(title),
            prices=[Price(amount=amount, per="event")],
            offerings=offerings,
        )

    # ------------------------------------------------------------------
    # Location / contact
    # ------------------------------------------------------------------

    def _parse_location(
        self, body: str, page_url: str
    ) -> tuple[Location | None, ServiceArea | None]:
        location: Location | None = None
        service_area: ServiceArea | None = None
        nationwide = bool(_TRAVEL_NATIONWIDE_RE.search(body))

        # Prefer Contact / Service area pipe line
        contact_raw = self._anchor_section(
            body,
            "Contact",
            stops=("### Wedding vendors in", "Wedding vendors in", "## Why use The Knot"),
        )
        if not contact_raw:
            contact_raw = self._anchor_section(
                body,
                "Service area & Contact info",
                stops=("### Wedding vendors in", "Wedding vendors in", "## Why use The Knot"),
            )
            if not contact_raw:
                # ### Service area &amp; Contact info
                m = re.search(
                    r"^###\s+Service area\s*&(?:amp;)?\s*Contact info\s*$",
                    body,
                    re.MULTILINE | re.IGNORECASE,
                )
                if m:
                    start = m.end()
                    nxt = re.search(r"^###\s+\S|^##\s+\S", body[start:], re.MULTILINE)
                    end = start + nxt.start() if nxt else len(body)
                    contact_raw = body[start:end].strip()

        pipe_line = None
        for line in (contact_raw or "").splitlines():
            text = unescape(line).strip()
            if "|" in text and not text.startswith("["):
                pipe_line = text
                break

        if pipe_line:
            left, _, right = pipe_line.partition("|")
            left = left.strip()
            right = right.strip()
            loc_m = _CITY_STATE_RE.search(left)
            if loc_m:
                city = clean_or_none(loc_m.group("city"))
                st = loc_m.group("st")
                state_name = STATE_CODE_TO_NAME.get(st)
                location = Location(
                    city=city,
                    state=state_name,
                    country=country_for_us_state(state=state_name, state_code=st),
                    raw_location=f"{city}, {st}" if city else left,
                )
            else:
                location = Location(raw_location=left or None)
            svc_m = _CITY_STATE_RE.search(right) if right else None
            if svc_m:
                service_area = ServiceArea(
                    city=clean_or_none(svc_m.group("city")),
                    state=STATE_CODE_TO_NAME.get(svc_m.group("st")),
                    state_code=svc_m.group("st"),
                    can_travel_nationwide=True if nationwide else None,
                )
            elif right:
                # e.g. "Denver, Colorado Springs, Boulder, Front Range Area"
                first_city = right.split(",")[0].strip()
                service_area = ServiceArea(
                    city=clean_or_none(first_city) if first_city else None,
                    can_travel_nationwide=True if nationwide else None,
                )

        # Header service-area line (e.g. "Denver, CO and All Surrounding Areas")
        if location is None or service_area is None:
            h1 = _H1_RE.search(body)
            header_chunk = body[h1.end() : h1.end() + 1200] if h1 else body[:1500]
            for line in header_chunk.splitlines():
                text = unescape(line).strip()
                if not text or text.startswith("[") or text.startswith("!"):
                    continue
                lower = text.lower()
                if lower in {"share", "booked?", "request quote", "service area"}:
                    continue
                if lower.startswith("the knot peace of mind"):
                    continue
                if parse_money(text) or lower.startswith("travel area"):
                    continue
                if lower.startswith("booking in"):
                    continue
                city_m = _CITY_STATE_RE.search(text)
                if city_m and ("surrounding" in lower or "area" in lower or "and" in lower):
                    city = clean_or_none(city_m.group("city"))
                    st = city_m.group("st")
                    if service_area is None:
                        service_area = ServiceArea(
                            city=city,
                            state=STATE_CODE_TO_NAME.get(st),
                            state_code=st,
                            can_travel_nationwide=True if nationwide else None,
                        )
                    if location is None:
                        state_name = STATE_CODE_TO_NAME.get(st)
                        location = Location(
                            city=city,
                            state=state_name,
                            country=country_for_us_state(
                                state=state_name, state_code=st
                            ),
                            raw_location=f"{city}, {st}",
                        )
                    break
                # Multi-city line without state code
                if "," in text and not text.startswith("http") and len(text) < 120:
                    if any(
                        w in lower
                        for w in ("denver", "colorado", "area", "boulder", "springs")
                    ):
                        first = text.split(",")[0].strip()
                        if service_area is None and first:
                            service_area = ServiceArea(
                                city=clean_or_none(first),
                                can_travel_nationwide=True if nationwide else None,
                            )
                        break

        # URL slug fallback when location is missing or city-less
        if location is None or not location.city:
            slug = self.slug_from_url(page_url) or ""
            slug_m = _SLUG_LOC_RE.search(slug)
            if slug_m:
                city = slug_m.group("city").replace("-", " ").title()
                st = slug_m.group("st").upper()
                state_name = STATE_CODE_TO_NAME.get(st)
                location = Location(
                    city=city,
                    state=state_name,
                    country=country_for_us_state(state=state_name, state_code=st),
                    raw_location=f"{city}, {st}",
                )

        if nationwide and service_area is None:
            service_area = ServiceArea(can_travel_nationwide=True)
        elif nationwide and service_area is not None:
            service_area = service_area.model_copy(
                update={"can_travel_nationwide": True}
            )

        return location, service_area

    def _parse_phone(self, body: str) -> str | None:
        match = _TEL_RE.search(body)
        if not match:
            return None
        raw = unquote(match.group("tel")).strip()
        # Prefer visible label if present
        label = clean_or_none(match.group(1))
        if label and re.search(r"\d", label):
            return label
        return clean_or_none(raw)

    def _parse_website(self, body: str) -> str | None:
        for match in _LINK_RE.finditer(body):
            label = unescape(match.group("label") or "").strip().lower()
            if label != "website":
                continue
            url = absolute_url(match.group("url").strip())
            if not url:
                continue
            # Strip tracking params
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            keep = {
                k: v
                for k, v in qs.items()
                if k.lower() not in {"utm_source", "utm_medium", "utm_campaign", "ref"}
            }
            clean = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    urlencode(keep, doseq=True),
                    "",
                )
            )
            return clean.rstrip("?") or None
        return None

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
            if url in seen:
                continue
            seen.add(url)
            links.append(SocialMediaLink(platform_type=platform, platform_url=url))
        return self._none_if_empty(links)

    # ------------------------------------------------------------------
    # Awards / badges / team
    # ------------------------------------------------------------------

    def _parse_awards(self, body: str) -> list[str] | None:
        raw = self._anchor_section(
            body,
            "Awards and Affiliations",
            stops=("Meet the team", "Availability", "Reviews", "Contact"),
        )
        if not raw:
            return None
        awards: list[str] = []
        year_line = None
        skip_explain = False
        for line in raw.splitlines():
            text = unescape(line).strip()
            if not text:
                continue
            lower = text.lower()
            if lower.startswith("why were they selected"):
                skip_explain = True
                continue
            if lower in {
                "best of weddings award",
                "hall of fame award",
                "join couples who chose award-winning vendors for their wedding",
                "message vendor",
            }:
                skip_explain = False
                continue
            if skip_explain:
                # Resume when the next award badge title appears
                if lower in {"hall of fame", "best of weddings"}:
                    skip_explain = False
                else:
                    continue
            if lower == "hall of fame":
                if "Hall of Fame" not in awards:
                    awards.append("Hall of Fame")
                continue
            if lower == "best of weddings":
                continue
            if lower.startswith("earned by winning"):
                continue
            years_m = _AWARD_YEARS_RE.match(text)
            if years_m:
                year_line = text
                continue
            if "best of weddings" in lower or "hall of fame" in lower:
                if text not in awards:
                    awards.append(text)
                continue
            # Skip long explanatory prose
            if len(text) > 80:
                continue

        if year_line:
            years_m = _AWARD_YEARS_RE.match(year_line)
            if years_m:
                years = years_m.group("years").split(".")
                more = years_m.group("more")
                flat = ", ".join(years)
                if more:
                    flat = f"{flat} ({more.rstrip('.')})"
                awards.append(f"Best of Weddings {flat}")

        return self._none_if_empty(awards)

    def _parse_badges(self, body: str) -> list[str] | None:
        if re.search(r"The Knot Peace of Mind", body):
            return ["The Knot Peace of Mind"]
        return None

    def _parse_team(self, body: str) -> list[TeamMember] | None:
        raw = self._anchor_section(
            body,
            "Meet the team",
            stops=("Availability", "Reviews", "Contact"),
        )
        if not raw:
            return None
        # Strip images
        raw = _IMAGE_RE.sub("", raw).strip()
        lines = [unescape(l).strip() for l in raw.splitlines()]
        lines = [l for l in lines if l]
        if not lines:
            return None

        name = lines[0] if lines else None
        if name and re.match(
            r"^Showing slide number \d+ out of \d+$",
            name.strip(),
            re.IGNORECASE,
        ):
            return None
        role = None
        bio_start = 1
        if len(lines) > 1 and len(lines[1].split()) <= 4 and "." not in lines[1]:
            role = lines[1]
            bio_start = 2
        bio = clean_or_none(" ".join(lines[bio_start:])) if bio_start < len(lines) else None
        if not name and not role and not bio:
            return None
        return [TeamMember(name=clean_or_none(name), role=clean_or_none(role), bio=bio)]

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def _join_review_body(self, body: str) -> str | None:
        text = unescape(body or "")
        # Drop vendor responses
        resp = re.search(r"^Response from\s+", text, re.MULTILINE | re.IGNORECASE)
        if resp:
            text = text[: resp.start()]
        text = re.sub(r"\bRead more\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bCircle Message\b.*", "", text, flags=re.IGNORECASE | re.DOTALL)
        # Rejoin truncated "…\n\ncontinuation" soft splits
        text = re.sub(r"\.\.\.\s*\n+", "... ", text)
        text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        # Drop trailing ellipsis artifact if body continues
        return text or None

    def _parse_reviews(self, body: str) -> list[Review] | None:
        raw = self._anchor_section(
            body,
            "Reviews",
            stops=("Contact", "### Service area", "### Wedding vendors in"),
        )
        if not raw:
            return None

        reviews: list[Review] = []
        seen: set[tuple[str | None, str | None]] = set()

        for match in _FULL_REVIEW_RE.finditer(raw):
            name = clean_or_none(match.group("name"))
            try:
                rating = float(match.group("rating"))
            except ValueError:
                rating = None
            review_date = self._parse_us_date(match.group("date"))
            text = self._join_review_body(match.group("body"))
            key = (name, match.group("date"))
            if key in seen:
                continue
            seen.add(key)
            if not text and not name:
                continue
            reviews.append(
                Review(
                    reviewer_name=name,
                    rating=rating,
                    text=text,
                    review_date=review_date,
                )
            )

        if not reviews:
            for match in _COMPACT_REVIEW_RE.finditer(raw):
                name = clean_or_none(match.group("name"))
                review_date = self._parse_us_date(match.group("date"))
                text = self._join_review_body(match.group("body"))
                key = (name, match.group("date"))
                if key in seen:
                    continue
                seen.add(key)
                if not text and not name:
                    continue
                reviews.append(
                    Review(
                        reviewer_name=name,
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

        # Logo can sit in Contact (after Reviews) — scan whole body
        for match in _IMAGE_RE.finditer(body):
            alt = unescape(match.group("alt") or "").lower()
            if "vendor logo" not in alt:
                continue
            url = absolute_url(match.group("url").strip())
            if url:
                profile_picture = strip_media_variant(url).split("?", 1)[0]
                break

        # Gallery: images from page top until About / Details
        cut_at = len(body)
        for pattern in (
            r"^###\s+About this vendor\s*$",
            r"^About this vendor\s*$",
            r"^Details\s*$",
            r"^Reviews\s*$",
        ):
            m = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
            if m and m.start() < cut_at:
                cut_at = m.start()
        gallery = body[:cut_at]

        for match in _IMAGE_RE.finditer(gallery):
            alt = unescape(match.group("alt") or "")
            raw_url = match.group("url").strip()
            url = absolute_url(raw_url)
            if not url:
                continue
            alt_lower = alt.lower()
            if "vendor logo" in alt_lower:
                continue
            # Skip review thumbs and tiny crops / category tiles
            if any(
                s in url
                for s in ("~sc_120.120", "~sc_90.90", "~sc_140.100", "~sc_250.100")
            ):
                continue
            host = urlparse(url).netloc.lower()
            if "xogrp.com" not in host:
                continue
            if "youtube.com" in url or "img.youtube.com" in url:
                continue
            canonical = strip_media_variant(url).split("?", 1)[0]
            if canonical in seen:
                continue
            seen.add(canonical)
            files.append(PortfolioFile(type="image", url=canonical))

        # Fallback profile picture: first ![Vendor](…) in about
        if profile_picture is None:
            for match in _IMAGE_RE.finditer(body):
                alt = unescape(match.group("alt") or "").lower()
                if alt in {"vendor", "meet the owner"}:
                    url = absolute_url(match.group("url").strip())
                    if url:
                        profile_picture = strip_media_variant(url).split("?", 1)[0]
                        break

        return self._none_if_empty(files), profile_picture
