"""Per-source vendor URL rules (regex classify now; scrape selectors later)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from utils.url import extract_website, strip_trailing_slash

TYPE_SINGLE_VENDOR = "single_vendor"
TYPE_VENDORS_DIRECTORY = "vendors_directory"
TYPE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class VendorSourceRules:
    source_url: str
    directory_url_re: re.Pattern[str]
    profile_url_re: re.Pattern[str]


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
    return (urlparse(origin).netloc or "").lower()


THEBASH_RULES = VendorSourceRules(
    source_url="https://www.thebash.com",
    directory_url_re=re.compile(
        r"^https?://(?:www\.)?thebash\.com/(services|search)/[a-z0-9-]+/?$"
    ),
    profile_url_re=re.compile(
        r"^https?://(?:www\.)?thebash\.com/[a-z0-9-]+/[a-z0-9-]+/?$"
    ),
)

GIGSALAD_RULES = VendorSourceRules(
    source_url="https://www.gigsalad.com",
    directory_url_re=re.compile(
        r"^https?://(?:www\.)?gigsalad\.com/"
        r"[A-Z][A-Za-z]*(-[A-Za-z]+)*"
        r"(/[A-Z][A-Za-z]*(-[A-Za-z]+)*)?"
        r"(/[A-Z]{2}/[A-Za-z0-9+]+)?/?$"
    ),
    profile_url_re=re.compile(
        r"^https?://(?:www\.)?gigsalad\.com/"
        r"[a-z0-9]+(?:[-_][a-z0-9]+)*_[a-z0-9-]*"
        r"(?:/contact)?/?$"
    ),
)

VENDOR_SOURCE_RULES: dict[str, VendorSourceRules] = {
    normalize_source_host(THEBASH_RULES.source_url): THEBASH_RULES,
    normalize_source_host(GIGSALAD_RULES.source_url): GIGSALAD_RULES,
}


def get_rules_for_url(page_url: str) -> VendorSourceRules | None:
    host = normalize_source_host(page_url)
    if not host:
        return None
    rules = VENDOR_SOURCE_RULES.get(host)
    if rules is not None:
        return rules
    if host.startswith("www."):
        return VENDOR_SOURCE_RULES.get(host[4:])
    return VENDOR_SOURCE_RULES.get(f"www.{host}")


def classify_url(rules: VendorSourceRules, url: str) -> str:
    if rules.directory_url_re.fullmatch(url):
        return TYPE_VENDORS_DIRECTORY
    if rules.profile_url_re.fullmatch(url):
        return TYPE_SINGLE_VENDOR
    return TYPE_UNKNOWN
