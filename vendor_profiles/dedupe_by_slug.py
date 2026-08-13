from __future__ import annotations

from vendor_profiles.parsers.registry import get_parser_for_url
from vendor_profiles.source_rules import normalize_source_host


def extract_slug(page_url: str) -> str | None:
    """Extract vendor slug using the same rules as structured extract parsers."""
    parser = get_parser_for_url(page_url)
    if parser is None:
        return None
    return parser.slug_from_url(page_url)


def dedupe_key(page_url: str) -> tuple[str, str] | None:
    """Return (host, slug) for dedupe, or None if either is missing."""
    host = normalize_source_host(page_url)
    slug = extract_slug(page_url)
    if not host or not slug:
        return None
    return (host, slug)


def partition_keepers_and_duplicates(
    page_urls: list[str],
) -> tuple[list[str], list[str]]:
    """Walk URLs in order; first (host, slug) wins. No key → keeper."""
    seen: set[tuple[str, str]] = set()
    keepers: list[str] = []
    duplicates: list[str] = []
    for page_url in page_urls:
        key = dedupe_key(page_url)
        if key is None:
            keepers.append(page_url)
            continue
        if key in seen:
            duplicates.append(page_url)
        else:
            seen.add(key)
            keepers.append(page_url)
    return keepers, duplicates
