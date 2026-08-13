from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse

from vendor_profiles.models.vendor_profile import (
    Category,
    DayAvailability,
    FAQ,
    Highlight,
    Location,
    LogisticDetails,
    PortfolioFile,
    Price,
    PriceRange,
    Review,
    ServiceArea,
    SocialMediaLink,
    TimeSlot,
    VendorProfile,
    WeeklyHours,
    YearsInBusiness,
)
from vendor_profiles.parsers.base import VendorProfileParser
from vendor_profiles.parsers.text import (
    clean_or_none,
    paragraphs,
    parse_date,
    parse_money,
    unescape,
)
from vendor_profiles.parsers.us_states import STATE_CODE_TO_NAME, country_for_us_state

_H1_RE = re.compile(r"^#\s+(?P<name>.+)\s*$", re.MULTILINE)
_TAGLINE_RE = re.compile(
    r"^(?P<label>.+?)\s*[•·]\s*(?P<zip>\d{5}(?:-\d{4})?)\s*$",
    re.MULTILINE,
)
_BREADCRUMB_CAT_RE = re.compile(
    r"^2\.\s+\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)\s*$",
    re.MULTILINE,
)
_RATING_RE = re.compile(
    r"(?:Excellent|Exceptional|Good|Great)?\s*(?P<rating>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PRICE_BLOCK_RE = re.compile(
    r"^(?P<price>\$[\d,]+(?:\.\d+)?(?:/\w+)?)\s*\n+"
    r"(?P<label>(?:Starting|Estimated)\s+price)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RESPONSE_RE = re.compile(r"^Responds\s+.+$", re.IGNORECASE | re.MULTILINE)
_HIRED_RE = re.compile(r"^Hired\s+(?P<n>\d+)\s+times?\s*$", re.IGNORECASE)
_SERVES_RE = re.compile(
    r"^Serves\s+(?P<city>.+),\s*(?P<st>[A-Z]{2})\s*$",
    re.IGNORECASE,
)
_EMPLOYEES_RE = re.compile(
    r"^(?P<n>\d+)\s+employees?\s*$",
    re.IGNORECASE,
)
_YEARS_RE = re.compile(
    r"^(?P<n>\d+)\s+years?\s+in\s+business\s*$",
    re.IGNORECASE,
)
_RATED_HIGHLY_RE = re.compile(
    r"^Customers rated this pro highly for\s+(?P<reasons>.+)\.\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CDN_HOST = "production-next-images-cdn.thumbtack.com"
_CDN_URL_RE = re.compile(
    r"https://production-next-images-cdn\.thumbtack\.com/[^\s\"'<>\\]+",
    re.IGNORECASE,
)
_CDN_ID_RE = re.compile(
    r"https://production-next-images-cdn\.thumbtack\.com/i/(?P<id>\d+)",
    re.IGNORECASE,
)
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_SOCIAL_REDIRECT_RE = re.compile(
    r"^/websites/services/\d+/(?P<platform>[a-z]+)/redirect/?$",
    re.IGNORECASE,
)
_CRED_NAME_RE = re.compile(
    r"Background Check\s*\n+\s*(?P<name>[A-Za-z][A-Za-z .'-]+)\s*\n",
)
_TOP_PRO_YEAR_RE = re.compile(r"^(?P<year>20\d{2})\s*$", re.MULTILINE)
_HOUR_CHUNK_RE = re.compile(
    r"(?P<day>Sun|Mon|Tue|Wed|Thu|Fri|Sat)"
    r"(?:(?P<closed>Closed)"
    r"|(?P<from>\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(?P<to>\d{1,2}:\d{2}\s*[ap]m))",
    re.IGNORECASE,
)
_REVIEW_NAME_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z]\.?)?)\s*$"
)
_ABS_DATE_RE = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}$")
_REL_DATE_RE = re.compile(
    r"^(?:"
    r"yesterday"
    r"|a\s+day\s+ago"
    r"|\d+\s+days?\s+ago"
    r"|a\s+month\s+ago"
    r"|\d+\s+months?\s+ago"
    r")$",
    re.IGNORECASE,
)
_PLUS_MORE_RE = re.compile(r"^\+\d+\s+more$", re.IGNORECASE)
_FAQ_ITEM_RE = re.compile(
    r"^-\s+(?P<q>.+?)\s*\n+"
    r"(?P<a>(?:[ \t]+.+\n?)+)",
    re.MULTILINE,
)

_BODY_END_MARKERS = (
    "### Popular in",
    "### Related cost",
    "### You might also like",
    "### In other nearby areas",
    "\nCancelSearch",
)

_SERVICE_GROUP_HEADERS = frozenset(
    {
        "type of magic",
        "event type",
        "additional services",
        "music types",
        "music genres",
        "meal",
        "drinks and dessert",
    }
)

_DAY_TO_FIELD = {
    "sun": "sunday",
    "mon": "monday",
    "tue": "tuesday",
    "tues": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "thurs": "thursday",
    "fri": "friday",
    "sat": "saturday",
}
_RANGE_HOURS_RE = re.compile(
    r"^(?P<from>\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(?P<to>\d{1,2}:\d{2}\s*[ap]m)$",
    re.IGNORECASE,
)

_REVIEW_STOP_LINES = frozenset(
    {
        "credentials",
        "projects and media",
        "services offered",
        "message",
        "request a call",
    }
)


class ThumbtackProfileParser(VendorProfileParser):
    source_host = "thumbtack.com"

    def parse(
        self,
        page_url: str,
        markdown: str,
        *,
        html: str | None = None,
    ) -> VendorProfile:
        body = self._profile_body(markdown)
        header = self._parse_header(markdown, body)
        business_name = header.get("business_name")
        if not business_name:
            raise ValueError("business_name is required")

        url_meta = self._parse_url_meta(page_url)
        overview = self._parse_overview(body, html=html)
        services_info = self._parse_services(body)
        portfolio, profile_picture = self._parse_media(markdown, body, html=html)
        first_name, last_name = self._parse_credentials(body)
        location, service_area = self._build_location(
            url_meta, overview, header.get("zip")
        )

        business_type = header.get("business_type")
        breadcrumb_cat = self._parse_breadcrumb_category(markdown)
        primary = breadcrumb_cat or url_meta.get("category") or business_type
        categories = None
        if primary and business_type:
            categories = [
                Category(primary_category=primary, sub_category=business_type)
            ]
        elif primary:
            categories = [
                Category(primary_category=primary, sub_category=primary)
            ]

        return VendorProfile(
            business_name=business_name,
            slug=self.slug_from_url(page_url),
            first_name=first_name,
            last_name=last_name,
            business_type=business_type,
            tagline=header.get("tagline"),
            profile_picture=profile_picture,
            categories=categories,
            description=self._parse_about(body),
            services_provided=self._none_if_empty(
                services_info.get("services")
            ),
            genres_or_styles=self._none_if_empty(
                services_info.get("genres")
            ),
            reasons_to_book_me=self._parse_reasons(body),
            faqs=self._parse_faqs(body),
            years_in_business=overview.get("years"),
            logistic_details=overview.get("logistic_details"),
            location=location,
            service_area=service_area,
            weekly_hours=overview.get("weekly_hours"),
            booking_notes=self._parse_payment_notes(body),
            prices=header.get("prices"),
            price_range=header.get("price_range"),
            rating_average=header.get("rating_average"),
            reviews=self._parse_reviews(body),
            times_booked=overview.get("times_booked"),
            response_time=header.get("response_time"),
            verified_badges=self._none_if_empty(overview.get("badges")),
            awards=self._parse_awards(body, overview.get("badges") or []),
            social_media=self._parse_social(body),
            portfolio_files=portfolio,
        )

    # ------------------------------------------------------------------
    # Body / helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _profile_body(markdown: str) -> str:
        h1 = _H1_RE.search(markdown)
        start = h1.start() if h1 else 0
        end = len(markdown)
        for marker in _BODY_END_MARKERS:
            idx = markdown.find(marker, start)
            if 0 <= idx < end:
                end = idx
        # Also cut at the second "Request estimate" CTA that precedes footer.
        footer = markdown.find("\nRequest estimate\n\nThumbtack\n", start)
        if 0 <= footer < end:
            end = footer
        return markdown[start:end].strip()

    @staticmethod
    def _none_if_empty(items: list | None):
        if not items:
            return None
        return items

    @staticmethod
    def _parse_relative_date(text: str, *, today: date | None = None) -> date | None:
        cleaned = unescape(text or "").strip().lower()
        if not cleaned:
            return None
        today = today or date.today()
        if cleaned == "yesterday" or cleaned == "a day ago":
            return today - timedelta(days=1)
        m = re.match(r"^(\d+)\s+days?\s+ago$", cleaned)
        if m:
            return today - timedelta(days=int(m.group(1)))
        if cleaned == "a month ago":
            return today - timedelta(days=30)
        m = re.match(r"^(\d+)\s+months?\s+ago$", cleaned)
        if m:
            return today - timedelta(days=30 * int(m.group(1)))
        return None

    @classmethod
    def _parse_review_date(cls, text: str) -> date | None:
        parsed = parse_date(text)
        if parsed:
            return parsed
        return cls._parse_relative_date(text)

    # ------------------------------------------------------------------
    # URL / breadcrumb
    # ------------------------------------------------------------------

    @staticmethod
    def slug_from_url(page_url: str) -> str | None:
        return ThumbtackProfileParser._parse_url_meta(page_url).get("slug")

    @staticmethod
    def _parse_url_meta(page_url: str) -> dict:
        path = urlparse(page_url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        # /{st}/{city}/{category}/{slug}/service/{id}
        meta: dict = {}
        if len(parts) >= 6 and parts[-2] == "service":
            meta["state_code"] = parts[0].upper()
            meta["city"] = parts[1].replace("-", " ").title()
            meta["category"] = parts[2].replace("-", " ")
            meta["slug"] = parts[3]
        elif len(parts) >= 1:
            meta["slug"] = parts[-1]
        return meta

    @staticmethod
    def _parse_breadcrumb_category(markdown: str) -> str | None:
        match = _BREADCRUMB_CAT_RE.search(markdown)
        if not match:
            return None
        return clean_or_none(match.group("label"))

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _parse_header(self, markdown: str, body: str) -> dict:
        out: dict = {}
        h1 = _H1_RE.search(body) or _H1_RE.search(markdown)
        if h1:
            out["business_name"] = clean_or_none(h1.group("name"))

        # Tagline appears in chrome before H1.
        tag = _TAGLINE_RE.search(markdown)
        if tag:
            label = clean_or_none(tag.group("label"))
            zip_code = tag.group("zip")
            if label and zip_code:
                out["tagline"] = f"{label} • {zip_code}"
                out["business_type"] = label
                out["zip"] = zip_code
            elif label:
                out["business_type"] = label
                out["tagline"] = label

        # Rating near H1 — first Excellent/Exceptional line.
        head = body[:800]
        rating_match = _RATING_RE.search(head)
        if rating_match:
            try:
                out["rating_average"] = float(rating_match.group("rating"))
            except ValueError:
                pass

        price_match = _PRICE_BLOCK_RE.search(body)
        if price_match:
            money = parse_money(price_match.group("price"))
            if money:
                amount, per = money
                out["prices"] = [Price(amount=amount, per=per)]
                out["price_range"] = PriceRange(min_price=amount)

        resp = _RESPONSE_RE.search(body)
        if resp:
            out["response_time"] = clean_or_none(resp.group(0))

        return out

    # ------------------------------------------------------------------
    # About / payment / reasons
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_about(body: str) -> str | None:
        start = body.find("##### About")
        if start < 0:
            return None
        start = body.find("\n", start)
        if start < 0:
            return None
        start += 1
        end = body.find("\nOverview\n", start)
        if end < 0:
            end = body.find("\nServices offered\n", start)
        if end < 0:
            end = len(body)
        paras = paragraphs(body[start:end])
        return "\n\n".join(paras) if paras else None

    @staticmethod
    def _parse_payment_notes(body: str) -> list[str] | None:
        start = body.find("##### Payment methods")
        if start < 0:
            return None
        start = body.find("\n", start)
        if start < 0:
            return None
        start += 1
        end_markers = (
            "\nTop Pro status\n",
            "\nSocial media\n",
            "\nMessage\n",
            "\nServices offered\n",
            "\nOverview\n",
        )
        end = len(body)
        for marker in end_markers:
            idx = body.find(marker, start)
            if 0 <= idx < end:
                end = idx
        text = clean_or_none(body[start:end])
        if not text:
            return None
        # Collapse to a single note sentence.
        note = " ".join(paragraphs(text) or [text])
        return [note] if note else None

    @staticmethod
    def _parse_reasons(body: str) -> list[Highlight] | None:
        match = _RATED_HIGHLY_RE.search(body)
        if not match:
            return None
        reasons = clean_or_none(match.group("reasons"))
        if not reasons:
            return None
        return [
            Highlight(
                reason_heading="Customers rated this pro highly",
                reason_description=reasons,
            )
        ]

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    def _parse_overview(self, body: str, *, html: str | None = None) -> dict:
        overview_block = ""
        start = body.find("\nOverview\n")
        if start < 0:
            start = body.find("Overview\n")
        else:
            start += 1
        if start >= 0:
            start = body.find("\n", start) + 1
            end_markers = (
                "\n##### Payment methods\n",
                "\nSocial media\n",
                "\nServices offered\n",
                "\nMessage\n",
                "\nTop Pro status\n",
            )
            end = len(body)
            for marker in end_markers:
                idx = body.find(marker, start)
                if 0 <= idx < end:
                    end = idx
            overview_block = body[start:end]

        out: dict = {"badges": []}
        for raw in overview_block.splitlines():
            line = unescape(raw).strip()
            if not line:
                continue
            if line.lower() in {"background checked"}:
                out["badges"].append("Background checked")
                continue
            if line.lower() in {"current top pro", "top pro"}:
                badge = (
                    "Current Top Pro"
                    if "current" in line.lower()
                    else "Top Pro"
                )
                if badge not in out["badges"]:
                    out["badges"].append(badge)
                continue
            m = _HIRED_RE.match(line)
            if m:
                out["times_booked"] = int(m.group("n"))
                continue
            m = _SERVES_RE.match(line)
            if m:
                out["serves_city"] = clean_or_none(m.group("city"))
                out["serves_state"] = m.group("st").upper()
                continue
            m = _EMPLOYEES_RE.match(line)
            if m:
                out["logistic_details"] = LogisticDetails(
                    team_size=int(m.group("n"))
                )
                continue
            m = _YEARS_RE.match(line)
            if m:
                years = int(m.group("n"))
                out["years"] = YearsInBusiness(
                    start_year=date.today().year - years
                )
                continue

        # Prefer full week from HTML BusinessDaySummary; fall back to markdown.
        hours = self._parse_weekly_hours_html(html)
        if hours is None:
            hours = self._parse_weekly_hours(overview_block)
        if hours:
            out["weekly_hours"] = hours
        return out

    @classmethod
    def _parse_weekly_hours_html(cls, html: str | None) -> WeeklyHours | None:
        if not html or "BusinessDaySummary" not in html:
            return None
        text = html.replace("\\/", "/")
        fields: dict[str, DayAvailability] = {}
        # Each Apollo/GraphQL BusinessDaySummary chunk has day text then hours text.
        for chunk in text.split('"BusinessDaySummary"')[1:]:
            texts = re.findall(r'"text"\s*:\s*"([^"]+)"', chunk[:1200])
            if len(texts) < 2:
                continue
            day_raw = texts[0].strip()
            hours_raw = texts[1].strip()
            day_key = _DAY_TO_FIELD.get(day_raw.lower()) or _DAY_TO_FIELD.get(
                day_raw[:3].lower()
            )
            if not day_key:
                continue
            slot = cls._day_availability_from_hours_text(hours_raw)
            if slot is not None:
                fields[day_key] = slot
        return WeeklyHours(**fields) if fields else None

    @staticmethod
    def _day_availability_from_hours_text(hours_raw: str) -> DayAvailability | None:
        cleaned = clean_or_none(hours_raw)
        if not cleaned:
            return None
        if cleaned.lower() == "closed":
            return DayAvailability(isAvailable=False)
        match = _RANGE_HOURS_RE.match(cleaned)
        if not match:
            return None
        from_t = clean_or_none(match.group("from"))
        to_t = clean_or_none(match.group("to"))
        if not from_t or not to_t:
            return None
        return DayAvailability(
            isAvailable=True,
            availability=[TimeSlot(**{"from": from_t, "to": to_t})],
        )

    @classmethod
    def _parse_weekly_hours(cls, block: str) -> WeeklyHours | None:
        if re.search(
            r"hasn't listed their business hours",
            block,
            re.IGNORECASE,
        ):
            return None
        # Prefer the mashed line after "Business hours".
        hours_idx = block.lower().find("business hours")
        search_in = block[hours_idx:] if hours_idx >= 0 else block
        # Drop "Read more" noise.
        search_in = re.sub(r"Read more", "", search_in, flags=re.IGNORECASE)
        chunks = list(_HOUR_CHUNK_RE.finditer(search_in))
        if not chunks:
            return None
        fields: dict[str, DayAvailability] = {}
        for m in chunks:
            day_key = _DAY_TO_FIELD.get(m.group("day")[:3].lower())
            if not day_key:
                continue
            if m.group("closed"):
                fields[day_key] = DayAvailability(isAvailable=False)
            else:
                slot = cls._day_availability_from_hours_text(
                    f"{m.group('from')} - {m.group('to')}"
                )
                if slot is not None:
                    fields[day_key] = slot
        return WeeklyHours(**fields) if fields else None

    def _build_location(
        self,
        url_meta: dict,
        overview: dict,
        zip_code: str | None,
    ) -> tuple[Location | None, ServiceArea | None]:
        city = overview.get("serves_city") or url_meta.get("city")
        state_code = overview.get("serves_state") or url_meta.get("state_code")
        if not city and not state_code:
            return None, None

        state_name = None
        if state_code:
            state_name = STATE_CODE_TO_NAME.get(state_code.upper())
        raw = None
        if city and state_code:
            raw = f"{city}, {state_code}"
        elif city:
            raw = city

        location = Location(
            city=city,
            state=state_name,
            country=country_for_us_state(
                state=state_name, state_code=state_code
            ),
            raw_location=raw,
        )
        service_area = ServiceArea(
            city=city,
            state=state_name,
            state_code=state_code.upper() if state_code else None,
            service_pincode=zip_code,
        )
        return location, service_area

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_services(body: str) -> dict:
        start = body.find("\nServices offered\n")
        if start < 0:
            start = body.find("Services offered\n")
            if start < 0:
                return {}
        start = body.find("\n", start) + 1
        end_markers = (
            "\nProjects and media\n",
            "\nReviews\n",
            "\nCredentials\n",
        )
        end = len(body)
        for marker in end_markers:
            idx = body.find(marker, start)
            if 0 <= idx < end:
                end = idx
        block = body[start:end]

        groups: dict[str, list[str]] = {}
        current: str | None = None
        for raw in block.splitlines():
            line = unescape(raw).strip()
            if not line:
                continue
            if _PLUS_MORE_RE.match(line) or line.lower() == "show more":
                continue
            if line.lower() in _SERVICE_GROUP_HEADERS:
                current = line
                groups.setdefault(current, [])
                continue
            if current is None:
                # Unknown leading label — treat as a group header.
                current = line
                groups.setdefault(current, [])
                continue
            # If line looks like a new unknown header (short, no digits-heavy),
            # keep attaching as values; known headers already handled.
            groups[current].append(line)

        services: list[str] = []
        genres: list[str] = []
        seen_svc: set[str] = set()
        seen_gen: set[str] = set()
        for header, values in groups.items():
            target = genres if header.lower() == "music genres" else services
            seen = seen_gen if header.lower() == "music genres" else seen_svc
            for v in values:
                key = v.lower()
                if key in seen:
                    continue
                seen.add(key)
                target.append(v)
        return {"services": services, "genres": genres}

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def _parse_reviews(self, body: str) -> list[Review] | None:
        # Prefer the reviews section after services/media.
        start = body.find("\nReviews\n")
        if start < 0:
            return None
        start += 1
        end = body.find("\nCredentials\n", start)
        if end < 0:
            end = body.find("\n## FAQs\n", start)
        if end < 0:
            end = len(body)
        block = body[start:end]

        # Jump past histogram / mention tags to first review separator or name.
        sep = block.find("* * *")
        if sep >= 0:
            block = block[sep + 5 :]

        lines = [unescape(ln).strip() for ln in block.splitlines()]
        reviews: list[Review] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line or line == "•":
                i += 1
                continue
            if line.lower() in _REVIEW_STOP_LINES:
                break
            if not _REVIEW_NAME_RE.match(line):
                i += 1
                continue
            # Peek: next non-empty should be a date.
            j = i + 1
            while j < len(lines) and not lines[j]:
                j += 1
            if j >= len(lines):
                break
            date_line = lines[j]
            if not (_ABS_DATE_RE.match(date_line) or _REL_DATE_RE.match(date_line)):
                i += 1
                continue

            name = line
            review_date = self._parse_review_date(date_line)
            j += 1
            # Skip • and Hired on Thumbtack.
            while j < len(lines) and (
                not lines[j]
                or lines[j] == "•"
                or lines[j].lower() == "hired on thumbtack"
            ):
                j += 1

            body_lines: list[str] = []
            details: str | None = None
            while j < len(lines):
                cur = lines[j]
                if not cur:
                    j += 1
                    # Blank line inside body is fine; keep going unless next
                    # looks like a new review name+date.
                    continue
                if cur.lower().startswith("details:"):
                    details = clean_or_none(cur[len("Details:") :])
                    j += 1
                    break
                if cur.lower().endswith("'s reply") or cur.lower().endswith(
                    "’s reply"
                ):
                    break
                # Next review: name then date.
                if _REVIEW_NAME_RE.match(cur):
                    k = j + 1
                    while k < len(lines) and not lines[k]:
                        k += 1
                    if k < len(lines) and (
                        _ABS_DATE_RE.match(lines[k])
                        or _REL_DATE_RE.match(lines[k])
                    ):
                        break
                if cur.lower() in _REVIEW_STOP_LINES:
                    break
                # Trailing service category labels are usually short and
                # appear right after details; if we haven't started body yet
                # keep collecting.
                body_lines.append(cur)
                j += 1

            # Skip reply block if present.
            if j < len(lines) and (
                lines[j].lower().endswith("'s reply")
                or lines[j].lower().endswith("’s reply")
            ):
                j += 1
                while j < len(lines):
                    cur = lines[j]
                    if not cur:
                        j += 1
                        continue
                    if _REVIEW_NAME_RE.match(cur):
                        k = j + 1
                        while k < len(lines) and not lines[k]:
                            k += 1
                        if k < len(lines) and (
                            _ABS_DATE_RE.match(lines[k])
                            or _REL_DATE_RE.match(lines[k])
                        ):
                            break
                    if cur.lower() in _REVIEW_STOP_LINES:
                        break
                    # Skip until service-category one-liner then next review.
                    # Service labels: Magician, Personal Chef, etc.
                    j += 1
                    # If next is a review name, stop without consuming.
                    if j < len(lines) and _REVIEW_NAME_RE.match(lines[j]):
                        k = j + 1
                        while k < len(lines) and not lines[k]:
                            k += 1
                        if k < len(lines) and (
                            _ABS_DATE_RE.match(lines[k])
                            or _REL_DATE_RE.match(lines[k])
                        ):
                            break

            # Drop trailing service-category label from body if it looks like one.
            while body_lines and self._looks_like_service_label(body_lines[-1]):
                # Only drop if a Details line already captured OR body has more.
                if details or len(body_lines) > 1:
                    # Heuristic: single short line without sentence punctuation.
                    last = body_lines[-1]
                    if len(last) < 40 and "." not in last and "!" not in last:
                        body_lines.pop()
                        continue
                break

            text = clean_or_none("\n\n".join(body_lines))
            if details:
                detail_line = f"Details: {details}"
                text = f"{text}\n\n{detail_line}" if text else detail_line

            if name and text:
                reviews.append(
                    Review(
                        reviewer_name=name,
                        text=text,
                        review_date=review_date,
                        rating=None,
                    )
                )
            i = j

        return reviews or None

    @staticmethod
    def _looks_like_service_label(line: str) -> bool:
        lower = line.lower()
        if lower in {
            "magician",
            "personal chef",
            "music entertainment",
            "piano lessons",
            "violin lessons",
            "private chef events",
        }:
            return True
        # Short Title Case label without sentence end.
        if len(line) <= 40 and "." not in line and "!" not in line:
            words = line.split()
            if 1 <= len(words) <= 4 and words[0][:1].isupper():
                return True
        return False

    # ------------------------------------------------------------------
    # FAQs / credentials / awards / media / social
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_faqs(body: str) -> list[FAQ] | None:
        start = body.find("## FAQs")
        if start < 0:
            return None
        start = body.find("\n", start)
        if start < 0:
            return None
        start += 1
        end = len(body)
        for marker in ("\n### Popular", "\n### Related", "\nCancelSearch"):
            idx = body.find(marker, start)
            if 0 <= idx < end:
                end = idx
        block = body[start:end]
        # Cut at duplicated price CTA after FAQs.
        price_cta = _PRICE_BLOCK_RE.search(block)
        if price_cta:
            block = block[: price_cta.start()]
        faqs: list[FAQ] = []
        for order, match in enumerate(_FAQ_ITEM_RE.finditer(block)):
            title = clean_or_none(match.group("q"))
            raw_a = match.group("a")
            answer_lines = [
                unescape(ln).strip()
                for ln in raw_a.splitlines()
                if unescape(ln).strip()
            ]
            # Drop indented markers / Show more.
            answer_lines = [
                ln
                for ln in answer_lines
                if ln.lower() != "show more" and not ln.startswith("- ")
            ]
            content = clean_or_none(" ".join(answer_lines))
            if title and content:
                faqs.append(FAQ(title=title, content=content, order=order))
        return faqs or None

    @staticmethod
    def _parse_credentials(body: str) -> tuple[str | None, str | None]:
        # Prefer the Credentials section name.
        cred_idx = body.find("\nCredentials\n")
        search_in = body[cred_idx:] if cred_idx >= 0 else body
        match = _CRED_NAME_RE.search(search_in)
        if not match:
            return None, None
        full = clean_or_none(match.group("name"))
        if not full:
            return None, None
        parts = full.split(None, 1)
        if len(parts) == 1:
            return parts[0], None
        return parts[0], parts[1]

    @staticmethod
    def _parse_awards(body: str, badges: list[str]) -> list[str] | None:
        years: list[str] = []
        # Years listed under Top Pro icons, near "Top Pro status".
        top_idx = body.find("Top Pro status")
        search = body[top_idx : top_idx + 800] if top_idx >= 0 else ""
        for m in _TOP_PRO_YEAR_RE.finditer(search):
            y = m.group("year")
            if y not in years:
                years.append(y)
        if years:
            return [f"Thumbtack Top Pro {y}" for y in years]
        if any("top pro" in b.lower() for b in badges):
            return ["Thumbtack Top Pro"]
        return None

    @staticmethod
    def _normalize_cdn_url(url: str) -> str | None:
        """Keep portfolio CDN urls; drop chrome/icon variants."""
        raw = (url or "").strip().rstrip("\\").rstrip(",").rstrip(")")
        # Unescape JSON slash variants from embedded page state.
        raw = raw.replace("\\/", "/")
        if _CDN_HOST not in raw.lower():
            return None
        if not raw.lower().startswith("https://"):
            return None
        if "/desktop/standard/" in raw:
            return None
        # Drop query/hash noise.
        raw = raw.split("?", 1)[0].split("#", 1)[0]
        return raw

    @classmethod
    def _cdn_image_id(cls, url: str) -> str | None:
        match = _CDN_ID_RE.search(url)
        return match.group("id") if match else None

    @classmethod
    def _collect_cdn_urls(cls, text: str) -> list[str]:
        """Dedupe CDN images by /i/{id}/, preferring first occurrence."""
        urls: list[str] = []
        seen_ids: set[str] = set()
        seen_exact: set[str] = set()
        for match in _CDN_URL_RE.finditer(text or ""):
            url = cls._normalize_cdn_url(match.group(0))
            if not url:
                continue
            image_id = cls._cdn_image_id(url)
            if image_id:
                if image_id in seen_ids:
                    continue
                seen_ids.add(image_id)
            elif url in seen_exact:
                continue
            else:
                seen_exact.add(url)
            urls.append(url)
        return urls

    @classmethod
    def _parse_media(
        cls,
        markdown: str,
        body: str,
        *,
        html: str | None = None,
    ) -> tuple[list[PortfolioFile] | None, str | None]:
        # Prefer HTML: gallery assets live on the Thumbtack CDN and are often
        # missing from markdown (only hero + "See all (N)" there).
        urls: list[str] = []
        if html:
            # Also catch JSON-escaped urls (https:\/\/...).
            unescaped = html.replace("\\/", "/")
            urls = cls._collect_cdn_urls(unescaped)

        if not urls:
            # Markdown fallback: hero images near H1.
            h1 = _H1_RE.search(markdown)
            about_idx = markdown.find("##### About")
            if h1 and about_idx > h1.start():
                head = markdown[max(0, h1.start() - 1500) : about_idx]
            elif h1:
                head = markdown[max(0, h1.start() - 1500) : h1.start() + 400]
            else:
                about_in_body = body.find("##### About")
                head = body[:about_in_body] if about_in_body > 0 else body[:800]
            for m in _IMAGE_RE.finditer(head):
                alt = (m.group("alt") or "").lower()
                if "top pro" in alt:
                    continue
                url = cls._normalize_cdn_url(m.group("url"))
                if url:
                    urls.append(url)
            # Dedupe markdown fallback the same way.
            urls = cls._collect_cdn_urls("\n".join(urls)) if urls else []

        if not urls:
            return None, None
        files = [PortfolioFile(type="image", url=u) for u in urls]
        return files, urls[0]

    @staticmethod
    def _parse_social(body: str) -> list[SocialMediaLink] | None:
        links: list[SocialMediaLink] = []
        seen: set[str] = set()
        for m in _LINK_RE.finditer(body):
            raw = m.group("url")
            match = _SOCIAL_REDIRECT_RE.match(raw)
            if not match:
                continue
            platform = match.group("platform").lower()
            abs_url = urljoin("https://www.thumbtack.com", raw)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            links.append(
                SocialMediaLink(platform_type=platform, platform_url=abs_url)
            )
        return links or None
