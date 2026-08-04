"""Per-source vendor URL rules (regex classify now; scrape selectors later)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from utils.url import clean_page_url, extract_website, strip_trailing_slash

TYPE_SINGLE_VENDOR = "profile"
TYPE_VENDORS_DIRECTORY = "directory"
TYPE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class VendorSourceRules:
    source_url: str
    directory_url_re: re.Pattern[str]
    profile_url_re: re.Pattern[str]


# First path segment on thebash.com that is never a vendor profile.
_THEBASH_NON_VENDOR_FIRST_SEGMENTS = frozenset(
    {
        "services",
        "search",
        "articles",
        "themes",
        "events",
        "login",
        "signup",
        "gigkids",
        "virtual-event-services",
        "event-inspiration",
        "musical-entertainment",
        "variety-act-landing",
        "speakers",
        "event-services",
        "guarantee",
        "about",
        "help",
        "venues",
        "contact",
        "terms-of-use",
        "ai-terms",
        "ai-usage-policy",
    }
)
_THEBASH_NON_VENDOR_FIRST_ALT = "|".join(
    sorted(_THEBASH_NON_VENDOR_FIRST_SEGMENTS, key=len, reverse=True)
)


# For each domain: (profile_regex, directory_regex)
# All patterns match urlparse(url).path only (classify_url never tests the full URL).
PATTERNS = {
    "thebash.com": {
        # /blues-band/ellie-d-soul-mix — exclude nav/listing first segments
        "profile": re.compile(
            rf"^/(?!(?:{_THEBASH_NON_VENDOR_FIRST_ALT})/)"
            r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*/?$"
        ),
        # /search/acrobat-denver-co
        "directory": re.compile(r"^/search/[a-z0-9]+(?:-[a-z0-9]+)*/?$"),
    },
    "gigsalad.com": {
        # /chuck_roy_denver, /leah_althoff_stand_up_comedy_denver, /matt_cobos_denver/contact
        "profile": re.compile(
            r"^/[a-z0-9]+(?:[-_][a-z0-9]+)*(?:/contact)?/?$",
            re.IGNORECASE,
        ),
        # /Comedians-Emcees/Stand-Up-Comedians/CO/Denver
        "directory": re.compile(
            r"^/[A-Za-z0-9-]+/[A-Za-z0-9-]+/[A-Z]{2}/[A-Za-z0-9-]+/?$"
        ),
    },
    "partyslate.com": {
        # /vendors/good-musicians
        "profile": re.compile(r"^/vendors/[a-z0-9]+(?:-[a-z0-9]+)+/?$"),
        # /find-vendors/event-entertainment/area/denver, /find-venues/corporate-event-venues/near/denver-co-usa/types/museum
        "directory": re.compile(
            r"^/find-(?:vendors|venues)/[a-z0-9-]+(?:/[a-z0-9-]+)*/?$"
        ),
    },
    "theknot.com": {
        # /marketplace/steve-shurack-denver-co-490736  (ends in -digits)
        "profile": re.compile(r"^/marketplace/[a-z0-9]+(?:-[a-z0-9]+)*-\d+/?$"),
        # /marketplace/live-wedding-bands-denver-co  (ends in 2-letter state code)
        "directory": re.compile(r"^/marketplace/[a-z]+(?:-[a-z]+)*-[a-z]{2}/?$"),
    },
    "zola.com": {
        # /wedding-vendors/wedding-bands-djs/nexus-strings
        "profile": re.compile(
            r"^/wedding-vendors/(?!search/)[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)+/?$"
        ),
        # /wedding-vendors/search/denver-co--wedding-bands-djs
        "directory": re.compile(r"^/wedding-vendors/search/[a-z0-9-]+/?$"),
    },
    "weddingwire.com": {
        # /biz/great-family-artists/8badbbfd76385de2.html
        # /reviews/great-family-artists/8badbbfd76385de2.html
        "profile": re.compile(
            r"^/(?:biz|reviews)/[a-z0-9]+(?:-[a-z0-9]+)+/[0-9a-f]+\.html$"
        ),
        # /c/co-colorado/.../wedding-ceremony-music/751-4-rca.html
        # /c/co-colorado/denver/wedding-ceremony-music/4-vendors.html
        "directory": re.compile(
            r"^/c/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+/\d+(?:-\d+-rca|-vendors)\.html$"
        ),
    },
    "thumbtack.com": {
        # /co/littleton/bands-for-hire/charlie-z-denver-jazz-quartet/service/484077481175605256
        "profile": re.compile(
            r"^/[a-z]{2}/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+/service/\d+/?$"
        ),
        # /co/denver/solo-musician-for-hire
        "directory": re.compile(r"^/[a-z]{2}/[a-z0-9-]+/[a-z0-9-]+/?$"),
    },
    "eventective.com": {
        # UNVERIFIED — no eventective profile URL has appeared in any data pull yet
        "profile": re.compile(r"^/[A-Za-z0-9-]+(?:/[A-Za-z0-9-]+)?\.html$"),
        # /las-vegas-nv/entertainers/
        "directory": re.compile(r"^/[a-z0-9-]+/[a-z0-9-]+/?$"),
    },
}


def _ensure_scheme(url: str) -> str:
    text = url.strip()
    if not text:
        return text
    parsed = urlparse(text)
    if not parsed.scheme:
        return f"https://{text}"
    return text


def normalize_source_host(url: str) -> str:
    """Lowercased host — ignores scheme, path, query, trailing slashes."""
    with_scheme = _ensure_scheme(url)
    cleaned = strip_trailing_slash(with_scheme.split("?", 1)[0].split("#", 1)[0])
    origin = extract_website(cleaned)
    host = (urlparse(origin).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


VENDOR_SOURCE_RULES: dict[str, VendorSourceRules] = {
    domain: VendorSourceRules(
        source_url=f"https://www.{domain}",
        directory_url_re=rules["directory"],
        profile_url_re=rules["profile"],
    )
    for domain, rules in PATTERNS.items()
}


def get_rules_for_url(
    page_url: str,
) -> VendorSourceRules | dict[str, re.Pattern[str]] | None:
    host = normalize_source_host(page_url)
    if not host:
        return None
    return PATTERNS.get(host)


def classify_url(
    arg1: VendorSourceRules | dict[str, re.Pattern[str]] | str, arg2: str | None = None
) -> str:
    """Classify a URL as 'profile', 'directory', 'unknown_source', or 'unmatched'.

    Supports both:
    - classify_url(url: str)
    - classify_url(rules, url: str)
    """
    if arg2 is None:
        url = str(arg1)
    else:
        url = arg2

    parsed = urlparse(_ensure_scheme(url))
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip() or "/"
    rules = PATTERNS.get(host)
    if not rules:
        return "unknown_source"
    if rules["profile"].match(path):
        return "profile"
    if rules["directory"].match(path):
        return "directory"
    return "unmatched"


def extract_vendor_profile_urls(
    page_url: str,
    all_links: list[str],
    markdown: str | None = None,
) -> list[str]:
    """Extract single vendor profile URLs from a directory page using domain classification rules."""
    candidates: list[str] = list(all_links)

    if markdown:
        md_links = re.findall(
            r"\[(?:[^\]]*)\]\((https?://[^\s\)]+|/[^\s\)]+)\)", markdown
        )
        candidates.extend(md_links)

    profile_urls: list[str] = []
    seen: set[str] = set()

    for raw in candidates:
        if not raw or not isinstance(raw, str):
            continue
        raw_cleaned = raw.strip()
        if not raw_cleaned:
            continue
        full_url = urljoin(page_url, raw_cleaned)
        cleaned = clean_page_url(full_url)
        if not cleaned or cleaned in seen:
            continue
        url_type = classify_url(cleaned)
        if url_type in (TYPE_SINGLE_VENDOR, "profile"):
            seen.add(cleaned)
            profile_urls.append(cleaned)

    return profile_urls
